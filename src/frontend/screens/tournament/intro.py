"""
screens/tournament/intro.py — The few seconds between creating a tournament
and its dashboard: the competition's logo and name fade in, then the
dashboard opens by itself (a click or any key skips the wait).
"""
from PyQt5.QtCore import QEasingCurve, QPropertyAnimation, Qt, QTimer, pyqtProperty
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QWidget

from app.screen_base import Screen
from ui.broadcast import tracked_font
from ui.theme import ACCENT, BG_BASE, FG_PRIMARY, FG_SECONDARY, FONT_DISPLAY

from .common import competition_emblem

FADE_MS = 700
HOLD_MS = 1800


class TournamentIntroScreen(Screen):
    def __init__(self, ds, on_done):
        super().__init__()
        self.ds = ds
        self.on_done = on_done
        self._emblem = None
        self._title, self._edition, self._name = "", "", ""
        self._opacity = 0.0
        self._fade = QPropertyAnimation(self, b"opacity", self)
        self._fade.setDuration(FADE_MS)
        self._fade.setStartValue(0.0)
        self._fade.setEndValue(1.0)
        self._fade.setEasingCurve(QEasingCurve.OutCubic)
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._finish)
        self._pending = False

    def get_opacity(self):
        return self._opacity

    def set_opacity(self, v):
        self._opacity = v
        self.update()

    opacity = pyqtProperty(float, get_opacity, set_opacity)

    def set_session(self, session):
        t = session.t
        tpl = t.template
        self._emblem = competition_emblem(self.ds, tpl, 220)
        self._title = str(tpl.get("name", "")).upper()
        edition = str(tpl.get("branding_season") or "")
        self._edition = edition
        self._name = t.name.upper() if t.name and t.name.upper() != self._title else ""

    def on_show(self):
        super().on_show()
        self._pending = True
        self._opacity = 0.0
        self._fade.start()
        self._timer.start(FADE_MS + HOLD_MS)

    def _finish(self):
        if self._pending:
            self._pending = False
            self._timer.stop()
            self.on_done()

    def mousePressEvent(self, event):
        self._finish()

    def keyPressEvent(self, event):
        self._finish()
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_BASE))
        if self._emblem is None:
            return
        p.setOpacity(self._opacity)
        w, h = self.width(), self.height()
        slide = (1.0 - self._opacity) * 24
        top = h / 2 - 190 + slide
        p.drawPixmap(int((w - self._emblem.width()) / 2), int(top), self._emblem)
        y = top + self._emblem.height() + 28
        p.setFont(tracked_font(FONT_DISPLAY, 40, QFont.Bold, 3))
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(0, int(y), w, 56, Qt.AlignCenter, self._title)
        y += 68
        label = " · ".join(x for x in (self._edition, self._name) if x)
        if label:
            p.setFont(tracked_font(FONT_DISPLAY, 18, QFont.DemiBold, 4))
            p.setPen(QColor(ACCENT))
            p.drawText(0, int(y), w, 32, Qt.AlignCenter, label)
