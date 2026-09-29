"""
ui/atmosphere.py — ambient stadium background layer
=====================================================
Soft floodlight cones + vignette + fine grain behind a screen's content,
the same treatment the mockups used (see gen_mockups.py's atmosphere()).
A still image can't show motion, so this runs a slow (70s) drift instead —
barely perceptible tick to tick, but it keeps the gaps around the cards
from reading as a flat fill.

The light layer is rendered at low resolution and scaled up with smooth
filtering rather than drawn straight at full size: the alpha deltas
involved are tiny (single digits out of 255) spread over a huge gradient
radius, which 8-bit quantization turns into visible banded rings — at a
glance, a rectangle-ish "box" around the content. Rendering small and
upscaling with bilinear filtering interpolates through those bands
instead of hard-stepping across them.
"""
import math
import random

from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QPainter, QColor, QRadialGradient, QPixmap, QImage
from PyQt5.QtCore import Qt, QTimer, QPointF, QRectF

from ui.theme import BG_BASE

_FLOOD_COLOR = (255, 214, 140)     # warm floodlight amber, matches the mockup
_DRIFT_PERIOD_MS = 46_000          # one full drift cycle — slow, but paced to
                                    # actually be noticed rather than just
                                    # technically animating
_GRAIN_DRIFT_PERIOD_MS = 19_000    # grain drifts on its own, faster and out
                                    # of phase with the light sway, so the
                                    # texture itself reads as alive
_TICK_MS = 200
_LAYER_W = 96                      # low-res render target for the light layer —
                                    # small enough that the smooth upscale erases
                                    # banding, large enough to keep the gradient
                                    # shapes recognisable


def _grain_pixmap(size=160, seed=7):
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    rnd = random.Random(seed)
    for _ in range(240):
        x, y = rnd.randint(0, size - 1), rnd.randint(0, size - 1)
        p.setPen(QColor(255, 255, 255, rnd.randint(4, 14)))
        p.drawPoint(x, y)
    p.end()
    return pm


def _light_layer(w, h, drift):
    """Floodlight cones + vignette, rendered at (w, h) — meant to be small
    and then scaled up by the caller."""
    img = QImage(w, h, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setCompositionMode(QPainter.CompositionMode_Plus)
    r, g, b = _FLOOD_COLOR
    for cx in (-w * 0.08 + drift, w * 1.08 + drift):
        grad = QRadialGradient(QPointF(cx, -h * 0.15), h * 1.15)
        grad.setColorAt(0.0, QColor(r, g, b, 62))
        grad.setColorAt(0.55, QColor(r, g, b, 22))
        grad.setColorAt(1.0, QColor(r, g, b, 0))
        p.setBrush(grad)
        p.drawRect(0, 0, w, h)
    p.setCompositionMode(QPainter.CompositionMode_SourceOver)

    # vignette — darker at the edges, so the lit centre reads as a stage
    vg = QRadialGradient(QPointF(w * 0.5, h * 0.42), max(w, h) * 0.75)
    vg.setColorAt(0.0, QColor(0, 0, 0, 0))
    vg.setColorAt(0.7, QColor(0, 0, 0, 55))
    vg.setColorAt(1.0, QColor(0, 0, 0, 145))
    p.setBrush(vg)
    p.drawRect(0, 0, w, h)
    p.end()
    return img


class AtmosphereWidget(QWidget):
    """Drop-in background: fills with BG_BASE plus a slow-drifting ambient
    lighting layer. Sits at the base of a screen's stack, with real content
    laid out in a layout on top of it — an ordinary QWidget in every way
    except what paintEvent draws."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grain = _grain_pixmap()
        self._phase = 0.0
        self._grain_phase = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)   # see PlayerView._timer
        self._timer.timeout.connect(self._tick)
        self._timer.start(_TICK_MS)

    def _tick(self):
        self._phase = (self._phase + _TICK_MS / _DRIFT_PERIOD_MS) % 1.0
        self._grain_phase = (self._grain_phase + _TICK_MS / _GRAIN_DRIFT_PERIOD_MS) % 1.0
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(_TICK_MS)

    def hideEvent(self, event):
        super().hideEvent(event)
        self._timer.stop()

    def paintEvent(self, event):
        w, h = self.width(), self.height()
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_BASE))
        if w <= 0 or h <= 0:
            return

        drift = math.sin(self._phase * 2 * math.pi) * 70   # px — a slow sway, not a pan

        layer_h = max(1, int(_LAYER_W * h / w))
        layer = _light_layer(_LAYER_W, layer_h, drift * _LAYER_W / w)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.drawImage(QRectF(0, 0, w, h), layer)

        # fine grain for texture — drifts on its own, out of phase with the
        # light sway, so the texture itself reads as gently alive rather
        # than a static overlay riding on top of the moving light
        gx = math.sin(self._grain_phase * 2 * math.pi) * self._grain.width() * 0.5
        gy = math.cos(self._grain_phase * 2 * math.pi) * self._grain.height() * 0.5
        p.drawTiledPixmap(QRectF(self.rect()), self._grain, QPointF(gx, gy))
