"""
shared/shirt_names.py — player names printed on the back of the shirt
=======================================================================
The game has no shirt names: a kit's back is a series of 22 textures
(backKitFile, "kit_back_%.png"), texture N being the back of shirt N. So a
name is baked into each player's own back texture when the match files are
written (backend/game_files_processor.py), and the team editor previews the
very same images (screens/team_tabs.py ShirtNamesTab) — one renderer, so what
the editor shows is what the game gets.

Where it is configured
  team season  "shirtNames": the lettering, shared by every kit of the season
      enabled    bool
      text       "surname" | "initial" (J. SMITH) | "display" (in-game name) | "full"
      case       "upper" | "asis"
      font       a bundled font's name (BUILTIN_FONTS) or a .ttf/.otf path
                 relative to the team folder
      size       letter (cap) height, in pixels of a 512 px texture
      spacing    extra space between letters, % of the letter height
      arch       curve, % of the letter height (+ middle up, - middle down)
      placement  "auto": the free space above the number, else below it;
                 "above" / "below" the number (these follow the number when
                 the kit changes) or "custom" (the `area` below)
      area       [x, y, w, h], fractions of the texture (placement "custom")
      gap        distance to the number, pixels of a 512 px texture
  kit          "shirtName": the colours, which usually differ per kit
      color      "auto" (the colour of the kit's own numbers) or "#rrggbb"
      outline    "" (none) or "#rrggbb"
      outlineWidth  pixels of a 512 px texture
  player       "shirt_name": what to print instead of the generated text
                 (an empty string is ignored)

Everything is optional: a missing or malformed value falls back to its
default (normalise_style), so a hand-edited file can't break a match.
"""
import hashlib
import os
import re
import unicodedata

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from shared.log import get_logger

log = get_logger(__name__)

REF = 512                       # sizes are given in pixels of a 512 px texture
SUPERSAMPLE = 3                 # letters drawn this much larger, then scaled down
MIN_CONDENSE = 0.72             # a long name is squeezed down to this width, then made smaller

TEXT_MODES = ("surname", "initial", "display", "full")
CASES = ("upper", "asis")
PLACEMENTS = ("auto", "above", "below", "custom")

# name -> (file in assets/fonts, variable-font style or None)
BUILTIN_FONTS = {
    "Barlow Condensed": ("BarlowCondensed-ExtraBold.ttf", None),
    "Oswald": ("Oswald-Variable.ttf", "Bold"),
    "Anton": ("Anton-Regular.ttf", None),
    "Bebas Neue": ("BebasNeue-Regular.ttf", None),
    "Saira Condensed": ("SairaCondensed-Bold.ttf", None),
    "Teko": ("Teko-Variable.ttf", "SemiBold"),
    "Graduate": ("Graduate-Regular.ttf", None),
    "Alfa Slab One": ("AlfaSlabOne-Regular.ttf", None),
    "Russo One": ("RussoOne-Regular.ttf", None),
    "Black Ops One": ("BlackOpsOne-Regular.ttf", None),
}
DEFAULT_FONT = "Barlow Condensed"
FONT_EXTS = (".ttf", ".otf")

SEASON_DEFAULTS = {
    "enabled": False,
    "text": "surname",
    "case": "upper",
    "font": DEFAULT_FONT,
    "size": 30,
    "spacing": 6,
    "arch": 0,
    "placement": "auto",
    "area": None,
    "gap": 8,
}
KIT_DEFAULTS = {
    "color": "auto",
    "outline": "",
    "outlineWidth": 0,
}
LIMITS = {"size": (8, 120), "spacing": (-20, 60), "arch": (-60, 60), "gap": (-40, 120),
          "outlineWidth": (0, 12)}

_HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


# ── configuration ─────────────────────────────────────────────────────────
def fonts_directory():
    from shared.config import config
    return os.path.join(config.mod_src_directory, "assets", "fonts")


