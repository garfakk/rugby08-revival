"""app/challenges.py: challenge files, migration of old files, restart
geometry, and the MatchConfig a challenge plays with."""
import json
import os

import pytest

from app import challenges as C
from conftest import FIXTURE_DATA
from shared.user_prefs import user_prefs

PLAYABLE = "rwc2023_sf_rsa_eng"


def load_fixture(cid=PLAYABLE):
    with open(os.path.join(FIXTURE_DATA, "challenges", cid + ".json"), encoding="utf-8") as f:
        return C.normalise(json.load(f))


# ── files ────────────────────────────────────────────────────────────────
def test_normalise_fills_defaults_one_level_deep():
    out = C.normalise({"name": "X", "home": {"team_id": "1"}})
    assert out["name"] == "X"
    assert out["home"]["team_id"] == "1"
    assert out["home"]["kit"] == "home"          # team block merged, not replaced
    assert out["difficulty"] == C.DEFAULTS["difficulty"]
    assert C.normalise(None) == C.new_challenge()


@pytest.mark.parametrize("field", ["home_team_side", "kick_off"])
def test_normalise_migrates_old_random(field):
    """Files from before sides and kick-off were fixed may still say "random"."""
    assert C.normalise({field: "random"})[field] == C.DEFAULTS[field]


def test_normalise_filters_user_choice():
    out = C.normalise({"user_choice": ["stadium_id", "bogus", "difficulty"]})
    assert out["user_choice"] == ["stadium_id", "difficulty"]


def test_new_challenge_is_a_copy():
    a = C.new_challenge()
    a["home"]["team_id"] = "x"
    assert C.DEFAULTS["home"]["team_id"] == ""


@pytest.mark.parametrize("name,taken,expected", [
    ("RWC Final!", set(), "rwc_final"),
    ("RWC Final", {"rwc_final"}, "rwc_final_2"),
    ("RWC Final", {"rwc_final", "rwc_final_2"}, "rwc_final_3"),
    ("???", set(), "challenge"),
])
def test_unique_id(name, taken, expected):
    assert C.unique_id(name, taken) == expected


def test_save_load_delete_roundtrip(data_dir):
    data = C.new_challenge()
    data.update(name="Zed", order=5)
    path = C.save("zed", data)
    assert path.endswith(os.path.join("challenges", "zed.json"))
    assert not os.path.exists(path + ".tmp")
    loaded = C.load_all()
    assert loaded["zed"]["name"] == "Zed"
    assert list(loaded)[-1] == "zed"              # order 5 sorts after the fixture ones (order <= 4)
    C.delete("zed")
    C.delete("zed")                               # already gone: no error
    assert "zed" not in C.load_all()


def test_load_all_skips_broken_file(data_dir):
    with open(os.path.join(data_dir, "challenges", "broken.json"), "w") as f:
        f.write("{not json")
    found = C.load_all()
    assert "broken" not in found and PLAYABLE in found


def test_load_all_ordered_by_order_then_name(data_dir):
    ids = list(C.load_all())
    keys = [(C.load_all()[i]["order"], C.load_all()[i]["name"].lower()) for i in ids]
    assert keys == sorted(keys)


# ── problems ─────────────────────────────────────────────────────────────
def test_fixture_challenge_playable(ds):
    assert C.problems(ds, load_fixture()) == []


def test_problems_reported(ds):
    data = load_fixture()
    data["home"]["team_id"] = "999999"
    data["away"]["season"] = "1900"
    data["stadium_id"] = "nope"
    data["branding"] = "nope:1"
    data["home"]["squad"] = {"players": ["123456789"]}
    found = C.problems(ds, data)
    assert any("home team 999999 is not in the data" in p for p in found)
    assert any("away team has no 1900 squad" in p for p in found)
    assert any("unknown player(s) 123456789" in p for p in found)
    assert any("stadium nope" in p for p in found)
    assert any("competition textures nope:1" in p for p in found)


def test_disabled_season_not_playable(ds):
    """The RWC 2007 challenges use England 2008, disabled in the data: the
    loader drops disabled seasons, so challenge mode can't offer them."""
    found = C.problems(ds, load_fixture("rwc2007_final_rsa_eng"))
    assert found == ["away team has no 2008 squad"]


def test_custom_kit_missing_file_reported(ds):
    data = load_fixture()
    data["home"]["custom_kit"] = {"frontKitFile": "kits_x/nope.png",
                                  "backKitFile": "kits_x/back_%.png", "color": "ignored"}
    assert C.custom_kit(data, "home") == {"frontKitFile": "kits_x/nope.png",
                                          "backKitFile": "kits_x/back_%.png"}
    found = C.problems(ds, data)
    assert any("custom kit file(s) not found: kits_x/nope.png, kits_x/back_%.png" in p for p in found)


