"""
shared/kit_files.py — packed kit textures
==========================================
A kit's 22 back-number textures are the same shirt but for the number, so the
data pack ships them as one lossless WebP sheet in the kit's folder
(kits_2024/home_back.webp): a grid GRID_COLS squares wide, shirt 1 top left,
left to right then top to bottom (22 backs of 512 x 512: 2048 x 3072, the
last two cells blank; a wider sheet compresses much worse). The square size
follows the sheet's width. An older sheet with the backs stacked in one
column (more than twice as tall as wide) still reads.
One sheet is about 1/8 of the 22 PNGs it replaces, pixel for pixel the same. The
older form, a folder of 22 PNG files named by a %-pattern
(kits_2024/home_back/home_back_%.png), still works everywhere: user imports
and edits use it.

Whatever needs one real image file per shirt (the game's FSH build, the
shirt-name printer, the 3D previews, the editor's thumbnails) asks for
back_pattern() / back_file(): a strip is unpacked once into the temp folder,
keyed by its path, size and mtime, and the %-pattern of those files comes
back. A %-pattern is returned unchanged.

Kit fronts ship as lossless WebP too. An older edit can still name the .png
a pack file used to be: migrate_kit_files() points such paths at the packed
file the data now has (only when the old file is gone and the new one is
there).
"""
import hashlib
import os

from PIL import Image

from shared.config import config

STRIP_EXT = ".webp"
BACK_COUNT = 22
GRID_COLS = 4
KIT_FILE_KEYS = ("frontKitFile", "backKitFile")
_CACHE = "kit_backs"


def is_strip(path) -> bool:
    """A back-number strip (not a %-pattern, not an .fsh)."""
    return bool(path) and "%" not in path and path.lower().endswith(STRIP_EXT)


def _layout(size):
    """(square size, columns, frames) of a sheet of `size` (w, h): a grid
    GRID_COLS wide, or an older single column."""
    w, h = size
    if not w or not h:
        return 0, 0, 0
    if is_column(size):                          # older layout
        return w, 1, h // w
    cell = w // GRID_COLS
    if not cell:
        return 0, 0, 0
    return cell, GRID_COLS, min(BACK_COUNT, GRID_COLS * (h // cell))


def is_column(size) -> bool:
    """The older one-column layout (repacked by pack_kit_textures.py)."""
    w, h = size
    return bool(w) and h > 2 * w


def strip_frames(path) -> list:
    """The sheet's square frames, shirt 1 first, as PIL images."""
    with Image.open(path) as im:
        im.load()
        cell, cols, count = _layout(im.size)
        return [im.crop(((i % cols) * cell, (i // cols) * cell,
                         (i % cols + 1) * cell, (i // cols + 1) * cell)) for i in range(count)]


def strip_frame_count(size) -> int:
    """Frames in a sheet of `size` (w, h)."""
    return _layout(size)[2]


def write_strip(images, path):
    """Lay `images` (same square size, shirt 1 first) out as a lossless WebP
    grid, GRID_COLS wide; RGB unless one of them uses its alpha. Cells past
    the last image stay blank."""
    arrays = [im.convert("RGBA") for im in images]
    w = arrays[0].width
    if any(im.size != (w, w) for im in arrays):
        raise ValueError("back numbers must all be squares of the same size")
    opaque = all(im.getchannel("A").getextrema() == (255, 255) for im in arrays)
    rows = -(-len(arrays) // GRID_COLS)
    sheet = Image.new("RGB" if opaque else "RGBA", (w * GRID_COLS, w * rows))
    for i, im in enumerate(arrays):
        sheet.paste(im.convert("RGB") if opaque else im, ((i % GRID_COLS) * w, (i // GRID_COLS) * w))
    sheet.save(path, "WEBP", lossless=True, quality=100, method=6, exact=True)


def _cache_dir(path):
    st = os.stat(path)
    key = f"{os.path.abspath(path)}|{st.st_size}|{st.st_mtime_ns}"
    return os.path.join(config.temp_directory, _CACHE, hashlib.sha1(key.encode()).hexdigest()[:16])


def _unpack(path, numbers):
    """Cache folder of `path` with the backs `numbers` (1-based) written."""
    folder = _cache_dir(path)
    wanted = [n for n in numbers if not os.path.isfile(os.path.join(folder, f"back_{n}.png"))]
    if wanted:
        os.makedirs(folder, exist_ok=True)
        frames = strip_frames(path)
        for n in wanted:
            if 1 <= n <= len(frames):
                out = os.path.join(folder, f"back_{n}.png")
                tmp = f"{out}.{os.getpid()}.tmp"
                frames[n - 1].save(tmp, "PNG", compress_level=1)
                os.replace(tmp, out)
    return folder


def back_pattern(path, count=BACK_COUNT):
    """Absolute %-pattern of one image file per shirt for `path` (a strip, or
    already a %-pattern). A missing or unreadable strip gives "" (logged by
    the caller's own missing-file handling)."""
    if not is_strip(path):
        return path
    try:
        return os.path.join(_unpack(path, range(1, count + 1)), "back_%.png")
    except OSError:
        return ""


def back_file(path, number=1):
    """Absolute path of shirt `number`'s back for `path` (strip or %-pattern)."""
    if not path:
        return ""
    if not is_strip(path):
        return path.replace("%", str(number), 1)
    try:
        return os.path.join(_unpack(path, [number]), f"back_{number}.png")
    except OSError:
        return ""


def _out_of_back_folder(rel):
    """x/home_back/home_back.webp -> x/home_back.webp: a strip needs no
    folder of its own (only a "..._back" folder is left)."""
    folder, name = os.path.split(rel)
    if folder and os.path.basename(folder).lower().endswith("back"):
        return os.path.join(os.path.dirname(folder), name).replace(os.sep, "/")
    return rel


def packed_rel(rel) -> str:
    """The name a kit file gets once packed: a back %-pattern
    (x/home_back/home_back_%.png) becomes its strip in the kit folder
    (x/home_back.webp), a strip still in a back folder moves up the same
    way, a .png front becomes its .webp. Anything else is returned as is."""
    if rel.endswith("_%.png"):
        return _out_of_back_folder(rel[:-len("_%.png")] + STRIP_EXT)
    if is_strip(rel):
        return _out_of_back_folder(rel)
    if "%" not in rel and rel.lower().endswith(".png"):
        return rel[:-4] + STRIP_EXT
    return rel


def migrate_kit_files(info, root) -> bool:
    """Point the kit files of a season block that no longer exist at their
    packed counterpart (an edit made before the pack was converted). True
    when the block changed."""
    changed = False
    for kit in ((info or {}).get("kits") or {}).values():
        if not isinstance(kit, dict):
            continue
        blocks = [kit] + [v for v in (kit.get("variants") or {}).values() if isinstance(v, dict)]
        for block in blocks:
            for key in KIT_FILE_KEYS:
                rel = block.get(key)
                if not rel or not isinstance(rel, str):
                    continue
                new = packed_rel(rel)
                if new == rel or os.path.isfile(os.path.join(root, rel.replace("%", "1", 1))):
                    continue
                if os.path.isfile(os.path.join(root, new)):
                    block[key] = new
                    changed = True
    return changed
