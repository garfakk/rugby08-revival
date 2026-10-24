"""backend/lineup_tracker.py: substitutions, re-entries, positional moves,
cards and injuries told apart from snapshots of the positions, and each
player's time on the pitch per position."""
import pytest

from backend.lineup_tracker import LineupTracker


def lineup(ids, off=()):
    """Positions 1..15 held by `ids` (a dict pos -> id overrides the default)."""
    return {pos: {'id': pid, 'off': pid in off} for pos, pid in ids.items()}


START = {pos: 100 + pos for pos in range(1, 16)}


def records(**fields):
    """{id: {"red", "injury"}} for the 22 of a squad, with overrides id=(red, injury)."""
    out = {100 + i: {'red': 0, 'injury': 0} for i in range(1, 23)}
    for key, (red, injury) in fields.items():
        out[int(key[1:])] = {'red': red, 'injury': injury}
    return out


@pytest.fixture
def tracker():
    t = LineupTracker()
    t.update(0.0, 0, 0.0, {'team_A': lineup(START)}, {'team_A': records()})
    return t


def step(t, minute, ids, off=(), recs=None):
    t.update(minute * 60.0, 0 if minute < 40 else 1, minute * 7.5,
             {'team_A': lineup(ids, off)}, {'team_A': recs or records()})
    return [{k: v for k, v in e.items() if k not in ('team', 'period')} for e in t.events]


def test_starting_lineup_and_full_match(tracker):
    step(tracker, 80, START)
    played = tracker.summary('team_A')
    assert tracker.starting['team_A'][10]['id'] == 110
    assert played[110] == {'seconds': 4800.0, 'real_seconds': 600.0,
                           'positions': {10: 4800.0}, 'real_positions': {10: 600.0}}
    assert tracker.events == []


def test_substitution(tracker):
    events = step(tracker, 50, {**START, **{2: 116}})
    assert events == [{'type': 'sub', 'clock': 3000.0, 'on_id': 116, 'off_id': 102,
                       'position': 2, 'injury': False}]
    step(tracker, 80, {**START, **{2: 116}})
    played = tracker.summary('team_A')
    assert played[102]['seconds'] == 3000.0 and played[116]['positions'] == {2: 1800.0}


def test_injury_replacement(tracker):
    step(tracker, 20, START, recs=records(i107=(0, 1)))
    events = step(tracker, 21, {**START, **{7: 120}}, recs=records(i107=(0, 1)))
    assert events[0] == {'type': 'injury', 'clock': 1200.0, 'id': 107, 'position': 7}
    assert events[1]['type'] == 'sub' and events[1]['injury'] is True and events[1]['off_id'] == 107


def test_positional_swap_without_leaving(tracker):
    events = step(tracker, 30, {**START, **{12: 113, 13: 112}})
    assert events == [{'type': 'move', 'clock': 1800.0, 'id': 113, 'from': 13, 'to': 12},
                      {'type': 'move', 'clock': 1800.0, 'id': 112, 'from': 12, 'to': 13}]
    step(tracker, 80, {**START, **{12: 113, 13: 112}})
    assert tracker.summary('team_A')[112]['positions'] == {12: 1800.0, 13: 3000.0}


def test_sub_that_moves_another_player(tracker):
    """The 22 comes on at 15 and the 15 moves to wing: one sub, one move."""
    events = step(tracker, 60, {**START, **{15: 122, 14: 115}})
    assert {e['type'] for e in events} == {'sub', 'move'}
    sub = next(e for e in events if e['type'] == 'sub')
    assert (sub['on_id'], sub['off_id'], sub['position']) == (122, 114, 15)


def test_reentry(tracker):
    step(tracker, 30, {**START, **{3: 117}})
    events = step(tracker, 70, START)
    assert events[-1]['type'] == 'reentry' and events[-1]['on_id'] == 103 and events[-1]['off_id'] == 117


def test_sin_bin_flag(tracker):
    events = step(tracker, 30, START, off={106})
    assert events == [{'type': 'sin_bin', 'clock': 1800.0, 'id': 106, 'position': 6}]
    events = step(tracker, 50, START)
    assert events[-1] == {'type': 'return', 'clock': 3000.0, 'id': 106, 'position': 6}
    step(tracker, 80, START)
    assert tracker.summary('team_A')[106]['seconds'] == 4800.0 - 1200.0


def test_red_card_flag(tracker):
    events = step(tracker, 30, START, off={104}, recs=records(i104=(1, 0)))
    assert events == [{'type': 'red_card', 'clock': 1800.0, 'id': 104, 'position': 4}]


def test_emptied_position_then_back(tracker):
    """If the game empties the position for a sin bin instead of flagging the player."""
    ids = dict(START)
    del ids[6]
    assert step(tracker, 30, ids)[-1] == {'type': 'off', 'clock': 1800.0, 'id': 106, 'position': 6}
    assert step(tracker, 50, START)[-1] == {'type': 'return', 'clock': 3000.0, 'id': 106, 'position': 6}


def test_stopped_clock_credits_nothing(tracker):
    step(tracker, 40, START)
    step(tracker, 40, START)        # half time: clock held at 40:00
    assert tracker.summary('team_A')[101]['seconds'] == 2400.0
