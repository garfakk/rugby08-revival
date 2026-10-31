"""
ui/checklist.py — A list of objectives as tick boxes: empty before the
match, ticked for the ones met after it (a challenge's objectives).
"""
from PyQt5.QtCore import QPointF, QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QHBoxLayout, QLabel, QVBoxLayout, QWidget

from ui.broadcast import label_css
from ui.theme import FG_MUTED, FG_PRIMARY, FG_SECONDARY, FONT_DISPLAY, GREEN

BOX = 18


class TickBox(QWidget):
    """A box, empty or ticked; painted, never focused."""

    def __init__(self, ticked=False, parent=None):
        super().__init__(parent)
        self.ticked = ticked
        self.setFixedSize(BOX + 2, BOX + 2)
        self.setAttribute(Qt.WA_TranslucentBackground, True)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        box = QRectF(1, 1, BOX, BOX)
        if self.ticked:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(GREEN))
            p.drawRoundedRect(box, 3, 3)
            tick = QPainterPath(QPointF(box.left() + 4, box.center().y()))
            tick.lineTo(box.left() + 7.5, box.bottom() - 4.5)
            tick.lineTo(box.right() - 3.5, box.top() + 4.5)
            p.setPen(QPen(QColor("#0b130b"), 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(Qt.NoBrush)
            p.drawPath(tick)
        else:
            p.setPen(QPen(QColor(FG_MUTED), 1.6))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(box.adjusted(0.8, 0.8, -0.8, -0.8), 3, 3)
        p.end()


class CheckList(QWidget):
    """One row per line: a tick box, then the line (wrapped)."""

    def __init__(self, size=14, parent=None):
        super().__init__(parent)
        self.setObjectName("checkList")
        self.setStyleSheet("QWidget#checkList { background: transparent; }")
        self._size = size
        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.setSpacing(8)
        self.boxes = []

    def set_items(self, lines, ticked=None):
        """`ticked`: one bool per line (None: every box empty)."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        ticked = list(ticked) if ticked is not None else [False] * len(lines)
        self.boxes = []
        for line, ok in zip(lines, ticked):
            row = QWidget()
            row.setStyleSheet("background: transparent;")
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(12)
            box = TickBox(ok)
            h.addWidget(box, alignment=Qt.AlignTop)
            text = QLabel(line)
            text.setWordWrap(True)
            text.setStyleSheet(label_css(self._size, QFont.DemiBold,
                                         FG_PRIMARY if ok else FG_SECONDARY, FONT_DISPLAY))
            h.addWidget(text, stretch=1)
            self._layout.addWidget(row)
            self.boxes.append(box)

    def ticked(self):
        return [b.ticked for b in self.boxes]