def parse_color(value):
    """'#rrggbb' (or 'rrggbb') -> (r, g, b); None for anything else."""
    m = _HEX.match(str(value or "").strip())
    if not m:
        return None
    h = m.group(1)
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def color_hex(rgb):
    return "#%02x%02x%02x" % tuple(int(c) for c in rgb[:3])


def _number(value, default, lo, hi):
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if v != v:          # NaN
        return default
    return max(lo, min(hi, v))


def _area(value):
    """A valid [x, y, w, h] (fractions, inside the texture) or None."""
    try:
        x, y, w, h = (float(v) for v in value)
    except (TypeError, ValueError):
        return None
    if not (w > 0.01 and h > 0.005):
        return None
    w, h = min(w, 1.0), min(h, 1.0)
    x = max(0.0, min(1.0 - w, x))
    y = max(0.0, min(1.0 - h, y))
    return [x, y, w, h]


def normalise_style(season_block=None, kit_block=None):
    """The season's "shirtNames" and the kit's "shirtName" merged into one
    complete, valid style dict (defaults for whatever is missing or bad)."""
    season_block = season_block if isinstance(season_block, dict) else {}
    kit_block = kit_block if isinstance(kit_block, dict) else {}
    out = dict(SEASON_DEFAULTS)
    out.update(KIT_DEFAULTS)
    out["enabled"] = bool(season_block.get("enabled", False))
    for key, options in (("text", TEXT_MODES), ("case", CASES), ("placement", PLACEMENTS)):
        if season_block.get(key) in options:
            out[key] = season_block[key]
    font = str(season_block.get("font") or "").strip()
    out["font"] = font or DEFAULT_FONT
    for key in ("size", "spacing", "arch", "gap"):
        lo, hi = LIMITS[key]
        out[key] = _number(season_block.get(key), SEASON_DEFAULTS[key], lo, hi)
    out["area"] = _area(season_block.get("area"))
    if out["placement"] == "custom" and out["area"] is None:
        out["placement"] = "auto"
    color = kit_block.get("color", "auto")
    out["color"] = color_hex(parse_color(color)) if parse_color(color) else "auto"
    outline = parse_color(kit_block.get("outline"))
    out["outline"] = color_hex(outline) if outline else ""
    lo, hi = LIMITS["outlineWidth"]
    out["outlineWidth"] = _number(kit_block.get("outlineWidth"), 0, lo, hi)
    return out


def is_font_file(value):
    return str(value or "").lower().endswith(FONT_EXTS)


def resolve_font(value, team_folder=""):
    """(path, variation, found) for a style's font value. A bundled name or
    a team-folder font file; anything unusable falls back to the default
    bundled font with found=False (the editor flags it)."""
    value = str(value or "").strip() or DEFAULT_FONT
    if is_font_file(value):
        path = value if os.path.isabs(value) else os.path.join(team_folder or "", value)
        if os.path.isfile(path):
            return path, None, True
    elif value in BUILTIN_FONTS:
        fname, variation = BUILTIN_FONTS[value]
        path = os.path.join(fonts_directory(), fname)
        if os.path.isfile(path):
            return path, variation, True
    fname, variation = BUILTIN_FONTS[DEFAULT_FONT]
    return os.path.join(fonts_directory(), fname), variation, False


def team_font_files(team_folder):
    """Font files found in a team folder, relative paths with '/'."""
    found = []
    if team_folder and os.path.isdir(team_folder):
        for dirpath, dirnames, filenames in os.walk(team_folder):
            dirnames.sort()
            for f in sorted(filenames):
                if f.lower().endswith(FONT_EXTS):
                    rel = os.path.relpath(os.path.join(dirpath, f), team_folder)
                    found.append(rel.replace(os.sep, "/"))
    return found


