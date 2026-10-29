"""app/team_browse.py and season.nearest_season: the logic of the alternative
Quick Match pickers."""
from app.season import nearest_season
from app.team_browse import TeamIndex, competitions, family_of, search_match


def test_nearest_season():
    assert nearest_season(["2019", "2023", "2025"], "2023") == "2023"
    assert nearest_season(["2019", "2023", "2025"], "2021") == "2023"      # tie: the later
    assert nearest_season(["2019", "2023"], "2030") == "2023"
    assert nearest_season([], "2020") == ""
    assert nearest_season(["2019"], "x") == "2019"


def test_search_match():
    assert search_match("all bl", "All Blacks")
    assert search_match("", "Anything")
    assert not search_match("bl all x", "All Blacks")


def test_families_and_competitions():
    assert family_of("Pro14") == family_of("Celtic League") == "URC"
    assert family_of("Premiership") == "Premiership"
    comps = competitions({"six_nations_2024": {}, "other": {}}, lambda t: {"pools": {"A": ["1", 2]}})
    assert comps == {"Six Nations": {"1", "2"}}


def test_team_index(ds):
    ix = TeamIndex(ds)
    tid = ix.all_teams()[0]
    assert ix.seasons(tid) == sorted(ds.teams[tid])
    assert ix.like(tid)[0:1] and tid in ix.like(tid)
    assert ix.span(tid)
    filters = ix.filters()
    assert filters[0][0] == "ALL" and filters[0][1](tid)
    assert ix.info("nope") == {}
