"""
ui/tattoo_editor.py — tattoos and skin colour, over the player editor
======================================================================
A full-window editor opened from the Appearance tab. Left: what to add (shapes by category, ready-made designs,
imported pictures), the layers with the selected one's settings, and the skin sliders. Middle: the body map —
the player's two arms and two legs unrolled, drawn with his real skin: click to choose where the next tattoo
goes, drag a tattoo to move it (onto another limb too), the corner handle resizes, the top one turns it.
Right: the screen's own 3D preview, borrowed for the time the editor is open, updated as you go.

Nothing is written until SAVE: the layers are flattened into one picture (app.tattoos.store) and handed back
through `on_save(design, adjust)`; CANCEL drops everything.
"""
from __future__ import annotations

import copy
import io
import math
import os
import random
import time

from PyQt5.QtCore import Qt, QPointF, QRectF, QTimer, pyqtSignal, QEvent, QSize
from PyQt5.QtGui import QColor, QFont, QImage, QPainter, QPen, QPixmap, QKeySequence, QPolygonF, QBrush
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QScrollArea, QSlider, QLineEdit,
    QPushButton, QShortcut, QFileDialog, QColorDialog, QSizePolicy, QFrame, QStackedWidget,
)

from app.tattoos import motifs as M, render as Rn, generate as G, store as S
from ui.broadcast import Card, display_label, eyebrow_label
from ui.editor_kit import compact_button, Note, SegmentField, ConfirmDialog, ScopeCheck
from ui.theme import (
    ACCENT, ACCENT_DARK, ACCENT_LITE, BG_BASE, BG_CARD, BG_HIGHLIGHT, BG_RAISED, BORDER, FG_PRIMARY,
    FG_SECONDARY, FG_TERTIARY, FG_MUTED, FONT_BODY, FONT_DISPLAY, INFO, T_LABEL, T_SMALL, T_TITLE, T_VALUE,
)
from shared.config import config
from shared.log import get_logger

log = get_logger(__name__)

READY = "Ready-made"
MINE = "My pictures"
CATEGORIES = [READY, "Fully inked", "Bands", "Tribal", "Rugby", "Symbols", "Ornament", "Lettering", "Skin marks", MINE]
SIDES = [("both", "Both"), ("a", "Right"), ("b", "Left")]
INKS = ["#1c2433", "#0b0b0d", "#1f3a5f", "#7a1020", "#1d5a2c", "#5a3a1a"]
TILE_ORDER = [("arm", "a", "RIGHT ARM"), ("arm", "b", "LEFT ARM"), ("leg", "a", "RIGHT LEG"), ("leg", "b", "LEFT LEG")]


def covered_by_kit(stats):
    """{limb: [(top, bottom, what)]} of the skin the player's kit hides (measured on the game's model)."""
    out = {"arm": [], "leg": [(0, 38, "under the shorts")]}
    if str(stats.get("socks") or "down") == "up":
        out["leg"].append((140, 256, "under the socks"))
    else:
        out["leg"].append((247, 256, ""))
    if str(stats.get("tight_tape") or "none") != "none":
        out["leg"].append((50, 78, "thigh tape"))
    if str(stats.get("wrist_tape") or "none") != "none":
        out["arm"].append((117, 129, ""))
    return out
MARKS = {"arm": [(0, "shoulder"), (50, "elbow"), (125, "wrist"), (200, "fingers")],
         "leg": [(115, "knee"), (245, "ankle")]}
ADJUST = [("light", "Brightness"), ("contrast", "Contrast"), ("warm", "Warmth"), ("sat", "Colour strength"),
          ("red", "Redness")]


def _qimage(img):
    img = img.convert("RGBA")
    data = img.tobytes("raw", "RGBA")
    q = QImage(data, img.width, img.height, img.width * 4, QImage.Format_RGBA8888)
    return q.copy()


def _label(text, size=T_SMALL, color=FG_SECONDARY, bold=False):
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setStyleSheet(f"color: {color}; background: transparent; font-family: '{FONT_DISPLAY if bold else FONT_BODY}';"
                      f" font-size: {size}pt; {'font-weight: 600;' if bold else ''}")
    return lab


# ═════════════════════════════════════════════════════════════════════════
class Slider(QWidget):
    """A labelled slider for a float range: one drag = one undo step (`pressed`, then `moved` while dragging)."""

    moved = pyqtSignal(float)
    pressed = pyqtSignal()
    released = pyqtSignal()

    STEPS = 200

    def __init__(self, label, lo, hi, value=0.0, fmt=None, parent=None):
        super().__init__(parent)
        self.lo, self.hi = float(lo), float(hi)
        self.fmt = fmt or (lambda v: f"{v:.2f}".rstrip("0").rstrip("."))
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        top = QHBoxLayout()
        top.setSpacing(4)
        self.name = _label(label, T_SMALL, FG_SECONDARY, bold=True)
        self.value_lbl = _label("", T_SMALL, FG_TERTIARY)
        self.value_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        top.addWidget(self.name, 1)
        top.addWidget(self.value_lbl)
        v.addLayout(top)
        self.s = QSlider(Qt.Horizontal)
        self.s.setRange(0, self.STEPS)
        self.s.setCursor(Qt.PointingHandCursor)
        self.s.setFixedHeight(20)
        self.s.setStyleSheet(
            f"QSlider {{ background: transparent; border: none; }}"
            f"QSlider::groove:horizontal {{ height: 4px; background: {BG_BASE}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {ACCENT_DARK}; border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0; border-radius: 7px;"
            f" background: {FG_SECONDARY}; }}"
            f"QSlider::handle:horizontal:hover {{ background: {FG_PRIMARY}; }}")
        self.s.sliderPressed.connect(self.pressed)
        self.s.sliderReleased.connect(self.released)
        self.s.valueChanged.connect(self._changed)
        v.addWidget(self.s)
        self._quiet = False
        self.set_value(value)

    def _to_float(self, i):
        return self.lo + (self.hi - self.lo) * i / self.STEPS

    def value(self):
        return self._to_float(self.s.value())

    def set_value(self, value):
        self._quiet = True
        frac = 0 if self.hi == self.lo else (float(value) - self.lo) / (self.hi - self.lo)
        self.s.setValue(int(round(min(max(frac, 0), 1) * self.STEPS)))
        self.value_lbl.setText(self.fmt(float(value)))
        self._quiet = False

    def _changed(self, i):
        v = self._to_float(i)
        self.value_lbl.setText(self.fmt(v))
        if not self._quiet:
            down = self.s.isSliderDown()
            if not down:
                self.pressed.emit()          # a click on the groove or a key: its own step
            self.moved.emit(v)
            if not down:
                self.released.emit()


class Toggle(QPushButton):
    """A small checkable pill."""

    def __init__(self, text, checked=False):
        super().__init__(text)
        self.setCheckable(True)
        self.setChecked(checked)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedHeight(26)
        self.setStyleSheet(
            f"QPushButton {{ background: {BG_HIGHLIGHT}; color: {FG_SECONDARY}; border: 1px solid {BORDER};"
            f" padding: 2px 8px; font-family: '{FONT_DISPLAY}'; font-size: 10pt; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {FG_PRIMARY}; border-color: {FG_TERTIARY}; }}"
            f"QPushButton:checked {{ background: {ACCENT_DARK}; color: {FG_PRIMARY}; border-color: {ACCENT}; }}")


