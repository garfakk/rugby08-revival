"""
ui/coin_toss.py — Coin toss overlay shown between KICK OFF and the match
============================================================================
A compact modal panel over the calling screen that runs
app/coin_toss.CoinToss step by step, with as little text as possible: the
coin spins on its own (the call is made for the caller), the result reads
YOU WON THE TOSS / YOU LOST THE TOSS, and after a short beat the other
team's choice is announced ("SAMOA CHOSE TO KICK OFF").

The coin is rugby-faced: heads carries the goalposts (the "H"), tails a
ball. Under it, the pitch shows both ends and the match wind — what the end
choice is really about — and is where the player decides, in one click:
an end to take it, halfway to kick off (only the choice that is theirs).
Hovering an option shows the crests where it puts them. KICK OFF then
starts the match.

    run_coin_toss(screen, names, humans, on_done, on_cancel, wind)
    toss_for_match(screen, ds, cfg, on_done, on_cancel)   # names/humans/wind from a MatchConfig

`screen` is the app.screen_base.Screen it covers (its FocusManager is scoped
to the panel while open). on_done receives CoinToss.resolved(); BACK at any
point cancels and calls on_cancel.
"""
import math
from dataclasses import replace

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QApplication, QAbstractButton
from PyQt5.QtGui import (
    QPainter, QColor, QFont, QPen, QRadialGradient, QBrush, QPolygonF,
    QPainterPath, QTransform, QLinearGradient, QFontMetrics,
)
from PyQt5.QtCore import (Qt, QTimer, QVariantAnimation, QEasingCurve, QRectF, QPointF, QEvent, QSize,
                          pyqtSignal)

from app.coin_toss import (
    CoinToss, HEADS, TAILS, KICK_OFF, CHOOSE_END, LEFT, RIGHT,
)
from app.game_data import WIND_POWER_NAMES
from app.input import Action, KEYMAP
from ui import StyledButton
from ui.broadcast import Card, eyebrow_label, label_css
from ui.theme import (
    ACCENT, HOME_TINT, AWAY_TINT, FG_PRIMARY, FG_TERTIARY, GREEN, DANGER_LITE, WARN,
    FONT_DISPLAY, FONT_BODY, BTN_HEIGHT,
)

# How long a CPU captain "thinks" before each of its decisions, and how long
# the coin spins.
CPU_BEAT_MS = 1100
CALL_BEAT_MS = 400      # the panel on screen before the coin goes up
FLIP_MS = 2000
FLIP_TURNS = 6          # full turns before it settles on its face

_TINT = {"home": HOME_TINT, "away": AWAY_TINT}
# Struck-coin palette (bronze-gold, directional light from top-left).
_INK          = QColor("#4d3506")   # engraved line work
_INK_SOFT     = QColor(94, 63, 8)    # relief drop shadow
_LIGHT_KICK   = QColor(255, 243, 196)  # relief highlight
_GOLD_INK     = QColor("#5e440c")     # flat-glyph ink (paint_face default)

# Pitch palette.
_GRASS_A, _GRASS_B = (18, 116, 43), (21, 100, 37)   # mow stripes
_IN_GOAL_GRASS = QColor("#10491d")
_HAZE = QColor(143, 184, 201)
_LINE_WHITE = QColor(255, 255, 255, 235)
_LINE_GLOW = QColor(255, 255, 255, 72)
_POST_GLOW = QColor(190, 235, 255, 70)
_POST_INK = QColor("#f8f8f2")
_WIND_INK = QColor("#a8dcf7")


# ── coin faces ───────────────────────────────────────────────────────────
def _posts_paths(r):
    """Rugby goalposts in a unit of radius r: (outline path, filled pads)."""
    line = QPainterPath()
    x, top, ground, bar = r * 0.3, -r * 0.8, r * 0.48, r * 0.02
    for sx in (-x, x):
        line.moveTo(sx, ground)
        line.lineTo(sx, top)
    line.moveTo(-x, bar)
    line.lineTo(x, bar)
    line.moveTo(-r * 0.62, ground)
    line.lineTo(r * 0.62, ground)
    pads = QPainterPath()
    pw, ph = r * 0.17, r * 0.26
    for sx in (-x, x):
        pads.addRoundedRect(QRectF(sx - pw / 2, ground - ph, pw, ph), pw * 0.32, pw * 0.32)
    return line, pads


def _ball_paths(r):
    """A rugby ball side-on, tilted like a placed kick, laid out from the
    reference replica ball (logos removed): (body, cap_fills, cap_seams,
    lens, seam_up, seam_low).

    - body: prolate spheroid, four cubics with the ellipse constant;
    - two tip-to-tip seams bowing above and below the silhouette enclose a
      pointed central lens — the signature panel layout of the reference;
    - each tip is a coloured cap bounded by a seam that sweeps from the
      upper silhouette edge, around the tip, to the lower edge;
    - the long seams carry dashed stitching. No logos, no lace, no grip.
    """
    t = QTransform().rotate(-32)
    a, b, k = r * 0.64, r * 0.40, 0.5523      # ratio 2a/2b = 1.6

    body = QPainterPath(QPointF(-a, 0))
    body.cubicTo(QPointF(-a, -k * b), QPointF(-k * a, -b), QPointF(0, -b))
    body.cubicTo(QPointF(k * a, -b), QPointF(a, -k * b), QPointF(a, 0))
    body.cubicTo(QPointF(a, k * b), QPointF(k * a, b), QPointF(0, b))
    body.cubicTo(QPointF(-k * a, b), QPointF(-a, k * b), QPointF(-a, 0))

    seam_up = QPainterPath(QPointF(-a * 0.99, 0))        # tip to tip, above
    seam_up.cubicTo(QPointF(-a * 0.45, -b * 0.86),
                    QPointF(a * 0.45, -b * 0.86), QPointF(a * 0.99, 0))
    seam_low = QPainterPath(QPointF(-a * 0.99, 0))       # mirrored below
    seam_low.cubicTo(QPointF(-a * 0.45, b * 0.86),
                     QPointF(a * 0.45, b * 0.86), QPointF(a * 0.99, 0))

    lens = QPainterPath(QPointF(-a * 0.99, 0))           # the central almond
    lens.cubicTo(QPointF(-a * 0.45, -b * 0.86),
                 QPointF(a * 0.45, -b * 0.86), QPointF(a * 0.99, 0))
    lens.cubicTo(QPointF(a * 0.45, b * 0.86),
                 QPointF(-a * 0.45, b * 0.86), QPointF(-a * 0.99, 0))
    lens.closeSubpath()

    cap_seams, cap_fills = QPainterPath(), []
    for sx in (-1.0, 1.0):                               # a cap at each tip
        s = QPointF(sx * a * 0.68, -b * 0.72)             # upper edge
        e = QPointF(sx * a * 0.68, b * 0.72)              # lower edge
        c1, c2 = QPointF(sx * a * 0.92, -b * 0.42), QPointF(sx * a * 0.92, b * 0.42)
        cap_seams.moveTo(s)
        cap_seams.cubicTo(c1, c2, e)
        fill = QPainterPath(s)                           # seam, then the tip
        fill.cubicTo(c1, c2, e)
        fill.cubicTo(QPointF(sx * a * 0.731, b * 0.72),
                     QPointF(sx * a, 0.0), QPointF(sx * a, 0.0))
        fill.cubicTo(QPointF(sx * a, 0.0),
                     QPointF(sx * a * 0.731, -b * 0.72), s)
        fill.closeSubpath()
        cap_fills.append(fill)
    return (t.map(body), [t.map(f) for f in cap_fills], t.map(cap_seams),
            t.map(lens), t.map(seam_up), t.map(seam_low))


