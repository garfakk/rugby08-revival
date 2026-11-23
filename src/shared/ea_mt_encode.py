"""
shared/ea_mt_encode.py — MicroTalk encoder and SCHl writer, the reverse of
shared/ea_mt.py: turns 22050 Hz mono samples into a clip in the format of
the commentary name clips in Audio/dat_eng.big.

The codec is a port of utkencode.c by Andrew D'Addesio (UNLICENSE / public
domain, https://github.com/daddesio/utkencode). The stock clips use its
default settings (halved innovation, Huffman threshold 24, gain 64 x 1.068,
about 40 kbit/s), which EA's own encoder used too.

The SCHl layout copies the stock clips: SCHl header, SCCl (block count),
SCDl blocks of 11 frames then 10 (each frame byte-aligned and preceded by a
flag byte, 0x00 = no PCM patch), SCEl.

    encode_schl(samples, rate=22050) -> bytes
"""
import struct

from shared.ea_mt import _RC

_BITRATE = 40000
_HUFF_THRESHOLD = 24
_GAIN_SIG = 64
_GAIN_BASE = 1.068

# (bits value, bits count) for -13..+13 in the two Huffman models
_HUFF = (
    [(16255, 16), (8063, 15), (3967, 14), (1919, 13), (895, 12), (383, 11), (127, 10),
     (63, 8), (31, 7), (15, 6), (7, 5), (3, 4), (2, 2), (0, 2), (1, 2), (11, 4), (23, 5),
     (47, 6), (95, 7), (191, 8), (639, 10), (1407, 11), (2943, 12), (6015, 13),
     (12159, 14), (24447, 15), (49023, 16)],
    [(8127, 15), (4031, 14), (1983, 13), (959, 12), (447, 11), (191, 10), (63, 9),
     (31, 7), (15, 6), (7, 5), (3, 4), (1, 3), (2, 3), (0, 2), (6, 3), (5, 3), (11, 4),
     (23, 5), (47, 6), (95, 7), (319, 9), (703, 10), (1471, 11), (3007, 12),
     (6079, 13), (12223, 14), (24511, 15)],
)

_GAINS = [float(_GAIN_SIG)]
for _ in range(63):
    _GAINS.append(_GAINS[-1] * _GAIN_BASE)


class _Bits:
    """LSB-first bit writer."""
    def __init__(self):
        self.value = 0
        self.count = 0

    def write(self, value, n):
        self.value |= (value & ((1 << n) - 1)) << self.count
        self.count += n

    def extend(self, other):
        self.write(other.value, other.count)

    def to_bytes(self):
        n = (self.count + 7) // 8
        return self.value.to_bytes(n, "little") if n else b""


def _quantize(value, table):
    best, best_d = 0, abs(value - table[0])
    for i in range(1, len(table)):
        d = abs(value - table[i])
        if d < best_d:
            best, best_d = i, d
    return best


def _find_rc(x):
    """Reflection coefficients of 432 samples (Levinson-Durbin)."""
    r = [0.0] * 13
    for i in range(13):
        r[i] = sum(x[j] * x[j + i] for j in range(432 - i))
    k = [0.0] * 12
    if abs(r[0]) <= 1.0 / 32768:
        return k
    a = [0.0] * 12
    a[0] = 1.0
    e = r[0]
    xv = [0.0] * 12
    y = r[1:]
    xv[0] = y[0] / r[0]
    for i in range(1, 12):
        u = sum(a[j] * r[i - j] for j in range(i))
        k[i - 1] = -u / e
        e += u * k[i - 1]
        if abs(e) <= 1.0 / 32768:
            return [0.0] * 12
        t = a[:i]
        a[i] = 0.0
        for j in range(1, i + 1):
            a[j] += k[i - 1] * t[i - j]
        m = y[i]
        for j in range(i):
            m -= xv[j] * r[i - j]
        m /= e
        xv[i] = 0.0
        for j in range(i + 1):
            xv[j] += m * a[i - j]
    k[11] = -xv[11]
    return k


def _rc_to_lpc(k):
    a = [1.0] + [0.0] * 12
    for i in range(1, 13):
        t = a[:i]
        a[i] = 0.0
        for j in range(1, i + 1):
            a[j] += k[i - 1] * t[i - j]
    return [-a[i] for i in range(1, 13)]


def _interp(x, o, a, z):
    """utkencode interpolate() on x[o:o+108] (5 samples of padding each side)."""
    if z:
        for i in range(o + (not a), o + 108, 2):
            x[i] = 0.0
    else:
        for i in range(o + (not a), o + 108, 2):
            x[i] = ((x[i - 1] + x[i + 1]) * .5973859429 - (x[i - 3] + x[i + 3]) * .1145915613
                    + (x[i - 5] + x[i + 5]) * .0180326793)