class Chips(QWidget):
    """One-of-many pills, wrapped on rows of `per_row`."""

    picked = pyqtSignal(str)

    def __init__(self, options, per_row=3, value=None):
        super().__init__()
        g = QGridLayout(self)
        g.setContentsMargins(0, 0, 0, 0)
        g.setSpacing(4)
        self.buttons = {}
        for i, (key, text) in enumerate(options):
            b = Toggle(text, key == value)
            b.clicked.connect(lambda _c=False, k=key: self.set_value(k, emit=True))
            g.addWidget(b, i // per_row, i % per_row)
            self.buttons[key] = b
        self._value = value

    def value(self):
        return self._value

    def set_value(self, key, emit=False):
        self._value = key
        for k, b in self.buttons.items():
            b.setChecked(k == key)
        if emit:
            self.picked.emit(key)


# ═════════════════════════════════════════════════════════════════════════
class Tile(QPushButton):
    """A thumbnail + name in the catalogue."""

    def __init__(self, name, pix=None, size=76):
        super().__init__()
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setFixedSize(size, size + 18)
        self.name = name
        self.pix = pix
        self.setToolTip(name)

    def set_pix(self, pix):
        self.pix = pix
        self.update()

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        hot = self.underMouse()
        r = QRectF(0.5, 0.5, self.width() - 1, self.height() - 1)
        p.fillRect(r, QColor(BG_RAISED if hot else BG_HIGHLIGHT))
        p.setPen(QPen(QColor(ACCENT if hot else BORDER), 1))
        p.drawRect(r)
        box = QRectF(6, 4, self.width() - 12, self.width() - 12)
        p.fillRect(box, QColor("#d9c3ae"))
        if self.pix is not None and not self.pix.isNull():
            s = self.pix.size()
            k = min(box.width() / s.width(), box.height() / s.height())
            w, h = s.width() * k, s.height() * k
            p.drawPixmap(QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h), self.pix,
                         QRectF(0, 0, s.width(), s.height()))
        p.setPen(QColor(FG_PRIMARY if hot else FG_SECONDARY))
        f = QFont(FONT_BODY)
        f.setPointSize(8)
        p.setFont(f)
        text = p.fontMetrics().elidedText(self.name, Qt.ElideRight, self.width() - 6)
        p.drawText(QRectF(3, self.height() - 18, self.width() - 6, 16), Qt.AlignCenter, text)


_THUMBS = {}


def _ink_thumb(mask, rgb=None, size=96):
    """Pixmap of an ink mask (dark ink on transparent), or a colour picture."""
    from PIL import Image
    if rgb is None:
        img = Image.new("RGBA", mask.size, (28, 36, 51, 255))
    else:
        img = rgb.convert("RGBA")
    img.putalpha(mask)
    img.thumbnail((size, size))
    return QPixmap.fromImage(_qimage(img))


def motif_thumb(mid, library=None):
    key = ("m", mid)
    if key not in _THUMBS:
        try:
            if mid.startswith("user:"):
                info = library.item(mid[5:]) if library else None
                a = info["aspect"] if info else 1
                w, h = (96, max(4, round(96 / a))) if a >= 1 else (max(4, round(96 * a)), 96)
                m, rgb = library.picture(mid[5:], w, h)
                _THUMBS[key] = _ink_thumb(m, rgb)
            else:
                mo = M.REG[mid]
                a = mo.aspect
                w, h = (96, max(4, round(96 / a))) if a >= 1 else (max(4, round(96 * a)), 96)
                _THUMBS[key] = _ink_thumb(M.draw_mask(mid, w, h, None, 3))
        except Exception as e:                 # a broken picture must not break the catalogue
            log.warning(f"tattoo thumbnail {mid}: {e}")
            _THUMBS[key] = QPixmap()
    return _THUMBS[key]


def ready_thumb(style):
    key = ("g", style)
    if key not in _THUMBS:
        from PIL import Image
        d = Rn.clean_design({"layers": G.generate(style, 1, "arm", side="a")})
        tile = Rn.render_tile(d["layers"], "arm")
        box = tile.getbbox() or (0, 0, 128, 128)
        crop = tile.crop(box)
        _THUMBS[key] = QPixmap.fromImage(_qimage(crop))
    return _THUMBS[key]


