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
#          mottling stays, fibre noise, detail kind). A "turf" colour is a hue:
#          it is brought to the stock grass' brightness (day and night match
#          their stock pitches' light).
MADE = {
    "Mod_08_synthetic_d": ("Reg2_08_best_d", (58, 114, 48), 0.10, 0.0, "turf"),
    "Mod_08_synthetic_n": ("Reg2_08_best_n", (58, 114, 48), 0.10, 0.0, "turf"),
    "Mod_08_hybrid_d": ("Reg2_08_best_d", (68, 110, 36), 0.60, 3.0, "stitch"),
}
# artificial turf comes in rolls ~3.8 m wide: the detail tile repeats every
# ~2047 units across (4 units a texel) -> a seam every 64 texels
ROLL = 64


def _luma(rgb):
    return float(np.dot(rgb, (0.299, 0.587, 0.114)))


def _grass(tiles, colour, keep, noise, rng, match_light=False):
    """Every tile recoloured to `colour`, keeping `keep` of the stock tiles'
    own (shared) variation: the tiles of the pitch still meet. `match_light`:
    `colour` is scaled to the stock grass' brightness."""
    mean = np.mean([t[..., :3].reshape(-1, 3).mean(0) for t in tiles.values()], axis=0)
    if match_light:
        colour = np.array(colour, np.float32) * (_luma(mean) / _luma(colour))
    out = {}
    for tag, t in tiles.items():
        rgb = np.array(colour, np.float32) + keep * (t[..., :3] - mean)
        rgb = rgb + rng.normal(0, noise, t.shape[:2])[..., None] * np.array([0.8, 1.0, 0.6])
        out[tag] = np.dstack([np.clip(rgb, 0, 255), np.full(t.shape[:2], 255)])
    return out


def _blur(a, sx, sy):
    """Gaussian blur that wraps around (the tile repeats), sx / sy in texels."""
    h, w = a.shape
    fy, fx = np.fft.fftfreq(h)[:, None], np.fft.fftfreq(w)[None, :]
    k = np.exp(-2 * (np.pi ** 2) * ((fx * sx) ** 2 + (fy * sy) ** 2))
    return np.real(np.fft.ifft2(np.fft.fft2(a) * k))


def _norm(a):
    return (a - a.mean()) / (a.std() or 1.0)


def _turf(h, w, rng):
    """Artificial turf seen from a match camera, grey around 128: a fine
    grain of fibre tips leaning one way (texels are 4 units across, 7 along),
    their brushing in soft patches, black rubber crumb between them, a few
    bright tips, and the rolls: a faint seam and a shade of their own each."""
    v = 10.0 * _norm(_blur(rng.normal(size=(h, w)), 0.55, 1.1))          # fibre tips
    v += 3.5 * _norm(_blur(rng.normal(size=(h, w)), 10.0, 6.0))          # brushing patches
    crumb = _blur((rng.random((h, w)) < 0.035).astype(float), 0.5, 0.4)
    v -= 120.0 * crumb                                                     # rubber crumb
    v += 30.0 * (rng.random((h, w)) < 0.006)                              # bright tips
    x = np.arange(w)
    shade = rng.normal(0, 2.0, w // ROLL + 1)[x // ROLL]                  # roll to roll
    seam = np.exp(-(((x + ROLL // 2) % ROLL - ROLL // 2) / 0.7) ** 2)      # seam at x % ROLL == 0
    v += shade[None, :] - 16.0 * seam[None, :]
    return 128 + v - v.mean()


def _detail(src, kind, rng):
    """The detail tile (128 = neutral: it is laid with dst * src * 2)."""
    h, w = src.shape[:2]
    y, x = np.mgrid[0:h, 0:w]
    if kind == "turf":
        v = _turf(h, w, rng)
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
    new = _grass(tiles, colour, keep, noise, rng, match_light=kind == "turf")
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
