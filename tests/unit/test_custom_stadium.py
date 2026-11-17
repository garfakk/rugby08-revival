"""Custom stadiums: the files a match at one puts over its stock slot, the
name it shows in the game, and the clean-up at the next match."""
import os
import struct

from app.match_data_builder import _custom_stadium, _stadium_stripes
from app.state import MatchConfig
from backend import game_files_processor as GFP
from backend import pitch_stripes
from shared.omodel.bigfile import pack_big
from conftest import point_config

EDEN = {"name": "Eden Park", "game_id": 49, "is_custom": True, "environments": ["day", "night"],
        "scenes": {"day": "stadiums/Eden/day.big", "night": "stadiums/Eden/night.big"},
        "files": {"frontend/textures/stadiums/auckland.d.fsh": "stadiums/Eden/p.fsh"}}


def _cfg(info, env="day"):
    cfg = MatchConfig()
    cfg.stadium = {"stadium_id": info["game_id"], "data": info}
    cfg.environment = env
    return cfg


def test_match_files_and_name():
    files, name = _custom_stadium(_cfg(EDEN, "night"))
    assert files == {"stadiums/auckland.night": "stadiums/Eden/night.big",
                     "frontend/textures/stadiums/auckland.d.fsh": "stadiums/Eden/p.fsh"}
    assert name == {"string_id": 2184, "name": "Eden Park"}
    # an environment without its own scene: the slot's stock scene
    files, _ = _custom_stadium(_cfg(dict(EDEN, scenes={}), "day"))
    assert list(files) == ["frontend/textures/stadiums/auckland.d.fsh"]
    # Millennium roof closed: its own pack name
    files, _ = _custom_stadium(_cfg(dict(EDEN, game_id=32, scenes={"cold": "c.big"}), "cold"))
    assert "stadiums/milleniumcovered.cold" in files


def test_club_ground_and_stock_keep_their_names():
    _files, name = _custom_stadium(_cfg(dict(EDEN, game_id=26)))      # Clermont: the away team's string
    assert name is None
    assert _custom_stadium(_cfg(dict(EDEN, is_custom=False))) == ({}, None)


def test_deploy_replaces_then_cleans_up(tmp_path, monkeypatch):
    data, game = tmp_path / "data", tmp_path / "game"
    (data / "stadiums" / "Eden").mkdir(parents=True)
    game.mkdir()
    (data / "stadiums" / "Eden" / "day.big").write_bytes(b"EDEN")
    point_config(monkeypatch, data_dir=str(data), game_dir=str(game))
    hand_made = game / "474d8471765e6d21f94690212c3f893a.big"        # a forum stadium dropped by hand
    hand_made.write_bytes(b"x")
    GFP.deploy_stadium_files({"stadium_files": {"stadiums/auckland.day": "stadiums/Eden/day.big"}})
    scene = game / "aee3684b4499d255320af73ab7b8ffe2.big"            # md5("stadiums/auckland.day")
    assert scene.read_bytes() == b"EDEN"
    GFP.deploy_stadium_files({"stadium_files": {}})                    # next match, stock stadium
    assert not scene.exists() and not (game / GFP.STADIUM_MANIFEST).exists()
    assert hand_made.exists()


def test_stadium_name_written_after_the_team_names(tmp_path, monkeypatch):
    point_config(monkeypatch, game_dir=str(tmp_path))
    GFP.edit_teams_name({"team_A": {"name": "Blues"}, "team_B": {"name": "Chiefs"},
                         "stadium_name": {"string_id": 2184, "name": "Eden Park"}})
    data = (tmp_path / GFP.game_filenames["game_strings_english"]).read_bytes()
    assert data.endswith(struct.pack("<H", 2184) + b"Eden Park\x00")


def test_stripes_of_the_matchs_environment_are_written_in_the_deployed_scene(tmp_path, monkeypatch):
    info = dict(EDEN, stripes={"night": {"opacity": 70}})
    files, _ = _custom_stadium(_cfg(info, "night"))
    assert _stadium_stripes(_cfg(info, "night"), files) == {"scene": "stadiums/auckland.night",
                                                             "values": {"opacity": 70}}
    assert _stadium_stripes(_cfg(info, "day"), files) is None          # that environment keeps its own
    data, game = tmp_path / "data", tmp_path / "game"
    (data / "stadiums" / "Eden").mkdir(parents=True)
    game.mkdir()
    config = bytearray(600)
    struct.pack_into("<I", config, 0, pitch_stripes.MAGIC)
    (data / "stadiums" / "Eden" / "night.big").write_bytes(pack_big([("Config.bin", bytes(config))]))
    point_config(monkeypatch, data_dir=str(data), game_dir=str(game))
    GFP.deploy_stadium_files({"stadium_files": {"stadiums/auckland.night": "stadiums/Eden/night.big"},
                              "stadium_stripes": {"scene": "stadiums/auckland.night", "values": {"opacity": 70}}})
    scene = game / GFP.stadium_game_filename("stadiums/auckland.night")
    assert pitch_stripes.read(str(scene))["opacity"] == 70
