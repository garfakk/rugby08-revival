"""app/tournament/session.py: what the tournament screens drive — saving on
every step, one level of undo, the pre-match crash snapshot, forfeits and
manual results."""
import copy

import pytest

from app.tournament import bridge, persistence, standings
from app.tournament.session import TournamentSession
from backend import game_specific_variables as gsv
from shared.user_prefs import user_prefs

TEMPLATE = {
    "id": "mini_cup", "name": "Mini Cup", "venue": "neutral",
    "stages": [{"id": "pools", "name": "Pool", "kind": "round_robin", "legs": 1}],
    "participants": {"default": {"pools": {"A": ["10002", "10001", "1015", "1010"]}}},
}
HUMAN = "10002"


@pytest.fixture
def session(ds, data_dir):
    return TournamentSession.new(ds, copy.deepcopy(TEMPLATE), "2024", humans=[HUMAN], seed=11)


def _game_result(home_tries, away_tries):
    def side(key, tries):
        rows = [{"id": rid, "tries": 0, "tackles": 0} for rid in gsv.players_roster_id[key]]
        for row in rows[:tries]:
            row["tries"] = 1
        return {"players": rows, "stats": {}}
    return {"team_A": side("team_A", home_tries), "team_B": side("team_B", away_tries)}


def test_new_session_is_saved(session):
    assert [s["id"] for s in persistence.list_saves()] == [session.t.id]
    assert not session.can_undo()


def test_advance_and_undo(session, ds):
    played_before = sum(f.played for f in session.t.fixtures)
    session.advance_to_human()
    fixture = session.human_fixture()
    assert fixture is not None and fixture.involves(HUMAN)
    if sum(f.played for f in session.t.fixtures) > played_before:
        assert session.can_undo()
        assert session.undo()
        assert sum(f.played for f in session.t.fixtures) == played_before
        reloaded = TournamentSession.load(session.t.id, ds)
        assert reloaded.t.to_dict() == session.t.to_dict()
    assert session.undo() is False                       # one level only


def test_begin_and_finish_game(session, monkeypatch):
    monkeypatch.setattr(user_prefs, "wind_mode", "advanced", raising=False)
    session.advance_to_human()
    fixture = session.human_fixture()
    cfg, repairs = session.begin_game(fixture)
    assert persistence.has_snapshot(session.t.id, "prematch")    # crash during the game: recoverable
    assert cfg.wind_power is not None
    again, _ = session.begin_game(fixture)
    assert (again.wind_power, again.wind_dir_deg) == (cfg.wind_power, cfg.wind_dir_deg)  # seeded
    done = session.finish_game(fixture, _game_result(3, 0))
    assert done[0] is fixture and fixture.played
    assert (fixture.result.home.points, fixture.result.away.points) == (15, 0)
    assert not persistence.has_snapshot(session.t.id, "prematch")
    assert all(f.played for f in session.t.fixtures_on(fixture.day))   # rest of the day simulated


def test_standard_wind_leaves_game_wind(session, monkeypatch):
    monkeypatch.setattr(user_prefs, "wind_mode", "standard", raising=False)
    session.advance_to_human()
    cfg, _ = session.begin_game(session.human_fixture())
    assert cfg.wind_power is None
    session.abandon_game()
    assert not persistence.has_snapshot(session.t.id, "prematch")


def test_forfeit(session):
    session.advance_to_human()
    fixture = session.human_fixture()
    session.forfeit(fixture, HUMAN)
    assert fixture.played and fixture.result.winner_id() != HUMAN
    stage = session.t.stage("pools")
    row = {r.team_id: r for r in standings.group_table(session.t, stage, stage.group("A"))}[HUMAN]
    assert row.lost >= 1


def test_simulate_human_fixture_and_to_end(session):
    session.advance_to_human()
    session.simulate(session.human_fixture())
    session.simulate_to_end()
    assert session.t.finished
    assert session.can_undo()


def test_set_selection_and_auto_select(session):
    entry = session.t.teams[HUMAN]
    players = list(reversed(entry.selection["players"]))
    errors, warnings = session.set_selection(HUMAN, players)
    assert errors == [] and session.t.teams[HUMAN].selection["manual"]
    assert warnings                                              # reversed: out of position
    sel = session.auto_select(HUMAN)
    assert sel["manual"] and len(sel["players"]) == 22
    assert persistence.load(session.t.id).teams[HUMAN].selection == sel
