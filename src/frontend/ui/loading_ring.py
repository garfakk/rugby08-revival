"""
ui/loading_ring.py — Circular loading ring
==============================================
The approved loading-screen mockup ("épuré: one element carries the whole
screen — a ring with a number inside it. No pitch, no ball, no crowd — that
motif lives on the main menu, not here.") — see
scratchpad/mockup/gen_mockups.py::loading() for the reference render this
was built to match.

Drop-in for QProgressBar as far as the loading screen is concerned:
`setRange`, `setValue`, `value`, `setTextVisible` all behave the same way,
and `celebrate()` / `celebration_finished` preserve the same hand-off used
to reveal the embedded game window once loading completes.
"""
import math

from PyQt5.QtCore import Qt, QTimer, QRectF, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QRadialGradient, QFont, QPen
from PyQt5.QtWidgets import QWidget

from ui.theme import ACCENT, ACCENT_LITE, GREEN, BORDER_EM, FG_PRIMARY, FG_SECONDARY, GREEN_2
from ui.broadcast import tracked_font

FRAME_MS = 33
CELEBRATION_MS = 500


class CircularLoadingRing(QWidget):
    """A ring with the percentage inside it — the whole loading screen's
    single focal element."""

    celebration_finished = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMinimumSize(200, 200)

        self._min = 0
        self._max = 1000
        self._value = 0
        self._shown_frac = 0.0     # eased toward _frac so the arc never jumps
        self._celebrating = False
        # Bumped by reset_display(), so a celebration left pending by an
        # abandoned load can never fire its hand-off into the NEXT one (see
        # _emit_celebration).
        self._celebration_token = 0
        self._pulse = 0.0
        self._fade = 1.0           # see set_fade()

        self._timer = QTimer(self)
        # Qt's default (CoarseTimer) is allowed up to ~5% slack and gets
        # batched with other timers for power saving — visible as jitter at
        # a 33 ms interval. PreciseTimer keeps the ring's easing/pulse smooth.
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._tick)
        self._timer.start(FRAME_MS)

    # ── QProgressBar-compatible API ─────────────────────────────────────
    def setRange(self, minimum: int, maximum: int):
        self._min, self._max = minimum, max(maximum, minimum + 1)

    def setValue(self, value: int):
        self._value = max(self._min, min(self._max, int(value)))

    def value(self) -> int:
        return self._value

    def setTextVisible(self, visible: bool):   # accepted; the % is always drawn
        pass

    def reset_display(self):
        """Snaps the drawn arc back to 0 without touching the underlying
        value — used to make a loading screen that starts already ahead
        (backend work began earlier, off-screen) still read as a normal,
        if unusually fast, climb from 0 rather than jumping in partway.

        Also clears the celebration latch. That matters for every load
        after the first: `celebrate()` is a one-shot, and a ring still
        latched from the previous match paints a full green arc (paintEvent
        forces frac=1.0 while celebrating) and — worse — returns early
        instead of emitting `celebration_finished`, which is what hands the
        screen over to the embedded game."""
        self._shown_frac = 0.0
        self._celebrating = False
        self._celebration_token += 1
        self.update()

    def celebrate(self):
        if self._celebrating:
            return
        self._celebrating = True
        token = self._celebration_token
        QTimer.singleShot(CELEBRATION_MS, lambda: self._emit_celebration(token))

    def _emit_celebration(self, token):
        if token == self._celebration_token and self._celebrating:
            self.celebration_finished.emit()

    # ── animation ────────────────────────────────────────────────────────
    def _tick(self):
        frac = (self._value - self._min) / (self._max - self._min)
        self._shown_frac += (frac - self._shown_frac) * 0.18
        self._pulse = (self._pulse + FRAME_MS / 1000.0) % 2.0
        self.update()

    # ── paint ────────────────────────────────────────────────────────────
    def set_fade(self, opacity: float):
        """Whole-ring opacity, applied in paintEvent. The kick-off fade-in
        uses this instead of a QGraphicsOpacityEffect, which would render the
        ring into an offscreen pixmap on every frame of the fade."""
        self._fade = max(0.0, min(1.0, opacity))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        if self._fade < 1.0:
            p.setOpacity(self._fade)

        side = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        r = side / 2 - 14
        thick = max(6, side * 0.045)

        glow_r = r + side * 0.16
        glow = QRadialGradient(cx, cy, glow_r)
        pulse = 0.5 + 0.5 * math.sin(self._pulse * math.pi)
        glow_col = QColor(ACCENT if not self._celebrating else BORDER_EM)
        glow_col.setAlpha(int(14 + 10 * pulse))
        glow.setColorAt(0.0, glow_col)
        glow.setColorAt(1.0, QColor(glow_col.red(), glow_col.green(), glow_col.blue(), 0))
        p.setPen(Qt.NoPen)
        p.setBrush(glow)
        p.drawEllipse(QRectF(cx - glow_r, cy - glow_r, glow_r * 2, glow_r * 2))

        ring_rect = QRectF(cx - r, cy - r, r * 2, r * 2)
        # Built fresh (not via p.pen()): the glow was drawn with Qt.NoPen,
        # and a QPen copied from that keeps NoPen's style even after its
        # color/width are changed — nothing then draws.
        pen = QPen()
        pen.setWidthF(thick)
        pen.setCapStyle(Qt.RoundCap)
        pen.setColor(QColor(ACCENT))
        p.setPen(pen)
        p.drawArc(ring_rect, 0, 360 * 16)

        frac = 1.0 if self._celebrating else self._shown_frac
        pen.setColor(QColor(GREEN_2 if self._celebrating else BORDER_EM))
        p.setPen(pen)
        span = int(-360 * frac * 16)
        p.drawArc(ring_rect, 90 * 16, span)

        # leading-edge dot, like a stopwatch hand
        if 0.0 < frac < 1.0:
            ang = math.radians(90 - 360 * frac)
            hx = cx + r * math.cos(ang)
            hy = cy - r * math.sin(ang)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(GREEN_2))
            hr = thick * 0.55
            p.drawEllipse(QRectF(hx - hr, hy - hr, hr * 2, hr * 2))

        # Number and "%" measured and centered as one unit, sign written
        # after the digits — a fixed split point either overlaps two-digit
        # numbers or leaves single-digit ones off-centre.
        pct = int(round(frac * 100))
        num_txt = str(pct)
        num_font = tracked_font("Barlow Condensed", int(side * 0.30), QFont.Bold, track=0)
        pct_font = tracked_font("Barlow", int(side * 0.09), QFont.DemiBold, track=0)
        p.setFont(num_font)
        num_w = p.fontMetrics().horizontalAdvance(num_txt)
        p.setFont(pct_font)
        sign_w = p.fontMetrics().horizontalAdvance("%")
        total_w = num_w + sign_w * 1.15
        x0 = cx - total_w / 2

        p.setFont(num_font)
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(x0, cy - r * 0.5, num_w, r), Qt.AlignLeft | Qt.AlignVCenter, num_txt)
        p.setFont(pct_font)
        p.setPen(QColor(FG_SECONDARY))
        p.drawText(QRectF(x0 + num_w + sign_w * 0.15, cy - r * 0.06, sign_w * 1.2, r * 0.3),
                   Qt.AlignLeft | Qt.AlignVCenter, "%")
