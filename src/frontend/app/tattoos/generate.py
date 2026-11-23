"""Procedural tattoos: a style + a seed → a few placed layers (bands, shapes, lettering) for a limb tile.
Every layer stays editable afterwards (position, size, seed, colour…), and the same seed gives the same result."""
from __future__ import annotations

import random
import uuid

from . import motifs as M
from . import render as R

# Where things are on the tiles (px, tile space) — see render.ZONES.
ARM = R.ZONES["arm"]
LEG = {**R.ZONES["leg"], "all": (104, 242)}     # whole-leg designs: knee down (tape and shorts above)
# The designs were drawn for a limb 128 px round; the body's limbs are narrower once widened (render.LIMBS
# xscale), so sizes shrink by this much to keep their proportions.
K = {limb: 1 / spec["xscale"] for limb, spec in R.LIMBS.items()}


def _layer(mid: str, rng: random.Random, limb: str, **kw) -> dict:
    """`x` is given as if the front of the limb were at 64 (as the designs were drawn)."""
    mo = M.get(mid)
    k = 1.0 if mo.wrap else K[limb]
    w = kw.pop("w", mo.size) * k
    h = kw.pop("h", None)
    h = w / mo.aspect if h is None else h * k
    params = kw.pop("params", {})
    x = R.LIMBS[limb]["front"] + (kw.pop("x", 64) - 64)
    raw = {"id": uuid.uuid4().hex[:8], "motif": mid, "limb": limb, "seed": rng.randrange(1, 99999), "params": params,
           "w": w, "h": h, "wrap": mo.wrap, "x": x, "y": 70, **kw}
    return R.clean_layer(raw)


def _tribal_sleeve(rng, limb, text):
    a, b = ARM["all"] if limb == "arm" else LEG["all"]
    out, y = [], a
    while y < b - 10:
        h = rng.choice([14, 18, 22, 26])
        kind = rng.choice(["gen:tribal_band", "gen:tribal_band", "gen:geo_sleeve", "gen:armband"])
        if kind == "gen:tribal_band":
            out.append(_layer(kind, rng, limb, h=h, y=y + h / 2, params={"cells": rng.randint(5, 10), "rows": 1 if h < 20 else 2}))
        elif kind == "gen:armband":
            h = 8
            out.append(_layer(kind, rng, limb, h=h, y=y + h / 2, params={"lines": rng.randint(1, 3)}))
        else:
            h = max(h, 22)
            out.append(_layer(kind, rng, limb, h=h, y=y + h / 2, params={"rows": rng.randint(3, 6), "cells": rng.randint(5, 10)}))
        y += h + rng.randint(1, 4)
    return out


def _forearm_geo(rng, limb, text):
    a, b = ARM["fore"] if limb == "arm" else LEG["shin"]
    h = (b - a) * rng.uniform(.7, 1.0)
    return [_layer("gen:geo_sleeve", rng, limb, h=h, y=(a + b) / 2, params={"rows": rng.randint(6, 12), "cells": rng.randint(6, 10), "density": rng.choice([.5, .8])})]


def _celtic_band(rng, limb, text):
    a, b = ARM["fore"] if limb == "arm" else LEG["shin"]
    y = (a + b) / 2
    return [_layer("gen:armband", rng, limb, h=7, y=y - 16, params={"lines": 2}), _layer("gen:rope", rng, limb, h=28, y=y,
            params={"turns": rng.randint(4, 8), "strands": rng.choice(["2", "3"])}), _layer("gen:armband", rng, limb, h=7, y=y + 16, params={"lines": 2})]


def _blackwork_piece(rng, limb, text):
    a, b = ARM["upper"] if limb == "arm" else LEG["thigh"]
    h = (b - a) * rng.uniform(.9, 1.1)
    return [_layer("gen:tribal_shape", rng, limb, w=h * .62, h=h, x=rng.choice([30, 64, 98]), y=(a + b) / 2,
                   params={"spikes": rng.randint(4, 9), "curl": rng.random(), "hollow": rng.random()})]


def _mandala_patch(rng, limb, text):
    a, b = ARM["fore"] if limb == "arm" else LEG["shin"]
    s = min(b - a, 64)
    return [_layer("gen:mandala", rng, limb, w=s, h=s, x=rng.choice([40, 64, 90]), y=(a + b) / 2,
                   params={"layers": rng.randint(3, 6), "petals": rng.choice([8, 12, 16, 20])})]


def _constellation(rng, limb, text):
    a, b = ARM["fore"] if limb == "arm" else LEG["shin"]
    return [_layer("gen:scatter", rng, limb, w=90, h=(b - a), x=64, y=(a + b) / 2, params={"count": rng.randint(8, 22), "shape": rng.choice(["stars", "crosses", "dots"])})]


