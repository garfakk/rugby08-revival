"""Pre-match anthem and haka. Every match is played in two club slots, so the
stock game picks the club intro (no anthem, no haka) and finds no anthem for
the slots' teams: the builder sends the anthem intro and the nation's stock
anthem code (reR08 .mis intro= / anthem=)."""
import json
import os

import pytest

from app.challenges import normalise
from app.match_data_builder import _presentation
from app.state import MatchConfig
from backend import game_specific_variables as gsv
from conftest import REAL_DATA

NZ = {"name": "New Zealand", "type": "international"}
AUS = {"name": "Australia", "type": "international"}
SPAIN = {"name": "Spain", "type": "international"}
URUGUAY = {"name": "Uruguay", "type": "international"}
LIONS = {"name": "British & Irish Lions", "type": "special"}
TOULOUSE = {"name": "Toulouse", "type": "club"}


def present(home, away, **cfg):
    return _presentation(home, away, MatchConfig(**cfg))


def test_test_match_plays_the_home_anthem_and_nz_haka():
    assert present(NZ, AUS) == {"anthem": 13, "intro": "anthem", "haka_home": True, "haka_away": False}
    assert present(AUS, NZ) == {"anthem": 2, "intro": "anthem", "haka_home": False, "haka_away": True}


def test_home_team_without_anthem_uses_the_away_one():
    assert present(SPAIN, NZ)["anthem"] == 13
    assert present(SPAIN, NZ)["intro"] == "anthem"


def test_no_anthem_on_either_side_keeps_the_stock_intro():
    assert present(SPAIN, URUGUAY) == {"anthem": None, "intro": None, "haka_home": False, "haka_away": False}


def test_special_sides_get_the_anthem_intro():
    assert present(AUS, LIONS)["intro"] == "anthem"
    assert present(LIONS, AUS)["anthem"] == 2


def test_club_matches_keep_the_club_intro():
    p = present(TOULOUSE, NZ)
    assert p["intro"] is None and p["anthem"] == 13      # World Cup intros still get the anthem
    assert p["haka_away"] is True
    assert present(TOULOUSE, TOULOUSE)["anthem"] is None


def test_forced_modes():
    assert present(NZ, AUS, anthem="away")["anthem"] == 2
    assert present(TOULOUSE, AUS, anthem="home") == {"anthem": 2, "intro": "anthem",
                                                       "haka_home": False, "haka_away": False}
    assert present(NZ, AUS, anthem="off") == {"anthem": None, "intro": "club",
                                                "haka_home": False, "haka_away": False}
    assert present(AUS, SPAIN, haka_away=True)["haka_away"] is True


def test_old_stock_value_means_auto():
    assert present(NZ, AUS, anthem="stock") == present(NZ, AUS)
    assert normalise({"anthem": "stock"})["anthem"] == "auto"
    assert normalise({"anthem": "home"})["anthem"] == "home"


def test_every_anthem_code_is_in_the_exe_table():
    table = {1, 2, 3, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 17, 18, 20, 21, 24, 25}
    assert set(gsv.anthem_codes.values()) <= table


def test_every_shipped_nation_with_a_stock_anthem_is_mapped():
    no_anthem = {"chile", "russia", "spain", "tunisia", "uruguay"}
    teams = os.path.join(REAL_DATA, "teams")
    for folder in os.listdir(teams):
        for f in os.listdir(os.path.join(teams, folder)):
            if not f.endswith(".json"):
                continue
            for seasons in json.load(open(os.path.join(teams, folder, f))).values():
                for info in seasons.values():
                    name = info.get("name", "").lower()
                    if info.get("type") == "international" and name not in no_anthem:
                        assert name in gsv.anthem_codes, name