# ═════════════════════════════════════════════════════════════════════════
class BodyMap(QWidget):
    """The four limb tiles, side by side, with the tattoos on them."""

    select = pyqtSignal(str)                 # layer id ("" = none)
    spot_set = pyqtSignal()
    begin_edit = pyqtSignal(str)             # undo checkpoint (label)
    changed = pyqtSignal()                   # a layer moved / resized / turned

    HANDLE = 9

    def __init__(self, editor):
        super().__init__()
        self.ed = editor
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(300, 260)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.atlas = None                    # QImage 512×256 of skin + tattoos
        self._drag = None
        self._hover = ""

    # ── geometry ─────────────────────────────────────────────────────────
    def _layout(self):
        """{(limb, side): QRectF} and the scale (screen px per tile px)."""
        gap, top, bottom = 14, 22, 4
        avail_w = self.width() - gap * 3 - 8
        avail_h = self.height() - top - bottom
        k = max(0.3, min(avail_w / (4 * 128), avail_h / 256))
        total = 4 * 128 * k + gap * 3
        x = (self.width() - total) / 2
        rects = {}
        for limb, side, _ in TILE_ORDER:
            rects[(limb, side)] = QRectF(x, top, 128 * k, 256 * k)
            x += 128 * k + gap
        return rects, k

    def tile_at(self, pos):
        rects, k = self._layout()
        for key, r in rects.items():
            if r.adjusted(-6, 0, 6, 0).contains(pos):
                tx = (pos.x() - r.x()) / k
                ty = (pos.y() - r.y()) / k
                return key[0], key[1], min(max(tx, 0), 127.99), min(max(ty, 0), 255.99)
        return None

    def to_screen(self, limb, side, x, y):
        rects, k = self._layout()
        r = rects[(limb, side)]
        return QPointF(r.x() + x * k, r.y() + y * k)

    @staticmethod
    def _local(L, tx, ty):
        """Tile point → the layer's own frame (unwidened, unrotated), relative to its centre."""
        xs = Rn.LIMBS[L["limb"]]["xscale"]
        tw = Rn.LIMBS[L["limb"]]["size"][0]
        dx = (tx - L["x"] + tw / 2) % tw - tw / 2
        dy = ty - L["y"]
        if L["wrap"]:
            return 0.0, dy
        dx /= xs
        a = math.radians(L["rot"])
        return dx * math.cos(a) + dy * math.sin(a), -dx * math.sin(a) + dy * math.cos(a)

    def _corners(self, L):
        """The layer's box corners in tile px (may leave the tile; x not wrapped)."""
        xs = Rn.LIMBS[L["limb"]]["xscale"]
        tw = Rn.LIMBS[L["limb"]]["size"][0]
        if L["wrap"]:
            return [(0, L["y"] - L["h"] / 2), (tw, L["y"] - L["h"] / 2), (tw, L["y"] + L["h"] / 2), (0, L["y"] + L["h"] / 2)]
        a = math.radians(L["rot"])
        out = []
        for lx, ly in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            px, py = lx * L["w"] / 2, ly * L["h"] / 2
            rx, ry = px * math.cos(a) - py * math.sin(a), px * math.sin(a) + py * math.cos(a)
            out.append((L["x"] + rx * xs, L["y"] + ry))
        return out

    def _handles(self, L, limb, side):
        """Screen points of the resize (bottom-right corner) and turn (above the top edge) handles."""
        c = self._corners(L)
        _, k = self._layout()
        res = self.to_screen(limb, side, *c[2])
        if L["wrap"]:
            return res, None
        tx = (c[0][0] + c[1][0]) / 2
        ty = (c[0][1] + c[1][1]) / 2
        cx, cy = L["x"], L["y"]
        dx, dy = tx - cx, ty - cy
        n = math.hypot(dx, dy) or 1
        return res, self.to_screen(limb, side, tx + dx / n * 16 / k, ty + dy / n * 16 / k)

    def _sides_of(self, L):
        return ("a", "b") if L["side"] == "both" else (L["side"],)

    def hit(self, limb, side, tx, ty):
        for L in reversed(self.ed.design["layers"]):
            if not L["visible"] or L["limb"] != limb or side not in self._sides_of(L):
                continue
            lx, ly = self._local(L, tx, ty)
            if L["wrap"] and abs(ly) <= max(L["h"] / 2, 4):
                return L
            if abs(lx) <= max(L["w"] / 2, 5) and abs(ly) <= max(L["h"] / 2, 5):
                return L
        return None

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        rects, k = self._layout()
        f = QFont(FONT_DISPLAY)
        f.setPointSize(9)
        f.setWeight(QFont.DemiBold)
        f.setLetterSpacing(QFont.AbsoluteSpacing, 1.2)
        small = QFont(FONT_BODY)
        small.setPointSize(8)
        sel = self.ed.selected()
        for limb, side, title in TILE_ORDER:
            r = rects[(limb, side)]
            x0, y0 = Rn.LIMBS[limb][side]
            if self.atlas is not None:
                p.drawImage(r, self.atlas, QRectF(x0, y0, 128, 256))
            p.setPen(QPen(QColor(BORDER), 1))
            p.setBrush(Qt.NoBrush)
            p.drawRect(r)
            p.setFont(f)
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(r.x() - 10, 2, r.width() + 20, 18), Qt.AlignCenter, title)
            # parts the kit hides, landmarks, the front of the limb
            p.setFont(small)
            for a, b, why in self.ed.covered.get(limb, []):
                hr = QRectF(r.x(), r.y() + a * k, r.width(), (b - a) * k)
                p.fillRect(hr, QColor(0, 0, 0, 150))
                p.setPen(QColor(FG_TERTIARY))
                p.drawText(hr, Qt.AlignCenter, why)
            for y, name in MARKS[limb]:
                yy = r.y() + y * k
                p.setPen(QPen(QColor(255, 255, 255, 70), 1, Qt.DashLine))
                p.drawLine(QPointF(r.x(), yy), QPointF(r.x() + 7, yy))
                p.setPen(QColor(255, 255, 255, 150))
                p.drawText(QRectF(r.x() + 9, yy - 7, r.width(), 14), Qt.AlignLeft | Qt.AlignVCenter, name)
            fx = r.x() + Rn.LIMBS[limb]["front"] * k
            p.setPen(QPen(QColor(255, 255, 255, 60), 1, Qt.DotLine))
            p.drawLine(QPointF(fx, r.y()), QPointF(fx, r.bottom()))
            p.setPen(QColor(255, 255, 255, 120))
            fy = r.bottom() - 14 if limb == "arm" else r.y() + 22 * k
            p.drawText(QRectF(fx - 30, fy, 60, 12), Qt.AlignCenter, "front")
            # where the next tattoo goes
            spot = self.ed.spot
            if spot["limb"] == limb and (spot["side"] == side or self.ed.side_mode == "both"):
                c = self.to_screen(limb, side, spot["x"], spot["y"])
                p.setPen(QPen(QColor(ACCENT_LITE), 2))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c, 7, 7)
                p.drawLine(QPointF(c.x() - 11, c.y()), QPointF(c.x() - 4, c.y()))
                p.drawLine(QPointF(c.x() + 4, c.y()), QPointF(c.x() + 11, c.y()))
                p.drawLine(QPointF(c.x(), c.y() - 11), QPointF(c.x(), c.y() - 4))
                p.drawLine(QPointF(c.x(), c.y() + 4), QPointF(c.x(), c.y() + 11))
            # the selected tattoo
            if sel is not None and sel["limb"] == limb and side in self._sides_of(sel):
                p.save()
                p.setClipRect(r.adjusted(-1, -1, 1, 1))
                tw = Rn.LIMBS[limb]["size"][0]
                for dx in ((-tw, 0, tw) if not sel["wrap"] else (0,)):
                    poly = QPolygonF([self.to_screen(limb, side, cx + dx, cy) for cx, cy in self._corners(sel)])
                    p.setPen(QPen(QColor(INFO), 1.5, Qt.DashLine))
                    p.setBrush(Qt.NoBrush)
                    p.drawPolygon(poly)
                p.restore()
                res, turn = self._handles(sel, limb, side)
                p.setPen(QPen(QColor(BG_BASE), 1))
                p.setBrush(QColor(INFO))
                p.drawRect(QRectF(res.x() - 5, res.y() - 5, 10, 10))
                if turn is not None:
                    p.drawEllipse(turn, 5.5, 5.5)
        p.end()

    # ── mouse ────────────────────────────────────────────────────────────
    def _handle_at(self, pos):
        sel = self.ed.selected()
        if sel is None:
            return None
        for side in self._sides_of(sel):
            res, turn = self._handles(sel, sel["limb"], side)
            if (res - pos).manhattanLength() <= self.HANDLE + 2:
                return "size", side
            if turn is not None and (turn - pos).manhattanLength() <= self.HANDLE + 2:
                return "turn", side
        return None

    def mousePressEvent(self, e):
        self.setFocus()
        if e.button() != Qt.LeftButton:
            return
        pos = QPointF(e.pos())
        h = self._handle_at(pos)
        sel = self.ed.selected()
        if h is not None and sel is not None:
            self.begin_edit.emit("resize" if h[0] == "size" else "turn")
            self._drag = {"mode": h[0], "side": h[1], "L0": dict(sel), "pos": pos}
            return
        at = self.tile_at(pos)
        if at is None:
            return
        limb, side, tx, ty = at
        L = self.hit(limb, side, tx, ty)
        if L is not None:
            self.select.emit(L["id"])
            self.begin_edit.emit("move")
            self._drag = {"mode": "move", "side": side, "L0": dict(L), "start": (limb, side, tx, ty), "moved": False}
        else:
            self.select.emit("")
            self.ed.set_spot(limb, side, tx, ty)
            self.spot_set.emit()
        self.update()

    def mouseMoveEvent(self, e):
        pos = QPointF(e.pos())
        d = self._drag
        if d is None:
            at = self.tile_at(pos)
            over = self.hit(*at) if at else None
            h = self._handle_at(pos)
            self.setCursor(Qt.SizeFDiagCursor if h and h[0] == "size" else Qt.CrossCursor if h else
                           Qt.OpenHandCursor if over is not None else Qt.CrossCursor if at else Qt.ArrowCursor)
            return
        sel = self.ed.selected()
        if sel is None:
            return
        L0 = d["L0"]
        if d["mode"] == "move":
            at = self.tile_at(pos)
            if at is None:
                return
            limb, side, tx, ty = at
            l0, s0, x0, y0 = d["start"]
            if limb == l0:
                nx, ny = L0["x"] + (tx - x0), L0["y"] + (ty - y0)
            else:                                   # dropped onto the other limb: follow the pointer
                nx, ny = tx, ty
            tw, th = Rn.LIMBS[limb]["size"]
            sel["limb"] = limb
            if sel["side"] != "both" and side != s0:
                sel["side"] = side
            sel["x"] = nx % tw
            sel["y"] = min(max(ny, -20), th + 20)
            self.setCursor(Qt.ClosedHandCursor)
        elif d["mode"] == "size":
            c = self.to_screen(sel["limb"], d["side"], L0["x"], L0["y"])
            r0 = math.hypot(d["pos"].x() - c.x(), d["pos"].y() - c.y()) or 1
            r1 = math.hypot(pos.x() - c.x(), pos.y() - c.y())
            f = min(max(r1 / r0, 0.1), 8)
            if L0["wrap"]:
                sel["h"] = min(max(L0["h"] * f, 2), 256)
            else:
                sel["w"] = min(max(L0["w"] * f, 4), 300)
                sel["h"] = min(max(L0["h"] * f, 2), 300)
        elif d["mode"] == "turn":
            c = self.to_screen(sel["limb"], d["side"], L0["x"], L0["y"])
            a0 = math.degrees(math.atan2(d["pos"].y() - c.y(), d["pos"].x() - c.x()))
            a1 = math.degrees(math.atan2(pos.y() - c.y(), pos.x() - c.x()))
            rot = L0["rot"] + (a1 - a0)
            rot = (rot + 180) % 360 - 180
            if not (e.modifiers() & Qt.ShiftModifier):
                for snap in (-180, -90, 0, 90, 180):
                    if abs(rot - snap) < 4:
                        rot = snap
            sel["rot"] = rot
        self.changed.emit()

    def mouseReleaseEvent(self, _e):
        if self._drag is not None:
            self._drag = None
            self.ed.end_edit()
        self.update()

    def wheelEvent(self, e):
        sel = self.ed.selected()
        at = self.tile_at(QPointF(e.pos()))
        if sel is None or at is None:
            return
        steps = e.angleDelta().y() / 120
        if not steps:
            return
        self.begin_edit.emit("wheel")
        if e.modifiers() & Qt.ShiftModifier and not sel["wrap"]:
            sel["rot"] = (sel["rot"] + 5 * steps + 180) % 360 - 180
        else:
            f = 1.06 ** steps
            if not sel["wrap"]:
                sel["w"] = min(max(sel["w"] * f, 4), 300)
            sel["h"] = min(max(sel["h"] * f, 2), 300)
        self.changed.emit()
        self.ed.end_edit(coalesce="wheel")


