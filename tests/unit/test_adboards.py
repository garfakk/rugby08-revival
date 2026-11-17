"""Adboard sets: the nine-board grounds (Castres, Le Parc, Perpignan, La
Beaujoire) look up ads7/ads8, so every set the game can be given has them
(backend.mod_utils.complete_adboards)."""
import glob
import os

import pytest

from backend.mod_utils import build_fsh, complete_adboards, extract_asset_from_fsh_file, fsh_entries

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
STATIC_WC = os.path.join(ROOT, "src", "assets", "static_files", "485c3bef5972390ec66b2ff013c45d14.fsh")


def _seven_board_set():
    entries = [(f"ads{i}", b"\x60" + b"\0" * 3 + (256).to_bytes(2, "little") * 2 + b"\0" * 8
                + bytes([i]) * (256 * 256 // 2)) for i in range(7)]
    return build_fsh(b"G359", entries)


def test_build_fsh_round_trips():
    data = _seven_board_set()
    assert [t for t, _ in fsh_entries(data)] == [f"ads{i}" for i in range(7)]
    assert build_fsh(data[12:16], fsh_entries(data)) == data


def test_missing_boards_copied_from_their_twins():
    data = _seven_board_set()
    full = dict(fsh_entries(complete_adboards(data)))
    assert sorted(full) == [f"ads{i}" for i in range(9)]
    assert full["ads7"] == full["ads4"] and full["ads8"] == full["ads5"]
    assert dict(fsh_entries(complete_adboards(data, {"ads7": full["ads0"]})))["ads7"] == full["ads0"]


def test_a_full_set_is_left_as_it_is():
    full = complete_adboards(_seven_board_set())
    assert complete_adboards(full) is full


@pytest.mark.parametrize("path", [STATIC_WC] + sorted(glob.glob(
    os.path.join(ROOT, "data", "competitions", "**", "adboards.fsh"), recursive=True)))
def test_shipped_adboards_have_nine_boards(path):
    if not os.path.isfile(path):
        pytest.skip("not in this checkout")
    tags = [t for t, _ in fsh_entries(open(path, "rb").read())]
    assert set(tags) >= {f"ads{i}" for i in range(9)}
    for i in range(len(tags)):
        extract_asset_from_fsh_file(path, i)          # every board decodes


# ── ad sets built for each stadium layout (backend/adboards.py) ─────────────
import re
import struct

from PIL import Image

from backend import adboards as AB
from backend import game_files_processor as GFP
from conftest import point_config

STD_TEMPLATE = os.path.join(ROOT, "src", "assets", "stock_game", "adboards_standard.fsh")


def _templates():
    return open(STATIC_WC, "rb").read(), open(STD_TEMPLATE, "rb").read()


def _sizes(data):
    return [(t, struct.unpack_from("<HH", b, 4)) for t, b in fsh_entries(data)]


def _band_colours(data, tag):
    image = dict(fsh_entries(data))[tag]
    from backend.mod_utils import fsh_entry_image
    im = fsh_entry_image(image).convert("RGB")
    return [im.getpixel((im.width // 2, y)) for y in (20, 100, 200)]


def test_default_set_keeps_the_world_cup_file_and_fits_the_standard_layout():
    wc, std = _templates()
    out = AB.build_all(AB.from_fsh(wc), wc, std)
    assert out[AB.game_filename(AB.WC_NAME)] == wc
    built = out[AB.game_filename(AB.STD_NAME)]
    assert _sizes(built) == _sizes(std)               # same boards, same sizes, frame included
    boards, stock = dict(fsh_entries(built)), dict(fsh_entries(std))
    assert boards["ads3"] == stock["ads3"]            # the frame is never an ad
    assert boards["ads0"] != stock["ads0"]            # the ads are the World Cup ones


def test_standard_set_gives_the_world_cup_strips_their_shape():
    wc, std = _templates()
    out = AB.build_all(AB.from_fsh(std), wc, std)
    assert _sizes(out[AB.game_filename(AB.WC_NAME)]) == _sizes(wc)
    assert _sizes(out[AB.game_filename(AB.STD_NAME)]) == _sizes(std)


def test_pictures_become_ads_on_every_board(tmp_path):
    wc, std = _templates()
    colours = [(200, 0, 0), (0, 200, 0), (0, 0, 200)]
    for i, c in enumerate(colours):
        Image.new("RGB", (300, 100), c).save(tmp_path / f"ad{i}.png")
    out = AB.build_all(AB.load_set(str(tmp_path)), wc, std)
    for name in (AB.WC_NAME, AB.STD_NAME):
        got = _band_colours(out[AB.game_filename(name)], "ads0")
        assert [tuple(round(v / 40) for v in c) for c in got] == \
            [tuple(round(v / 40) for v in c) for c in colours]
    strip = _band_colours(out[AB.game_filename(AB.WC_NAME)], "ads2")
    assert strip[0][0] > 150 and strip[1][1] > 150      # the strips carry them too


def test_boards_named_in_a_folder_replace_those_of_the_fsh(tmp_path):
    wc, std = _templates()
    (tmp_path / "set.fsh").write_bytes(wc)
    Image.new("RGB", (256, 256), (0, 0, 255)).save(tmp_path / "ads1.png")
    out = AB.build(wc, AB.load_set(str(tmp_path)))
    boards, stock = dict(fsh_entries(out)), dict(fsh_entries(wc))
    assert boards["ads0"] == stock["ads0"] and boards["ads1"] != stock["ads1"]
    assert _band_colours(out, "ads1")[0][2] > 150


def test_an_empty_folder_is_no_set(tmp_path):
    with pytest.raises(ValueError):
        AB.load_set(str(tmp_path))


def test_stadium_xml_names_one_file_per_layout():
    xml = open(os.path.join(ROOT, "src", "assets", "static_files",
                            "456c6d548b2e7a8a1d9c7016d63d7bfe.xml"), encoding="latin-1").read()
    stadiums = re.findall(r'<stadium name="([^"]+)">(.*?)</stadium>', xml, re.S)
    assert len(stadiums) >= 89
    names = {re.search(r'(?<![A-Za-z])ads="([^"]+)"', body).group(1) for _, body in stadiums}
    assert names == {"World_Cup\\World_Cup", "Standard\\France_Standard"}
    family = {n: re.search(r'(?<![A-Za-z])ads="([^"]+)"', b).group(1) for n, b in stadiums}
    assert family["millenium.day"] == family["castres.night"] == "World_Cup\\World_Cup"
    assert family["twickenham.day"] == family["auckland.day"] == "Standard\\France_Standard"


def test_deploy_writes_both_layout_files(tmp_path, monkeypatch):
    data, game = tmp_path / "data", tmp_path / "game"
    (data / "adboards" / "mine").mkdir(parents=True)
    game.mkdir()
    Image.new("RGB", (300, 100), (200, 0, 0)).save(data / "adboards" / "mine" / "a.png")
    point_config(monkeypatch, data_dir=str(data), game_dir=str(game))
    names = {AB.game_filename(AB.WC_NAME), AB.game_filename(AB.STD_NAME)}
    GFP.deploy_adboards({"adboards": "adboards/mine"})
    assert {p.name for p in game.iterdir()} == names
    assert _band_colours((game / AB.game_filename(AB.STD_NAME)).read_bytes(), "ads0")[0][0] > 150
    GFP.deploy_adboards({"adboards": "adboards/missing"})        # unusable: the default set
    wc = open(STATIC_WC, "rb").read()
    assert (game / AB.game_filename(AB.WC_NAME)).read_bytes() == wc


def test_library_ad_sets_are_listed(tmp_path, monkeypatch):
    from app import dressing
    lib = tmp_path / "data" / "ingame_graphics" / "ads"
    (lib / "pics").mkdir(parents=True)
    point_config(monkeypatch, data_dir=str(tmp_path / "data"), game_dir=str(tmp_path))
    for i in range(2):
        Image.new("RGB", (60, 20), (i * 90, 0, 0)).save(lib / "pics" / f"ad{i}.png")
    (lib / "solo.fsh").write_bytes(open(STATIC_WC, "rb").read())
    labels = [o["label"] for o in dressing.library_sets("ads")]
    assert labels == ["Pics", "Solo"]
    assert AB.load_ref("ingame_graphics/ads/pics").layout == "wc"
    assert AB.load_ref("dressing/ads/pics").layout == "wc"     # a reference saved before the move