def _lettering(rng, limb, text):
    a, b = ARM["fore"] if limb == "arm" else LEG["shin"]
    txt = (text or rng.choice(["FAMILY", "LOYALTY", "HONOUR", "BROTHERS", "ALWAYS", "FORWARD"]))[:20]
    return [_layer("gen:text", rng, limb, w=88, h=24, x=64, y=(a + b) / 2, params={"text": txt, "font": rng.choice(list(M.TEXT_FONTS)), "tilt": rng.choice([0, -8, 8])})]


def _koru_fern(rng, limb, text):
    a, b = ARM["fore"] if limb == "arm" else LEG["shin"]
    y = (a + b) / 2
    out = [_layer("bank:fern", rng, limb, w=26, h=58, x=64, y=y), _layer("bank:koru", rng, limb, w=30, h=30, x=36, y=y + 8, flip=True), _layer("bank:koru", rng, limb, w=30, h=30, x=92, y=y + 8)]
    return out


def _maori_band(rng, limb, text):
    a, b = ARM["fore"] if limb == "arm" else LEG["shin"]
    y = (a + b) / 2
    return [_layer("gen:armband", rng, limb, h=7, y=y - 24, params={"lines": 2}),
            _layer("gen:teeth_band", rng, limb, h=26, y=y - 6, params={"teeth": rng.randint(6, 12), "rows": 2}),
            _layer("gen:wave_band", rng, limb, h=24, y=y + 22, params={"waves": rng.randint(4, 8)}),
            _layer("gen:armband", rng, limb, h=7, y=y + 40, params={"lines": 2})]


def _rugby_pride(rng, limb, text):
    a, b = ARM["fore"] if limb == "arm" else LEG["shin"]
    y = (a + b) / 2
    glyph = rng.choice(["ball_tilted", "trophy", "boot", "kick", "shield_crest", "jersey", "posts", "rugby_ball"])
    out = [_layer(f"bank:{glyph}", rng, limb, x=64, y=y - 10)]
    out.append(_layer("gen:text", rng, limb, w=84, h=18, x=64, y=y + 30, params={"text": (text or rng.choice(["FORWARD", "TRY TIME", "BROTHERS", "FOR THE JERSEY", "NO. 8", "FRONT ROW"]))[:20], "font": rng.choice(["block", "slab", "brush"]), "tilt": 0}))
    return out


def _tribal_emblem(rng, limb, text):
    a, b = ARM["upper"] if limb == "arm" else LEG["thigh"]
    a2, b2 = ARM["fore"] if limb == "arm" else LEG["shin"]
    glyph = rng.choice(["tribal_turtle", "tribal_wing", "hei_matau", "tribal_star", "tribal_flame", "tribal_cross", "triskele", "triple_koru", "tribal_fan", "tribal_spear"])
    mo = M.get(f"bank:{glyph}")
    w = (b2 - a2) * .95 * min(1.0, mo.aspect) if mo.aspect < 1 else min(100, (b2 - a2) * 1.4)
    return [_layer(f"bank:{glyph}", rng, limb, w=w, h=w / mo.aspect, x=64, y=(a2 + b2) / 2),
            _layer("gen:thorn_band", rng, limb, h=16, y=b2 + 4, params={"thorns": rng.randint(6, 12)})]


STYLES = {
    "tribal_sleeve": ("Tribal sleeve", _tribal_sleeve, "stacked polynesian-style bands, shoulder to wrist"),
    "forearm_geo": ("Geometric forearm", _forearm_geo, "rows of triangles, diamonds, chevrons and dots"),
    "celtic_band": ("Celtic rope band", _celtic_band, "a braid between two lines"),
    "blackwork_piece": ("Blackwork piece", _blackwork_piece, "one solid symmetrical tribal shape"),
    "mandala_patch": ("Mandala", _mandala_patch, "a round ornament"),
    "constellation": ("Constellation", _constellation, "scattered stars, crosses or dots"),
    "lettering": ("Lettering", _lettering, "a word in a tattoo hand"),
    "maori_band": ("Maori band", _maori_band, "teeth, waves and lines wrapped round the forearm"),
    "rugby_pride": ("Rugby pride", _rugby_pride, "a rugby emblem (ball, boot, cup, posts, crest) over a slogan"),
    "tribal_emblem": ("Tribal emblem", _tribal_emblem, "one big blackwork / polynesian emblem over a thorn band"),
    "koru_fern": ("Koru and fern", _koru_fern, "maori-inspired spirals around a silver fern"),
}


def catalogue() -> list[dict]:
    return [{"id": k, "name": v[0], "hint": v[2]} for k, v in STYLES.items()]


def generate(style: str, seed: int = 1, limb: str = "arm", text: str = "", side: str = "both") -> list[dict]:
    if style == "random":
        style = random.Random(seed).choice(list(STYLES))
    if style not in STYLES:
        raise ValueError(f"unknown style '{style}'")
    rng = random.Random(seed * 7919 + 13)
    layers = STYLES[style][1](rng, limb if limb in R.LIMBS else "arm", text)
    for L in layers:
        L["side"] = side if side in ("a", "b", "both") else "both"
    return layers
