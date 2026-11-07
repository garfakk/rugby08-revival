"""A knockout game of a competition the game doesn't have (match_type
"exhibition": Top 14, URC, Pro14) is sent as the closest one the game has,
so a final gets a final's presentation; league games stay as they are."""
from types import SimpleNamespace

from app.tournament.bridge import game_match_type


def _f(knockout):
    return SimpleNamespace(knockout=knockout)


def test_playoffs_take_a_real_competition():
    top14 = {"match_type": "exhibition", "playoff_match_type": "premiership", "category": "Top 14"}
    assert game_match_type(top14, _f(False)) == "exhibition"
    assert game_match_type(top14, _f(True)) == "premiership"
    # no playoff_match_type: the closest — a club league's is the Premiership
    assert game_match_type({"match_type": "exhibition", "category": "URC"}, _f(True)) == "premiership"
    assert game_match_type({"match_type": "exhibition"}, _f(True)) == "world_cup"
    # a real competition keeps its own, knockouts included
    assert game_match_type({"match_type": "european_cup"}, _f(True)) == "european_cup"
    assert game_match_type({"match_type": "bogus"}, _f(False)) == "exhibition"


def test_club_leagues_in_the_data():
    import json, os
    from conftest import REAL_DATA
    for n in ("top_14", "pro14", "urc"):
        path = os.path.join(REAL_DATA, "competitions", n, f"{n}.json")
        if os.path.isfile(path):
            tpl = json.load(open(path, encoding="utf-8"))["template"]
            assert game_match_type(tpl, _f(True)) == "premiership"
