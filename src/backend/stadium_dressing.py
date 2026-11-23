"""
backend/stadium_dressing.py — the post pads, corner flags and posts of a match
===============================================================================
The game reads one "pads and flags" file per stadium (the mod's stadium XML
names Tournaments\\World_Cup for all of them, so one file per match):

  pada  post pad wrap        padb  post pad top
  flag  corner flag          flgp  corner flag pole
  post  post colour          xbar  crossbar colour

The mod keeps each as one picture (a "set") the player can mix freely:

  pads set   1088 x 768 (any 17:12 size), packed, each part in the game
             texture's proportions:
               x 0-192     pad wrap (one face of the post pad, top = pad top)
               x 192-576   corner flag pole
               x 576-1088  corner flag (y 0-256), pad top (y 256-768)
  posts set  128 x 1024 (any 1:8 size), two strips:
               x 0-64      the post, from its top (y 0) down to the top of
                           the pad; it wraps round the post, both posts wear it
               x 64-128    the crossbar turned upright: from the post (y 0)
                           to the middle (y 837), then its middle part
                           (y 837-1024); the bar's top runs down the right
                           edge. Its other half mirrors this one.

The game's textures are cut from them (split): its post texture runs down the
post (row 0 at the top), its crossbar texture along the bar from the post
(u 0.1) to near the middle (u 0.4), then the middle 10% (u 0.6-0.9), the
same in every stock stadium.

A set is named by a reference: a picture (path relative to the mod data, or
absolute), or "stock:<name>" for one of the game's own files
(stadiums/pads_and_flags/<name>, read from data.gob; e.g.
"stock:standard/twickenham"). Folders of the older one-picture-per-texture
sets (pad_wrap.png, pad_top.png, flag.png, flag_pole.png / post.png,
crossbar.png) still load, and a reference saved to such a folder finds the
picture of the same name (".../pads" -> ".../pads.png"). Missing textures
keep the stock World Cup ones.
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

# the pads picture: tag -> (left, top, right, bottom) in PADS_SIZE pixels
PADS_SIZE = (1088, 768)
PADS_LAYOUT = {"pada": (0, 0, 192, 768), "flgp": (192, 0, 576, 768),
               "flag": (576, 0, 1088, 256), "padb": (576, 256, 1088, 768)}
# the posts picture (POSTS_SIZE pixels): the post's strip, and the
# crossbar's (turned upright): its outer part then its middle
POSTS_SIZE = (128, 1024)
POST_BOX = (0, 0, 64, 1024)
XBAR_OUTER = (64, 0, 128, 837)
XBAR_MIDDLE = (64, 837, 128, 1024)
XBAR_TEXTURE = (256, 64)


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
  one, and one to an older pads / posts set folder that is gone moved to
  the picture of its name; any other reference unchanged."""
  path = (ref or "").replace("\\", "/")
  for old in _OLD_LIBRARIES:
    if path.startswith(old):
      ref = path = LIBRARY + "/" + path[len(old):]
  if not path or is_stock(path) or os.path.isabs(path) or os.path.splitext(path)[1]:
    return ref
  from shared.config import config
  base = os.path.join(config.mod_data_directory, path.rstrip("/"))
  if not os.path.exists(base):
    for ext in IMAGE_EXTS:
      if os.path.isfile(base + ext):
        return path.rstrip("/") + ext
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


# ── one picture <-> the game's textures ────────────────────────────────────
def _scaled(box, size, full):
  sx, sy = size[0] / full[0], size[1] / full[1]
  return (box[0] * sx, box[1] * sy, box[2] * sx, box[3] * sy)


def _resize(image, size, box=None):
  """`image` (or its `box`) at `size`; small textures stay crisp, and
  nothing outside the box bleeds in."""
  bw = (box[2] - box[0]) if box else image.width
  bh = (box[3] - box[1]) if box else image.height
  size = (max(1, round(size[0])), max(1, round(size[1])))
  if size[0] >= 4 * bw or size[1] >= 4 * bh:
    return image.resize(size, Image.NEAREST, box=box)
  if box:
    image = image.crop(tuple(round(v) for v in box))
  return image.resize(size, Image.LANCZOS)


def split_pads(image):
  """{tag: PIL image} of a pads picture."""
  image = image.convert("RGBA")
  out = {}
  for tag, box in PADS_LAYOUT.items():
    l, t, r, b = _scaled(box, image.size, PADS_SIZE)
    out[tag] = _resize(image, (box[2] - box[0], box[3] - box[1]), (l, t, r, b)) \
      if image.size != PADS_SIZE else image.crop(box)
  return out


def compose_pads(images):
  """The pads picture of {tag: PIL image} (tags missing stay transparent)."""
  canvas = Image.new("RGBA", PADS_SIZE, (0, 0, 0, 0))
  for tag, box in PADS_LAYOUT.items():
    if images.get(tag) is not None:
      canvas.paste(_resize(images[tag].convert("RGBA"), (box[2] - box[0], box[3] - box[1])), box[:2])
  return canvas


