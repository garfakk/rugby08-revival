"""
screens/tournament/pitch.py — a matchday XV on a pitch, the bench below.

Slots follow shirt numbers: 1-15 laid out in the standard formation
(forwards up front, back three deep), 16-22 in a row of replacements. Each
token shows the number, the player's surname, a value chip (rating, stat)
and a ring in the slot's state colour (fit, out of position, unavailable).

Interactive: click / arrows pick a slot (`slot_selected`), Enter or a
double-click activates it (`slot_activated`). The arrows leave the widget
at its edges so the screen's focus can move on.
"""
from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QBrush, QColor, QFont, QFontMetrics, QLinearGradient, QPainter, QPen
from PyQt5.QtWidgets import QSizePolicy, QWidget

from ui.broadcast import tracked_font
from ui.theme import (ACCENT, BG_BASE, BG_CARD, FG_MUTED, FG_PRIMARY, FG_SECONDARY,
                      FG_TERTIARY, FONT_DISPLAY)

# Shirt number -> (x, y) on the pitch, 0..1 (y = 0 is the front row).
FORMATION = {
    1: (0.30, 0.06), 2: (0.50, 0.06), 3: (0.70, 0.06),
    4: (0.38, 0.19), 5: (0.62, 0.19),
    6: (0.18, 0.30), 8: (0.50, 0.33), 7: (0.82, 0.30),
    9: (0.58, 0.46),
    10: (0.44, 0.57),
    12: (0.31, 0.67), 13: (0.18, 0.77),
    11: (0.05, 0.88), 14: (0.95, 0.88),
    15: (0.50, 0.93),
}
TOKEN_R = 17


def surname(name):
    """"J.Wilkinson" / "Jonny Wilkinson" -> "Wilkinson"."""
    name = (name or "").strip()
    if "." in name.split(" ")[0]:
        name = name.split(".", 1)[1]
    return name.split(" ")[-1] if " " in name else name


