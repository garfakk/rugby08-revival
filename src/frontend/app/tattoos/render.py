"""
app/tattoos/render.py — tattoo designs → the player's skin layer (no Qt)
========================================================================
The game's skin is one 512×256 atlas: two arm tiles and two leg tiles, each 128×256, each the unrolled
surface of a cylinder — x goes once round the limb (its right edge meets its left edge), y runs down it.
Measured on the game's own body model (the 3D preview uses its UVs as is):

  side "a" (x 0–255) is the player's right arm and leg, side "b" (256–511) the left ones.
  arm  shoulder 0 · elbow ~50 · wrist ~125 · hand and fingers 130–256 · front of the arm at x 64
  leg  hidden by the shorts above ~40 · knee ~100–130 · ankle ~245 · front of the leg at x 32

A texture pixel covers less of the limb across than along it, so a motif is widened by `xscale` to look
round on the body. The left and right tiles share one layout (side "a" = the left one in the atlas).

A *design* is a stack of layers, each a motif (shape / generator / imported picture) placed on a limb.
`render_overlay` paints them into one transparent 512×256 image: the flattened tattoo layer the player
wears in `skin_overlay`. Ink is *embedded* by default: its colour is shaded by the skin under it, so the
skin's texture shows through like a real tattoo.
"""
from __future__ import annotations

import re
import uuid

import numpy as np
from PIL import Image, ImageFilter

from . import motifs as M

ATLAS = (512, 256)
LIMBS = {
    "arm": {"a": (0, 0), "b": (256, 0), "size": (128, 256), "xscale": 1.4, "front": 64},
    "leg": {"a": (128, 0), "b": (384, 0), "size": (128, 256), "xscale": 1.15, "front": 32},
}
#: (top, bottom) of the parts of each limb, in tile pixels
ZONES = {
    "arm": {"upper": (4, 46), "elbow": (44, 60), "fore": (58, 124), "wrist": (116, 132),
            "hand": (130, 200), "all": (4, 124)},
    "leg": {"thigh": (38, 100), "knee": (98, 134), "shin": (132, 242), "ankle": (226, 248),
            "all": (38, 242)},
}
INK = "#1c2433"
MAX_LAYERS = 80
ATLAS_MOTIF = "atlas"           # a whole flattened tattoo image kept as one layer (older tattoos)


# ── design ───────────────────────────────────────────────────────────────────
def _num(v, lo, hi, default):
    try:
        v = float(v)
    except (TypeError, ValueError):
        return default
    return min(max(v, lo), hi) if v == v else default


def _colour(v, default=INK) -> str:
    return v if isinstance(v, str) and re.fullmatch(r"#[0-9a-fA-F]{6}", v) else default


def clean_layer(raw: dict, library=None) -> dict:
    """A layer with every field present and in range. `library` (store.Library) knows the imported
    pictures ("user:<id>"); unknown motifs raise ValueError."""
    mid = str(raw.get("motif") or "")
    pic = None
    if mid.startswith("user:"):
        pic = library.item(mid[5:]) if library is not None else None
        if pic is None:
            raise ValueError(f"unknown picture '{mid}'")
    elif mid == ATLAS_MOTIF:
        if not str(raw.get("src") or ""):
            raise ValueError("atlas layer without a picture")
    elif mid not in M.REG:
        raise ValueError(f"unknown motif '{mid}'")
    limb = raw.get("limb") if raw.get("limb") in LIMBS else "arm"
    tw, th = LIMBS[limb]["size"]
    mo = M.REG.get(mid)
    params = M.clean_params(mo, raw.get("params")) if mo else {}
    nat = mo.size if mo else (pic["size"] if pic else 40)
    asp = mo.aspect if mo else (pic["aspect"] if pic else _num(raw.get("aspect"), .1, 10, 1))
    w = _num(raw.get("w"), 4, 512, nat)
    h = _num(raw.get("h"), 2, 512, w / asp)
    return {
        "id": str(raw.get("id") or uuid.uuid4().hex[:8])[:16], "motif": mid, "params": params,
        "name": str(raw.get("name") or (mo.name if mo else pic["name"] if pic else "Earlier tattoos"))[:40],
        "seed": int(_num(raw.get("seed"), 0, 999999, 1)), "limb": limb,
        "side": raw.get("side") if raw.get("side") in ("a", "b", "both") else "both",
        "x": _num(raw.get("x"), -64, tw + 64, LIMBS[limb]["front"]), "y": _num(raw.get("y"), -64, th + 64, th / 2),
        "w": w, "h": h, "rot": _num(raw.get("rot"), -360, 360, 0), "flip": bool(raw.get("flip")),
        "opacity": _num(raw.get("opacity"), 0.05, 1, 0.9), "color": _colour(raw.get("color")),
        "soft": _num(raw.get("soft"), 0, 3, 0.6), "ink": raw.get("ink") if raw.get("ink") in ("embed", "opaque") else "embed",
        "wrap": bool(raw.get("wrap")), "visible": raw.get("visible") is not False,
        "src": str(raw.get("src") or "")[:300] if mid == ATLAS_MOTIF else "",
    }


