"""A competition's own trophy (competition definition "trophy"): lifted in
the ceremony it names, its model and texture standing in for that
ceremony's stock trophy for the match only (the Top 14's Bouclier de
Brennus in the Ten Nations ceremony)."""
import json
import os
from types import SimpleNamespace

import pytest

from app import competition_branding
from app.match_data_builder import _trophy_files, _trophy_lift
from app.state import MatchConfig
from backend import game_files_processor as gfp
from backend import game_specific_variables as gsv
from conftest import REAL_DATA
from shared.config import config

TEN = gsv.trophy_files["TenNations"]


@pytest.fixture
def comp(tmp_path, monkeypatch):
    """A competition folder with a trophy, as the loader gives it."""
    monkeypatch.setattr(config, "mod_data_directory", str(tmp_path))
    folder = tmp_path / "competitions" / "cup"
    (folder / "assets" / "trophy").mkdir(parents=True)
    (folder / "assets" / "trophy" / "t.o").write_bytes(b"o")
    (folder / "assets" / "trophy" / "t.fsh").write_bytes(b"f")
    info = {"name": "Cup", "trophy": {"ceremony": "TenNations", "model": "assets/trophy/t.o",
                                      "texture": "assets/trophy/t.fsh"}}
    return SimpleNamespace(tournaments={"cup": {"": info}},
                           tournaments_folder_path={"cup": str(folder)}), info


def test_branding_brings_the_trophy(comp):
    ds, _info = comp
    cfg = MatchConfig()
    assert competition_branding.apply(ds, cfg, "cup")
    assert cfg.trophy == {"ceremony": "TenNations",
                          "model": "competitions/cup/assets/trophy/t.o",
                          "texture": "competitions/cup/assets/trophy/t.fsh"}


def test_missing_files_bring_none(comp):
    ds, info = comp
    info["trophy"]["model"] = "assets/trophy/nope.o"
    cfg = MatchConfig()
    competition_branding.apply(ds, cfg, "cup")
    assert cfg.trophy == {}


def test_only_when_the_trophy_is_lifted(comp):
    ds, _info = comp
    cfg = MatchConfig()
    competition_branding.apply(ds, cfg, "cup")
    for lift in ("stock", "off"):
        cfg.trophy_lift = lift
        assert _trophy_lift(cfg) == lift and _trophy_files(cfg) == {}
    cfg.trophy_lift = "on"                      # a final: the competition's ceremony
    assert _trophy_lift(cfg) == "TenNations"
    assert _trophy_files(cfg) == {TEN["model"]: cfg.trophy["model"],
                                  TEN["texture"]: cfg.trophy["texture"]}
    cfg.trophy_lift = "WorldCup"                # another ceremony asked for: stock trophy
    assert _trophy_lift(cfg) == "WorldCup" and _trophy_files(cfg) == {}


def test_copied_for_the_match_and_cleaned_before_the_next(comp, tmp_path, monkeypatch):
    ds, _info = comp
    game = tmp_path / "game"
    game.mkdir()
    monkeypatch.setattr(config, "game_launcher_directory", str(game))
    cfg = MatchConfig()
    competition_branding.apply(ds, cfg, "cup")
    cfg.trophy_lift = "on"
    for name, src in _trophy_files(cfg).items():          # what edit_graphics_files does
        gfp.copy_file(os.path.join(config.mod_data_directory, src), str(game / name))
    assert (game / TEN["model"]).read_bytes() == b"o"
    assert {TEN["model"], TEN["texture"]} <= gfp.generated_game_filenames()
    gfp.clean_generated_files(str(game))
    assert not (game / TEN["model"]).exists() and not (game / TEN["texture"]).exists()


def test_top_14_has_the_brennus():
    path = os.path.join(REAL_DATA, "competitions", "top_14", "top_14.json")
    if not os.path.isfile(path):
        pytest.skip("no data pack")
    trophy = json.load(open(path, encoding="utf-8"))["trophy"]
    assert trophy["ceremony"] == "TenNations"
    folder = os.path.dirname(path)
    for key in ("model", "texture"):
        assert os.path.isfile(os.path.join(folder, trophy[key]))
    from shared.omodel import parse_o
    (mesh,) = parse_o(open(os.path.join(folder, trophy["model"]), "rb").read())
    assert mesh.shapename == "T_tr" and mesh.name.startswith("TenTrophies")
