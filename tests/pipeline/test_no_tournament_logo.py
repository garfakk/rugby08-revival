"""Quick match starts with no pitch logo and no tournament logo: "none"
gives the game a blank (fully transparent) tournament logo, not the
template's nor the home team's."""
import os

import pytest

from app.match_data_builder import build_match_data
from backend import game_specific_variables as gsv
from backend import mod_utils as M
from conftest import make_match_config

pytestmark = pytest.mark.slow


def test_quick_match_defaults():
    from app.state import MatchConfig
    assert MatchConfig().pitch_logo_choice == "none"


def test_none_writes_a_blank_logo(ds, game_dir, monkeypatch):
    monkeypatch.setattr(M, "ensure_wine_d3d8_native_override", lambda *a, **k: None)
    monkeypatch.setattr(M, "disable_wine_virtual_desktop", lambda *a, **k: None)
    os.makedirs(os.path.join(game_dir, "Data"), exist_ok=True)
    from backend.start_match import start_match
    cfg = make_match_config(ds, tournament_logo_choice="none", pitch_logo_choice="none")
    md = build_match_data(ds, cfg)
    assert md["tournament_logo"] == "" and md["pitch_logos"] == ""
    assert start_match(md, start_R08=False) is None
    blob = open(os.path.join(game_dir, gsv.game_filenames["tournament_logo"]), "rb").read()
    img = M.fsh_entry_image(M.fsh_entries(blob)[0][1]).convert("RGBA")
    assert img.getextrema()[3] == (0, 0)          # alpha 0 everywhere
