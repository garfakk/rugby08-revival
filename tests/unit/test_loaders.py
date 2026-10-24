"""team/stadium/competition loaders and the config parser."""
import configparser
import json
import os
import re

import pytest

from conftest import SRC
from shared.config import Config, config
from stadium_data_loader import StadiumDataLoader
from team_data_loader import TeamDataLoader
from tournament_data_loader import TournamentDataLoader, _parse_relaxed_json


def _write(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(data if isinstance(data, str) else json.dumps(data))


# ── teams ────────────────────────────────────────────────────────────────
@pytest.fixture
def teams_tree(tmp_path):
    t = tmp_path / "teams"
    _write(str(t / "France" / "france.json"),
           {"10001": {"2024": {"name": "France"}, "2008": {"name": "France", "enabled": False}}})
    _write(str(t / "France" / "france (copy).json"), {"10001": {"2024": {"name": "Old"}}})
    _write(str(t / "France" / "france.json.deleted-20260101-000000"), {"999": {}})
    _write(str(t / "Ghost" / "ghost.json"), {"2001": {"2008": {"name": "G", "enabled": False}}})
    _write(str(t / "Nojson" / "other.json"), {"2002": {"2024": {"name": "N"}}})
    _write(str(t / "New Team" / "new_team.json"), {"2003": {"2024": {"name": "New"}}})
    _write(str(t / "Broken" / "broken.json"), "{oops")
    p = tmp_path / "players"
    _write(str(p / "a.json"), {"1": {"display_name": "A1"}, "2": {"display_name": "A2"}})
    _write(str(p / "b.json"), {"2": {"display_name": "B2"}})
    _write(str(p / "c.json"), [{"id": 3, "display_name": "C3"}])
    return tmp_path


def test_load_teams(teams_tree):
    loader = TeamDataLoader(str(teams_tree / "teams"), str(teams_tree / "players"))
    teams = loader.load_teams()
    assert teams["10001"] == {"2024": {"name": "France"}}           # only <folder>.json, disabled dropped
    assert "2001" not in teams                                      # no enabled season
    assert "2002" not in teams                                      # folder without its json
    assert teams["2003"]["2024"]["name"] == "New"                   # "New Team" -> new_team.json
    assert "999" not in teams
    ids = {os.path.basename(k): v for k, v in loader.team_json_ids.items()}
    assert ids["other.json"] == ["2002"] and ids["france (copy).json"] == ["10001"]
    assert loader.teams_folder_path["10001"].endswith("France")


def test_load_players_last_duplicate_wins(teams_tree):
    loader = TeamDataLoader(str(teams_tree / "teams"), str(teams_tree / "players"))
    players = loader.load_players()
    assert players["2"]["display_name"] == "B2"
    assert players["3"]["display_name"] == "C3"
    assert [os.path.basename(p) for p in loader.players_sources["2"]] == ["a.json", "b.json"]
    assert loader.players_file_path["2"].endswith("b.json")


def test_missing_dirs(tmp_path):
    loader = TeamDataLoader(str(tmp_path / "x"), str(tmp_path / "y"))
    assert loader.load_teams() == {} and loader.load_players() == {}
    assert StadiumDataLoader(str(tmp_path / "z")).load_stadiums() == {}
    assert TournamentDataLoader(str(tmp_path / "z")).load_tournaments() == {}


def test_team_json_name():
    assert TeamDataLoader.team_json_name("New Zealand") == "new_zealand.json"


# ── stadiums / competitions ──────────────────────────────────────────────
def test_fixture_stadiums_load():
    stadiums = StadiumDataLoader(config.directory_stadiums).load_stadiums()
    assert stadiums and all(isinstance(v, dict) for v in stadiums.values())


def test_relaxed_json():
    assert _parse_relaxed_json('{"a": [1, 2,], "b": {"c": 1,},}') == {"a": [1, 2], "b": {"c": 1}}


def test_competitions_seasonal_override_and_filter(tmp_path):
    _write(str(tmp_path / "cup" / "cup.json"),
           '{"id": "cup", "name": "Cup", "seasonal": true, "ball": "b.png",'
           ' "seasons": {"2007": {"logo": "l.png",}, "2023": {"ball": "",}, "2011": {"name": "Cup 11"}},}')
    _write(str(tmp_path / "plain" / "plain.json"), {"id": "5002", "name": "P", "pads": "p.fsh",
                                                     "template": {"id": "x"}})
    _write(str(tmp_path / "empty" / "empty.json"), {"id": "e", "name": "E"})
    _write(str(tmp_path / "named" / "named.json"), {"id": "n", "name": "N", "logo": "missing.png"})
    for f in ("cup/b.png", "cup/l.png", "plain/p.fsh"):
        (tmp_path / f).write_bytes(b"x")
    loader = TournamentDataLoader(str(tmp_path))
    out = loader.load_tournaments()
    assert set(out["cup"]) == {"2007", "2011"}                       # 2023 has no asset left
    assert "n" not in out                                            # names a file not on disk
    assert out["cup"]["2007"] == {"name": "Cup", "ball": "b.png", "logo": "l.png"}
    assert out["cup"]["2011"]["name"] == "Cup 11"
    assert out["5002"] == {"": {"name": "P", "pads": "p.fsh"}}       # template not branding
    assert "e" not in out
    assert loader.tournaments_folder_path["cup"].endswith("cup")


# ── config ───────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,expected", [("1", True), ("yes", True), (" On ", True),
                                          ("false", False), ("0", False), ("", False), (True, True)])