def _interp_error(x, o, a, z):
    err = 0.0
    if z:
        for i in range(o + (not a), o + 108, 2):
            err += x[i] * x[i]
    else:
        for i in range(o + (not a), o + 108, 2):
            p = ((x[i - 1] + x[i + 1]) * .5973859429 - (x[i - 3] + x[i + 3]) * .1145915613
                 + (x[i - 5] + x[i + 5]) * .0180326793)
            err += (p - x[i]) ** 2
    return err


def _encode_huffman(inn, o, pow_, a, z):
    gain = _GAINS[pow_] * (1.0 if z else 0.5)
    bits = _Bits()
    bits.write(pow_ | (a << 6) | (z << 7), 8)
    out = [0.0] * 108
    values = [0] * 108
    err = 0.0
    for i in range(a, 108, 2):
        v = inn[o + i] / gain
        v = max(-13.0, min(13.0, v))
        v = int(v + 0.5) if v >= 0 else -int(-v + 0.5)
        values[i] = v
        out[i] = gain * v
        err += (out[i] - inn[o + i]) ** 2
    zeros = [0] * 108
    c = 0
    for i in range(108 - 2 - a, -1, -2):          # the decoder's off-by-one, see utkencode
        c = c + 1 if values[i] == 0 else 0
        zeros[i] = c
    i, model = a, 0
    while i < 108:
        if zeros[i] >= 7:
            n = min(zeros[i], 70)
            if model == 0:
                bits.write(255 | ((n - 7) << 8), 14)
            else:
                bits.write(127 | ((n - 7) << 7), 13)
            model = 0
            i += n * 2
        else:
            v = values[i]
            bits.write(*_HUFF[model][13 + v])
            model = 1 if (v < -1 or v > 1) else 0
            i += 2
    return bits, out, err


def _encode_triangular(inn, o, pow_, a, z):
    gain = 2.0 * _GAINS[pow_] * (1.0 if z else 0.5)
    bits = _Bits()
    bits.write(pow_ | (a << 6) | (z << 7), 8)
    out = [0.0] * 108
    err = 0.0
    for i in range(a, 108, 2):
        v = inn[o + i] / gain
        v = 1 if v >= 0.5 else (-1 if v <= -0.5 else 0)
        if v > 0:
            bits.write(3, 2)
        elif v < 0:
            bits.write(1, 2)
        else:
            bits.write(0, 1)
        out[i] = gain * v
        err += (out[i] - inn[o + i]) ** 2
    return bits, out, err


def _encode_innovation(bw, inn, use_huffman, target):
    o = 5
    a, z = 0, 1
    best = _interp_error(inn, o, 0, 1)
    for ta, tz in ((1, 1), (0, 0), (1, 0)):
        e = _interp_error(inn, o, ta, tz)
        if e < best:
            best, a, z = e, ta, tz
    # weak low-pass before halving
    src = inn[:]
    for i in range(o + a, o + 108, 2):
        inn[i] = (1.0 if z else 0.5) * (src[i] + (src[i - 1] + src[i + 1]) * 0.6189590521549956
                                        + (src[i - 3] + src[i + 3]) * -0.1633990749076792
                                        + (src[i - 5] + src[i + 5]) * 0.05858453198856907)
    if use_huffman:
        mx = max(abs(inn[i]) for i in range(o + a, o + 108, 2))
        i = 62
        while i >= 0 and not (_GAINS[i] * (1.0 if z else 0.5) * 13.5 < mx):
            i -= 1
        min_pow = i + 1
        chosen = None
        for p in range(min_pow, 64):
            bits, out, err = _encode_huffman(inn, o, p, a, z)
            d = abs(bits.count - target)
            if chosen is None or d < chosen[0]:
                chosen = (d, bits, out)
    else:
        chosen = None
        for p in range(64):
            bits, out, err = _encode_triangular(inn, o, p, a, z)
            if chosen is None or err < chosen[0]:
                chosen = (err, bits, out)
    bw.extend(chosen[1])
    for i in range(108):
        inn[o + i] = chosen[2][i]
    _interp(inn, o, a, z)


