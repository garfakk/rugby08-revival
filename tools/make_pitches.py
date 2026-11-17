"""
tools/make_pitches.py — builds the mod's own pitch textures (data/pitches/*.big)
================================================================================
Synthetic (artificial turf) and hybrid (natural grass stitched with fibres)
pitches, made from the game's own "best" pitch packs: the same mesh and
mowing masks, new grass tiles (tp01..tp04) and detail tile (dtil).

    python tools/make_pitches.py          (needs the game's data.gob in the config)
"""
import os
import sys

import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "src", "frontend")]

from backend import pitches                                    # noqa: E402
from shared.omodel.bigfile import BigArchive, pack_big         # noqa: E402
from shared.omodel.fshlib import Fsh                           # noqa: E402

OUT = os.path.join(ROOT, "data", "pitches")
TILES = ("tp01", "tp02", "tp03", "tp04")

# name -> (stock pack it is made from, grass colour, how much of the stock
#          mottling stays, fibre noise, detail kind)
MADE = {
    "Mod_08_synthetic_d": ("Reg2_08_best_d", (62, 122, 42), 0.30, 5.0, "weave"),
    "Mod_08_synthetic_n": ("Reg2_08_best_n", (58, 112, 42), 0.30, 5.0, "weave"),
    "Mod_08_hybrid_d": ("Reg2_08_best_d", (68, 110, 36), 0.60, 3.0, "stitch"),
}


def _grass(tiles, colour, keep, noise, rng):
    """Every tile recoloured to `colour`, keeping `keep` of the stock tiles'
    own (shared) variation: the tiles of the pitch still meet."""
    mean = np.mean([t[..., :3].reshape(-1, 3).mean(0) for t in tiles.values()], axis=0)
    out = {}
    for tag, t in tiles.items():
        rgb = np.array(colour, np.float32) + keep * (t[..., :3] - mean)
        rgb = rgb + rng.normal(0, noise, t.shape[:2])[..., None] * np.array([0.8, 1.0, 0.6])
        out[tag] = np.dstack([np.clip(rgb, 0, 255), np.full(t.shape[:2], 255)])
    return out


def _detail(src, kind, rng):
    """The detail tile (128 = neutral: it is laid with dst * src * 2)."""
    h, w = src.shape[:2]
    y, x = np.mgrid[0:h, 0:w]
    if kind == "weave":      # rows of fibres, 8 px apart, and a fine grain
        v = 128 + 11 * np.sin(2 * np.pi * y / 8) + 5 * np.sin(2 * np.pi * (x + 4 * (y // 8 % 2)) / 16)
        v = v + rng.normal(0, 5, (h, w))
    else:                    # hybrid: the grass' own detail, softened, and stitching every 16 px
        v = 128 + 0.55 * (src[..., :3].mean(2) - 128)
        v = v - 14 * (((x % 16) == 0) | ((y % 16) == 0)) + rng.normal(0, 3, (h, w))
    v = np.clip(v, 0, 255)
    return np.dstack([v, v, v, np.full((h, w), 255.0)])


def build(name):
    base, colour, keep, noise, kind = MADE[name]
    src = BigArchive.open(pitches.pack_path(base))
    fsh = Fsh(src.read("Textures.fsh"))
    rng = np.random.default_rng(sum(map(ord, name)))
    entries = {e.name: e for e in fsh.entries}
    tiles = {t: np.asarray(entries[t].decode(), np.float32) for t in TILES}
    new = _grass(tiles, colour, keep, noise, rng)
    new["dtil"] = _detail(np.asarray(entries["dtil"].decode(), np.float32), kind, rng)
    from PIL import Image
    for tag, arr in new.items():
        fsh.replace(entries[tag], Image.fromarray(arr.astype(np.uint8), "RGBA"))
    pack = [(n, bytes(fsh.blob) if n == "Textures.fsh" else src.read(n)) for n in src.entries]
    os.makedirs(OUT, exist_ok=True)
    path = os.path.join(OUT, name.lower() + ".big")
    with open(path, "wb") as fh:
        fh.write(pack_big(pack))
    print(path, os.path.getsize(path))


if __name__ == "__main__":
    for n in MADE:
        build(n)
