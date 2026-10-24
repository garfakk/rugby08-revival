"""
ui/stat_compare.py — Home value | label | away value, with a split bar
showing each side's share. Used by the post-match screen and tournament
match reports.

`progress` (0..1) lets the rows be revealed: each bar grows out from the
centre and its numbers fade in, one row slightly after the other.
`reveal()` plays that (or jumps to the end with animations off).
"""
from PyQt5.QtCore import QEasingCurve, QRectF, Qt, QVariantAnimation, pyqtProperty
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QWidget

from ui import motion
from ui.broadcast import tracked_font
from ui.theme import AWAY_TINT, FG_PRIMARY, FG_SECONDARY, FONT_DISPLAY, HOME_TINT

ROW_H = 42
REVEAL_MS = 750
STAGGER = 0.35            # share of the reveal over which the rows' starts are spread


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _num(v):
    """A value is a number or "made/attempted" text; the bar uses the first part."""
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(str(v).split("/")[0])
    except ValueError:
        return 0.0


class StatComparison(QWidget):
    """Home value | label | away value, with a split bar showing the share."""

    def __init__(self, rows=(), parent=None, home_color=HOME_TINT, away_color=AWAY_TINT, row_h=ROW_H):
        super().__init__(parent)
        self._row_h = row_h
        self._progress = 1.0
        self._colors = (home_color, away_color)
        self._anim = None
        self.set_rows(list(rows))

    def set_rows(self, rows):
        self.rows = list(rows)          # [(label, home_value, away_value)]
        self.setMinimumHeight(len(self.rows) * self._row_h)
        self.update()

    def get_progress(self):
        return self._progress

    def set_progress(self, v):
        self._progress = float(v)
        self.update()

    progress = pyqtProperty(float, get_progress, set_progress)

    def reveal(self):
        if self._anim is not None:
            self._anim.stop()
        if not motion.enabled():
            self.set_progress(1.0)
            return
        self.set_progress(0.0)
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(REVEAL_MS)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setEasingCurve(QEasingCurve.Linear)
        self._anim.valueChanged.connect(lambda v: self.set_progress(float(v)))
        self._anim.start()

    def _row_progress(self, i):
        n = max(1, len(self.rows))
        start = STAGGER * i / n
        return _ease((self._progress - start) / (1.0 - STAGGER))

    def paintEvent(self, event):
        p = QPainter(self)
        mid = self.width() / 2
        y = 0
        for i, (label, hv, av) in enumerate(self.rows):
            k = self._row_progress(i)
            p.setOpacity(1.0)
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.DemiBold, track=2.0))
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(mid - 130, y, 260, 20), Qt.AlignCenter, label)

            p.setOpacity(k)
            p.setFont(tracked_font(FONT_DISPLAY, 16, QFont.Bold, track=0.4))
            p.setPen(QColor(FG_PRIMARY))
            p.drawText(QRectF(mid - 260, y, 110, 20), Qt.AlignRight | Qt.AlignVCenter, str(hv))
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(mid + 150, y, 110, 20), Qt.AlignLeft | Qt.AlignVCenter, str(av))

            p.setOpacity(1.0)
            h, a = _num(hv), _num(av)
            total = max(h + a, 1)
            bar_w = 220 * k
            bar_y = y + 24              # under the numbers (rows are >= 32 high)
            p.fillRect(QRectF(mid - 20 - bar_w * h / total, bar_y, bar_w * h / total, 5),
                       QColor(self._colors[0]))
            p.fillRect(QRectF(mid + 20, bar_y, bar_w * a / total, 5), QColor(self._colors[1]))
            y += self._row_h
