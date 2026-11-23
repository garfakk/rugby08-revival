"""Fully inked areas (blackout sleeves, solid bands, fades, negative-space patterns, solid shapes) and a few more
line shapes. Same interface as motifs.py: each draws an ink mask on a Pen in [-1, 1] coordinates.

Bands wrap round the limb (`wrap=True`): their mask spans the whole circumference, so anything repeated across
uses a whole number of repeats and stays seamless where the two edges of the tile meet. The presets (`place`)
fill one part of a limb in one click — they are the same blackout drawing with other defaults."""
from __future__ import annotations

import math

from .motifs import C, R, bez, circ, mirror_x, reg, rot, spiral, _text

EDGES = ["straight", "wavy", "zigzag", "ragged", "flames", "fade"]
CUTS = ["none", "stars", "diamonds", "triangles", "dots", "lines", "koru"]
# where the presets go — render.ZONES (kept here as numbers: render imports motifs)
ARM_ALL, ARM_UPPER, ARM_FORE, ARM_WRIST = (4, 126), (4, 50), (56, 126), (110, 128)
LEG_ALL, LEG_THIGH, LEG_CALF, LEG_KNEE = (38, 244), (38, 102), (132, 244), (96, 136)


def _fill_params(top="straight", bottom="straight", edge=.18, repeats=6, cut="none", cut_size=9.0):
    return [C("top", "Top edge", EDGES, top), C("bottom", "Bottom edge", EDGES, bottom),
            R("edge", "Edge depth", .04, .45, edge), R("repeats", "Edge repeats", 2, 16, repeats),
            C("cut", "Pattern cut out", CUTS, cut), R("cut_size", "Pattern size", 4.0, 22.0, cut_size, .5),
            R("dot", "Dot size", .5, 2.5, 1.0)]