def clean_design(raw: dict | None, library=None) -> dict:
    raw = raw or {}
    layers = []
    for r in (raw.get("layers") or [])[:MAX_LAYERS]:
        try:
            layers.append(clean_layer(r, library))
        except ValueError:
            continue
    return {"version": 2, "layers": layers}


def has_ink(design: dict) -> bool:
    return any(L["visible"] for L in design["layers"])


# ── one layer ────────────────────────────────────────────────────────────────
def _source(L: dict, w: int, h: int, library=None):
    """(mask L, colours RGB or None) of the layer's motif at w×h."""
    mid = L["motif"]
    if mid.startswith("user:"):
        if library is None:
            return Image.new("L", (w, h), 0), None
        return library.picture(mid[5:], w, h)
    return M.draw_mask(mid, w, h, L["params"], L["seed"]), None


_IMG_CACHE: dict = {}


def layer_images(L: dict, library=None):
    """(mask, colours or None) of the layer as it lies on its tile — size, rotation, mirror, widening done.
    Cached: moving a layer redraws nothing."""
    key = (L["motif"], tuple(sorted((k, str(v)) for k, v in L["params"].items())), L["seed"], L["limb"],
           L["wrap"], round(L["w"], 2), round(L["h"], 2), round(L["rot"], 2), L["flip"])
    hit = _IMG_CACHE.get(key)
    if hit is None:
        hit = _layer_images(L, library)
        if len(_IMG_CACHE) > 300:
            _IMG_CACHE.clear()
        _IMG_CACHE[key] = hit
    return hit


def _layer_images(L: dict, library=None):
    xs = LIMBS[L["limb"]]["xscale"]
    tw, _ = LIMBS[L["limb"]]["size"]
    w = tw / xs if L["wrap"] else L["w"]
    w, h = max(2, round(w)), max(2, round(L["h"]))
    if w * h > 700 * 700:
        return None, None
    m, rgb = _source(L, w, h, library)
    ims = [m] + ([rgb] if rgb is not None else [])
    if L["flip"]:
        ims = [i.transpose(Image.FLIP_LEFT_RIGHT) for i in ims]
    if L["rot"] and not L["wrap"]:
        ims = [i.rotate(-L["rot"], resample=Image.BICUBIC, expand=True) for i in ims]
    if L["wrap"]:
        ims = [i.resize((tw, i.height), Image.LANCZOS) for i in ims]       # exactly once round: no seam
    elif xs != 1.0:
        ims = [i.resize((max(1, round(i.width * xs)), i.height), Image.LANCZOS) for i in ims]
    return ims[0], (ims[1] if len(ims) > 1 else None)


def _paste_max(dst: np.ndarray, m: np.ndarray, x: int, y: int) -> None:
    """dst = max(dst, m placed at x, y) — overlapping edge copies of a wrapped layer must not add up."""
    H, W = dst.shape[:2]
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + m.shape[1], W), min(y + m.shape[0], H)
    if x1 <= x0 or y1 <= y0:
        return
    src = m[y0 - y:y1 - y, x0 - x:x1 - x]
    if dst.ndim == 2:
        np.maximum(dst[y0:y1, x0:x1], src, out=dst[y0:y1, x0:x1])
    else:
        dst[y0:y1, x0:x1] = src


def _on_tile(img: np.ndarray, tw: int, th: int, left: int, top: int, wrap_x: bool = True) -> np.ndarray:
    """`img` placed on a tw×th tile (wrapping round the limb)."""
    shape = (th, tw) if img.ndim == 2 else (th, tw, img.shape[2])
    full = np.zeros(shape, np.float32 if img.dtype != np.uint8 else np.uint8)
    for dx in ((-tw, 0, tw) if wrap_x else (0,)):
        _paste_max(full, img, left + dx, top)
    return full


