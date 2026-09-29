"""
ui/icons.py — small QPainter glyphs shared by the broadcast widget kit.
Mirrors the primitives used to render the approved mockups
(scratchpad/mockup/gen_mockups.py) so the built app matches them.
"""
from PyQt5.QtGui import QPainter, QColor, QPolygonF, QPen
from PyQt5.QtCore import QPointF, QRectF, Qt


def arrow(p: QPainter, cx, cy, direction, color, size=8):
    p.save()
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    if direction == "left":
        pts = [QPointF(cx + size, cy - size), QPointF(cx + size, cy + size), QPointF(cx - size, cy)]
    elif direction == "right":
        pts = [QPointF(cx - size, cy - size), QPointF(cx - size, cy + size), QPointF(cx + size, cy)]
    elif direction == "up":
        pts = [QPointF(cx - size, cy + size), QPointF(cx + size, cy + size), QPointF(cx, cy - size)]
    else:
        pts = [QPointF(cx - size, cy - size), QPointF(cx + size, cy - size), QPointF(cx, cy + size)]
    p.drawPolygon(QPolygonF(pts))
    p.restore()


def gamepad_icon(p: QPainter, cx, cy, s, color):
    p.save()
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.6, 2.6 * s))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    w, h = 46 * s, 26 * s
    rect = QRectF(cx - w / 2, cy - h / 2, w, h)
    p.drawRoundedRect(rect, h * 0.5, h * 0.5)
    r = h * 0.42
    p.drawEllipse(QPointF(rect.left() + w * 0.30, cy), r, r)
    p.drawEllipse(QPointF(rect.left() + w * 0.70, cy), r, r)
    p.restore()


def keyboard_icon(p: QPainter, cx, cy, s, color):
    p.save()
    pen = QPen(QColor(color))
    pen.setWidthF(max(1.4, 2.0 * s))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    w, h = 44 * s, 26 * s
    rect = QRectF(cx - w / 2, cy - h / 2, w, h)
    p.drawRoundedRect(rect, 3 * s, 3 * s)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(color))
    for row in range(2):
        for col in range(6):
            kx = rect.left() + 5 * s + col * (w - 10 * s) / 6
            ky = rect.top() + 5 * s + row * (h - 10 * s) / 2
            p.drawRect(QRectF(kx, ky, (w - 10 * s) / 6 - 2.5 * s, (h - 10 * s) / 2 - 2.5 * s))
    p.restore()


def link_icon(p: QPainter, cx, cy, linked, s, color=None, break_color="#e0483c"):
    p.save()
    pen = QPen(QColor(color) if color else QColor("#4d5872"))
    pen.setWidthF(max(1.6, 2.4 * s))
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    r = 8 * s
    gap = 1.5 * s if linked else 8 * s
    for sign in (-1, 1):
        ex = cx + sign * gap
        p.drawEllipse(QRectF(ex - r, cy - r * 0.7, r * 2, r * 1.4))
    if not linked:
        pen2 = QPen(QColor(break_color))
        pen2.setWidthF(max(1.4, 2.0 * s))
        p.setPen(pen2)
        p.drawLine(QPointF(cx - 3 * s, cy - 7 * s), QPointF(cx + 3 * s, cy + 7 * s))
    p.restore()
