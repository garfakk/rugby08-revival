#!/usr/bin/env python3
"""Write the painted posts sets of the library (data/stadium_graphics/posts):
pictures in the posts layout of backend/stadium_dressing.py (128 x 1024: the
post's strip, then the crossbar's, upright). Run by hand after changing a
design:

    python3 tools/make_posts.py

Each design draws the post (top at y 0) and the crossbar lying flat, from
the post (x 0) to the middle and on through its middle part; the bar is
turned upright into its strip at the end.

The post is eight-sided and each side shows the whole width of the post's
strip, the next one mirrored: nothing can wind round the post. Rows make
rings (hoops, bands, fades); a stripe climbing across the width makes a
zigzag ring, a triangle one tooth per side.

Names say what the posts look like: their colours, the main one first, then
the pattern (red_white_zigzag, green_gold_hoops; one colour: black_gold is
black posts with a gold middle). Sets made for a club or from the game keep
its name (edinburgh, generic).
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src")]

from backend.stadium_dressing import POSTS_SIZE, POST_BOX, XBAR_OUTER, XBAR_MIDDLE  # noqa: E402

OUT = os.path.join(ROOT, "data", "stadium_graphics", "posts")
SS = 4                                   # drawn larger, then shrunk: smooth edges

POST_W, POST_H = POST_BOX[2] - POST_BOX[0], POST_BOX[3] - POST_BOX[1]
BAR_T = XBAR_OUTER[2] - XBAR_OUTER[0]                    # the bar's thickness
OUTER_L = XBAR_OUTER[3] - XBAR_OUTER[1]                  # post to the middle
MIDDLE_L = XBAR_MIDDLE[3] - XBAR_MIDDLE[1]

WHITE, RED, BLACK = (240, 240, 240), (200, 30, 40), (25, 25, 25)
NAVY, BLUE, SKY = (20, 40, 110), (30, 70, 170), (110, 180, 230)
GREEN, GOLD = (0, 110, 60), (215, 160, 35)
EMERALD, MAROON, ORANGE = (0, 140, 75), (115, 20, 45), (235, 110, 20)

#: rows of the post's strip (stock Stadium.o): its top cap above TOP_Y,
#: the crossbar (3 m up a post of about 14 m) at BAR_Y, the pad at the bottom
TOP_Y, BAR_Y = 56, 943


class Design:
    """A post (POST_W x POST_H) and a flat crossbar (OUTER_L + MIDDLE_L long,
    BAR_T thick), drawn SS times larger."""

    def __init__(self, post=WHITE, bar=WHITE, middle=None):
        self.post = Image.new("RGBA", (POST_W * SS, POST_H * SS), post)
        self.bar = Image.new("RGBA", ((OUTER_L + MIDDLE_L) * SS, BAR_T * SS), bar)
        self.p, self.b = ImageDraw.Draw(self.post), ImageDraw.Draw(self.bar)
        if middle:
            self.middle(middle)

    def middle(self, colour, x0=0.0, x1=1.0):
        """Paint the bar's middle part (or the share x0-x1 of it)."""
        a = (OUTER_L + MIDDLE_L * x0) * SS
        self.b.rectangle((round(a), 0, round((OUTER_L + MIDDLE_L * x1) * SS) - 1, BAR_T * SS), fill=colour)

    def hoops(self, colours, height, top=0, bottom=POST_H):
        for i, y in enumerate(range(top, bottom, height)):
            self.p.rectangle((0, y * SS, POST_W * SS, min(bottom, y + height) * SS - 1),
                             fill=colours[i % len(colours)])

    def zigzag(self, colour, rise, width, spacing, top=0, bottom=POST_H):
        """Zigzag rings every `spacing` rows: a stripe `width` thick that
        climbs `rise` rows across the strip, so up one side, down the next."""
        for y in range(top, bottom, spacing):
            pts = [(0, y + rise), (POST_W, y), (POST_W, y + width), (0, y + rise + width)]
            self.p.polygon([(x * SS, yy * SS) for x, yy in pts], fill=colour)

    def fade(self, top, bottom, start=0, end=POST_H):
        """The post going from `top` to `bottom` colour between rows start-end
        (above start: `top`, below end: `bottom`)."""
        for y in range(POST_H * SS):
            t = min(1.0, max(0.0, (y / SS - start) / max(1, end - start)))
            t = t * t * (3 - 2 * t)                     # eased
            colour = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
            self.p.line((0, y, POST_W * SS, y), fill=colour)

    def teeth(self, colour, y, size, up=False):
        """A ring of triangles, one per side of the post, base on row y."""
        tip = y - size if up else y + size
        pts = [(0, y), (POST_W, y), (POST_W / 2, tip)]
        self.p.polygon([(px * SS, py * SS) for px, py in pts], fill=colour)

    def band(self, colour, top, bottom):
        """A ring round the post between rows top and bottom."""
        self.p.rectangle((0, top * SS, POST_W * SS, bottom * SS - 1), fill=colour)

    def bar_band(self, colour, x0, x1):
        """A band on the bar between x0 and x1 pixels from the post."""
        self.b.rectangle((x0 * SS, 0, x1 * SS - 1, BAR_T * SS), fill=colour)

    def bar_fade(self, a, b):
        """The bar going from colour a at the post to b at the middle."""
        for x in range(OUTER_L * SS):
            t = x / (OUTER_L * SS)
            t = t * t * (3 - 2 * t)
            self.b.line((x, 0, x, BAR_T * SS), fill=tuple(round(p + (q - p) * t) for p, q in zip(a, b)))

    def bar_bands(self, colours, width):
        """Bands across the bar from the post to the middle part."""
        for i, x in enumerate(range(0, OUTER_L, width)):
            self.b.rectangle((x * SS, 0, min(OUTER_L, x + width) * SS - 1, BAR_T * SS),
                             fill=colours[i % len(colours)])

    def picture(self):
        out = Image.new("RGBA", POSTS_SIZE, (0, 0, 0, 0))
        out.paste(self.post.resize((POST_W, POST_H), Image.LANCZOS), POST_BOX[:2])
        bar = self.bar.resize((OUTER_L + MIDDLE_L, BAR_T), Image.LANCZOS)
        for box, x0, x1 in ((XBAR_OUTER, 0, OUTER_L), (XBAR_MIDDLE, OUTER_L, OUTER_L + MIDDLE_L)):
            # upright: the post end at the top, the bar's top on the right
            out.paste(bar.crop((x0, 0, x1, BAR_T)).transpose(Image.ROTATE_270), box[:2])
        return out


