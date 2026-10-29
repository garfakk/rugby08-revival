"""
ui/motion.py — small, reusable entrance motions: a fade, and a row of
cards fading in one after the other.

A fade is a curtain: a child widget over the target, painted in the
screen's background colour and thinning out to nothing, then deleted. Not a
QGraphicsOpacityEffect: those can't be nested (a page fading while its cards
fade in crashed Qt), render their widget through an offscreen pixmap, and
clip children that paint outside it. The catch: the target should sit on
the plain background colour, as the screens' bodies do.

Nothing happens with animations off (user_prefs.animations): callers never
branch on it themselves.
"""
from PyQt5.QtCore import QEasingCurve, QEvent, Qt, QTimer, QVariantAnimation
from PyQt5.QtGui import QColor, QPainter
from PyQt5.QtWidgets import QWidget

from shared.user_prefs import user_prefs
from ui.theme import BG_BASE


def enabled() -> bool:
    return bool(getattr(user_prefs, "animations", True))


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
