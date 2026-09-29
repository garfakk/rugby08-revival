"""
ui/intro.py — startup intro animation
==========================================
A ~7s overlay shown once over the already-built main menu at launch: a
floodlight-style accent line draws itself in, the wordmark and subtitle
fade up after it, a beat of held atmosphere, then the whole thing fades
out to reveal the app underneath. Click/tap or any key skips straight to
the end.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFrame, QGraphicsOpacityEffect,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import (
    Qt, QPropertyAnimation, QVariantAnimation, QSequentialAnimationGroup,
    QEasingCurve, pyqtSignal,
)

from ui.atmosphere import AtmosphereWidget
from ui.broadcast import display_label
from ui.theme import BG_BASE, ACCENT

LINE_WIDTH = 440


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

        self._title_fx = QGraphicsOpacityEffect(self._title)
        self._title.setGraphicsEffect(self._title_fx)
        self._title_fx.setOpacity(0.0)

        self._subtitle_fx = QGraphicsOpacityEffect(self._subtitle)
        self._subtitle.setGraphicsEffect(self._subtitle_fx)
        self._subtitle_fx.setOpacity(0.0)

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
        self._done = False

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
        seq.addPause(1800)  # hold — total sequence lands at ~6.6s
        seq.addAnimation(self._fade(self._curtain_fx, 0.0, 1.0, 900))
        seq.finished.connect(self._finish)
        self._group = seq
        seq.start()

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
            self._finish()
