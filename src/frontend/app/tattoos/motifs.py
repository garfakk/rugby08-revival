"""
Tattoo motifs: every motif draws an ink mask (PIL "L", 255 = ink) of any size.

Two families, one interface:
  * bank glyphs  — hand-built vector designs (cross, anchor, silver fern, koru…), fixed look;
  * generators   — procedural designs (tribal bands, rope, mandala, sleeves…) driven by a seed and a few
    sliders, so "another one" is one click.
A motif is `Motif(id, name, cat, aspect, params, draw)`; `draw(pen, rng, p)` paints on a `Pen` whose
coordinates are normalised to [-1, 1] on both axes (x right, y down), whatever the pixel size.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Callable

from PIL import Image, ImageDraw, ImageFont

SS = 3                                   # supersampling
FONTS = Path(__file__).resolve().parents[3] / "assets" / "fonts"
TEXT_FONTS = {"script": "tattoo/Yellowtail-Regular.ttf", "block": "BebasNeue-Regular.ttf", "serif": "tattoo/PlayfairDisplaySC-Black.ttf",
              "brush": "tattoo/PermanentMarker-Regular.ttf", "rock": "tattoo/RockSalt-Regular.ttf", "slab": "tattoo/Bevan-Regular.ttf"}


class Pen:
    def __init__(self, w: int, h: int):
        self.w, self.h = max(2, int(w)), max(2, int(h))
        self.W, self.H = self.w * SS, self.h * SS
        self.im = Image.new("L", (self.W, self.H), 0)
        self.d = ImageDraw.Draw(self.im)
        self.u = min(self.W, self.H) / 2          # one normalised unit of line width, in pixels

    def px(self, x: float, y: float) -> tuple[float, float]:
        return ((x + 1) * 0.5 * self.W, (y + 1) * 0.5 * self.H)

    def pts(self, pts) -> list[tuple[float, float]]:
        return [self.px(x, y) for x, y in pts]

    def poly(self, pts, ink: int = 255) -> None:
        self.d.polygon(self.pts(pts), fill=ink)

    def stroke(self, pts, t: float = 0.06, closed: bool = False, ink: int = 255) -> None:
        p = self.pts(list(pts) + ([pts[0]] if closed else []))
        w = max(1, round(t * self.u))
        self.d.line(p, fill=ink, width=w, joint="curve")
        r = w / 2
        for x, y in (p if len(p) < 400 else p[::2]):      # round joints / caps
            self.d.ellipse((x - r, y - r, x + r, y + r), fill=ink)

    def ellipse(self, cx, cy, rx, ry=None, t: float | None = None, ink: int = 255) -> None:
        ry = rx if ry is None else ry
        x0, y0 = self.px(cx - rx, cy - ry)
        x1, y1 = self.px(cx + rx, cy + ry)
        if t is None:
            self.d.ellipse((x0, y0, x1, y1), fill=ink)
        else:
            self.d.ellipse((x0, y0, x1, y1), outline=ink, width=max(1, round(t * self.u)))

    def finish(self) -> Image.Image:
        return self.im.resize((self.w, self.h), Image.LANCZOS)


def bez(p0, p1, p2, p3, n: int = 18):
    out = []
    for i in range(n + 1):
        t = i / n
        a, b, c, d = (1 - t) ** 3, 3 * (1 - t) ** 2 * t, 3 * (1 - t) * t * t, t ** 3
        out.append((a * p0[0] + b * p1[0] + c * p2[0] + d * p3[0], a * p0[1] + b * p1[1] + c * p2[1] + d * p3[1]))
    return out


def circ(cx, cy, r, a0=0.0, a1=360.0, n: int = 48, ry=None):
    ry = r if ry is None else ry
    return [(cx + r * math.cos(math.radians(a0 + (a1 - a0) * i / n)), cy + ry * math.sin(math.radians(a0 + (a1 - a0) * i / n)))
            for i in range(n + 1)]


def rot(pts, deg, cx=0.0, cy=0.0):
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in pts]


def spiral(cx, cy, r0, r1, turns, a0=0.0, n=90, cw=True):
    sg = 1 if cw else -1
    return [(cx + (r0 + (r1 - r0) * i / n) * math.cos(math.radians(a0 + sg * 360 * turns * i / n)),
             cy + (r0 + (r1 - r0) * i / n) * math.sin(math.radians(a0 + sg * 360 * turns * i / n))) for i in range(n + 1)]


def mirror_x(pts):
    return [(-x, y) for x, y in pts]


# ── motif registry ───────────────────────────────────────────────────────────
@dataclass
class Motif:
    id: str
    name: str
    cat: str
    draw: Callable
    aspect: float = 1.0                  # width / height of its natural box
    params: list = field(default_factory=list)   # [{"k","label","type":"range|choice|text","min","max","step","default","options"}]
    kind: str = "bank"                   # bank | gen
    size: int = 40                       # natural width on a limb tile, px
    tags: str = ""
    wrap: bool = False                   # tiles around the limb (full-width bands)
    place: dict | None = None            # preset spot: {"limb", "y0", "y1"} (tile px) — fills that part of the limb

    def defaults(self) -> dict:
        return {p["k"]: p["default"] for p in self.params}

    def meta(self) -> dict:
        return {"id": f"{self.kind}:{self.id}", "name": self.name, "cat": self.cat, "aspect": self.aspect, "kind": self.kind,
                "size": self.size, "params": self.params, "tags": self.tags, "wrap": self.wrap, "place": self.place}


REG: dict[str, Motif] = {}


def reg(id, name, cat, aspect=1.0, params=None, kind="bank", size=40, tags="", wrap=False, place=None):
    def deco(fn):
        REG[f"{kind}:{id}"] = Motif(id, name, cat, fn, aspect, params or [], kind, size, tags, wrap, place)
        return fn
    return deco


def R(k, label, lo, hi, default, step=None):
    return {"k": k, "label": label, "type": "range", "min": lo, "max": hi, "default": default,
            "step": step if step is not None else (1 if isinstance(default, int) else 0.05)}


def C(k, label, options, default):
    return {"k": k, "label": label, "type": "choice", "options": options, "default": default}


# ── bank glyphs ──────────────────────────────────────────────────────────────
@reg("cross", "Cross", "Symbols", 0.62, size=34, tags="christian latin religion")
def _cross(pen, rng, p):
    pen.poly([(-.14, -1), (.14, -1), (.14, -.5), (.9, -.5), (.9, -.2), (.14, -.2), (.14, 1), (-.14, 1), (-.14, -.2), (-.9, -.2), (-.9, -.5), (-.14, -.5)])
    pen.poly([(-.06, -.85), (.06, -.85), (.06, .85), (-.06, .85)], 0)


@reg("celtic_cross", "Celtic cross", "Symbols", 0.85, size=40, tags="celtic irish scottish welsh")
def _celtic(pen, rng, p):
    pen.poly([(-.12, -1), (.12, -1), (.12, -.4), (.55, -.4), (.55, -.16), (.12, -.16), (.12, 1), (-.12, 1), (-.12, -.16), (-.55, -.16), (-.55, -.4), (-.12, -.4)])
    pen.ellipse(0, -.28, .68, .54, t=.09)
    pen.stroke([(-.5, 0.62), (0.5, 0.62)], .05)
    pen.stroke([(-.38, .32), (.38, .32)], .05)


def _star(pen, n, r1, r0, a0=-90, t=None, ink=255):
    pts = []
    for i in range(2 * n):
        r = r1 if i % 2 == 0 else r0
        a = math.radians(a0 + 180 * i / n)
        pts.append((r * math.cos(a), r * math.sin(a)))
    if t is None:
        pen.poly(pts, ink)
    else:
        pen.stroke(pts, t, closed=True, ink=ink)


@reg("star", "Star", "Symbols", 1, size=26, tags="stars")
def _star5(pen, rng, p):
    _star(pen, 5, 1, .42)


@reg("star_outline", "Star outline", "Symbols", 1, size=26, tags="stars")
def _star5o(pen, rng, p):
    _star(pen, 5, .95, .4, t=.12)


@reg("nautical_star", "Nautical star", "Symbols", 1, size=30, tags="sailor compass")
def _nstar(pen, rng, p):
    _star(pen, 4, 1, .2)
    _star(pen, 4, .62, .18, a0=-45)
    pen.ellipse(0, 0, .14, ink=0)
    pen.ellipse(0, 0, .07)


@reg("compass", "Compass rose", "Symbols", 1, size=44, tags="sailor navigation")
def _compass(pen, rng, p):
    pen.ellipse(0, 0, .72, t=.06)
    pen.ellipse(0, 0, .6, t=.03)
    _star(pen, 4, 1, .16)
    _star(pen, 4, .62, .14, a0=-45)
    pen.ellipse(0, 0, .1, ink=0)
    pen.ellipse(0, 0, .05)


@reg("anchor", "Anchor", "Symbols", .8, size=38, tags="sailor sea")
def _anchor(pen, rng, p):
    pen.ellipse(0, -.82, .15, t=.09)
    pen.stroke([(0, -.67), (0, .82)], .1)
    pen.stroke([(-.4, -.45), (.4, -.45)], .09)
    pen.stroke(circ(0, .12, .8, 20, 160, 30), .1)
    pen.poly([(-.82, .38), (-.62, .24), (-.5, .52)])
    pen.poly([(.82, .38), (.62, .24), (.5, .52)])


@reg("heart", "Heart", "Symbols", 1.05, size=28, tags="love")
def _heart(pen, rng, p):
    pts = bez((0, .9), (-1.3, -.1), (-.6, -1.0), (0, -.35), 20) + bez((0, -.35), (.6, -1.0), (1.3, -.1), (0, .9), 20)
    pen.poly(pts)


@reg("lightning", "Lightning bolt", "Symbols", .55, size=26)
def _bolt(pen, rng, p):
    pen.poly([(.35, -1), (-.55, .12), (-.05, .12), (-.4, 1), (.6, -.2), (.08, -.2)])


@reg("wings", "Wings", "Symbols", 1.7, size=64, tags="angel eagle")
def _wings(pen, rng, p):
    n = 10
    for i in range(n):
        f = i / (n - 1)
        a = math.radians(-82 + 112 * f)
        ln = (.5 + .5 * math.sin(math.pi * min(1.0, f * .9 + .12))) * 1.0
        w = .075 + .02 * f
        for sg in (-1, 1):
            bx, by = sg * .07, -.05 + .06 * f
            dx, dy = sg * math.cos(a), math.sin(a)
            nx, ny = -dy, dx
            pts = [(bx, by)]
            for t, k in ((.3, 1), (.7, .95), (1.0, 0)):
                pts.append((bx + dx * ln * t + nx * w * k, by + dy * ln * t + ny * w * k))
            for t, k in ((.7, .95), (.3, 1)):
                pts.append((bx + dx * ln * t - nx * w * k, by + dy * ln * t - ny * w * k))
            pen.poly(pts)
            pen.stroke([(bx + dx * ln * .12, by + dy * ln * .12), (bx + dx * ln * .9, by + dy * ln * .9)], .02, ink=0)
    pen.ellipse(0, .0, .09)


@reg("fern", "Silver fern", "Rugby", .5, size=44, tags="new zealand all blacks maori silver")
def _fern(pen, rng, p):
    stem = bez((0, 1), (-.25, .4), (-.2, -.3), (.18, -.95), 40)
    pen.stroke(stem, .06)
    for i in range(3, len(stem) - 3, 3):
        x, y = stem[i]
        f = i / len(stem)
        ln = (.82 - .52 * f) * (1 if i > 5 else .5)
        tx, ty = stem[min(i + 1, len(stem) - 1)][0] - stem[i - 1][0], stem[min(i + 1, len(stem) - 1)][1] - stem[i - 1][1]
        ang = math.atan2(ty, tx)
        for sg in (-1, 1):
            a = ang + sg * math.radians(62 - 10 * f)
            pts = bez((x, y), (x + .3 * ln * math.cos(a), y + .3 * ln * math.sin(a) - .05), (x + .75 * ln * math.cos(a), y + .75 * ln * math.sin(a) + .04),
                      (x + ln * math.cos(a), y + ln * math.sin(a) + .1 * ln), 10)
            pen.stroke(pts, .075 * (1 - .5 * f))


@reg("koru", "Koru spiral", "Tribal", 1, size=34, tags="maori fern spiral new zealand")
def _koru(pen, rng, p):
    pen.stroke(spiral(0, 0, .12, .78, 1.55, a0=200, cw=False), .16)
    pen.stroke(bez((.78 * math.cos(math.radians(200 - 360 * 1.55)), .78 * math.sin(math.radians(200 - 360 * 1.55))), (.5, .95), (-.3, .95), (-.9, .55), 20), .1)
    pen.ellipse(0, 0, .2)


@reg("shamrock", "Shamrock", "Rugby", 1, size=34, tags="ireland irish clover")
def _shamrock(pen, rng, p):
    for a in (90, 210, 330):
        leaf = [(0.0, 0.0)] + bez((0, 0), (-.5, -.35), (-.62, -.85), (0, -.55), 14) + bez((0, -.55), (.62, -.85), (.5, -.35), (0, 0), 14)
        pen.poly(rot(leaf, a - 90 + 180, 0, 0)[::1])
    pen.stroke(bez((0, .1), (.05, .5), (.2, .75), (.45, .95), 16), .09)


@reg("sun", "Sun", "Symbols", 1, size=36, tags="sol tribal")
def _sun(pen, rng, p):
    pen.ellipse(0, 0, .42)
    pen.ellipse(0, 0, .3, ink=0)
    pen.ellipse(0, 0, .22)
    for i in range(16):
        a = 360 * i / 16
        l = 1 if i % 2 == 0 else .78
        pen.poly(rot([(-.07, -.55), (0, -l), (.07, -.55)], a))


@reg("crown", "Crown", "Symbols", 1.2, size=34, tags="king")
def _crown(pen, rng, p):
    pen.poly([(-.9, .6), (-.9, -.45), (-.45, .05), (0, -.8), (.45, .05), (.9, -.45), (.9, .6)])
    pen.poly([(-.78, .5), (.78, .5), (.78, .42), (-.78, .42)], 0)
    for x, y in ((-.9, -.55), (0, -.9), (.9, -.55)):
        pen.ellipse(x, y, .1)
    pen.poly([(-.9, .66), (.9, .66), (.9, .86), (-.9, .86)])


@reg("dagger", "Dagger", "Symbols", .32, size=44, tags="sword knife")
def _dagger(pen, rng, p):
    pen.poly([(0, -1), (.2, -.55), (.2, .15), (-.2, .15), (-.2, -.55)])
    pen.stroke([(0, -.85), (0, .1)], .05, ink=0)
    pen.poly([(-.7, .15), (.7, .15), (.7, .3), (-.7, .3)])
    pen.poly([(-.1, .3), (.1, .3), (.1, .8), (-.1, .8)])
    pen.ellipse(0, .9, .14)


@reg("arrow", "Arrow", "Symbols", .25, size=46)
def _arrow(pen, rng, p):
    pen.stroke([(0, -.85), (0, .95)], .1)
    pen.poly([(0, -1), (.5, -.45), (0, -.6), (-.5, -.45)])
    for y in (.68, .85):
        pen.stroke([(0, y), (.4, y - .22)], .07)
        pen.stroke([(0, y), (-.4, y - .22)], .07)


@reg("laurel", "Laurel wreath", "Symbols", 1, size=44, tags="victory champion")
def _laurel(pen, rng, p):
    for sg in (-1, 1):
        arc = circ(0, 0, .8, 105 if sg < 0 else 75, 255 if sg < 0 else -75, 30)
        pen.stroke(arc, .05)
        for i in range(2, len(arc) - 1, 2):
            x, y = arc[i]
            a = math.atan2(y, x) + sg * math.pi / 2
            for k in (-1, 1):
                aa = a + k * .8 * sg
                pen.poly([(x, y), (x + .2 * math.cos(aa - .4), y + .2 * math.sin(aa - .4)), (x + .3 * math.cos(aa), y + .3 * math.sin(aa)),
                          (x + .2 * math.cos(aa + .4), y + .2 * math.sin(aa + .4))])


@reg("skull", "Skull", "Symbols", .9, size=34, tags="death")
def _skull(pen, rng, p):
    pen.ellipse(0, -.2, .8, .72)
    pen.poly([(-.45, .3), (.45, .3), (.4, .85), (-.4, .85)])
    for sx in (-1, 1):
        pen.ellipse(.33 * sx, -.15, .21, .24, ink=0)
    pen.poly([(0, .08), (-.1, .3), (.1, .3)], 0)
    for x in (-.24, -.08, .08, .24):
        pen.stroke([(x, .5), (x, .85)], .05, ink=0)


@reg("rugby_ball", "Rugby ball", "Rugby", 1.7, size=44, tags="ball")
def _ball(pen, rng, p):
    pen.ellipse(0, 0, .97, .6, t=.1)
    pen.stroke([(-.28, 0), (.28, 0)], .07)
    for x in (-.2, -.1, 0, .1, .2):
        pen.stroke([(x, -.14), (x, .14)], .05)
    pen.stroke(bez((-.97, 0), (-.6, -.2), (-.55, -.2), (-.38, -.3), 10), .05)
    pen.stroke(bez((.97, 0), (.6, -.2), (.55, -.2), (.38, -.3), 10), .05)


@reg("posts", "Rugby posts", "Rugby", .8, size=40, tags="goal h")
def _posts(pen, rng, p):
    pen.stroke([(-.55, -1), (-.55, .3)], .09)
    pen.stroke([(.55, -1), (.55, .3)], .09)
    pen.stroke([(-.55, .1), (.55, .1)], .09)
    pen.stroke([(0, .1), (0, 1)], .1)


@reg("feather", "Feather", "Symbols", .35, size=46, tags="bird native")
def _feather(pen, rng, p):
    spine = bez((.0, 1), (.1, .4), (-.1, -.3), (.05, -1), 30)
    for i in range(2, 28):
        x, y = spine[i]
        f = i / 30
        w = .7 * math.sin(math.pi * min(1, f * 1.05)) ** .8
        pen.poly([(x, y), (x - w, y - .2), (x - w * .8, y - .05)])
        pen.poly([(x, y), (x + w, y - .2), (x + w * .8, y - .05)])
    pen.stroke(spine, .045, ink=0)
    pen.stroke(spine[:8], .05)


@reg("tribal_sun", "Tribal sun", "Tribal", 1, size=44, tags="polynesian samoan")
def _tsun(pen, rng, p):
    pen.ellipse(0, 0, .36)
    pen.ellipse(0, 0, .22, ink=0)
    pen.ellipse(0, 0, .12)
    for i in range(12):
        a = 360 * i / 12
        pen.poly(rot([(-.13, -.45), (-.05, -.78), (0, -1), (.05, -.78), (.13, -.45)], a))
        pen.poly(rot([(-.04, -.5), (0, -.7), (.04, -.5)], a), 0)


@reg("moon_stars", "Moon and stars", "Symbols", 1, size=34, tags="night")
def _moon(pen, rng, p):
    pen.ellipse(-.1, 0, .85)
    pen.ellipse(.22, -.1, .72, ink=0)
    _star(pen, 5, .22, .09)
    pen.ellipse(0, 0, 0.0)


# ── procedural generators ────────────────────────────────────────────────────
@reg("tribal_band", "Tribal band", "Bands", 3.2, kind="gen", size=128, wrap=True, tags="polynesian maori samoan armband",
     params=[R("cells", "Repeats", 3, 14, 7), R("rows", "Rows", 1, 3, 2), R("thick", "Line weight", .4, 1.8, 1.0), R("fill", "Solid fill", 0, 1, .55)])
def _tribal_band(pen, rng, p):
    n, rows = int(p["cells"]), int(p["rows"])
    t = .05 * p["thick"]
    rowh = 2 / rows
    for r in range(rows):
        y0 = -1 + r * rowh
        yc, hh = y0 + rowh / 2, rowh / 2 * .86
        kind = rng.choice(["teeth", "spear", "wave", "diamond", "koru", "zig"])
        pen.stroke([(-1, y0 + rowh * .06), (1, y0 + rowh * .06)], t * 1.2)
        pen.stroke([(-1, y0 + rowh * .94), (1, y0 + rowh * .94)], t * 1.2)
        for i in range(n):
            cx, cw = -1 + (i + .5) * 2 / n, 1 / n * .9
            solid = rng.random() < p["fill"]
            if kind == "teeth":
                pen.poly([(cx - cw, yc - hh), (cx + cw, yc - hh), (cx, yc + hh * .1)])
                pen.poly([(cx - cw * .7, yc + hh), (cx + cw * .7, yc + hh), (cx, yc + hh * .25)])
            elif kind == "spear":
                pen.poly([(cx - cw * .6, yc), (cx, yc - hh), (cx + cw * .6, yc), (cx, yc + hh)])
                pen.poly([(cx - cw * .25, yc), (cx, yc - hh * .5), (cx + cw * .25, yc), (cx, yc + hh * .5)], 0 if solid else 255)
            elif kind == "wave":
                pen.stroke([(cx + cw * (j / 8 * 2 - 1), yc + hh * .7 * math.sin(math.pi * (j / 8 * 2 - 1) * 1.0)) for j in range(9)], t * 1.4)
                pen.ellipse(cx, yc, cw * .22 * (1 if solid else .01) + .001)
            elif kind == "diamond":
                pen.poly([(cx - cw, yc), (cx, yc - hh), (cx + cw, yc), (cx, yc + hh)])
                pen.poly([(cx - cw * .55, yc), (cx, yc - hh * .55), (cx + cw * .55, yc), (cx, yc + hh * .55)], 0)
                if solid:
                    pen.ellipse(cx, yc, cw * .28 * pen.W / pen.H * .5 + .02)
            elif kind == "koru":
                pts = spiral(cx, yc, .02, hh * .7, 1.5, a0=rng.choice([0, 180]), n=40)
                pen.stroke(pts, t * 2.2 if solid else t * 1.4)
            else:
                pen.stroke([(cx - cw, yc + hh * .8), (cx, yc - hh * .8), (cx + cw, yc + hh * .8)], t * 1.6)
        if kind == "zig":
            pass


@reg("rope", "Rope / braid", "Bands", 3.5, kind="gen", size=128, wrap=True, tags="celtic braid twist",
     params=[R("turns", "Twists", 2, 12, 6), R("thick", "Strand width", .5, 1.8, 1.0), C("strands", "Strands", ["2", "3"], "2")])
def _rope(pen, rng, p):
    n = int(p["turns"])
    ns = int(p["strands"])
    t = .27 / (1 + .4 * (ns - 2)) * p["thick"]
    amp = .72
    steps = 400
    xs = [-1 + 2 * i / steps for i in range(steps + 1)]
    def y(k, x):
        return amp * math.sin(math.pi * n * (x + 1) + 2 * math.pi * k / ns)
    # order strands by depth: depth_k(x) = cos(phase) — higher is in front
    segs = []
    for i in range(steps):
        x0, x1 = xs[i], xs[i + 1]
        xm = (x0 + x1) / 2
        order = sorted(range(ns), key=lambda k: math.cos(math.pi * n * (xm + 1) + 2 * math.pi * k / ns))
        segs.append((x0, x1, order))
    for i in range(0, steps, 4):                   # blocks of 4 steps share one order
        x0, x1, order = segs[i]
        xa, xb = xs[i], xs[min(steps, i + 5)]
        for k in order:
            pts = [(x, y(k, x)) for x in [xa + (xb - xa) * j / 5 for j in range(6)]]
            pen.stroke(pts, t * 1.45, ink=0)
            pen.stroke(pts, t)


@reg("barbed_wire", "Barbed wire", "Bands", 4.2, kind="gen", size=128, wrap=True, tags="prison",
     params=[R("barbs", "Barbs", 2, 10, 5), R("thick", "Weight", .5, 1.8, 1.0)])
def _barbed(pen, rng, p):
    n = int(p["barbs"])
    t = .1 * p["thick"]
    for k in (0, 1):
        pen.stroke([(x, .22 * math.sin(math.pi * n * (x + 1) * 1.0 + math.pi * k)) for x in [-1 + 2 * i / 240 for i in range(241)]], t)
    for i in range(n):
        cx = -1 + (i + .25) * 2 / n
        for sg in (-1, 1):
            pen.stroke([(cx - .035, -.0), (cx - .035 + .07 * sg, .62 * sg)], t * .8)
            pen.stroke([(cx + .13, .0), (cx + .13 - .07 * sg, -.62 * sg)], t * .8)


@reg("armband", "Armband lines", "Bands", 8, kind="gen", size=128, wrap=True, tags="ring simple",
     params=[R("lines", "Lines", 1, 5, 2), R("thick", "Weight", .4, 2, 1.0), C("style", "Style", ["solid", "dotted", "mixed"], "solid")])
def _armband(pen, rng, p):
    n = int(p["lines"])
    for i in range(n):
        y = 0 if n == 1 else -.7 + 1.4 * i / (n - 1)
        th = (.55 if i % 2 else 1.0) * p["thick"] * .12 * 1.4
        st = p["style"] if p["style"] != "mixed" else ("dotted" if i % 2 else "solid")
        if st == "solid":
            pen.stroke([(-1, y), (1, y)], th)
        else:
            m = 40
            for j in range(m):
                pen.ellipse(-1 + (j + .5) * 2 / m, y, th * .5 * pen.W / pen.H * .02 + .015 + th * .08, th * .2 + .02)


@reg("geo_sleeve", "Geometric sleeve", "Bands", .62, kind="gen", size=128, wrap=True, tags="sleeve rows pattern forearm",
     params=[R("rows", "Rows", 3, 14, 8), R("cells", "Repeats", 4, 14, 8), R("thick", "Weight", .5, 1.8, 1.0), R("density", "Density", .2, 1, .7)])
def _geo_sleeve(pen, rng, p):
    rows, n, t = int(p["rows"]), int(p["cells"]), .04 * p["thick"]
    y = -1.0
    while y < 1 - .05:
        kind = rng.choice(["tri", "dots", "zig", "line", "diamond", "chev", "gap", "gap"] if p["density"] < .6 else ["tri", "dots", "zig", "line", "diamond", "chev", "tri"])
        hh = rng.uniform(.5, 1.0) * 2 / rows * 1.4
        if y + hh > 1:
            hh = 1 - y
        if hh < .05:
            break
        yc = y + hh / 2
        if kind == "tri":
            for i in range(n):
                cx, cw = -1 + (i + .5) * 2 / n, 1 / n
                pen.poly([(cx - cw * .9, y), (cx + cw * .9, y), (cx, y + hh * .95)])
        elif kind == "dots":
            m = n * 2
            for i in range(m):
                pen.ellipse(-1 + (i + .5) * 2 / m, yc, hh * .17 * pen.H / pen.W + .004, hh * .17)
        elif kind == "zig":
            pts = [(-1 + 2 * i / (n * 2), y + hh * (.15 + .7 * (i % 2))) for i in range(n * 2 + 1)]
            pen.stroke(pts, t * 1.4)
        elif kind == "line":
            pen.stroke([(-1, yc), (1, yc)], t * rng.uniform(.9, 2.2))
        elif kind == "diamond":
            for i in range(n):
                cx, cw = -1 + (i + .5) * 2 / n, 1 / n * .85
                pen.poly([(cx - cw, yc), (cx, y), (cx + cw, yc), (cx, y + hh)])
                pen.poly([(cx - cw * .5, yc), (cx, y + hh * .28), (cx + cw * .5, yc), (cx, y + hh * .72)], 0)
        elif kind == "chev":
            for i in range(n):
                cx, cw = -1 + (i + .5) * 2 / n, 1 / n * .9
                pen.stroke([(cx - cw, y + hh * .15), (cx, y + hh * .85), (cx + cw, y + hh * .15)], t * 1.5)
        y += hh + rng.uniform(.015, .05)


@reg("mandala", "Mandala", "Ornament", 1, kind="gen", size=56, tags="radial flower geometric",
     params=[R("layers", "Layers", 2, 7, 4), R("petals", "Petals", 6, 24, 12), R("thick", "Weight", .5, 1.6, 1.0)])
def _mandala(pen, rng, p):
    n, layers, t = int(p["petals"]), int(p["layers"]), .035 * p["thick"]
    pen.ellipse(0, 0, .08)
    for L in range(layers):
        r0, r1 = .1 + .85 * L / layers, .1 + .85 * (L + 1) / layers
        kind = rng.choice(["petal", "tri", "dots", "ring", "arc"])
        off = rng.choice([0, 180 / n])
        pen.ellipse(0, 0, r1, t=t)
        for i in range(n):
            a = 360 * i / n + off
            if kind == "petal":
                w = (r1 - r0) * .45
                pen.stroke(rot(bez((0, -r0), (-w * 2, -(r0 + r1) / 2), (-w, -r1 + .02), (0, -r1), 12) + bez((0, -r1), (w, -r1 + .02), (w * 2, -(r0 + r1) / 2), (0, -r0), 12), a), t * 1.2)
            elif kind == "tri":
                pen.poly(rot([(-.07 * (r1 + .3), -r0), (0, -r1), (.07 * (r1 + .3), -r0)], a))
            elif kind == "dots":
                pen.poly(rot([(0, -(r0 + r1) / 2 - .03), (.03, -(r0 + r1) / 2), (0, -(r0 + r1) / 2 + .03), (-.03, -(r0 + r1) / 2)], a))
                pen.ellipse(0, 0, 0)
                x, y = rot([(0, -(r0 + r1) / 2)], a)[0]
                pen.ellipse(x, y, .035 + .01 * L)
            elif kind == "arc":
                pen.stroke(rot(circ(0, -(r0 + r1) / 2, (r1 - r0) * .3, 200, 340, 8), a), t)
            else:
                pen.stroke(rot([(0, -r0), (0, -r1)], a), t * .7)


@reg("tribal_shape", "Tribal shape", "Tribal", 1, kind="gen", size=56, tags="blackwork symmetric shoulder polynesian",
     params=[R("spikes", "Spikes", 3, 12, 6), R("curl", "Curl", 0, 1, .5), R("hollow", "Cut-outs", 0, 1, .5)])
def _tribal_shape(pen, rng, p):
    n = int(p["spikes"])
    pts, hole = [], []
    for i in range(n):                                  # half outline (right side), mirrored for symmetry
        y0, y1 = -.95 + 1.9 * i / n, -.95 + 1.9 * (i + 1) / n
        ym = (y0 + y1) / 2
        w = (.25 + .55 * math.sin(math.pi * (i + .5) / n)) * rng.uniform(.75, 1.2)
        sweep = p["curl"] * rng.uniform(-.25, .35) * (y1 - y0) * n
        pts += [(.07, y0), (.07 + w * .5, y0 + (y1 - y0) * .2), (.07 + w + sweep, ym + (y1 - y0) * .12), (.07 + w * .5, y1 - (y1 - y0) * .15)]
        if rng.random() < p["hollow"]:
            hole.append([(.08 + w * .2, ym - .03), (.08 + w * .55, ym), (.08 + w * .2, ym + .03)])
    out = pts + [(.07, .95)]
    pen.poly(out)
    pen.poly(mirror_x(out))
    pen.poly([(-.07, -1), (.07, -1), (.07, 1), (-.07, 1)])
    for h in hole:
        pen.poly(h, 0)
        pen.poly(mirror_x(h), 0)
    pen.ellipse(0, 0, .09, ink=0)


@reg("dotwork", "Dotwork fade", "Ornament", 1, kind="gen", size=50, tags="stipple shading",
     params=[R("dots", "Dots", 80, 900, 380), C("shape", "Shape", ["disc", "band", "line"], "disc"), R("size", "Dot size", .5, 2, 1.0)])
def _dotwork(pen, rng, p):
    for _ in range(int(p["dots"])):
        x, y = rng.uniform(-1, 1), rng.uniform(-1, 1)
        if p["shape"] == "disc":
            d = math.hypot(x, y)
            keep = rng.random() > d ** 1.4
        elif p["shape"] == "band":
            keep = rng.random() > abs(x) ** 1.3
        else:
            keep = rng.random() > abs(y) ** 1.3
        if keep:
            r = .028 * p["size"] * (1 - .5 * (math.hypot(x, y) if p["shape"] == "disc" else abs(x)))
            pen.ellipse(x, y, r * pen.H / pen.W * 1 + .002, r)


@reg("scatter", "Scattered stars / dots", "Ornament", 1.4, kind="gen", size=60, tags="constellation night",
     params=[R("count", "Count", 3, 40, 14), C("shape", "Shape", ["stars", "dots", "crosses"], "stars"), R("size", "Size", .5, 2, 1.0)])
def _scatter(pen, rng, p):
    pts = []
    for _ in range(int(p["count"]) * 6):
        c = (rng.uniform(-.9, .9), rng.uniform(-.9, .9))
        if all(math.hypot(c[0] - q[0], (c[1] - q[1]) * 1) > .2 for q in pts):
            pts.append(c)
        if len(pts) >= p["count"]:
            break
    for x, y in pts:
        s = rng.uniform(.04, .1) * p["size"]
        if p["shape"] == "dots":
            pen.ellipse(x, y, s * .6 * pen.H / pen.W + .002, s * .6)
        elif p["shape"] == "crosses":
            pen.stroke([(x - s, y), (x + s, y)], .03)
            pen.stroke([(x, y - s), (x, y + s)], .03)
        else:
            pen.poly([(x + (math.cos(a) * (s if i % 2 == 0 else s * .4)) * pen.H / pen.W, y + math.sin(a) * (s if i % 2 == 0 else s * .4))
                      for i, a in enumerate(math.radians(-90 + 36 * i) for i in range(10))])


@reg("text", "Text", "Lettering", 3.0, kind="gen", size=70, tags="name words date numbers roman",
     params=[{"k": "text", "label": "Text", "type": "text", "default": "FAMILY"}, C("font", "Lettering", list(TEXT_FONTS), "script"),
             R("tilt", "Tilt", -20, 20, 0, 1)])
def _text(pen, rng, p):
    txt = str(p.get("text") or " ")[:40]
    path = FONTS / TEXT_FONTS.get(str(p.get("font")), TEXT_FONTS["script"])
    px = int(pen.H * .8)
    f = _font(str(path), px)
    box = pen.d.textbbox((0, 0), txt, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    k = min(pen.W * .96 / max(w, 1), pen.H * .96 / max(h, 1), 3.0)
    f = _font(str(path), max(8, int(px * k)))
    box = pen.d.textbbox((0, 0), txt, font=f)
    w, h = box[2] - box[0], box[3] - box[1]
    layer = Image.new("L", (pen.W, pen.H), 0)
    ImageDraw.Draw(layer).text(((pen.W - w) / 2 - box[0], (pen.H - h) / 2 - box[1]), txt, font=f, fill=255)
    if p.get("tilt"):
        layer = layer.rotate(-float(p["tilt"]), resample=Image.BICUBIC)
    pen.im.paste(255, (0, 0), layer)


@lru_cache(maxsize=64)
def _font(path: str, px: int):
    try:
        return ImageFont.truetype(path, px)
    except OSError:
        return ImageFont.load_default()


# skin marks: soft, small, drawn as normal ink at low opacity by the layer defaults
@reg("freckles", "Freckles", "Skin marks", 1.6, kind="gen", size=44, tags="skin natural",
     params=[R("count", "Count", 10, 160, 60), R("size", "Size", .5, 2, 1.0)])
def _freckles(pen, rng, p):
    for _ in range(int(p["count"])):
        x, y = rng.gauss(0, .45), rng.gauss(0, .4)
        if abs(x) < 1 and abs(y) < 1:
            r = rng.uniform(.02, .055) * p["size"]
            pen.ellipse(x, y, r * pen.H / pen.W + .002, r)


@reg("scar", "Scar", "Skin marks", 2.6, kind="gen", size=40, tags="skin cut stitches",
     params=[R("stitches", "Stitches", 0, 12, 5), R("curve", "Curve", 0, 1, .4)])
def _scar(pen, rng, p):
    c = p["curve"] * .5 * rng.choice([-1, 1])
    line = bez((-.9, .1), (-.4, c), (.4, -c), (.9, -.1), 30)
    pen.stroke(line, .09)
    n = int(p["stitches"])
    for i in range(n):
        x, y = line[int((i + .5) / n * 30)]
        pen.stroke([(x, y - .35), (x, y + .35)], .05)


@reg("birthmark", "Birthmark / bruise", "Skin marks", 1, kind="gen", size=26, tags="skin soft patch",
     params=[R("lobes", "Lobes", 3, 9, 5)])
def _birthmark(pen, rng, p):
    n = int(p["lobes"])
    pen.poly([(math.cos(a) * r, math.sin(a) * r) for a, r in
              ((2 * math.pi * i / 48, .6 + .3 * sum(math.sin(k * 2 * math.pi * i / 48 + ph) / k for k, ph in ((2, 0), (3, 1.3), (n, 2.1)))) for i in range(48))])


# ── rendering ────────────────────────────────────────────────────────────────
def get(motif_id: str) -> Motif:
    m = REG.get(motif_id if ":" in motif_id else f"bank:{motif_id}")
    if m is None:
        raise KeyError(motif_id)
    return m


def clean_params(m: Motif, given: dict | None) -> dict:
    out = m.defaults()
    for spec in m.params:
        if given and spec["k"] in given:
            v = given[spec["k"]]
            if spec["type"] == "range":
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                v = min(max(v, spec["min"]), spec["max"])
                v = int(round(v)) if isinstance(spec["default"], int) else v
            elif spec["type"] == "choice":
                if str(v) not in [str(o) for o in spec["options"]]:
                    continue
                v = str(v)
            else:
                v = str(v)[:60]
            out[spec["k"]] = v
    return out


def draw_mask(motif_id: str, w: int, h: int, params: dict | None = None, seed: int = 1) -> Image.Image:
    """Ink mask (L) of the motif at exactly w×h px."""
    m = get(motif_id)
    pen = Pen(w, h)
    m.draw(pen, random.Random(seed), clean_params(m, params))
    return pen.finish()


def catalogue() -> list[dict]:
    return [m.meta() for m in REG.values()]


from . import motifs_more  # noqa: E402,F401  (registers the tribal and rugby motifs)
from . import motifs_fill  # noqa: E402,F401  (fully inked areas and more shapes)
