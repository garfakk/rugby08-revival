"""Stadium dressing: pads / posts sets (image folders) built into the game's
pads-and-flags file, stock references read from the game, and who decides
which set a match wears (backend/stadium_dressing.py, app/dressing.py)."""
import hashlib
import os
import struct

from PIL import Image

from backend import game_files_processor as GFP
from backend import game_specific_variables as gsv
from backend import mod_utils as mu
from backend import stadium_dressing as SD
from conftest import point_config

TEMPLATE = open(SD.template_path(), "rb").read()


def _tags(data):
    return [t for t, _ in mu.fsh_entries(data)]


def test_template_rebuilt_from_its_own_images_is_unchanged():
    images = SD.preview_images("", "")
    out = SD.build(images, images, TEMPLATE)
    for (tag, a), (_, b) in zip(mu.fsh_entries(TEMPLATE), mu.fsh_entries(out)):
        assert a[:16] == b[:16] and len(a) == len(b), tag


def test_sets_replace_their_textures_only():
    pads = {"pada": Image.new("RGBA", (100, 300), (200, 0, 0, 255))}
    posts = {"post": Image.new("RGBA", (32, 32), (0, 0, 255, 255)),
             "pada": Image.new("RGBA", (8, 8), "green")}         # not a posts texture: ignored
    out = SD.build(pads, posts, TEMPLATE)
    assert _tags(out) == _tags(TEMPLATE)
    blocks, stock = dict(mu.fsh_entries(out)), dict(mu.fsh_entries(TEMPLATE))
    word, w, h = struct.unpack_from("<IHH", blocks["pada"], 0)
    assert (word & 0xFF, w, h) == (mu.FSH_CODE_DXT1, 128, 512)       # powers of two
    assert mu.fsh_entry_image(blocks["pada"]).getpixel((5, 5))[:3][0] > 180
    assert mu.fsh_entry_image(blocks["post"]).getpixel((5, 5))[2] > 200
    for tag in ("padb", "flag", "flgp", "xbar"):
        assert blocks[tag] == stock[tag]


def test_mipmapped_texture_keeps_its_mip_count():
    out = SD.build({"flgp": Image.new("RGBA", (64, 256), "red")}, {}, TEMPLATE)
    block = dict(mu.fsh_entries(out))["flgp"]
    stock = dict(mu.fsh_entries(TEMPLATE))["flgp"]
    assert block[15] >> 4 == stock[15] >> 4 == 6
    word, w, h = struct.unpack_from("<IHH", block, 0)
    size = sum(mu._fsh_pixel_data_size(word & 0xFF, max(1, w >> i), max(1, h >> i)) for i in range(7))
    assert len(block) >= 16 + size


def test_set_folders_round_trip(tmp_path):
    images = {"pada": Image.new("RGBA", (64, 256), "red"), "flag": Image.new("RGBA", (128, 64), "blue")}
    SD.save_set(images, str(tmp_path / "p"), "pads")
    assert sorted(os.listdir(tmp_path / "p")) == ["flag.png", "pad_wrap.png"]
    loaded = SD.load(str(tmp_path / "p"), "pads")
    assert sorted(loaded) == ["flag", "pada"]
    assert SD.load(str(tmp_path / "p"), "posts") == {}


def test_stock_reference_read_from_the_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(SD, "_cache_dir", lambda: str(tmp_path))
    game_path = SD.stock_game_path("stock:standard/twickenham")
    assert game_path == "stadiums/pads_and_flags/standard/twickenham"
    name = hashlib.md5(game_path.encode()).hexdigest() + ".fsh"
    assert name == "2e10208edab624f24f814a1817235c91.fsh"
    (tmp_path / name).write_bytes(TEMPLATE)
    assert sorted(SD.load("stock:standard/twickenham", "posts")) == ["post", "xbar"]
    assert SD.stock_game_path("stock:world_cup/world_cup", "ads") == "stadiums/adboards/world_cup/world_cup"
    assert SD.stock_game_path("dressing/pads/x") is None


def test_deploy_pads_writes_the_game_file(tmp_path, monkeypatch):
    data, game = tmp_path / "data", tmp_path / "game"
    game.mkdir()
    SD.save_set({"post": Image.new("RGBA", (32, 32), (0, 0, 255, 255))},
                str(data / "dressing" / "posts" / "blue"), "posts")
    point_config(monkeypatch, data_dir=str(data), game_dir=str(game))
    GFP.deploy_pads({"pads": "", "posts": "dressing/posts/blue"})
    out = (game / gsv.game_filenames["stadium_graphics"]).read_bytes()
    assert mu.fsh_entry_image(dict(mu.fsh_entries(out))["post"]).getpixel((4, 4))[2] > 200


def test_every_stock_slot_has_stock_sets_that_exist():
    for game_id, entry in gsv.STOCK_DRESSING.items():
        assert game_id in gsv.STADIUM_SLOTS
        assert entry["pads"] in gsv.STOCK_PADS
        assert entry["ads"] in gsv.STOCK_ADS


class _Cfg:
    def __init__(self, stadium, **picks):
        self.stadium = {"stadium_id": stadium.get("game_id"), "data": stadium}
        self.pads = picks.get("pads")
        self.posts = picks.get("posts")
        self.adboards = picks.get("adboards")