class LineupPitch(QWidget):
    slot_selected = pyqtSignal(int)
    slot_activated = pyqtSignal(int)

    def __init__(self, interactive=True, bench=True, parent=None):
        super().__init__(parent)
        self.interactive = interactive
        self.bench = bench
        self.slots = []        # [{name, sub, value, ring, faded}]
        self.current = 0 if interactive else None
        self._hover = None
        self.setFocusPolicy(Qt.StrongFocus if interactive else Qt.NoFocus)
        self.setMouseTracking(interactive)
        self.setMinimumSize(420, 560 if bench else 470)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def set_slots(self, slots):
        self.slots = list(slots)
        self.update()

    def set_current(self, i):
        self.current = i
        self.update()

    # ── geometry ─────────────────────────────────────────────────────────
    def _pitch_rect(self):
        bench_h = 96 if self.bench else 0
        h = self.height() - bench_h - 4
        w = min(self.width() - 4, h * 1.1)
        return QRectF((self.width() - w) / 2, 2, w, h)

    def _centers(self):
        r = self._pitch_rect()
        out = []
        inner = r.adjusted(46, 30, -46, -44)
        for n in range(1, 16):
            x, y = FORMATION[n]
            out.append(QPointF(inner.x() + inner.width() * x, inner.y() + inner.height() * y))
        if self.bench:
            n = 7
            span = min(self.width() - 60, 7 * 92)
            x0 = (self.width() - span) / 2 + span / n / 2
            y = self.height() - 56
            out += [QPointF(x0 + i * span / n, y) for i in range(n)]
        return out

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self._pitch_rect()
        grad = QLinearGradient(r.topLeft(), r.bottomLeft())
        grad.setColorAt(0, QColor("#13612a"))
        grad.setColorAt(1, QColor("#0e4f20"))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(grad))
        p.drawRect(r)
        stripes = 8
        for i in range(stripes):
            if i % 2:
                p.fillRect(QRectF(r.x(), r.y() + r.height() * i / stripes, r.width(), r.height() / stripes),
                           QColor(255, 255, 255, 10))
        line = QPen(QColor(255, 255, 255, 120), 1.2)
        p.setPen(line)
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(6, 6, -6, -6))
        # half of a pitch, attacking up: halfway line at the top, our 22 and
        # try line at the bottom, posts on it.
        top, bottom = r.y() + 6, r.bottom() - 6
        p.drawLine(QPointF(r.x() + 6, r.y() + r.height() * 0.45), QPointF(r.right() - 6, r.y() + r.height() * 0.45))
        dash = QPen(QColor(255, 255, 255, 80), 1, Qt.DashLine)
        p.setPen(dash)
        for frac in (0.22, 0.62):
            y = r.y() + r.height() * frac
            p.drawLine(QPointF(r.x() + 6, y), QPointF(r.right() - 6, y))
        p.setPen(line)
        y22 = r.y() + r.height() * 0.78
        p.drawLine(QPointF(r.x() + 6, y22), QPointF(r.right() - 6, y22))
        cx = r.center().x()
        p.setPen(QPen(QColor(255, 255, 255, 160), 2))
        p.drawLine(QPointF(cx - 14, bottom), QPointF(cx - 14, bottom - 26))
        p.drawLine(QPointF(cx + 14, bottom), QPointF(cx + 14, bottom - 26))
        p.drawLine(QPointF(cx - 14, bottom - 10), QPointF(cx + 14, bottom - 10))

        if self.bench:
            p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.6))
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(QRectF(0, self.height() - 96, self.width(), 18), Qt.AlignCenter, "REPLACEMENTS")

        centers = self._centers()
        for i, slot in enumerate(self.slots[:len(centers)]):
            self._paint_token(p, i, centers[i], slot)

    def _paint_token(self, p, i, c, slot):
        sel = self.interactive and i == self.current
        hot = sel or (self.interactive and i == self._hover)
        ring = QColor(slot.get("ring") or FG_SECONDARY)
        faded = slot.get("faded")
        if sel:
            p.setPen(Qt.NoPen)
            glow = QColor(ACCENT)
            glow.setAlpha(90 if self.hasFocus() else 50)
            p.setBrush(glow)
            p.drawEllipse(c, TOKEN_R + 7, TOKEN_R + 7)
        p.setPen(QPen(QColor(ACCENT) if sel else ring, 3 if hot else 2.2))
        p.setBrush(QColor(BG_BASE if not faded else BG_CARD))
        p.drawEllipse(c, TOKEN_R, TOKEN_R)
        p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, 0))
        p.setPen(QColor(FG_MUTED if faded else FG_PRIMARY))
        p.drawText(QRectF(c.x() - TOKEN_R, c.y() - TOKEN_R, 2 * TOKEN_R, 2 * TOKEN_R), Qt.AlignCenter,
                   str(slot.get("number", i + 1)))
        # name plate
        name = surname(slot.get("name", "")) or "—"
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 0.4))
        fm = p.fontMetrics()
        name = fm.elidedText(name.upper(), Qt.ElideRight, 96)
        tw = fm.horizontalAdvance(name)
        value = slot.get("value")
        vw = 0
        if value not in (None, ""):
            vw = QFontMetrics(tracked_font(FONT_DISPLAY, 9, QFont.Bold, 0)).horizontalAdvance(str(value)) + 8
        plate = QRectF(c.x() - (tw + vw + 12) / 2, c.y() + TOKEN_R + 3, tw + vw + 12, 17)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 170))
        p.drawRoundedRect(plate, 3, 3)
        p.setPen(QColor(FG_MUTED if faded else (ACCENT if sel else FG_PRIMARY)))
        p.drawText(QRectF(plate.x() + 6, plate.y(), tw + 2, plate.height()), Qt.AlignLeft | Qt.AlignVCenter, name)
        if vw:
            vr = QRectF(plate.right() - vw - 3, plate.y() + 2, vw, plate.height() - 4)
            p.setBrush(QColor(slot.get("value_color") or ring))
            p.drawRoundedRect(vr, 2, 2)
            p.setPen(QColor(BG_BASE))
            p.setFont(tracked_font(FONT_DISPLAY, 9, QFont.Bold, 0))
            p.drawText(vr, Qt.AlignCenter, str(value))
        sub = slot.get("sub")
        if sub:
            p.setFont(tracked_font(FONT_DISPLAY, 8, QFont.DemiBold, 1.0))
            p.setPen(QColor(slot.get("sub_color") or FG_TERTIARY))
            p.drawText(QRectF(c.x() - 60, plate.bottom(), 120, 13), Qt.AlignCenter, sub.upper())

    # ── input ────────────────────────────────────────────────────────────
    def _at(self, pos):
        for i, c in enumerate(self._centers()[:len(self.slots)]):
            if (QPointF(pos) - c).manhattanLength() < TOKEN_R * 2:
                return i
        return None

    def mouseMoveEvent(self, e):
        hit = self._at(e.pos())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit is not None else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        hit = self._at(e.pos()) if self.interactive else None
        if hit is not None:
            self.current = hit
            self.update()
            self.slot_selected.emit(hit)

    def mouseDoubleClickEvent(self, e):
        hit = self._at(e.pos()) if self.interactive else None
        if hit is not None:
            self.slot_activated.emit(hit)

    def keyPressEvent(self, e):
        if not self.interactive:
            return super().keyPressEvent(e)
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and self.current is not None:
            self.slot_activated.emit(self.current)
            e.accept()
            return
        dirs = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if k in dirs:
            centers = self._centers()[:len(self.slots)]
            if self.current is None:
                self.current = 0
            dx, dy = dirs[k]
            cur = centers[self.current]
            best, score = None, None
            for i, c in enumerate(centers):
                v = c - cur
                primary = v.x() * dx + v.y() * dy
                if i == self.current or primary <= 4:
                    continue
                s = primary + abs(v.x() * dy + v.y() * dx) * 1.6
                if score is None or s < score:
                    best, score = i, s
            if best is not None:
                self.current = best
                self.update()
                self.slot_selected.emit(best)
                e.accept()
            else:
                e.ignore()
            return
        super().keyPressEvent(e)

    def focusInEvent(self, e):
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)
