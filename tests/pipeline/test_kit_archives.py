"""Kits shipped as the game's own files (a .big front, a .fsh of the 22
backs) instead of images: decoded for everything that needs pictures, given
to the game as they are, shirt names lettered onto the named backs only."""
import os
import shutil

import pytest
from PIL import Image

from app.game_data import ASSET_SPECS
from app.match_data_builder import build_match_data
from backend import game_specific_variables as gsv
from backend import mod_utils as M
from shared import kit_files as KF
from shared.config import config
from ui.editor_kit import asset_status
from conftest import make_match_config

pytestmark = pytest.mark.slow


@pytest.fixture
def archives(tmp_path):
    """front.big / back.fsh made from the mod's templates (back 5 painted
    red, so the decode can be checked)."""
    T = config.templates_directory
    shutil.copy(os.path.join(T, "kit_front.big"), tmp_path / "front.big")
    shutil.copy(os.path.join(T, "kit_back.fsh"), tmp_path / "back.fsh")
    assert M.replace_asset_in_fsh_file(str(tmp_path / "back.fsh"),
                                       Image.new("RGBA", (256, 256), (255, 0, 0, 255)), index=4)
    return tmp_path


def test_archives_decode_to_images(archives):
    front = KF.front_file(str(archives / "front.big"))
    assert front.endswith(".png") and Image.open(front).size[0] > 0
    pattern = KF.back_pattern(str(archives / "back.fsh"))
    assert "%" in pattern
    assert all(os.path.isfile(pattern.replace("%", str(n))) for n in range(1, 23))
    assert Image.open(KF.back_file(str(archives / "back.fsh"), 5)).convert("RGB").getpixel((9, 9)) \
        == (255, 0, 0)
    assert KF.archive_frame_count(str(archives / "back.fsh")) == 22
    # images are untouched by all this
    assert KF.front_file("kits/home_front.webp") == "kits/home_front.webp"


def test_archive_status(archives):
    assert asset_status(str(archives), "front.big", ASSET_SPECS["frontKitFile"])[0] == "ok"
    assert asset_status(str(archives), "back.fsh", ASSET_SPECS["backKitFile"])[:2] == \
        ("ok", "FSH · 22 entries")
    entries = M.fsh_entries((archives / "back.fsh").read_bytes())
    (archives / "short.fsh").write_bytes(M.build_fsh(b"G359", entries[:3]))
    assert asset_status(str(archives), "short.fsh", ASSET_SPECS["backKitFile"])[0] == "partial"
    (archives / "junk.fsh").write_bytes(b"not an fsh")
    assert asset_status(str(archives), "junk.fsh", ASSET_SPECS["backKitFile"])[0] == "bad"
    assert KF.back_pattern(str(archives / "junk.fsh")) == ""
    assert KF.front_file(str(archives / "junk.fsh")) == ""


def _game_kit(game_dir, key):
    return os.path.join(game_dir, gsv.game_filenames["team_A"][key])


def test_game_gets_the_archives(ds, archives, run_kits, game_dir):
    run_kits(ds, archives, names=False)
    assert open(_game_kit(game_dir, "kit_front"), "rb").read() == (archives / "front.big").read_bytes()
    assert open(_game_kit(game_dir, "kit_back"), "rb").read() == (archives / "back.fsh").read_bytes()


def test_shirt_names_on_an_fsh_back(ds, archives, run_kits, game_dir):
    md = run_kits(ds, archives, names=True)
    names = md["team_A"]["shirt_names"]["names"]
    assert sum(1 for n in names[:22] if n) > 10
    source = M.fsh_entries((archives / "back.fsh").read_bytes())
    written = M.fsh_entries(open(_game_kit(game_dir, "kit_back"), "rb").read())
    assert len(written) == len(source) == 22
    for i, (old, new) in enumerate(zip(source, written)):
        assert len(old[1]) == len(new[1])                   # layout kept
        assert (old != new) == bool(i < len(names) and names[i]), i


@pytest.fixture
def run_kits(game_dir, monkeypatch):
    monkeypatch.setattr(M, "ensure_wine_d3d8_native_override", lambda *a, **k: None)
    monkeypatch.setattr(M, "disable_wine_virtual_desktop", lambda *a, **k: None)
    os.makedirs(os.path.join(game_dir, "Data"), exist_ok=True)
    from backend.start_match import start_match

    def run(ds, archives, names):
        if names:
            ds.teams["10002"]["2024"]["shirtNames"] = {"enabled": True, "text": "surname",
                                                       "font": "Oswald"}
        md = build_match_data(ds, make_match_config(ds))
        md["team_A"]["kit_front"] = str(archives / "front.big")   # absolute: joined as is
        md["team_A"]["kit_back"] = str(archives / "back.fsh")
        assert start_match(md, start_R08=False) is None
        return md
    return run
