"""ui/pitch_grid.py — the pitch textures as a grid of pictures to tick
=====================================================================
One tile per texture, grouped by region: its grass and its name. A tick says
a match at the stadium may use it. The cursor (arrows) or the mouse over a
tile asks for it to be shown (`previewed(key)`: the stadium editor lays it on
the 3D view); leaving the grid shows the last one the cursor was on.

The first tile ("" key) is the stadium's own pitch: shown, never ticked.
"""
from PyQt5.QtCore import QPoint, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QImage, QPainter, QPen, QPixmap
from PyQt5.QtWidgets import QSizePolicy, QWidget

from ui.broadcast import tracked_font
from ui.theme import (ACCENT, BG_BASE, BG_RAISED, BORDER, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY,
                      FONT_DISPLAY, T_SMALL)

COLUMNS = 2
TILE_H = 92
HEAD_H = 24
GAP = 8


def pixmap(image):
    image = image.convert("RGBA")
    q = QImage(image.tobytes(), image.width, image.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(q.copy())


class PitchGrid(QWidget):
    """`groups` = [(heading, [(key, label)])], the first group may be
    ("", [("", "Stadium's own")])."""

    toggled = pyqtSignal(str, bool)
    previewed = pyqtSignal(str)

    def __init__(self, groups, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.groups = [(head, list(items)) for head, items in groups]
        self.on = set()
        self.pics = {}                    # key -> QPixmap
        self.raw = {}                     # key -> PIL image
        self.key = None
        self.cursor = ""                  # the tile the cursor is on
        self._hover = None
        self._flat = [k for _h, items in self.groups for k, _l in items]
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setFixedHeight(self._height())
        self._font = tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.3)
        self._head_font = tracked_font(FONT_DISPLAY, T_SMALL, QFont.Bold, 1.0)

    # ── data ────────────────────────────────────────────────────────────
    def set_values(self, on_keys):
        self.on = set(on_keys)
        self.update()

    def set_pictures(self, pics):
        """{key: PIL image}"""
        self.raw = dict(pics)
        self.pics = {k: pixmap(v) for k, v in pics.items() if v is not None}
        self.update()

    def set_label(self, key, label):
        self.groups = [(head, [(k, label if k == key else l) for k, l in items])
                       for head, items in self.groups]
        self.update()

    # ── layout ──────────────────────────────────────────────────────────
    def _height(self):
        h = 0
        for head, items in self.groups:
            h += (HEAD_H if head else 0) + ((len(items) + COLUMNS - 1) // COLUMNS) * (TILE_H + GAP)
        return h

    def _tiles(self):
        """[(key, label, rect)] and [(heading, y)]"""
        tiles, heads, y = [], [], 0
        w = (self.width() - GAP * (COLUMNS - 1)) / COLUMNS
        for head, items in self.groups:
            if head:
                heads.append((head, y))
                y += HEAD_H
            for i, (key, label) in enumerate(items):
                tiles.append((key, label, QRectF((i % COLUMNS) * (w + GAP), y + (i // COLUMNS) * (TILE_H + GAP),
                                                 w, TILE_H)))
            y += ((len(items) + COLUMNS - 1) // COLUMNS) * (TILE_H + GAP)
        return tiles, heads

    def _at(self, pos):
        for key, _label, rect in self._tiles()[0]:
            if rect.contains(pos):
                return key
        return None

    # ── input ───────────────────────────────────────────────────────────
    def _show(self, key):
        self.previewed.emit(key)

    def mouseMoveEvent(self, event):
        key = self._at(event.pos())
        if key != self._hover:
            self._hover = key
            self.update()
            self._show(self.cursor if key is None else key)

    def leaveEvent(self, event):
        if self._hover is not None:
            self._hover = None
            self.update()
            self._show(self.cursor)

    def mousePressEvent(self, event):
        self.setFocus()
        key = self._at(event.pos())
        if key is None:
            return
        self.cursor = key
        self._toggle(key)
        self.update()
        self._show(key)

    def _toggle(self, key):
        if key == "":
            return
        state = key not in self.on
        (self.on.add if state else self.on.discard)(key)
        self.toggled.emit(key, state)

    def _move(self, dx, dy):
        """The cursor one tile left/right or up/down; False when there is
        none (the focus leaves the grid)."""
        tiles = self._tiles()[0]
        here = next((r for k, _l, r in tiles if k == self.cursor), None)
        if here is None:
            return False
        if dx:
            row = [(r.left(), k) for k, _l, r in tiles if abs(r.top() - here.top()) < 1
                   and (r.left() - here.left()) * dx > 0]
            if not row:
                return False
            self.cursor = min(row, key=lambda t: abs(t[0] - here.left()))[1]
            return True
        beyond = [(r.top(), abs(r.left() - here.left()), k) for k, _l, r in tiles
                  if (r.top() - here.top()) * dy > 0]
        if not beyond:
            return False
        near = min(abs(t[0] - here.top()) for t in beyond)
        self.cursor = min((t for t in beyond if abs(t[0] - here.top()) == near), key=lambda t: t[1])[2]
        return True

    def focusInEvent(self, event):
        super().focusInEvent(event)
        if self.cursor not in self._flat:
            self.cursor = self._flat[0] if self._flat else ""
        self._show(self.cursor)
        self.update()

    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.update()

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._toggle(self.cursor)
        else:
            step = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}.get(k)
            if step is None or not self._move(*step):
                super().keyPressEvent(event)
                return
            self._show(self.cursor)
        self.update()
        event.accept()

    # ── paint ───────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        tiles, heads = self._tiles()
        p.setFont(self._head_font)
        p.setPen(QColor(FG_TERTIARY))
        for head, y in heads:
            p.drawText(QRectF(0, y, self.width(), HEAD_H), Qt.AlignLeft | Qt.AlignVCenter, head.upper())
        focused = self.hasFocus()
        fm = QFontMetrics(self._font)
        for key, label, rect in tiles:
            on = key in self.on
            here = focused and key == self.cursor
            hot = key == self._hover
            p.setPen(QPen(QColor(ACCENT if (on or here) else (FG_TERTIARY if hot else BORDER)),
                          2 if (on or here) else 1))
            p.setBrush(QColor(BG_RAISED))
            p.drawRoundedRect(rect.adjusted(1, 1, -1, -1), 4, 4)
            thumb = rect.adjusted(4, 4, -4, -24)
            pic = self.pics.get(key)
            if pic is not None and not pic.isNull():
                src = pic.rect()
                want = thumb.width() / thumb.height()
                if src.width() / src.height() > want:
                    w = int(src.height() * want)
                    src.setX((src.width() - w) // 2)
                    src.setWidth(w)
                else:
                    h = int(src.width() / want)
                    src.setY((src.height() - h) // 2)
                    src.setHeight(h)
                p.drawPixmap(thumb, pic, QRectF(src))
            else:
                p.fillRect(thumb, QColor(BG_BASE))
            if on:
                badge = QRectF(rect.right() - 22, rect.top() + 6, 16, 16)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(ACCENT))
                p.drawRoundedRect(badge, 3, 3)
                p.setPen(QPen(QColor(BG_BASE), 2))
                p.drawLine(QPoint(int(badge.left()) + 3, int(badge.top()) + 8),
                           QPoint(int(badge.left()) + 6, int(badge.top()) + 11))
                p.drawLine(QPoint(int(badge.left()) + 6, int(badge.top()) + 11),
                           QPoint(int(badge.left()) + 12, int(badge.top()) + 4))
            p.setFont(self._font)
            p.setPen(QColor(FG_PRIMARY if (on or here) else FG_SECONDARY))
            p.drawText(QRectF(rect.left() + 6, rect.bottom() - 21, rect.width() - 12, 18),
                       Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(label, Qt.ElideRight, int(rect.width()) - 12))
