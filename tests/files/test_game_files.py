"""backend/game_files_processor.py: the files written into the game folder for
a match — mission (.mis), roster (.rdf), team names (game strings) — checked
against golden files and re-read with the mod's own roster reader."""
import copy
import os
import xml.etree.ElementTree as ET

import pytest

from app.roster_import.reader import read_roster
from backend import game_files_processor as GFP
from backend import game_specific_variables as gsv
from shared.config import config


def mission(game_dir):
    path = os.path.join(game_dir, gsv.game_filenames["missionFile"])
    with open(path, encoding="utf-8") as f:
        return f.read()


def write_mission(game_dir, md):
    GFP.create_mission_file(md)
    text = mission(game_dir)
    return text, ET.fromstring(text)


# ── mission file ─────────────────────────────────────────────────────────
def test_mission_file_golden(game_dir, match_data, golden):
    text, root = write_mission(game_dir, match_data)
    golden("mission_eng_fra.mis", text)
    assert root.get("side") == "left" and root.get("diff") == "2"
    assert root.get("c0") == "home"


def test_wind_always_written(game_dir, match_data):
    """A .mis without <WIND> crashes the game while loading."""
    for power in (None, 0, 2, 10):
        md = dict(match_data, wind_power=power)
        _, root = write_mission(game_dir, md)
        wind = root.find("GAME/ENVIRONMENT/WEATHER/WIND")
        assert wind is not None, power
        if power is None:
            assert 0 <= int(wind.get("power")) <= 3                 # stock random band
        elif power == 0:
            assert (wind.get("x"), wind.get("z")) == ("0", "0")     # calm has no direction


def test_wind_direction_written_as_integers(game_dir, match_data):
    """The game parses <WIND x/z> with atol: "-0.7071" would read as 0, a
    calm wind. Off-axis bearings must survive as integers."""
    md = dict(match_data, wind_power=6, wind_x=-0.1736, wind_z=-0.9848)
    _, root = write_mission(game_dir, md)
    wind = root.find("GAME/ENVIRONMENT/WEATHER/WIND")
    assert (wind.get("x"), wind.get("y"), wind.get("z")) == ("-174", "0", "-985")
    _, root = write_mission(game_dir, dict(match_data, wind_power=None))
    wind = root.find("GAME/ENVIRONMENT/WEATHER/WIND")
    for axis in ("x", "z"):
        assert wind.get(axis).lstrip("-").isdigit()


def test_weather_defaults(game_dir, match_data):
    md = dict(match_data, environment=None, pitch_texture="")
    _, root = write_mission(game_dir, md)
    weather = root.find("GAME/ENVIRONMENT/WEATHER")
    assert weather.get("env") == "default" and weather.get("pitchtex") == "default"


def test_advanced_fields_omitted_by_default(game_dir, match_data):
    _, root = write_mission(game_dir, match_data)
    for attr in ("anthem", "haka0", "haka1", "trophy_lift", "stadium_flags", "kickassist",
                 "cpu_lineout_keep", "cpu_jackal"):
        assert attr not in root.attrib
    assert root.find("EVENTS") is None
    assert list(root.find("OBJECTIVES")) == []


def test_advanced_fields_written(game_dir, match_data):
    md = dict(match_data, anthem="home", haka_away=True, trophy_lift="on", stadium_flags=False,
              kick_assist=True, cpu_edge={"cpu_lineout_keep": 97, "cpu_jackal": 25,
                                                   "cpu_fh_kick": "65,40,15,5"},
              precip_mode="snow", snow_intensity=12.0, breath=True,
              score_events=[{"type": "SS_TRY", "team": "away", "player": 3, "time": 300},
                            {"type": ""}],
              mission_state={"mode_name": "PEN K", "mode_time": 600, "mode_period": 1},
              mission_nis=[{"script_name": "penalty_general_TeamA", "controller": 7,
                            "team": "home", "player": 4, "x": -3.0, "z": 28.0}],
              objectives=[{"type": "WinGame", "mustpass": True,
                           "parameters": [{"name": "amount", "value": 1}, {"name": ""}]},
                          {"type": ""}],
              cards=[{"team": "away", "jersey": "12", "type": "yellow", "minute": 46},
                     {"team": "home", "jersey": None}])
    _, root = write_mission(game_dir, md)
    assert root.get("anthem") == "home" and root.get("haka1") == "1"
    assert root.get("stadium_flags") == "off" and root.get("kickassist") == "on"
    assert root.get("cpu_lineout_keep") == "97" and root.get("cpu_jackal") == "25"
    assert root.get("cpu_fh_kick") == "65,40,15,5"
    weather = root.find("GAME/ENVIRONMENT/WEATHER")
    assert weather.get("precip") == "snow" and weather.get("intensity") == "12.0"
    assert weather.get("breath") == "on"
    events = root.findall("GAME/STATE/SCORE/EVENT")
    assert [e.get("team") for e in events] == ["away"]                # empty type skipped
    mode = root.find("GAME/STATE/MODE")
    assert (mode.get("name"), mode.get("time"), mode.get("period")) == ("PEN K", "600", "1")
    nis = root.find("GAME/STATE/NIS")
    assert nis.get("controller") == "7" and nis.get("angle") == "" and nis.get("z") == "28.0"
    objs = root.findall("OBJECTIVES/OBJECTIVE")
    assert len(objs) == 1 and objs[0].get("mustpass") == "1"
    assert [p.get("name") for p in objs[0]] == ["amount"]
    assert objs[0].get("type") in gsv.objective_types
    cards = root.findall("EVENTS/CARD")
    assert len(cards) == 1 and cards[0].get("jersey") == "12"         # cards without a jersey dropped