def render_tile(layers: list[dict], limb: str, tile_under: Image.Image | None = None, library=None,
                atlas_tiles: dict | None = None) -> Image.Image:
    """RGBA tile of one limb side: all its visible layers, bottom first."""
    tw, th = LIMBS[limb]["size"]
    out_rgb = np.zeros((th, tw, 3), np.float32)
    out_a = np.zeros((th, tw), np.float32)
    under = np.asarray(tile_under.convert("RGB"), np.float32) / 255 if tile_under is not None else None
    for L in layers:
        if L["limb"] != limb or not L["visible"]:
            continue
        if L["motif"] == ATLAS_MOTIF:
            tile = (atlas_tiles or {}).get(L["id"])
            if tile is None:
                continue
            t = np.asarray(tile, np.float32) / 255
            a, rgb = t[..., 3] * L["opacity"], t[..., :3]
        else:
            m, colours = layer_images(L, library)
            if m is None:
                continue
            if L["soft"] > 0:
                m = m.filter(ImageFilter.GaussianBlur(L["soft"] * .55))
            cx, cy = (tw / 2 if L["wrap"] else L["x"]), L["y"]
            left, top = round(cx - m.width / 2), round(cy - m.height / 2)
            a = _on_tile(np.asarray(m, np.uint8), tw, th, left, top).astype(np.float32) / 255 * L["opacity"]
            if colours is not None:
                rgb = _on_tile(np.asarray(colours, np.uint8), tw, th, left, top).astype(np.float32) / 255
                if L["ink"] == "embed" and under is not None:
                    lum = under.mean(-1, keepdims=True)
                    rgb = rgb * (0.55 + 0.45 * lum / max(float(lum.mean()), 1e-3))
            else:
                rgb = np.zeros((th, tw, 3), np.float32)
                rgb[:] = [int(L["color"][i:i + 2], 16) / 255 for i in (1, 3, 5)]
                if L["ink"] == "embed" and under is not None:
                    # the ink's own colour, shaded by the skin under it (its creases and pores show through)
                    lum = under.mean(-1, keepdims=True)
                    rgb = rgb * (0.62 + 0.38 * lum / max(float(lum.mean()), 1e-3)) + under * 0.06
        rgb = np.clip(rgb, 0, 1)
        na = a + out_a * (1 - a)
        safe = np.maximum(na, 1e-6)[..., None]
        out_rgb = (rgb * a[..., None] + out_rgb * out_a[..., None] * (1 - a[..., None])) / safe
        out_a = na
    return Image.fromarray((np.dstack([out_rgb, out_a]) * 255 + .5).astype(np.uint8), "RGBA")


def _atlas_tiles(design: dict, library, side: str, limb: str) -> dict:
    """The part of each atlas layer's picture on one tile."""
    out = {}
    spec = LIMBS[limb]
    x, y = spec[side]
    for L in design["layers"]:
        if L["motif"] == ATLAS_MOTIF and L["limb"] == limb and L["side"] in (side, "both") and library is not None:
            img = library.atlas(L["src"])
            if img is not None:
                out[L["id"]] = img.crop((x, y, x + spec["size"][0], y + spec["size"][1]))
    return out


def render_overlay(design: dict, under: Image.Image | None = None, library=None) -> Image.Image:
    """The 512×256 RGBA overlay of the design. `under` = the skin it will lie on (embedded ink takes its texture)."""
    out = Image.new("RGBA", ATLAS, (0, 0, 0, 0))
    if under is not None and under.size != ATLAS:
        under = under.resize(ATLAS, Image.LANCZOS)
    for limb, spec in LIMBS.items():
        for side in ("a", "b"):
            layers = [L for L in design["layers"] if L["limb"] == limb and L["side"] in (side, "both")]
            if not layers:
                continue
            x, y = spec[side]
            tu = under.crop((x, y, x + spec["size"][0], y + spec["size"][1])) if under is not None else None
            out.paste(render_tile(layers, limb, tu, library, _atlas_tiles(design, library, side, limb)), (x, y))
    return out


def compose(base: Image.Image, overlay: Image.Image | None, over: list[Image.Image] = ()) -> Image.Image:
    """What the game paints: base skin, the tattoos, then the other layers (baselayers, straps, gloves) on top."""
    out = base.convert("RGBA")
    if out.size != ATLAS:
        out = out.resize(ATLAS, Image.LANCZOS)
    if overlay is not None:
        out = Image.alpha_composite(out, overlay)
    for im in over:
        im = im.convert("RGBA")
        out = Image.alpha_composite(out, im if im.size == ATLAS else im.resize(ATLAS, Image.LANCZOS))
    out.putalpha(255)
    return out


# ── skin adjust ──────────────────────────────────────────────────────────────
ADJUST_KEYS = ("light", "contrast", "warm", "sat", "red")


def clean_adjust(raw: dict | None) -> dict:
    raw = raw or {}
    return {k: round(_num(raw.get(k), -1, 1, 0), 3) for k in ADJUST_KEYS}


def is_adjusted(adjust: dict | None) -> bool:
    return any(abs(float((adjust or {}).get(k, 0) or 0)) > 1e-3 for k in ADJUST_KEYS)


def adjust_skin(img: Image.Image, adjust: dict | None) -> Image.Image:
    """Brightness, contrast, warmth, saturation and redness of a skin texture (each −1…1, 0 = as is)."""
    if not is_adjusted(adjust):
        return img
    adj = clean_adjust(adjust)
    a = np.asarray(img.convert("RGB"), np.float32) / 255
    a = a * (1 + .5 * adj["light"])
    if adj["contrast"]:
        mean = a.mean()
        a = mean + (a - mean) * (1 + .8 * adj["contrast"])
    w = adj["warm"]
    a[..., 0] *= 1 + .10 * w
    a[..., 2] *= 1 - .16 * w
    f = adj["red"]
    a[..., 0] *= 1 + .12 * f
    a[..., 1] *= 1 - .05 * f
    a[..., 2] *= 1 - .03 * f
    g = a.mean(-1, keepdims=True)
    a = g + (a - g) * (1 + adj["sat"])
    out = Image.fromarray((np.clip(a, 0, 1) * 255 + .5).astype(np.uint8), "RGB").convert("RGBA")
    out.putalpha(img.getchannel("A") if img.mode == "RGBA" else 255)
    return out