def split_posts(image):
  """{"post", "xbar"} textures of a posts picture: the post's strip, and
  the crossbar's parts laid out along the game's bar."""
  image = image.convert("RGBA")
  post = _resize(image, (POST_BOX[2] - POST_BOX[0], POST_BOX[3] - POST_BOX[1]),
                 _scaled(POST_BOX, image.size, POSTS_SIZE))
  tw, th = XBAR_TEXTURE
  rows = (round(th * 0.1), round(th * 0.9))
  cols = [round(tw * f) for f in (0.1, 0.4, 0.6, 0.9)]

  def part(box, width):
    # upright in the picture (bar top on the right): back along the bar
    upright = _resize(image, (rows[1] - rows[0], width), _scaled(box, image.size, POSTS_SIZE))
    return upright.transpose(Image.ROTATE_90)

  outer, middle = part(XBAR_OUTER, cols[1] - cols[0]), part(XBAR_MIDDLE, cols[3] - cols[2])
  bar = Image.new("RGBA", (tw, rows[1] - rows[0]))
  bar.paste(outer, (cols[0], 0))
  bar.paste(middle, (cols[2], 0))
  # the margins the bar never shows: their neighbours' edge columns
  for x0, x1, src in ((0, cols[0], cols[0]), (cols[1], tw // 2, cols[1] - 1),
                      (tw // 2, cols[2], cols[2]), (cols[3], tw, cols[3] - 1)):
    if x1 > x0:
      bar.paste(bar.crop((src, 0, src + 1, bar.height)).resize((x1 - x0, bar.height)), (x0, 0))
  xbar = Image.new("RGBA", (tw, th))
  xbar.paste(bar, (0, rows[0]))
  xbar.paste(bar.crop((0, 0, tw, 1)).resize((tw, rows[0])), (0, 0))
  xbar.paste(bar.crop((0, bar.height - 1, tw, bar.height)).resize((tw, th - rows[1])), (0, rows[1]))
  return {"post": post, "xbar": xbar}


def compose_posts(images):
  """The posts picture of a "post" and an "xbar" texture (the game's)."""
  canvas = Image.new("RGBA", POSTS_SIZE, (0, 0, 0, 0))
  post, xbar = images.get("post"), images.get("xbar")
  if post is not None:
    canvas.paste(_resize(post.convert("RGBA"), (POST_BOX[2] - POST_BOX[0], POST_BOX[3] - POST_BOX[1])),
                 POST_BOX[:2])
  if xbar is not None:
    xbar = xbar.convert("RGBA")
    w, h = xbar.size
    for box, (u0, u1) in ((XBAR_OUTER, (0.1, 0.4)), (XBAR_MIDDLE, (0.6, 0.9))):
      along = _resize(xbar, (box[3] - box[1], box[2] - box[0]), (w * u0, h * 0.1, w * u1, h * 0.9))
      canvas.paste(along.transpose(Image.ROTATE_270), box[:2])
  return canvas


def split(image, kind):
  return split_pads(image) if kind == "pads" else split_posts(image)


def compose(images, kind):
  return compose_pads(images) if kind == "pads" else compose_posts(images)


# ── loading and saving ──────────────────────────────────────────────────
def set_path(ref, base=None):
  """The file or folder the reference `ref` names (a reference to an older
  set folder that is gone finds the picture of its name), None when there
  is none or `ref` is a stock one."""
  if not ref or is_stock(ref):
    return None
  path = _resolve_folder(ref, base)
  if os.path.exists(path):
    return path
  for ext in IMAGE_EXTS:
    if os.path.isfile(path.rstrip("/\\") + ext):
      return path.rstrip("/\\") + ext
  return None


def load(ref, kind, base=None):
  """{tag: PIL image} of the set `ref` for `kind` ("pads" or "posts"): its
  picture cut into the game's textures, an older set folder's images, or
  the stock file's textures. {} when nothing is found."""
  if not ref:
    return {}
  names = PADS_FILES if kind == "pads" else POSTS_FILES
  if is_stock(ref):
    data = stock_bytes(stock_game_path(ref, kind))
    return _fsh_images(data, set(names.values())) if data else {}
  path = set_path(ref, base)
  if path is None:
    return {}
  if os.path.isdir(path):
    return _folder_images(path, names)
  if path.lower().endswith(".fsh"):
    with open(path, "rb") as f:
      return _fsh_images(f.read(), set(names.values()))
  try:
    return split(_open(path), kind)
  except OSError as e:
    log.warning(f"dressing: cannot read {path}: {e}")
    return {}


def save_set(images, path, kind):
  """Write {tag: PIL image} as the set picture `path` of `kind`; textures
  missing take the stock World Cup ones."""
  full = stock_textures(kind)
  full.update({t: i for t, i in images.items() if t in full})
  os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
  compose(full, kind).save(path)


def stock_textures(kind=None):
  """{tag: PIL image} of the stock World Cup file (the template): all, or
  those of `kind`."""
  tags = set(PADS_FILES.values()) | set(POSTS_FILES.values())
  if kind:
    tags = set((PADS_FILES if kind == "pads" else POSTS_FILES).values())
  with open(template_path(), "rb") as f:
    return _fsh_images(f.read(), tags)


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
  images = stock_textures()
  images.update(load(pads_ref, "pads", base))
  images.update(load(posts_ref, "posts", base))
  return images
