"""
shared/commentary_audio.py — a user's recording as a commentary name clip
==========================================================================
Turns a WAV file (any rate, mono or stereo, 8/16/24/32-bit PCM or float)
into the game's clip format (shared/ea_mt_encode.py): mixed to mono,
resampled to 22050 Hz, the silence around the name cut, levelled like the
stock clips (about -11.5 dBFS RMS, soft-limited) and encoded to MicroTalk.

Encoding takes about half a second per clip, so the result is cached under
user_data/cache/commentary, keyed by the WAV's content.

    to_clip(path) -> SCHl bytes          (ValueError: not a usable WAV)
"""
import hashlib
import os
import struct
import wave

import numpy as np

from shared.ea_mt_encode import encode_schl
from shared.log import get_logger

log = get_logger(__name__)

RATE = 22050
TARGET_RMS_DB = -11.5
MAX_SECONDS = 4.0           # a name; longer recordings are cut
CACHE_VERSION = b"1"


def _read_wav(path):
    """(float32 mono samples in [-1, 1], rate)"""
    try:
        with wave.open(path, "rb") as w:
            channels, width, rate = w.getnchannels(), w.getsampwidth(), w.getframerate()
            frames = w.readframes(w.getnframes())
        fmt = "pcm"
    except wave.Error:
        channels, width, rate, frames, fmt = _read_float_wav(path)
    except (EOFError, OSError) as e:
        raise ValueError(f"not a WAV file ({e})") from e
    if not frames or not rate or not channels:
        raise ValueError("the WAV file is empty")
    if fmt == "float":
        a = np.frombuffer(frames, dtype="<f4" if width == 4 else "<f8").astype(np.float32)
    elif width == 1:
        a = (np.frombuffer(frames, np.uint8).astype(np.float32) - 128) / 128
    elif width == 2:
        a = np.frombuffer(frames, "<i2").astype(np.float32) / 32768
    elif width == 3:
        b = np.frombuffer(frames, np.uint8).reshape(-1, 3).astype(np.int32)
        v = b[:, 0] | (b[:, 1] << 8) | (b[:, 2] << 16)
        a = (np.where(v >= 1 << 23, v - (1 << 24), v)).astype(np.float32) / (1 << 23)
    elif width == 4:
        a = np.frombuffer(frames, "<i4").astype(np.float32) / 2 ** 31
    else:
        raise ValueError(f"{width * 8}-bit WAV not supported")
    n = len(a) // channels
    a = a[:n * channels].reshape(n, channels).mean(axis=1)
    return a, rate


def _read_float_wav(path):
    """The chunks of a WAVE_FORMAT_IEEE_FLOAT (3) or EXTENSIBLE float file,
    which the wave module refuses."""
    try:
        with open(path, "rb") as f:
            data = f.read()
    except OSError as e:
        raise ValueError(f"cannot read the file ({e})") from e
    if data[:4] != b"RIFF" or data[8:12] != b"WAVE":
        raise ValueError("not a WAV file")
    pos, fmt, frames = 12, None, None
    while pos + 8 <= len(data):
        cid, size = data[pos:pos + 4], struct.unpack_from("<I", data, pos + 4)[0]
        body = data[pos + 8:pos + 8 + size]
        if cid == b"fmt " and len(body) >= 16:
            fmt = struct.unpack_from("<HHIIHH", body)
            if fmt[0] == 0xFFFE and len(body) >= 26:    # extensible: sub format
                fmt = (struct.unpack_from("<H", body, 24)[0],) + fmt[1:]
        elif cid == b"data":
            frames = body
        pos += 8 + size + (size & 1)
    if fmt is None or frames is None:
        raise ValueError("not a WAV file")
    tag, channels, rate, _, _, bits = fmt
    if tag != 3 or bits not in (32, 64):
        raise ValueError("WAV encoding not supported (use 16-bit PCM)")
    return channels, bits // 8, rate, frames, "float"


def _resample(a, rate):
    if rate == RATE:
        return a
    if rate > RATE:                             # low-pass first: no aliasing
        cutoff = 0.45 * RATE / rate
        n = np.arange(-64, 65)
        h = 2 * cutoff * np.sinc(2 * cutoff * n) * np.hamming(len(n))
        a = np.convolve(a, h / h.sum(), "same")
    t = np.arange(int(len(a) * RATE / rate)) * (rate / RATE)
    return np.interp(t, np.arange(len(a)), a).astype(np.float32)


def _trim(a, lead=0.02, tail=0.08):
    win = max(1, int(RATE * 0.01))
    env = np.sqrt(np.convolve(a * a, np.ones(win) / win, "same"))
    idx = np.where(env > env.max() * 0.06)[0]
    if not len(idx):
        return a
    return a[max(0, idx[0] - int(lead * RATE)):idx[-1] + int(tail * RATE)]


def _level(a):
    rms = float(np.sqrt(np.mean(a * a)))
    if rms < 1e-5:
        raise ValueError("the recording is silent")
    a = a * (10 ** (TARGET_RMS_DB / 20) / rms)
    return np.tanh(a * 1.2) / np.tanh(1.2) * 0.98


def samples(path):
    """The recording as it goes in the clip: 22050 Hz int16 samples."""
    a, rate = _read_wav(path)
    a = _trim(_resample(a.astype(np.float32), rate))[:int(MAX_SECONDS * RATE)]
    if len(a) < RATE // 20:
        raise ValueError("the recording is too short")
    a = _level(a)
    return np.clip(np.round(a * 32767), -32768, 32767).astype(np.int16)


def _cache_dir():
    from shared.app_paths import user_data_directory
    return os.path.join(user_data_directory(), "cache", "commentary")


def to_clip(path, cache_dir=None):
    """The game clip (SCHl bytes) for the WAV at `path`."""
    try:
        with open(path, "rb") as f:
            raw = f.read()
    except OSError as e:
        raise ValueError(f"cannot read the file ({e})") from e
    key = hashlib.sha1(CACHE_VERSION + raw).hexdigest()
    folder = cache_dir or _cache_dir()
    cached = os.path.join(folder, key + ".dat")
    try:
        with open(cached, "rb") as f:
            return f.read()
    except OSError:
        pass
    data = encode_schl(samples(path).tolist())
    try:
        os.makedirs(folder, exist_ok=True)
        tmp = cached + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, cached)
    except OSError as e:
        log.warning("commentary clip cache not written: %s", e)
    return data
