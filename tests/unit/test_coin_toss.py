"""app/coin_toss.py: Law 6.3 — the toss winner kicks off or picks an end, and
the kicking side is never the end-chooser."""
import itertools
import random

import pytest

from app import coin_toss as T


def test_flip_requires_a_call():
    with pytest.raises(AssertionError):
        T.CoinToss(rng=random.Random(1)).flip()


def test_resolved_requires_an_end():
    t = T.CoinToss(call=T.HEADS, face=T.HEADS, decision=T.KICK_OFF)
    with pytest.raises(AssertionError):
        t.resolved()


@pytest.mark.parametrize("call,face,winner", [
    (T.HEADS, T.HEADS, "away"), (T.TAILS, T.TAILS, "away"),
    (T.HEADS, T.TAILS, "home"), (T.TAILS, T.HEADS, "home"),
])
def test_caller_wins_when_call_matches(call, face, winner):
    assert T.CoinToss(call=call, face=face).winner == winner


@pytest.mark.parametrize("call,face,decision,end",
                         list(itertools.product([T.HEADS, T.TAILS], [T.HEADS, T.TAILS],
                                           [T.KICK_OFF, T.CHOOSE_END], [T.LEFT, T.RIGHT])))
def test_every_outcome(call, face, decision, end):
    t = T.CoinToss(call=call, face=face, decision=decision, end=end)
    assert t.kicker != t.end_chooser
    if decision == T.KICK_OFF:
        assert t.kicker == t.winner
    else:
        assert t.end_chooser == t.winner
    r = t.resolved()
    assert r["kick_off"] == t.kicker
    home_end = end if t.end_chooser == "home" else ({T.LEFT: T.RIGHT, T.RIGHT: T.LEFT}[end])
    assert r["home_team_side"] == home_end


def test_unresolved_steps_are_none():
    t = T.CoinToss()
    assert t.winner is None and t.end_chooser is None and t.kicker is None


def test_seeded_rng_is_reproducible():
    def run(seed):
        t = T.CoinToss(rng=random.Random(seed))
        t.call = t.cpu_call()
        t.flip()
        t.decision = t.cpu_decision()
        t.end = t.cpu_end()
        return t.resolved()
    assert run(7) == run(7)
    assert {run(s)["kick_off"] for s in range(40)} == {"home", "away"}
