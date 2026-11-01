"""
shared/commentary.py — the commentary name clips
====================================================
A player's `commentary` id picks which recorded surname the commentators
say. The ids are the clip numbers in the game's Audio/dat_eng.big, a BIGF
archive whose entries are named "<id:04d>_<Name>.dat" (0060_Bailey.dat):
the name in the file is what is said, which for players the game never
shipped is a sound-alike (Baille uses 60 "Bailey"). Each entry is an EA
SCHl MicroTalk stream (shared/ea_mt.py).

    names()        -> {id: "Bailey", ...}  ({} when the archive isn't found)
    wav_bytes(id)  -> a mono 16-bit WAV of the clip, or None
"""
import glob
import io
import os
import re
import struct
import sys
import wave

from shared.config import config
from shared.ea_mt import decode_schl
from shared.log import get_logger

log = get_logger(__name__)

_CLIP = re.compile(r"(\d{4})_(.+)\.dat$", re.IGNORECASE)
_index = None       # (archive path, {id: (name, offset, size)})


def _archive_path():
    audio = os.path.join(getattr(config, "R08_directory", "") or "", "Audio")
    preferred = os.path.join(audio, "dat_eng.big")
    if os.path.isfile(preferred):
        return preferred
    found = sorted(glob.glob(os.path.join(audio, "dat_*.big")))
    return found[0] if found else None


def _read_index(path):
    clips = {}
    with open(path, "rb") as f:
        head = f.read(16)
        if len(head) < 16 or head[:4] != b"BIGF":
            raise ValueError("not a BIGF archive")
        count, header_size = struct.unpack(">II", head[8:16])
        table = f.read(max(0, header_size - 16))
    pos = 0
    for _ in range(count):
        if pos + 8 > len(table):
            break
        offset, size = struct.unpack_from(">II", table, pos)
        end = table.index(b"\0", pos + 8)
        name = table[pos + 8:end].decode("latin-1")
        pos = end + 1
        m = _CLIP.match(name)
        if m:
            clips[int(m.group(1))] = (m.group(2).replace("_", " "), offset, size)
    return clips


def _load():
    global _index
    path = _archive_path()
    if _index is not None and _index[0] == path:
        return _index[1]
    clips = {}
    if path:
        try:
            clips = _read_index(path)
        except (OSError, ValueError) as e:
            log.warning("commentary clips unreadable in %s: %s", path, e)
    _index = (path, clips)
    return clips


def names():
    """{commentary id: the name said}, empty when the game's archive is
    missing or unreadable."""
    return {cid: entry[0] for cid, entry in _load().items()}


def wav_bytes(cid):
    """The clip for `cid` as WAV file bytes, or None."""
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return None
    entry = _load().get(cid)
    if entry is None:
        return None
    _, offset, size = entry
    try:
        with open(_index[0], "rb") as f:
            f.seek(offset)
            samples, rate = decode_schl(f.read(size))
    except (OSError, ValueError, IndexError, struct.error) as e:
        log.warning("commentary clip %s failed to decode: %s", cid, e)
        return None
    if samples.itemsize != 2:
        return None
    if sys.byteorder == "big":             # WAV is little-endian
        samples.byteswap()
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(samples.tobytes())
    return buf.getvalue()