# ── the text ──────────────────────────────────────────────────────────────
def shirt_text(player, mode="surname", case="upper"):
    """What goes on a player's back. `player` is a player record (or the
    flattened record+season dict) — first_name, last_name, display_name and
    the optional shirt_name override are read."""
    if not player:
        return ""
    override = str(player.get("shirt_name") or "").strip()
    if override:
        text = override
    else:
        first = str(player.get("first_name") or "").strip()
        last = str(player.get("last_name") or "").strip()
        display = str(player.get("display_name") or player.get("name") or "").strip()
        if not last and display:
            # "J.Smith" / "J. Smith" -> surname "Smith"
            last = re.sub(r"^([^\W\d_]{1,3}\.\s*)+", "", display).strip() or display
        if mode == "display":
            text = display or last
        elif mode == "full":
            text = f"{first} {last}".strip()
        elif mode == "initial" and first:
            text = f"{first[0]}. {last}"
        else:
            text = last
    text = re.sub(r"\s+", " ", text).strip()
    return text.upper() if case == "upper" else text


# ── the kit's numbers ─────────────────────────────────────────────────────
_ANALYSIS_CACHE = {}
_PROBE = 256        # images are compared at this size


def _stamp(path):
    try:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path, None, None)


def _load_rgb(path, size=_PROBE):
    with Image.open(path) as im:
        return np.asarray(im.convert("RGBA").convert("RGB").resize((size, size), Image.BILINEAR),
                          dtype=np.int16)


def _grow(y0, y1, x0, x1, by):
    """Index of the box (probe pixels) grown by `by` on every side."""
    return (slice(max(0, int(y0) - by), min(_PROBE, int(y1) + 1 + by)),
            slice(max(0, int(x0) - by), min(_PROBE, int(x1) + 1 + by)))


def _palette(pixels, k=3, rounds=8):
    """Up to `k` main colours of `pixels` ((n, 3) float): a small k-means."""
    lum = pixels @ np.array([0.299, 0.587, 0.114], np.float32)
    order = np.argsort(lum)
    centres = pixels[order[np.linspace(0, len(order) - 1, k).astype(int)]].copy()
    for _ in range(rounds):
        label = ((pixels[:, None, :] - centres[None]) ** 2).sum(-1).argmin(1)
        for i in range(k):
            if (label == i).any():
                centres[i] = np.median(pixels[label == i], axis=0)
    # fewer real colours than k: the same colour twice is one colour
    kept = []
    for c in centres:
        if all(np.abs(c - other).sum() > 60 for other in kept):
            kept.append(c)
    return np.array(kept, dtype=np.float32)


def _shares(pixels, centres):
    if not len(pixels) or not len(centres):
        return np.zeros(len(centres))
    label = ((pixels[:, None, :] - centres[None]) ** 2).sum(-1).argmin(1)
    return np.bincount(label, minlength=len(centres)) / len(pixels)


def _ink(stack, still_pixels, ring_sides):
    """(ink, shirt, shirt colours) from `stack` — (images, pixels, 3), the
    pixels where the numbers differ —, the pixels inside the numbers' extent
    that never change and the pixels just outside it (a list: above, below,
    left, right). Every number
    pixel shows the ink in some image, while the shirt is what the other two
    mostly are: the ink is the colour with the most coverage beyond its
    share of those. ink is None when it can't be told from the shirt."""
    rng = np.random.default_rng(0)

    def sample(px, n):
        return px[rng.choice(len(px), n, replace=False)] if len(px) > n else px

    if stack.shape[1] > 6000:
        stack = stack[:, rng.choice(stack.shape[1], 6000, replace=False)]
    ring_sides = [sample(px, 1000) for px in ring_sides]
    ring_pixels = np.concatenate(ring_sides)
    still_pixels = sample(still_pixels, 3000)
    flat = stack.reshape(-1, 3)
    centres = _palette(flat)
    near = np.sqrt(((stack[:, :, None, :] - centres[None, None]) ** 2).sum(-1))   # (k, n, c)
    coverage = (near < 45).any(0).mean(0)          # number pixels showing that colour somewhere
    shirtness = (_shares(still_pixels, centres) + _shares(ring_pixels, centres)) / 2
    ink_k = int(np.argmax(coverage - shirtness))
    others = np.arange(len(centres)) != ink_k
    ink = np.median(flat[near.reshape(-1, len(centres)).argmin(1) == ink_k], axis=0)
    # the shirt's own colours (for the free-space search): around the numbers
    # on at least three sides — a logo next to them is on one side only
    around = np.concatenate([still_pixels, ring_pixels]) if len(ring_pixels) else flat
    palette = _palette(around)
    share = _shares(around, palette)
    sides = sum((_shares(px, palette) > 0.08) for px in ring_sides if len(px))
    shirt = palette[share.argmax()]
    if others.any() and np.abs(ink - shirt).sum() < 60:
        shirt = centres[others][shirtness[others].argmax()]
    distinct = np.abs(palette - ink).sum(1) > 60
    shirt_colours = palette[(share > 0.1) & (sides >= 3) & distinct]
    if not len(shirt_colours):
        shirt_colours = shirt[None]
    if np.abs(ink - shirt).sum() < 60:
        return None, shirt, shirt_colours
    return ink, shirt, shirt_colours


