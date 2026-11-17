"""
backend/stadium_dressing.py — the post pads, corner flags and posts of a match
===============================================================================
The game reads one "pads and flags" file per stadium (the mod's stadium XML
names Tournaments\\World_Cup for all of them, so one file per match):

  pada  post pad wrap        padb  post pad top
  flag  corner flag          flgp  corner flag pole
  post  post colour          xbar  crossbar colour

The mod keeps these as image folders ("sets") the player can mix freely:

  pads set   pad_wrap.png  pad_top.png  flag.png  flag_pole.png
  posts set  post.png  crossbar.png

A set is named by a reference: a folder (path relative to the mod data, or
absolute), or "stock:<name>" for one of the game's own files
(stadiums/pads_and_flags/<name>, read from data.gob; e.g.
"stock:standard/twickenham"). Missing images keep the stock World Cup ones.
"""
import hashlib
import os
import struct

from PIL import Image

from backend import mod_utils as mu
from shared.app_paths import assets_directory
from shared.log import get_logger

log = get_logger(__name__)

STOCK_PREFIX = "stock:"
# The mod data folder of the sets any match can wear: <LIBRARY>/<kind>/<set>.
# It was "dressing/", then "ingame_graphics/": references saved then still
# work (library_ref).
LIBRARY = "stadium_graphics"
_OLD_LIBRARIES = ("dressing/", "ingame_graphics/")
PADS_DIR = "stadiums/pads_and_flags"
ADS_DIR = "stadiums/adboards"

# file name -> FSH tag
PADS_FILES = {"pad_wrap": "pada", "pad_top": "padb", "flag": "flag", "flag_pole": "flgp"}
POSTS_FILES = {"post": "post", "crossbar": "xbar"}
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp", ".tga", ".webp")
MAX_SIDE = 512


def template_path():
  return os.path.join(assets_directory(), "stock_game", "pads_world_cup.fsh")


# ── stock files (data.gob) ──────────────────────────────────────────────────
def stock_game_path(ref, kind="pads"):
  """The game path of a "stock:" reference ("stadiums/pads_and_flags/standard/
  twickenham"), None for any other reference."""
  if not is_stock(ref):
    return None
  base = PADS_DIR if kind in ("pads", "posts") else ADS_DIR
  return f"{base}/{ref[len(STOCK_PREFIX):].strip().lower()}"


def is_stock(ref):
  return isinstance(ref, str) and ref.startswith(STOCK_PREFIX)


def _stock_hash_name(game_path):
  return hashlib.md5(game_path.lower().encode()).hexdigest() + ".fsh"


def _cache_dir():
  from shared.config import config
  return os.path.join(config.temp_directory, "stock_dressing")


def prefetch_stock(game_paths):
  """Extract the stock files `game_paths` from data.gob into the cache, in
  one pass over the archive (the ones already cached are skipped)."""
  from shared.config import config
  cache = _cache_dir()
  wanted = [_stock_hash_name(p) for p in game_paths
            if not os.path.isfile(os.path.join(cache, _stock_hash_name(p)))]
  if not wanted or not os.path.isfile(config.R08_data_gob_filepath):
    return
  os.makedirs(cache, exist_ok=True)
  try:
    mu.extract_files_from_big_archive(config.R08_data_gob_filepath, wanted, cache)
  except OSError as e:
    log.warning(f"stock dressing: {e}")


def stock_bytes(game_path):
  """The bytes of the stock file `game_path` (cached), None when the game
  has no such file or is not installed."""
  path = os.path.join(_cache_dir(), _stock_hash_name(game_path))
  if not os.path.isfile(path):
    prefetch_stock([game_path])
  try:
    with open(path, "rb") as f:
      return f.read()
  except OSError:
    return None


# ── sets ────────────────────────────────────────────────────────────────────
def library_ref(ref):
  """`ref` with a reference into an old library folder moved to the current
  one; any other reference unchanged."""
  path = (ref or "").replace("\\", "/")
  for old in _OLD_LIBRARIES:
    if path.startswith(old):
      return LIBRARY + "/" + path[len(old):]
  return ref


def _resolve_folder(ref, base=None):
  if os.path.isabs(ref):
    return ref
  ref = library_ref(ref)
  if base is None:
    from shared.config import config
    base = config.mod_data_directory
  return os.path.join(base, ref)


def _open(path):
  with Image.open(path) as im:
    return im.convert("RGBA")


def _folder_images(folder, names):
  """{tag: PIL image} of the images of `names` (file stem -> tag) in `folder`."""
  out = {}
  if not os.path.isdir(folder):
    return out
  for entry in os.listdir(folder):
    stem, ext = os.path.splitext(entry)
    tag = names.get(stem.lower())
    if tag and ext.lower() in IMAGE_EXTS:
      try:
        out[tag] = _open(os.path.join(folder, entry))
      except OSError as e:
        log.warning(f"dressing: cannot read {entry}: {e}")
  return out


