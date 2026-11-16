"""
backend/stadium_screen.py — a custom stadium's giant screen, dressed per match
===============================================================================
Some custom stadiums carry a big screen: one texture of their scene pack's
Textures.fsh (La Defense Arena: "scre", 824x212, its "RUGBY 08" picture). The
game never updates it (no stadium texture is redrawn during a match), so the
mod paints it once per match: both crests and team names, the competition
logo between them. The stadium's JSON names the texture ("screen": "scre").

The picture replaces the texture's top level; its mipmaps are dropped (the
count in the header set to 0) so no distant view shows the old picture.
"""
import os
import struct

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from backend import mod_utils as mu
from shared.app_paths import assets_directory
from shared.log import get_logger
from shared.omodel.bigfile import BigArchive, pack_big

log = get_logger(__name__)

TEXTURES = "Textures.fsh"
FONT = "BebasNeue-Regular.ttf"

BG_TOP = (14, 22, 40)
BG_BOTTOM = (3, 6, 14)
TEXT = (245, 247, 250)
ACCENT = (89, 172, 216)


def _font(size):
  return ImageFont.truetype(os.path.join(assets_directory(), "fonts", FONT), size)


def load_image(path):
  """PIL RGBA image of a picture file or of an FSH's first texture; None
  when `path` is empty or unreadable."""
  if not path or not os.path.isfile(path):
    return None
  try:
    if path.lower().endswith(".fsh"):
      with open(path, "rb") as f:
        entries = mu.fsh_entries(f.read())
      return mu.fsh_entry_image(entries[0][1]).convert("RGBA") if entries else None
    with Image.open(path) as im:
      return im.convert("RGBA")
  except (OSError, ValueError, struct.error, IndexError) as e:
    log.warning(f"screen: cannot read {path}: {e}")
    return None


def _trim(image):
  """`image` cropped to its non-transparent part."""
  box = image.getchannel("A").point(lambda a: 255 if a > 8 else 0).getbbox()
  return image.crop(box) if box else image


def _fit(image, box_w, box_h):
  image = _trim(image)
  scale = min(box_w / image.width, box_h / image.height)
  return image.resize((max(1, round(image.width * scale)), max(1, round(image.height * scale))),
                      Image.LANCZOS)


