# This file contains some useful funtions (copy a file, edit .FSH and .BIG files, etc)

import shutil
import os
import sys
from pathlib import Path
import subprocess
import numpy as np
sys.path.append(str(Path(__file__).parent.parent))
from PIL import Image
import struct
import io
import hashlib
from shared.config import config
from shared.user_prefs import user_prefs

# Custom modules
from backend.game_specific_variables import *

from shared.log import get_logger, logging_active

log = get_logger(__name__)


# Copy a file and logs the result
def copy_file(source, destination):
  try:
    shutil.copy2(source, destination)
#    print(f"Successfuly copied {source} into {destination}")
    log.debug(f"Successfully copied {source.split('/')[-1]}")
    return True

  except Exception as e:
    log.error(f"Unable to copy {source} into {destination}: {e}")
#    print(f"Unable to copy {source.split('/')[-1]}")
    return False

# This function adds an image to a .FSH file -- EXPERIMENTAL
def add_image_to_fsh_file(fsh_file_path, image_file_path, dimensions, position):
    # WARNING add_image_to_fsh_file is experimental and may be unstable
    log.debug(f"Adding image: {image_file_path} into {fsh_file_path}")

    try:
        with open(fsh_file_path, 'r+b') as fsh_file:
          fsh_file.seek(position)

          image = Image.open(image_file_path)

          if image is None:
            log.error("Invalid image")
            return

          if image.size != dimensions:
            image = image.resize(dimensions)
            log.debug(f"Incorrect image size for {image_file_path}. Resizing.")

          # Process based on image mode to match original behavior
          if image.mode == 'RGB':
            # Original writes B G R 255 for RGB
            data = image.tobytes()  # R G B R G B ...
            arr = np.frombuffer(data, dtype=np.uint8).reshape(-1, 3)
            bgra_arr = np.empty((arr.shape[0], 4), dtype=np.uint8)
            bgra_arr[:, 0] = arr[:, 2]  # B
            bgra_arr[:, 1] = arr[:, 1]  # G
            bgra_arr[:, 2] = arr[:, 0]  # R
            bgra_arr[:, 3] = 255         # A
            bgra_data = bgra_arr.tobytes()
          elif image.mode == 'RGBA':
            # Original writes B G R A
            data = image.tobytes()  # R G B A ...
            arr = np.frombuffer(data, dtype=np.uint8).reshape(-1, 4)
            bgra_arr = arr[:, [2, 1, 0, 3]]  # B G R A
            bgra_data = bgra_arr.tobytes()
          else:
            # For other modes (e.g., L, P), convert to RGBA
            image = image.convert('RGBA')
            data = image.tobytes()
            arr = np.frombuffer(data, dtype=np.uint8).reshape(-1, 4)
            bgra_arr = arr[:, [2, 1, 0, 3]]
            bgra_data = bgra_arr.tobytes()

          fsh_file.write(bgra_data)
              
    except Exception as e:
        log.error(f"Unable to add image to {fsh_file_path}: {e}") 
        
# ---------------------------------------------------------------------------
# FSH (EA SHPI) asset replacement
# ---------------------------------------------------------------------------
# An FSH file is an EA SHPI container:
#   char   magic[4]      'SHPI' / 'SHPX' / 'SHPS'
#   uint32 filesize
#   uint32 num_entries
#   char   dir_id[4]
#   repeat num_entries: { char tag[4]; uint32 offset }   (offset from file start)
# Each bitmap entry (at its offset) starts with a 16-byte header:
#   byte   code          (0x7D = A8R8G8B8, 0x60 = DXT1, 0x62 = DXT5, ...)
#   24-bit next-block offset
#   uint16 width, height
#   4 x uint16 misc
# followed by the pixel data.

FSH_MAGICS = (b"SHPI", b"SHPX", b"SHPS")
FSH_CODE_A8R8G8B8 = 0x7D
FSH_CODE_DXT1 = 0x60
FSH_CODE_DXT5 = 0x62
FSH_CODE_NAMES = {
  FSH_CODE_A8R8G8B8: "A8R8G8B8",
  FSH_CODE_DXT1: "DXT1",
  FSH_CODE_DXT5: "DXT5",
}


def _fsh_pixel_data_size(code, width, height):
  if code == FSH_CODE_A8R8G8B8:
    return width * height * 4
  if code == FSH_CODE_DXT1:
    return ((width + 3) // 4) * ((height + 3) // 4) * 8
  if code == FSH_CODE_DXT5:
    return ((width + 3) // 4) * ((height + 3) // 4) * 16
  raise ValueError(f"Unsupported FSH bitmap code 0x{code:02X}")


def _image_to_rgba_array(image, dimensions):
  """Open/resize an image and return an (H, W, 4) uint8 RGBA array."""
  if image.size != dimensions:
    log.debug(f"Incorrect image size {image.size}, resizing to {dimensions}")
    image = image.resize(dimensions, Image.LANCZOS)
  if image.mode != 'RGBA':
    image = image.convert('RGBA')
  return np.asarray(image, dtype=np.uint8).reshape(dimensions[1], dimensions[0], 4)


def _encode_a8r8g8b8(rgba):
  """(H, W, 4) RGBA -> little-endian A8R8G8B8 (BGRA byte order)."""
  return np.ascontiguousarray(rgba[..., [2, 1, 0, 3]]).tobytes()


def _rgba_to_dxt_blocks(rgba):
  """(H, W, 4) RGBA -> (N, 16, 4) int32 array of 4x4 blocks, row-major."""
  h, w = rgba.shape[:2]
  pad_h = (-h) % 4
  pad_w = (-w) % 4
  if pad_h or pad_w:
    rgba = np.pad(rgba, ((0, pad_h), (0, pad_w), (0, 0)), mode='edge')
    h, w = rgba.shape[:2]
  blocks = rgba.reshape(h // 4, 4, w // 4, 4, 4).transpose(0, 2, 1, 3, 4)
  return blocks.reshape(-1, 16, 4).astype(np.int32)


def _pack_565(rgb):
  """(N, 3) int32 -> (N,) uint32 packed RGB565."""
  r, g, b = rgb[:, 0], rgb[:, 1], rgb[:, 2]
  return (((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)).astype(np.uint32)


def _unpack_565(c):
  """(N,) packed RGB565 -> (N, 3) int32 with bit replication."""
  r = (c >> 11) & 0x1F
  g = (c >> 5) & 0x3F
  b = c & 0x1F
  return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], axis=1).astype(np.int32)


def _encode_dxt_color(blocks):
  """Encode the 8-byte DXT color part of each block (4-color mode).

  blocks: (N, 16, 4) int32. Returns (c0, c1, index_bits) as uint32 arrays.
  Endpoints are per-channel min/max — fast and good enough for asset
  repackaging (same strategy as ea-files-editor).
  """
  rgb = blocks[:, :, :3]
  c0 = _pack_565(rgb.max(axis=1))
  c1 = _pack_565(rgb.min(axis=1))
  # 4-color mode requires c0 > c1; swap where needed. Equal endpoints are
  # fine: every pixel then maps to index 0.
  swap = c0 < c1
  c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)

  p0 = _unpack_565(c0)
  p1 = _unpack_565(c1)
  palette = np.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3], axis=1)  # (N, 4, 3)
  dist = ((rgb[:, :, None, :] - palette[:, None, :, :]) ** 2).sum(axis=3)       # (N, 16, 4)
  indices = dist.argmin(axis=2).astype(np.uint32)                               # (N, 16)
  shifts = np.arange(16, dtype=np.uint32) * 2
  index_bits = np.bitwise_or.reduce(indices << shifts, axis=1)
  return c0, c1, index_bits


