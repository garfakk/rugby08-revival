#!/usr/bin/env python3
"""EA SHPI (.fsh) texture codec for Rugby 08.

Record codes seen in the game data (survey of data.gob):
  0x60 DXT1, 0x62 DXT5, 0x7d ARGB8888, 0x7f RGB888
Entry layout: 16-byte header {u8 code, u24 next, u16 w, u16 h, ...} + pixel
data (+ optional trailing attachments e.g. "EAGL64 metal bin" - preserved
verbatim on re-encode).
"""
import struct

import numpy as np
from PIL import Image


def _un565(c):
    r = (c >> 11) & 31; g = (c >> 5) & 63; b = c & 31
    return ((r * 255) // 31, (g * 255) // 63, (b * 255) // 31)


def _dxt_colors(c0, c1, dxt1):
    p0, p1 = _un565(c0), _un565(c1)
    if dxt1 and c0 <= c1:
        p2 = tuple((a + b) // 2 for a, b in zip(p0, p1)); p3 = (0, 0, 0)
    else:
        p2 = tuple((2 * a + b) // 3 for a, b in zip(p0, p1))
        p3 = tuple((a + 2 * b) // 3 for a, b in zip(p0, p1))
    return p0, p1, p2, p3


def dxt1_decode(data, w, h):
    """Whole-image DXT1 decode, block maths vectorised over numpy.

    Same output as decoding block by block in python, ~50x faster: this runs
    once per texture every time a kit preview is built, and the per-texel loop
    was most of the wait when the match-setup screen opens.
    """
    bx_count, by_count = (w + 3) // 4, (h + 3) // 4
    blocks = np.frombuffer(data, dtype=np.uint8,
                           count=bx_count * by_count * 8).reshape(-1, 8).astype(np.uint32)
    c0 = blocks[:, 0] | (blocks[:, 1] << 8)
    c1 = blocks[:, 2] | (blocks[:, 3] << 8)
    bits = (blocks[:, 4] | (blocks[:, 5] << 8)
            | (blocks[:, 6] << 16) | (blocks[:, 7] << 24))

    def un565(c):
        return np.stack([(((c >> 11) & 31) * 255) // 31,
                         (((c >> 5) & 63) * 255) // 63,
                         ((c & 31) * 255) // 31], axis=1)

    p0, p1 = un565(c0), un565(c1)
    # c0 > c1 selects the 4-colour (opaque) block layout, else 3 colours + a
    # transparent index 3 — as in _dxt_colors(..., dxt1=True).
    four = (c0 > c1)[:, None]
    p2 = np.where(four, (2 * p0 + p1) // 3, (p0 + p1) // 2)
    p3 = np.where(four, (p0 + 2 * p1) // 3, 0)
    palette = np.stack([p0, p1, p2, p3], axis=1).astype(np.uint8)   # (blocks, 4, 3)
    alpha = np.full((len(palette), 4), 255, dtype=np.uint8)
    alpha[~four[:, 0], 3] = 0

    texel = np.arange(16, dtype=np.uint32)
    idx = (bits[:, None] >> (texel * 2)) & 3                        # (blocks, 16)
    rows = np.arange(len(palette))[:, None]
    rgba = np.empty((len(palette), 16, 4), dtype=np.uint8)
    rgba[:, :, :3] = palette[rows, idx]
    rgba[:, :, 3] = alpha[rows, idx]

    # blocks are stored left-to-right, top-to-bottom; each holds a 4x4 tile
    img = (rgba.reshape(by_count, bx_count, 4, 4, 4)
               .transpose(0, 2, 1, 3, 4)
               .reshape(by_count * 4, bx_count * 4, 4))
    return img[:h, :w].tobytes()


def dxt5_decode(data, w, h):
    """DXT5 counterpart of dxt1_decode — same output, vectorised the same way."""
    bx_count, by_count = (w + 3) // 4, (h + 3) // 4
    blocks = np.frombuffer(data, dtype=np.uint8,
                           count=bx_count * by_count * 16).reshape(-1, 16).astype(np.uint32)
    a0, a1 = blocks[:, 0], blocks[:, 1]
    abits = np.zeros(len(blocks), dtype=np.uint64)
    for shift in range(6):                      # 48-bit little-endian alpha indices
        abits |= blocks[:, 2 + shift].astype(np.uint64) << np.uint64(shift * 8)
    c0 = blocks[:, 8] | (blocks[:, 9] << 8)
    c1 = blocks[:, 10] | (blocks[:, 11] << 8)
    bits = (blocks[:, 12] | (blocks[:, 13] << 8)
            | (blocks[:, 14] << 16) | (blocks[:, 15] << 24))

    def un565(c):
        return np.stack([(((c >> 11) & 31) * 255) // 31,
                         (((c >> 5) & 63) * 255) // 63,
                         ((c & 31) * 255) // 31], axis=1)

    # DXT5 always uses the 4-colour layout (_dxt_colors(..., dxt1=False))
    p0, p1 = un565(c0), un565(c1)
    palette = np.stack([p0, p1, (2 * p0 + p1) // 3, (p0 + 2 * p1) // 3],
                       axis=1).astype(np.uint8)
    # Alpha ramp: 8 values, 6-step when a0 > a1, otherwise 4-step plus 0/255
    alut = np.zeros((len(blocks), 8), dtype=np.uint8)
    wide = a0 > a1
    alut[:, 0], alut[:, 1] = a0, a1
    for j in range(1, 7):
        alut[wide, 1 + j] = (((7 - j) * a0[wide] + j * a1[wide]) // 7).astype(np.uint8)
    for j in range(1, 5):
        alut[~wide, 1 + j] = (((5 - j) * a0[~wide] + j * a1[~wide]) // 5).astype(np.uint8)
    alut[~wide, 6], alut[~wide, 7] = 0, 255

    texel = np.arange(16, dtype=np.uint32)
    idx = (bits[:, None] >> (texel * 2)) & 3
    aidx = (abits[:, None] >> (texel.astype(np.uint64) * np.uint64(3))) & np.uint64(7)
    rows = np.arange(len(blocks))[:, None]
    rgba = np.empty((len(blocks), 16, 4), dtype=np.uint8)
    rgba[:, :, :3] = palette[rows, idx]
    rgba[:, :, 3] = alut[rows, aidx.astype(np.intp)]

    img = (rgba.reshape(by_count, bx_count, 4, 4, 4)
               .transpose(0, 2, 1, 3, 4)
               .reshape(by_count * 4, bx_count * 4, 4))
    return img[:h, :w].tobytes()


def _565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def dxt_encode_block_colors(px):
    """px = 16 (r,g,b) tuples -> (c0,c1,bits) simple min/max encoder."""
    lo = min(px, key=sum); hi = max(px, key=sum)
    c0, c1 = _565(*hi), _565(*lo)
    if c0 == c1:
        return c0, c1, 0
    if c0 < c1:
        c0, c1 = c1, c0
        lo, hi = hi, lo
    cols = _dxt_colors(c0, c1, False)
    bits = 0
    for t, p in enumerate(px):
        best = min(range(4), key=lambda ci: sum((a - b) ** 2 for a, b in zip(p, cols[ci])))
        bits |= best << (t * 2)
    return c0, c1, bits


def dxt1_encode(rgba, w, h):
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            px = [tuple(rgba[((by + py) * w + bx + px_) * 4:((by + py) * w + bx + px_) * 4 + 3])
                  for py in range(4) for px_ in range(4)]
            c0, c1, bits = dxt_encode_block_colors(px)
            out += struct.pack('<HHI', c0, c1, bits)
    return bytes(out)


def dxt5_encode(rgba, w, h):
    out = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            idx = [((by + py) * w + bx + px_) * 4 for py in range(4) for px_ in range(4)]
            px = [tuple(rgba[o:o + 3]) for o in idx]
            al = [rgba[o + 3] for o in idx]
            a0, a1 = max(al), min(al)
            out += bytes((a0, a1))
            abits = 0
            if a0 > a1:
                alut = [a0, a1] + [((7 - j) * a0 + j * a1) // 7 for j in range(1, 7)]
            else:
                alut = [a0, a1, 0, 255] if a0 == a1 else [a0, a1] + [((5 - j) * a0 + j * a1) // 5 for j in range(1, 5)] + [0, 255]
            for t, a in enumerate(al):
                best = min(range(len(alut)), key=lambda ai: abs(alut[ai] - a))
                abits |= best << (t * 3)
            out += abits.to_bytes(6, 'little')
            c0, c1, bits = dxt_encode_block_colors(px)
            out += struct.pack('<HHI', c0, c1, bits)
    return bytes(out)


class FshEntry:
    def __init__(self, name, code, w, h, pixofs, pixlen, raw):
        self.name, self.code, self.w, self.h = name, code, w, h
        self.pixofs, self.pixlen, self.raw = pixofs, pixlen, raw

    def decode(self):
        d = self.raw[self.pixofs:self.pixofs + self.pixlen]
        if self.code == 0x60: rgba = dxt1_decode(d, self.w, self.h)
        elif self.code == 0x62: rgba = dxt5_decode(d, self.w, self.h)
        elif self.code == 0x7d: rgba = bytes(b for p in struct.iter_unpack('<I', d)
                                             for b in ((p[0] >> 0) & 255, (p[0] >> 8) & 255,
                                                       (p[0] >> 16) & 255, (p[0] >> 24) & 255))
        elif self.code == 0x7f:
            rgba = b''.join(d[i:i + 3] + b'\xff' for i in range(0, self.w * self.h * 3, 3))
        else:
            raise ValueError(f'unsupported fsh code {self.code:#x}')
        return Image.frombytes('RGBA', (self.w, self.h), rgba)

    def encode(self, img):
        img = img.convert('RGBA').resize((self.w, self.h)) if img.size != (self.w, self.h) \
              else img.convert('RGBA')
        rgba = img.tobytes()
        if self.code == 0x60: return dxt1_encode(rgba, self.w, self.h)
        if self.code == 0x62: return dxt5_encode(rgba, self.w, self.h)
        if self.code == 0x7d:
            return b''.join(struct.pack('<I', (a << 24) | (b_ << 16) | (g << 8) | r)
                            for r, g, b_, a in struct.iter_unpack('4B', rgba))
        if self.code == 0x7f:
            return b''.join(bytes(p[:3]) for p in struct.iter_unpack('4B', rgba))
        raise ValueError(f'unsupported fsh code {self.code:#x}')


class Fsh:
    def __init__(self, blob):
        assert blob[:4] == b'SHPI', 'not SHPI'
        self.blob = bytearray(blob)
        total, n = struct.unpack('<II', blob[4:12])
        self.dir_id = blob[12:16]
        self.entries = []
        offs = [(struct.unpack_from('<4sI', blob, 16 + i * 8)) for i in range(n)]
        sorted_offs = sorted(o for _, o in offs) + [len(blob)]
        for name, off in offs:
            code = blob[off]
            w, h = struct.unpack_from('<HH', blob, off + 4)
            end = next(x for x in sorted_offs if x > off)
            if code == 0x60: plen = w * h // 2
            elif code == 0x62: plen = w * h
            elif code == 0x7d: plen = w * h * 4
            elif code == 0x7f: plen = w * h * 3
            else: plen = end - off - 16
            self.entries.append(FshEntry(name.decode('latin1').strip('\0'),
                                         code, w, h, off + 16, plen, self.blob))

    def replace(self, entry, img):
        """Re-encode img into entry's pixel area in-place (same size/format)."""
        enc = entry.encode(img)
        assert len(enc) == entry.pixlen, 'encoded size mismatch'
        self.blob[entry.pixofs:entry.pixofs + entry.pixlen] = enc

    def save(self, path):
        open(path, 'wb').write(self.blob)