def _paste_glow(canvas, image, x, y):
  """`image` at (x, y) over a soft light halo, as an LED wall shows a crest."""
  glow = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
  halo = Image.new("RGBA", image.size, (255, 255, 255, 0))
  halo.putalpha(image.getchannel("A").point(lambda a: a * 70 // 255))
  glow.paste(halo, (x, y), halo)
  glow = glow.filter(ImageFilter.GaussianBlur(10))
  canvas.alpha_composite(glow)
  canvas.alpha_composite(image, (x, y))


def _fit_font(draw, lines, max_w, max_h):
  """(font, line height) of the largest size at which every line of `lines`
  fits max_w and all of them max_h."""
  size = max_h
  while True:
    font = _font(size)
    boxes = [draw.textbbox((0, 0), line, font=font) for line in lines]
    line_h = max(b - t for _, t, _, b in boxes)
    total = line_h * len(lines) + round(size * 0.12) * (len(lines) - 1)
    if size <= 10 or (max(r - l for l, _, r, _ in boxes) <= max_w and total <= max_h):
      return font, size
    size -= 2


def _name(draw, text, cx, cy, max_w, max_h):
  """`text` (upper case) centred on (cx, cy), shrunk to fit max_w x max_h;
  a long name goes on two lines when that lets it be bigger."""
  text = (text or "").upper().strip()
  options = [[text]]
  words = text.split()
  if len(words) > 1:
    cut = min(range(1, len(words)),
              key=lambda i: abs(len(" ".join(words[:i])) - len(" ".join(words[i:]))))
    options.append([" ".join(words[:cut]), " ".join(words[cut:])])
  fits = [_fit_font(draw, lines, max_w, round(max_h * (1 if len(lines) == 1 else 1.9))) + (lines,)
          for lines in options]
  # one line unless it would be much smaller than two
  font, size, lines = fits[0] if fits[0][1] >= 0.6 * max_h else max(fits, key=lambda o: o[1])
  gap = round(size * 0.12)
  heights = [draw.textbbox((0, 0), line, font=font) for line in lines]
  line_h = max(b - t for _, t, _, b in heights)
  y = cy - (line_h * len(lines) + gap * (len(lines) - 1)) / 2
  for line in lines:
    l, t, r, b = draw.textbbox((0, 0), line, font=font)
    draw.text((cx - (r - l) / 2 - l, y - t), line, font=font, fill=TEXT)
    y += line_h + gap


def render(size, home, away, centre_logo=None):
  """The screen picture (PIL RGBA, `size`): `home`/`away` = {"name", "logo"
  (PIL image or None)}, `centre_logo` the competition's (None: "VS")."""
  w, h = size
  canvas = Image.new("RGBA", size)
  draw = ImageDraw.Draw(canvas)
  for y in range(h):
    k = y / max(1, h - 1)
    draw.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * k) for a, b in zip(BG_TOP, BG_BOTTOM)) + (255,))
  # a faint LED grid
  grid = Image.new("RGBA", size, (0, 0, 0, 0))
  gdraw = ImageDraw.Draw(grid)
  for x in range(0, w, 3):
    gdraw.line([(x, 0), (x, h)], fill=(0, 0, 0, 28))
  for y in range(0, h, 3):
    gdraw.line([(0, y), (w, y)], fill=(0, 0, 0, 28))
  canvas.alpha_composite(grid)

  pad = round(h * 0.06)
  crest = round(h * 0.74)
  centre_w = round(w * 0.14)
  name_w = (w - 2 * (crest + 2 * pad) - centre_w - 2 * pad) // 2
  name_h = round(h * 0.34)
  for side, team in (("home", home), ("away", away)):
    logo = team.get("logo")
    if logo is not None:
      img = _fit(logo, crest, crest)
      x = pad + (crest - img.width) // 2 if side == "home" else w - pad - crest + (crest - img.width) // 2
      _paste_glow(canvas, img, x, (h - img.height) // 2)
    cx = crest + 2 * pad + name_w / 2 if side == "home" else w - crest - 2 * pad - name_w / 2
    _name(draw, team.get("name"), cx, h / 2, name_w, name_h)

  if centre_logo is not None:
    img = _fit(centre_logo, centre_w, round(h * 0.62))
    canvas.alpha_composite(img, ((w - img.width) // 2, (h - img.height) // 2))
  else:
    font = _font(round(h * 0.3))
    l, t, r, b = draw.textbbox((0, 0), "VS", font=font)
    draw.text(((w - (r - l)) / 2 - l, (h - (b - t)) / 2 - t), "VS", font=font, fill=ACCENT)

  bar = max(2, round(h * 0.025))
  draw.rectangle([0, h - bar, w, h], fill=ACCENT + (255,))
  return canvas


def with_texture(fsh_data, tag, image):
  """`fsh_data` with texture `tag` showing `image` (resized to it), its
  format and attachments kept, its mipmaps dropped. KeyError when the FSH
  has no `tag`."""
  entries = mu.fsh_entries(fsh_data)
  blocks = dict(entries)
  block = blocks[tag]
  code_word, w, h = struct.unpack_from("<IHH", block, 0)
  code = code_word & 0xFF
  next_off = code_word >> 8
  size = mu._fsh_pixel_data_size(code, w, h)
  rgba = mu._image_to_rgba_array(image, (w, h))
  if code == mu.FSH_CODE_DXT1:
    pixels = mu._encode_dxt1(rgba)
  elif code == mu.FSH_CODE_DXT5:
    pixels = mu._encode_dxt5(rgba)
  elif code == mu.FSH_CODE_A8R8G8B8:
    pixels = mu._encode_a8r8g8b8(rgba)
  else:
    raise ValueError(f"screen texture {tag}: format 0x{code:02X} not supported")
  trailer = block[next_off:] if next_off else b""
  head = bytearray(block[:16])
  new_next = (16 + size) if next_off else 0
  struct.pack_into("<I", head, 0, code | (new_next << 8))
  head[15] &= 0x0F                       # mipmap count: none
  blocks[tag] = bytes(head) + pixels[:size] + trailer
  return mu.build_fsh(fsh_data[12:16], [(t, blocks[t]) for t, _ in entries])


def screen_size(big_data, tag):
  """(w, h) of texture `tag` in the scene pack `big_data`, or None."""
  try:
    archive = BigArchive(big_data)
    blocks = dict(mu.fsh_entries(archive.read(TEXTURES)))
    return struct.unpack_from("<HH", blocks[tag], 4) if tag in blocks else None
  except (KeyError, ValueError, struct.error):
    return None


def dress_scene(big_path, tag, home, away, centre_logo=None):
  """Rewrite the scene pack at `big_path` so its screen texture `tag` shows
  this match (see render). False when the pack has no such texture."""
  with open(big_path, "rb") as f:
    data = f.read()
  archive = BigArchive(data)
  name = next((n for n in archive.entries if n.lower() == TEXTURES.lower()), None)
  if name is None:
    log.warning(f"screen: {big_path} has no {TEXTURES}")
    return False
  textures = archive.read(name)
  blocks = dict(mu.fsh_entries(textures))
  if tag not in blocks:
    log.warning(f"screen: no texture {tag!r} in {big_path}")
    return False
  w, h = struct.unpack_from("<HH", blocks[tag], 4)
  picture = render((w, h), home, away, centre_logo)
  new_textures = with_texture(textures, tag, picture)
  entries = [(n, new_textures if n == name else archive.read(n)) for n in archive.entries]
  with open(big_path, "wb") as f:
    f.write(pack_big(entries))
  return True
