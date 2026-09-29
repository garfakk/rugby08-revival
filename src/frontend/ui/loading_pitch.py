"""
ui/loading_pitch.py — Bouncing-ball loading bar
================================================
A progress widget shaped like a floodlit rugby pitch: the ball bounces from
one try line to the other, its position tracking the loading progress. It
hops high and spins fast while progress flows, and settles into tired little
hops in place when nothing is moving — so the animation itself tells the user
whether the machine is still working.

Drop-in for QProgressBar as far as the loading screen is concerned:
`setRange`, `setValue`, `value`, `setTextVisible` all behave the same way.
When the value reaches the maximum the ball is kicked through the posts and
`celebration_finished` fires (see `CELEBRATION_MS`).
"""
import math
import random
import time

from PyQt5.QtCore import Qt, QTimer, QRectF, QPointF, pyqtSignal
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QBrush, QLinearGradient, QRadialGradient,
    QPainterPath, QFont,
)
from PyQt5.QtWidgets import QWidget

from ui.theme import ACCENT, ACCENT_LITE, FG_PRIMARY, FG_SECONDARY, FONT_DISPLAY

# ── Tuning ─────────────────────────────────────────────────────────────────────
FRAME_MS        = 33            # ~30 fps, cheap enough next to a booting game
BOUNCE_MS       = 620           # one hop at full speed
BOUNCE_MS_IDLE  = 900           # one hop when progress has stalled
HOP_H           = 0.62          # hop height as a fraction of the sky area
HOP_H_IDLE      = 0.22          # tired little hops when nothing is happening
SQUASH_WINDOW   = 0.14          # fraction of the hop spent squashed on impact
TRAIL_LEN       = 14
DUST_PER_BOUNCE = 6
CELEBRATION_MS  = 1150           # kick through the posts + TRY! flash

QUIP_MS = 3200
QUIPS = [
    "Inflating the ball…",
    "Chalking the try line…",
    "Waking up the front row…",
    "Teaching the props to jog…",
    "Polishing the kicking tee…",
    "Bribing the touch judge…",
    "Counting the ears in the scrum…",
    "Finding the physio's cold spray…",
    "Ironing the referee's whistle…",
    "Explaining the offside line, again…",
    "Filling the water bottles…",
    "Mowing the stripes…",
    "Checking studs for length…",
    "Convincing the winger to tackle…",
]

# Pitch palette (kept local: this widget is the only thing that is green)
GRASS_DARK   = QColor("#123018")
GRASS_LIGHT  = QColor("#1a4523")
GRASS_STRIPE = QColor(255, 255, 255, 10)
LINE_COL     = QColor(226, 236, 226, 110)
POST_COL     = QColor("#e8e4d8")
BALL_DARK    = QColor("#5d2f11")
BALL_MID     = QColor("#8a4b1e")
BALL_LITE    = QColor("#b8763a")


