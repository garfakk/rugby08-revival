"""Silences the stock menu/loop music in the user's own Audio/aems.big.

The mod does not ship aems.big (it is EA's data, and 40+ MB): instead the
stock archive already in the game folder is patched in place. Six looping
music tracks are swapped for one silent .abk (assets/templates/silent_loop.abk,
about 1 KB compressed, nothing of the original in it).

Checking is cheap enough to do at every match start: only the archive's
directory (well under 1 KB) is read to tell a stock file from a patched one.
The 40 MB rewrite happens once, through a temp file and an atomic rename, with
the untouched original kept next to it as aems.big.orig.
"""
import os
import shutil
import struct

from shared.config import config
from shared.log import get_logger

log = get_logger(__name__)

ARCHIVE_NAME = "aems.big"
BACKUP_SUFFIX = ".orig"
TEMPLATE_NAME = "silent_loop.abk"

# Entry name -> size in the stock archive (all three retail installs checked
# agree). The patch only touches an archive that matches all of these: an
# unknown build, a different game version or a hand-edited file is left alone.
STOCK_LOOP_SIZES = {
    "apofloop.abk": 323956,
    "casaloop.abk": 129524,
    "d4loop.abk": 242548,
    "skwadloop.abk": 226676,
    "subloop.abk": 146932,
    "wolfloop.abk": 132596,
}

STOCK = "stock"
PATCHED = "patched"
UNKNOWN = "unknown"


def _read_directory(path):
    """(magic, [{'name', 'offset', 'size'}...]) of a BIG archive, reading only
    its directory."""
    with open(path, "rb") as f:
        head = f.read(16)
        magic = head[:4]
        if magic not in (b"BIGF", b"BIG4"):
            raise ValueError(f"not a BIG archive (magic {magic!r})")
        count = struct.unpack(">I", head[8:12])[0]
        header_size = struct.unpack(">I", head[12:16])[0]
        raw = f.read(max(0, header_size - 16))
    entries, pos = [], 0
    for _ in range(count):
        offset, size = struct.unpack(">II", raw[pos:pos + 8])
        end = raw.index(b"\0", pos + 8)
        entries.append({"name": raw[pos + 8:end].decode("ascii"),
                        "offset": offset, "size": size})
        pos = end + 1
    return magic, entries


def archive_state(path, silent_size):
    """STOCK, PATCHED or UNKNOWN for the archive at `path`."""
    try:
        _, entries = _read_directory(path)
    except (OSError, ValueError, struct.error) as e:
        log.warning(f"Cannot read {path}: {e}")
        return UNKNOWN
    sizes = {e["name"].lower(): e["size"] for e in entries}
    if all(sizes.get(n) == s for n, s in STOCK_LOOP_SIZES.items()):
        return STOCK
    # apofloop's stock size equals the silent file's, so it cannot tell the
    # two states apart; the other five can, and the patch is applied to all
    # six atomically.
    others = [n for n in STOCK_LOOP_SIZES if n != "apofloop.abk"]
    if all(sizes.get(n) == silent_size for n in others) and "apofloop.abk" in sizes:
        return PATCHED
    return UNKNOWN


def _rewrite(path, replacements):
    """Write `path` again with the named entries' data replaced. Same layout
    as the archive this replaces: header, directory (padded to 4 bytes), data
    back to back."""
    magic, entries = _read_directory(path)
    with open(path, "rb") as f:
        for e in entries:
            f.seek(e["offset"])
            e["data"] = replacements.get(e["name"].lower()) or f.read(e["size"])
            e["size"] = len(e["data"])
    header_size = 16 + sum(8 + len(e["name"]) + 1 for e in entries)
    header_size = (header_size + 3) & ~3     # directory padded to 4 bytes, as in the archive this replaces
    offset = header_size
    for e in entries:
        e["offset"] = offset
        offset += e["size"]

    dir_end = 16 + sum(8 + len(e["name"]) + 1 for e in entries)
    tmp = path + ".tmp"
    with open(tmp, "wb") as f:
        f.write(magic)
        f.write(struct.pack("<I", offset))
        f.write(struct.pack(">II", len(entries), header_size))
        for e in entries:
            f.write(struct.pack(">II", e["offset"], e["size"]))
            f.write(e["name"].encode("ascii") + b"\0")
        f.write(b"\0" * (header_size - dir_end))
        for e in entries:
            f.write(e["data"])
    os.replace(tmp, path)


def ensure_patched(game_dir=None):
    """Make sure the game's aems.big has its loop music silenced. Returns the
    final state (PATCHED, or UNKNOWN when the file is missing or not the
    stock one — in which case it is left untouched)."""
    game_dir = game_dir or config.game_launcher_directory
    path = os.path.join(game_dir, "Audio", ARCHIVE_NAME)
    template = os.path.join(config.templates_directory, TEMPLATE_NAME)
    if not os.path.isfile(path):
        log.warning(f"{path} not found, audio patch skipped")
        return UNKNOWN
    try:
        with open(template, "rb") as f:
            silent = f.read()
    except OSError as e:
        log.error(f"Silent loop template unreadable: {e}")
        return UNKNOWN

    state = archive_state(path, len(silent))
    if state == PATCHED:
        return PATCHED
    if state == UNKNOWN:
        log.warning(f"{path} is not the stock archive, left untouched "
                    "(menu loops will play)")
        return UNKNOWN

    backup = path + BACKUP_SUFFIX
    try:
        if not os.path.exists(backup):
            shutil.copy2(path, backup)
        _rewrite(path, {name: silent for name in STOCK_LOOP_SIZES})
    except OSError as e:
        log.error(f"Audio patch failed: {e}")
        try:
            os.remove(path + ".tmp")
        except OSError:
            pass
        return UNKNOWN
    log.info("aems.big patched: menu loops silenced")
    return PATCHED
