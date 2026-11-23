"""More bank motifs: tribal (maori / polynesian / celtic / blackwork) and rugby (balls, boots, trophy, national emblems).
Registered into `motifs.REG` on import (motifs.py imports this at its end)."""
from __future__ import annotations

import math

from .motifs import R, bez, circ, mirror_x, reg, rot, spiral


def blade(pen, p0, p1, w=.12, bend=0.0, n=14, taper=1.0, ink=255, base_w=None):
    """A curved spike from p0 (width w) to p1 (a point), bending sideways by `bend`."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L
    c = [(p0[0] + dx * t + nx * bend * math.sin(math.pi * t), p0[1] + dy * t + ny * bend * math.sin(math.pi * t)) for t in (i / n for i in range(n + 1))]
    left, right = [], []
    for i, (x, y) in enumerate(c):
        a, b = c[max(i - 1, 0)], c[min(i + 1, n)]
        tx, ty = b[0] - a[0], b[1] - a[1]
        tl = math.hypot(tx, ty) or 1.0
        ux, uy = -ty / tl, tx / tl
        ww = (base_w if base_w is not None else w) * (1 - (i / n) ** taper) / 2
        left.append((x + ux * ww, y + uy * ww))
        right.append((x - ux * ww, y - uy * ww))
    pen.poly(left + right[::-1], ink)


def star_at(pen, cx, cy, r, n=5, ink=255):
    pts = []
    for i in range(2 * n):
        rr = r if i % 2 == 0 else r * .42
        a = math.radians(-90 + 180 * i / n)
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    pen.poly(pts, ink)


def _koru_at(pen, cx, cy, r, ang=0.0, t=.12):
    """Koru: a spiral frond with its stem, scaled by r, turned by ang degrees about (cx, cy)."""
    sp = rot([(x * r, y * r) for x, y in spiral(0, 0, .1, .9, 1.45, a0=200, cw=False, n=60)], ang)
    pen.stroke([(cx + x, cy + y) for x, y in sp], t * (1 + r))
    end = sp[-1]
    stem = bez(end, (end[0] + .5 * r, end[1] + .9 * r), (-.2 * r, 1.4 * r), (-.9 * r, 1.1 * r), 20)
    pen.stroke([(cx + x, cy + y) for x, y in rot(stem, ang)], t * (1 + r) * .8)
    pen.ellipse(cx, cy, .1 * r + .02)


# ── tribal ───────────────────────────────────────────────────────────────────
@reg("hei_matau", "Hei matau (fish hook)", "Tribal", .75, size=40, tags="maori fish hook new zealand pounamu jade")
def _hei_matau(pen, rng, p):
    hook = bez((-.2, -.5), (-.28, .35), (-.15, .95), (.4, .72), 30) + bez((.4, .72), (.95, .5), (.78, -.05), (.55, -.3), 24)
    pen.stroke(hook, .24)
    pen.poly([(.38, -.35), (.58, -.62), (.74, -.3)])
    pen.ellipse(-.2, -.7, .24, ink=255)
    pen.ellipse(-.2, -.7, .11, ink=0)
    pen.stroke(bez((-.2, -.45), (-.2, -.1), (-.2, .3), (-.2, .5), 10), .06, ink=0)


@reg("triple_koru", "Triple koru", "Tribal", 1.1, size=44, tags="maori fern spirals family")
def _triple_koru(pen, rng, p):
    for cx, cy, r, sx in ((-.62, -.3, .27, -1), (0, -.55, .3, 1), (.62, -.3, .27, 1)):
        head = spiral(cx, cy, .03, r, 1.5, a0=90, cw=sx > 0, n=50)
        pen.stroke(head, .12)
        pen.ellipse(cx, cy, .06)
        ex, ey = head[-1]
        pen.stroke(bez((ex, ey), (ex, ey + .5), (cx * .4, .45), (0, .95), 20), .11)


@reg("pikorua", "Pikorua (twist)", "Tribal", 1.6, size=44, tags="maori twist infinity bond friendship")
def _pikorua(pen, rng, p):
    def lem(t0, t1, n=70):
        out = []
        for i in range(n + 1):
            t = t0 + (t1 - t0) * i / n
            d = 1 + math.sin(t) ** 2
            out.append((.9 * math.cos(t) / d, .75 * math.sin(t) * math.cos(t) / d * 1.6))
        return out
    pen.stroke(lem(0, 2 * math.pi), .16, closed=True)
    pen.stroke(lem(math.pi / 2 - .55, math.pi / 2 + .55), .27, ink=0)
    pen.stroke(lem(math.pi / 2 - .55, math.pi / 2 + .55), .16)


@reg("triskele", "Triskele", "Tribal", 1, size=40, tags="celtic spiral three")
def _triskele(pen, rng, p):
    for k in range(3):
        arm = bez((0, 0), (.15, -.95), (1.0, -.7), (.82, -.12), 30) + spiral(.62, -.12, .2, .06, 1.1, a0=0, cw=False, n=24)
        pen.stroke(rot(arm, 120 * k), .14)
    pen.ellipse(0, 0, .1)


@reg("triquetra", "Triquetra", "Tribal", 1, size=38, tags="celtic knot trinity")
def _triquetra(pen, rng, p):
    for k in range(3):
        lens = bez((0, -.95), (.62, -.5), (.55, .0), (0, .3), 24) + bez((0, .3), (-.55, .0), (-.62, -.5), (0, -.95), 24)
        pen.stroke(rot(lens, 120 * k, 0, -.12), .075, closed=True)
    pen.ellipse(0, -.08, .7, t=.055)


@reg("tribal_flame", "Tribal flame", "Tribal", .8, size=40, tags="fire blackwork")
def _tflame(pen, rng, p):
    for x, h, b in ((-.55, .6, -.2), (-.25, .85, -.18), (0, 1.0, .1), (.25, .85, .18), (.55, .6, .2)):
        blade(pen, (x * .5, .95), (x * 1.1, .95 - 1.9 * h), w=.42, bend=b * 1.4, taper=.8)
    pen.poly([(-.35, .95), (.35, .95), (0, .55)], 0)


@reg("tribal_wing", "Tribal wings", "Tribal", 1.5, size=64, tags="blackwork angel")
def _twings(pen, rng, p):
    for k in range(6):
        a = math.radians(-86 + 15 * k)
        ln = 1.0 - .05 * k
        tx, ty = .08 + ln * math.cos(a) * 1.0, .85 + ln * math.sin(a) * 1.65
        w = .3 - .02 * k
        blade(pen, (.05, .85 - .03 * k), (tx, ty), w=w, bend=-.2 + .03 * k, taper=.9)
        blade(pen, (-.05, .85 - .03 * k), (-tx, ty), w=w, bend=.2 - .03 * k, taper=.9)
    pen.ellipse(0, .85, .13)


@reg("tribal_turtle", "Honu (turtle)", "Tribal", 1, size=44, tags="polynesian hawaiian samoan sea protection")
def _turtle(pen, rng, p):
    pen.ellipse(0, .05, .46, .5)
    pen.ellipse(0, .05, .36, .4, ink=0)
    pen.stroke([(0, -.28), (.17, -.1), (.17, .16), (0, .32), (-.17, .16), (-.17, -.1)], .06, closed=True)
    for a in (0, 72, 144, 216, 288):
        x, y = rot([(0, -.33)], a, 0, 0)[0]
        pen.ellipse(x, .05 + y * 1.1, .035)
    pen.ellipse(0, -.66, .13, .16)
    for sx in (-1, 1):
        blade(pen, (sx * .36, -.28), (sx * .95, -.62), w=.26, bend=sx * .1, taper=1.1)
        blade(pen, (sx * .34, .3), (sx * .8, .82), w=.22, bend=-sx * .1, taper=1.1)
    blade(pen, (0, .52), (0, .95), w=.12, taper=1.0)


@reg("tribal_cross", "Tribal cross", "Tribal", .8, size=40, tags="blackwork cross spikes")
def _tcross(pen, rng, p):
    blade(pen, (0, -.2), (0, -1), w=.34, taper=.9)
    blade(pen, (0, -.2), (0, 1.0), w=.34, taper=.9)
    for sx in (-1, 1):
        blade(pen, (0, -.4), (sx * .98, -.4), w=.3, taper=.9)
        blade(pen, (sx * .1, .35), (sx * .55, .72), w=.17, bend=sx * .14)
    pen.poly([(0, -.62), (.14, -.4), (0, -.18), (-.14, -.4)], 0)
    pen.ellipse(0, -.4, .05)


@reg("tribal_star", "Tribal star", "Tribal", 1, size=44, tags="blackwork sun compass")
def _tstar(pen, rng, p):
    for i in range(8):
        a = 360 * i / 8
        L = 1.0 if i % 2 == 0 else .7
        pen.poly(rot([(-.17, -.2), (0, -L), (.17, -.2)], a))
    pen.ellipse(0, 0, .3)
    pen.ellipse(0, 0, .2, ink=0)
    pen.ellipse(0, 0, .1)


@reg("tribal_spear", "Tribal spearhead", "Tribal", .4, size=48, tags="taiaha maori weapon blade")
def _tspear(pen, rng, p):
    pen.poly([(0, -1), (.28, -.45), (.2, .1), (0, .22), (-.2, .1), (-.28, -.45)])
    for y in (-.5, -.3, -.1):
        pen.poly([(-.15, y), (0, y - .09), (.15, y)], 0)
    pen.stroke([(0, .2), (0, .98)], .12)
    pen.ellipse(0, .48, .1, .05, ink=0)
    pen.ellipse(0, .72, .1, .05, ink=0)


@reg("tribal_fan", "Shark-tooth fan", "Tribal", 1.1, size=48, tags="niho taniwha teeth maori polynesian")
def _tfan(pen, rng, p):
    n = 9
    for i in range(n):
        a = math.radians(-76 + 152 * i / (n - 1))
        f = 1 - .3 * abs(i - (n - 1) / 2) / ((n - 1) / 2)
        blade(pen, (0, .95), (math.sin(a) * .98 * f, .95 - math.cos(a) * 1.85 * f), w=.3, taper=1.0)
    pen.ellipse(0, .95, .22)
    pen.ellipse(0, .95, .12, ink=0)


# ── tribal bands ─────────────────────────────────────────────────────────────
@reg("teeth_band", "Niho taniwha (teeth) band", "Bands", 4, kind="gen", size=128, wrap=True, tags="maori polynesian shark teeth armband",
     params=[R("teeth", "Teeth", 4, 20, 10), R("rows", "Rows", 1, 3, 2), R("thick", "Border weight", .4, 1.8, 1.0)])
def _teeth_band(pen, rng, p):
    n, rows, t = int(p["teeth"]), int(p["rows"]), .05 * p["thick"]
    rowh = 2 / rows
    for r in range(rows):
        y0, y1 = -1 + r * rowh, -1 + (r + 1) * rowh
        flip = r % 2
        pen.stroke([(-1, y0 + rowh * .04), (1, y0 + rowh * .04)], t)
        pen.stroke([(-1, y1 - rowh * .04), (1, y1 - rowh * .04)], t)
        for i in range(n):
            cx, w = -1 + (i + .5) * 2 / n, 1 / n * .98
            a, b = (y0 + rowh * .1, y1 - rowh * .1)
            if flip:
                a, b = b, a
            pen.poly([(cx - w, a), (cx + w, a), (cx, b)])
            pen.poly([(cx - w * .45, a + (b - a) * .18), (cx + w * .45, a + (b - a) * .18), (cx, a + (b - a) * .58)], 0)


@reg("thorn_band", "Thorn band", "Bands", 4, kind="gen", size=128, wrap=True, tags="blackwork spikes armband vine",
     params=[R("thorns", "Thorns", 3, 16, 8), R("thick", "Weight", .4, 1.8, 1.0), R("curl", "Curl", 0, 1, .6)])
def _thorn_band(pen, rng, p):
    n = int(p["thorns"])
    pen.stroke([(x, .12 * math.sin(math.pi * n * (x + 1))) for x in [-1 + 2 * i / 200 for i in range(201)]], .1 * p["thick"])
    for i in range(n):
        cx = -1 + (i + .5) * 2 / n
        sg = 1 if i % 2 else -1
        blade(pen, (cx - .02, 0), (cx + 1 / n * .9 * p["curl"], sg * .95), w=.2 * p["thick"], bend=sg * .25 * p["curl"], taper=.9)


@reg("wave_band", "Wave scroll band", "Bands", 4, kind="gen", size=128, wrap=True, tags="polynesian ocean curl scroll armband",
     params=[R("waves", "Waves", 3, 14, 7), R("thick", "Weight", .4, 1.8, 1.0), R("curls", "Curls", 0, 1, 1)])
def _wave_band(pen, rng, p):
    n, t = int(p["waves"]), .13 * p["thick"]
    pen.stroke([(x, .35 * math.sin(2 * math.pi * n * (x + 1) / 2)) for x in [-1 + 2 * i / 240 for i in range(241)]], t)
    if p["curls"] > .5:
        for k in range(n):
            sg = 1 if k % 2 == 0 else -1
            x = -1 + (k + .5) / n
            pen.stroke(spiral(x, .35 * sg + sg * .3, .02, .3, 1.3, a0=90 * sg, n=24, cw=sg > 0), t * .8)


# ── rugby ────────────────────────────────────────────────────────────────────
@reg("ball_solid", "Rugby ball (solid)", "Rugby", 1.3, size=46, tags="ball laces")
def _ball_solid(pen, rng, p):
    pen.ellipse(0, 0, .97, .6)
    for sx in (-1, 1):
        pen.stroke([(sx * x, y) for x, y in bez((.0, -.58), (.45, -.45), (.72, -.2), (.82, .0), 12)], .035, ink=0)
        pen.stroke([(sx * x, y) for x, y in bez((.0, .58), (.45, .45), (.72, .2), (.82, .0), 12)], .035, ink=0)
    pen.stroke([(-.3, 0), (.3, 0)], .06, ink=0)
    for x in (-.22, -.11, 0, .11, .22):
        pen.stroke([(x, -.15), (x, .15)], .04, ink=0)


@reg("ball_tilted", "Ball with seams", "Rugby", 1.3, size=44, tags="ball diagonal")
def _ball_tilt(pen, rng, p):
    def tilt(pts):
        return rot(pts, -35)
    pen.poly(tilt(circ(0, 0, .95, 0, 360, 60, ry=.58)))
    pen.stroke(tilt(circ(0, 0, .95, 0, 360, 60, ry=.58)), .05)
    pen.poly(tilt(circ(0, 0, .8, 0, 360, 60, ry=.46)), 0)
    pen.stroke(tilt([(-.25, 0), (.25, 0)]), .06)
    for x in (-.18, -.09, 0, .09, .18):
        pen.stroke(tilt([(x, -.12), (x, .12)]), .04)
    pen.stroke(tilt([(-.8, -.3), (-.55, -.2)]), .04)
    pen.stroke(tilt([(.8, .3), (.55, .2)]), .04)


@reg("trophy", "Cup", "Rugby", .8, size=42, tags="webb ellis world cup champion trophy")
def _trophy(pen, rng, p):
    bowl = bez((-.55, -.9), (-.6, -.1), (-.3, .1), (-.08, .12), 16) + [(.08, .12)] + bez((.08, .12), (.3, .1), (.6, -.1), (.55, -.9), 16)
    pen.poly(bowl)
    pen.stroke(bez((-.55, -.75), (-1.05, -.8), (-.95, -.1), (-.38, -.12), 14), .09)
    pen.stroke(bez((.55, -.75), (1.05, -.8), (.95, -.1), (.38, -.12), 14), .09)
    pen.poly([(-.08, .1), (.08, .1), (.12, .55), (-.12, .55)])
    pen.ellipse(0, .35, .2, .07)
    pen.poly([(-.5, .95), (.5, .95), (.38, .65), (-.38, .65)])
    pen.stroke([(-.45, -.55), (.45, -.55)], .04, ink=0)


@reg("jersey", "Jersey", "Rugby", 1.15, size=40, tags="shirt number kit")
def _jersey(pen, rng, p):
    pen.poly([(-.35, -.9), (.35, -.9), (.95, -.55), (.78, -.1), (.5, -.25), (.5, .95), (-.5, .95), (-.5, -.25), (-.78, -.1), (-.95, -.55)])
    pen.poly([(-.2, -.92), (0, -.62), (.2, -.92)], 0)
    pen.stroke([(-.5, .1), (.5, .1)], .05, ink=0)
    pen.stroke([(-.5, .28), (.5, .28)], .05, ink=0)


@reg("boot", "Rugby boot", "Rugby", 1.5, size=44, tags="kicking studs")
def _boot(pen, rng, p):
    pen.poly([(-.9, -.75), (-.3, -.75), (-.25, -.25), (.35, -.02), (.85, .18), (.97, .42), (.95, .6), (-.9, .6)])
    pen.poly([(-.92, .66), (.97, .66), (.97, .76), (-.92, .76)])
    for x in (-.75, -.3, .25, .75):
        pen.poly([(x - .1, .8), (x + .1, .8), (x, .98)])
    for k in range(4):
        pen.stroke([(-.18 + .17 * k, -.12 + .08 * k), (-.02 + .17 * k, -.3 + .08 * k + .12)], .035, ink=0)
    pen.stroke([(-.9, .02), (-.35, .02)], .04, ink=0)


@reg("kick", "Posts and ball", "Rugby", .8, size=42, tags="goal conversion kicker h")
def _kick(pen, rng, p):
    pen.stroke([(-.55, -.7), (-.55, .45)], .08)
    pen.stroke([(.55, -.7), (.55, .45)], .08)
    pen.stroke([(-.55, .25), (.55, .25)], .08)
    pen.stroke([(0, .25), (0, 1)], .09)
    pen.poly(rot(circ(0, -.5, .26, 0, 360, 30, ry=.14), -30))


@reg("shield_crest", "Shield with ball", "Rugby", .85, size=40, tags="crest badge club team heraldic")
def _shield(pen, rng, p):
    out = [(-.85, -.9), (.85, -.9), (.85, .05)] + bez((.85, .05), (.8, .6), (.35, .85), (0, 1.0), 20) + bez((0, 1.0), (-.35, .85), (-.8, .6), (-.85, .05), 20)
    pen.stroke(out, .1, closed=True)
    pen.stroke([(-.85, -.5), (.85, -.5)], .06)
    pen.poly(rot(circ(0, .12, .5, 0, 360, 40, ry=.28), -35))
    pen.stroke(rot([(-.15, .12), (.15, .12)], -35, 0, .12), .04, ink=0)
    star_at(pen, 0, -.72, .13)


@reg("rose", "Tudor rose", "Rugby", 1, size=38, tags="england english red rose")
def _rose(pen, rng, p):
    for k in range(5):
        x, y = rot([(0, -.6)], 72 * k)[0]
        pen.ellipse(x, y, .36, t=.07)
    for k in range(5):
        x, y = rot([(0, -.32)], 72 * k + 36)[0]
        pen.ellipse(x, y, .22, t=.06)
    pen.ellipse(0, 0, .13)
    for k in range(5):
        x, y = rot([(0, -.6)], 72 * k)[0]
        pen.ellipse(x, y, .04)


@reg("thistle", "Thistle", "Rugby", .65, size=40, tags="scotland scottish")
def _thistle(pen, rng, p):
    pen.ellipse(0, -.1, .34, .3)
    for k in range(-3, 4):
        blade(pen, (k * .08, -.35), (k * .24, -.98 + abs(k) * .06), w=.13, bend=k * .03, taper=.8)
    for x in (-.2, -.1, 0, .1, .2):
        pen.stroke([(x - .1, -.25), (x + .1, .05)], .03, ink=0)
        pen.stroke([(x + .1, -.25), (x - .1, .05)], .03, ink=0)
    pen.poly([(-.34, .1), (.34, .1), (0, .28)])
    pen.stroke([(0, .2), (0, .98)], .08)
    blade(pen, (0, .65), (-.8, .25), w=.2, bend=.15, taper=.9)
    blade(pen, (0, .7), (.8, .3), w=.2, bend=-.15, taper=.9)


@reg("welsh_feathers", "Three feathers", "Rugby", .95, size=42, tags="wales welsh prince of wales plumes")
def _feathers(pen, rng, p):
    def feather(a, ln):
        spine = bez((0, 0), (.05, -.3 * ln), (-.03, -.7 * ln), (0, -ln), 20)
        for i in range(1, 19):
            x, y = spine[i]
            w = .3 * math.sin(math.pi * i / 20) ** .7
            L = rot([(x, y), (x - w, y - .14), (x - w * .75, y - .02)], a, 0, 0)
            Rr = rot([(x, y), (x + w, y - .14), (x + w * .75, y - .02)], a, 0, 0)
            pen.poly([(px, py + .9) for px, py in L])
            pen.poly([(px, py + .9) for px, py in Rr])
    feather(-32, .95)
    feather(32, .95)
    feather(0, 1.15)
    pen.stroke(circ(0, .98, .16, 180, 360, 12), .07)
    pen.stroke([(-.3, .9), (.3, .9)], .08)


@reg("southern_cross", "Southern Cross", "Rugby", .85, size=42, tags="new zealand australia stars constellation")
def _scross(pen, rng, p):
    star_at(pen, 0, -.78, .3)
    star_at(pen, 0, .78, .32)
    star_at(pen, -.72, .04, .27)
    star_at(pen, .72, -.1, .27)
    star_at(pen, .3, .3, .14)


@reg("maple_leaf", "Maple leaf", "Rugby", 1, size=36, tags="canada canadian")
def _maple(pen, rng, p):
    half = [(0, -1), (.15, -.68), (.3, -.76), (.27, -.4), (.58, -.56), (.5, -.3), (.92, -.2), (.7, .02), (.8, .24), (.42, .2), (.38, .42), (.07, .38), (.06, .98)]
    pen.poly(half + mirror_x(half)[::-1])


@reg("kiwi", "Kiwi", "Rugby", 1.3, size=42, tags="new zealand bird")
def _kiwi(pen, rng, p):
    pen.ellipse(-.2, .0, .62, .5)
    pen.poly([(.35, -.18), (.9, .15), (1.0, .3), (.88, .22), (.32, .1)])
    pen.stroke(bez((.34, -.05), (.55, -.2), (.72, -.05), (.95, .3), 14), .09)
    pen.ellipse(.36, -.1, .05, ink=0)
    for x in (-.3, -.05):
        pen.stroke([(x, .42), (x - .02, .82)], .07)
        pen.stroke([(x - .02, .82), (x + .18, .85)], .05)
        pen.stroke([(x - .02, .82), (x - .17, .88)], .05)

