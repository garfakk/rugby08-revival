"""
ui/face_thumbs.py — face thumbnails for stock portraits and custom heads
=========================================================================
Two shapes come through here: a stock portrait — a small standalone .fsh
(backend.mod_utils.stock_portrait_path), the game's own menu-portrait/
miniface texture, cheaper to fetch and decode than the full head_<n>.big
model archive, and what the game's own menus show — or a modder's custom
head_<n>.big (model.o + textures.fsh), which has no portrait counterpart
so its textures.fsh "face" entry (the 512x512 face texture) is decoded
instead. Decoding is cached as PNGs on disk either way, and only done for
faces actually shown.

face_png_bytes() does the decode/cache and touches no Qt objects, so it is
safe to call from a worker thread (e.g. ui.face_picker's grid, decoding many
faces as they scroll into view) — QPixmap itself must only ever be built on
the GUI thread, which is what face_thumbnail() below is for.
"""
import hashlib
import io
import os

from PyQt5.QtGui import QPixmap


from shared.log import get_logger

log = get_logger(__name__)


def _cache_path(cache_dir, big_path):
    try:
        stamp = f"{big_path}:{os.path.getmtime(big_path)}"
    except OSError:
        return None
    return os.path.join(cache_dir, hashlib.sha1(stamp.encode()).hexdigest()[:16] + ".png")


def cached_face(cache_dir, big_path):
    """The thumbnail if it is already on disk, else a null pixmap (no decode)."""
    path = _cache_path(cache_dir, big_path)
    if path and os.path.isfile(path):
        return QPixmap(path)
    return QPixmap()


def face_png_bytes(cache_dir, path_in, size=160):
    """PNG bytes of a face thumbnail — a stock portrait .fsh
    (backend.mod_utils.stock_portrait_path) or a custom head_<n>.big
    (model.o + textures.fsh) — reading/writing the disk cache. No
    QImage/QPixmap involved, so safe off the GUI thread. Never raises: a
    broken archive just has no thumbnail (None)."""
    if not path_in or not os.path.isfile(path_in):
        return None
    path = _cache_path(cache_dir, path_in)
    if path and os.path.isfile(path):
        try:
            with open(path, "rb") as fh:
                return fh.read()
        except OSError:
            pass
    try:
        from shared.omodel import BigArchive, Fsh
        with open(path_in, "rb") as fh:
            blob = fh.read()
        if blob[:4] == b"BIGF":
            arc = BigArchive(blob)
            name = arc.find(".fsh")
            if name is None:
                return None
            fsh = Fsh(arc.read(name))
            entry = next((e for e in fsh.entries if e.name == "face"),
                        fsh.entries[0] if fsh.entries else None)
        else:
            fsh = Fsh(blob)
            entry = fsh.entries[0] if fsh.entries else None
        if entry is None:
            return None
        img = entry.decode().convert("RGBA")
        img.thumbnail((size, size))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        data = buf.getvalue()
        if path:
            os.makedirs(cache_dir, exist_ok=True)
            with open(path, "wb") as fh:
                fh.write(data)
        return data
    except Exception as e:     # a thumbnail is never worth an error dialog
        log.warning(f"{path_in}: {e}")
        return None


def face_thumbnail(cache_dir, path_in, size=160):
    """Decode (or reuse) a stock portrait .fsh or custom head .big as a
    square QPixmap thumbnail. GUI-thread only — see face_png_bytes() for
    the thread-safe decode this wraps."""
    data = face_png_bytes(cache_dir, path_in, size)
    if not data:
        return QPixmap()
    pix = QPixmap()
    pix.loadFromData(data)
    return pix