def paint_face(p, face, r, ink=_GOLD_INK, relief=None):
    """The face's mark centred on the painter's origin, sized for radius r.

    Without `relief`: a flat glyph in `ink` (button icons). With `relief`
    (a fill colour): a struck, embossed mark — a soft drop shadow, a bright
    offset highlight, then the mark itself filled with a top-lit gold
    gradient over `relief` and drawn in dark ink.
    """
    w = max(1.7, r * 0.07)
    if face == HEADS:
        line, pads = _posts_paths(r)
        layers = [(line, None, w), (pads, True, w * 0.55)]
        parts = None
    else:
        body, cap_fills, cap_seams, lens, seam_up, seam_low = _ball_paths(r)
        layers = [(body, True, w), (lens, None, w * 0.8), (cap_seams, None, w * 0.8)]
        parts = (cap_fills, lens, seam_up, seam_low)

    def _pass(offset, stroke, fill, alpha=255,
              lens_fill=None, cap_fill=None, stitch=None):
        p.save()
        p.translate(offset, offset)
        p.setOpacity(alpha / 255.0)
        if parts is not None and cap_fill is not None:   # panel colours first
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(cap_fill))
            for f in parts[0]:
                p.drawPath(f)
            p.setBrush(QBrush(lens_fill))
            p.drawPath(parts[1])
        for path, filled, width in layers:
            p.setPen(QPen(stroke, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            p.setBrush(QBrush(fill) if filled else Qt.NoBrush)
            p.drawPath(path)
        if stitch is not None and parts is not None:     # dashed stitching
            pen = QPen(stitch, w * 0.35, Qt.CustomDashLine, Qt.RoundCap)
            pen.setDashPattern([1.3, 1.3])
            p.setOpacity(alpha / 255.0 * 0.55)
            p.setPen(pen)
            p.setBrush(Qt.NoBrush)
            p.drawPath(parts[2])
            p.drawPath(parts[3])
        p.restore()

    if relief is None:
        if face == HEADS:
            _pass(0.0, QColor(ink), QColor(ink))
        else:                                            # replica tricolore
            _pass(0.0, QColor(ink), QColor("#eef1f5"),
                  lens_fill=QColor("#2a4fbf"), cap_fill=QColor("#e03131"),
                  stitch=QColor(ink))
        return

    fill = QLinearGradient(-r * 0.5, -r, r * 0.5, r)
    fill.setColorAt(0.0, QColor("#e9c063"))
    fill.setColorAt(1.0, QColor("#b5893a"))
    off = max(0.8, r * 0.066)
    _pass(off, _INK_SOFT, _INK_SOFT, 128,
          lens_fill=QColor("#4a3106"), cap_fill=QColor("#3a2503"))          # shadow
    _pass(-off * 0.64, _LIGHT_KICK, _LIGHT_KICK, 230,
          lens_fill=QColor("#fff0c0"), cap_fill=QColor("#f7e8b0"))          # highlight
    _pass(0.0, _INK, QBrush(fill), stitch=_INK,
          lens_fill=QColor("#a67c26"), cap_fill=QColor("#8a631c"))          # the mark


class CoinWidget(QWidget):
    """A struck gold coin spinning about its vertical axis: `angle` 0 shows
    heads, 180 tails; `lift` (0..1) raises it above its shadow. The coin is
    built up in layers — rim ring, face field, beaded rim, recessed legend
    band, embossed mark, specular crescent, vignette — so it reads as a
    minted object rather than a gold disc."""

    RADIUS = 54.0

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(170, 176)
        self.angle = 0.0
        self.lift = 0.0

    def set_pose(self, angle, lift=0.0):
        self.angle = angle
        self.lift = lift
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.RADIUS
        cx = self.width() / 2
        ground = self.height() - 14
        cy = ground - r - 6 - self.lift * 36

        cos = math.cos(math.radians(self.angle % 360))
        squash = abs(cos)
        rx = max(r * squash, 2.5)

        # ── soft contact shadow (a flattened radial gradient blob) ──
        sw = r * 2 * (1.0 - 0.4 * self.lift)
        shadow = QRadialGradient(0.0, 0.0, max(sw / 2, 1.0))
        shadow.setColorAt(0.0, QColor(0, 0, 0, 140))
        shadow.setColorAt(0.55, QColor(0, 0, 0, 80))
        shadow.setColorAt(1.0, QColor(0, 0, 0, 0))
        p.save()
        p.translate(cx + self.lift * 6, ground)
        p.scale(1.0, max(9 * (1.0 - 0.5 * self.lift) / (sw / 2), 0.05))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(shadow))
        p.drawEllipse(QRectF(-sw / 2, -sw / 2, sw, sw))
        p.restore()

        # ── milled edge, visible while the coin is turned ──
        edge = 9.0 * (1.0 - squash)
        if edge > 0.5:
            eg = QLinearGradient(0, cy - r, 0, cy + r)
            eg.setColorAt(0.0, QColor("#a37c22"))
            eg.setColorAt(0.5, QColor("#6e4d11"))
            eg.setColorAt(1.0, QColor("#4c320a"))
            p.setPen(Qt.NoPen)
            p.setBrush(QBrush(eg))
            p.drawEllipse(QRectF(cx - rx - edge / 2, cy - r - edge / 2, 2 * rx + edge, 2 * r + edge))
            p.setPen(QPen(QColor(59, 38, 5, 128), 1))
            for i in range(-22, 23):
                y = cy + i * r / 23
                half = math.sqrt(max(0.0, 1 - (i / 23) ** 2))
                p.drawLine(QPointF(cx - rx * half - edge / 2, y), QPointF(cx - rx * half, y))
            p.setPen(Qt.NoPen)

        # ── rim ring: directional bronze, light top-left → dark bottom-right ──
        rim = QLinearGradient(cx - rx * 0.6, cy - r, cx + rx * 0.6, cy + r)
        rim.setColorAt(0.0, QColor("#d9b457"))
        rim.setColorAt(0.45, QColor("#8a631c"))
        rim.setColorAt(1.0, QColor("#57390a"))
        p.setBrush(QBrush(rim))
        p.drawEllipse(QRectF(cx - rx, cy - r, 2 * rx, 2 * r))

        # ── face field, slightly inset, lit from top-left ──
        face = QRadialGradient(cx - rx * 0.28, cy - r * 0.4, r * 1.75)
        face.setColorAt(0.0, QColor("#fff3c9"))
        face.setColorAt(0.38, QColor("#f2cd6b"))
        face.setColorAt(0.78, QColor("#d4a23e"))
        face.setColorAt(1.0, QColor("#9c6f1d"))
        p.setBrush(QBrush(face))
        p.drawEllipse(QRectF(cx - rx + 1.5, cy - r + 1.5, 2 * rx - 3, 2 * r - 3))

        if squash < 0.2:
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(255, 235, 160, 128), 1))
            p.drawEllipse(QRectF(cx - rx, cy - r, 2 * rx, 2 * r))
            return

        p.save()
        p.translate(cx, cy)
        p.scale(squash, 1.0)

        # Raised rim: dark groove under the bead line, light ring above it.
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(74, 49, 7, 140), 2.6))
        p.drawEllipse(QRectF(-r + 2, -r + 2, 2 * r - 4, 2 * r - 4))
        p.setPen(QPen(QColor(255, 242, 190, 90), 1.4))
        p.drawEllipse(QRectF(-r + 4.6, -r + 4.6, 2 * r - 9.2, 2 * r - 9.2))

        # Beaded rim: 48 beads, each with a lit edge.
        br = r - 7
        p.setPen(QPen(QColor("#7d5a14"), 0.8))
        p.setBrush(QColor("#ffe9a8"))
        for i in range(48):
            a = math.tau * i / 48
            p.drawEllipse(QPointF(math.cos(a) * br, math.sin(a) * br), 1.15, 1.15)

        # Recessed legend band the lettering sits in.
        p.setPen(QPen(QColor(74, 49, 7, 76), 12))
        p.drawEllipse(QRectF(-r * 0.78, -r * 0.78, r * 1.56, r * 1.56))
        p.setPen(QPen(QColor(255, 238, 175, 40), 1))
        p.drawEllipse(QRectF(-r * 0.72, -r * 0.72, r * 1.44, r * 1.44))

        # The mark, embossed. No legend: the faces speak for themselves.
        p.save()
        p.translate(0, -1.0)
        paint_face(p, HEADS if cos >= 0 else TAILS, r * 0.6, relief="#d9a93a")
        p.restore()

        # Specular crescent, top-left, where the light source sits.
        p.setPen(QPen(QColor(255, 255, 244, 128), 3, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(-r + 3, -r + 3, 2 * r - 6, 2 * r - 6), 196 * 16, 44 * 16)
        p.setPen(QPen(QColor(255, 255, 244, 56), 1.6, Qt.SolidLine, Qt.RoundCap))
        p.drawArc(QRectF(-r + 8, -r + 8, 2 * r - 16, 2 * r - 16), 206 * 16, 30 * 16)

        # Face vignette: warms the edge, focuses the mark.
        vign = QRadialGradient(0.0, 0.0, r - 2)
        vign.setColorAt(0.72, QColor(58, 37, 3, 0))
        vign.setColorAt(1.0, QColor(58, 37, 3, 97))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(vign))
        p.drawEllipse(QRectF(-r + 2, -r + 2, 2 * r - 4, 2 * r - 4))
        p.restore()


