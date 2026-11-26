#!/usr/bin/env python3
"""Draw the Nations Championship art (data/competitions/nations_championship/
assets): the tournament logo, both pitch logos, the pads and the posts. An
original design of the mod — a ring of twelve stars, one per nation, round
a ball, in navy and gold. Run by hand after changing it:

    .venv/bin/python tools/make_nations_championship.py
"""
import math
import os
import sys

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src"), os.path.join(ROOT, "tools")]

from backend.stadium_dressing import PADS_LAYOUT, PADS_SIZE  # noqa: E402
import make_posts  # noqa: E402

OUT = os.path.join(ROOT, "data", "competitions", "nations_championship", "assets")
FONTS = os.path.join(ROOT, "src", "assets", "fonts")
SS = 4                                          # drawn larger, then shrunk

NAVY, DEEP = (14, 26, 58), (8, 15, 36)
GOLD, WHITE = (214, 172, 72), (244, 244, 240)


def font(size, name="Oswald-Variable.ttf", weight=None):
    f = ImageFont.truetype(os.path.join(FONTS, name), size)
    if weight:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass
    return f


def star(draw, cx, cy, r, fill):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.42
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    draw.polygon(pts, fill=fill)


def emblem(size, ring=GOLD, ball=WHITE):
    """The mark: twelve stars round a tilted ball, on a transparent square."""
    s = size * SS
    im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    c, r = s / 2, s * 0.42
    for i in range(12):
        a = -math.pi / 2 + i * math.pi / 6
        star(d, c + r * math.cos(a), c + r * math.sin(a), s * 0.055, ring)
    # the ball: an ellipse with its seam and laces, turned 35°
    ball_im = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    b = ImageDraw.Draw(ball_im)
    w, h = s * 0.30, s * 0.19
    lw = max(1, round(s * 0.028))
    b.ellipse((c - w, c - h, c + w, c + h), outline=ball, width=lw)
    b.line((c - w * 0.55, c, c + w * 0.55, c), fill=ball, width=max(1, lw // 2))
    for k in range(-2, 3):
        x = c + k * w * 0.16
        b.line((x, c - h * 0.28, x, c + h * 0.28), fill=ball, width=max(1, lw // 2))
    im.alpha_composite(ball_im.rotate(35, resample=Image.BICUBIC, center=(c, c)))
    return im.resize((size, size), Image.LANCZOS)


def text(label, size, colour, name="Oswald-Variable.ttf", weight=700, track=0.08):
    """`label` in one line, tracked, cropped to its ink."""
    f = font(size * SS, name, weight)
    gap = size * SS * track
    widths = [f.getlength(ch) for ch in label]
    width = int(sum(widths) + gap * (len(label) - 1)) + 4
    asc, desc = f.getmetrics()
    im = Image.new("RGBA", (width, asc + desc), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    x = 0
    for ch, w in zip(label, widths):
        d.text((x, 0), ch, font=f, fill=colour)
        x += w + gap
    im = im.crop(im.getbbox())
    return im.resize((max(1, im.width // SS), max(1, im.height // SS)), Image.LANCZOS)


def lockup(width, colour=WHITE, accent=GOLD, mark=True):
    """Emblem over NATIONS / CHAMPIONSHIP, `width` wide, transparent."""
    top = text("NATIONS", 60, colour, track=0.06)
    bottom = text("CHAMPIONSHIP", 30, accent, track=0.18)
    # both lines as wide as each other, together 86 % of the width
    top = top.resize((round(width * 0.86), round(top.height * width * 0.86 / top.width)), Image.LANCZOS)
    bottom = bottom.resize((top.width, round(bottom.height * top.width / bottom.width)), Image.LANCZOS)
    em = emblem(round(width * 0.52), accent, colour) if mark else None
    gap = round(width * 0.04)
    h = (em.height + gap if em else 0) + top.height + gap + bottom.height
    out = Image.new("RGBA", (width, h), (0, 0, 0, 0))
    y = 0
    if em:
        out.alpha_composite(em, ((width - em.width) // 2, 0))
        y = em.height + gap
    out.alpha_composite(top, ((width - top.width) // 2, y))
    out.alpha_composite(bottom, ((width - bottom.width) // 2, y + top.height + gap))
    return out


def fit(im, box_w, box_h):
    k = min(box_w / im.width, box_h / im.height)
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)


def centred(canvas, im, box=None):
    l, t, r, b = box or (0, 0, *canvas.size)
    canvas.alpha_composite(im, (l + (r - l - im.width) // 2, t + (b - t - im.height) // 2))


def backdrop(w, h):
    """Navy cloth: a soft vertical gradient."""
    im = Image.new("RGBA", (w, h), NAVY + (255,))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line((0, y, w, y), fill=tuple(round(a + (b - a) * t) for a, b in zip(NAVY, DEEP)) + (255,))
    return im


def tournament_logo():
    im = Image.new("RGBA", (256, 256), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((6, 6, 249, 249), 28, fill=NAVY + (255,), outline=GOLD + (255,), width=4)
    centred(im, fit(lockup(200), 200, 214))
    return im


def pitch_logo(size):
    """White, a little see-through: painted on the grass."""
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    centred(im, fit(lockup(size, WHITE, WHITE), size * 0.92, size * 0.92))
    alpha = im.getchannel("A").point(lambda a: round(a * 0.85))
    im.putalpha(alpha)
    return im


def pads():
    canvas = Image.new("RGBA", PADS_SIZE, (0, 0, 0, 0))
    for tag, (l, t, r, b) in PADS_LAYOUT.items():
        w, h = r - l, b - t
        part = backdrop(w, h)
        if tag == "pada":                       # the post pad: reads bottom to top
            line = Image.new("RGBA", (h, w), (0, 0, 0, 0))
            word = fit(text("NATIONS CHAMPIONSHIP", 60, WHITE, track=0.08), h * 0.62, w * 0.36)
            em = emblem(round(w * 0.62))
            centred(line, word, (round(h * 0.24), 0, h, w))
            centred(line, em, (0, 0, round(h * 0.26), w))
            part.alpha_composite(line.rotate(90, expand=True))
            ImageDraw.Draw(part).rectangle((0, 0, w - 1, 5), fill=GOLD)
        elif tag == "flgp":                     # four flag-pole strips
            for i in range(4):
                sw = w // 4
                line = Image.new("RGBA", (h, sw), (0, 0, 0, 0))
                word = fit(text("NATIONS CHAMPIONSHIP", 40, WHITE, track=0.08), h * 0.6, sw * 0.42)
                centred(line, word, (round(h * 0.22), 0, h, sw))
                centred(line, emblem(round(sw * 0.7)), (0, 0, round(h * 0.24), sw))
                part.alpha_composite(line.rotate(90, expand=True), (i * sw, 0))
        elif tag == "flag":
            em = emblem(round(min(h * 0.76, w * 0.32)))
            centred(part, em, (round(w * 0.03), 0, round(w * 0.38), h))
            word = fit(lockup(300, mark=False), w * 0.56, h * 0.6)
            centred(part, word, (round(w * 0.38), 0, round(w * 0.97), h))
        else:                                   # padb: the plain back of the pad
            centred(part, emblem(round(min(w, h) * 0.55), GOLD + (90,), WHITE + (60,)))
        canvas.paste(part, (l, t))
    return canvas


def posts():
    d = make_posts.Design(post=make_posts.NAVY, bar=make_posts.NAVY, middle=GOLD)
    d.band(GOLD, 0, make_posts.TOP_Y)
    for y in range(make_posts.TOP_Y + 40, make_posts.BAR_Y - 80, 120):
        d.band(GOLD, y, y + 8)
    for x in range(60, make_posts.OUTER_L, 160):
        d.bar_band(GOLD, x, x + 8)
    return d.picture()


def main():
    os.makedirs(os.path.join(OUT, "pitch_logos"), exist_ok=True)
    files = {
        "tournament_logo.png": tournament_logo(),
        "pitch_logos/pitch_logo_1.png": pitch_logo(256),
        "pitch_logos/pitch_logo_2.png": pitch_logo(128),
        "pads.png": pads(),
        "posts.png": posts(),
    }
    for name, im in files.items():
        path = os.path.join(OUT, name)
        im.save(path, optimize=True)
        print("wrote", path, im.size)


if __name__ == "__main__":
    main()
