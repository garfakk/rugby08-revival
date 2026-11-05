"""app/tournament/trophy.py: the trophy lift of a user's match — the final's
winner, or, in a competition with no final (Six Nations), whoever the
deciding match crowns."""
import copy

import pytest

from app.tournament import bridge, engine, trophy
from app.tournament.model import MatchResult, Tournament
from app.tournament.session import TournamentSession

TEAMS = ["10002", "10001", "1015", "1010"]
LEAGUE = {
    "id": "mini_league", "name": "Mini League", "venue": "neutral",
    "stages": [{"id": "pools", "name": "Table", "kind": "round_robin", "legs": 1}],
    "participants": {"default": {"pools": {"A": TEAMS}}},
}
CUP = dict(LEAGUE, id="mini_cup", stages=LEAGUE["stages"] + [
    {"id": "ko", "name": "Final", "kind": "knockout", "rounds": [
        {"id": "final", "name": "Final", "match_subtype": "final", "final": True,
         "ties": [["pools:A1", "pools:A2"]]}]}])


def _to_the_last_day(session):
    """Simulate everything before the user's last matchday."""
    t = session.t
    last = max(f.day for f in t.fixtures)
    while True:
        session.advance_to_human()
        f = session.human_fixture()
        assert f is not None
        if f.day == last:
            return f
        session.simulate(f)


def _score(home_pts, home_tries, away_pts, away_tries, fixture):
    return MatchResult(home=trophy._Side(fixture.home, home_pts, home_tries),
                       away=trophy._Side(fixture.away, away_pts, away_tries))


@pytest.fixture
def league(ds, data_dir):
    return TournamentSession.new(ds, copy.deepcopy(LEAGUE), "2024", humans=["10002"], seed=5)


def test_the_last_matchday_of_a_league_decides_it(league):
    f = _to_the_last_day(league)
    assert trophy.is_decider(league.t, f)
    assert not any(trophy.is_decider(league.t, g) for g in league.t.fixtures if g.day < f.day)


def test_the_days_other_matches_are_played_before_the_decider(league):
    f = _to_the_last_day(league)
    league.begin_game(f)
    others = [g for g in league.t.fixtures_on(f.day) if g is not f]
    assert others and all(g.played for g in others)
    assert not f.played


@pytest.mark.parametrize("seed", range(8))
def test_the_champion_lifts_on_every_result_that_crowns_it(ds, data_dir, seed):
    s = TournamentSession.new(ds, copy.deepcopy(LEAGUE), "2024", humans=["10002"], seed=seed)
    f = _to_the_last_day(s)
    s.begin_game(f)
    by_result = trophy.lifters(s.t, f)
    assert set(by_result) == set(trophy.RESULTS)
    samples = {"home_win": [(20, 3, 3, 0), (13, 1, 12, 1), (40, 6, 0, 0)],
               "away_win": [(3, 0, 20, 3), (12, 1, 13, 1), (0, 0, 40, 6)],
               "draw": [(10, 1, 10, 1), (25, 4, 25, 3)]}
    for result, scores in samples.items():
        for score in scores:
            t = Tournament.from_dict(copy.deepcopy(s.t.to_dict()))
            g = next(x for x in t.fixtures if x.id == f.id)
            g.result = _score(*score, g)          # the table only reads the score
            champion = engine.champion_of(t)
            lifter = by_result[result]
            if lifter:                       # this result crowns that side, whatever the score
                assert champion == (g.home if lifter == "home" else g.away)
            # no lifter: the champion is elsewhere, or depends on the score


def _crafted(ds, leader):
    """A league whose last matchday is all that is left; `leader` won every
    earlier match 40-0 with six tries."""
    t = engine.create_tournament(ds, copy.deepcopy(LEAGUE), "2024", seed=1)
    last = max(f.day for f in t.fixtures)
    for f in sorted(t.fixtures, key=lambda f: f.day):
        if f.day == last:
            break
        if f.involves(leader):
            score = (40, 6, 0, 0) if f.home == leader else (0, 0, 40, 6)
        else:
            score = (10, 1, 10, 1)
        f.result = _score(*score, f)
    return t, [f for f in t.fixtures if f.day == last]


def test_a_runaway_leader_lifts_even_when_it_loses(ds, data_dir):
    t, last_day = _crafted(ds, "10002")
    mine = next(f for f in last_day if f.involves("10002"))
    other = next(f for f in last_day if f is not mine)
    other.result = _score(10, 1, 10, 1, other)
    side = "home" if mine.home == "10002" else "away"
    assert trophy.lifters(t, mine) == {"home_win": side, "away_win": side, "draw": side}


def test_a_title_won_elsewhere_lifts_nothing(ds, data_dir):
    t, last_day = _crafted(ds, "10002")
    leader = next(f for f in last_day if f.involves("10002"))
    other = next(f for f in last_day if f is not leader)
    leader.result = (_score(40, 6, 0, 0, leader) if leader.home == "10002"
                     else _score(0, 0, 40, 6, leader))
    assert trophy.lifters(t, other) == {"home_win": None, "away_win": None, "draw": None}


def test_an_unplayed_match_of_the_day_leaves_it_open(ds, data_dir):
    t, last_day = _crafted(ds, "10002")
    assert trophy.lifters(t, last_day[0]) is None


