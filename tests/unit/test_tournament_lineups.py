"""app/tournament/lineups.py: a human team's default lineup is what every
match starts from; a match's own changes (match setup) and injuries never
rewrite it; lineups can be saved under a name and the played ones loaded."""
import copy

import pytest

from app.tournament import lineups
from app.tournament.model import Condition
from app.tournament.session import TournamentSession

TEMPLATE = {
    "id": "mini_cup", "name": "Mini Cup", "venue": "neutral",
    "stages": [{"id": "pools", "name": "Pool", "kind": "round_robin", "legs": 1}],
    "participants": {"default": {"pools": {"A": ["10002", "10001", "1015", "1010"]}}},
}
HUMAN = "10002"


@pytest.fixture
def session(ds, data_dir):
    return TournamentSession.new(ds, copy.deepcopy(TEMPLATE), "2024", humans=[HUMAN], seed=11)


def _entry(session):
    return session.t.teams[HUMAN]


def test_auto_until_a_lineup_is_set(session):
    assert lineups.is_auto(_entry(session))
    players = list(reversed(_entry(session).selection["players"]))
    session.set_selection(HUMAN, players)
    assert not lineups.is_auto(_entry(session))
    assert lineups.default(_entry(session))["players"] == players


def test_match_changes_do_not_reach_the_default(session):
    session.auto_select(HUMAN)
    default = list(lineups.default(_entry(session))["players"])
    session.advance_to_human()
    fixture = session.human_fixture()
    session.begin_game(fixture)
    swapped = list(_entry(session).selection["players"])
    swapped[0], swapped[1] = swapped[1], swapped[0]
    session.set_match_selection(HUMAN, swapped)
    assert _entry(session).selection["players"] == swapped           # this match
    assert lineups.default(_entry(session))["players"] == default    # not the default
    session.abandon_game()
    session.begin_game(fixture)
    assert _entry(session).selection["players"] == default


def test_an_injury_is_covered_without_rewriting_the_default(session):
    session.auto_select(HUMAN)
    default = list(lineups.default(_entry(session))["players"])
    hurt = session.t.players[default[9]]
    hurt.conditions.append(Condition(kind="injury", matches_left=2))
    session.advance_to_human()
    session.begin_game(session.human_fixture())
    assert hurt.pid not in _entry(session).selection["players"]
    assert lineups.default(_entry(session))["players"] == default


def test_save_rename_load_delete(session, ds):
    session.auto_select(HUMAN)
    best = list(lineups.default(_entry(session))["players"])
    session.save_lineup(HUMAN, "Best XV")
    session.set_selection(HUMAN, list(reversed(best)))
    assert lineups.matching(_entry(session), lineups.default(_entry(session))) is None
    session.rename_lineup(HUMAN, 0, "First choice")
    session.load_lineup(HUMAN, lineups.saved(_entry(session))[0])
    assert lineups.default(_entry(session))["players"] == best
    assert lineups.matching(_entry(session), lineups.default(_entry(session))) == 0
    reloaded = TournamentSession.load(session.t.id, ds)
    assert lineups.saved(reloaded.t.teams[HUMAN])[0]["name"] == "First choice"
    session.delete_lineup(HUMAN, 0)
    assert lineups.saved(_entry(session)) == []


def test_played_lineups_are_remembered(session):
    session.auto_select(HUMAN)
    session.advance_to_human()
    fixture = session.human_fixture()
    session.begin_game(fixture)
    played_xv = list(_entry(session).selection["players"])
    session.simulate(fixture)
    (f, sel), *_ = lineups.played(session.t, HUMAN)
    assert f.id == fixture.id and sel["players"] == played_xv
