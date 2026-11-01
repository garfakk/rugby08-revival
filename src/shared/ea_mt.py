"""
shared/ea_mt.py — Electronic Arts' MicroTalk ("MT", "UTK") speech decoder, and
the SCHl stream around it: the format of the commentary clips in
Audio/dat_eng.big (see shared/commentary.py).

The codec is a port of utkdec.c from vgmstream, itself based on Andrew
D'Addesio's utkencode (UNLICENSE / public domain):
https://github.com/daddesio/utkencode  ·  http://wiki.niotso.org/UTK
A frame is 432 samples; the clips are mono, 22050 Hz.

    decode_schl(data) -> (samples: array('h'), sample_rate)
"""
import array
import struct

_RC = [
    0.0, -0.996776, -0.990327, -0.983879, -0.977431, -0.970982, -0.964534, -0.958085,
    -0.951637, -0.930754, -0.904960, -0.879167, -0.853373, -0.827579, -0.801786, -0.775992,
    -0.750198, -0.724405, -0.698611, -0.670635, -0.619048, -0.567460, -0.515873, -0.464286,
    -0.412698, -0.361111, -0.309524, -0.257937, -0.206349, -0.154762, -0.103175, -0.051587,
    0.0, 0.051587, 0.103175, 0.154762, 0.206349, 0.257937, 0.309524, 0.361111,
    0.412698, 0.464286, 0.515873, 0.567460, 0.619048, 0.670635, 0.698611, 0.724405,
    0.750198, 0.775992, 0.801786, 0.827579, 0.853373, 0.879167, 0.904960, 0.930754,
    0.951637, 0.958085, 0.964534, 0.970982, 0.977431, 0.983879, 0.990327, 0.996776,
]

_NORMAL_ROW = [4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 17,
               4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 21,
               4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 18,
               4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 25,
               4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 17,
               4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 22,
               4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 18,
               4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 0]
_NORMAL = _NORMAL_ROW + [4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 17,
                         4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 21,
                         4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 18,
                         4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 26,
                         4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 17,
                         4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 22,
                         4, 6, 5, 9, 4, 6, 5, 13, 4, 6, 5, 10, 4, 6, 5, 18,
                         4, 6, 5, 9, 4, 6, 5, 14, 4, 6, 5, 10, 4, 6, 5, 2]
# the large-pulse model: rows of 16, the same 8 twice
_LARGE = []
_ROWS = [(19, 16, 23), (20, 16, 27), (19, 16, 24), (20, 16, 1),
         (19, 16, 23), (20, 16, 28), (19, 16, 24), (20, 16, 3)]
for _a, _b, _c in _ROWS * 2:
    _LARGE += [4, 11, 7, 15, 4, 12, 8, _a, 4, 11, 7, _b, 4, 12, 8, _c]
_CODEBOOKS = (_NORMAL, _LARGE)

# next model, code size, pulse value
_COMMANDS = [(1, 8, 0.0), (1, 7, 0.0), (0, 8, 0.0), (0, 7, 0.0), (0, 2, 0.0), (0, 2, -1.0),
             (0, 2, 1.0), (0, 3, -1.0), (0, 3, 1.0), (1, 4, -2.0), (1, 4, 2.0), (1, 3, -2.0),
             (1, 3, 2.0), (1, 5, -3.0), (1, 5, 3.0), (1, 4, -3.0), (1, 4, 3.0), (1, 6, -4.0),
             (1, 6, 4.0), (1, 5, -4.0), (1, 5, 4.0), (1, 7, -5.0), (1, 7, 5.0), (1, 6, -5.0),
             (1, 6, 5.0), (1, 8, -6.0), (1, 8, 6.0), (1, 7, -6.0), (1, 7, 6.0)]
_MASK = [0x01, 0x03, 0x07, 0x0F, 0x1F, 0x3F, 0x7F, 0xFF]


