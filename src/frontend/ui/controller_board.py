"""
ui/controller_board.py — who plays which team, the Rugby 08 way
================================================================
Three lanes: the home team, CPU (the middle) and the away team, and an icon
for the keyboard and for every gamepad connected. Each device moves its own
icon: a pad with its own d-pad or stick left/right (app.gamepad claims the
press while the board has the focus), the keyboard with its arrow keys, and
the mouse by clicking either half of an icon. A pad's icon flashes whenever
that pad presses something, so everyone can tell which icon is theirs.
Pads come and go as they are plugged in.
"""
import time

from PyQt5.QtCore import Qt, QRectF, QPointF, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QWidget

from app import gamepad
from app.input import Action, KEYMAP
from ui.theme import (ACCENT, AWAY_TINT, FG_MUTED, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY,
                      FONT_BODY, FONT_DISPLAY, HOME_TINT)

KBD = "kbd"
ZONES = ("home", "none", "away")            # lanes, left to right
_LANE_TINT = {"home": HOME_TINT, "none": FG_TERTIARY, "away": AWAY_TINT}
# One colour per device, so an icon is told apart from the others at a glance.
_DEVICE_TINT = (FG_SECONDARY, "#7ccf4a", "#c58cf2", "#ff9f1c", "#8fd3f4")

HEADER_H = 48
_ICON_INK = QColor(8, 14, 20, 225)   # the keys and buttons cut into an icon
CHIP_H = 40
CHIP_GAP = 6
CHIP_MAX_W = 230
FLASH_S = 0.45


