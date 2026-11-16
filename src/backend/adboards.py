"""
backend/adboards.py — the stadium ad boards the game is given
==============================================================
The game looks each stadium's ad textures up by name (the stadium's entry in
xml/config/stadiumadsandpads). Two board layouts exist and a stadium model
only fits the one it was built for:

  World Cup  ads0 ads1 ads4 ads5 (+ads7 ads8)  256x256 sheets, 3 ads stacked
             ads2 ads3                         128x256 strips, 3 ads stacked
             ads6                              256x256 board frame (no ad)
  Standard   ads0 ads1 ads2 (+ads4 ads5)       256x256 sheets, 3 ads stacked
             ads3                              128x128 board frame (no ad)

Giving a Standard ground the World Cup file put a sponsor strip on its frame
and a strip-sized ad on its sheets: the textures mapped wrongly. The mod's
stadium XML therefore names one file per layout (World_Cup\\World_Cup and
Standard\\France_Standard); this module builds both from ONE ad set the
player picked, and the game gets each as a loose file over the archive's.

An ad set is a FSH (either layout), a folder of images (each image one ad,
repeated over every ad row), or a folder with a FSH and images named after
its boards (ads0.png ...) that replace those boards.
"""
import hashlib
import os
import re
import struct

from PIL import Image

from backend import mod_utils as mu
from shared.log import get_logger

log = get_logger(__name__)

WC_NAME = "world_cup/world_cup"
STD_NAME = "standard/france_standard"

# layout -> board tags by role, in the order a set's boards are handed out
LAYOUTS = {
  "wc": {"sheets": ["ads0", "ads1", "ads4", "ads5", "ads7", "ads8"],
         "strips": ["ads2", "ads3"], "frame": "ads6"},
  "std": {"sheets": ["ads0", "ads1", "ads2", "ads4", "ads5"],
          "strips": [], "frame": "ads3"},
}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp", ".gif")
SHEET_SIZE = (256, 256)
STRIP_SIZE = (128, 256)
ROWS = 3
_SETS_NEEDED = 6               # sheets and strips an image set must make


def game_filename(name):
  """The loose file name next to the exe that replaces the archive's ad file
  `name` ("world_cup/world_cup"): the md5 of its game path + ".fsh"."""
  return hashlib.md5(f"stadiums/adboards/{name}".lower().encode()).hexdigest() + ".fsh"


