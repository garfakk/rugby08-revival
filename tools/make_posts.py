#!/usr/bin/env python3
"""Write the painted posts sets of the library (data/stadium_graphics/posts):
pictures in the posts layout of backend/stadium_dressing.py (128 x 1024: the
post's strip, then the crossbar's, upright). Run by hand after changing a
design:

    python3 tools/make_posts.py

Each design draws the post (top at y 0) and the crossbar lying flat, from
the post (x 0) to the middle and on through its middle part; the bar is
turned upright into its strip at the end. The post's picture wraps round
the post, so a stripe that climbs one period across its width turns into a
spiral.
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
NAVY, BLUE = (20, 40, 110), (30, 70, 170)
GREEN, GOLD = (0, 110, 60), (215, 160, 35)


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

    def spiral(self, colour, period, width):
        """A stripe winding up the post: it climbs `period` pixels across the
        post's width, `width` thick."""
        for y in range(-period, POST_H + period, period):
            pts = [(0, y), (POST_W, y - period), (POST_W, y - period + width), (0, y + width)]
            self.p.polygon([(x * SS, yy * SS) for x, yy in pts], fill=colour)

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


def red_spiral():
    d = Design(WHITE, WHITE, RED)
    d.spiral(RED, 160, 56)
    d.bar_bands([RED, WHITE], 140)
    return d


def navy_spiral():
    d = Design(WHITE, WHITE, NAVY)
    d.spiral(NAVY, 200, 48)
    return d


def black_hoops():
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


DESIGNS = {"red_spiral": red_spiral, "navy_spiral": navy_spiral, "black_hoops": black_hoops,
           "green_gold_hoops": green_gold_hoops, "tricolour": tricolour, "black_gold": black_gold}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, make in DESIGNS.items():
        path = os.path.join(OUT, name + ".png")
        make().picture().save(path, optimize=True)
        print("wrote", path)


if __name__ == "__main__":
    main()
