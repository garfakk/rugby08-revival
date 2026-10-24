"""
ui/intro.py — startup intro animation
==========================================
A ~7s overlay shown once over the already-built main menu at launch: a
floodlight-style accent line draws itself in, the wordmark and subtitle
fade up after it, a beat of held atmosphere, then the whole thing fades
out to reveal the app underneath. The fade-out waits for the app to be
built: on a slow start the title stays up (a quiet "LOADING" coming in after
a while) instead of the screen going blank. ESC skips to the end.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QGraphicsOpacityEffect,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import (
    Qt, QElapsedTimer, QPropertyAnimation, QTimer, QVariantAnimation, QSequentialAnimationGroup,
    QEasingCurve, pyqtSignal,
)

from ui.atmosphere import AtmosphereWidget
from ui.broadcast import display_label
from ui.theme import BG_BASE, ACCENT

LINE_WIDTH = 440

# Where the sequence in _start() stands still (ms from its start): the pause
# before the line, the one after it, and the hold up to the fade-out. Work
# that blocks the GUI thread is best done in these (see quiet_for): a frozen
# frame is invisible there, a stutter in the line or the fades is not.
QUIET_WINDOWS = ((0, 400), (1500, 1900), (3850, 5650))
FADE_OUT_AT = 5650
# Held on the title past FADE_OUT_AT this long (app still building) before
# the "LOADING" hint fades in.
LOADING_HINT_AFTER_MS = 1200


class IntroSplash(QWidget):
    """Owns its own teardown: connect `finished`, or just let it
    `deleteLater()` itself when the sequence (or a skip) ends."""

    finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget {{ background: {BG_BASE}; }}")
        self.setFocusPolicy(Qt.StrongFocus)

        # Same ambient floodlight/grain treatment the match screens use —
        # ties the intro to the app's own look rather than a bespoke one,
        # and its slow drift keeps the held beat from reading as a frozen
        # frame.
        self._atmosphere = AtmosphereWidget(self)
        self._atmosphere.lower()

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addStretch(1)

        line_row = QHBoxLayout()
        line_row.addStretch(1)
        self._line = QFrame()
        self._line.setFixedHeight(3)
        self._line.setFixedWidth(0)
        self._line.setStyleSheet(f"background: {ACCENT}; border: none;")
        line_row.addWidget(self._line)
        line_row.addStretch(1)
        v.addLayout(line_row)
        v.addSpacing(22)

        self._title = display_label("RUGBY 08", 60, QFont.Bold, track=4.0)
        self._title.setAlignment(Qt.AlignCenter)
        v.addWidget(self._title)
        v.addSpacing(6)

        self._subtitle = display_label("REVIVAL", 16, QFont.DemiBold,
                                       track=7.0, color=ACCENT)
        self._subtitle.setAlignment(Qt.AlignCenter)
        v.addWidget(self._subtitle)
        v.addStretch(1)

        self._loading = display_label("LOADING", 11, QFont.DemiBold, track=5.0)
        self._loading.setAlignment(Qt.AlignCenter)
        v.addWidget(self._loading)
        v.addSpacing(48)

        self._title_fx = QGraphicsOpacityEffect(self._title)
        self._title.setGraphicsEffect(self._title_fx)
        self._title_fx.setOpacity(0.0)

        self._subtitle_fx = QGraphicsOpacityEffect(self._subtitle)
        self._subtitle.setGraphicsEffect(self._subtitle_fx)
        self._subtitle_fx.setOpacity(0.0)

        self._loading_fx = QGraphicsOpacityEffect(self._loading)
        self._loading.setGraphicsEffect(self._loading_fx)
        self._loading_fx.setOpacity(0.0)

        # The final "fade out" is this plain solid-colour curtain fading IN
        # over everything, not the splash itself fading out — a
        # QGraphicsOpacityEffect on a widget with an actively-animating
        # child (the atmosphere's own repaint timer) causes Qt's effect
        # renderer and the child's own paintEvent to collide ("QPainter::
        # begin: A paint device can only be painted by one painter at a
        # time"). A leaf widget with no children/timers has no such risk.
        self._curtain = QWidget(self)
        self._curtain.setAttribute(Qt.WA_StyledBackground, True)
        self._curtain.setStyleSheet(f"background: {BG_BASE};")
        self._curtain_fx = QGraphicsOpacityEffect(self._curtain)
        self._curtain.setGraphicsEffect(self._curtain_fx)
        self._curtain_fx.setOpacity(0.0)

        self._group = None
        self._clock = None
        self._done = False
        self._skipped = False
        self._fading_out = False
        self._held_at = None      # clock time the title started waiting for the app
        self._loading_anim = None
        #: Optional callable; the splash stays up (covering the window) until
        #: it returns True — the app is still being built behind it.
        self.ready = None

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._atmosphere.setGeometry(self.rect())
        self._curtain.setGeometry(self.rect())
        self._curtain.raise_()

    def showEvent(self, event):
        super().showEvent(event)
        self._atmosphere.setGeometry(self.rect())
        self._curtain.setGeometry(self.rect())
        self._curtain.raise_()
        if self._group is None:
            self._start()
        self.setFocus()

    def quiet_for(self, ms):
        """True when the GUI thread may be kept busy for `ms` without the
        animation visibly stuttering: nothing moves for that long, or the
        sequence is in its fade-out (the caller is then holding the app up)."""
        if self._clock is None or self._skipped or self._held_at is not None:
            return True
        t = self._clock.elapsed()
        return t >= FADE_OUT_AT or any(a <= t and t + ms <= b for a, b in QUIET_WINDOWS)

    # ── sequence ─────────────────────────────────────────────────────────
    def _fade(self, effect, start, end, ms):
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(ms)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(QEasingCurve.InOutQuad)
        return anim

    def _start(self):
        line_anim = QVariantAnimation(self)
        line_anim.setDuration(1100)
        line_anim.setStartValue(0)
        line_anim.setEndValue(LINE_WIDTH)
        line_anim.setEasingCurve(QEasingCurve.OutCubic)
        line_anim.valueChanged.connect(self._line.setFixedWidth)

        seq = QSequentialAnimationGroup(self)
        seq.addPause(400)
        seq.addAnimation(line_anim)
        seq.addPause(400)
        seq.addAnimation(self._fade(self._title_fx, 0.0, 1.0, 850))
        seq.addPause(250)
        seq.addAnimation(self._fade(self._subtitle_fx, 0.0, 1.0, 850))
        seq.addPause(1800)  # hold — the fade-out (~0.9s) follows once the app is built
        seq.finished.connect(self._fade_out_when_ready)
        self._group = seq
        self._clock = QElapsedTimer()
        self._clock.start()
        seq.start()

    def _is_ready(self):
        return self.ready is None or self.ready()

    def _fade_out_when_ready(self):
        """End of the held beat: fade out once the app behind is built. Until
        then the title stays up — never a blank screen — and after a while a
        "LOADING" hint fades in under it."""
        if self._done or self._fading_out:
            return
        if not self._is_ready():
            now = self._clock.elapsed() if self._clock is not None else 0
            if self._held_at is None:
                self._held_at = now
            if self._loading_anim is None and now - self._held_at >= LOADING_HINT_AFTER_MS:
                self._loading_anim = self._fade(self._loading_fx, 0.0, 0.6, 600)
                self._loading_anim.start()
            QTimer.singleShot(30, self._fade_out_when_ready)
            return
        self._fading_out = True
        if self._loading_anim is not None:
            self._loading_anim.stop()
        curtain = self._fade(self._curtain_fx, self._curtain_fx.opacity(), 1.0, 900)
        curtain.finished.connect(self._finish)
        curtain.start()

    def _finish(self):
        if self._done:
            return
        self._done = True
        self.hide()
        self.finished.emit()
        self.deleteLater()

    # ── skip ─────────────────────────────────────────────────────────────
    # def mousePressEvent(self, event):
        # self._finish()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._skip()

    def _skip(self):
        """End the sequence now. If the app is not built yet, jump to the held
        title and fade out from there once it is, rather than going blank."""
        if self._skipped or self._fading_out:
            return
        self._skipped = True
        if self._group is not None:
            self._group.stop()
        if self._is_ready():
            self._curtain_fx.setOpacity(1.0)
            self._finish()
            return
        self._line.setFixedWidth(LINE_WIDTH)
        self._title_fx.setOpacity(1.0)
        self._subtitle_fx.setOpacity(1.0)
        self._fade_out_when_ready()
