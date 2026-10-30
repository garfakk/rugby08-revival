"""ui/coin_toss.py: the coin spins on its own, the result is YOU WON / YOU
LOST THE TOSS, the player only gets the choice that is theirs — one click
on the pitch — the other team's decisions are announced, and heads / tails
is never mentioned."""
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


def _wait_for_offer(overlay, timeout=3000):
    waited = 0
    while not overlay.pitch.options and not overlay._buttons and waited < timeout:
        QTest.qWait(10)
        waited += 10
    return overlay.pitch.options


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
    _wait_for_offer(overlay)
    texts.append(overlay.title.text() + overlay.sub.text())
    assert overlay.toss.face is not None
    assert not any(w in t.lower() for t in texts for w in ("heads", "tails", "call"))
    overlay.cancel()


def test_won_the_toss_one_click_on_an_end(qapp, host, fast):
    """Won: the ends and halfway are offered on the pitch; one click on an
    end takes it (the other team kicks off), then KICK OFF starts."""
    seed = _seed_where(lambda t: t.winner == "home")
    overlay, done = _run(host, fast, seed, {"home"})
    assert _wait_for_offer(overlay) == ["left", "kick", "right"]
    assert overlay._buttons == []
    assert "YOU WON THE TOSS" in overlay.title.text()
    assert "halfway" in overlay.sub.text()
    overlay.pitch.hover = "left"                           # hovered: the crests where it puts them
    assert overlay.pitch._shown() == ({"left": "home", "right": "away"}, "away")
    overlay.pitch.pick("left")
    assert "REDS" in overlay.title.text() and "KICK OFF" in overlay.title.text()
    assert _labels(overlay) == ["KICK OFF"]
    overlay._buttons[0].click()
    assert done == [{"kick_off": "away", "home_team_side": "left"}]


def test_won_the_toss_clicks_halfway_to_kick_off(qapp, host, fast):
    seed = _seed_where(lambda t: t.winner == "home")
    overlay, done = _run(host, fast, seed, {"home"})
    _wait_for_offer(overlay)
    overlay.pitch.hover = "kick"
    assert overlay.pitch._shown() == ({}, "home")          # you kick off, the ends still open
    overlay.pitch.pick("kick")
    assert "YOU KICK OFF" in overlay.title.text()
    assert _wait_for_buttons(overlay) == ["KICK OFF"]      # they picked their end
    overlay._buttons[0].click()
    assert done[0]["kick_off"] == "home"


def test_lost_the_toss_announces_their_choice(qapp, host, fast):
    # they chose to kick off: the player picks the end, on the pitch
    seed = _seed_where(lambda t: t.winner == "away" and t.decision == "kick off")
    overlay, done = _run(host, fast, seed, {"home"})
    assert _wait_for_offer(overlay) == ["left", "right"]
    assert "REDS" in overlay.title.text() and "CHOSE TO KICK OFF" in overlay.title.text()
    overlay.pitch.step(1)                                  # Left/Right step through the ends
    overlay.pitch.step(1)
    assert overlay.pitch.hover == "right"
    overlay.pitch.pick()
    overlay._buttons[0].click()
    assert done == [{"kick_off": "away", "home_team_side": "right"}]


def test_lost_the_toss_they_take_an_end(qapp, host, fast):
    seed = _seed_where(lambda t: t.winner == "away" and t.decision == "choose end")
    overlay, _done = _run(host, fast, seed, {"home"})
    assert _wait_for_buttons(overlay) == ["KICK OFF"]      # nothing left to choose
    assert overlay.pitch.options == []
    assert "REDS" in overlay.title.text() and "CHOSE THE" in overlay.title.text()
    assert overlay.sub.text() == "YOU KICK OFF"
    overlay.cancel()


def test_toss_keeps_the_wind_where_it_was_shown(ds, qapp, host, fast):
    """The pitch shows the wind as for home attacking right; home taking
    the other end turns the home-relative bearing round."""
    from conftest import make_match_config
    cfg = make_match_config(ds, wind_power=4, wind_dir_deg=90.0)
    cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}
    done = []
    overlay = fast.toss_for_match(host, ds, cfg, done.append)
    overlay._finish({"kick_off": "home", "home_team_side": "right"})
    assert done[0].wind_dir_deg == 270.0 and cfg.wind_dir_deg == 90.0
    overlay = fast.toss_for_match(host, ds, cfg, done.append)
    overlay._finish({"kick_off": "home", "home_team_side": "left"})
    assert done[1].wind_dir_deg == 90.0


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
