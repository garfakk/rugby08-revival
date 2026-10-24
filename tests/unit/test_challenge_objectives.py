"""app/challenge_objectives.py: objectives judged from what R08_handler reads
back (timed score events, or the full-time sheet when the clock wasn't read).
The score the challenge starts on is history, never credited to the player."""
import pytest

from app import challenge_objectives as O


def ev(team, slot, kind, minute):
    return {"team": team, "slot": slot, "type": kind, "clock": minute * 60.0}


def result(events=None, home=0, away=0, rows=None):
    r = {"team_A": {"score": {"points": home}, "players": (rows or {}).get("home", [])},
         "team_B": {"score": {"points": away}, "players": (rows or {}).get("away", [])}}
    if events is not None:
        r["events"] = events
    return r


@pytest.mark.parametrize("obj,text", [
    ({"type": "score", "event": "try"}, "Score a try"),
    ({"type": "score", "event": "try", "count": 2}, "Score 2 tries"),
    ({"type": "score", "event": "penalty"}, "Kick a penalty"),
    ({"type": "score", "event": "drop_goal", "count": 3}, "Kick 3 drop goals"),
    ({"type": "score"}, "Score"),
    ({"type": "score", "count": 2}, "Score 2 times"),
    ({"type": "score", "event": "try", "player": 9, "before": 40}, "Score a try with #9 before 40'"),
    ({"type": "restrict", "event": "try", "max": 0}, "Concede no tries"),
    ({"type": "restrict", "max": 0}, "Keep the opponents scoreless"),
    ({"type": "restrict", "event": "penalty", "max": 2}, "Concede 2 penalties or fewer"),
    ({"type": "lead_at", "minute": 40}, "Lead at half-time"),
    ({"type": "lead_at", "minute": 60, "margin": 7}, "Lead by 7+ at 60'"),
    ({"type": "never_trail"}, "Never let the opponents take the lead"),
    ({"type": "win_by", "margin": 7}, "Win by 7 points or more"),
    ({"type": "win_by", "text": "Custom"}, "Custom"),
])
def test_describe(obj, text):
    assert O.describe(obj) == text


def test_describe_uses_names():
    obj = {"type": "score", "event": "try", "player": 10}
    assert O.describe(obj, names={"home": {10: "Carter"}}) == "Score a try with Carter (#10)"
    assert O.describe({"type": "never_trail"}, team_names={"away": "France"}) == \
        "Never let France take the lead"


def test_match_scores_timed_skips_starting_score():
    ch = {"mission_mode_time": 600, "score_events": [{"team": "home", "player": 10, "type": "SS_PENALTY"}]}
    events = [ev("team_A", 9, "penalty", 10), ev("team_A", 9, "try", 30), ev("team_B", 0, "try", 50)]
    scores, timed = O.match_scores(ch, result(events))
    assert timed
    assert [(s["side"], s["shirt"], s["type"]) for s in scores] == [("home", 10, "try"), ("away", 1, "try")]


def test_match_scores_untimed_from_sheet_minus_start():
    ch = {"score_events": [{"team": "home", "player": 1, "type": "SS_TRY"}]}
    rows = {"home": [{"tries": 2}], "away": [{"penalties_scored": 1}]}
    scores, timed = O.match_scores(ch, result(rows=rows))
    assert not timed
    assert sorted((s["side"], s["type"]) for s in scores) == [("away", "penalty"), ("home", "try")]


@pytest.mark.parametrize("obj,events,expected", [
    ({"type": "score", "event": "try"}, [ev("team_A", 0, "try", 10)], True),
    ({"type": "score", "event": "try"}, [ev("team_B", 0, "try", 10)], False),
    ({"type": "score", "event": "try", "player": 9}, [ev("team_A", 8, "try", 10)], True),
    ({"type": "score", "event": "try", "player": 9}, [ev("team_A", 7, "try", 10)], False),
    ({"type": "score", "event": "try", "before": 20}, [ev("team_A", 0, "try", 25)], False),
    ({"type": "score", "count": 2}, [ev("team_A", 0, "try", 1), ev("team_A", 0, "penalty", 2)], True),
    ({"type": "restrict", "event": "try", "max": 0}, [ev("team_B", 0, "try", 1)], False),
    ({"type": "restrict", "event": "points", "max": 3}, [ev("team_B", 0, "penalty", 1)], True),
    ({"type": "restrict", "event": "points", "max": 3}, [ev("team_B", 0, "try", 1)], False),
    ({"type": "lead_at", "minute": 40}, [ev("team_A", 0, "try", 30)], True),
    ({"type": "lead_at", "minute": 40}, [ev("team_A", 0, "try", 50)], False),
    # added time at the end of the first half: the clock stays at 40:00
    ({"type": "lead_at", "minute": 40}, [ev("team_A", 0, "try", 40)], True),
    ({"type": "lead_at", "minute": 60}, [ev("team_A", 0, "try", 60)], False),
    ({"type": "never_trail"}, [ev("team_A", 0, "try", 10), ev("team_B", 0, "penalty", 20)], True),
    ({"type": "never_trail"}, [ev("team_B", 0, "penalty", 10), ev("team_A", 0, "try", 20)], False),
])
def test_judge_timed(obj, events, expected):
    passed, note = O.judge(obj, {"user_side": "home"}, result(events))
    assert passed is expected, note


@pytest.mark.parametrize("obj", [
    {"type": "score", "event": "try", "before": 40},
    {"type": "lead_at", "minute": 40},
    {"type": "never_trail"},
])
def test_clock_dependent_objectives_unknown_without_clock(obj):
    passed, note = O.judge(obj, {}, result())
    assert passed is None and note == "match clock not read"


def test_win_by_uses_final_score_and_user_side():
    assert O.judge({"type": "win_by", "margin": 7}, {}, result(home=20, away=13))[0] is True
    assert O.judge({"type": "win_by", "margin": 7}, {}, result(home=20, away=14))[0] is False
    assert O.judge({"type": "win_by", "margin": 1}, {"user_side": "away"},
                   result(home=10, away=11))[0] is True


def test_never_trail_counts_starting_score():
    ch = {"score_events": [{"team": "away", "player": 1, "type": "SS_PENALTY"}]}
    passed, _ = O.judge({"type": "never_trail"}, ch, result([ev("team_B", 0, "penalty", 5)]))
    assert passed is False


def test_unknown_objective():
    assert O.judge({"type": "nope"}, {}, result([])) == (None, "unknown objective")


def test_judge_all():
    ch = {"match_objectives": [{"type": "win_by", "margin": 1}, {"type": "never_trail"}]}
    out = O.judge_all(ch, result([ev("team_A", 0, "try", 1)], home=5))
    assert [(o["type"], p) for o, p, _ in out] == [("win_by", True), ("never_trail", True)]
    assert O.judge_all({}, result()) == []