class PitchProgressBar(QWidget):
    """Progress bar drawn as a rugby pitch with a bouncing ball."""

    celebration_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumHeight(150)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

        self._min = 0
        self._max = 1000
        self._value = 0

        now = time.time()
        self._t0 = now
        self._frac = 0.0            # progress 0..1
        self._frac_prev = 0.0
        self._speed = 0.0           # smoothed d(frac)/dt, drives the animation
        self._last_tick = now
        self._bounce_phase = 0.0    # 0..1 within the current hop
        self._spin = 0.0            # ball rotation, degrees
        self._trail: list[tuple[float, float]] = []
        self._dust: list[dict] = []
        self._sparks: list[dict] = []

        self._quip = random.randrange(len(QUIPS))
        self._quip_at = now

        self._crowd = [(random.random(), random.random(), random.random())
                       for _ in range(220)]

        self._celebrating = False
        self._celebrate_t0 = 0.0
        self._try_flash = 0.0

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_MS)

    # ── QProgressBar-compatible API ────────────────────────────────────────────

    def setRange(self, minimum: int, maximum: int):
        self._min, self._max = minimum, max(maximum, minimum + 1)

    def setValue(self, value: int):
        self._value = max(self._min, min(self._max, int(value)))
        self._frac = (self._value - self._min) / (self._max - self._min)

    def value(self) -> int:
        return self._value

    def setTextVisible(self, visible: bool):   # accepted, always drawn
        pass

    # ── Animation ──────────────────────────────────────────────────────────────

    def celebrate(self):
        """Kick the ball through the posts. Emits celebration_finished when the
        flash is over (also emitted immediately if already celebrating)."""
        if self._celebrating:
            return
        self._celebrating = True
        self._celebrate_t0 = time.time()
        for _ in range(28):
            angle = random.uniform(-2.6, -0.5)
            speed = random.uniform(90, 260)
            self._sparks.append({
                "x": 0.0, "y": 0.0,           # filled in on the first frame
                "vx": math.cos(angle) * speed,
                "vy": math.sin(angle) * speed,
                "life": random.uniform(0.5, 1.0),
                "born": False,
            })
        QTimer.singleShot(CELEBRATION_MS, self.celebration_finished.emit)

    def _tick(self):
        now = time.time()
        dt = max(1e-3, min(0.2, now - self._last_tick))
        self._last_tick = now

        # Instantaneous speed of the progress itself, heavily smoothed: this is
        # what makes the ball look lively when work is flowing and sleepy when
        # it is not.
        raw_speed = (self._frac - self._frac_prev) / dt
        self._frac_prev = self._frac
        self._speed += (raw_speed - self._speed) * 0.12
        drive = max(0.0, min(1.0, self._speed / 0.06))   # 6 %/s ≈ full pelt

        if not self._celebrating:
            period = (BOUNCE_MS_IDLE + (BOUNCE_MS - BOUNCE_MS_IDLE) * drive) / 1000.0
            prev_phase = self._bounce_phase
            self._bounce_phase = (self._bounce_phase + dt / period) % 1.0
            if self._bounce_phase < prev_phase:          # landed
                self._spawn_dust()
            self._spin += (40 + 620 * drive) * dt

        if now - self._quip_at > QUIP_MS / 1000.0:
            self._quip_at = now
            self._quip = (self._quip + 1 + random.randrange(len(QUIPS) - 1)) % len(QUIPS)

        self._step_particles(dt)
        self.update()

    def _spawn_dust(self):
        w, h = self.width(), self.height()
        if w <= 0:
            return
        bx, _ = self._ball_pos(w, h)
        ground = self._ground_y(h)
        for _ in range(DUST_PER_BOUNCE):
            self._dust.append({
                "x": bx + random.uniform(-6, 6),
                "y": ground + random.uniform(-2, 2),
                "vx": random.uniform(-34, 18),
                "vy": random.uniform(-26, -6),
                "life": random.uniform(0.25, 0.55),
                "age": 0.0,
                "r": random.uniform(1.2, 3.0),
            })

    def _step_particles(self, dt: float):
        for p in self._dust:
            p["age"] += dt
            p["x"] += p["vx"] * dt
            p["y"] += p["vy"] * dt
            p["vy"] += 90 * dt
        self._dust = [p for p in self._dust if p["age"] < p["life"]]

        for s in self._sparks:
            if not s["born"]:
                continue
            s["life"] -= dt
            s["x"] += s["vx"] * dt
            s["y"] += s["vy"] * dt
            s["vy"] += 340 * dt
        self._sparks = [s for s in self._sparks if s["life"] > 0]

    # ── Geometry helpers ───────────────────────────────────────────────────────

    def _ground_y(self, h: int) -> float:
        return h - max(38.0, h * 0.26)

    def _lane(self, w: int):
        """(start x, end x) of the ball's run, leaving room for the posts."""
        return 30.0, max(60.0, w - 78.0)

    def _hop_height(self, h: int) -> float:
        drive = max(0.0, min(1.0, self._speed / 0.06))
        sky = self._ground_y(h) - 34.0
        return sky * (HOP_H_IDLE + (HOP_H - HOP_H_IDLE) * drive)

    def _ball_pos(self, w: int, h: int):
        x0, x1 = self._lane(w)
        ground = self._ground_y(h)

        if self._celebrating:
            t = min(1.0, (time.time() - self._celebrate_t0) / (CELEBRATION_MS / 1000.0))
            # Conversion kick: a long arc that clears the crossbar between the
            # posts and hangs there rather than shooting off the widget.
            start_x = x0 + self._frac * (x1 - x0)
            target_x = x1 + 26
            bx = start_x + (target_x - start_x) * min(1.0, t * 1.35)
            arc = math.sin(min(1.0, t * 1.15) * math.pi * 0.78)
            by = ground - arc * (ground - 22.0)
            return bx, by

        bx = x0 + self._frac * (x1 - x0)
        by = ground - math.sin(self._bounce_phase * math.pi) * self._hop_height(h)
        return bx, by

    # ── Painting ───────────────────────────────────────────────────────────────

    def paintEvent(self, _event):
        w, h = self.width(), self.height()
        if w <= 2 or h <= 2:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, True)

        self._paint_sky(p, w, h)
        self._paint_pitch(p, w, h)
        self._paint_posts(p, w, h)
        self._paint_trail(p, w, h)
        self._paint_dust(p)
        self._paint_ball(p, w, h)
        self._paint_sparks(p)
        self._paint_text(p, w, h)
        p.end()

    def _paint_sky(self, p: QPainter, w: int, h: int):
        ground = self._ground_y(h)
        sky = QLinearGradient(0, 0, 0, ground)
        sky.setColorAt(0.0, QColor("#06060b"))
        sky.setColorAt(0.62, QColor("#131822"))
        sky.setColorAt(1.0, QColor("#243026"))
        p.fillRect(QRectF(0, 0, w, ground), QBrush(sky))

        # Floodlight cones from the top corners
        for cx in (w * 0.18, w * 0.82):
            glow = QRadialGradient(QPointF(cx, -20), max(w, h) * 0.75)
            glow.setColorAt(0.0, QColor(255, 244, 210, 46))
            glow.setColorAt(1.0, QColor(255, 244, 210, 0))
            p.fillRect(QRectF(0, 0, w, ground), QBrush(glow))

        # Crowd: a band of dots that twinkles, denser as the load progresses
        band_top, band_h = ground * 0.30, ground * 0.34
        t = time.time()
        for i, (fx, fy, seed) in enumerate(self._crowd):
            if fx > 0.25 + 0.75 * self._frac:      # stands fill up as we load
                continue
            twinkle = 0.55 + 0.45 * math.sin(t * (1.2 + seed) + i)
            col = QColor(ACCENT_LITE if seed > 0.86 else "#6a6a7a")
            col.setAlpha(int(70 * twinkle) + 25)
            p.fillRect(QRectF(fx * w, band_top + fy * band_h, 2.0, 2.0), col)

    def _paint_pitch(self, p: QPainter, w: int, h: int):
        ground = self._ground_y(h)
        pitch = QRectF(0, ground, w, h - ground)
        grass = QLinearGradient(0, ground, 0, h)
        grass.setColorAt(0.0, GRASS_LIGHT)
        grass.setColorAt(1.0, GRASS_DARK)
        p.fillRect(pitch, QBrush(grass))

        # Mown stripes
        stripe_w = max(14.0, w / 18.0)
        x = 0.0
        while x < w:
            p.fillRect(QRectF(x, ground, stripe_w, h - ground), GRASS_STRIPE)
            x += stripe_w * 2

        # Pitch markings, drawn up into the sky area like a side-on view
        x0, x1 = self._lane(w)
        p.setPen(QPen(LINE_COL, 1))
        for frac in (0.0, 0.25, 0.5, 0.75, 1.0):
            lx = x0 + (x1 - x0) * frac
            solid = frac in (0.0, 0.5, 1.0)
            pen = QPen(LINE_COL, 2 if solid else 1)
            if not solid:
                pen.setStyle(Qt.DashLine)
            p.setPen(pen)
            p.drawLine(QPointF(lx, ground - 8), QPointF(lx, h - 4))

        # The ground already covered, tinted like fresh chalk
        p.fillRect(QRectF(x0, ground, max(0.0, self._frac * (x1 - x0)), 3.0),
                   QColor(ACCENT))

    def _paint_posts(self, p: QPainter, w: int, h: int):
        ground = self._ground_y(h)
        _, x1 = self._lane(w)
        px = x1 + 26
        top = 34.0
        bar = ground - (ground - top) * 0.42
        pen = QPen(POST_COL, 3)
        pen.setCapStyle(Qt.RoundCap)
        p.setPen(pen)
        p.drawLine(QPointF(px - 16, ground), QPointF(px - 16, top))
        p.drawLine(QPointF(px + 16, ground), QPointF(px + 16, top))
        p.drawLine(QPointF(px - 16, bar), QPointF(px + 16, bar))

    def _paint_trail(self, p: QPainter, w: int, h: int):
        bx, by = self._ball_pos(w, h)
        self._trail.append((bx, by))
        if len(self._trail) > TRAIL_LEN:
            del self._trail[:-TRAIL_LEN]
        for i, (tx, ty) in enumerate(self._trail[:-1]):
            alpha = int(70 * (i + 1) / len(self._trail))
            col = QColor(ACCENT_LITE)
            col.setAlpha(alpha)
            p.setBrush(QBrush(col))
            p.setPen(Qt.NoPen)
            r = 1.0 + 2.0 * (i + 1) / len(self._trail)
            p.drawEllipse(QPointF(tx, ty), r, r)

    def _paint_dust(self, p: QPainter):
        p.setPen(Qt.NoPen)
        for d in self._dust:
            fade = 1.0 - d["age"] / d["life"]
            col = QColor(210, 220, 200, int(110 * fade))
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(d["x"], d["y"]), d["r"], d["r"] * 0.7)

    def _paint_ball(self, p: QPainter, w: int, h: int):
        bx, by = self._ball_pos(w, h)
        ground = self._ground_y(h)

        # Shadow: tight and dark on the ground, soft when the ball is high
        height = max(0.0, ground - by)
        span = max(1.0, self._hop_height(h))
        lift = min(1.0, height / span)
        sw = 16.0 - 6.0 * lift
        p.setPen(Qt.NoPen)
        p.setBrush(QBrush(QColor(0, 0, 0, int(120 * (1.0 - 0.6 * lift)))))
        p.drawEllipse(QPointF(bx, ground + 3), sw + 4, 3.6 - 1.2 * lift)

        # Squash and stretch: flat on impact, stretched at the top of the hop
        if self._celebrating:
            sx, sy = 1.0, 1.0
        elif self._bounce_phase < SQUASH_WINDOW or self._bounce_phase > 1 - SQUASH_WINDOW:
            sx, sy = 1.22, 0.78
        else:
            sx, sy = 0.94, 1.08

        p.save()
        p.translate(bx, by)
        p.rotate(self._spin if not self._celebrating else self._spin + 220)
        p.scale(sx, sy)

        body = QRectF(-19, -12, 38, 24)
        leather = QLinearGradient(0, -9.5, 0, 9.5)
        leather.setColorAt(0.0, BALL_LITE)
        leather.setColorAt(0.55, BALL_MID)
        leather.setColorAt(1.0, BALL_DARK)
        p.setPen(QPen(QColor(40, 20, 8, 200), 1))
        p.setBrush(QBrush(leather))
        p.drawEllipse(body)

        # White bands and lacing
        p.setPen(QPen(QColor(235, 232, 222, 210), 2))
        p.drawArc(QRectF(-17, -11, 10, 22), -70 * 16, 140 * 16)
        p.drawArc(QRectF(7, -11, 10, 22), 110 * 16, 140 * 16)
        p.setPen(QPen(QColor(240, 238, 230, 230), 1.6))
        p.drawLine(QPointF(-6, 0), QPointF(6, 0))
        for lx in (-4.0, 0.0, 4.0):
            p.drawLine(QPointF(lx, -3.4), QPointF(lx, 3.4))
        p.restore()

        # Spark particles are born at the ball on the first celebration frame
        for s in self._sparks:
            if not s["born"]:
                s["x"], s["y"], s["born"] = bx, by, True

    def _paint_sparks(self, p: QPainter):
        p.setPen(Qt.NoPen)
        for s in self._sparks:
            if not s["born"]:
                continue
            col = QColor(ACCENT_LITE)
            col.setAlpha(int(230 * min(1.0, s["life"])))
            p.setBrush(QBrush(col))
            p.drawEllipse(QPointF(s["x"], s["y"]), 2.2, 2.2)

    def _paint_text(self, p: QPainter, w: int, h: int):
        percent = int(round(self._frac * 100))

        # Percentage on the left, quip on the right: the ball's kick lands in
        # the top-right corner and would otherwise sit on top of the number.
        p.setFont(QFont(FONT_DISPLAY, 15, QFont.Bold))
        p.setPen(QColor(ACCENT))
        p.drawText(QRectF(10, 6, 70, 24), Qt.AlignLeft | Qt.AlignVCenter,
                   f"{percent:d}%")

        p.setFont(QFont(FONT_DISPLAY, 9))
        p.setPen(QColor(FG_SECONDARY))
        p.drawText(QRectF(88, 6, w - 110, 24), Qt.AlignRight | Qt.AlignVCenter,
                   QUIPS[self._quip])

        if self._celebrating:
            t = min(1.0, (time.time() - self._celebrate_t0) / (CELEBRATION_MS / 1000.0))
            pop = 1.0 + 0.5 * math.sin(min(1.0, t * 2.2) * math.pi * 0.5)
            p.save()
            p.translate(w * 0.42, h * 0.52)
            p.scale(pop, pop)
            p.setFont(QFont(FONT_DISPLAY, 22, QFont.Bold))
            p.setPen(QColor(255, 255, 255, int(255 * min(1.0, 2.4 * (1.0 - t) + 0.35))))
            p.drawText(QRectF(-120, -20, 240, 40), Qt.AlignCenter, "TRY!")
            p.restore()