def _periodic_noise(rng, n):
    """A seamless [0, 1] noise along x (whole number of periods round the limb)."""
    waves = [(k, rng.uniform(0, 2 * math.pi), rng.uniform(.3, 1) / k ** .7) for k in range(max(1, n // 2), n * 3)]
    tot = sum(a for _, _, a in waves)
    return lambda x: .5 + .5 * sum(a * math.sin(math.pi * k * (x + 1) + ph) for k, ph, a in waves) / tot


def _edge_offset(style, e, n, noise):
    """Offset (0…e, y units) of an edge inward from the band's border at x."""
    if style == "wavy":
        return lambda x: e * (.5 + .5 * math.cos(math.pi * n * (x + 1)))
    if style == "zigzag":
        return lambda x: e * abs(((n * (x + 1) / 2) % 1) * 2 - 1)
    if style == "ragged":
        return lambda x: e * noise(x)
    if style == "flames":
        def flame(x):
            u = (n * (x + 1) / 2) % 1
            u = u + .12 * math.sin(2 * math.pi * u)
            t = max(0.0, 1 - abs(2 * u - 1)) ** 2.4
            return e * (1 - t)
        return flame
    if style == "fade":
        return lambda x: e
    return lambda x: 0.0


def _blackout(pen, rng, p):
    n = int(p["repeats"])
    e = 2 * float(p["edge"])
    top = _edge_offset(p["top"], e, n, _periodic_noise(rng, n))
    bot = _edge_offset(p["bottom"], e, n, _periodic_noise(rng, n))
    N = 260
    xs = [-1 + 2 * i / N for i in range(N + 1)]
    pts = [(x, -1 + top(x)) for x in xs] + [(x, 1 - bot(x)) for x in reversed(xs)]
    pen.poly(pts)
    # dotwork fades: dots thinning out towards the border
    rp = float(p["dot"])
    rx, ry = rp * 2 / pen.w, rp * 2 / pen.h
    for style, sign in ((p["top"], -1), (p["bottom"], 1)):
        if style != "fade":
            continue
        count = int(pen.w * pen.h * e / 2 / (rp * rp * 9) + 20)
        for _ in range(count):
            x, t = rng.uniform(-1, 1), rng.random()          # t: 0 at the border, 1 at the solid ink
            if rng.random() < t ** 1.4:
                y = sign * (1 - e * (1 - t))
                s = .6 + .6 * t
                pen.ellipse(x, y, rx * s, ry * s)
    _cut_outs(pen, rng, p, -1 + (e if p["top"] != "straight" else 0), 1 - (e if p["bottom"] != "straight" else 0))


def _cut_outs(pen, rng, p, y0, y1):
    """Negative-space pattern (skin showing through) in rows between y0 and y1."""
    cut = p["cut"]
    if cut == "none" or y1 - y0 < .1:
        return
    s = float(p["cut_size"])                         # motif size in output pixels
    sy, sx = s * 2 / pen.h, s * 2 / pen.w            # … in y / x units
    rows = max(1, int((y1 - y0) / (sy * 1.7)))
    m = max(2, int(round(2 / (sx * 1.7))))
    for r in range(rows):
        yc = y0 + (r + .5) * (y1 - y0) / rows
        off = .5 if r % 2 else 0.0
        if cut == "lines":
            if r:
                yl = y0 + r * (y1 - y0) / rows
                pen.stroke([(-1.02, yl), (1.02, yl)], max(1.5, s * .3) * 3 / pen.u, ink=0)
            continue
        for i in range(m):
            cx = -1 + (i + .5 + off) * 2 / m
            if cx > 1 - sx * .5:
                cx -= 2
            hx, hy = sx * .5, sy * .5
            if cut == "stars":
                pts = []
                for k in range(10):
                    a = math.radians(-90 + 36 * k)
                    f = 1 if k % 2 == 0 else .42
                    pts.append((cx + math.cos(a) * hx * f, yc + math.sin(a) * hy * f))
                pen.poly(pts, ink=0)
            elif cut == "diamonds":
                pen.poly([(cx - hx * .7, yc), (cx, yc - hy), (cx + hx * .7, yc), (cx, yc + hy)], ink=0)
            elif cut == "triangles":
                d = 1 if (i + r) % 2 else -1
                pen.poly([(cx - hx, yc - d * hy * .8), (cx + hx, yc - d * hy * .8), (cx, yc + d * hy * .8)], ink=0)
            elif cut == "dots":
                pen.ellipse(cx, yc, hx * .5, hy * .5, ink=0)
            elif cut == "koru":
                pts = [(cx + (px - cx) * hx / hy, py) for px, py in spiral(cx, yc, .02 * hy, hy * .85, 1.6, n=40)]
                pen.stroke(pts, max(1.2, s * .16) * 3 / pen.u, ink=0)


def _band(id, name, place=None, size=128, aspect=4.0, tags="", **defaults):
    reg(id, name, "Fully inked", aspect, kind="gen", size=size, wrap=True, tags="solid blackout fill " + tags,
        params=_fill_params(**defaults), place=place)(_blackout)


def _spot(limb, span):
    return {"limb": limb, "y0": span[0], "y1": span[1]}


# sleeves and fills that cover a whole part of a limb
_band("full_sleeve", "Full sleeve (arm)", _spot("arm", ARM_ALL), aspect=.8, tags="arm shoulder wrist blackout")
_band("half_sleeve", "Half sleeve (upper arm)", _spot("arm", ARM_UPPER), aspect=2.2, tags="upper arm biceps",
      bottom="wavy", edge=.12, repeats=4)
_band("forearm_sleeve", "Forearm sleeve", _spot("arm", ARM_FORE), aspect=1.4, tags="forearm",
      top="ragged", edge=.1, repeats=7)
_band("wrist_cuff", "Wrist cuff", _spot("arm", ARM_WRIST), aspect=7, tags="wrist bracelet",
      top="zigzag", edge=.3, repeats=10)
_band("flame_sleeve", "Flame sleeve", _spot("arm", ARM_FORE), aspect=1.4, tags="forearm fire flames",
      top="flames", edge=.32, repeats=5)
_band("full_leg", "Full leg", _spot("leg", LEG_ALL), aspect=.55, tags="leg thigh calf blackout")
_band("thigh_fill", "Thigh", _spot("leg", LEG_THIGH), aspect=2.0, tags="thigh upper leg", bottom="wavy", edge=.12, repeats=4)
_band("knee_band", "Knee band", _spot("leg", LEG_KNEE), aspect=3.2, tags="knee", top="zigzag", bottom="zigzag",
      edge=.2, repeats=8)
_band("calf_sleeve", "Calf sleeve", _spot("leg", LEG_CALF), aspect=1.1, tags="calf shin lower leg",
      top="ragged", edge=.08, repeats=7)
# bands placed where the marker is
_band("solid_band", "Solid band", size=128, aspect=5, tags="armband")
_band("fade_band", "Fade band", size=128, aspect=3, tags="shading dotwork gradient", top="fade", bottom="fade", edge=.24)
_band("blackout_stars", "Blackout with stars", size=128, aspect=2.2, tags="negative space", cut="stars")
_band("blackout_diamonds", "Blackout with diamonds", size=128, aspect=2.2, tags="negative space geometric", cut="diamonds")
_band("blackout_polynesian", "Polynesian blackout", size=128, aspect=2.2, tags="negative space maori samoan teeth",
      cut="triangles", top="zigzag", bottom="zigzag", edge=.12, repeats=10, cut_size=8.0)
_band("blackout_lines", "Blackout stripes", size=128, aspect=2.2, tags="negative space lines rings", cut="lines", cut_size=7.0)
_band("blackout_koru", "Blackout with koru", size=128, aspect=2.2, tags="negative space maori spiral", cut="koru", cut_size=11.0)


# ── solid shapes (not round the limb) ────────────────────────────────────────
def _rough(rng, p, n=96):
    noise = [(k, rng.uniform(0, 6.3), rng.uniform(.4, 1) / k) for k in range(3, 11)]
    tot = sum(a for _, _, a in noise)
    return lambda t: 1 - float(p.get("rough", 0)) * .18 * (.5 + .5 * sum(a * math.sin(k * t + ph) for k, ph, a in noise) / tot)


@reg("solid_patch", "Solid patch", "Fully inked", 1.0, kind="gen", size=44, tags="solid blackout square block",
     params=[R("round", "Rounded corners", 0, 1, .35), R("rough", "Rough edge", 0, 1, 0.0)])
def _patch(pen, rng, p):
    r = _rough(rng, p)
    k = 2 + 10 * (1 - float(p["round"])) ** 2               # superellipse exponent: 2 = oval … 12 = square
    pts = []
    for i in range(160):
        t = 2 * math.pi * i / 160
        c, s = math.cos(t), math.sin(t)
        x = math.copysign(abs(c) ** (2 / k), c)
        y = math.copysign(abs(s) ** (2 / k), s)
        pts.append((x * .98 * r(t), y * .98 * r(t)))
    pen.poly(pts)


@reg("solid_disc", "Solid circle", "Fully inked", 1.0, kind="gen", size=34, tags="solid round dot blackout",
     params=[R("rough", "Rough edge", 0, 1, 0.0), R("ring", "Hole", 0, .8, 0.0)])
def _disc(pen, rng, p):
    r = _rough(rng, p)
    pen.poly([(math.cos(t) * .98 * r(t), math.sin(t) * .98 * r(t)) for t in (2 * math.pi * i / 120 for i in range(120))])
    if p["ring"] > 0:
        pen.ellipse(0, 0, p["ring"], ink=0)


@reg("solid_diamond", "Solid diamond", "Fully inked", .75, kind="gen", size=30, tags="solid rhombus blackout",
     params=[R("hole", "Hole", 0, .8, 0.0)])
def _sdiamond(pen, rng, p):
    pen.poly([(-1, 0), (0, -1), (1, 0), (0, 1)])
    if p["hole"] > 0:
        h = p["hole"]
        pen.poly([(-h, 0), (0, -h), (h, 0), (0, h)], ink=0)


@reg("solid_triangle", "Solid triangle", "Fully inked", 1.1, kind="gen", size=30, tags="solid blackout geometric",
     params=[C("point", "Points", ["up", "down"], "up")])
def _striangle(pen, rng, p):
    d = -1 if p["point"] == "up" else 1
    pen.poly([(-1, -d * .95), (1, -d * .95), (0, d * .95)])


@reg("solid_stripe", "Stripe down the limb", "Fully inked", .12, kind="gen", size=14, tags="solid line vertical blackout",
     params=[C("ends", "Ends", ["square", "pointed", "fade"], "square")], place=_spot("arm", ARM_ALL))
def _stripe(pen, rng, p):
    if p["ends"] == "pointed":
        pen.poly([(0, -1), (1, -.85), (1, .85), (0, 1), (-1, .85), (-1, -.85)])
    elif p["ends"] == "fade":
        pen.poly([(-1, -.7), (1, -.7), (1, .7), (-1, .7)])
        rx, ry = 2.2 / pen.w, 2.2 / pen.h
        for _ in range(int(pen.w * pen.h / 40) + 10):
            x, t = rng.uniform(-1, 1), rng.random()
            if rng.random() < t ** 1.3:
                pen.ellipse(x, rng.choice([-1, 1]) * (1 - .3 * t), rx, ry)
    else:
        pen.poly([(-1, -1), (1, -1), (1, 1), (-1, 1)])


# ── more line work ───────────────────────────────────────────────────────────
@reg("swallow", "Swallow", "Symbols", 1.3, size=40, tags="bird sailor traditional")
def _swallow(pen, rng, p):
    body = bez((-.15, -.05), (.2, -.35), (.55, -.25), (.7, -.15), 12) + bez((.7, -.15), (.5, .05), (.25, .15), (0, .2), 12)
    tail = [(0, .2), (-.35, .55), (-.2, .25), (-.55, .45), (-.25, .05), (-.15, -.05)]
    pen.poly(body + tail)
    wing = bez((.05, -.05), (-.3, -.7), (-.8, -.9), (-1.0, -.95), 14) + bez((-1.0, -.95), (-.6, -.45), (-.35, -.15), (.2, .08), 14)
    pen.poly(wing)
    wing2 = bez((.25, -.15), (.35, -.6), (.65, -.9), (.95, -.98), 14) + bez((.95, -.98), (.7, -.6), (.6, -.3), (.45, -.1), 14)
    pen.poly(wing2)
    pen.ellipse(.62, -.2, .035, ink=0)


@reg("infinity", "Infinity", "Symbols", 2.2, size=40, tags="forever loop")
def _infinity(pen, rng, p):
    pts = []
    for i in range(121):
        t = 2 * math.pi * i / 120
        d = 1 + math.sin(t) ** 2
        pts.append((.95 * math.cos(t) / d, .95 * 1.6 * math.sin(t) * math.cos(t) / d))
    pen.stroke(pts, .16)


@reg("gem", "Diamond gem", "Symbols", 1.2, size=34, tags="jewel crystal")
def _gem(pen, rng, p):
    top, girdle, tip = -.55, -.15, .95
    outline = [(-.55, top), (.55, top), (.95, girdle), (0, tip), (-.95, girdle)]
    pen.stroke(outline, .07, closed=True)
    pen.stroke([(-.95, girdle), (.95, girdle)], .06)
    for a, b in (((-.55, top), (-.3, girdle)), ((.55, top), (.3, girdle)), ((0, top), (-.3, girdle)), ((0, top), (.3, girdle)),
                 ((-.3, girdle), (0, tip)), ((.3, girdle), (0, tip))):
        pen.stroke([a, b], .05)


@reg("mountains", "Mountains", "Symbols", 1.8, size=46, tags="peaks nature outdoors")
def _mountains(pen, rng, p):
    pen.stroke([(-1, .7), (-.45, -.55), (-.1, .1), (.3, -.85), (1, .7)], .07)
    pen.stroke([(-1, .7), (1, .7)], .07)
    pen.poly([(.3, -.85), (.45, -.55), (.32, -.5), (.22, -.58), (.12, -.48)])
    pen.poly([(-.45, -.55), (-.32, -.3), (-.42, -.27), (-.5, -.35), (-.58, -.28)])
    pen.ellipse(-.75, -.6, .13)


@reg("great_wave", "Wave", "Symbols", 1.5, size=46, tags="ocean sea japanese surf")
def _wave(pen, rng, p):
    crest = bez((-1, .8), (-.6, -.2), (.1, -1.0), (.75, -.5), 24) + bez((.75, -.5), (.95, -.35), (.7, -.05), (.45, -.25), 12)
    pen.stroke(crest, .09)
    pen.stroke(spiral(.25, -.25, .03, .3, 1.2, a0=200, n=36), .06)
    for k in range(3):
        y = .2 + k * .27
        pen.stroke([(x, y + .08 * math.sin(4 * x + k)) for x in [-1 + .04 * i for i in range(51)]], .05)


@reg("rose_flower", "Rose", "Symbols", .8, size=40, tags="flower love traditional")
def _rose(pen, rng, p):
    pen.stroke(spiral(0, -.35, .03, .5, 2.2, n=80), .07)
    pen.stroke(circ(0, -.35, .55, 20, 160, 24), .07)
    pen.stroke([(0, .2), (.05, .55), (0, .98)], .06)
    for sg in (-1, 1):
        leaf = bez((0, .55), (sg * .3, .35), (sg * .6, .45), (sg * .7, .6), 12) + bez((sg * .7, .6), (sg * .45, .75), (sg * .2, .7), (0, .55), 12)
        pen.poly(leaf)


@reg("roman_date", "Date in Roman numerals", "Lettering", 4.0, kind="gen", size=80, tags="date year numbers roman",
     params=[{"k": "text", "label": "Text", "type": "text", "default": "XXI · XI · MMXXVI"},
             C("font", "Lettering", ["serif", "block", "slab", "script", "brush", "rock"], "serif"),
             R("tilt", "Tilt", -20, 20, 0, 1)])
def _roman(pen, rng, p):
    _text(pen, rng, p)


@reg("name_script", "Name", "Lettering", 3.0, kind="gen", size=70, tags="name signature words",
     params=[{"k": "text", "label": "Text", "type": "text", "default": "Mum"},
             C("font", "Lettering", ["script", "brush", "serif", "block", "slab", "rock"], "script"),
             R("tilt", "Tilt", -20, 20, -6, 1)])
def _name(pen, rng, p):
    _text(pen, rng, p)