class _Decoder:
    def __init__(self, pcm_blocks):
        self.pcm_blocks = pcm_blocks
        self.data = b""
        self.pos = 0
        self.bits_value = 0
        self.bits_count = 0
        self.parsed = False
        self.reduced = False
        self.threshold = 0
        self.fixed_gains = [0.0] * 64
        self.rc = [0.0] * 12
        self.history = [0.0] * 12
        self.sub = [0.0] * (324 + 432)          # adapt_cb (324) then samples (432)

    # bit reader (LSB first)
    def _byte(self):
        if self.pos < len(self.data):
            b = self.data[self.pos]
            self.pos += 1
            return b
        return 0

    def _init_bits(self):
        if not self.bits_count:
            self.bits_value = self._byte()
            self.bits_count = 8

    def _peek(self, n):
        return self.bits_value & _MASK[n - 1]

    def _read(self, n):
        ret = self.bits_value & _MASK[n - 1]
        self.bits_value >>= n
        self.bits_count -= n
        if self.bits_count < 8:
            self.bits_value |= self._byte() << self.bits_count
            self.bits_count += 8
        return ret

    def _header(self):
        self.reduced = self._read(1) == 1
        thre = self._read(4)
        gain = self._read(4)
        mult = self._read(6)
        self.threshold = 32 - thre
        self.fixed_gains[0] = 8.0 * (1 + gain)
        m = 1.04 + mult * 0.001
        for i in range(1, 64):
            self.fixed_gains[i] = self.fixed_gains[i - 1] * m

    def _excitation(self, multipulse, out, start, stride):
        i = 0
        if multipulse:
            model = 0
            while i < 108:
                cmd = _CODEBOOKS[model][self._peek(8)]
                model, size, pulse = _COMMANDS[cmd]
                self._read(size)
                if cmd > 3:
                    out[start + i] = pulse
                    i += stride
                elif cmd > 1:
                    count = 7 + self._read(6)
                    if i + count * stride > 108:
                        count = (108 - i) // stride
                    while count > 0:
                        out[start + i] = 0.0
                        i += stride
                        count -= 1
                else:
                    x = 7
                    while self._read(1):
                        x += 1
                    if not self._read(1):
                        x = -x
                    out[start + i] = float(x)
                    i += stride
        else:
            while i < 108:
                code = self._peek(2)
                if code in (0, 2):
                    val, bits = 0.0, 1
                elif code == 1:
                    val, bits = -2.0, 2
                else:
                    val, bits = 2.0, 2
                self._read(bits)
                out[start + i] = val
                i += stride

    @staticmethod
    def _rc_to_lpc(rc):
        lpc = [0.0] * 12
        tmp1 = [0.0] * 12
        tmp2 = [0.0] * 12
        for i in range(10, -1, -1):
            tmp2[i + 1] = rc[i]
        tmp2[0] = 1.0
        for i in range(12):
            x = -(rc[11] * tmp2[11])
            for j in range(10, -1, -1):
                x -= rc[j] * tmp2[j]
                tmp2[j + 1] = x * rc[j] + tmp2[j]
            tmp2[0] = x
            tmp1[i] = x
            for j in range(i):
                x -= tmp1[i - 1 - j] * lpc[j]
            lpc[i] = x
        return lpc

    def _filter(self, offset, blocks):
        lpc = self._rc_to_lpc(self.rc)
        h = self.history
        s = self.sub
        p = 324 + offset
        for _ in range(blocks):
            for j in range(12):
                x = s[p]
                for k in range(j):
                    x += lpc[k] * h[k - j + 12]
                for k in range(j, 12):
                    x += lpc[k] * h[k - j]
                h[11 - j] = x
                s[p] = x
                p += 1

    def _frame(self):
        self._init_bits()
        if not self.parsed:
            self._header()
            self.parsed = True
        multipulse = False
        rc_delta = [0.0] * 12
        for i in range(12):
            if i == 0:
                idx = self._read(6)
                multipulse = idx < self.threshold
            elif i < 4:
                idx = self._read(6)
            else:
                idx = 16 + self._read(5)
            rc_delta[i] = (_RC[idx] - self.rc[i]) * 0.25
        exc = [0.0] * (5 + 108 + 5)
        s = self.sub
        for i in range(4):
            lag = self._read(8)
            pitch_gain = self._read(4) / 15.0
            fixed = self.fixed_gains[self._read(6)]
            if not self.reduced:
                self._excitation(multipulse, exc, 5, 1)
            else:
                align = self._read(1)
                zero = self._read(1)
                self._excitation(multipulse, exc, 5 + align, 2)
                if zero:
                    for j in range(54):
                        exc[5 + (1 - align) + 2 * j] = 0.0
                else:
                    for j in range(5):
                        exc[j] = 0.0
                        exc[5 + 108 + j] = 0.0
                    base = 5 + (1 - align)
                    for j in range(0, 108, 2):
                        t1 = (exc[base + j - 5] + exc[base + j + 5]) * 0.01803268
                        t2 = (exc[base + j - 3] + exc[base + j + 3]) * 0.11459156
                        t3 = (exc[base + j - 1] + exc[base + j + 1]) * 0.59738597
                        exc[base + j] = t1 - t2 + t3
                    fixed *= 0.5
            for j in range(108):
                idx = 108 * i + 216 - lag + j
                if idx < 0:
                    idx = 0
                s[324 + 108 * i + j] = fixed * exc[5 + j] + pitch_gain * s[idx]
        s[0:324] = s[432:756]
        for i in range(4):
            for j in range(12):
                self.rc[j] += rc_delta[j]
            self._filter(12 * i, 1 if i < 3 else 33)

    def _frame_pcm(self):
        present = self._byte() == 0xEE
        self._frame()
        self.pos -= 1                       # the last byte read belongs to the next frame
        self.bits_count = 0
        if present:
            offset = struct.unpack(">h", bytes((self._byte(), self._byte())))[0]
            count = struct.unpack(">h", bytes((self._byte(), self._byte())))[0]
            if offset < 0 or offset > 432 or count < 0 or count > 432 - offset:
                raise ValueError("bad PCM patch in a MicroTalk frame")
            for i in range(count):
                self.sub[324 + offset + i] = float(struct.unpack(">h", bytes((self._byte(), self._byte())))[0])

    def decode(self, data, samples):
        """`samples` samples from the frames in `data` (a block's payload)."""
        self.data, self.pos, self.bits_count = data, 0, 0
        out = array.array("h")
        while len(out) < samples:
            before = self.pos
            if self.pcm_blocks:
                self._frame_pcm()
            else:
                self._frame()
            for v in self.sub[324:756]:
                out.append(max(-32768, min(32767, int(round(v)))))
            if self.pos == before and self.pos >= len(data):
                break
        return out[:samples]