class ControllerBoard(QWidget):
    changed = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.names = {"home": "HOME", "away": "AWAY"}
        self.crests = {}
        self.pads = ()                      # connected pads' indices, in order
        self.zones = {KBD: "home"}          # device: lane
        self._hover = None                  # (device, -1 | 1)
        self._flash = {}                    # device: time of its last press
        self._flash_timer = QTimer(self)
        self._flash_timer.setInterval(30)
        self._flash_timer.timeout.connect(self._tick_flash)
        self._nav = None
        self._hook()
        self._fit()

    def _hook(self):
        """Follow the pads (app.gamepad), once its navigator is running."""
        nav = gamepad.navigator()
        if nav is None or nav is self._nav:
            return
        self._nav = nav
        nav.pads_changed.connect(self.set_pads)
        nav.pad_pressed.connect(self._on_pad_pressed)
        self.set_pads(nav.connected())

    # ── model ────────────────────────────────────────────────────────────
    def devices(self):
        """The keyboard, then each connected pad."""
        return (KBD,) + tuple(self.pads)

    def label(self, device):
        return "KEYBOARD" if device == KBD else f"PAD {self.pads.index(device) + 1}"

    def set_pads(self, pads):
        pads = tuple(pads)
        if pads == self.pads:
            return
        self.pads = pads
        # A pad unplugged leaves its lane; a new one starts as CPU.
        self.zones = {d: self.zones.get(d, "none") for d in self.devices()}
        self._fit()
        self.update()
        self.changed.emit()

    def set_zone(self, device, zone):
        if self.zones.get(device) == zone or zone not in ZONES:
            return
        self.zones[device] = zone
        self.update()
        self.changed.emit()

    def move(self, device, delta):
        """One lane left (-1) or right (+1); stops at the ends."""
        if device not in self.zones:
            return
        i = max(0, min(len(ZONES) - 1, ZONES.index(self.zones[device]) + delta))
        self.set_zone(device, ZONES[i])

    def pad_zones(self):
        """Each connected pad's lane, in the game's pad order."""
        return [self.zones[n] for n in self.pads]

    def set_teams(self, names, crests=None):
        self.names = dict(names)
        self.crests = dict(crests or {})
        self.update()

    # ── input ────────────────────────────────────────────────────────────
    def _claim(self, pad, name):
        """A pad's left/right moves its own icon while the board has the focus."""
        if name not in ("left", "right") or pad not in self.zones:
            return False
        self.move(pad, -1 if name == "left" else 1)
        return True

    def _on_pad_pressed(self, pad, _name):
        if pad in self.zones and self.isVisible():
            self._flash[pad] = time.monotonic()
            self._flash_timer.start()

    def focusInEvent(self, event):
        nav = gamepad.navigator()
        if nav is not None:
            nav.claim = self._claim
        self.update()
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        nav = gamepad.navigator()
        if nav is not None and nav.claim == self._claim:
            nav.claim = None
        self.update()
        super().focusOutEvent(event)

    def showEvent(self, event):
        self._hook()
        super().showEvent(event)

    def hideEvent(self, event):
        nav = gamepad.navigator()
        if nav is not None and nav.claim == self._claim:
            nav.claim = None
        super().hideEvent(event)

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action in (Action.NAV_LEFT, Action.NAV_RIGHT):
            self.move(KBD, -1 if action == Action.NAV_LEFT else 1)
            event.accept()
            return
        event.ignore()

    def _hit(self, pos):
        """(device, -1 | 1): the icon under `pos` and which half of it."""
        for device, rect in self._chip_rects().items():
            if rect.contains(pos):
                return device, (-1 if pos.x() < rect.center().x() else 1)
        return None

    def mouseMoveEvent(self, event):
        hit = self._hit(QPointF(event.pos()))
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, event):
        self._hover = None
        self.update()

    def mousePressEvent(self, event):
        hit = self._hit(QPointF(event.pos()))
        if hit and event.button() == Qt.LeftButton:
            self.move(*hit)
        super().mousePressEvent(event)

    # ── geometry ─────────────────────────────────────────────────────────
    def _fit(self):
        rows = max(2, len(self.devices()))
        self.setFixedHeight(HEADER_H + rows * (CHIP_H + CHIP_GAP) + CHIP_GAP)

    def _lane_rect(self, i):
        w = self.width() / len(ZONES)
        return QRectF(i * w + 4, 2, w - 8, self.height() - 4)

    def _row_y(self, row):
        return 2 + HEADER_H + row * (CHIP_H + CHIP_GAP)

    def _chip_rects(self):
        """Each device on its own row, in its lane's column."""
        out = {}
        for row, device in enumerate(self.devices()):
            lane = self._lane_rect(ZONES.index(self.zones[device]))
            w = min(CHIP_MAX_W, lane.width() - 12)
            out[device] = QRectF(lane.center().x() - w / 2, self._row_y(row), w, CHIP_H)
        return out

    # ── painting ─────────────────────────────────────────────────────────
    def _tick_flash(self):
        now = time.monotonic()
        self._flash = {d: t for d, t in self._flash.items() if now - t < FLASH_S}
        if not self._flash:
            self._flash_timer.stop()
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        for i, zone in enumerate(ZONES):
            self._paint_lane(p, i, zone)
        self._paint_tracks(p)
        now = time.monotonic()
        for device, rect in self._chip_rects().items():
            flash = max(0.0, 1 - (now - self._flash[device]) / FLASH_S) if device in self._flash else 0.0
            self._paint_chip(p, device, rect, flash)
        if self.hasFocus():
            p.setPen(QPen(QColor(ACCENT), 2))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(QRectF(self.rect()).adjusted(1, 1, -1, -1), 8, 8)
        p.end()

    def _paint_tracks(self, p):
        """A faint rail along each device's row, with a stop in every lane:
        the way its icon slides."""
        rail = QColor(FG_MUTED)
        rail.setAlpha(110)
        stops = [self._lane_rect(i).center().x() for i in range(len(ZONES))]
        for row in range(len(self.devices())):
            y = self._row_y(row) + CHIP_H / 2
            p.setPen(QPen(rail, 1.5, Qt.DashLine))
            p.drawLine(QPointF(stops[0], y), QPointF(stops[-1], y))
            p.setPen(Qt.NoPen)
            p.setBrush(rail)
            for x in stops:
                p.drawEllipse(QPointF(x, y), 3, 3)

    def _paint_lane(self, p, i, zone):
        lane = self._lane_rect(i)
        tint = QColor(_LANE_TINT[zone])
        fill = QColor(tint)
        fill.setAlpha(22 if zone != "none" else 10)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawRoundedRect(lane, 6, 6)
        bar = QColor(tint)
        bar.setAlpha(200 if zone != "none" else 70)
        p.setBrush(bar)
        p.drawRect(QRectF(lane.left() + 10, lane.top() + HEADER_H - 6, lane.width() - 20, 2))

        head = QRectF(lane.left(), lane.top(), lane.width(), HEADER_H - 8)
        text = "CPU" if zone == "none" else self.names.get(zone, zone).upper()
        p.setFont(QFont(FONT_DISPLAY, 13, QFont.Bold))
        fm = p.fontMetrics()
        pix = self.crests.get(zone)
        crest = 34 if pix is not None and not pix.isNull() else 0
        room = head.width() - 24 - (crest + 8 if crest else 0)
        if crest and room < 80:             # a narrow lane: the crest says it
            text, room = "", -8
        text = fm.elidedText(text, Qt.ElideRight, int(max(room, 0)))
        total = fm.horizontalAdvance(text) + (crest + 8 if crest else 0)
        x = head.center().x() - total / 2
        if crest:
            p.drawPixmap(QRectF(x, head.center().y() - crest / 2, crest, crest), pix, QRectF(pix.rect()))
            x += crest + 8
        p.setPen(QColor(FG_PRIMARY if zone != "none" else FG_TERTIARY))
        p.drawText(QRectF(x, head.top(), room + 4, head.height()), Qt.AlignVCenter | Qt.AlignLeft, text)

    def _paint_chip(self, p, device, rect, flash):
        tint = QColor(_DEVICE_TINT[0 if device == KBD else 1 + self.pads.index(device) % 4])
        fill = QColor(tint)
        fill.setAlpha(int(46 + 150 * flash))
        p.setPen(QPen(tint, 2))
        p.setBrush(fill)
        p.drawRoundedRect(rect, 10, 10)

        icon = QRectF(rect.center().x() - 19, rect.center().y() - 12.5, 38, 25)
        if device == KBD:
            self._paint_keyboard(p, icon, tint)
        else:
            self._paint_pad(p, icon, tint)
            # the pad's number, on a badge at its corner
            badge = QPointF(icon.right() + 1, icon.top() + 3)
            p.setPen(QPen(tint, 1.5))
            p.setBrush(_ICON_INK)
            p.drawEllipse(badge, 7, 7)
            p.setPen(QColor(FG_PRIMARY))
            p.setFont(QFont(FONT_DISPLAY, 8, QFont.Bold))
            p.drawText(QRectF(badge.x() - 7, badge.y() - 7, 14, 14), Qt.AlignCenter,
                       str(self.pads.index(device) + 1))

        # ‹ › where the icon can still go; brighter under the mouse
        zone_i = ZONES.index(self.zones[device])
        p.setFont(QFont(FONT_DISPLAY, 16, QFont.Bold))
        for delta, x, align in ((-1, rect.left() + 6, Qt.AlignLeft), (1, rect.right() - 18, Qt.AlignRight)):
            if not 0 <= zone_i + delta < len(ZONES):
                continue
            hot = self._hover == (device, delta)
            p.setPen(QColor(FG_PRIMARY if hot else FG_MUTED))
            p.drawText(QRectF(x, rect.top(), 12, rect.height()), Qt.AlignVCenter | align,
                       "‹" if delta < 0 else "›")

    @staticmethod
    def _paint_keyboard(p, r, tint):
        """A filled keyboard: three rows of keys and a space bar, drawn on a
        48 x 32 grid scaled into `r`."""
        p.save()
        p.translate(r.topLeft())
        p.scale(r.width() / 48, r.height() / 32)
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(QRectF(1, 5, 46, 23), 4, 4)
        p.setBrush(_ICON_INK)
        for y, start, count in ((8.5, 4.2, 9), (13.5, 6.4, 8)):
            for k in range(count):
                p.drawRoundedRect(QRectF(start + k * 4.6, y, 3.4, 3.4), 0.8, 0.8)
        p.drawRoundedRect(QRectF(4.2, 19, 7.4, 3.4), 0.8, 0.8)
        p.drawRoundedRect(QRectF(13.4, 19, 21.2, 3.4), 0.8, 0.8)
        p.drawRoundedRect(QRectF(36.4, 19, 7.4, 3.4), 0.8, 0.8)
        p.restore()

    @staticmethod
    def _paint_pad(p, r, tint):
        """A filled gamepad: grips, d-pad, two sticks, four face buttons, on
        a 48 x 32 grid scaled into `r`."""
        p.save()
        p.translate(r.topLeft())
        p.scale(r.width() / 48, r.height() / 32)
        body = QPainterPath()
        body.moveTo(13, 4)
        body.lineTo(35, 4)
        body.cubicTo(42, 4, 45, 7, 46.4, 13)
        body.cubicTo(48, 21, 48.2, 28, 44.5, 30.2)
        body.cubicTo(41, 32, 37.5, 28.5, 34.5, 24.5)
        body.lineTo(13.5, 24.5)
        body.cubicTo(10.5, 28.5, 7, 32, 3.5, 30.2)
        body.cubicTo(-0.2, 28, 0, 21, 1.6, 13)
        body.cubicTo(3, 7, 6, 4, 13, 4)
        body.closeSubpath()
        p.setPen(Qt.NoPen)
        p.setBrush(tint)
        p.drawRoundedRect(QRectF(8, 1.5, 9, 4), 1.5, 1.5)        # shoulder buttons
        p.drawRoundedRect(QRectF(31, 1.5, 9, 4), 1.5, 1.5)
        p.drawPath(body)
        p.setBrush(_ICON_INK)
        p.drawRoundedRect(QRectF(7.6, 11.4, 8.8, 3.2), 0.8, 0.8)  # d-pad
        p.drawRoundedRect(QRectF(10.4, 8.6, 3.2, 8.8), 0.8, 0.8)
        for dx, dy in ((0, -3.2), (3.2, 0), (0, 3.2), (-3.2, 0)):
            p.drawEllipse(QPointF(36 + dx, 13 + dy), 1.7, 1.7)
        for x in (18.5, 29.5):                                    # sticks
            p.drawEllipse(QPointF(x, 19.5), 3.6, 3.6)
        p.setBrush(tint)
        for x in (18.5, 29.5):
            p.drawEllipse(QPointF(x, 19.5), 1.8, 1.8)
        p.setBrush(_ICON_INK)
        p.drawEllipse(QPointF(24, 10), 1.6, 1.6)                  # guide button
        p.restore()