# ── roster ───────────────────────────────────────────────────────────────
def test_roster_golden_and_readable(game_dir, data_dir, ds, match_data, golden):
    GFP.edit_roster_file(copy.deepcopy(match_data))
    path = os.path.join(game_dir, gsv.game_filenames["roster"])
    with open(path, "rb") as f:
        golden("roster_eng_fra.rdf", f.read())
    roster = read_roster(path)
    written = {p["roster_id"]: p for p in roster["players"].values()}
    for team in ("team_A", "team_B"):
        for player, rid in zip(match_data[team]["players"], gsv.players_roster_id[team]):
            rec = written[rid]
            assert rec["name"] == player["name"][:14]
            assert rec["commentary"] == player["commentary"]
            assert rec["ratings"]["attack"] == player["attack"]
            assert rec["ratings"]["lineout"] == player["line_out"]
            assert rec["ratings"]["consitance"] == player["consistency"]
            assert rec["positions"][0] == player["pos1"]
            assert 0 <= player["height"] - rec["height_cm"] <= 3     # truncated to the inch (see below)
            assert abs(rec["weight_kg"] - player["weight"]) <= 1
            assert rec["foot"] == f"{player['best_foot']}_footed"
            assert rec["socks"] == ("up" if player["socks_up"] else "down")


def test_roster_team_performance_floor(game_dir, match_data):
    """legend/immortal floor the CPU team's record performance bytes (attack is
    what the CPU set-play chooser reads); a stock value above stays."""
    path = os.path.join(game_dir, gsv.game_filenames["roster"])
    GFP.edit_roster_file(copy.deepcopy(match_data))
    before = read_roster(path)["teams"]
    md = copy.deepcopy(match_data)
    md["team_B"]["performance_floor"] = {k: 90 for k in gsv.team_performance_keys}
    GFP.edit_roster_file(md)
    after = read_roster(path)["teams"]
    a_id, b_id = gsv.teams_id["team_A"], gsv.teams_id["team_B"]
    assert after[a_id]["performance"] == before[a_id]["performance"]
    for key, value in after[b_id]["performance"].items():
        assert value == max(90, before[b_id]["performance"][key])


@pytest.mark.xfail(strict=True, reason="suspected bug: write_players_data_to_roster truncates "
                   "height to whole inches (int()) instead of rounding, so e.g. 178 cm is stored "
                   "as 176 cm in game")
def test_roster_height_rounded_to_nearest_inch(game_dir, match_data):
    md = copy.deepcopy(match_data)
    for p in md["team_A"]["players"] + md["team_B"]["players"]:
        p["height"] = 178
    GFP.edit_roster_file(md)
    roster = read_roster(os.path.join(game_dir, gsv.game_filenames["roster"]))
    rid = gsv.players_roster_id["team_A"][0]
    rec = next(p for p in roster["players"].values() if p["roster_id"] == rid)
    assert rec["height_cm"] == 178


def test_roster_skipped_without_22_players(game_dir, match_data):
    md = copy.deepcopy(match_data)
    md["team_B"]["players"] = md["team_B"]["players"][:21]
    GFP.edit_roster_file(md)
    path = os.path.join(game_dir, gsv.game_filenames["roster"])
    template = os.path.join(config.templates_directory, gsv.template_filenames["roster"])
    assert open(path, "rb").read() == open(template, "rb").read()


# ── team names ───────────────────────────────────────────────────────────
def test_team_names_appended(game_dir, match_data):
    GFP.edit_teams_name(match_data)
    for key in ("game_strings_english", "game_strings_french"):
        written = open(os.path.join(game_dir, gsv.game_filenames[key]), "rb").read()
        template = open(os.path.join(config.templates_directory, gsv.template_filenames[key]), "rb").read()
        tail = written[len(template):]
        assert written.startswith(template)
        assert tail == (gsv.teams_string_id["team_A"] + match_data["team_A"]["name"].encode() + b"\0"
                        + gsv.teams_string_id["team_B"] + match_data["team_B"]["name"].encode() + b"\0")


# ── clean-up ─────────────────────────────────────────────────────────────
def test_clean_generated_files_only_touches_generated(game_dir, match_data):
    GFP.create_mission_file(match_data)
    GFP.edit_teams_name(match_data)
    keep = os.path.join(game_dir, "Data", "data.gob")
    os.makedirs(os.path.dirname(keep))
    open(keep, "wb").close()
    removed = GFP.clean_generated_files()
    assert removed == 3                                              # .mis + 2 string files
    assert sorted(os.listdir(game_dir)) == ["Data", "Rugby08.exe"]
    assert os.path.isfile(keep)


def test_generated_names_include_faces_and_teams():
    names = GFP.generated_game_filenames()
    assert gsv.game_filenames["missionFile"] in names
    for team in ("team_A", "team_B"):
        assert set(gsv.game_filenames[team].values()) <= names
    for faces in gsv.face_id_for_custom_faces.values():
        assert all(f["filename"] in names for f in faces)
    assert "Rugby08.exe" not in names


def test_static_files_copied_with_exclusions(game_dir, monkeypatch):
    monkeypatch.setattr(config, "exclude_static_files", ["d3d8.dll"])
    os.makedirs(os.path.join(game_dir, "Data"))      # a real install always has it (videos go there)
    GFP.copy_static_files()
    src = config.static_files_directory
    for root, _dirs, files in os.walk(src):
        for name in files:
            rel = os.path.relpath(os.path.join(root, name), src)
            if name in ("eaenpc.vp6", "inenpc.vp6"):
                rel = os.path.join(os.path.dirname(rel), "Data", name)
            assert os.path.exists(os.path.join(game_dir, rel)) is (name != "d3d8.dll"), rel