# ═════════════════════════════════════════════════════════════════════════
class TattooEditor(QWidget):
    """The editor. `on_save(design, adjust)` is called on SAVE (then it closes); `on_close()` either way."""

    def __init__(self, screen, title, design, adjust, base_source, other_layers, library, on_save,
                 on_close=None, scope_box=None, start="add", covered=None):
        super().__init__(screen)
        self._screen = screen
        self.library = library
        self.on_save = on_save
        self.on_close = on_close
        self.design = copy.deepcopy(design)
        self.adjust = Rn.clean_adjust(adjust)
        self._saved_state = self._state()
        self.covered = covered or covered_by_kit({})
        self.base_source = base_source          # PIL RGBA 512×256, before the skin sliders
        self.other_layers = other_layers        # PIL layers painted over the tattoos (straps, gloves…)
        self.sel_id = ""
        self.side_mode = "both"
        self.spot = {"limb": "arm", "side": "a", "x": Rn.LIMBS["arm"]["front"], "y": 90}
        self._undo, self._redo = [], []
        self._pending = None                     # (label, state) taken at begin_edit
        self._coalesce = (None, 0.0)
        self._closed = False
        self._preview_files = []

        self._render_timer = QTimer(self, singleShot=True, interval=16, timeout=self._render_map)
        self._stage_timer = QTimer(self, singleShot=True, interval=380, timeout=self._update_stage)

        self.setGeometry(screen.rect())
        self.card = Card(stripe=ACCENT)
        self.card.setParent(self)
        outer = QVBoxLayout(self.card)
        outer.setContentsMargins(16, 12, 16, 12)
        outer.setSpacing(8)

        # header
        head = QHBoxLayout()
        head.setSpacing(8)
        head.addWidget(display_label(title, T_TITLE, QFont.Bold, track=0.8, upper=False))
        head.addStretch(1)
        self.undo_btn = compact_button("UNDO")
        self.undo_btn.clicked.connect(self.undo)
        self.redo_btn = compact_button("REDO")
        self.redo_btn.clicked.connect(self.redo)
        head.addWidget(self.undo_btn)
        head.addWidget(self.redo_btn)
        if scope_box is not None:
            self.scope = ScopeCheck(checked=scope_box.checked)
            self.scope.setToolTip("Save to every season of this player, or only the one shown")

            def follow(on, box=scope_box):
                box.set_checked(on)
                box.toggled.emit(on)
            self.scope.toggled.connect(follow)
            head.addWidget(self.scope)
        cancel = compact_button("CANCEL")
        cancel.clicked.connect(self.cancel)
        self.save_btn = compact_button("SAVE", "primary")
        self.save_btn.clicked.connect(self.save)
        head.addWidget(cancel)
        head.addWidget(self.save_btn)
        outer.addLayout(head)

        body = QHBoxLayout()
        body.setSpacing(12)
        outer.addLayout(body, 1)

        # left column
        left = QVBoxLayout()
        left.setSpacing(8)
        self.mode = Chips([("add", "ADD"), ("layers", "TATTOOS"), ("skin", "SKIN")], per_row=3, value=start)
        self.mode.picked.connect(self._show_mode)
        left.addWidget(self.mode)
        self.pages = QStackedWidget()
        self.pages.addWidget(self._build_add())
        self.pages.addWidget(self._build_layers())
        self.pages.addWidget(self._build_skin())
        left.addWidget(self.pages, 1)
        lw = QWidget()
        lw.setLayout(left)
        lw.setFixedWidth(272)
        body.addWidget(lw)

        # middle: the map and what to do with it
        mid = QVBoxLayout()
        mid.setSpacing(6)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        bar.addWidget(_label("New tattoos go on", T_SMALL, FG_TERTIARY))
        self.side_chips = Chips([("both", "BOTH SIDES"), ("one", "ONE SIDE")], per_row=2, value="both")
        self.side_chips.picked.connect(self._set_side_mode)
        bar.addWidget(self.side_chips)
        bar.addStretch(1)
        mid.addLayout(bar)
        self.map = BodyMap(self)
        self.map.select.connect(self.set_selected)
        self.map.begin_edit.connect(self.begin_edit)
        self.map.changed.connect(self._changed)
        self.map.spot_set.connect(self._refresh_hint)
        mid.addWidget(self.map, 1)
        self.sel_bar = QHBoxLayout()
        self.sel_bar.setSpacing(6)
        self.hint = _label("", T_SMALL, FG_TERTIARY)
        self.sel_bar.addWidget(self.hint, 1)
        self.edit_btn = compact_button("SETTINGS")
        self.edit_btn.clicked.connect(lambda: self.mode.set_value("layers", emit=True))
        self.dup_btn = compact_button("DUPLICATE")
        self.dup_btn.clicked.connect(self.duplicate)
        self.del_btn = compact_button("DELETE", "danger")
        self.del_btn.clicked.connect(self.delete_selected)
        for b in (self.edit_btn, self.dup_btn, self.del_btn):
            b.setFixedHeight(28)
            self.sel_bar.addWidget(b)
        mid.addLayout(self.sel_bar)
        body.addLayout(mid, 1)

        # right: the 3D stage
        self.stage_box = None
        borrow = getattr(screen, "borrow_stage", None)
        if callable(borrow):
            self.stage_box = QWidget()
            sv = QVBoxLayout(self.stage_box)
            sv.setContentsMargins(0, 0, 0, 0)
            sv.setSpacing(4)
            sv.addWidget(eyebrow_label("on the player", color=FG_TERTIARY, size=10))
            self.stage = borrow(self.stage_box)
            sv.addWidget(self.stage, 1)
            views = QHBoxLayout()
            views.setSpacing(4)
            sv.addWidget(_label("Drag the player to look all round.", T_SMALL, FG_TERTIARY))
            for text, yaw in (("FRONT", 0), ("SIDE", 90), ("BACK", 180)):
                b = Toggle(text)
                b.setCheckable(False)
                b.setMinimumWidth(10)
                b.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
                b.clicked.connect(lambda _c=False, y=yaw: self._turn_stage(y))
                views.addWidget(b)
            sv.addLayout(views)
            self.stage_box.setFixedWidth(260)
            body.addWidget(self.stage_box)

        # The screen behind has its own Ctrl+Z, Ctrl+S… shortcuts: two shortcuts on one key fire neither, so
        # while the editor is open those keys are taken before the shortcut system sees them (see _keys).
        self._keys = {
            (Qt.ControlModifier, Qt.Key_Z): self.undo,
            (Qt.ControlModifier, Qt.Key_Y): self.redo,
            (Qt.ControlModifier | Qt.ShiftModifier, Qt.Key_Z): self.redo,
            (Qt.ControlModifier, Qt.Key_D): self.duplicate,
            (Qt.ControlModifier, Qt.Key_S): self.save,
            (Qt.NoModifier, Qt.Key_Delete): self.delete_selected,
        }
        QApplication.instance().installEventFilter(self)

        self.setAcceptDrops(True)
        self._place()
        screen.installEventFilter(self)
        if hasattr(screen, "_dialog"):
            self._prev_dialog = screen._dialog
            screen._dialog = self
        self._show_mode(start)
        self._fill_catalogue()
        self._sync_all()
        self.show()
        self.raise_()
        self.map.setFocus()

    # ── state / undo ─────────────────────────────────────────────────────
    def _state(self):
        return copy.deepcopy({"layers": self.design["layers"], "adjust": self.adjust})

    def _set_state(self, st):
        self.design["layers"] = copy.deepcopy(st["layers"])
        self.adjust = dict(st["adjust"])
        if self.selected() is None:
            self.sel_id = ""
        self._sync_all()

    def dirty(self):
        return self._state() != self._saved_state

    def begin_edit(self, label="edit"):
        if self._pending is None:
            self._pending = (label, self._state())

    def end_edit(self, coalesce=None):
        if self._pending is None:
            return
        label, before = self._pending
        self._pending = None
        if before == self._state():
            return
        now = time.monotonic()
        key, t = self._coalesce
        if coalesce and key == coalesce and now - t < 0.8 and self._undo:
            pass                                   # same wheel/slider gesture: keep the first snapshot
        else:
            self._undo.append(before)
            del self._undo[:-150]
        self._coalesce = (coalesce, now)
        self._redo.clear()
        self._update_buttons()

    def edit(self, fn, label="edit", coalesce=None):
        """One undoable change made through `fn()`."""
        self.begin_edit(label)
        fn()
        self.end_edit(coalesce)
        self._changed()

    def undo(self):
        if not self._undo:
            return
        self._redo.append(self._state())
        self._set_state(self._undo.pop())

    def redo(self):
        if not self._redo:
            return
        self._undo.append(self._state())
        self._set_state(self._redo.pop())

    def _update_buttons(self):
        self.undo_btn.setEnabled(bool(self._undo))
        self.redo_btn.setEnabled(bool(self._redo))

    # ── layers ───────────────────────────────────────────────────────────
    def selected(self):
        return next((L for L in self.design["layers"] if L["id"] == self.sel_id), None)

    def set_selected(self, lid):
        self.sel_id = lid or ""
        self._refresh_layer_list()
        self._refresh_props()
        self._refresh_hint()
        self.map.update()

    def set_spot(self, limb, side, x, y):
        self.spot = {"limb": limb, "side": side, "x": x, "y": y}

    def _set_side_mode(self, mode):
        self.side_mode = mode
        self.map.update()

    def _new_side(self):
        return "both" if self.side_mode == "both" else self.spot["side"]

    def add_motif(self, mid):
        mo = M.REG.get(mid)
        info = self.library.item(mid[5:]) if mid.startswith("user:") else None
        limb, x, y = self.spot["limb"], self.spot["x"], self.spot["y"]
        raw = {"motif": mid, "limb": limb, "side": self._new_side(), "x": x, "y": y,
               "seed": random.randrange(1, 99999)}
        if mo is not None:
            raw.update({"w": mo.size, "h": mo.size / mo.aspect, "wrap": mo.wrap})
            if mo.cat == "Skin marks":
                raw.update({"opacity": .45, "color": "#5a3a2a", "soft": 1.2})
            if mo.place:
                limb = mo.place["limb"]
                y0, y1 = mo.place["y0"], mo.place["y1"]
                raw.update({"limb": limb, "y": (y0 + y1) / 2, "h": y1 - y0, "x": Rn.LIMBS[limb]["front"]})
                if not mo.wrap:
                    raw["w"] = mo.size
            elif mo.wrap:
                raw["h"] = min(mo.size / mo.aspect, 60)
        elif info is not None:
            w = 44.0
            raw.update({"w": w, "h": w / info["aspect"], "opacity": 1.0 if info["mode"] == "colour" else .9})
        if raw.get("side") not in ("both", "a", "b"):
            raw["side"] = "both"
        try:
            L = Rn.clean_layer(raw, self.library)
        except ValueError as e:
            log.warning(f"cannot add {mid}: {e}")
            return
        self.edit(lambda: self.design["layers"].append(L), "add")
        self.set_selected(L["id"])
        if mo is not None and any(p["type"] == "text" for p in mo.params):
            self.mode.set_value("layers", emit=True)
            QTimer.singleShot(0, self._focus_text)

    def add_ready(self, style):
        layers = G.generate(style, random.randrange(1, 99999), self.spot["limb"], side=self._new_side())
        if not layers:
            return
        self.edit(lambda: self.design["layers"].extend(layers), "add design")
        self.set_selected(layers[-1]["id"])

    def duplicate(self):
        L = self.selected()
        if L is None:
            return
        tw, th = Rn.LIMBS[L["limb"]]["size"]
        C = dict(copy.deepcopy(L), id=os.urandom(4).hex(), y=min(L["y"] + 12, th))
        if L["wrap"]:
            C["y"] = min(L["y"] + L["h"] + 4, th)
        else:
            C["x"] = (L["x"] + 14) % tw
        self.edit(lambda: self.design["layers"].append(C), "duplicate")
        self.set_selected(C["id"])

    def delete_selected(self):
        L = self.selected()
        if L is None:
            return
        self.edit(lambda: self.design["layers"].remove(L), "delete")
        self.set_selected("")

    def remove_layer(self, lid):
        self.edit(lambda: self.design["layers"].__setitem__(
            slice(None), [L for L in self.design["layers"] if L["id"] != lid]), "delete")
        if self.sel_id == lid:
            self.set_selected("")

    def move_layer(self, lid, d):
        ls = self.design["layers"]
        i = next((n for n, L in enumerate(ls) if L["id"] == lid), None)
        if i is None or not 0 <= i + d < len(ls):
            return

        def swap():
            ls[i], ls[i + d] = ls[i + d], ls[i]
        self.edit(swap, "order")

    def clear_all(self):
        if not self.design["layers"]:
            return
        self.edit(lambda: self.design["layers"].clear(), "clear")
        self.set_selected("")

    def set_prop(self, key, value, coalesce=None):
        L = self.selected()
        if L is None:
            return

        def apply():
            if key.startswith("param:"):
                L["params"][key[6:]] = value
            else:
                L[key] = value
        self.edit(apply, key, coalesce=coalesce or f"{L['id']}:{key}")

    # ── refresh ──────────────────────────────────────────────────────────
    def _changed(self):
        self._render_timer.start()
        self._stage_timer.start()
        self._refresh_hint()
        self._update_buttons()

    def _sync_all(self):
        self._refresh_layer_list()
        self._refresh_props()
        self._refresh_skin()
        self._refresh_hint()
        self._update_buttons()
        self._render_map()
        self._stage_timer.start()

    def _refresh_hint(self):
        L = self.selected()
        for b in (self.edit_btn, self.dup_btn, self.del_btn):
            b.setVisible(L is not None)
        if L is not None:
            self.hint.setText("Drag to move it (onto another arm or leg too). Square: size. Dot: turn. "
                              "Mouse wheel: size.")
        elif self.design["layers"]:
            self.hint.setText("Click a tattoo to change it, or click the skin to choose where the next one goes.")
        else:
            self.hint.setText("Click the skin to choose a spot, then pick a tattoo on the left.")

    def base_skin(self):
        return Rn.adjust_skin(self.base_source, self.adjust)

    def composed(self, with_others=False):
        base = self.base_skin()
        over = Rn.render_overlay(self.design, base, self.library) if Rn.has_ink(self.design) else None
        return Rn.compose(base, over, self.other_layers if with_others else ())

    def _render_map(self):
        try:
            self.map.atlas = _qimage(self.composed())
        except Exception as e:
            log.warning(f"tattoo preview failed: {e}")
        self.map.update()

    def _update_stage(self):
        if self.stage_box is None or self._closed:
            return
        try:
            folder = os.path.join(config.temp_directory, "tattoo_preview")
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"skin_{os.getpid()}_{time.monotonic_ns()}.png")
            self.composed(with_others=True).save(path)
            self._screen.refresh_stage(preview_skin=path)
            for old in self._preview_files[:-1]:
                try:
                    os.remove(old)
                except OSError:
                    pass
            self._preview_files = self._preview_files[-1:] + [path]
        except Exception as e:
            log.warning(f"3D tattoo preview failed: {e}")

    def _turn_stage(self, yaw):
        pv = getattr(self.stage, "player_view", None)
        if pv is not None:
            pv.renderer.yaw = yaw
            pv.update()

    # ── left: add ────────────────────────────────────────────────────────
    def _build_add(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.cat = Chips([(c, c.upper()) for c in CATEGORIES], per_row=2, value="Fully inked")
        for b in self.cat.buttons.values():
            b.setFixedHeight(24)
        self.cat.picked.connect(lambda _c: self._fill_catalogue())
        v.addWidget(self.cat)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search (e.g. fern, cross, sleeve)")
        self.search.setClearButtonEnabled(True)
        self.search.setStyleSheet(
            f"QLineEdit {{ background: {BG_HIGHLIGHT}; color: {FG_PRIMARY}; border: 1px solid {BORDER};"
            f" padding: 4px 6px; font-family: '{FONT_BODY}'; font-size: 10pt; }}")
        self.search.textChanged.connect(lambda _t: self._fill_catalogue())
        v.addWidget(self.search)
        self.grid_scroll = QScrollArea()
        self.grid_scroll.setWidgetResizable(True)
        self.grid_scroll.setFrameShape(QFrame.NoFrame)
        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(6)
        self.grid_scroll.setWidget(self.grid_host)
        v.addWidget(self.grid_scroll, 1)
        self.import_btn = compact_button("IMPORT A PICTURE…")
        self.import_btn.clicked.connect(self.import_picture)
        v.addWidget(self.import_btn)
        return page

    def _catalogue(self):
        """[(key, name, thumb_fn, on_click, removable)] for the category / search."""
        q = self.search.text().strip().lower()
        out = []
        if q:
            for mid, mo in M.REG.items():
                if q in f"{mo.name} {mo.tags} {mo.cat}".lower():
                    out.append((mid, mo.name, lambda m=mid: motif_thumb(m), lambda m=mid: self.add_motif(m), False))
            for it in self.library.items():
                if q in it["name"].lower():
                    out.append((it["id"], it["name"], lambda m=it["id"]: motif_thumb(m, self.library),
                                lambda m=it["id"]: self.add_motif(m), True))
            return out
        cat = self.cat.value()
        if cat == READY:
            return [(f"ready:{k}", v[0], lambda k=k: ready_thumb(k), lambda k=k: self.add_ready(k), False)
                    for k, v in G.STYLES.items()]
        if cat == MINE:
            return [(it["id"], it["name"], lambda m=it["id"]: motif_thumb(m, self.library),
                     lambda m=it["id"]: self.add_motif(m), True) for it in self.library.items()]
        return [(mid, mo.name, lambda m=mid: motif_thumb(m), lambda m=mid: self.add_motif(m), False)
                for mid, mo in M.REG.items() if mo.cat == cat]

    def _fill_catalogue(self):
        while self.grid.count():
            w = self.grid.takeAt(0).widget()
            if w is not None:
                w.hide()
                w.setParent(None)
                w.deleteLater()
        items = self._catalogue()
        cols = 3
        tiles = []
        for i, (key, name, thumb, click, removable) in enumerate(items):
            t = Tile(name)
            t.clicked.connect(lambda _c=False, f=click: f())
            if removable:
                t.setContextMenuPolicy(Qt.CustomContextMenu)
                t.customContextMenuRequested.connect(lambda _p, k=key, n=name: self._confirm_remove_picture(k, n))
                t.setToolTip(f"{name} — right-click to remove it from your pictures")
            self.grid.addWidget(t, i // cols, i % cols)
            tiles.append((t, thumb))
        if not items:
            msg = ("No picture yet. IMPORT A PICTURE puts a drawing or a photo of a tattoo here."
                   if self.cat.value() == MINE and not self.search.text() else "Nothing found.")
            self.grid.addWidget(_label(msg, T_SMALL, FG_TERTIARY), 0, 0, 1, cols)
        self.grid.setRowStretch(len(items) // cols + 1, 1)
        self._thumb_jobs = tiles
        QTimer.singleShot(0, self._load_thumbs)

    def _load_thumbs(self):
        """Thumbnails a few at a time, so the list shows at once."""
        t0 = time.monotonic()
        while self._thumb_jobs and time.monotonic() - t0 < 0.03:
            tile, thumb = self._thumb_jobs.pop(0)
            try:
                tile.set_pix(thumb())
            except RuntimeError:                  # the tile went with a newer list
                pass
        if self._thumb_jobs:
            QTimer.singleShot(0, self._load_thumbs)

    def _confirm_remove_picture(self, key, name):
        def done(role):
            if role == "remove":
                self.library.remove(key[5:])
                _THUMBS.pop(("m", key), None)
                self._fill_catalogue()
        ConfirmDialog(self, f"Remove “{name}”?", "It leaves your pictures. Tattoos made with it keep it.",
                      [("CANCEL", "neutral", "cancel"), ("REMOVE", "danger", "remove")], done)

    # ── importing ────────────────────────────────────────────────────────
    def import_picture(self, path=None):
        if not path:
            start = getattr(TattooEditor, "_last_dir", "") or os.path.expanduser("~")
            path, _ = QFileDialog.getOpenFileName(self, "Import a tattoo picture", start,
                                                  "Pictures (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
            if not path:
                return
            TattooEditor._last_dir = os.path.dirname(path)
        try:
            with open(path, "rb") as fh:
                data = fh.read()
            S.preview_import(data)
        except Exception as e:
            ConfirmDialog(self, "This picture can't be used", str(e) or "Unreadable file.",
                          [("OK", "primary", "ok")], lambda _r: None, cancel_role="ok")
            return
        ImportDialog(self, data, os.path.splitext(os.path.basename(path))[0], self._imported)

    def _imported(self, item):
        if item is None:
            return
        self.cat.set_value(MINE)
        self.search.clear()
        self._fill_catalogue()
        self.add_motif(item["id"])

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls() and any(u.isLocalFile() for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        files = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        if files:
            pos = self.map.mapFrom(self, e.pos())
            at = self.map.tile_at(QPointF(pos))
            if at is not None:
                self.set_spot(*at)
            QTimer.singleShot(0, lambda: self.import_picture(files[0]))

    # ── left: layers ─────────────────────────────────────────────────────
    def _build_layers(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        self.list_scroll = QScrollArea()
        self.list_scroll.setWidgetResizable(True)
        self.list_scroll.setFrameShape(QFrame.NoFrame)
        self.list_scroll.setFixedHeight(150)
        self.list_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.list_host = QWidget()
        self.list_v = QVBoxLayout(self.list_host)
        self.list_v.setContentsMargins(0, 0, 0, 0)
        self.list_v.setSpacing(2)
        self.list_scroll.setWidget(self.list_host)
        v.addWidget(self.list_scroll)
        self.props_scroll = QScrollArea()
        self.props_scroll.setWidgetResizable(True)
        self.props_scroll.setFrameShape(QFrame.NoFrame)
        v.addWidget(self.props_scroll, 1)
        row = QHBoxLayout()
        clear = compact_button("REMOVE ALL", "danger")
        clear.setFixedHeight(28)
        clear.clicked.connect(self._confirm_clear)
        row.addStretch(1)
        row.addWidget(clear)
        v.addLayout(row)
        return page

    def _confirm_clear(self):
        if not self.design["layers"]:
            return
        ConfirmDialog(self, "Remove every tattoo?", "UNDO brings them back.",
                      [("CANCEL", "neutral", "cancel"), ("REMOVE ALL", "danger", "go")],
                      lambda r: self.clear_all() if r == "go" else None)

    def _refresh_layer_list(self):
        while self.list_v.count():
            it = self.list_v.takeAt(0)
            if it.widget():
                it.widget().hide()
                it.widget().setParent(None)
                it.widget().deleteLater()
        layers = self.design["layers"]
        if not layers:
            self.list_v.addWidget(_label("No tattoo yet. Choose a spot on the body, then a tattoo in ADD.",
                                         T_SMALL, FG_TERTIARY))
        for L in reversed(layers):                 # top first
            self.list_v.addWidget(self._layer_row(L))
        self.list_v.addStretch(1)

    def _layer_row(self, L):
        w = QFrame()
        on = L["id"] == self.sel_id
        w.setStyleSheet(f"QFrame {{ background: {ACCENT_DARK if on else BG_HIGHLIGHT}; border: none; }}")
        h = QHBoxLayout(w)
        h.setContentsMargins(4, 1, 2, 1)
        h.setSpacing(2)

        def small(text, tip, fn, width=24):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.setFixedSize(width, 22)
            b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            b.setCursor(Qt.PointingHandCursor)
            b.setFocusPolicy(Qt.NoFocus)
            b.setStyleSheet(f"QPushButton {{ background: transparent; color: {FG_SECONDARY}; border: none;"
                            f" font-size: 10pt; }} QPushButton:hover {{ color: {FG_PRIMARY}; }}")
            b.clicked.connect(fn)
            return b

        h.addWidget(small("●" if L["visible"] else "○", "show / hide",
                          lambda: self._toggle_visible(L["id"])))
        side = {"both": "both", "a": "right", "b": "left"}[L["side"]]
        where = f"{side} {L['limb']}s" if L["side"] == "both" else f"{side} {L['limb']}"
        name = QPushButton()
        name.setToolTip(f"{L['name']} — {where}")
        name.setMinimumWidth(40)
        name.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Fixed)
        fm = name.fontMetrics()
        name.setText(fm.elidedText(f"{L['name']} · {where}", Qt.ElideRight, 160))
        name.setFlat(True)
        name.setCursor(Qt.PointingHandCursor)
        name.setFocusPolicy(Qt.NoFocus)
        name.setStyleSheet(f"QPushButton {{ text-align: left; background: transparent; border: none;"
                           f" color: {FG_PRIMARY if L['visible'] else FG_MUTED}; font-family: '{FONT_BODY}';"
                           f" font-size: 9pt; padding: 2px; }}")
        name.clicked.connect(lambda: self.set_selected(L["id"]))
        h.addWidget(name, 1)
        h.addWidget(small("▲", "in front", lambda: self.move_layer(L["id"], 1), 20))
        h.addWidget(small("▼", "behind", lambda: self.move_layer(L["id"], -1), 20))
        h.addWidget(small("✕", "delete", lambda: self.remove_layer(L["id"]), 20))
        return w

    def _toggle_visible(self, lid):
        L = next((x for x in self.design["layers"] if x["id"] == lid), None)
        if L is not None:
            self.edit(lambda: L.__setitem__("visible", not L["visible"]), "show")
            self._refresh_layer_list()

    def _refresh_props(self):
        old = self.props_scroll.takeWidget()
        if old is not None:
            old.deleteLater()
        host = QWidget()
        v = QVBoxLayout(host)
        v.setContentsMargins(0, 4, 6, 4)
        v.setSpacing(6)
        L = self.selected()
        self._text_edit = None
        if L is None:
            v.addWidget(_label("Click a tattoo on the body (or in the list) to change it.", T_SMALL, FG_TERTIARY))
            v.addStretch(1)
            self.props_scroll.setWidget(host)
            return
        mo = M.REG.get(L["motif"])
        v.addWidget(eyebrow_label(L["name"], color=ACCENT, size=T_SMALL))

        def slider(label, key, lo, hi, fmt=None, value=None):
            s = Slider(label, lo, hi, L[key] if value is None else value, fmt)
            s.pressed.connect(lambda: self.begin_edit(key))
            s.moved.connect(lambda val: self._slide(key, val))
            s.released.connect(lambda: self.end_edit())
            v.addWidget(s)
            return s

        atlas = L["motif"] == Rn.ATLAS_MOTIF
        if not atlas:
            if L["wrap"]:
                slider("Height", "h", 2, 256, lambda x: f"{x:.0f}")
            else:
                slider("Size", "size", 4, 260, lambda x: f"{x:.0f}", value=max(L["w"], L["h"]))
                slider("Turn", "rot", -180, 180, lambda x: f"{x:.0f}°")
        slider("Strength", "opacity", .05, 1, lambda x: f"{x * 100:.0f}%")
        if not atlas:
            slider("Faded lines", "soft", 0, 3, lambda x: f"{x:.1f}")
            colour_mode = L["motif"].startswith("user:") and (self.library.item(L["motif"][5:]) or {}).get("mode") == "colour"
            if not colour_mode:
                v.addWidget(_label("Ink colour", T_SMALL, FG_SECONDARY, bold=True))
                row = QHBoxLayout()
                row.setSpacing(4)
                for c in INKS:
                    b = QPushButton()
                    b.setFixedSize(26, 22)
                    b.setCursor(Qt.PointingHandCursor)
                    b.setFocusPolicy(Qt.NoFocus)
                    edge = FG_PRIMARY if L["color"].lower() == c else BORDER
                    b.setStyleSheet(f"QPushButton {{ background: {c}; border: 2px solid {edge}; }}")
                    b.clicked.connect(lambda _c=False, col=c: self._set_and_refresh("color", col))
                    row.addWidget(b)
                more = QPushButton("…")
                more.setFixedSize(26, 22)
                more.setToolTip("any colour")
                more.setFocusPolicy(Qt.NoFocus)
                more.clicked.connect(self._pick_colour)
                row.addWidget(more)
                row.addStretch(1)
                v.addLayout(row)
            look = Chips([("embed", "REAL INK"), ("opaque", "FLAT")], per_row=2, value=L["ink"])
            look.picked.connect(lambda val: self._set_and_refresh("ink", val))
            look.setToolTip("REAL INK lets the skin show through like a real tattoo")
            v.addWidget(look)
        v.addWidget(_label("On", T_SMALL, FG_SECONDARY, bold=True))
        sides = Chips(SIDES, per_row=3, value=L["side"])
        sides.picked.connect(lambda val: self._set_and_refresh("side", val))
        v.addWidget(sides)
        if not atlas:
            limb = Chips([("arm", "ARM"), ("leg", "LEG")], per_row=2, value=L["limb"])
            limb.picked.connect(self._set_limb)
            v.addWidget(limb)
            flags = QHBoxLayout()
            mirror = Toggle("MIRROR", L["flip"])
            mirror.clicked.connect(lambda on: self._set_and_refresh("flip", bool(on)))
            flags.addWidget(mirror)
            band = Toggle("ALL ROUND", L["wrap"])
            band.setToolTip("Spread it right round the arm or leg, like a band")
            band.clicked.connect(lambda on: self._set_and_refresh("wrap", bool(on)))
            flags.addWidget(band)
            flags.addStretch(1)
            v.addLayout(flags)
        if mo is not None and mo.params:
            v.addWidget(_label("Shape", T_SMALL, FG_SECONDARY, bold=True))
            for spec in mo.params:
                k = spec["k"]
                cur = L["params"].get(k, spec["default"])
                if spec["type"] == "range":
                    integer = isinstance(spec["default"], int)
                    s = Slider(spec["label"], spec["min"], spec["max"], float(cur),
                               (lambda x: f"{round(x):.0f}") if integer else None)
                    s.pressed.connect(lambda k=k: self.begin_edit(k))
                    s.moved.connect(lambda val, k=k, i=integer: self._slide("param:" + k, round(val) if i else val))
                    s.released.connect(lambda: self.end_edit())
                    v.addWidget(s)
                elif spec["type"] == "choice":
                    v.addWidget(_label(spec["label"], T_SMALL, FG_TERTIARY))
                    ch = Chips([(str(o), str(o).upper()) for o in spec["options"]], per_row=3, value=str(cur))
                    ch.picked.connect(lambda val, k=k: self._set_and_refresh("param:" + k, val))
                    v.addWidget(ch)
                else:
                    v.addWidget(_label(spec["label"], T_SMALL, FG_TERTIARY))
                    ed = QLineEdit(str(cur))
                    ed.setMaxLength(40)
                    ed.setStyleSheet(f"QLineEdit {{ background: {BG_HIGHLIGHT}; color: {FG_PRIMARY};"
                                     f" border: 1px solid {BORDER}; padding: 4px; font-size: 11pt; }}")
                    ed.textEdited.connect(lambda t, k=k: self.set_prop("param:" + k, t, coalesce=f"text:{k}"))
                    v.addWidget(ed)
                    self._text_edit = ed
            if mo.kind == "gen":
                again = compact_button("ANOTHER ONE")
                again.setToolTip("Another version of this design")
                again.clicked.connect(lambda: self._set_and_refresh("seed", random.randrange(1, 999999)))
                v.addWidget(again)
        v.addStretch(1)
        self.props_scroll.setWidget(host)

    def _focus_text(self):
        if self._text_edit is not None:
            self._text_edit.setFocus()
            self._text_edit.selectAll()

    def _slide(self, key, val):
        L = self.selected()
        if L is None:
            return
        if key == "size":
            big = max(L["w"], L["h"]) or 1
            f = val / big
            L["w"], L["h"] = max(4, L["w"] * f), max(2, L["h"] * f)
        elif key.startswith("param:"):
            L["params"][key[6:]] = val
        else:
            L[key] = val
        self._changed()

    def _set_and_refresh(self, key, value):
        self.set_prop(key, value)
        self._refresh_props()
        self._refresh_layer_list()

    def _set_limb(self, limb):
        L = self.selected()
        if L is None or L["limb"] == limb:
            return

        def apply():
            L["limb"] = limb
            L["x"] = Rn.LIMBS[limb]["front"]
            L["y"] = min(L["y"], Rn.LIMBS[limb]["size"][1] - 10)
        self.edit(apply, "limb")
        self._refresh_props()
        self._refresh_layer_list()

    def _pick_colour(self):
        L = self.selected()
        if L is None:
            return
        c = QColorDialog.getColor(QColor(L["color"]), self, "Ink colour")
        if c.isValid():
            self._set_and_refresh("color", c.name())

    # ── left: skin ───────────────────────────────────────────────────────
    def _build_skin(self):
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 0, 6, 0)
        v.setSpacing(8)
        v.addWidget(_label("The colour of the player's skin (arms and legs).", T_SMALL, FG_TERTIARY))
        self.skin_sliders = {}
        for key, label in ADJUST:
            s = Slider(label, -1, 1, self.adjust[key], lambda x: f"{x * 100:+.0f}" if abs(x) > .004 else "0")
            s.pressed.connect(lambda: self.begin_edit("skin"))
            s.moved.connect(lambda val, k=key: self._adjust(k, val))
            s.released.connect(lambda: self.end_edit())
            v.addWidget(s)
            self.skin_sliders[key] = s
        reset = compact_button("RESET")
        reset.clicked.connect(lambda: self.edit(lambda: self.adjust.update(Rn.clean_adjust({})), "reset skin")
                              or self._refresh_skin())
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(reset)
        v.addLayout(row)
        v.addStretch(1)
        return page

    def _adjust(self, key, val):
        self.adjust[key] = round(val, 3)
        self._changed()

    def _refresh_skin(self):
        for k, s in getattr(self, "skin_sliders", {}).items():
            s.set_value(self.adjust[k])

    def _show_mode(self, mode):
        self.pages.setCurrentIndex({"add": 0, "layers": 1, "skin": 2}.get(mode, 0))
        if mode == "layers":
            self._refresh_props()

    # ── close ────────────────────────────────────────────────────────────
    def save(self):
        if self._closed:
            return
        try:
            self.on_save(copy.deepcopy(self.design), dict(self.adjust))
        except Exception as e:
            log.error(f"saving tattoos failed: {e}")
            ConfirmDialog(self, "Could not save", str(e), [("OK", "primary", "ok")], lambda _r: None,
                          cancel_role="ok")
            return
        self._close()

    def cancel(self):
        if not self.dirty():
            self._close()
            return
        ConfirmDialog(self, "Leave without saving?", "Your changes to the tattoos and the skin are lost.",
                      [("KEEP EDITING", "neutral", "cancel"), ("LEAVE", "danger", "leave")],
                      lambda r: self._close() if r == "leave" else None)

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self._render_timer.stop()
        self._stage_timer.stop()
        self._screen.removeEventFilter(self)
        QApplication.instance().removeEventFilter(self)
        if hasattr(self._screen, "_dialog"):
            self._screen._dialog = getattr(self, "_prev_dialog", None)
        if self.stage_box is not None:
            reclaim = getattr(self._screen, "reclaim_stage", None)
            if callable(reclaim):
                reclaim()
        for old in self._preview_files:
            try:
                os.remove(old)
            except OSError:
                pass
        if self.on_close:
            self.on_close()
        self.hide()
        self.deleteLater()

    # ── overlay mechanics ────────────────────────────────────────────────
    def _place(self):
        self.setGeometry(self.parentWidget().rect())
        m = 12 if self.width() < 1200 else 24
        self.card.setGeometry(m, m, self.width() - 2 * m, self.height() - 2 * m)
        if self.stage_box is not None:
            self.stage_box.setFixedWidth(200 if self.width() < 1150 else 260 if self.width() < 1500 else 340)

    def eventFilter(self, watched, event):
        if watched is self._screen and event.type() == QEvent.Resize:
            self._place()
            return False
        if event.type() in (QEvent.ShortcutOverride, QEvent.KeyPress) and not self._closed \
                and isinstance(watched, QWidget) and (watched is self or self.isAncestorOf(watched)):
            mods = event.modifiers() & (Qt.ControlModifier | Qt.ShiftModifier)
            slot = self._keys.get((mods, event.key()))
            if slot is not None and not (isinstance(watched, QLineEdit) and mods != Qt.ControlModifier | Qt.ShiftModifier
                                         and event.key() in (Qt.Key_Z, Qt.Key_Y, Qt.Key_Delete)):
                if event.type() == QEvent.ShortcutOverride:
                    event.accept()                  # a key press, not the screen's shortcut
                    return False
                if self._top_dialog() is None:
                    slot()
                return True
        return False

    def _top_dialog(self):
        """A confirm / import dialog open over the editor (its keys are its own)."""
        return next((c for c in self.children() if isinstance(c, (ConfirmDialog, ImportDialog)) and c.isVisible()),
                    None)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 170))

    def mousePressEvent(self, e):
        e.accept()

    def keyPressEvent(self, e):
        k = e.key()
        L = self.selected()
        if k == Qt.Key_Escape:
            if L is not None:
                self.set_selected("")
            else:
                self.cancel()
        elif L is not None and k in (Qt.Key_Left, Qt.Key_Right, Qt.Key_Up, Qt.Key_Down):
            step = 5 if e.modifiers() & Qt.ShiftModifier else 1
            dx = {Qt.Key_Left: -step, Qt.Key_Right: step}.get(k, 0)
            dy = {Qt.Key_Up: -step, Qt.Key_Down: step}.get(k, 0)
            tw = Rn.LIMBS[L["limb"]]["size"][0]
            self.edit(lambda: L.update(x=(L["x"] + dx) % tw, y=L["y"] + dy), "nudge", coalesce="nudge")
        e.accept()


# ═════════════════════════════════════════════════════════════════════════
class ImportDialog(QWidget):
    """Import a picture: how it becomes a tattoo (one ink colour, or its own colours), with a live preview."""

    def __init__(self, editor, data, name, on_done):
        super().__init__(editor)
        self.editor, self.data, self.on_done = editor, data, on_done
        self.setGeometry(editor.rect())
        self.card = Card(stripe=ACCENT)
        self.card.setParent(self)
        self.card.setFixedSize(520, 470)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(22, 16, 22, 16)
        v.setSpacing(10)
        v.addWidget(display_label("import a picture", T_TITLE, QFont.Bold, track=0.8, upper=False))
        self.preview = QLabel()
        self.preview.setAlignment(Qt.AlignCenter)
        self.preview.setFixedHeight(220)
        self.preview.setStyleSheet("background: #d9c3ae; border: none;")
        v.addWidget(self.preview)
        self.mode = Chips([("ink", "ONE INK COLOUR"), ("colour", "KEEP ITS COLOURS")], per_row=2, value="ink")
        self.mode.picked.connect(lambda _m: self._update())
        v.addWidget(self.mode)
        self.light = Toggle("LIGHT DRAWING ON A DARK BACKGROUND")
        self.light.clicked.connect(lambda _c: self._update())
        v.addWidget(self.light)
        self.level = Slider("How dark counts as ink", 0, 1, .5, lambda x: f"{x * 100:.0f}")
        self.level.moved.connect(lambda _v: self._timer.start())
        v.addWidget(self.level)
        self.name = QLineEdit(name[:40])
        self.name.setPlaceholderText("Name")
        self.name.setStyleSheet(f"QLineEdit {{ background: {BG_HIGHLIGHT}; color: {FG_PRIMARY};"
                                f" border: 1px solid {BORDER}; padding: 4px; font-size: 11pt; }}")
        v.addWidget(self.name)
        row = QHBoxLayout()
        row.addStretch(1)
        cancel = compact_button("CANCEL")
        cancel.clicked.connect(lambda: self._finish(None))
        ok = compact_button("ADD", "primary")
        ok.clicked.connect(self._add)
        row.addWidget(cancel)
        row.addWidget(ok)
        v.addLayout(row)
        self._timer = QTimer(self, singleShot=True, interval=60, timeout=self._update)
        self.card.move((self.width() - self.card.width()) // 2, max(20, (self.height() - self.card.height()) // 2))
        self._update()
        self.show()
        self.raise_()
        self.name.setFocus()

    def _update(self):
        try:
            img = S.preview_import(self.data, self.mode.value(), self.light.isChecked(), self.level.value())
        except Exception:
            return
        img.thumbnail((460, 210))
        self.preview.setPixmap(QPixmap.fromImage(_qimage(img)))

    def _add(self):
        try:
            item = self.editor.library.add(self.data, self.name.text().strip() or "Picture", self.mode.value(),
                                           self.light.isChecked(), self.level.value())
        except ValueError as e:
            ConfirmDialog(self, "Nothing to import", str(e), [("OK", "primary", "ok")], lambda _r: None,
                          cancel_role="ok")
            return
        except Exception as e:
            log.error(f"tattoo import failed: {e}")
            ConfirmDialog(self, "Could not import", str(e), [("OK", "primary", "ok")], lambda _r: None,
                          cancel_role="ok")
            return
        self._finish(item)

    def _finish(self, item):
        self.hide()
        self.deleteLater()
        self.on_done(item)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 150))

    def mousePressEvent(self, e):
        e.accept()

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self._finish(None)
        elif e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._add()
        e.accept()