def test_resolve_pick_then_stadium_json_then_stock():
    from app import dressing
    twickenham = {"game_id": 14}
    assert dressing.resolve(_Cfg(twickenham), "pads") == "stock:standard/twickenham"
    assert dressing.resolve(_Cfg(twickenham), "posts") == "stock:standard/twickenham"
    assert dressing.resolve(_Cfg(twickenham), "ads") == "stock:scrolling/england_scrolling"
    own = {"game_id": 70, "dressing": {"pads": "dressing/pads/racing"}}
    assert dressing.resolve(_Cfg(own), "pads") == "dressing/pads/racing"
    assert dressing.resolve(_Cfg(own), "ads") == "stock:world_cup/france_nonwc"
    picked = _Cfg(own, pads="competitions/top_14/assets/pads")
    assert dressing.resolve(picked, "pads") == "competitions/top_14/assets/pads"
    assert dressing.resolve(_Cfg({}), "pads") == ""


def test_competition_seasons_sharing_a_set_share_an_entry(tmp_path, monkeypatch):
    from app import dressing
    point_config(monkeypatch, data_dir=str(tmp_path))
    comp = tmp_path / "competitions" / "six"
    for name in ("modern", "2018"):
        (comp / "p" / name).mkdir(parents=True)

    class DS:
        tournaments = {"six": {"2019": {"name": "Six", "pads": "p/modern"},
                               "2020": {"name": "Six", "pads": "p/modern"},
                               "2018": {"name": "Six", "pads": "p/2018"},
                               "2021": {"name": "Six", "pads": "p/missing"}}}
        tournaments_folder_path = {"six": str(comp)}

    sets = dressing.competition_sets(DS, "pads")
    assert sorted((o["label"], o["ref"]) for o in sets) == [
        ("Six 2018", "competitions/six/p/2018"), ("Six 2019–2020", "competitions/six/p/modern")]


def test_suggestions_are_the_stadium_and_the_teams_competitions(tmp_path, monkeypatch):
    from app import dressing
    point_config(monkeypatch, data_dir=str(tmp_path))
    comp = tmp_path / "competitions" / "t14"
    for name, colour in (("a", "red"), ("b", "blue")):
        SD.save_set({"pada": Image.new("RGBA", (64, 256), colour)}, str(comp / "sets" / name), "pads")
    monkeypatch.setattr(dressing, "look", lambda ref, kind: ref or None)
    monkeypatch.setattr(dressing, "_TEMPLATES", [
        ("t14", "", {"1"}, set()),               # lists team 1
        ("pro", "2020", set(), {"pro d2"}),      # takes Pro D2 clubs
        ("other", "", {"9"}, set())])

    class DS:
        tournaments = {"t14": {"": {"pads": "sets/a"}}, "pro": {"2020": {"pads": "sets/b"}},
                       "other": {"": {"pads": "sets/a"}}}
        tournaments_folder_path = {"t14": str(comp), "pro": str(comp), "other": str(comp)}

    teams = [("1", {"category": "Top 14"}), ("2", {"category": "Pro D2"})]
    refs = dressing.suggested_refs(DS, "pads", teams, {"game_id": 14}, {"game_id": 70})
    assert refs == ["stock:standard/twickenham", "competitions/t14/sets/b",
                    "competitions/t14/sets/a", "stock:standard/stade_de_france"]
    options = dressing.choices(DS, "pads", None, {"game_id": 14}, refs)
    assert options[0]["ref"] == "" and options[0]["label"] == "Default"
    assert options[0]["default_ref"] == "stock:standard/twickenham"
    flagged = [o["ref"] for o in options if o.get("suggested")]
    assert flagged == ["", "competitions/t14/sets/b", "competitions/t14/sets/a",
                       "stock:standard/stade_de_france"]
    assert len({o["ref"] for o in options}) == len(options)     # no set listed twice


def test_sets_that_look_alike_are_listed_once(tmp_path, monkeypatch):
    from app import dressing
    point_config(monkeypatch, data_dir=str(tmp_path))
    lib = tmp_path / "dressing" / "posts"
    bar = Image.new("RGBA", (16, 16), (240, 240, 240, 255))
    bar.paste((20, 35, 95, 255), (8, 0, 16, 16))
    for name in ("a", "b"):           # the same white post and navy band
        SD.save_set({"post": Image.new("RGBA", (32, 32), "white"), "xbar": bar}, str(lib / name), "posts")
    SD.save_set({"post": Image.new("RGBA", (32, 32), "white"),
                 "xbar": Image.new("RGBA", (16, 16), "white")}, str(lib / "plain"), "posts")
    monkeypatch.setattr(dressing, "stock_sets", lambda kind: [])

    class DS:
        tournaments, tournaments_folder_path = {}, {}

    options = dressing.choices(DS, "posts")
    assert [o["label"] for o in options] == ["Default", "White · navy", "White"]
    assert options[1]["refs"] == ["dressing/posts/a", "dressing/posts/b"]
    # a pick folded into another entry still selects that entry
    assert any("dressing/posts/b" in o["refs"] for o in dressing.choices(
        DS, "posts", current="dressing/posts/b"))