def red_white_zigzag():
    d = Design(WHITE, WHITE, RED)
    d.zigzag(RED, 28, 34, 110, top=TOP_Y)
    d.bar_bands([RED, WHITE], 140)
    return d


def navy_white_zigzag():
    d = Design(WHITE, WHITE, NAVY)
    d.zigzag(NAVY, 20, 26, 150, top=TOP_Y + 40)
    return d


def black_white_hoops():
    d = Design(WHITE, WHITE, BLACK)
    d.hoops([BLACK, WHITE], 64)
    d.bar_bands([BLACK, WHITE], 160)
    return d


def green_gold_hoops():
    d = Design(GREEN, GOLD, GREEN)
    d.hoops([GREEN, GOLD], 96)
    return d


def tricolour():
    """White posts with a blue, white and red band near the top of each post
    and in the middle of the bar."""
    d = Design(WHITE, WHITE)
    d.hoops([BLUE, WHITE, RED], 48, top=96, bottom=96 + 3 * 48)
    for i, colour in enumerate((BLUE, WHITE, RED)):
        d.middle(colour, i / 3, (i + 1) / 3)
    return d


def black_gold():
    return Design(BLACK, BLACK, GOLD)


def sky_blue_white_hoops():
    """Narrow sky blue and white hoops, a sky blue bar."""
    d = Design(WHITE, SKY, WHITE)
    d.hoops([SKY, WHITE], 56)
    return d


def green_white_zigzag():
    d = Design(WHITE, WHITE, EMERALD)
    d.zigzag(EMERALD, 36, 40, 130, top=TOP_Y)
    d.bar_bands([EMERALD, WHITE], 120)
    return d


def black_gold_hoops():
    """Black posts with thin gold hoops."""
    d = Design(BLACK, BLACK, GOLD)
    for y in range(TOP_Y + 60, BAR_Y, 120):
        d.band(GOLD, y, y + 16)
    d.bar_band(GOLD, 0, 16)
    return d


def white_red_tips():
    """White posts with red tips and a thin red ring under them, red bar
    ends and middle."""
    d = Design(WHITE, WHITE, RED)
    d.band(RED, 0, TOP_Y + 200)
    d.band(RED, TOP_Y + 220, TOP_Y + 232)
    d.band(RED, BAR_Y - 30, BAR_Y - 18)
    d.bar_band(RED, 0, 70)
    return d


def white_blue_fade():
    """White at the top fading to royal blue at the bottom of the posts; the
    bar fades from blue at the posts to white."""
    d = Design(WHITE, WHITE, WHITE)
    d.fade(WHITE, BLUE, 300, POST_H)
    d.bar_fade(BLUE, WHITE)
    d.middle(BLUE, 0.4, 0.6)
    return d


def orange_black_fade():
    """Orange tops fading to black: a floodlit night look."""
    d = Design(ORANGE, BLACK, ORANGE)
    d.fade(ORANGE, BLACK, 80, 900)
    d.bar_fade(BLACK, ORANGE)
    return d


def maroon_white_hoops():
    """Broad maroon hoops with thin white ones between."""
    d = Design(MAROON, MAROON, WHITE)
    for y in range(110, POST_H, 140):
        d.band(WHITE, y, y + 24)
    d.middle(MAROON, 0.15, 0.85)
    return d


def black_white_tapa():
    """White posts with borders of black teeth, like a Pacific tapa cloth,
    at the top, half way up and over the crossbar."""
    d = Design(WHITE, WHITE, BLACK)
    for y in (TOP_Y + 20, 480, BAR_Y - 130):
        d.band(BLACK, y, y + 14)
        d.teeth(BLACK, y + 14, 46)
        d.band(BLACK, y + 76, y + 84)
    d.bar_band(BLACK, 0, 14)
    for x in range(40, OUTER_L, 64):
        d.b.polygon([(x * SS, 0), ((x + 32) * SS, 0), ((x + 16) * SS, BAR_T * SS * 0.6)], fill=BLACK)
    return d


DESIGNS = {f.__name__: f for f in (
    red_white_zigzag, navy_white_zigzag, green_white_zigzag, black_white_hoops,
    green_gold_hoops, sky_blue_white_hoops, maroon_white_hoops, black_gold_hoops, tricolour,
    black_gold, white_red_tips, white_blue_fade, orange_black_fade, black_white_tapa)}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, make in DESIGNS.items():
        path = os.path.join(OUT, name + ".png")
        make().picture().save(path, optimize=True)
        print("wrote", path)


if __name__ == "__main__":
    main()