def test_a_league_decider_turns_the_trophy_on(league, ds):
    f = _to_the_last_day(league)
    cfg, _ = league.begin_game(f)
    by_result = trophy.lifters(league.t, f)
    if any(by_result.values()):
        assert cfg.trophy_lift == "on"
        assert cfg.trophy_lifter == trophy.lifter_attr(by_result)
    else:
        assert cfg.trophy_lift == "stock" and cfg.trophy_lifter == ""


def test_an_earlier_league_match_lifts_nothing(league, ds):
    league.advance_to_human()
    f = league.human_fixture()
    cfg = bridge.to_match_config(ds, league.t, f)
    assert cfg.trophy_lift == "stock"


def test_a_final_lifts_for_its_winner(ds, data_dir):
    t = engine.create_tournament(ds, copy.deepcopy(CUP), "2024", humans=["10002"], seed=3)
    final = next(f for f in t.fixtures if f.final)
    final.home, final.away = "10002", "10001"
    cfg = bridge.to_match_config(ds, t, final)
    assert cfg.trophy_lift == "on" and cfg.trophy_lifter == ""
    assert trophy.lifters(t, final) is None          # a cup with a final has no decider


def test_lifter_attr():
    assert trophy.lifter_attr(dict(trophy.DEFAULT_LIFTERS)) == ""
    assert trophy.lifter_attr({"home_win": "home", "away_win": "home", "draw": "home"}) == \
        "home_win:home;away_win:home;draw:home"
    assert trophy.lifter_attr({"home_win": None, "away_win": "away", "draw": None}) == \
        "home_win:none;away_win:away;draw:none"


# ── expert mode: simulate to the title match ─────────────────────────────
def _mine(t, team):
    return [f for f in t.fixtures if f.played and f.involves(team)]


@pytest.mark.parametrize("seed", range(4))
def test_league_simulated_to_its_decider_for_the_title(ds, data_dir, seed):
    s = TournamentSession.new(ds, copy.deepcopy(LEAGUE), "2024", humans=["1015"], seed=seed)
    done = s.simulate_to_title_match(for_title=True)
    due = s.human_fixture()
    assert due is not None and trophy.is_decider(s.t, due) and not due.played
    assert done and all(f.result.winner_id() == "1015" for f in _mine(s.t, "1015"))
    assert not s.title_match_ahead()
    assert s.can_undo()


@pytest.mark.parametrize("seed", range(4))
def test_cup_simulated_to_the_users_final(ds, data_dir, seed):
    s = TournamentSession.new(ds, copy.deepcopy(CUP), "2024", humans=["10001"], seed=seed)
    s.simulate_to_title_match(for_title=True)
    due = s.human_fixture()
    assert due is not None and due.final and due.involves("10001") and not due.played


def test_as_simulated_stops_at_the_title_match_or_on_the_way_out(ds, data_dir):
    for seed in range(6):
        s = TournamentSession.new(ds, copy.deepcopy(CUP), "2024", humans=["10001"], seed=seed)
        s.simulate_to_title_match(for_title=False)
        due = s.human_fixture()
        if due is not None:
            assert due.final
        else:
            assert engine.is_eliminated(s.t, "10001")
            assert not any(f.final and f.played for f in s.t.fixtures)   # the rest is left to play


def test_nothing_to_do_once_the_title_match_is_due(ds, data_dir):
    s = TournamentSession.new(ds, copy.deepcopy(LEAGUE), "2024", humans=["10002"], seed=2)
    s.simulate_to_title_match(for_title=True)
    played = sum(f.played for f in s.t.fixtures)
    assert s.simulate_to_title_match(for_title=True) == []
    assert sum(f.played for f in s.t.fixtures) == played


# ── the game's competition stage (.mis matchsubtype) ─────────────────────
@pytest.mark.parametrize("given", ["none", None])
def test_table_matches_of_a_competition_are_pool_matches(ds, data_dir, given):
    """A competition match at stage 0 gets none of the game's competition
    commentary: a table round the template leaves at "none" goes out as pool."""
    tpl = copy.deepcopy(LEAGUE)
    tpl["match_type"] = "six_nations"
    if given:
        tpl["stages"][0]["match_subtype"] = given
    s = TournamentSession.new(ds, tpl, "2024", humans=["10002"], seed=1)
    s.advance_to_human()
    cfg, _ = s.begin_game(s.human_fixture())
    assert (cfg.match_type, cfg.match_subtype) == ("six_nations", "pool")


def test_a_final_is_a_final_and_a_friendly_has_no_stage(ds, data_dir):
    cup = copy.deepcopy(CUP)
    cup["match_type"] = "world_cup"
    t = engine.create_tournament(ds, cup, "2024", humans=["10002"], seed=3)
    final = next(f for f in t.fixtures if f.final)
    final.home, final.away, final.match_subtype = "10002", "10001", "none"
    assert bridge.to_match_config(ds, t, final).match_subtype == "final"
    league = engine.create_tournament(ds, copy.deepcopy(LEAGUE), "2024", seed=1)   # no match_type
    f = league.fixtures[0]
    assert bridge.to_match_config(ds, league, f).match_subtype in ("none", "pool")
    assert bridge.to_match_config(ds, league, f).match_type == "exhibition"
