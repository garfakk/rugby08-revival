"""
backend/pitch_stripes.py — the mowing stripes of a stadium's pitch
===================================================================
The game paints a pitch's grass tiles (tp01..tp04, backend/pitches.py) with
a mowing mask each (mowa, mowb, mowc, mowf: light and dark bands) whose
strength comes from the stadium's scene pack, its Config.bin: the mask
shader's "Contrast" is built from three of its floats (stock values run
0 .. 0.4, 0 on muddy and frosty pitches, about 0.35 on a dry one) and the
grass colour is scaled by a fourth (0.76 .. 1.34).

  float 35   stripes     how strong the bands are (0 = a plain lawn)
  float 36   brightness  the grass colour gain

A stadium's JSON may keep its own values per environment ("stripes":
{"day": {"opacity": 35, "brightness": 110}}, percent of those floats); a
match rewrites them in the scene pack it deploys (`apply`). Without them the
pack's own values stand.
"""
import struct

from shared.log import get_logger
from shared.omodel.bigfile import BigArchive, pack_big

log = get_logger(__name__)

CONFIG = "Config.bin"
MAGIC = 0xDEADBEEF
FIELDS = {"opacity": 35, "brightness": 36}               # key -> float index in Config.bin
RANGES = {"opacity": (0, 100), "brightness": (50, 150)}   # percent
MASKS = {"tp01": "mowa", "tp02": "mowb", "tp03": "mowc", "tp04": "mowf"}   # tile -> its mask


def _config(blob):
    """Config.bin bytes of the scene pack `blob`, None when it has none."""
    archive = BigArchive(blob)
    if CONFIG not in archive:
        return archive, None
    raw = archive.read(CONFIG)
    if len(raw) < (max(FIELDS.values()) + 1) * 4 or struct.unpack_from("<I", raw)[0] != MAGIC:
        return archive, None
    return archive, raw


def clean(values):
    """`values` with only the known keys, whole percents in range; {} when
    nothing is left (= the pack's own)."""
    out = {}
    for key, (lo, hi) in RANGES.items():
        try:
            out[key] = max(lo, min(hi, int(round(float((values or {})[key])))))
        except (KeyError, TypeError, ValueError):
            continue
    return out


def read(path):
    """{"opacity", "brightness"} (percent) of the scene pack at `path`; {}
    when the pack has no readable Config.bin."""
    try:
        with open(path, "rb") as fh:
            _archive, raw = _config(fh.read())
    except (OSError, ValueError, struct.error):
        return {}
    if raw is None:
        return {}
    return {key: int(round(struct.unpack_from("<f", raw, idx * 4)[0] * 100)) for key, idx in FIELDS.items()}


def contrast(values):
    """(stripes, gain) as the shader sees them, from percent `values`."""
    return values.get("opacity", 0) / 100.0, values.get("brightness", 100) / 100.0


def apply(path, values):
    """Rewrite the scene pack at `path` with `values` (percent, see clean);
    False when it has nothing to change."""
    values = clean(values)
    if not values:
        return False
    with open(path, "rb") as fh:
        archive, raw = _config(fh.read())
    if raw is None:
        log.warning(f"stripes: {path} has no usable {CONFIG}")
        return False
    data = bytearray(raw)
    for key, pct in values.items():
        struct.pack_into("<f", data, FIELDS[key] * 4, pct / 100.0)
    entries = [(n, bytes(data) if n == CONFIG else archive.read(n)) for n in archive.entries]
    with open(path, "wb") as fh:
        fh.write(pack_big(entries))
    return True
