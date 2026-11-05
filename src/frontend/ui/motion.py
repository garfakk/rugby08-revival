"""
ui/motion.py — small, reusable entrance motions: a fade, and a row of
cards fading in one after the other.

A fade is a curtain: a child widget over the target, painted in the
screen's background colour and thinning out to nothing, then deleted. Not a
QGraphicsOpacityEffect: those can't be nested (a page fading while its cards
fade in crashed Qt), render their widget through an offscreen pixmap, and
clip children that paint outside it. The catch: the target should sit on
the plain background colour, as the screens' bodies do.

Nothing happens with animations off (user_prefs.animations, Settings >
Advanced): callers never branch on it themselves; other Qt animations take
their duration from ms().

Running animations say so (hold/release, or track() on a Qt animation):
idle-time work — prewarming caches, building hidden screens — asks
animating() first and waits (when_idle), so it never lands mid-motion.
"""
import weakref

from PyQt5.QtCore import QAbstractAnimation, QEasingCurve, QEvent, QObject, Qt, QTimer, QVariantAnimation
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget

from shared.user_prefs import user_prefs
from ui.theme import BG_BASE


def enabled() -> bool:
    return bool(getattr(user_prefs, "animations", True))


# ── what is moving right now ─────────────────────────────────────────────
_running = weakref.WeakSet()


def hold(obj):
    """`obj` (any QObject) is animating until release(obj) or its deletion."""
    _running.add(obj)


def release(obj):
    _running.discard(obj)


def animating() -> bool:
    for obj in list(_running):
        try:
            if isinstance(obj, QAbstractAnimation):
                if obj.state() == QAbstractAnimation.Running:
                    return True
            elif obj.isVisible() if isinstance(obj, QWidget) else True:
                return True
        except RuntimeError:            # the C++ side is gone
            _running.discard(obj)
    return False


def track(anim):
    """Count a QAbstractAnimation as animating while it runs."""
    hold(anim)
    return anim


def when_idle(fn, delay=0, poll=120, settle=250):
    """Call `fn` once nothing has animated for `settle` ms (checked every
    `poll` ms), at the earliest after `delay` ms."""
    state = {"quiet": 0}

    def check():
        if animating():
            state["quiet"] = 0
        else:
            state["quiet"] += poll
            if state["quiet"] >= settle:
                fn()
                return
        QTimer.singleShot(poll, check)
    QTimer.singleShot(delay, check)


def after_paint(widget, fn, delay=0):
    """Call `fn` once `widget` has been painted (then `delay` ms more): an
    animation started from here begins on a frame the user can see, rather
    than spending its first frames behind the screen's own first paint.
    A hidden widget waits for the paint that comes with showing it."""
    if widget is None:
        QTimer.singleShot(delay, fn)
        return

    class _Once(QObject):
        def eventFilter(self, watched, event):
            if event.type() == QEvent.Paint:
                watched.removeEventFilter(self)
                QTimer.singleShot(delay, fn)
                self.deleteLater()
            return False
    f = _Once(widget)
    widget.installEventFilter(f)
    widget.update()


def ms(duration):
    """An animation's duration, 0 with animations off: a Qt animation of
    0 ms jumps straight to its end value (and still emits finished)."""
    return duration if enabled() else 0


class _Curtain(QWidget):
    """Covers its parent in `color`, from opaque to clear, then goes away.
    Clicks go through it: the target is usable while it fades."""

    def __init__(self, target, ms, delay, color):
        super().__init__(target)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self._color = QColor(color)
        self._alpha = 1.0
        self.setGeometry(target.rect())
        target.installEventFilter(self)
        self.show()
        self.raise_()
        hold(self)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(ms)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.0)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self._anim.valueChanged.connect(self._set_alpha)
        self._anim.finished.connect(self._done)
        if delay:
            # owned by the curtain: gone with it if the target is deleted first
            self._wait = QTimer(self)
            self._wait.setSingleShot(True)
            self._wait.timeout.connect(self._anim.start)
            self._wait.start(delay)
        else:
            self._anim.start()

    def _set_alpha(self, v):
        self._alpha = float(v)
        self.update()

    def _done(self):
        release(self)
        target = self.parentWidget()
        if target is not None:
            target.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
        return False

    def paintEvent(self, event):
        if self._alpha <= 0:
            return
        c = QColor(self._color)
        c.setAlphaF(max(0.0, min(1.0, self._alpha)))
        QPainter(self).fillRect(self.rect(), c)


def fade_in(widget, ms=220, delay=0, color=BG_BASE):
    """Fade a visible widget in from the background colour."""
    if not enabled() or widget is None or not widget.isVisible():
        return None
    for old in widget.findChildren(_Curtain, options=Qt.FindDirectChildrenOnly):
        old._done()                           # a fade restarted: one curtain at a time
    return _Curtain(widget, ms, delay, color)


def stagger_in(widgets, step=45, ms=260, start=0):
    """Fade a row of widgets in one after the other."""
    if not enabled():
        return
    for i, w in enumerate(w for w in widgets if w is not None):
        fade_in(w, ms=ms, delay=start + i * step)