def analyse_numbers(paths):
    """{'box': (x0, y0, x1, y1) fractions of the numbers' extent or None,
        'ink': (r, g, b) the numbers' colour or None,
        'background': (r, g, b) the shirt around them or None,
        'clutter': per texture row (top to bottom, _PROBE rows), the share
                   of the name band covered by something not the shirt}
    from a few of the kit's back textures: what differs between them is the
    number. `paths` is the list of existing back images (any order)."""
    paths = [p for p in paths if p and os.path.isfile(p)]
    key = tuple(_stamp(p) for p in paths)
    if key in _ANALYSIS_CACHE:
        return _ANALYSIS_CACHE[key]
    result = {"box": None, "ink": None, "background": None}
    try:
        # a handful spread over the series: 1, 8, 10, 22… cover every digit shape
        picks = paths if len(paths) <= 6 else [paths[i] for i in
                                               sorted({0, 7, 9, 14, len(paths) - 1, len(paths) // 2})]
        images = [_load_rgb(p) for p in picks]
        if len(images) >= 2:
            diff = np.zeros(images[0].shape[:2], bool)
            for im in images[1:]:
                diff |= np.abs(im - images[0]).sum(-1) > 60
            ys, xs = np.nonzero(diff)
            if len(xs) > 20:
                # trim stray pixels (compression noise) from the extent
                x0, x1 = np.percentile(xs, [0.5, 99.5])
                y0, y1 = np.percentile(ys, [0.5, 99.5])
                n = float(_PROBE)
                result["box"] = (x0 / n, y0 / n, (x1 + 1) / n, (y1 + 1) / n)
                still = np.zeros(diff.shape, bool)
                still[_grow(y0, y1, x0, x1, 0)] = True
                for im in images[1:]:           # strictly unchanged: no faint edges either
                    still &= np.abs(im - images[0]).sum(-1) <= 20
                ys_, xs_ = _grow(y0, y1, x0, x1, 4)
                outer_y, outer_x = _grow(y0, y1, x0, x1, 12)
                first = images[0].astype(np.float32)
                ring_sides = [first[outer_y.start:ys_.start, xs_].reshape(-1, 3),      # above
                              first[ys_.stop:outer_y.stop, xs_].reshape(-1, 3),        # below
                              first[ys_, outer_x.start:xs_.start].reshape(-1, 3),      # left
                              first[ys_, xs_.stop:outer_x.stop].reshape(-1, 3)]        # right
                stack = np.stack([im[diff] for im in images]).astype(np.float32)
                ink, shirt, shirt_colours = _ink(stack, first[still], ring_sides)
                result["background"] = tuple(int(c) for c in shirt)
                if ink is not None:
                    result["ink"] = tuple(int(c) for c in ink)
                # How cluttered (logos, text) each row is across the band a
                # name would take: what "auto" placement looks for free space in.
                bx0, bx1 = _band(result["box"])
                band = images[0][:, int(bx0 * n):max(int(bx0 * n) + 1, int(bx1 * n))].astype(np.float32)
                dist = np.sqrt(((band[:, :, None, :] - shirt_colours[None, None]) ** 2).sum(-1)).min(-1)
                result["clutter"] = [round(float(v), 3) for v in (dist > 70).mean(1)]
        elif images:
            result["background"] = tuple(int(c) for c in np.median(images[0].reshape(-1, 3), axis=0))
    except Exception as e:       # analysis is a convenience: never fatal
        log.warning(f"shirt names: could not analyse the back numbers: {e}")
    if len(_ANALYSIS_CACHE) > 64:
        _ANALYSIS_CACHE.clear()
    _ANALYSIS_CACHE[key] = result
    return result


def contrast_color(rgb):
    """Black or white, whichever reads better on `rgb`."""
    if rgb is None:
        return (0, 0, 0)
    r, g, b = rgb
    return (20, 20, 20) if 0.299 * r + 0.587 * g + 0.114 * b > 140 else (245, 245, 245)


def text_color(style, analysis):
    rgb = parse_color(style.get("color"))
    if rgb:
        return rgb
    return analysis.get("ink") or contrast_color(analysis.get("background"))


def _band(box):
    """(x0, x1) fractions of the band a name takes across the shirt: centred
    on the numbers, a little wider than them."""
    x0, _, x1, _ = box
    w = max(0.5, min(0.84, (x1 - x0) * 1.9))
    cx = max(w / 2, min(1 - w / 2, (x0 + x1) / 2))
    return cx - w / 2, cx + w / 2


CLUTTER = 0.06      # a row more covered than this (a logo, not a seam) is not free


def _free_run(clutter, start, step):
    """Fraction of the texture height free of clutter from row fraction
    `start`, going up (step -1) or down (step +1)."""
    n = len(clutter)
    row = int(start * n) if step > 0 else int(np.ceil(start * n)) - 1
    free = 0
    while 0 <= row < n and clutter[row] < CLUTTER:
        free += 1
        row += step
    return free / n


def name_area(style, analysis):
    """[x, y, w, h] fractions where the name goes: the custom area, or a band
    above/below the kit's numbers (a sensible spot when they can't be found).
    "auto" takes the band above the number if it is free of logos, else the
    one below, else the side with more room, the name made smaller to fit it
    (down to half its size: below that, it goes above at full size)."""
    if style.get("placement") == "custom" and style.get("area"):
        return list(style["area"])
    box = analysis.get("box") or (0.32, 0.28, 0.68, 0.62)
    x0, y0, x1, y1 = box
    bx0, bx1 = _band(box)
    h = min(0.3, style["size"] * 1.5 / REF)
    gap = style["gap"] / REF
    placement = style.get("placement")
    if placement not in ("above", "below"):
        clutter = analysis.get("clutter")
        placement = "above"
        if clutter:
            above = min(h, _free_run(clutter, y0 - gap, -1))
            below = min(h, _free_run(clutter, y1 + gap, +1))
            if above < h * 0.95:
                if below >= h * 0.95 or below > above:
                    placement, room = "below", below
                else:
                    room = above
                if room >= h * 0.5:
                    h = room
                else:
                    placement = "above"
    y = y1 + gap if placement == "below" else y0 - gap - h
    return _area([bx0, y, bx1 - bx0, h])


def area_overlap(area, analysis):
    """Share of the area's rows taken by a logo or other print (0..1, by the
    analysis' clutter profile): above ~0.25 the name is printed over it."""
    clutter = analysis.get("clutter")
    if not clutter or not area:
        return 0.0
    n = len(clutter)
    rows = clutter[max(0, int(area[1] * n)):max(int(area[1] * n) + 1, int(np.ceil((area[1] + area[3]) * n)))]
    return float(np.mean([r >= CLUTTER for r in rows])) if rows else 0.0


# ── drawing ───────────────────────────────────────────────────────────────
_FONT_CACHE = {}


def _font(path, variation, px):
    key = (path, variation, int(px))
    f = _FONT_CACHE.get(key)
    if f is None:
        f = ImageFont.truetype(path, max(1, int(px)))
        if variation:
            try:
                f.set_variation_by_name(variation)
            except Exception:
                pass
        if len(_FONT_CACHE) > 256:
            _FONT_CACHE.clear()
        _FONT_CACHE[key] = f
    return f


def _cap_ratio(path, variation):
    """Cap height / font size for a font (measured on 'H')."""
    f = _font(path, variation, 200)
    box = f.getbbox("H")
    return max(0.3, (box[3] - box[1]) / 200.0)


def _glyph(font, ch):
    mask = font.getmask(ch)
    return mask.size, bytes(mask)


def _missing(font, ch, notdef):
    if ch.isspace():
        return False
    try:
        return _glyph(font, ch) == notdef
    except Exception:
        return True


def displayable(text, path, variation=None):
    """`text` with the characters the font has no glyph for replaced by their
    plain letter (É -> E) or dropped."""
    font = _font(path, variation, 64)
    try:
        notdef = _glyph(font, "")      # private use: no font here has it
    except Exception:
        notdef = None
    out = []
    for ch in text:
        if notdef is not None and _missing(font, ch, notdef):
            base = "".join(c for c in unicodedata.normalize("NFKD", ch)
                           if not unicodedata.combining(c))
            out.append(base if base and base != ch and not _missing(font, base[0], notdef) else "")
        else:
            out.append(ch)
    return "".join(out)


def render_text_layer(size, text, style, font_path, variation=None, area=None, color=(0, 0, 0)):
    """RGBA image of `size` (w, h): transparent, with `text` lettered into
    `area` (fractions) using `style`. Long names are condensed, then made
    smaller, so they always fit the area's width."""
    W, H = size
    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    text = displayable(text or "", font_path, variation).strip()
    if not text or not area:
        return layer
    sy = H / REF
    ax, ay, aw, ah = area[0] * W, area[1] * H, area[2] * W, area[3] * H
    ss = SUPERSAMPLE
    cap = min(style["size"] * sy, ah)
    arch = style["arch"] / 100.0 * cap
    # letters must fit the area's height with the arch and outline included
    stroke = style["outlineWidth"] * sy if style.get("outline") else 0.0
    fit_h = ah - abs(arch) - 2 * stroke
    if fit_h < cap:
        cap = max(2.0, fit_h)
    ratio = _cap_ratio(font_path, variation)
    spacing = style["spacing"] / 100.0

    def measure(cap_px):
        f = _font(font_path, variation, cap_px / ratio * ss)
        gaps = spacing * cap_px * ss
        widths = [f.getlength(ch) for ch in text]
        return f, widths, gaps, sum(widths) + gaps * (len(text) - 1) + 2 * stroke * ss

    f, widths, gaps, natural = measure(cap)
    target = aw * ss
    condense = 1.0
    if natural > target:
        condense = max(MIN_CONDENSE, target / natural)
        if natural * condense > target:
            shrink = target / (natural * condense)
            cap *= shrink
            arch *= shrink
            f, widths, gaps, natural = measure(cap)
        condense = min(condense, target / natural)      # exact fit, whatever rounding did

    # draw the letters on a supersampled strip: baseline at a fixed line
    s_stroke = int(round(stroke * ss))
    ascent, descent = f.getmetrics()
    pad = s_stroke + 4 * ss
    arch_ss = arch * ss
    strip_w = int(natural + 2 * pad) + 2
    strip_h = int(ascent + descent + 2 * pad + abs(arch_ss)) + 2
    strip = Image.new("RGBA", (strip_w, strip_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(strip)
    top = pad + max(0.0, arch_ss)            # room above for the raised middle
    fill = tuple(color[:3]) + (255,)
    outline = parse_color(style.get("outline"))
    x = pad + s_stroke
    for ch, w in zip(text, widths):
        kwargs = {}
        if s_stroke and outline:
            kwargs = {"stroke_width": s_stroke, "stroke_fill": tuple(outline) + (255,)}
        draw.text((x, top), ch, font=f, fill=fill, **kwargs)
        x += w + gaps

    # arch: each column moved up/down along a parabola (bridge warp)
    if abs(arch_ss) >= 0.5:
        arr = np.asarray(strip)
        out = np.zeros_like(arr)
        x_first, x_last = pad, pad + natural
        span = max(1.0, (x_last - x_first) / 2.0)
        mid = (x_first + x_last) / 2.0
        for col in range(strip_w):
            u = (col - mid) / span
            shift = int(round(arch_ss * (1.0 - min(1.0, u * u))))
            if shift > 0:
                out[:-shift, col] = arr[shift:, col]
            elif shift < 0:
                out[-shift:, col] = arr[:shift, col]
            else:
                out[:, col] = arr[:, col]
        strip = Image.fromarray(out, "RGBA")

    # scale down (and condense) to texture pixels, place in the area
    out_w = max(1, int(round(strip_w * condense / ss)))
    out_h = max(1, int(round(strip_h / ss)))
    small = strip.resize((out_w, out_h), Image.LANCZOS)
    # vertical: the letters' cap band, arch included, centred in the area
    cap_top = top + f.getbbox("H")[1] - max(0.0, arch_ss)      # strip pixels
    y = ay + (ah - (cap + abs(arch))) / 2.0 - cap_top / ss
    # horizontal: the letters (pad .. pad + natural on the strip) centred
    x = ax + (aw - natural * condense / ss) / 2.0 - pad * condense / ss
    _paste_clipped(layer, small, int(round(x)), int(round(y)))
    return layer


def _paste_clipped(layer, img, x, y):
    """alpha_composite that tolerates a negative offset / overflow."""
    W, H = layer.size
    sx0, sy0 = max(0, -x), max(0, -y)
    dx0, dy0 = max(0, x), max(0, y)
    w = min(img.width - sx0, W - dx0)
    h = min(img.height - sy0, H - dy0)
    if w > 0 and h > 0:
        layer.alpha_composite(img.crop((sx0, sy0, sx0 + w, sy0 + h)), (dx0, dy0))


class BackPrinter:
    """Letters names onto one kit's back textures.

        printer = BackPrinter(style, font_path, back_paths, variation)
        image = printer.render(index, "SMITH")     # PIL RGBA, or None

    `back_paths` is the kit's 22 back images in shirt order (index 0 = shirt 1);
    the numbers' position and colour are worked out from them once."""

    def __init__(self, style, font_path, back_paths, variation=None):
        self.style = style
        self.font_path = font_path
        self.variation = variation
        self.back_paths = list(back_paths)
        self.analysis = analyse_numbers(self.back_paths)
        self.area = name_area(style, self.analysis)
        self.color = text_color(style, self.analysis)

    def back_path(self, index):
        if 0 <= index < len(self.back_paths):
            return self.back_paths[index]
        return None

    def render(self, index, text, base=None):
        """The back texture of shirt index+1 with `text` on it (a PIL RGBA
        image at the texture's own size), or None if there is no texture."""
        path = self.back_path(index)
        if base is None:
            if not path or not os.path.isfile(path):
                return None
            with Image.open(path) as im:
                base = im.convert("RGBA")
        else:
            base = base.convert("RGBA")
        if not text:
            return base
        layer = render_text_layer(base.size, text, self.style, self.font_path, self.variation,
                                  self.area, self.color)
        base.alpha_composite(layer)
        return base

    def cache_name(self, index, text):
        """A file name identifying render(index, text)'s result."""
        h = hashlib.sha1(repr((sorted(self.style.items(), key=lambda kv: kv[0]),
                               _stamp(self.font_path), self.variation,
                               _stamp(self.back_path(index) or ""), text)).encode("utf-8"))
        return h.hexdigest()[:20] + ".png"


def expand_back_paths(pattern_path, count=22):
    """Absolute %-pattern -> the `count` image paths, shirt order."""
    if not pattern_path or "%" not in pattern_path:
        return []
    return [pattern_path.replace("%", str(i), 1) for i in range(1, count + 1)]


def season_style_for(info, kit):
    """Style for a team season block and one (resolved) kit dict."""
    return normalise_style((info or {}).get("shirtNames"), (kit or {}).get("shirtName"))