# ── pitch: both ends + the wind ──────────────────────────────────────────
# World Rugby Law 1 dimensions, metres. Length runs left→right (try line to
# try line, plus an in-goal each side), width runs near touchline → far.
FIELD_LEN, IN_GOAL, FIELD_W = 100.0, 10.0, 70.0
TOTAL_LEN = FIELD_LEN + 2 * IN_GOAL
POST_GAP, CROSSBAR_H, POST_H, PAD_H = 5.6, 3.0, 16.0, 1.8


KICK = "kick"           # the halfway option: elect to kick off


class PitchWidget(QWidget):
    """The pitch to scale in broadcast perspective (camera behind the near
    touchline): mow stripes that lose saturation and gain haze with depth,
    every Law 1 marking drawn over a soft glow, posts that catch the light
    on both try lines, and the wind: a badge with its strength (a ten-step
    gauge) and, when it blows, an arrow on the grass sized by it.

    It is also where the toss is decided, in one click: offer() makes the
    ends and/or halfway clickable (and steppable with Left/Right). The
    hovered option lights up in the picker's colour and the crests show
    what it means — who takes which end, who kicks off from halfway.
    picked(option) fires with LEFT, RIGHT or KICK. Once decided,
    set_result() keeps the crests on their ends and the kicker's on
    halfway.

    The wind is drawn fixed to the pitch, blowing as for home attacking
    right; toss_for_match turns it round when home takes the other end, so
    the end picked here really is with or against it."""

    DEPTH = 0.55        # how much the far touchline shrinks (0 = flat plan)
    picked = pyqtSignal(str)

    def __init__(self, wind_power=None, wind_deg=0.0, parent=None):
        super().__init__(parent)
        self.setFixedSize(660, 270)
        self.setMouseTracking(True)
        self.wind_power = wind_power        # None = stock random, 0 = calm
        self.wind_deg = wind_deg or 0.0
        self.crests = {}        # {side: QPixmap}
        self.names = {}         # {side: name}
        self.ends = {}          # {LEFT: side, RIGHT: side} once decided
        self.kicker = None      # the side kicking off, once known
        self.options = []       # clickable now: LEFT / KICK / RIGHT
        self.picker = None      # the side choosing
        self.hover = None

    # ── state ────────────────────────────────────────────────────────────
    def set_teams(self, names, crests):
        self.names, self.crests = dict(names), dict(crests or {})
        self.update()

    def offer(self, options, picker, kicker=None):
        """Make `options` clickable for `picker`; `kicker` when already
        known (they elected to kick off: only the end is left to pick)."""
        self.options = [o for o in (LEFT, KICK, RIGHT) if o in options]
        self.picker, self.kicker, self.hover = picker, kicker, None
        self.update()

    def clear_offer(self):
        self.options, self.hover = [], None
        self.setCursor(Qt.ArrowCursor)
        self.update()

    def set_result(self, ends, kicker):
        self.clear_offer()
        self.ends, self.kicker = dict(ends), kicker
        self.update()

    def step(self, delta):
        """Left/Right on a pad or keyboard: the next option along."""
        if not self.options:
            return
        if self.hover not in self.options:
            self.hover = self.options[0 if delta > 0 else -1]
        else:
            i = self.options.index(self.hover) + delta
            self.hover = self.options[max(0, min(len(self.options) - 1, i))]
        self.update()

    def pick(self, option=None):
        option = option or self.hover
        if option in self.options:
            self.clear_offer()
            self.picked.emit(option)

    def _shown(self):
        """(ends, kicker) to draw: the hovered option's outcome, else what
        is decided."""
        if self.hover is None or self.picker is None:
            return self.ends, self.kicker
        rival = "away" if self.picker == "home" else "home"
        if self.hover == KICK:
            return {}, self.picker
        other_end = RIGHT if self.hover == LEFT else LEFT
        return {self.hover: self.picker, other_end: rival}, self.kicker or rival

    # ── hit areas (pitch metres) ─────────────────────────────────────────
    def _area(self, option):
        L, G = TOTAL_LEN, IN_GOAL
        if option == LEFT:
            return self._poly(-1, G + 22)
        if option == RIGHT:
            return self._poly(L - G - 22, L + 1)
        return self._poly(L / 2 - 8, L / 2 + 8)

    def _option_at(self, pos):
        for option in self.options:
            if self._area(option).containsPoint(QPointF(pos), Qt.OddEvenFill):
                return option
        return None

    def mouseMoveEvent(self, event):
        hover = self._option_at(event.pos())
        if hover != self.hover and (hover or self.options):
            self.hover = hover
            self.update()
        self.setCursor(Qt.PointingHandCursor if hover else Qt.ArrowCursor)

    def leaveEvent(self, event):
        if self.hover is not None:
            self.hover = None
            self.update()

    def mousePressEvent(self, event):
        option = self._option_at(event.pos())
        if option:
            self.pick(option)
        event.accept()

    # pitch metres -> widget pixels (a homography: straight lines stay straight)
    def _scale(self, y):
        return 1.0 / (1.0 + self.DEPTH * y / FIELD_W)

    def _pt(self, x, y):
        near_w = self.width() - 8
        top, bottom = 40.0, self.height() - 30.0
        t = y / FIELD_W
        k = self.DEPTH
        sy = bottom - (bottom - top) * t * (1 + k) / (1 + k * t)
        s = self._scale(y)
        return QPointF(self.width() / 2 + (x - TOTAL_LEN / 2) / TOTAL_LEN * near_w * s, sy)

    def _poly(self, x0, x1, y0=0.0, y1=FIELD_W):
        return QPolygonF([self._pt(x0, y0), self._pt(x1, y0), self._pt(x1, y1), self._pt(x0, y1)])

    def _line(self, p, x0, y0, x1, y1):
        p.drawLine(self._pt(x0, y0), self._pt(x1, y1))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setPen(Qt.NoPen)
        L, G = TOTAL_LEN, IN_GOAL
        ends, kicker = self._shown()

        # Turf: base, then 10 m mow stripes in three depth bands that lose
        # saturation toward the camera horizon — the aerial haze pass below
        # finishes the job.
        p.setBrush(QColor("#155a22"))
        p.drawPolygon(self._poly(-2, L + 2, -2, FIELD_W + 2))
        bands = ((0.0, 24.0, 1.0), (24.0, 47.0, 0.93), (47.0, FIELD_W, 0.80))
        for i in range(10):
            col = _GRASS_A if i % 2 else _GRASS_B
            for y0, y1, alpha in bands:
                p.setOpacity(alpha)
                p.setBrush(QColor(*col))
                p.drawPolygon(self._poly(G + i * 10, G + (i + 1) * 10, y0, y1))
        p.setOpacity(1.0)

        # In-goals: darker turf, tinted by depth band for the team taking the end.
        for end, x0 in ((LEFT, 0), (RIGHT, L - G)):
            p.setBrush(_IN_GOAL_GRASS)
            p.drawPolygon(self._poly(x0, x0 + G))
            if end in ends:
                tint = QColor(_TINT[ends[end]])
                for y0, y1, alpha in ((0.0, 24.0, 107), (24.0, 47.0, 87), (47.0, FIELD_W, 66)):
                    t = QColor(tint)
                    t.setAlpha(alpha)
                    p.setBrush(t)
                    p.drawPolygon(self._poly(x0, x0 + G, y0, y1))

        # Atmospheric haze over the far half of the pitch.
        p.setBrush(QColor(_HAZE.red(), _HAZE.green(), _HAZE.blue(), 26))
        p.drawPolygon(self._poly(-2, L + 2, 40, FIELD_W + 2))
        p.setBrush(QColor(_HAZE.red(), _HAZE.green(), _HAZE.blue(), 26))
        p.drawPolygon(self._poly(-2, L + 2, 54, FIELD_W + 2))

        self._paint_options(p)

        # Markings: a soft glow under every solid line, then the line itself.
        p.setBrush(Qt.NoBrush)
        glow_pen = QPen(_LINE_GLOW, 3, Qt.SolidLine, Qt.RoundCap)
        ink_pen = QPen(_LINE_WHITE, 1.3, Qt.SolidLine, Qt.RoundCap)

        def mark(x0, y0, x1, y1):
            p.setPen(glow_pen)
            self._line(p, x0, y0, x1, y1)
            p.setPen(ink_pen)
            self._line(p, x0, y0, x1, y1)

        for pts in ((0, 0, L, 0), (0, FIELD_W, L, FIELD_W)):   # touchlines
            mark(*pts)
        for x in (G, L - G, G + 22, L - G - 22, L / 2):        # try lines, 22s, halfway
            mark(x, 0, x, FIELD_W)

        dash = QPen(_LINE_WHITE, 1.0, Qt.CustomDashLine)
        dash.setDashPattern([4, 4])
        p.setPen(dash)                                          # 10 m and 5 m lines
        for x in (L / 2 - 10, L / 2 + 10, G + 5, L - G - 5):
            self._line(p, x, 0, x, FIELD_W)

        p.setPen(QPen(QColor(255, 255, 255, 210), 1.0))        # 5/15 m hashes
        for y in (5, 15, FIELD_W - 15, FIELD_W - 5):
            for x in (G + 5, G + 22, L / 2 - 10, L / 2, L / 2 + 10, L - G - 22, L - G - 5):
                self._line(p, x - 1, y, x + 1, y)
        for y in (5, FIELD_W - 5):
            for x in (G + 5, L - G - 5):
                self._line(p, x, y - 1, x, y + 1)

        self._paint_wind_arrow(p)
        for x in (G, L - G):
            self._paint_posts(p, x)
        self._paint_crests(p, ends, kicker)
        self._paint_vignette(p)
        self._paint_wind_badge(p)

    def _paint_options(self, p):
        """The clickable areas: a faint outline each, the hovered one filled
        in the picker's colour with a bright edge."""
        if not self.options:
            return
        tint = QColor(_TINT.get(self.picker, FG_PRIMARY))
        for option in self.options:
            area = self._area(option)
            if option == self.hover:
                fill = QColor(tint)
                fill.setAlpha(70)
                p.setBrush(fill)
                p.setPen(QPen(tint, 2.4))
            else:
                p.setBrush(QColor(255, 255, 255, 14))
                edge = QPen(QColor(255, 255, 255, 110), 1.2, Qt.CustomDashLine)
                edge.setDashPattern([3, 3])
                p.setPen(edge)
            p.drawPolygon(area)
            caption = {LEFT: "THIS END", RIGHT: "THIS END", KICK: "KICK OFF"}[option]
            x = {LEFT: (IN_GOAL + 22) / 2, RIGHT: TOTAL_LEN - (IN_GOAL + 22) / 2, KICK: TOTAL_LEN / 2}[option]
            at = self._pt(x, 0)
            self._pill(p, QRectF(at.x() - 42, at.y() + 6, 84, 18), caption,
                       tint if option == self.hover else QColor(FG_PRIMARY),
                       tint if option == self.hover else QColor(255, 255, 255, 60))

    def _paint_crests(self, p, ends, kicker):
        """A crest on each end taken, the kicker's on halfway with a ball."""
        mid = FIELD_W * 0.38            # nearer half: the wind arrow has the far one
        for end, x in ((LEFT, IN_GOAL / 2 + 5), (RIGHT, TOTAL_LEN - IN_GOAL / 2 - 5)):
            if end in ends:
                self._crest(p, ends[end], self._pt(x, mid), 54)
        if kicker:
            at = self._pt(TOTAL_LEN / 2, mid)
            self._crest(p, kicker, at, 50)
            ball = QRectF(at.x() + 20, at.y() + 10, 16, 11)
            p.save()
            p.translate(ball.center())
            p.rotate(-20)
            p.translate(-ball.center())
            p.setPen(QPen(QColor(60, 40, 20), 1))
            p.setBrush(QColor("#f1e7d0"))
            p.drawEllipse(ball)
            p.restore()

    def _crest(self, p, side, at, size):
        """The team's crest on a dark disc ringed in its colour (a coloured
        disc with its initial when there is no crest)."""
        ring = QColor(_TINT[side])
        r = size / 2
        p.setPen(QPen(ring, 2))
        p.setBrush(QColor(8, 14, 20, 200))
        p.drawEllipse(at, r, r)
        pix = self.crests.get(side)
        if pix is not None and not pix.isNull():
            inner = int(size * 0.74)
            p.drawPixmap(QRectF(at.x() - inner / 2, at.y() - inner / 2, inner, inner), pix,
                         QRectF(pix.rect()))
        else:
            p.setPen(ring)
            p.setFont(QFont(FONT_DISPLAY, int(size * 0.32), QFont.Bold))
            p.drawText(QRectF(at.x() - r, at.y() - r, size, size), Qt.AlignCenter,
                       (self.names.get(side) or side)[:1].upper())

    def _paint_posts(self, p, x):
        """Uprights rise straight up the screen from the try line, sized by
        their depth. A blurred grass shadow, a cool glow, gold pads and a
        bright white rail — posts that read as floodlit steel."""
        mid = FIELD_W / 2
        px_per_m = (self.width() - 8) / TOTAL_LEN
        tops = []
        for y in (mid - POST_GAP / 2, mid + POST_GAP / 2):
            base = self._pt(x, y)
            m = px_per_m * self._scale(y)
            tops.append((base, POST_H * m, CROSSBAR_H * m, PAD_H * m))
        p.setPen(QPen(QColor(0, 0, 0, 100), 2.6, Qt.SolidLine, Qt.RoundCap))
        for base, up, _, _ in tops:                           # shadow on the grass
            p.drawLine(base, QPointF(base.x() + up * 0.35, base.y() + up * 0.12))
        glow = QPainterPath()
        for base, up, _, pad in tops:
            glow.moveTo(base.x(), base.y() - pad)
            glow.lineTo(base.x(), base.y() - up)
        (b0, _, bar0, _), (b1, _, bar1, _) = tops
        glow.moveTo(b0.x(), b0.y() - bar0)
        glow.lineTo(b1.x(), b1.y() - bar1)
        p.setPen(QPen(_POST_GLOW, 4, Qt.SolidLine, Qt.RoundCap))  # cool bloom
        p.drawPath(glow)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT))                               # post pads
        for base, _, _, pad in tops:
            pad_r = QRectF(base.x() - 2.4, base.y() - pad, 4.8, pad + 1)
            p.drawRoundedRect(pad_r, 1.2, 1.2)
        p.setPen(QPen(_POST_INK, 1.8, Qt.SolidLine, Qt.RoundCap))  # the rail
        for base, up, _, pad in tops:
            p.drawLine(QPointF(base.x(), base.y() - pad), QPointF(base.x(), base.y() - up))
        p.setPen(QPen(_POST_INK, 2.2, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(QPointF(b0.x(), b0.y() - bar0), QPointF(b1.x(), b1.y() - bar1))

    def _paint_wind_arrow(self, p):
        """The wind's direction as an arrow on the grass, longer and thicker
        the stronger it blows. None when calm or left to the game."""
        if not self.wind_power:
            return
        power = min(10, self.wind_power)
        rad = math.radians(self.wind_deg % 360)
        dx, dy = math.cos(rad), -math.sin(rad)      # toward home's attack end (right) / home's right
        length = 16 + power * 3.2
        width = 2.5 + power * 0.55
        cx, cy = TOTAL_LEN / 2, FIELD_W * 0.78
        tail = (cx - dx * length / 2, cy - dy * length / 2)
        tip = (cx + dx * length / 2, cy + dy * length / 2)
        nx, ny = -dy, dx
        head = 6.0 + power * 0.6
        back = (tip[0] - dx * head, tip[1] - dy * head)
        ink = _WIND_INK
        streak = QPen(QColor(143, 211, 244, 90), 2, Qt.SolidLine, Qt.RoundCap)
        p.setPen(streak)
        for k in range(min(3, 1 + power // 3)):                 # motion streaks, more in a gale
            off = (k - 1) * 3.5
            p.drawLine(self._pt(tail[0] - dx * (5 + 3 * k) + nx * off, tail[1] - dy * (5 + 3 * k) + ny * off),
                       self._pt(tail[0] - dx * 1.5 + nx * off, tail[1] - dy * 1.5 + ny * off))
        p.setPen(QPen(QColor(0, 0, 0, 90), width + 3, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(self._pt(*tail), self._pt(*back))
        p.setPen(QPen(ink, width, Qt.SolidLine, Qt.RoundCap))
        p.drawLine(self._pt(*tail), self._pt(*back))
        p.setPen(Qt.NoPen)
        p.setBrush(ink)
        spread = head * 0.75
        p.drawPolygon(QPolygonF([self._pt(*tip),
                                 self._pt(back[0] + nx * spread, back[1] + ny * spread),
                                 self._pt(back[0] + dx * 1.5, back[1] + dy * 1.5),
                                 self._pt(back[0] - nx * spread, back[1] - ny * spread)]))

    def _paint_wind_badge(self, p):
        """WIND 6 · STRONG GALE and a ten-step gauge, NO WIND when calm,
        RANDOM WIND when the game rolls its own."""
        if not self.wind_power:
            text = "RANDOM WIND" if self.wind_power is None else "NO WIND"
            self._pill(p, QRectF(self.width() / 2 - 60, 4, 120, 26), text,
                       QColor(FG_TERTIARY), QColor(255, 255, 255, 36), size=9)
            return
        power = min(10, self.wind_power)
        text = f"WIND {power} · {WIND_POWER_NAMES.get(power, '').upper()}"
        p.setFont(QFont(FONT_DISPLAY, 9, QFont.Bold))
        text_w = QFontMetrics(p.font()).horizontalAdvance(text)
        gauge_w = 10 * 8
        w = text_w + gauge_w + 40
        rect = QRectF(self.width() / 2 - w / 2, 4, w, 26)
        p.setPen(QPen(QColor(143, 211, 244, 110), 1))
        p.setBrush(QColor(10, 18, 26, 210))
        p.drawRoundedRect(rect, 11, 11)
        p.setPen(_WIND_INK)
        p.drawText(QRectF(rect.left() + 14, rect.top(), text_w + 2, rect.height()), Qt.AlignVCenter, text)
        x0 = rect.right() - 14 - gauge_w
        p.setPen(Qt.NoPen)
        for i in range(10):
            h = 5 + i * 1.0
            bar = QRectF(x0 + i * 8, rect.center().y() + 7 - h, 6, h)
            if i < power:
                p.setBrush(_WIND_INK if i < 4 else QColor(WARN) if i < 7 else QColor(DANGER_LITE))
            else:
                p.setBrush(QColor(255, 255, 255, 34))
            p.drawRect(bar)

    @staticmethod
    def _pill(p, rect, text, ink, border, size=8):
        """A rounded badge: dark glass fill, thin border, centred lettering."""
        p.setPen(QPen(border, 1))
        p.setBrush(QColor(10, 18, 26, 184))
        p.drawRoundedRect(rect, rect.height() / 2, rect.height() / 2)
        p.setPen(ink)
        p.setFont(QFont(FONT_DISPLAY, size, QFont.Bold))
        p.drawText(rect, Qt.AlignCenter, text)

    def _paint_vignette(self, p):
        """Focus the pitch: darker corners, untouched centre."""
        vign = QRadialGradient(self.width() / 2, self.height() / 2, self.width() * 0.62)
        vign.setColorAt(0.55, QColor(0, 0, 0, 0))
        vign.setColorAt(1.0, QColor(0, 0, 0, 78))
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(vign))
        p.drawRect(self.rect())



# ── overlay ──────────────────────────────────────────────────────────────
class CoinTossOverlay(QWidget):
    def __init__(self, screen, names, humans, on_done, on_cancel=None, wind=(None, 0.0), toss=None,
                 crests=None):
        super().__init__(screen)
        self.screen = screen
        self.names = names              # {"home": "...", "away": "..."}
        self.crests = crests or {}      # {"home": QPixmap, "away": QPixmap}
        self.humans = set(humans)       # sides the player controls
        self.on_done = on_done
        self.on_cancel = on_cancel
        self.toss = toss or CoinToss()
        self._wind = wind
        self._buttons = []
        self._closed = False
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._anim = None

        self.setFocusPolicy(Qt.StrongFocus)
        self._build()
        screen.installEventFilter(self)
        self.setGeometry(screen.rect())

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch(1)
        row = QHBoxLayout()
        row.addStretch(1)

        self.card = Card(stripe=ACCENT)
        self.card.setFixedWidth(740)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(30, 18, 30, 22)
        v.setSpacing(8)
        v.addWidget(eyebrow_label("coin toss", color=ACCENT, size=13))

        self.coin = CoinWidget()
        v.addWidget(self.coin, alignment=Qt.AlignHCenter)

        self.title = QLabel()
        self.title.setAlignment(Qt.AlignCenter)
        self.title.setTextFormat(Qt.RichText)
        self.title.setStyleSheet(label_css(20, QFont.Bold, FG_PRIMARY))
        # room for two lines of each: long team names wrap, the card stays put
        self.title.setWordWrap(True)
        self.title.setFixedHeight(QFontMetrics(self.title.font()).lineSpacing() * 2 + 18)
        v.addWidget(self.title)

        self.sub = QLabel()
        self.sub.setAlignment(Qt.AlignCenter)
        self.sub.setTextFormat(Qt.RichText)
        self.sub.setStyleSheet(label_css(11, QFont.Normal, FG_TERTIARY, FONT_BODY))
        self.sub.setWordWrap(True)
        self.sub.setMinimumHeight(38)
        v.addWidget(self.sub)

        v.addSpacing(4)
        self.pitch = PitchWidget(*self._wind)
        self.pitch.set_teams(self.names, self.crests)
        self.pitch.picked.connect(self._on_pick)
        v.addWidget(self.pitch, alignment=Qt.AlignHCenter)
        v.addSpacing(6)

        # Fixed height so the card doesn't jump as buttons come and go.
        holder = QWidget()
        holder.setObjectName("tossButtons")
        holder.setStyleSheet("QWidget#tossButtons { background: transparent; }")
        holder.setFixedHeight(BTN_HEIGHT)
        self.button_row = QHBoxLayout(holder)
        self.button_row.setContentsMargins(0, 0, 0, 0)
        self.button_row.setSpacing(12)
        v.addWidget(holder)

        row.addWidget(self.card)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(1)

    def paintEvent(self, event):
        QPainter(self).fillRect(self.rect(), QColor(0, 0, 0, 175))

    def eventFilter(self, obj, event):
        if obj is self.screen and event.type() == QEvent.Resize:
            self.setGeometry(self.screen.rect())
        return False

    # ── helpers ──────────────────────────────────────────────────────────
    def _team(self, side):
        return f"<span style='color:{_TINT[side]}'>{(self.names.get(side) or side).upper()}</span>"

    def _show(self, title, sub=""):
        self.title.setText(title)
        self.sub.setText(sub)

    def _set_buttons(self, choices):
        """choices: [(label, callback, icon or None)]. An empty list parks
        focus on the overlay itself so keys never reach the screen behind."""
        for b in self._buttons:
            self.screen.focus.unregister(b)
            b.setParent(None)
            b.deleteLater()
        self._buttons = []
        for label, cb, icon in choices:
            b = StyledButton(label, "primary" if len(choices) == 1 else "neutral")
            b.setMinimumHeight(BTN_HEIGHT)
            if icon is not None:
                b.setIcon(icon)
                b.setIconSize(QSize(22, 22))
            b.clicked.connect(cb)
            self.screen.focus.register(b)
            self.button_row.addWidget(b)
            self._buttons.append(b)
        if self._buttons:
            self._buttons[0].setFocus()
        else:
            self.setFocus()

    def _later(self, fn, ms=CPU_BEAT_MS):
        try:
            self._timer.timeout.disconnect()
        except TypeError:
            pass
        self._timer.timeout.connect(fn)
        self._timer.start(ms)

    # ── flow ─────────────────────────────────────────────────────────────
    # As little text as possible: the coin spins on its own, the result is
    # YOU WON / YOU LOST THE TOSS, and after a short beat the other team's
    # choice is announced. The player only gets the choice that is theirs.
    def _you(self):
        """The side the player controls, when exactly one is."""
        return next(iter(self.humans)) if len(self.humans) == 1 else None

    def _verdict(self, text, good):
        return f"<span style='color:{GREEN if good else DANGER_LITE}'>{text}</span>"

    def _side(self, side):
        """YOU for the player's side, else the team's name."""
        return "YOU" if side == self._you() else self._team(side)

    def start(self):
        self.screen.focus.push_scope(self)
        self.show()
        self.raise_()
        self.coin.set_pose(0.0)
        self.toss.call = self.toss.cpu_call()
        self._show("")
        self._set_buttons([])
        self._later(self._spin, CALL_BEAT_MS)

    def _spin(self):
        face = self.toss.flip()
        end_angle = FLIP_TURNS * 360.0 + (0.0 if face == HEADS else 180.0)
        spin = QEasingCurve(QEasingCurve.OutCubic)
        self._anim = QVariantAnimation(self)
        self._anim.setStartValue(0.0)
        self._anim.setEndValue(1.0)
        self._anim.setDuration(FLIP_MS)
        self._anim.valueChanged.connect(lambda t: self.coin.set_pose(
            end_angle * spin.valueForProgress(t), 4.0 * t * (1.0 - t)))
        self._anim.finished.connect(self._on_landed)
        self._anim.start()

    def _on_landed(self):
        if self._closed:
            return
        winner, you = self.toss.winner, self._you()
        if you is not None:
            won = winner == you
            self._show(self._verdict("YOU WON THE TOSS" if won else "YOU LOST THE TOSS", won))
        else:
            self._show(f"{self._team(winner)} WIN THE TOSS")
        self._set_buttons([])
        if winner in self.humans:
            self.sub.setText("Click the end you want, or halfway to kick off")
            self.pitch.offer((LEFT, KICK, RIGHT), winner)
        else:
            self._later(lambda: self._on_decision(self.toss.cpu_decision()))

    def _on_pick(self, option):
        """A click on the pitch: the winner's one-click choice (an end, or
        halfway to kick off), or the end left to pick."""
        if self.toss.decision is None:
            if option == KICK:
                self._on_decision(KICK_OFF)
            else:
                self.toss.decision = CHOOSE_END
                self._on_end(option)
        elif option in (LEFT, RIGHT):
            self._on_end(option)

    def _on_decision(self, decision):
        self.toss.decision = decision
        winner, chooser = self.toss.winner, self.toss.end_chooser
        if winner not in self.humans:
            self._show(f"{self._team(winner)} CHOSE " + ("TO KICK OFF" if decision == KICK_OFF
                                                         else "THEIR END"))
        elif decision == KICK_OFF:
            self._show(f"{self._side(winner)} KICK OFF")
        else:
            self._show("CHOOSE YOUR END" if chooser == self._you() else f"{self._team(chooser)} CHOOSE AN END")
        self._set_buttons([])
        if chooser in self.humans:
            self.sub.setText("Click the end you want")
            self.pitch.offer((LEFT, RIGHT), chooser, kicker=self.toss.kicker)
        else:
            self.pitch.clear_offer()
            self._later(lambda: self._on_end(self.toss.cpu_end()))

    def _on_end(self, end):
        self.toss.end = end
        result = self.toss.resolved()
        chooser, kicker = self.toss.end_chooser, result["kick_off"]
        home_end = result["home_team_side"]
        away_end = RIGHT if home_end == LEFT else LEFT
        self.pitch.set_result({home_end: "home", away_end: "away"}, kicker)
        if chooser not in self.humans:
            # the other team's pick, and who kicks off when that is news
            # (the player chose to kick off: no need to say it again)
            news = self.toss.winner not in self.humans
            self._show(f"{self._team(chooser)} CHOSE THE {end.upper()} END",
                       f"{self._side(kicker)} KICK OFF" if news else "")
        else:
            self._show(f"{self._side(kicker)} KICK OFF")
        self._set_buttons([("KICK OFF", lambda: self._finish(result), None)])

    def _finish(self, result):
        self._close()
        self.on_done(result)

    def cancel(self):
        self._close()
        if self.on_cancel:
            self.on_cancel()

    def _close(self):
        if self._closed:
            return
        self._closed = True
        self._timer.stop()
        if self._anim is not None:
            self._anim.stop()
        self.screen.removeEventFilter(self)
        self.screen.focus.unregister_tree(self)
        self.screen.focus.pop_scope(self)
        self.hide()
        self.deleteLater()
        self.screen.setFocus()

    # ── input ────────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if self.pitch.options and action in (Action.NAV_LEFT, Action.NAV_RIGHT):
            self.pitch.step(-1 if action == Action.NAV_LEFT else 1)
        elif self.pitch.options and action == Action.CONFIRM:
            self.pitch.pick()
        elif action in (Action.NAV_UP, Action.NAV_DOWN, Action.NAV_LEFT, Action.NAV_RIGHT):
            self.screen.focus.move(action)
        elif action == Action.CONFIRM:
            w = QApplication.focusWidget()
            if isinstance(w, QAbstractButton) and w in self._buttons:
                w.click()
        elif action == Action.BACK:
            self.cancel()
        # Everything else stops here too: nothing reaches the screen behind.
        event.accept()

    def mousePressEvent(self, event):
        event.accept()


def run_coin_toss(screen, names, humans, on_done, on_cancel=None, wind=(None, 0.0), crests=None):
    overlay = CoinTossOverlay(screen, names, humans, on_done, on_cancel, wind, crests=crests)
    overlay.start()
    return overlay


def toss_for_match(screen, ds, cfg, on_done, on_cancel=None):
    """run_coin_toss for a MatchConfig: team names, the sides the player
    controls and the wind come from `cfg`; on_done receives a copy of `cfg`
    carrying the toss's kick_off / home_team_side (the original is left as
    it was, so the screen's own rows keep their values for when the toss is
    turned off).

    The wind bearing is relative to home's attack (app.game_data); the
    pitch shows it as for home attacking right (home_team_side left). When
    the toss gives home the other end, the bearing is turned round so the
    wind keeps blowing the way it was shown: the end picked is really with
    or against it."""
    from screens.tournament.common import team_crest

    def name(slot):
        info = slot.info(ds)
        return info.get("name") or slot.team_id or ""

    def done(result):
        out = replace(cfg, **result)
        if out.wind_power and result["home_team_side"] != LEFT:
            out.wind_dir_deg = (cfg.wind_dir_deg + 180.0) % 360.0
        on_done(out)

    names = {"home": name(cfg.home), "away": name(cfg.away)}
    crests = {side: team_crest(ds, slot.team_id, slot.season, 64, names[side], slot.variant)
              for side, slot in (("home", cfg.home), ("away", cfg.away))}
    humans = {c.get("zone") for c in cfg.controllers.values()} & {"home", "away"}
    return run_coin_toss(screen, names, humans, done, on_cancel,
                         wind=(cfg.wind_power, cfg.wind_dir_deg), crests=crests)