def _fsh_images(data, tags):
  out = {}
  for tag, block in mu.fsh_entries(data):
    if tag in tags:
      try:
        out[tag] = mu.fsh_entry_image(block).convert("RGBA")
      except ValueError as e:
        log.warning(f"dressing: {tag}: {e}")
  return out


def load(ref, kind, base=None):
  """{tag: PIL image} of the set `ref` for `kind` ("pads" or "posts"): its
  images, or the stock file's textures. {} when nothing is found."""
  if not ref:
    return {}
  names = PADS_FILES if kind == "pads" else POSTS_FILES
  if is_stock(ref):
    data = stock_bytes(stock_game_path(ref, kind))
    return _fsh_images(data, set(names.values())) if data else {}
  path = _resolve_folder(ref, base)
  if os.path.isfile(path) and path.lower().endswith(".fsh"):
    with open(path, "rb") as f:
      return _fsh_images(f.read(), set(names.values()))
  return _folder_images(path, names)


def save_set(images, folder, kind):
  """Write {tag: PIL image} as a set folder (file names of `kind`)."""
  names = {tag: stem for stem, tag in (PADS_FILES if kind == "pads" else POSTS_FILES).items()}
  os.makedirs(folder, exist_ok=True)
  for tag, image in images.items():
    if tag in names:
      image.save(os.path.join(folder, names[tag] + ".png"))


# ── the game file ───────────────────────────────────────────────────────────
def _pow2(n):
  p = 4
  while p < n and p < MAX_SIDE:
    p *= 2
  return p


def _encode(image, code, w, h):
  """`image` as a `code` bitmap of w x h (DXT padded to whole 4x4 blocks)."""
  bw, bh = (max(4, (w + 3) // 4 * 4), max(4, (h + 3) // 4 * 4)) if code in (mu.FSH_CODE_DXT1, mu.FSH_CODE_DXT5) else (w, h)
  pic = image.resize((w, h), Image.LANCZOS)
  if (bw, bh) != (w, h):
    canvas = Image.new("RGBA", (bw, bh))
    canvas.paste(pic, (0, 0))
    pic = canvas
  rgba = mu._image_to_rgba_array(pic, (bw, bh))
  if code == mu.FSH_CODE_DXT1:
    return mu._encode_dxt1(rgba)
  if code == mu.FSH_CODE_DXT5:
    return mu._encode_dxt5(rgba)
  return mu._encode_a8r8g8b8(rgba)


def _block(template_block, image):
  """`template_block` (a stock texture) showing `image`: same format and
  mipmap count, size = the image's rounded to powers of two, the template's
  trailing bytes kept."""
  word, tw, th = struct.unpack_from("<IHH", template_block, 0)
  code, nxt = word & 0xFF, word >> 8
  mips = template_block[15] >> 4
  used = mu._fsh_pixel_data_size(code, tw, th)
  for i in range(1, mips + 1):
    used += mu._fsh_pixel_data_size(code, max(1, tw >> i), max(1, th >> i))
  # bytes between the pixels and the attachment (16 in the stock blocks
  # without mipmaps), then the attachment itself
  slack = template_block[16 + used:nxt] if nxt else b""
  trailer = template_block[nxt:] if nxt else template_block[16 + used:]
  w, h = _pow2(image.width), _pow2(image.height)
  pixels = _encode(image, code, w, h)
  for i in range(1, mips + 1):
    pixels += _encode(image, code, max(1, w >> i), max(1, h >> i))
  head = bytearray(template_block[:16])
  new_next = 16 + len(pixels) + len(slack) if nxt else 0
  struct.pack_into("<IHH", head, 0, code | (new_next << 8), w, h)
  return bytes(head) + pixels + slack + trailer


def build(pads, posts, template_data=None):
  """The game's pads-and-flags FSH from {tag: image} of a pads set and of a
  posts set; textures neither gives keep the template's."""
  if template_data is None:
    with open(template_path(), "rb") as f:
      template_data = f.read()
  entries = mu.fsh_entries(template_data)
  chosen = {**{t: i for t, i in (pads or {}).items() if t in PADS_FILES.values()},
            **{t: i for t, i in (posts or {}).items() if t in POSTS_FILES.values()}}
  out = []
  for tag, block in entries:
    out.append((tag, _block(block, chosen[tag]) if tag in chosen else block))
  return mu.build_fsh(template_data[12:16], out)


def preview_images(pads_ref, posts_ref, base=None):
  """{tag: PIL image} for the 3D preview: the stock World Cup textures under
  the two sets'."""
  with open(template_path(), "rb") as f:
    images = _fsh_images(f.read(), set(PADS_FILES.values()) | set(POSTS_FILES.values()))
  images.update(load(pads_ref, "pads", base))
  images.update(load(posts_ref, "posts", base))
  return images