# ── geometry ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("side,home_side,period,expected", [
    ("home", "right", 0, C.HOME_ATTACKS_Z_FIRST_HALF),
    ("away", "right", 0, -C.HOME_ATTACKS_Z_FIRST_HALF),
    ("home", "left", 0, -C.HOME_ATTACKS_Z_FIRST_HALF),
    ("home", "right", 1, -C.HOME_ATTACKS_Z_FIRST_HALF),
    ("home", "left", 1, C.HOME_ATTACKS_Z_FIRST_HALF),
    ("home", "right", None, C.HOME_ATTACKS_Z_FIRST_HALF),
    ("home", "right", 2, C.HOME_ATTACKS_Z_FIRST_HALF),
])
def test_attack_sign(side, home_side, period, expected):
    assert C.attack_sign(side, home_side, period) == expected


def test_restart_xz_none_without_spot():
    assert C.restart_xz(C.new_challenge(), "home") == (None, None)


@pytest.mark.parametrize("spot,expected_abs", [
    ({"metres_out": 22, "across": 5}, (5.0, 28.0)),
    ({"metres_out": -10, "across": 0}, (0.0, 50.0)),          # clamped to the try line
    ({"metres_out": 500, "across": 0}, (0.0, 50.0)),          # clamped to the far try line
    ({"metres_out": 22, "across": 99}, (33.0, 28.0)),         # clamped to the touchline
])
def test_restart_xz_clamped(spot, expected_abs):
    data = dict(C.new_challenge(), restart_spot=spot, mission_mode_period=0)
    x, z = C.restart_xz(data, "home")
    assert (abs(x), abs(z)) == expected_abs
    sign = C.attack_sign("home", data["home_team_side"], 0)
    assert z == pytest.approx(sign * (C.TRY_LINE_Z - min(max(spot["metres_out"], 0), 100)))


def test_start_state_authored_nis_kept():
    data = dict(C.new_challenge(), mission_mode_name="PEN K", mission_nis=[{"script_name": "x"}])
    assert C.start_state(data, "home") == ("PEN K", [{"script_name": "x"}])


def test_start_state_scenes():
    base = C.new_challenge()
    assert C.start_state(dict(base, mission_mode_name="KICK OFF", mission_mode_time=600), "home") == \
        ("", [C._nis("kick_off")])
    name, nis = C.start_state(dict(base, mission_mode_name="PEN K"), "home")
    assert name == "PEN K" and nis[0]["script_name"] == "penalty_general_TeamB"   # penalised side
    name, nis = C.start_state(dict(base, mission_mode_name="PEN K",
                                   restart_spot={"metres_out": 30, "offender": 4}), "away")
    assert nis[0]["controller"] == 7 and nis[0]["team"] == "home" and nis[0]["player"] == 4
    name, nis = C.start_state(dict(base, mission_mode_name="LINE OUT"), "away")
    assert nis[0]["script_name"] == "lineout01_teamb"
    assert C.start_state(base, "home") == ("", [])


# ── to_match_config ──────────────────────────────────────────────────────
def test_to_match_config(ds, monkeypatch):
    monkeypatch.setattr(user_prefs, "wind_mode", "advanced", raising=False)
    data = load_fixture()
    data["score_events"] = [{"team": "home", "player": 10, "type": "SS_PENALTY"},
                            {"team": "away", "player": 1, "type": "SS_TRY"}]
    data["wind_power"] = None
    cfg = C.to_match_config(ds, data)
    assert cfg.home.team_id == data["home"]["team_id"]
    assert cfg.away.team_id == data["away"]["team_id"]
    assert len(cfg.home.players) >= 22
    assert [e["player"] for e in cfg.score_events] == [9, 0]      # shirts 1-15 -> 0-based
    assert cfg.wind_power == 0                                   # no power = calm, never random
    assert cfg.controllers[1]["zone"] == data["user_side"]
    assert cfg.lock_controllers


@pytest.mark.parametrize("flags,expected", [(None, True), (False, False), (True, True)])
def test_world_cup_stadium_flags(ds, flags, expected):
    """A World Cup challenge left on "stock" gets the RWC stadium dressing;
    an explicit false is kept."""
    data = dict(load_fixture(), match_type="world_cup", stadium_flags=flags)
    assert C.to_match_config(ds, data).stadium_flags is expected


def test_standard_wind_setting_leaves_game_wind(ds, monkeypatch):
    monkeypatch.setattr(user_prefs, "wind_mode", "standard", raising=False)
    data = load_fixture()
    data["wind_power"] = 5
    assert C.to_match_config(ds, data).wind_power is None


def test_start_score_and_minute():
    data = dict(C.new_challenge(), mission_mode_time=780,
                score_events=[{"team": "away", "type": "SS_PENALTY"},
                              {"team": "home", "type": "SS_TRY"}, {"team": "home", "type": "SS_CONVERSION"}])
    assert C.start_score(data) == (7, 3)
    assert C.start_minute(data) == 13
    assert C.start_minute(C.new_challenge()) is None


def test_is_choice():
    data = dict(C.new_challenge(), user_choice=["stadium_id"])
    assert C.is_choice(data, "stadium_id")
    assert C.is_choice(data, "difficulty")             # always choosable
    assert not C.is_choice(data, "environment")
