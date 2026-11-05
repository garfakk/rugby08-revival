"""ui.motion's idle gate: background work waits for running animations, and
an animation started before its screen is painted starts on that paint."""
import pytest
from PyQt5.QtCore import QVariantAnimation
from PyQt5.QtWidgets import QWidget

pytestmark = pytest.mark.qt


@pytest.fixture
def motion_on(monkeypatch):
    from shared.user_prefs import user_prefs
    monkeypatch.setattr(user_prefs, "animations", True)
    from ui import motion
    return motion


def test_tracked_animation_counts_only_while_running(qapp, qtbot, motion_on):
    motion = motion_on
    anim = motion.track(QVariantAnimation())
    anim.setDuration(80)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    assert not motion.animating()            # tracked but not started
    anim.start()
    assert motion.animating()
    qtbot.waitUntil(lambda: anim.state() == anim.Stopped, timeout=2000)
    assert not motion.animating()


def test_when_idle_waits_for_the_animation(qapp, qtbot, motion_on):
    motion = motion_on
    anim = motion.track(QVariantAnimation())
    anim.setDuration(300)
    anim.setStartValue(0.0)
    anim.setEndValue(1.0)
    anim.start()
    ran = []
    motion.when_idle(lambda: ran.append(anim.state()), poll=20, settle=40)
    qtbot.waitUntil(lambda: bool(ran), timeout=3000)
    assert ran == [anim.Stopped]


def test_held_widget_counts_while_visible(qapp, qtbot, motion_on):
    motion = motion_on
    w = QWidget()
    qtbot.addWidget(w)
    motion.hold(w)
    assert not motion.animating()            # hidden: nothing on screen moves
    w.show()
    assert motion.animating()
    motion.release(w)
    assert not motion.animating()


def test_after_paint_waits_for_a_hidden_widget(qapp, qtbot, motion_on):
    motion = motion_on
    w = QWidget()
    qtbot.addWidget(w)
    ran = []
    motion.after_paint(w, lambda: ran.append(True))
    qtbot.wait(60)
    assert not ran                           # never painted yet
    w.show()
    qtbot.waitUntil(lambda: bool(ran), timeout=2000)


def test_stat_reveal_starts_on_screen(qapp, qtbot, motion_on):
    from ui.stat_compare import StatComparison
    s = StatComparison([("TRIES", 2, 1)])
    qtbot.addWidget(s)
    s.reveal()                               # filled before the screen shows
    qtbot.wait(60)
    assert s.get_progress() == 0.0
    s.show()
    qtbot.waitUntil(lambda: s.get_progress() == 1.0, timeout=3000)