def _encode_dxt1(rgba):
  """(H, W, 4) RGBA -> DXT1 bytes (opaque, 4-color mode)."""
  blocks = _rgba_to_dxt_blocks(rgba)
  c0, c1, index_bits = _encode_dxt_color(blocks)
  out = np.zeros((len(blocks), 8), dtype=np.uint8)
  out[:, 0:2] = c0.astype('<u2')[:, None].view(np.uint8)
  out[:, 2:4] = c1.astype('<u2')[:, None].view(np.uint8)
  out[:, 4:8] = index_bits.astype('<u4')[:, None].view(np.uint8)
  return out.tobytes()


def _encode_dxt5(rgba):
  """(H, W, 4) RGBA -> DXT5 bytes (8-alpha interpolated mode)."""
  blocks = _rgba_to_dxt_blocks(rgba)
  n = len(blocks)

  # Alpha part: endpoints are per-block min/max, 8-alpha mode (a0 > a1).
  alpha = blocks[:, :, 3]
  a0 = alpha.max(axis=1)
  a1 = alpha.min(axis=1)
  palette = np.stack([a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)], axis=1)  # (N, 8)
  dist = np.abs(alpha[:, :, None] - palette[:, None, :])
  indices = dist.argmin(axis=2).astype(np.uint64)  # equal endpoints -> index 0, safe
  shifts = np.arange(16, dtype=np.uint64) * 3
  alpha_bits = np.bitwise_or.reduce(indices << shifts, axis=1)  # 48 bits used

  c0, c1, index_bits = _encode_dxt_color(blocks)

  out = np.zeros((n, 16), dtype=np.uint8)
  out[:, 0] = a0.astype(np.uint8)
  out[:, 1] = a1.astype(np.uint8)
  byte_shifts = np.arange(6, dtype=np.uint64) * 8
  out[:, 2:8] = ((alpha_bits[:, None] >> byte_shifts) & 0xFF).astype(np.uint8)
  out[:, 8:10] = c0.astype('<u2')[:, None].view(np.uint8)
  out[:, 10:12] = c1.astype('<u2')[:, None].view(np.uint8)
  out[:, 12:16] = index_bits.astype('<u4')[:, None].view(np.uint8)
  return out.tobytes()


def _blocks_to_image(pixels, width, height):
  """(N, 16, C) row-major 4x4 blocks -> (height, width, C) image (cropped)."""
  bw = (width + 3) // 4
  bh = (height + 3) // 4
  c = pixels.shape[2]
  img = pixels.reshape(bh, bw, 4, 4, c).transpose(0, 2, 1, 3, 4).reshape(bh * 4, bw * 4, c)
  return img[:height, :width]


