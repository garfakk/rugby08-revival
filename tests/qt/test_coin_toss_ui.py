"""ui/coin_toss.py: the coin spins on its own, the result is YOU WON / YOU
LOST THE TOSS, the player only gets the choice that is theirs, the other
team's decisions are announced, and heads / tails is never mentioned."""
import random

import pytest
from PyQt5.QtTest import QTest

pytestmark = pytest.mark.qt


@pytest.fixture
def fast(monkeypatch):
    from ui import coin_toss as ui
    monkeypatch.setattr(ui, "CPU_BEAT_MS", 5)
    monkeypatch.setattr(ui, "CALL_BEAT_MS", 5)
    monkeypatch.setattr(ui, "FLIP_MS", 20)
    return ui


@pytest.fixture
def host(qapp):
    from app.screen_base import Screen
    s = Screen()
    s.resize(1280, 800)
    s.show()
    yield s
    s.close()
    s.deleteLater()


def _run(host, fast, seed, humans):
    from app.coin_toss import CoinToss
    done = []
    overlay = fast.CoinTossOverlay(host, {"home": "Blues", "away": "Reds"}, humans, done.append,
                                   toss=CoinToss(rng=random.Random(seed)))
    overlay.start()
    return overlay, done


def _labels(overlay):
    return [b.text() for b in overlay._buttons]


def _wait_for_buttons(overlay, timeout=3000):
    waited = 0
    while not overlay._buttons and waited < timeout:
        QTest.qWait(10)
        waited += 10
    return _labels(overlay)


def _seed_where(predicate):
    from app.coin_toss import CoinToss
    for seed in range(200):
        t = CoinToss(rng=random.Random(seed))
        t.call = t.cpu_call()
        t.flip()
        t.decision = t.cpu_decision()
        if predicate(t):
            return seed
    raise AssertionError("no seed")


def test_no_call_to_make_the_coin_spins_by_itself(qapp, host, fast):
    overlay, _done = _run(host, fast, 1, {"away"})        # the player is the caller
    assert overlay._buttons == []                          # no HEADS / TAILS to press
    texts = [overlay.title.text() + overlay.sub.text()]
    _wait_for_buttons(overlay)
    texts.append(overlay.title.text() + overlay.sub.text())
    assert overlay.toss.face is not None
    assert not any(w in t.lower() for t in texts for w in ("heads", "tails", "call"))
    overlay.cancel()


def test_won_the_toss_offers_kick_off_or_end(qapp, host, fast):
    seed = _seed_where(lambda t: t.winner == "home")
    overlay, done = _run(host, fast, seed, {"home"})
    assert _wait_for_buttons(overlay) == ["KICK OFF", "CHOOSE END"]
    assert "YOU WON THE TOSS" in overlay.title.text() and overlay.sub.text() == ""
    overlay._buttons[1].click()                            # choose an end
    assert "CHOOSE YOUR END" in overlay.title.text()
    assert "LEFT END" in _labels(overlay)[0]
    overlay._buttons[0].click()
    assert "REDS" in overlay.title.text() and "KICK OFF" in overlay.title.text()
    overlay._buttons[0].click()                            # CONTINUE
    assert done == [{"kick_off": "away", "home_team_side": "left"}]


def test_lost_the_toss_announces_their_choice(qapp, host, fast):
    # they chose to kick off: the player picks the end
    seed = _seed_where(lambda t: t.winner == "away" and t.decision == "kick off")
    overlay, done = _run(host, fast, seed, {"home"})
    _wait_for_buttons(overlay)
    assert "REDS" in overlay.title.text() and "CHOSE TO KICK OFF" in overlay.title.text()
    assert "LEFT END" in _labels(overlay)[0]
    overlay._buttons[1].click()
    overlay._buttons[0].click()
    assert done == [{"kick_off": "away", "home_team_side": "right"}]


def test_lost_the_toss_they_take_an_end(qapp, host, fast):
    seed = _seed_where(lambda t: t.winner == "away" and t.decision == "choose end")
    overlay, _done = _run(host, fast, seed, {"home"})
    assert _wait_for_buttons(overlay) == ["CONTINUE"]      # nothing left to choose
    assert "REDS" in overlay.title.text() and "CHOSE THE" in overlay.title.text()
    assert overlay.sub.text() == "YOU KICK OFF"
    overlay.cancel()


def test_lost_message_is_shown_while_they_decide(qapp, host, fast, monkeypatch):
    monkeypatch.setattr(fast, "CPU_BEAT_MS", 2000)       # long enough to read it
    seed = _seed_where(lambda t: t.winner == "away")
    overlay, _done = _run(host, fast, seed, {"home"})
    waited = 0
    while "LOST" not in overlay.title.text() and waited < 2000:
        QTest.qWait(10)
        waited += 10
    assert "YOU LOST THE TOSS" in overlay.title.text()
    assert overlay.sub.text() == "" and overlay._buttons == []     # their choice comes after a beat
    overlay.cancel()
