#!/usr/bin/env python3
"""Write the painted posts sets of the library (data/stadium_graphics/posts):
pictures in the posts layout of backend/stadium_dressing.py (the goal seen
from the front, 768 x 1024). Run by hand after changing a design:

    python3 tools/make_posts.py

A post's picture wraps round the post, so a stripe that climbs one period
across the post's width turns into a spiral.
"""
import os
import sys

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.join(ROOT, "src")]

from backend.stadium_dressing import (POSTS_SIZE, POST_X, RIGHT_POST_X,  # noqa: E402
                                      XBAR_Y, XBAR_MIDDLE_X)

OUT = os.path.join(ROOT, "data", "stadium_graphics", "posts")
SS = 4                                   # drawn larger, then shrunk: smooth edges

WHITE, RED, BLACK = (240, 240, 240), (200, 30, 40), (25, 25, 25)
NAVY, BLUE = (20, 40, 110), (30, 70, 170)
GREEN, GOLD = (0, 110, 60), (215, 160, 35)


def _canvas():
    return Image.new("RGBA", (POSTS_SIZE[0] * SS, POSTS_SIZE[1] * SS), (0, 0, 0, 0))


def _box(x0, y0, x1, y1):
    return (x0 * SS, y0 * SS, x1 * SS - 1, y1 * SS - 1)


def _posts(draw, colour):
    for x0, x1 in (POST_X, RIGHT_POST_X):
        draw.rectangle(_box(x0, 0, x1, POSTS_SIZE[1]), fill=colour)


def _bar(draw, colour, middle=None):
    draw.rectangle(_box(POST_X[1], XBAR_Y[0], RIGHT_POST_X[0], XBAR_Y[1]), fill=colour)
    if middle:
        draw.rectangle(_box(XBAR_MIDDLE_X[0], XBAR_Y[0], XBAR_MIDDLE_X[1], XBAR_Y[1]), fill=middle)


def _post_hoops(draw, colours, height, top=0, bottom=None):
    bottom = POSTS_SIZE[1] if bottom is None else bottom
    for i, y in enumerate(range(top, bottom, height)):
        for x0, x1 in (POST_X, RIGHT_POST_X):
            draw.rectangle(_box(x0, y, x1, min(bottom, y + height)), fill=colours[i % len(colours)])


def _bar_bands(draw, colours, width):
    """Bands across the crossbar, from each post in (the bar's right half
    mirrors its left)."""
    for i, x in enumerate(range(POST_X[1], XBAR_MIDDLE_X[0], width)):
        draw.rectangle(_box(x, XBAR_Y[0], min(XBAR_MIDDLE_X[0], x + width), XBAR_Y[1]),
                       fill=colours[i % len(colours)])


def _spiral(image, colour, period, width):
    """A stripe winding up each post: climbs `period` pixels across the
    post's width, `width` thick."""
    draw = ImageDraw.Draw(image)
    w = POST_X[1] - POST_X[0]
    for x0, _ in (POST_X, RIGHT_POST_X):
        for y in range(-period, POSTS_SIZE[1] + period, period):
            pts = [(x0, y), (x0 + w, y - period), (x0 + w, y - period + width), (x0, y + width)]
            draw.polygon([(px * SS, py * SS) for px, py in pts], fill=colour)
    return image


def red_spiral():
    image = _canvas()
    draw = ImageDraw.Draw(image)
    _posts(draw, WHITE)
    _spiral(image, RED, 160, 56)
    _bar(draw, WHITE)
    _bar_bands(draw, [RED, WHITE], 40)
    draw.rectangle(_box(XBAR_MIDDLE_X[0], XBAR_Y[0], XBAR_MIDDLE_X[1], XBAR_Y[1]), fill=RED)
    return image


def navy_spiral():
    image = _canvas()
    draw = ImageDraw.Draw(image)
    _posts(draw, WHITE)
    _spiral(image, NAVY, 200, 48)
    _bar(draw, WHITE, NAVY)
    return image


def black_hoops():
    image = _canvas()
    draw = ImageDraw.Draw(image)
    _post_hoops(draw, [BLACK, WHITE], 64)
    _bar(draw, WHITE)
    _bar_bands(draw, [BLACK, WHITE], 48)
    draw.rectangle(_box(XBAR_MIDDLE_X[0], XBAR_Y[0], XBAR_MIDDLE_X[1], XBAR_Y[1]), fill=BLACK)
    return image


def green_gold_hoops():
    image = _canvas()
    draw = ImageDraw.Draw(image)
    _post_hoops(draw, [GREEN, GOLD], 96)
    _bar(draw, GOLD, GREEN)
    return image


def tricolour():
    """White posts with a blue, white and red band at the top of each post
    and in the middle of the bar."""
    image = _canvas()
    draw = ImageDraw.Draw(image)
    _posts(draw, WHITE)
    _post_hoops(draw, [BLUE, WHITE, RED], 48, top=96, bottom=96 + 3 * 48)
    _bar(draw, WHITE)
    third = (XBAR_MIDDLE_X[1] - XBAR_MIDDLE_X[0]) / 3
    for i, colour in enumerate((BLUE, WHITE, RED)):
        x = XBAR_MIDDLE_X[0] + i * third
        draw.rectangle((round(x * SS), XBAR_Y[0] * SS, round((x + third) * SS) - 1, XBAR_Y[1] * SS - 1),
                       fill=colour)
    return image


def black_gold():
    image = _canvas()
    draw = ImageDraw.Draw(image)
    _posts(draw, BLACK)
    _bar(draw, BLACK, GOLD)
    return image


DESIGNS = {"red_spiral": red_spiral, "navy_spiral": navy_spiral, "black_hoops": black_hoops,
           "green_gold_hoops": green_gold_hoops, "tricolour": tricolour, "black_gold": black_gold}


def main():
    os.makedirs(OUT, exist_ok=True)
    for name, make in DESIGNS.items():
        image = make().resize(POSTS_SIZE, Image.LANCZOS)
        # the bar's right half as the game shows it: its left half mirrored
        left = image.crop((POST_X[1], XBAR_Y[0], XBAR_MIDDLE_X[0], XBAR_Y[1]))
        image.paste(left.transpose(Image.FLIP_LEFT_RIGHT), (XBAR_MIDDLE_X[1], XBAR_Y[0]))
        path = os.path.join(OUT, name + ".png")
        image.save(path, optimize=True)
        print("wrote", path)


if __name__ == "__main__":
    main()