def _row_heights(total, rows=ROWS):
  heights = [total // rows] * rows
  heights[-1] += total - sum(heights)
  return heights


def _fit(image, size):
  """`image` (PIL) as exactly `size`: stretched when its shape is close to it,
  else shrunk to fit and centred on its own corner colour."""
  image = image.convert("RGBA")
  w, h = size
  if abs((image.width / image.height) / (w / h) - 1) < 0.2:
    return image.resize(size, Image.LANCZOS)
  scale = min(w / image.width, h / image.height)
  inner = (max(1, round(image.width * scale)), max(1, round(image.height * scale)))
  bg = image.getpixel((0, 0))
  out = Image.new("RGBA", size, bg[:3] + (255,))
  out.paste(image.resize(inner, Image.LANCZOS), ((w - inner[0]) // 2, (h - inner[1]) // 2))
  return out


def _stack(rows, size):
  """One board of `size` from `ROWS` ad images, one per band."""
  out = Image.new("RGBA", size, (255, 255, 255, 255))
  y = 0
  for row, height in zip(rows, _row_heights(size[1])):
    out.paste(_fit(row, (size[0], height)), (0, y))
    y += height
  return out


def _bands(sheet):
  y, out = 0, []
  for height in _row_heights(sheet.height):
    out.append(sheet.crop((0, y, sheet.width, y + height)))
    y += height
  return out


class Board:
  """One texture of a set: its FSH block, its picture, or both."""

  def __init__(self, block=None, image=None):
    self.block = block
    self._image = image

  @property
  def size(self):
    if self.block is not None:
      return struct.unpack_from("<HH", self.block, 4)
    return self._image.size

  def image(self):
    if self._image is None:
      self._image = mu.fsh_entry_image(self.block)
    return self._image


class AdSet:
  """The boards of an ad set by role: `sheets` and `strips` carry ads,
  `frame` is the board frame texture (None: the target keeps its own)."""

  def __init__(self, layout, sheets, strips, frame):
    self.layout, self.sheets, self.strips, self.frame = layout, sheets, strips, frame


def layout_of(entries):
  """"wc" when the set's ads2 is a 128-wide strip, else "std"."""
  blocks = dict(entries)
  if "ads2" in blocks and struct.unpack_from("<H", blocks["ads2"], 4)[0] == STRIP_SIZE[0]:
    return "wc"
  return "std"


def from_fsh(data, overrides=None):
  """An AdSet from an adboards FSH; `overrides` {tag: PIL image} replace
  boards of the file (resized to the board's size)."""
  entries = mu.fsh_entries(data)
  layout = layout_of(entries)
  boards = {tag: Board(block=block) for tag, block in entries}
  for tag, image in (overrides or {}).items():
    if tag in boards:
      boards[tag] = Board(image=_fit(image, boards[tag].size))
  spec = LAYOUTS[layout]
  sheets = [boards[t] for t in spec["sheets"] if t in boards]
  if not sheets:
    raise ValueError("no ad board in this FSH")
  return AdSet(layout, sheets, [boards[t] for t in spec["strips"] if t in boards],
               boards.get(spec["frame"]))


def from_images(images):
  """An AdSet from ad pictures: each one an ad, repeated over every row."""
  if not images:
    raise ValueError("no image")
  n = len(images)
  sheets = [Board(image=_stack([images[(ROWS * k + j) % n] for j in range(ROWS)], SHEET_SIZE))
            for k in range(_SETS_NEEDED)]
  strips = [Board(image=_stack([images[(ROWS * k + j) % n] for j in range(ROWS)], STRIP_SIZE))
            for k in range(2)]
  return AdSet("wc", sheets, strips, None)


def _images_in(folder):
  return [os.path.join(folder, n) for n in sorted(os.listdir(folder))
          if n.lower().endswith(IMAGE_EXTS) and not n.startswith(".")]


def _open_image(path):
  with Image.open(path) as im:
    im.load()
    return im.copy()


def load_set(path):
  """An AdSet from a .fsh file, an image file or a folder (see the module
  doc). ValueError when `path` holds nothing usable."""
  if os.path.isfile(path):
    if path.lower().endswith(".fsh"):
      with open(path, "rb") as f:
        return from_fsh(f.read())
    return from_images([_open_image(path)])
  if not os.path.isdir(path):
    raise ValueError(f"not found: {path}")
  fshs = sorted(n for n in os.listdir(path) if n.lower().endswith(".fsh"))
  images = _images_in(path)
  if fshs:
    pick = next((n for n in fshs if n.lower() == "adboards.fsh"), fshs[0])
    named = {}
    for img in images:
      m = re.fullmatch(r"(ads\d)", os.path.splitext(os.path.basename(img))[0].lower())
      if m:
        named[m.group(1)] = _open_image(img)
    with open(os.path.join(path, pick), "rb") as f:
      return from_fsh(f.read(), named)
  if images:
    return from_images([_open_image(p) for p in images])
  raise ValueError(f"no .fsh or image in {path}")


def load_ref(ref, base=None):
  """An AdSet from a set reference: "stock:<name>" (the game's own
  stadiums/adboards/<name>, from data.gob) or a path (relative to `base`,
  the mod data by default). ValueError when nothing usable is there."""
  from backend import stadium_dressing as sd
  if sd.is_stock(ref):
    data = sd.stock_bytes(sd.stock_game_path(ref, "ads"))
    if not data:
      raise ValueError(f"stock ads not found: {ref}")
    return from_fsh(data)
  if base is None:
    from shared.config import config
    base = config.mod_data_directory
  return load_set(ref if os.path.isabs(ref) else os.path.join(base, ref))


def _pick(items, i):
  """items[i], and past the end the twin of the board two before (ads7 is
  ads4's size and stand-in, as the stock nine-board sets do it)."""
  return items[i] if i < len(items) else items[(i - 2) % len(items)]


def _strip_from_sheet(sheet):
  """A 128x256 strip from a 256x256 sheet: each band fitted to half the width."""
  image = sheet.image()
  return Board(image=_stack(_bands(image), STRIP_SIZE))


def _pixels(board, code, w, h):
  """The pixel data of `board` as a `code` w x h bitmap."""
  size = mu._fsh_pixel_data_size(code, w, h)
  if board.block is not None:
    word, bw, bh = struct.unpack_from("<IHH", board.block, 0)
    if (word & 0xFF, bw, bh) == (code, w, h):
      return board.block[16:16 + size]
  rgba = mu._image_to_rgba_array(board.image(), (w, h))
  if code == mu.FSH_CODE_DXT1:
    return mu._encode_dxt1(rgba)
  if code == mu.FSH_CODE_DXT5:
    return mu._encode_dxt5(rgba)
  return mu._encode_a8r8g8b8(rgba)


def _with_board(template_block, board):
  """`template_block` (a stock board: header, pixels, trailer) carrying
  `board`'s picture: the header and trailer stay the stock ones."""
  code_word, w, h = struct.unpack_from("<IHH", template_block, 0)
  code = code_word & 0xFF
  size = mu._fsh_pixel_data_size(code, w, h)
  return template_block[:16] + _pixels(board, code, w, h) + template_block[16 + size:]


def build(template_data, ad_set):
  """The FSH of `template_data`'s layout (a stock adboards file) showing
  `ad_set`'s ads."""
  entries = mu.fsh_entries(template_data)
  layout = layout_of(entries)
  spec = LAYOUTS[layout]
  blocks = dict(entries)
  for i, tag in enumerate(spec["sheets"]):
    if tag in blocks:
      blocks[tag] = _with_board(blocks[tag], _pick(ad_set.sheets, i))
  for j, tag in enumerate(spec["strips"]):
    if tag in blocks:
      src = ad_set.strips[j] if ad_set.layout == "wc" and j < len(ad_set.strips) \
        else _strip_from_sheet(_pick(ad_set.sheets, j))
      blocks[tag] = _with_board(blocks[tag], src)
  frame = spec["frame"]
  if frame in blocks and ad_set.frame is not None and ad_set.layout == layout:
    blocks[frame] = _with_board(blocks[frame], ad_set.frame)
  return mu.build_fsh(template_data[12:16], [(tag, blocks[tag]) for tag, _ in entries])


def build_all(ad_set, wc_template, std_template):
  """{game file name: FSH bytes} for the two layout files the stadium XML names."""
  return {game_filename(WC_NAME): build(wc_template, ad_set),
          game_filename(STD_NAME): build(std_template, ad_set)}