def test_parse_bool(raw, expected):
    assert config._parse_bool(raw) is expected


@pytest.mark.parametrize("raw,expected", [("a, b,c", ["a", "b", "c"]), ("a|b", ["a", "b"]),
                                          ("one", ["one"]), ("", []), (["x"], ["x"])])
def test_parse_list(raw, expected):
    assert config._parse_list(raw) == expected


def test_parse_env_assignments_and_file(tmp_path):
    assert config._parse_env_assignments("A=1, B = two, junk, =x") == {"A": "1", "B": "two"}
    env = tmp_path / "x.env"
    env.write_text('# c\nexport A=1\nB="two words"\nC=three # note\nD=\'q\'\nnoequals\n')
    assert config._load_env_file(str(env)) == {"A": "1", "B": "two words", "C": "three", "D": "q"}
    assert config._load_env_file(str(tmp_path / "missing")) == {}


def test_options_override_with_types(tmp_path, monkeypatch):
    ini = tmp_path / "c.ini"
    ini.write_text("[Options]\nembed_game = false\nreveal_screen_id = 0x79\n"
                   "exclude_static_files = a.dll, b.dll\nlog-level = DEBUG\n"
                   "memory_addresses = 5\nboot_counter_max = notanumber\nunknown_key = 1\n")
    for attr in ("embed_game", "reveal_screen_id", "exclude_static_files", "log_level",
                 "memory_addresses", "boot_counter_max"):
        monkeypatch.setattr(config, attr, getattr(config, attr))
    assert config._load_config_file(str(ini), "Options")
    assert config.embed_game is False
    assert config.reveal_screen_id == 0x79
    assert config.exclude_static_files == ["a.dll", "b.dll"]
    assert config.log_level == "DEBUG"
    assert isinstance(config.memory_addresses, dict)                 # dicts never overwritten
    assert config.boot_counter_max == 20736                          # bad value: default kept
    assert not hasattr(config, "unknown_key")


def test_every_documented_option_exists():
    """Every key config.ini.example documents is a real Config attribute
    (a typo there is silently ignored by _load_config_file)."""
    cp = configparser.ConfigParser()
    with open(os.path.join(SRC, "config.ini.example"), encoding="utf-8") as f:
        text = f.read()
    # documented options may be commented out: "# key = value"
    keys = set(re.findall(r"^[#;]? ?([A-Za-z_][A-Za-z0-9_]*) *=", text.split("[Options]", 1)[1], re.M))
    missing = sorted(k for k in keys if not hasattr(config, k))
    assert not missing, missing


def test_derived_paths_follow_data_directory():
    assert config.directory_players == os.path.join(config.mod_data_directory, "players")
    assert config.templates_directory == os.path.join(config.mod_src_directory, "assets", "templates")
    assert not config.temp_directory.startswith(config.R08_directory)


def test_data_version_read(tmp_path, monkeypatch):
    (tmp_path / "VERSION").write_text("data_version=2026.10.1\nschema=3\n")
    monkeypatch.setattr(config, "mod_data_directory", str(tmp_path))
    assert config._read_data_version() == ("2026.10.1", 3)
    (tmp_path / "VERSION").write_text("schema=abc\n")
    assert config._read_data_version() == ("unknown", 0)


def test_config_is_valid(tmp_path):
    ini = tmp_path / "c.ini"
    assert not Config._config_is_valid(str(ini))
    ini.write_text(f"[Main]\nR08_directory = {tmp_path}\nR08_filename = Rugby08.exe\n")
    assert not Config._config_is_valid(str(ini))
    (tmp_path / "Rugby08.exe").write_bytes(b"")
    assert Config._config_is_valid(str(ini))


def test_competition_menu_logo_alone_is_branding(tmp_path):
    _write(str(tmp_path / "cup" / "cup.json"), {"id": "cup", "name": "Cup", "logo_frontend": "m.png"})
    (tmp_path / "cup" / "m.png").write_bytes(b"x")
    assert TournamentDataLoader(str(tmp_path)).load_tournaments()["cup"][""]["logo_frontend"] == "m.png"