def _decode_dxt_color(color_bytes):
  """(N, 8) uint8 DXT color blocks -> (N, 16, 3) uint8 RGB."""
  n = color_bytes.shape[0]
  c0 = color_bytes[:, 0].astype(np.uint32) | (color_bytes[:, 1].astype(np.uint32) << 8)
  c1 = color_bytes[:, 2].astype(np.uint32) | (color_bytes[:, 3].astype(np.uint32) << 8)
  idx = (color_bytes[:, 4].astype(np.uint32) | (color_bytes[:, 5].astype(np.uint32) << 8)
         | (color_bytes[:, 6].astype(np.uint32) << 16) | (color_bytes[:, 7].astype(np.uint32) << 24))
  p0 = _unpack_565(c0)
  p1 = _unpack_565(c1)
  four = (c0 > c1)[:, None]
  p2 = np.where(four, (2 * p0 + p1) // 3, (p0 + p1) // 2)
  p3 = np.where(four, (p0 + 2 * p1) // 3, np.zeros_like(p0))
  palette = np.stack([p0, p1, p2, p3], axis=1)  # (N, 4, 3)
  shifts = np.arange(16, dtype=np.uint32) * 2
  indices = (idx[:, None] >> shifts) & 0x3  # (N, 16)
  return palette[np.arange(n)[:, None], indices].astype(np.uint8)


def _decode_dxt1(data, width, height):
  n = ((width + 3) // 4) * ((height + 3) // 4)
  blocks = np.frombuffer(data, dtype=np.uint8).reshape(n, 8)
  rgba = np.empty((n, 16, 4), dtype=np.uint8)
  rgba[..., :3] = _decode_dxt_color(blocks)
  rgba[..., 3] = 255
  return _blocks_to_image(rgba, width, height)


def _decode_dxt5(data, width, height):
  n = ((width + 3) // 4) * ((height + 3) // 4)
  blocks = np.frombuffer(data, dtype=np.uint8).reshape(n, 16)
  a0 = blocks[:, 0].astype(np.int32)
  a1 = blocks[:, 1].astype(np.int32)
  abits = np.zeros(n, dtype=np.uint64)
  for i in range(6):
    abits |= blocks[:, 2 + i].astype(np.uint64) << np.uint64(8 * i)
  shifts = np.arange(16, dtype=np.uint64) * np.uint64(3)
  aidx = (abits[:, None] >> shifts) & np.uint64(0x7)  # (N, 16)
  # 8-alpha mode when a0 > a1, else 6-alpha mode (indices 6,7 are 0 and 255)
  pal8 = np.stack([a0, a1] + [((7 - k) * a0 + k * a1) // 7 for k in range(1, 7)], axis=1)
  pal6 = np.stack([a0, a1] + [((5 - k) * a0 + k * a1) // 5 for k in range(1, 5)]
                  + [np.zeros_like(a0), np.full_like(a0, 255)], axis=1)
  apal = np.where((a0 > a1)[:, None], pal8, pal6)  # (N, 8)
  alpha = apal[np.arange(n)[:, None], aidx]  # (N, 16)
  rgba = np.empty((n, 16, 4), dtype=np.uint8)
  rgba[..., :3] = _decode_dxt_color(blocks[:, 8:16])
  rgba[..., 3] = alpha.astype(np.uint8)
  return _blocks_to_image(rgba, width, height)


def _decode_a8r8g8b8(data, width, height):
  arr = np.frombuffer(data, dtype=np.uint8).reshape(height, width, 4)
  return arr[..., [2, 1, 0, 3]].copy()  # BGRA -> RGBA


# Extract a bitmap asset from a .FSH file as a PIL RGBA image. The entry is
# selected by `index` (position in the directory). The bitmap format and
# dimensions are read from the entry header.
def extract_asset_from_fsh_file(fsh_file_path, index):
  with open(fsh_file_path, 'rb') as fsh_file:
    records = _read_fsh_directory(fsh_file)
    if not 0 <= index < len(records):
      raise ValueError(f"Entry index {index} out of range (file has {len(records)} entries)")
    entry_offset = records[index][1]
    fsh_file.seek(entry_offset)
    code_word, width, height = struct.unpack("<IHH", fsh_file.read(8))
    code = code_word & 0xFF
    if code not in FSH_CODE_NAMES:
      raise ValueError(f"Unsupported bitmap format 0x{code:02X} at index {index}")
    fsh_file.seek(entry_offset + 16)
    data = fsh_file.read(_fsh_pixel_data_size(code, width, height))
  if code == FSH_CODE_A8R8G8B8:
    rgba = _decode_a8r8g8b8(data, width, height)
  elif code == FSH_CODE_DXT1:
    rgba = _decode_dxt1(data, width, height)
  else:
    rgba = _decode_dxt5(data, width, height)
  return Image.fromarray(rgba, 'RGBA')


# Return True if a config value is a custom asset path (a real file reference)
# rather than a boolean/empty "stock" flag. Fields like `gloves`, `baselayer_1`
# or `boot_style` hold either a stock value (True/False/int/empty) or a path
# string pointing to a custom image; this tells the two cases apart.
def is_custom_asset(value):
  return isinstance(value, str) and value not in ('', 'True', 'False')


# Composite one or more transparent overlay images on top of a base skin
# image and save the result as a PNG. `overlay_paths` are pasted in order,
# so the last one ends up on top. Returns the output path.
def composite_baselayers_on_image(base_image, overlay_paths, output_path):
  result = base_image.convert('RGBA')
  for layer_path in overlay_paths:
    layer = Image.open(layer_path).convert('RGBA')
    if layer.size != result.size:
      log.warning(f"Baselayer {layer_path} size {layer.size} != skin {result.size}, resizing")
      layer = layer.resize(result.size, Image.LANCZOS)
    result = Image.alpha_composite(result, layer)
  result.save(output_path)
  return output_path


def _read_fsh_directory(fsh_file):
  """Return the list of (tag, offset) directory records, validating the header."""
  header = fsh_file.read(16)
  if len(header) < 16 or header[:4] not in FSH_MAGICS:
    raise ValueError(f"Not an FSH/SHPI file (magic={header[:4]!r})")
  num_entries = struct.unpack_from("<I", header, 8)[0]
  directory = fsh_file.read(num_entries * 8)
  if len(directory) < num_entries * 8:
    raise ValueError("Truncated FSH directory")
  return [
    (directory[i * 8:i * 8 + 4].decode('latin-1'), struct.unpack_from("<I", directory, i * 8 + 4)[0])
    for i in range(num_entries)
  ]


# Replace a bitmap asset inside a .FSH file with a new image, in place.
# The target entry can be selected by `tag` (4-char directory name, e.g. 'loga'),
# by `index` (position in the directory), or by `position` (the pixel-data
# offset used by fsh_files_offsets, i.e. entry offset + 16). The bitmap format
# (A8R8G8B8, DXT1 or DXT5) and dimensions are read from the entry header, so
# the file layout is never changed. `dimensions`, when given, is only checked
# against the header. Returns True on success.
def replace_asset_in_fsh_file(fsh_file_path, image_file_path, dimensions=None, position=None, tag=None, index=None):
  log.debug(f"Replacing asset in {fsh_file_path} with {image_file_path}")
  try:
    with open(fsh_file_path, 'r+b') as fsh_file:
      records = _read_fsh_directory(fsh_file)

      # Resolve the target entry offset
      if tag is not None:
        matches = [off for t, off in records if t == tag]
        if not matches:
          raise ValueError(f"No entry tagged {tag!r} (available: {[t for t, _ in records]})")
        entry_offset = matches[0]
      elif index is not None:
        if not 0 <= index < len(records):
          raise ValueError(f"Entry index {index} out of range (file has {len(records)} entries)")
        entry_offset = records[index][1]
      elif position is not None:
        entry_offset = position - 16
        if entry_offset not in [off for _, off in records]:
          raise ValueError(f"Position 0x{position:X} does not match any entry "
                           f"(entry offsets: {[hex(o) for _, o in records]})")
      else:
        raise ValueError("One of tag, index or position must be given")

      # Read the entry header: format code and dimensions come from the file
      fsh_file.seek(entry_offset)
      code_word, width, height = struct.unpack("<IHH", fsh_file.read(8))
      code = code_word & 0xFF
      if code not in FSH_CODE_NAMES:
        raise ValueError(f"Unsupported bitmap format 0x{code:02X} at offset 0x{entry_offset:X} "
                         f"(supported: {', '.join(FSH_CODE_NAMES.values())})")
      if dimensions is not None and tuple(dimensions) != (width, height):
        log.warning(f"Requested dimensions {dimensions} differ from FSH entry {(width, height)}, "
                        f"using the entry's own dimensions")

      rgba = _image_to_rgba_array(Image.open(image_file_path), (width, height))
      if code == FSH_CODE_A8R8G8B8:
        pixel_data = _encode_a8r8g8b8(rgba)
      elif code == FSH_CODE_DXT1:
        pixel_data = _encode_dxt1(rgba)
      else:
        pixel_data = _encode_dxt5(rgba)

      expected_size = _fsh_pixel_data_size(code, width, height)
      if len(pixel_data) != expected_size:
        raise ValueError(f"Encoded size {len(pixel_data)} != expected {expected_size} bytes")

      fsh_file.seek(entry_offset + 16)
      fsh_file.write(pixel_data)
      log.debug(f"Wrote {len(pixel_data)} bytes ({FSH_CODE_NAMES[code]} {width}x{height}) "
                    f"at 0x{entry_offset + 16:X}")
      return True

  except Exception as e:
    log.error(f"Unable to replace asset in {fsh_file_path}: {e}")
    return False


# Add a file to a .big archive
def add_file_to_big_archive(big_archive_filepath, new_item_filepath, file_name_in_archive=None, replace=True):
    
    if not os.path.exists(big_archive_filepath):
        log.error(f"Archive {big_archive_filepath} does not exist")
        return False
    
    if not os.path.exists(new_item_filepath):
        log.error(f"File {new_item_filepath} does not exist")
        return False
    
    if file_name_in_archive is None:
        file_name_in_archive = os.path.basename(new_item_filepath)
    
    # Read the existing archive
    with open(big_archive_filepath, 'rb') as f:
        # Read header
        magic = f.read(4).decode('ascii')
        if magic not in ['BIGF', 'BIG4']:
            log.error(f"Invalid BIG file (magic: {magic})")
            return False
        
        # Read archive size (little endian)
        archive_size = struct.unpack('<I', f.read(4))[0]
        
        # Read number of files and header size (big endian)
        num_files = struct.unpack('>I', f.read(4))[0]
        header_size = struct.unpack('>I', f.read(4))[0]
        
        # Read all file entries
        entries = []
        for _ in range(num_files):
            offset = struct.unpack('>I', f.read(4))[0]
            size = struct.unpack('>I', f.read(4))[0]
            
            # Read null-terminated filename
            name_bytes = b''
            while True:
                b = f.read(1)
                if b == b'\x00':
                    break
                name_bytes += b
            
            entries.append({
                'offset': offset,
                'size': size,
                'name': name_bytes.decode('ascii')
            })
        
        # Read all file data
        file_data = []
        for entry in entries:
            f.seek(entry['offset'])
            file_data.append(f.read(entry['size']))
    
    # Read the new file
    with open(new_item_filepath, 'rb') as f:
        new_file_data = f.read()
    
    # Check if file already exists in archive
    existing_index = None
    for i, entry in enumerate(entries):
        if entry['name'] == file_name_in_archive:
            existing_index = i
            break
    
    if existing_index is not None:
        if replace:
            # Replace existing file
            log.debug(f"Replacing existing file: {file_name_in_archive}")
            entries[existing_index]['size'] = len(new_file_data)
            file_data[existing_index] = new_file_data
        else:
            log.error(f"File {file_name_in_archive} already exists in archive")
            return False
    else:
        # Add new entry
        entries.append({
            'offset': 0,  # Will be calculated
            'size': len(new_file_data),
            'name': file_name_in_archive
        })
        file_data.append(new_file_data)
    
    # Calculate new header size
    new_header_size = 16  # Base header
    for entry in entries:
        new_header_size += 8 + len(entry['name']) + 1  # offset + size + name + null
    
    # Calculate new offsets
    current_offset = new_header_size
    for i, entry in enumerate(entries):
        entry['offset'] = current_offset
        current_offset += entry['size']
    
    # Calculate new archive size
    new_archive_size = current_offset
    
    # Write new archive
    with open(big_archive_filepath, 'wb') as f:
        # Write header
        f.write(magic.encode('ascii'))
        f.write(struct.pack('<I', new_archive_size))
        f.write(struct.pack('>I', len(entries)))
        f.write(struct.pack('>I', new_header_size))
        
        # Write entries
        for entry in entries:
            f.write(struct.pack('>I', entry['offset']))
            f.write(struct.pack('>I', entry['size']))
            f.write(entry['name'].encode('ascii') + b'\x00')
        
        # Write file data
        for data in file_data:
            f.write(data)
    
    log.debug(f"Successfully {'replaced' if existing_index is not None else 'added'} {file_name_in_archive} in {big_archive_filepath}")
    return True


# Detect EA RefPack/QFS compression (signature 0x10FB, optionally with flag bits)
def is_refpack(data):
    return len(data) >= 2 and data[1] == 0xFB and (data[0] & 0x3E) == 0x10


# Decompress an EA RefPack (a.k.a. QFS) stream, as used by Maxis/EA BIG archives.
# Header: 1 flag byte, 0xFB, optional packed-size field, then unpacked size
# (3 bytes, or 4 if the low flag bit is set), all big endian.
def refpack_decompress(data):
    if not is_refpack(data):
        raise ValueError("Not a RefPack stream")

    flags = data[0]
    pos = 2
    size_len = 4 if (flags & 0x01) else 3
    if flags & 0x80:                       # packed-size field present -> skip it
        pos += size_len
    unpacked_size = int.from_bytes(data[pos:pos + size_len], 'big')
    pos += size_len

    out = bytearray()
    while pos < len(data):
        ctrl = data[pos]; pos += 1
        if ctrl < 0x80:                    # 2-byte command
            a = data[pos]; pos += 1
            num_plain = ctrl & 0x03
            num_copy = ((ctrl & 0x1C) >> 2) + 3
            offset = ((ctrl & 0x60) << 3) + a + 1
        elif ctrl < 0xC0:                  # 3-byte command
            a = data[pos]; b = data[pos + 1]; pos += 2
            num_plain = (a >> 6) & 0x03
            num_copy = (ctrl & 0x3F) + 4
            offset = ((a & 0x3F) << 8) + b + 1
        elif ctrl < 0xE0:                  # 4-byte command
            a = data[pos]; b = data[pos + 1]; c = data[pos + 2]; pos += 3
            num_plain = ctrl & 0x03
            num_copy = ((ctrl & 0x0C) << 6) + c + 5
            offset = ((ctrl & 0x10) << 12) + (a << 8) + b + 1
        else:                              # literal run (no back-reference)
            num_plain = ((ctrl & 0x1F) << 2) + 4 if ctrl < 0xFC else ctrl & 0x03
            out += data[pos:pos + num_plain]; pos += num_plain
            if ctrl >= 0xFC:               # 0xFC-0xFF terminates the stream
                break
            continue

        out += data[pos:pos + num_plain]; pos += num_plain
        ref = len(out) - offset
        for i in range(num_copy):          # back-reference may overlap, copy byte by byte
            out.append(out[ref + i])

    if len(out) != unpacked_size:
        log.warning(f"RefPack size mismatch (got {len(out)}, expected {unpacked_size})")
    return bytes(out)


# Extract files from a .big archive by name
def extract_files_from_big_archive(big_archive_filepath, file_names, output_directory=None,
                                   decompress=True):
    """
    Extract files from a BIG archive by their names.
    
    Args:
        big_archive_filepath: Path to the BIG archive file
        file_names: List of file names to extract (or single string for one file)
        output_directory: Directory to save extracted files. If None, uses current directory
    
    Returns:
        dict: {filename: success_status} for each requested file, or False if archive is invalid
    """
    
    if not os.path.exists(big_archive_filepath):
        log.error(f"Archive {big_archive_filepath} does not exist")
        return False
    
    # Normalize file_names to a list
    if isinstance(file_names, str):
        file_names = [file_names]
    
    # Set output directory
    if output_directory is None:
        output_directory = os.getcwd()
    
    # Create output directory if it doesn't exist
    if not os.path.exists(output_directory):
        os.makedirs(output_directory)
    
    results = {requested_filename: False for requested_filename in file_names}

    # Normalize a BIG entry name for tolerant lookups: BIG names use Windows
    # backslash separators and are matched case-insensitively.
    def _normalize(name):
        return name.replace('\\', '/').lower()

    try:
        # A BIG archive may itself be RefPack-compressed as a unit (EA stores
        # some this way) — that can only be told apart from an ordinary BIG
        # by its first bytes, so peek those before deciding how to read the
        # rest. Archives like data.gob (hundreds of MB) are NOT whole-archive
        # compressed, so this lets the common case skip reading the archive
        # into memory at all: the directory is read from disk on its own
        # (a few hundred KB even for thousands of entries), and only the
        # requested entries' own byte ranges are read afterwards.
        with open(big_archive_filepath, 'rb') as raw:
            peek = raw.read(16)
            if decompress and is_refpack(peek):
                log.debug(f"Archive {os.path.basename(big_archive_filepath)} is RefPack-compressed; decompressing...")
                raw.seek(0)
                raw_data = refpack_decompress(raw.read())
                f = io.BytesIO(raw_data)
            else:
                raw.seek(0)
                f = raw

            # Read header
            magic = f.read(4)
            if magic not in (b'BIGF', b'BIG4'):
                log.error(f"Invalid BIG file (magic: {magic!r})")
                return False

            # Total archive size in bytes (little endian for BIGF/BIG4)
            archive_size = struct.unpack('<I', f.read(4))[0]

            # Number of files and header/index size (big endian)
            num_files = struct.unpack('>I', f.read(4))[0]
            header_size = struct.unpack('>I', f.read(4))[0]

            # Read all file entries
            entries = []
            for _ in range(num_files):
                entry_header = f.read(8)
                if len(entry_header) < 8:
                    raise ValueError("Truncated entry header in BIG archive")
                offset, size = struct.unpack('>II', entry_header)

                # Read null-terminated filename. Names are stored in the game's
                # 8-bit encoding, so decode as latin-1 to never raise.
                name_bytes = b''
                while True:
                    b = f.read(1)
                    if b == b'' or b == b'\x00':
                        break
                    name_bytes += b

                entries.append({
                    'offset': offset,
                    'size': size,
                    'name': name_bytes.decode('latin-1'),
                })

            # Build a lookup keyed on the normalized name for tolerant matching
            entries_by_name = {_normalize(e['name']): e for e in entries}

            # Extract requested files
            for requested_filename in file_names:
                entry = entries_by_name.get(_normalize(requested_filename))
                if entry is None:
                    log.warning(f"File not found in archive: {requested_filename}")
                    continue

                # Validate the entry stays within the archive before reading
                if entry['offset'] + entry['size'] > archive_size:
                    log.error(
                        f"Error extracting {requested_filename}: entry "
                        f"(offset={entry['offset']}, size={entry['size']}) "
                        f"exceeds archive size {archive_size}"
                    )
                    continue

                try:
                    # Read file data
                    f.seek(entry['offset'])
                    file_data = f.read(entry['size'])
                    if len(file_data) != entry['size']:
                        raise ValueError(
                            f"expected {entry['size']} bytes, got {len(file_data)}"
                        )

                    # An individual entry may itself be RefPack-compressed
                    if decompress and is_refpack(file_data):
                        file_data = refpack_decompress(file_data)

                    # Map the (possibly backslash-separated) archive path onto
                    # the local filesystem, recreating any subdirectories.
                    relative_path = entry['name'].replace('\\', os.sep)
                    output_filepath = os.path.join(output_directory, relative_path)
                    os.makedirs(os.path.dirname(output_filepath) or '.', exist_ok=True)

                    with open(output_filepath, 'wb') as out_f:
                        out_f.write(file_data)

                    log.debug(f"Successfully extracted {requested_filename} to {output_filepath}")
                    results[requested_filename] = True
                except Exception as e:
                    log.error(f"Error extracting {requested_filename}: {e}")
                    results[requested_filename] = False

    except Exception as e:
        log.error(f"Error reading archive {big_archive_filepath}: {e}")
        return False

    return results


# Stock heads live in data.gob under a hashed name: md5("players/heads/<face_id>")
# + ".big" — confirmed against the "20 - MD5 hashes" filelist on the modding
# drive (the same scheme frontend/textures/heads/<id> uses for the separate
# menu-portrait texture, which this does not need: the players/heads/<id>.big
# already bundles its own model.o + textures.fsh, RefPack-compressed as a
# whole, same as extract_files_from_big_archive already handles).
def stock_head_path(face_id, cache_dir):
    """Local path to a stock head_<face_id>.big (model.o + textures.fsh),
    extracted from data.gob and cached under `cache_dir` by face id so
    browsing players doesn't re-scan the ~450MB archive every time. None
    when face_id isn't numeric, the game isn't installed/configured, or the
    id has no head archive in data.gob."""
    try:
        face_id = int(face_id)
    except (TypeError, ValueError):
        return None
    cached = os.path.join(cache_dir, f"{face_id}.big")
    if os.path.isfile(cached):
        return cached
    gob_path = config.R08_data_gob_filepath
    if not os.path.isfile(gob_path):
        return None
    entry_name = hashlib.md5(f"players/heads/{face_id}".encode()).hexdigest() + ".big"
    try:
        os.makedirs(cache_dir, exist_ok=True)
        result = extract_files_from_big_archive(gob_path, entry_name, cache_dir)
        if not result or not result.get(entry_name):
            return None
        os.replace(os.path.join(cache_dir, entry_name), cached)
    except OSError as e:
        log.warning(f"stock head for face {face_id}: {e}")
        return None
    return cached


# The menu-portrait texture referenced in the stock_head_path comment above:
# a small standalone .fsh (no model.o, no .big wrapper) at the hashed path
# frontend/textures/heads/<face_id>, cheaper to extract and decode than the
# full head archive when all that's needed is a face thumbnail.
def stock_portrait_path(face_id, cache_dir):
    """Local path to a stock face_<face_id>_portrait.fsh, extracted from
    data.gob and cached under `cache_dir` by face id. None when face_id
    isn't numeric, the game isn't installed/configured, or the id has no
    portrait texture in data.gob."""
    try:
        face_id = int(face_id)
    except (TypeError, ValueError):
        return None
    cached = os.path.join(cache_dir, f"{face_id}_portrait.fsh")
    if os.path.isfile(cached):
        return cached
    gob_path = config.R08_data_gob_filepath
    if not os.path.isfile(gob_path):
        return None
    entry_name = hashlib.md5(f"frontend/textures/heads/{face_id}".encode()).hexdigest() + ".fsh"
    try:
        os.makedirs(cache_dir, exist_ok=True)
        result = extract_files_from_big_archive(gob_path, entry_name, cache_dir)
        if not result or not result.get(entry_name):
            return None
        os.replace(os.path.join(cache_dir, entry_name), cached)
    except OSError as e:
        log.warning(f"stock portrait for face {face_id}: {e}")
        return None
    return cached


# The stock game's generic training kit ("Kit training A" in-game, team id
# 107 / location "traina" in playermanager.xml) lives in data.gob at the
# fixed, un-hashed-looking-but-still-hashed paths "kit/kits/trn1" (front
# kit, a plain BIGF archive — not RefPack-compressed, unlike the heads) and
# "kit/kits/trn1.numbers" (back-panel shirt numbers, one per jersey number,
# all sharing FSH entry name "jbck" the way boots.fsh's styles share
# "clet" — the first is used, same as everywhere else that doesn't pass an
# explicit index). Confirmed against the "20 - MD5 hashes" filelist same as
# stock_head_path above. There's exactly one training kit A, so unlike
# heads this doesn't need a per-id cache — just a fixed pair of files.
_STOCK_KIT_ENTRIES = {"kit/kits/trn1": "big", "kit/kits/trn1.numbers": "fsh"}


def stock_kit_paths(cache_dir):
    """(front_kit_path, numbers_path) for the stock training kit A, cached
    under `cache_dir` after the first extraction from data.gob. Either (or
    both) come back None if the game isn't installed/configured or the
    entry is missing from data.gob — callers already treat a missing kit
    path as "no kit" gracefully."""
    out = {}
    gob_path = config.R08_data_gob_filepath
    for path, ext in _STOCK_KIT_ENTRIES.items():
        cached = os.path.join(cache_dir, f"{os.path.basename(path)}.{ext}")
        if os.path.isfile(cached):
            out[path] = cached
            continue
        if not os.path.isfile(gob_path):
            out[path] = None
            continue
        entry_name = hashlib.md5(path.encode()).hexdigest() + "." + ext
        try:
            os.makedirs(cache_dir, exist_ok=True)
            result = extract_files_from_big_archive(gob_path, entry_name, cache_dir)
            if not result or not result.get(entry_name):
                out[path] = None
                continue
            os.replace(os.path.join(cache_dir, entry_name), cached)
            out[path] = cached
        except OSError as e:
            log.warning(f"stock kit {path}: {e}")
            out[path] = None
    return out["kit/kits/trn1"], out["kit/kits/trn1.numbers"]


# The generic body / skin tones / boots / head every 3D player preview wears (only
# the kit is team-specific). body.o is the mod's own (split left/right skin UVs)
# and ships in assets/static_files; the two .fsh are stock data.gob entries, and
# the head is the stock face 21543 archive (model.o + textures.fsh).
_BODY_ENTRY = "dc6975fd9498de7faa1f5b263a690e5e.o"
_PREVIEW_FSH = {"skin.fsh": "e6032b2303f4b08e2765786e39b6a5f0.fsh",
                "boots.fsh": "5f1c1437ecb6fb9c7f280f5b54e47f7e.fsh"}
_GENERIC_HEAD_FACE = 21543
_preview_assets_failed = set()


def _same_file(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def player_preview_assets(cache_dir):
    """{'body': .o, 'skin': .fsh, 'boots': .fsh, 'head': .big or None} paths for the
    3D player preview, extracted once into `cache_dir`. None when a required file
    (body, skin, boots) is unavailable; the head is optional. A failed attempt is
    not repeated during this run (each one scans the ~450MB data.gob)."""
    out = {"body": os.path.join(cache_dir, "body.o"),
           "skin": os.path.join(cache_dir, "skin.fsh"),
           "boots": os.path.join(cache_dir, "boots.fsh")}
    missing = [k for k, v in out.items() if not os.path.isfile(v)]
    # body.o ships with the mod and changes between versions (it once got split
    # left/right skin UVs): a copy cached by an older build must be replaced.
    bundled_body = config._bundled_dll(_BODY_ENTRY)
    if "body" not in missing and not _same_file(bundled_body, out["body"]):
        missing.append("body")
    if missing and cache_dir in _preview_assets_failed:
        return None
    if missing:
        try:
            os.makedirs(cache_dir, exist_ok=True)
            if "body" in missing:
                shutil.copyfile(config._bundled_dll(_BODY_ENTRY), out["body"])
            wanted = {n: e for n, e in _PREVIEW_FSH.items() if n[:-4] in missing}
            if wanted:
                res = extract_files_from_big_archive(config.R08_data_gob_filepath,
                                                     list(wanted.values()), cache_dir)
                for name, entry in wanted.items():
                    if res and res.get(entry):
                        os.replace(os.path.join(cache_dir, entry), os.path.join(cache_dir, name))
        except OSError as e:
            log.warning(f"3D preview assets: {e}")
        missing = [k for k, v in out.items() if not os.path.isfile(v)]
        if missing:
            _preview_assets_failed.add(cache_dir)
            log.warning(f"3D preview assets missing: {missing}")
            return None
    out["head"] = stock_head_path(_GENERIC_HEAD_FACE, cache_dir)
    return out


# Normalise the player's skin_overlay field to a list of overlays, from bottom to top.
# The field is either False/unset, a single image path, or a list of image paths
# (first item at the bottom).
def get_skin_overlays(player):
    value = player.get('skin_overlay', False)
    if isinstance(value, (list, tuple)):
        return [v for v in value if is_custom_asset(v)]
    return [value] if is_custom_asset(value) else []


# Return True if a config value is a custom asset path that points to an existing
# file under `root` (the mod data directory).
def custom_asset_exists(value, root):
  return is_custom_asset(value) and os.path.isfile(os.path.join(root, value))


# Resolve which textures make up a player's skin, exactly as they will be written
# to the skins FSH file. Returns (custom_skin_filepath or None, overlay_filepaths)
# where overlays are ordered bottom to top (skin_overlay items, then a custom
# gloves image) and only contain files that exist. Missing files are reported
# and skipped, so the roster never points at a custom slot nobody filled.
def resolve_player_skin_layers(player, root, stock_skins=()):
  skin = player.get('skin', '')
  custom_skin = None
  if skin not in stock_skins and custom_asset_exists(skin, root):
    custom_skin = os.path.join(root, skin)
  elif skin not in stock_skins:
    log.warning(f"Skin file not found for player {player.get('name')}: {skin}")
  overlays = []
  for value in get_skin_overlays(player) + [player.get('gloves', False)]:
    if not is_custom_asset(value):
      continue
    if custom_asset_exists(value, root):
      overlays.append(os.path.join(root, value))
    else:
      log.warning(f"Overlay file not found for player {player.get('name')}: {os.path.join(root, str(value))}")
  return custom_skin, overlays
  
# This function converts cm to inches
def cm_to_feet_and_inches(cm):
  # 1 inch = 2.54 cm
  # 1 foot = 12 inches
  inches = cm / 2.54
  feet = int(inches // 12)
  remaining_inches = round(inches % 12, 2)
  return feet, remaining_inches

def _embedding_possible():
  """True when the frontend will take charge of the game window (embed it, or
  reveal it fullscreen), i.e. it is safe to boot the window off-screen
  (someone will move it back)."""
  if not getattr(config, "embed_game", True):
    return False
  if config.platform == "linux":
    return bool(shutil.which("xdotool"))
  return True


def _game_is_dpi_aware(exe_filepath):
  """True when Windows will let the game see the real screen resolution. The
  2007 exe has no dpiAware manifest, so that only happens when the exe is
  marked HIGHDPIAWARE in the app-compat layers (per user, then per machine)."""
  if config.platform != "windows":
    return True
  try:
    import winreg
  except ImportError:
    return False
  key = r"Software\Microsoft\Windows NT\CurrentVersion\AppCompatFlags\Layers"
  for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
    try:
      with winreg.OpenKey(root, key) as layers:
        value, _ = winreg.QueryValueEx(layers, exe_filepath)
    except OSError:
      continue
    tokens = str(value).upper().split()
    if "DPIUNAWARE" in tokens:
      return False
    if "HIGHDPIAWARE" in tokens:
      return True
  return False


def _wine_binary():
  """The wine executable used to run the game (the launcher IS wine on Linux)."""
  wine_binary = config.game_launcher_executable_filepath
  if "wine" not in os.path.basename(wine_binary).lower():
    wine_binary = shutil.which("wine") or "wine"
  return wine_binary


def _wine_user_reg_has(marker, value_line):
  """True if the prefix's user.reg already contains `value_line` within the
  section whose header contains `marker`. Cheap idempotency check that avoids
  spinning wine/wineserver on every launch."""
  wine_prefix = config.game_launcher_environment.get("WINEPREFIX") or os.path.expanduser("~/.wine")
  user_reg = os.path.join(wine_prefix, "user.reg")
  try:
    with open(user_reg, 'r', encoding='utf-8', errors='replace') as f:
      content = f.read()
    idx = content.find(marker)
    return idx != -1 and value_line in content[idx:idx + 500]
  except Exception:
    return False  # can't read the registry file — caller will just run wine reg


def _wine_reg_add(key, value_name, data, description):
  """Best-effort `wine reg add` with logging; never raises."""
  try:
    result = subprocess.run(
      [_wine_binary(), "reg", "add", key, "/v", value_name, "/t", "REG_SZ", "/d", data, "/f"],
      capture_output=True, text=True, timeout=60,
      env=config.game_launcher_environment,
    )
    if result.returncode == 0:
      log.debug(description)
    else:
      log.warning(f"wine reg add failed ({description}): {result.stderr.strip()}")
  except Exception as e:
    log.warning(f"wine reg add failed ({description}): {e}")


def _wine_reg_delete(args, description):
  """Best-effort `wine reg delete`; never raises."""
  try:
    result = subprocess.run(
      [_wine_binary(), "reg", "delete", *args, "/f"],
      capture_output=True, text=True, timeout=60,
      env=config.game_launcher_environment,
    )
    if result.returncode == 0:
      log.debug(description)
  except Exception as e:
    log.warning(f"wine reg delete failed ({description}): {e}")


def disable_wine_virtual_desktop():
  """Wine only: remove the prefix-global virtual desktop (winecfg "Emulate a
  virtual desktop"). It is obsolete for this game — the d3d8 proxy keeps the
  game windowed and blocks display-mode switches — and its bare (blue) desktop
  window pops up over everything during boot.

  NOTE: a per-app AppDefaults\\<exe>\\Explorer "Desktop"="" override does NOT
  work: wine then fails to create the desktop window at all and the game hangs
  invisibly (get_desktop_window errors). So the global value must go; any
  leftover per-app override from older versions is deleted too. Idempotent,
  best-effort."""
  if config.platform != "linux" or not config.wine_disable_virtual_desktop:
    return
  exe_name = config.R08_filename

  # Remove the broken per-app override if an older version wrote it
  if _wine_user_reg_has(f"Software\\\\Wine\\\\AppDefaults\\\\{exe_name}\\\\Explorer",
                        '"Desktop"'):
    _wine_reg_delete([f"HKCU\\Software\\Wine\\AppDefaults\\{exe_name}\\Explorer"],
                     f"Removed broken per-app Desktop override for {exe_name}")

  # Remove the global virtual desktop setting
  if _wine_user_reg_has("[Software\\\\Wine\\\\Explorer]", '"Desktop"'):
    _wine_reg_delete(["HKCU\\Software\\Wine\\Explorer", "/v", "Desktop"],
                     "Wine virtual desktop disabled (global)")


def ensure_wine_d3d8_native_override():
  """Wine only: per-app dll override so the proxy d3d8.dll placed next to the
  exe is actually loaded. Without "d3d8"="native,builtin", wine silently loads
  its BUILTIN d3d8 and the whole proxy (windowed mode, mode-switch block,
  rugby08patches chain-load) never runs. Idempotent, best-effort."""
  if config.platform != "linux":
    return
  exe_name = config.R08_filename
  if _wine_user_reg_has(f"Software\\\\Wine\\\\AppDefaults\\\\{exe_name}\\\\DllOverrides",
                        '"d3d8"="native,builtin"'):
    return
  _wine_reg_add(f"HKCU\\Software\\Wine\\AppDefaults\\{exe_name}\\DllOverrides",
                "d3d8", "native,builtin",
                f"Wine dll override d3d8=native,builtin set for {exe_name}")


def _set_ini_value(ini_filepath, section, key, value):
  """Set section/key in an ini file, leaving every other line as the user wrote it
  (creates the file/section when missing)."""
  try:
    with open(ini_filepath, encoding="utf-8", errors="replace") as f:
      lines = f.read().splitlines()
  except OSError:
    lines = []
  current = None
  section_end = None      # index just after the last line of `section`
  for i, line in enumerate(lines):
    stripped = line.strip()
    if stripped.startswith("[") and stripped.endswith("]"):
      current = stripped[1:-1].strip().lower()
      if current == section.lower():
        section_end = i + 1
      continue
    if current == section.lower():
      if stripped:
        section_end = i + 1
      name = stripped.split("=", 1)[0].strip().lower() if "=" in stripped else None
      if name == key.lower():
        lines[i] = f"{key} = {value}"
        break
  else:
    if section_end is None:
      lines += [f"[{section}]", f"{key} = {value}"]
    else:
      lines.insert(section_end, f"{key} = {value}")
  with open(ini_filepath, "w", encoding="utf-8") as f:
    f.write("\n".join(lines) + "\n")


def _describe_game_files(game_dir, names):
  """One INFO line per file: size, mtime and MD5, to compare two installs."""
  for name in names:
    path = os.path.join(game_dir, name)
    try:
      stat = os.stat(path)
      with open(path, "rb") as f:
        digest = hashlib.md5(f.read()).hexdigest()
      log.info(f"game file {name}: {stat.st_size} bytes, mtime {int(stat.st_mtime)}, md5 {digest}")
    except OSError as e:
      log.info(f"game file {name}: missing ({e})")


def log_game_session(game_dir, max_lines=150):
  """Copy the newest session of rugby08_patches.log (proxy + patches DLL, next
  to the exe) into the app log, so one file tells the whole story of a launch
  (window sizes, profile load, patch install timing)."""
  if not logging_active():
    return
  path = os.path.join(game_dir, "rugby08_patches.log")
  try:
    with open(path, "r", encoding="utf-8", errors="replace") as f:
      lines = f.read().splitlines()
  except OSError as e:
    log.info(f"No game log to read ({path}): {e}")
    return
  start = 0
  for i, line in enumerate(lines):
    if line.startswith("==== session"):
      start = i
  session = lines[start:]
  log.info(f"Game log {path}: {len(session)} lines in the last session")
  for line in session[:max_lines]:
    log.info(f"  game| {line}")
  if len(session) > max_lines:
    log.info(f"  game| ... {len(session) - max_lines} more lines in the file")


def configure_game_logging(game_dir):
  """Game-side logs (proxy + patches DLL share rugby08_patches.log next to the
  exe) follow the mod's log level: on for every level but OFF. Returns True if on."""
  enabled = logging_active()
  ini = os.path.join(game_dir, "rugby08patches.ini")
  try:
    if enabled or os.path.isfile(ini):
      _set_ini_value(ini, "general", "log", "1" if enabled else "0")
  except OSError as e:
    log.warning(f"cannot update {ini}: {e}")
  if enabled:
    log.info(f"Game logs on: {os.path.join(game_dir, 'rugby08_patches.log')}")
  return enabled


def configure_d3d8_proxy():
  """Deploy the d3d8.dll proxy (windowed mode + embeddable window) next to the
  game exe, optionally the rugby08patches.dll gameplay patches, and generate the
  rugby08_windowed.ini that drives the proxy."""
  game_dir = config.game_launcher_directory

  # Make wine actually load the proxy (native d3d8.dll next to the exe)
  ensure_wine_d3d8_native_override()
  # No virtual desktop needed: the proxy keeps the game windowed
  disable_wine_virtual_desktop()

  # Copy the proxy d3d8.dll next to the exe
  if not copy_file(config.d3d8proxy_dll_filepath, os.path.join(game_dir, "d3d8.dll")):
    return False

  # Copy the gameplay patches DLL (chain-loaded by the proxy)
  if config.use_rugby08patches:
    if not copy_file(config.rugby08patches_dll_filepath,
                     os.path.join(game_dir, "rugby08patches.dll")):
      return False

  game_log = configure_game_logging(game_dir)
  if game_log:
    _describe_game_files(game_dir, ["d3d8.dll", "rugby08patches.dll", "user_profile.pro",
                                    "rugby08patches.ini"])

  # Generate rugby08_windowed.ini from config
  def onezero(value):
    return "1" if value else "0"

  # Boot the window off-screen so it never flashes on the desktop before the
  # frontend reparents it. Only when embedding will actually happen; the
  # frontend moves the window back on-screen if embedding times out.
  offscreen = config.d3d8_offscreen_boot and _embedding_possible()
  pos_x, pos_y = (-10000, -10000) if offscreen else (60, 60)

  # Mode: "all" (both this app and the game stay windowed/embedded) or
  # "frontend-fullscreen" (game still boots windowed, this app goes
  # fullscreen around it) — implemented by the d3d8 proxy DLL. Driven
  # by the same Settings > Windowed Mode toggle as the frontend's own window
  # (main.MainWindow.apply_windowed_mode), not the separate config.d3d8_mode
  # (an unused advanced override now that Settings owns this).
  d3d8_mode = "all" if user_prefs.game_windowed else "frontend-fullscreen"

  # The proxy vetoes any resize to >= monitor size (the game trying to go
  # fullscreen) and snaps the client area to FrontendWidth x FrontendHeight
  # instead — including the frontend's own fullscreen reveal. Make that size
  # the target monitor so the veto lands on exactly the fullscreen we want.
  frontend_w, frontend_h = config.d3d8_frontend_width, config.d3d8_frontend_height
  monitor = getattr(config, "reveal_monitor_rect", None)
  linux_embedded = (config.platform == "linux" and getattr(config, "embed_frontend_size", False)
                    and monitor)
  if linux_embedded:
    # Linux: the game is embedded and stretched to fill its host (the fullscreen
    # mod window, or the game screen of a windowed one) — same idea, the size the
    # game must render at is that host's physical size.
    left, top, right, bottom = monitor
    frontend_w, frontend_h = right - left, bottom - top
  elif (config.platform == "windows" and getattr(config, "reveal_fullscreen", False)
          and monitor):
    left, top, right, bottom = monitor
    frontend_w, frontend_h = right - left, bottom - top
    # The proxy runs inside the game, so it compares sizes in the GAME's
    # coordinates. Rugby08.exe has no dpiAware manifest: unless the exe is
    # marked HIGHDPIAWARE, Windows hides the real resolution from it and scales
    # its window afterwards, so a scaled screen must be written here divided by
    # that scaling (1920x1080 at 150% -> 1280x720) or the reveal comes out
    # oversized.
    if not _game_is_dpi_aware(config.game_launcher_executable_filepath):
      scale = float(getattr(config, "reveal_monitor_scale", 1.0) or 1.0)
      if scale > 0:
        frontend_w, frontend_h = round(frontend_w / scale), round(frontend_h / scale)
        log.debug(f"Game is DPI-unaware: proxy frontend size {frontend_w}x{frontend_h} "
              f"(monitor {right - left}x{bottom - top} at {scale:.2f}x)")

  ini_lines = [
    "[windowed]",
    "Enable=1",
    f"Mode={d3d8_mode}",
    f"AllowResize={onezero(config.d3d8_allow_resize)}",
    f"Borderless={onezero(config.d3d8_borderless)}",
    f"KeepActive={onezero(config.d3d8_keep_active)}",
    f"BlockModeSwitch={onezero(config.d3d8_block_mode_switch)}",
    f"PosX={pos_x}",
    f"PosY={pos_y}",
    f"Width={config.d3d8_loading_width}",
    f"Height={config.d3d8_loading_height}",
    f"FrontendWidth={frontend_w}",
    f"FrontendHeight={frontend_h}",
    f"Log={onezero(config.d3d8_log or game_log)}",
    f"LoadPatchesDll={onezero(config.use_rugby08patches)}",
    "PatchesDll=rugby08patches.dll",
  ]

  ini_filepath = os.path.join(game_dir, "rugby08_windowed.ini")
  try:
    with open(ini_filepath, 'w', encoding='utf-8') as f:
      f.write("\n".join(ini_lines) + "\n")
    log.debug(f"Successfully wrote {ini_filepath}")
    log.info("Proxy ini: " + " ".join(l for l in ini_lines if "=" in l))
    return True

  except Exception as e:
    log.error(f"Unable to write d3d8 proxy ini {ini_filepath}: {e}")
    return False

