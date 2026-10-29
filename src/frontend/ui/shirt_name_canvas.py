"""
ui/shirt_name_canvas.py — the back of the shirt, with the name area to drag
=============================================================================
Shows one back texture as the game gets it (the name already lettered on it,
see shared/shirt_names.py) and the rectangle the name is fitted into. The
rectangle is moved by dragging it and resized by its handles, or with the
keyboard: arrows move it, Alt+arrows resize it (Shift: bigger steps).

The area is in fractions of the texture ([x, y, w, h]); `area_changing`
fires while it moves (for a live preview) and `area_changed` once it is
let go — that is the one to store.
"""
from PyQt5.QtWidgets import QWidget, QSizePolicy
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPixmap, QBrush
from PyQt5.QtCore import Qt, QRectF, QPointF, pyqtSignal, QTimer

from ui.broadcast import draw_frame, tracked_font
from ui.theme import (
    BG_BASE, BORDER, ACCENT, FG_TERTIARY, FG_SECONDARY, FONT_DISPLAY, T_SMALL,
)

REF = 512.0          # keyboard steps are pixels of a 512 px texture
MIN_W, MIN_H = 0.06, 0.02


class NameAreaCanvas(QWidget):
    area_changing = pyqtSignal(list)
    area_changed = pyqtSignal(list)

    HANDLE = 9

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setMinimumSize(280, 280)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self._pixmap = None
        self._placeholder = "NO BACK TEXTURE"
        self._area = None              # [x, y, w, h] fractions
        self._number_box = None        # (x0, y0, x1, y1) fractions, for reference
        self._editable = True
        self._caption = "NAME AREA"
        self._drag = None              # (mode, start point, start area)
        self._hover = None
        self._key_timer = QTimer(self)
        self._key_timer.setSingleShot(True)
        self._key_timer.setInterval(450)
        self._key_timer.timeout.connect(lambda: self._area and self.area_changed.emit(list(self._area)))

    # ── content ──────────────────────────────────────────────────────────
    def set_image(self, image):
        """QImage (or None, with `placeholder` shown instead)."""
        self._pixmap = QPixmap.fromImage(image) if image is not None and not image.isNull() else None
        self.update()

    def set_placeholder(self, text):
        self._placeholder = text
        self.update()

    def set_area(self, area):
        if self._drag is None:
            self._area = list(area) if area else None
            self.update()

    def area(self):
        return list(self._area) if self._area else None

    def set_number_box(self, box):
        self._number_box = box
        self.update()

    def set_caption(self, text):
        self._caption = text
        self.update()

    def set_editable(self, on):
        self._editable = bool(on)
        self.setCursor(Qt.ArrowCursor)
        self.update()

    # ── geometry ─────────────────────────────────────────────────────────
    def _texture_rect(self):
        side = max(1, min(self.width(), self.height()) - 2)
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def _to_widget(self, area):
        t = self._texture_rect()
        x, y, w, h = area
        return QRectF(t.x() + x * t.width(), t.y() + y * t.height(), w * t.width(), h * t.height())

    def _handles(self, r):
        s = self.HANDLE
        pts = {"tl": r.topLeft(), "t": QPointF(r.center().x(), r.top()), "tr": r.topRight(),
               "r": QPointF(r.right(), r.center().y()), "br": r.bottomRight(),
               "b": QPointF(r.center().x(), r.bottom()), "bl": r.bottomLeft(),
               "l": QPointF(r.left(), r.center().y())}
        return {k: QRectF(p.x() - s / 2, p.y() - s / 2, s, s) for k, p in pts.items()}

    def _hit(self, pos):
        if not self._area or not self._editable:
            return None
        r = self._to_widget(self._area)
        for k, hr in self._handles(r).items():
            if hr.adjusted(-3, -3, 3, 3).contains(QPointF(pos)):
                return k
        if r.contains(QPointF(pos)):
            return "move"
        return None

    _CURSORS = {"move": Qt.SizeAllCursor, "l": Qt.SizeHorCursor, "r": Qt.SizeHorCursor,
                "t": Qt.SizeVerCursor, "b": Qt.SizeVerCursor, "tl": Qt.SizeFDiagCursor,
                "br": Qt.SizeFDiagCursor, "tr": Qt.SizeBDiagCursor, "bl": Qt.SizeBDiagCursor}

    @staticmethod
    def clamp(area):
        x, y, w, h = area
        w = max(MIN_W, min(1.0, w))
        h = max(MIN_H, min(1.0, h))
        x = max(0.0, min(1.0 - w, x))
        y = max(0.0, min(1.0 - h, y))
        return [round(x, 4), round(y, 4), round(w, 4), round(h, 4)]

    def _dragged(self, mode, start, area, pos):
        t = self._texture_rect()
        dx = (pos.x() - start.x()) / t.width()
        dy = (pos.y() - start.y()) / t.height()
        x, y, w, h = area
        if mode == "move":
            return self.clamp([x + dx, y + dy, w, h])
        x0, y0, x1, y1 = x, y, x + w, y + h
        if "l" in mode:
            x0 = min(x1 - MIN_W, max(0.0, x0 + dx))
        if "r" in mode:
            x1 = max(x0 + MIN_W, min(1.0, x1 + dx))
        if "t" in mode:
            y0 = min(y1 - MIN_H, max(0.0, y0 + dy))
        if "b" in mode:
            y1 = max(y0 + MIN_H, min(1.0, y1 + dy))
        return self.clamp([x0, y0, x1 - x0, y1 - y0])

    # ── mouse ────────────────────────────────────────────────────────────
    def mousePressEvent(self, event):
        self.setFocus()
        mode = self._hit(event.pos())
        if mode and event.button() == Qt.LeftButton:
            self._drag = (mode, QPointF(event.pos()), list(self._area))

    def mouseMoveEvent(self, event):
        if self._drag:
            mode, start, area = self._drag
            new = self._dragged(mode, start, area, QPointF(event.pos()))
            if new != self._area:
                self._area = new
                self.area_changing.emit(list(new))
                self.update()
            return
        hit = self._hit(event.pos())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(self._CURSORS.get(hit, Qt.ArrowCursor))
            self.update()

    def mouseReleaseEvent(self, event):
        if self._drag:
            start_area = self._drag[2]
            self._drag = None
            if self._area != start_area:
                self.area_changed.emit(list(self._area))
            self.update()

    def leaveEvent(self, event):
        if self._hover and not self._drag:
            self._hover = None
            self.setCursor(Qt.ArrowCursor)
            self.update()

    # ── keyboard ─────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        k, mods = event.key(), event.modifiers()
        arrows = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if k not in arrows or not self._area or not self._editable:
            super().keyPressEvent(event)
            return
        step = (8 if mods & Qt.ShiftModifier else 1) / REF
        dx, dy = arrows[k]
        x, y, w, h = self._area
        if mods & Qt.AltModifier:          # resize, keeping the centre
            w2, h2 = w + 2 * dx * step, h - 2 * dy * step
            new = self.clamp([x - (w2 - w) / 2, y - (h2 - h) / 2, w2, h2])
        else:
            new = self.clamp([x + dx * step, y + dy * step, w, h])
        if new != self._area:
            self._area = new
            self.area_changing.emit(list(new))
            self._key_timer.start()
            self.update()
        event.accept()

    def focusOutEvent(self, event):
        if self._key_timer.isActive():
            self._key_timer.stop()
            if self._area:
                self.area_changed.emit(list(self._area))
        super().focusOutEvent(event)

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        t = self._texture_rect()
        p.fillRect(t, QColor(BG_BASE))
        if self._pixmap is None:
            p.setPen(QColor(FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.8))
            p.drawText(t, Qt.AlignCenter | Qt.TextWordWrap, self._placeholder)
        else:
            p.drawPixmap(t, self._pixmap, QRectF(self._pixmap.rect()))
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(t)

        if self._number_box and self._pixmap is not None:
            x0, y0, x1, y1 = self._number_box
            nr = self._to_widget((x0, y0, x1 - x0, y1 - y0))
            p.setPen(QPen(QColor(255, 255, 255, 90), 1, Qt.DotLine))
            p.drawRect(nr)

        if self._area and self._pixmap is not None:
            r = self._to_widget(self._area)
            active = self._drag is not None or self.hasFocus() or self._hover is not None
            colour = QColor(ACCENT) if self._editable else QColor(FG_SECONDARY)
            # dark halo first so the frame reads on a white shirt too
            p.setPen(QPen(QColor(0, 0, 0, 140), 3))
            p.drawRect(r)
            p.setPen(QPen(colour, 1.5, Qt.SolidLine if active else Qt.DashLine))
            p.drawRect(r)
            if self._editable:
                p.setBrush(QBrush(colour))
                p.setPen(QPen(QColor(0, 0, 0, 160), 1))
                for k, hr in self._handles(r).items():
                    p.drawRect(hr if k == self._hover or active else hr.adjusted(1.5, 1.5, -1.5, -1.5))
            # caption under (or over) the box
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL - 1, QFont.Bold, 1.0))
            caption = self._caption
            fm = p.fontMetrics()
            cw, ch = fm.horizontalAdvance(caption) + 10, fm.height() + 2
            cy = r.bottom() + 5 if r.bottom() + ch + 6 < t.bottom() else r.top() - ch - 5
            cap = QRectF(r.x(), cy, cw, ch)
            p.setPen(Qt.NoPen)
            p.setBrush(colour)
            p.drawRect(cap)
            p.setPen(QColor(BG_BASE))
            p.drawText(cap, Qt.AlignCenter, caption)
        if self.hasFocus():
            draw_frame(p, self.rect(), ACCENT)
