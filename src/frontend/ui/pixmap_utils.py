"""ui/pixmap_utils.py — small QPixmap helpers."""
import numpy as np
from PyQt5.QtCore import QRect
from PyQt5.QtGui import QImage, QPixmap


def trim_transparent(pix: QPixmap):
    """(trimmed pixmap, QRect of the kept area in `pix` coordinates): `pix`
    cropped to the bounding box of its non-transparent pixels. Returns
    (pix, its own rect) when there is nothing to trim."""
    whole = QRect(0, 0, pix.width(), pix.height())
    if pix.isNull():
        return pix, whole
    img = pix.toImage().convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    raw = np.frombuffer(img.constBits().asstring(img.bytesPerLine() * h), dtype=np.uint8)
    alpha = raw.reshape(h, img.bytesPerLine())[:, : w * 4].reshape(h, w, 4)[:, :, 3]
    rows, cols = np.where(alpha.any(axis=1))[0], np.where(alpha.any(axis=0))[0]
    if not len(rows) or not len(cols):
        return pix, whole
    rect = QRect(int(cols[0]), int(rows[0]), int(cols[-1] - cols[0] + 1), int(rows[-1] - rows[0] + 1))
    return pix.copy(rect), rect