def parse_header(data):
    """(codec, sample rate, total samples, offset of the first block) of an
    SCHl stream."""
    if data[:4] != b"SCHl":
        raise ValueError("not an EA SCHl stream")
    size = struct.unpack_from("<I", data, 4)[0]
    body = data[8:size]
    pos = 4 if body[:4] == b"GSTR" else 0
    pos += 1                                   # platform byte
    codec, rate, samples = None, 22050, 0
    while pos < len(body):
        b = body[pos]
        pos += 1
        if b == 0xFF:
            break
        if b == 0xFD:                          # start of the audio sub-header
            continue
        n = body[pos]
        pos += 1
        value = int.from_bytes(body[pos:pos + n], "big")
        pos += n
        if b == 0x85:
            samples = value
        elif b == 0x84:
            rate = value
        elif b == 0xA0:
            codec = value
    return codec, rate, samples, size


def decode_schl(data):
    """(array('h') of samples, sample rate) of an EA SCHl MicroTalk clip."""
    codec, rate, total, pos = parse_header(data)
    if codec not in (4, None):
        raise ValueError(f"unsupported EA codec {codec}")
    dec = _Decoder(pcm_blocks=True)
    out = array.array("h")
    while pos + 8 <= len(data):
        tag = data[pos:pos + 4]
        size = struct.unpack_from("<I", data, pos + 4)[0]
        if size < 8:
            break
        if tag == b"SCDl":
            # id, size, samples, channel offset (mono: 0), a flag byte (0x01
            # on the first block), then the frames
            n = struct.unpack_from(">I", data, pos + 8)[0]
            start = pos + 16 + struct.unpack_from("<I", data, pos + 12)[0] + 1
            out.extend(dec.decode(data[start:pos + size], n))
        elif tag == b"SCEl":
            break
        pos += size
    return out[:total] if total else out, rate
