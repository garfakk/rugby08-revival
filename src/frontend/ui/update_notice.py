"""
ui/update_notice.py — "UPDATE AVAILABLE" on the main menu.

A small plate in the "now playing" medal's style (ui/music.py TrackMedal),
parked against the bottom-right corner of the content column, above the
hint bar. It shows what the startup check found (program and/or data
version) and opens Tools > Updates on a click; pad users read where to go
(TOOLS › UPDATES). The owner shows it on the main menu only.
"""
from PyQt5.QtCore import QEvent, QPoint, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter
from PyQt5.QtWidgets import QWidget

from ui.broadcast import draw_frame, tracked_font
from ui.theme import BG_RAISED, BORDER, FG_MUTED, FG_PRIMARY, FONT_BODY, FONT_DISPLAY, GREEN


class UpdateNotice(QWidget):
    clicked = pyqtSignal()

    MARGIN = 26
    HEIGHT = 58

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCursor(Qt.PointingHandCursor)
        self._anchor = None
        self._line = ""
        self._eyebrow_font = tracked_font(FONT_BODY, 9, QFont.DemiBold, track=2.0)
        self._title_font = tracked_font(FONT_DISPLAY, 15, QFont.Bold, track=1.0)
        self.hide()

    @property
    def has_news(self):
        return bool(self._line)

    def set_result(self, result):
        """What a schedule.Result found; nothing found hides the notice."""
        parts = []
        if result and result.program and result.program.available:
            parts.append(f"PROGRAM {result.program.release.version}")
        if result and result.data and result.data.available:
            parts.append(f"DATA {result.data.release.version}")
        self._line = "  ·  ".join(parts)
        width = 30 + max(QFontMetrics(self._title_font).horizontalAdvance(self._line),
                         QFontMetrics(self._eyebrow_font).horizontalAdvance("UPDATE AVAILABLE  ·  TOOLS › UPDATES"))
        self.setFixedSize(max(240, min(width + 26, 560)), self.HEIGHT)
        self.reposition()

    def set_anchor(self, widget):
        self._anchor = widget
        widget.installEventFilter(self)
        self.reposition()

    def eventFilter(self, watched, event):
        if watched is self._anchor and event.type() in (QEvent.Resize, QEvent.Move):
            self.reposition()
        return super().eventFilter(watched, event)

    def reposition(self):
        parent = self.parentWidget()
        if parent is None:
            return
        from ui.broadcast import HintBar
        bars = [b.height() for b in parent.window().findChildren(HintBar) if b.isVisible()]
        right = parent.width()
        if self._anchor is not None:
            right = self._anchor.mapTo(parent, QPoint(self._anchor.width(), 0)).x()
        self.move(right - self.width() - self.MARGIN,
                  parent.height() - self.height() - self.MARGIN - (max(bars) if bars else 0))

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        rect = self.rect()
        p.fillRect(rect, QColor(BG_RAISED))
        draw_frame(p, rect, BORDER)
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(GREEN))
        p.setFont(self._eyebrow_font)
        p.setPen(QColor(GREEN))
        p.drawText(QRectF(18, 8, self.width() - 26, 13), Qt.AlignLeft | Qt.AlignVCenter, "UPDATE AVAILABLE")
        w = QFontMetrics(self._eyebrow_font).horizontalAdvance("UPDATE AVAILABLE")
        p.setPen(QColor(FG_MUTED))
        p.drawText(QRectF(18 + w, 8, self.width() - 26 - w, 13), Qt.AlignLeft | Qt.AlignVCenter,
                   "  ·  TOOLS › UPDATES")
        p.setFont(self._title_font)
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(17, 24, self.width() - 26, 24), Qt.AlignLeft | Qt.AlignVCenter, self._line)