class _Encoder:
    def __init__(self):
        self.inp = [0.0] * (12 + 432)
        self.acb = [0.0] * (324 + 432)
        self.prev_rc = [0.0] * 12
        self.inn = [0.0] * (5 + 108 + 5)
        self.first = True
        self.target = round(_BITRATE * 432 / 22050 / 4) - 18

    def frame(self, samples):
        """One 432-sample frame -> its bytes (byte-aligned)."""
        bw = _Bits()
        if self.first:
            bw.write(1, 1)                                   # halved innovation
            bw.write(32 - _HUFF_THRESHOLD, 4)
            bw.write(_GAIN_SIG // 8 - 1, 4)
            bw.write(round((_GAIN_BASE - 1.04) * 1000), 6)
            self.first = False
        inp = self.inp
        for i in range(432):
            inp[12 + i] = float(samples[i]) if i < len(samples) else 0.0
        rc = _find_rc(inp[12:])
        use_huffman = False
        for i in range(4):
            idx = 1 + _quantize(rc[i], _RC[1:])
            bw.write(idx, 6)
            rc[i] = _RC[idx]
            if i == 0 and idx < _HUFF_THRESHOLD:
                use_huffman = True
        for i in range(4, 12):
            idx = _quantize(rc[i], _RC[16:48])
            bw.write(idx, 5)
            rc[i] = _RC[16 + idx]
        delta = [(rc[i] - self.prev_rc[i]) / 4.0 for i in range(12)]
        cur = self.prev_rc[:]
        acb = self.acb
        for i in range(4):
            for j in range(12):
                cur[j] += delta[j]
            lpc = _rc_to_lpc(cur)
            n = 12 if i < 3 else 396
            for s in range(n):
                p = 12 + 12 * i + s
                pred = 0.0
                for j in range(12):
                    pred += lpc[j] * inp[p - 1 - j]
                acb[324 + 12 * i + s] = inp[p] - pred
        inp[0:12] = inp[432:444]
        self.prev_rc = cur
        inn = self.inn
        for i in range(4):
            e0 = 324 + 108 * i
            best_lag, best_corr = 108, 0.0
            for lag in range(108, 324):
                c = 0.0
                for j in range(108):
                    c += acb[e0 + j] * acb[e0 + j - lag]
                if c > best_corr:
                    best_lag, best_corr = lag, c
            energy = sum(acb[e0 + j - best_lag] ** 2 for j in range(108))
            if energy >= 1 / 32768.0:
                gain = max(0.0, min(1.0, best_corr / energy))
                lag = best_lag
            else:
                lag, gain = 108, 0.0
            bw.write(lag - 108, 8)
            gi = int(gain * 15.0 + 0.5)
            bw.write(gi, 4)
            gain = gi / 15.0
            for j in range(108):
                inn[5 + j] = acb[e0 + j] - gain * acb[e0 + j - lag]
            _encode_innovation(bw, inn, use_huffman, self.target)
            for j in range(108):
                acb[e0 + j] = inn[5 + j] + gain * acb[e0 + j - lag]
        acb[0:324] = acb[432:756]
        return bw.to_bytes()


def _pad4(b):
    return b + b"\0" * (-len(b) % 4)


def _header(total, rate):
    def field(tag, value):
        n = max(1, (value.bit_length() + 7) // 8)
        return bytes((tag, n)) + value.to_bytes(n, "big")
    # same fields and order as the stock clips
    body = (b"GSTR" + bytes.fromhex("01000000c8060165fd800103") + field(0x85, total)
            + field(0xA0, 4) + field(0x84, rate) + b"\xff")
    body = _pad4(body)
    return b"SCHl" + struct.pack("<I", len(body) + 8) + body


def encode_schl(samples, rate=22050):
    """An SCHl MicroTalk clip of `samples` (sequence of ints, mono)."""
    samples = [max(-32768, min(32767, int(v))) for v in samples]
    total = len(samples)
    enc = _Encoder()
    frames = [enc.frame(samples[i:i + 432]) for i in range(0, max(total, 1), 432)]
    blocks = []
    i = 0
    while i < len(frames):
        n = 11 if i == 0 else 10
        chunk = frames[i:i + n]
        count = min(total - i * 432, 432 * len(chunk))
        payload = b"".join(b"\x00" + f for f in chunk)
        body = struct.pack(">I", count) + struct.pack("<I", 0) + (b"\x01" if i == 0 else b"\x00") + payload
        blocks.append(b"SCDl" + struct.pack("<I", len(_pad4(body)) + 8) + _pad4(body))
        i += n
    out = _header(total, rate)
    out += b"SCCl" + struct.pack("<I", 12) + struct.pack(">I", len(blocks))
    out += b"".join(blocks) + b"SCEl" + struct.pack("<I", 8)
    return out
