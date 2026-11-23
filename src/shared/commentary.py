"""
shared/commentary.py — the commentary name clips
====================================================
A player's `commentary` id picks which recorded surname the commentators
say. The ids are the clip numbers in the game's Audio/dat_eng.big, a BIGF
archive whose entries are named "<id:04d>_<Name>.dat" (0060_Bailey.dat):
the name in the file is what is said, which for players the game never
shipped is a sound-alike (Baille uses 60 "Bailey"). Each entry is an EA
SCHl MicroTalk stream (shared/ea_mt.py).

New clips are files in the mod data's commentary folder (the pack's, or
the user's own in user_data/mod_data/commentary), with ids from CUSTOM_BASE:

    3000_Dupont.dat   a clip in the game's format (tools/voicegen makes them)
    3001_Dupont.wav   a recording, converted when used (shared/commentary_audio)
    Dupont.wav        a recording without an id: it gets a fixed one from
                      AUTO_BASE up, worked out from the name

backend/commentary_deploy.py adds them to the game's archives before a
match; here they are listed next to the stock ones. In the game they are
numbered again, from GAME_BASE in id order (game_ids): the game was heard
saying clip 3000 but never ids from 5000 up.

    names()        -> {id: "Bailey", ...}  ({} when the archive isn't found)
    custom_clips() -> {id: (name, path)} of the new clips
    clip_data(path) -> the game clip of a new clip file
    in_game(id)    -> the id the game knows the clip by
    match_clip(id, last_name) -> the id to use in a match: when the player's
                     clip is none or a sound-alike, a clip saying exactly
                     the surname (stock first, else a new one) replaces it
    wav_bytes(id)  -> a mono 16-bit WAV of the clip, or None
"""
import glob
import io
import os
import re
import struct
import sys
import wave
import zlib

from shared.config import config
from shared.ea_mt import decode_schl
from shared.log import get_logger

log = get_logger(__name__)

_CLIP = re.compile(r"(\d{4,5})_(.+)\.dat$", re.IGNORECASE)
_CUSTOM = re.compile(r"(?:(\d{4,5})_)?(.+)\.(dat|wav)$", re.IGNORECASE)
_index = None       # (archive path, {id: (name, offset, size)})

#: first id of the new clips; the stock ones stop at 2705
CUSTOM_BASE = 3000
#: ids of the recordings named without one (Dupont.wav): AUTO_BASE + a hash
AUTO_BASE, AUTO_END = 5000, 10000
CUSTOM_FOLDER = "commentary"
#: first id of the new clips in the game's archives
GAME_BASE = 3000


def _archive_path():
    audio = os.path.join(getattr(config, "R08_directory", "") or "", "Audio")
    # the stock archive, kept aside once the new clips were added to it
    for name in ("dat_eng.big.stock", "dat_eng.big"):
        preferred = os.path.join(audio, name)
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
        if m and int(m.group(1)) < CUSTOM_BASE:
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


def custom_folder():
    return os.path.join(getattr(config, "mod_data_directory", "") or "", CUSTOM_FOLDER)


def custom_clips(folder=None):
    """{id: (name said, path)} of the new clips in the mod data."""
    folder = folder or custom_folder()
    out, unnumbered = {}, {}
    try:
        files = sorted(os.listdir(folder))
    except OSError:
        return out
    for fn in files:
        m = _CUSTOM.match(fn)
        if not m:
            continue
        name = m.group(2).replace("_", " ").strip()
        path = os.path.join(folder, fn)
        if m.group(1):
            cid = int(m.group(1))
            if CUSTOM_BASE <= cid <= 0xFFFF and cid not in out:
                out[cid] = (name, path)
        elif m.group(3).lower() == "wav" and _key(name):
            unnumbered.setdefault(_key(name), (name, path))
    for key in sorted(unnumbered):
        cid = _auto_id(key, out)
        if cid:
            out[cid] = unnumbered[key]
    return out


def _auto_id(key, taken):
    """The id of an unnumbered recording: the same one each time for a
    name (the next free one when two names land on it)."""
    span = AUTO_END - AUTO_BASE
    start = zlib.crc32(key.encode()) % span
    for i in range(span):
        cid = AUTO_BASE + (start + i) % span
        if cid not in taken:
            return cid
    return None


def next_id(folder=None):
    """A free id for a new numbered clip (below the unnumbered ones)."""
    used = set(custom_clips(folder)) | set(names())
    cid = CUSTOM_BASE
    while cid in used or AUTO_BASE <= cid < AUTO_END:
        cid += 1
    return cid


def game_ids(clips=None):
    """{new clip id: its id in the game}: 3000, 3001... in id order."""
    clips = custom_clips() if clips is None else clips
    return {cid: GAME_BASE + i for i, cid in enumerate(sorted(clips))}


def in_game(cid):
    """The id a match gives the game for clip `cid` (0: a new clip that is gone)."""
    if cid < CUSTOM_BASE:
        return cid
    return game_ids().get(cid, 0)


def clip_data(path):
    """The game clip (SCHl bytes) of a new clip file: a .dat as it is, a
    recording converted. ValueError / OSError when unusable."""
    if path.lower().endswith(".wav"):
        from shared import commentary_audio
        return commentary_audio.to_clip(path)
    with open(path, "rb") as f:
        data = f.read()
    if data[:4] != b"SCHl":
        raise ValueError("not a commentary clip")
    return data


def _key(name):
    return re.sub(r"[^a-z]", "", (name or "").lower())


def match_clip(cid, last_name):
    try:
        cid = int(cid or 0)
    except (TypeError, ValueError):
        cid = 0
    said = names()
    if cid >= CUSTOM_BASE and cid not in said:
        cid = 0                             # a new clip that was removed
    key = _key(last_name)
    if not key:
        return cid
    if cid and _key(said.get(cid)) == key:
        return cid                          # already says the name
    exact = [c for c, n in said.items() if _key(n) == key]
    return min(exact) if exact else cid


def names():
    """{commentary id: the name said}: the game's clips (none when its
    archive is missing or unreadable) and the new ones."""
    out = {cid: entry[0] for cid, entry in _load().items()}
    out.update({cid: entry[0] for cid, entry in custom_clips().items()})
    return out


def clip_bytes(cid, folder=None):
    """The SCHl stream of clip `cid`, or None. `folder`: where the new
    clips are (default: the mod data's)."""
    custom = custom_clips(folder).get(cid) if cid >= CUSTOM_BASE else None
    if custom:
        try:
            return clip_data(custom[1])
        except ValueError as e:
            log.warning("commentary clip %s unusable: %s", custom[1], e)
            return None
    entry = _load().get(cid)
    if entry is None:
        return None
    _, offset, size = entry
    with open(_index[0], "rb") as f:
        f.seek(offset)
        return f.read(size)


def wav_bytes(cid, folder=None):
    """The clip for `cid` as WAV file bytes, or None."""
    try:
        cid = int(cid)
    except (TypeError, ValueError):
        return None
    try:
        data = clip_bytes(cid, folder)
        if data is None:
            return None
        samples, rate = decode_schl(data)
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
