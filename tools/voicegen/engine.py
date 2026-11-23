"""
voicegen/engine.py — new commentary name clips in the stock commentator's voice
================================================================================
Zero-shot voice cloning with F5-TTS: the model is given a few of the game's
own name clips (audio + the name said, which is the clip's file name) as the
voice/style reference and says the new name the same way. Each take is then
trimmed, levelled like the stock clips (about -11.5 dBFS RMS, limited to full
scale), resampled to 22050 Hz and encoded to the game's MicroTalk format.

Takes are ranked by speaker similarity (Resemblyzer d-vectors) to the average
of all stock name clips; a stock clip itself scores about 0.86.

    eng = Engine()                         # loads lazily, on first use
    takes = eng.make("Dupont", say_as="Doo-pon", count=3)
    eng.save(takes[0], "Dupont", folder)   # -> (id, path of the .dat)
"""
import glob
import json
import os
import re
import sys
import warnings

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path[:0] = [os.path.join(ROOT, "src", "frontend"), os.path.join(ROOT, "src")]
warnings.filterwarnings("ignore")

from shared import commentary                       # noqa: E402  (game paths, clip index)
from shared.ea_mt import decode_schl                # noqa: E402
from shared.ea_mt_encode import encode_schl         # noqa: E402

RATE = 22050
#: stock clips used as the voice reference: close to the voice average,
#: typical length and delivery
REFERENCES = ("Aguero", "Southwell", "Natoba")
TARGET_RMS_DB = -11.5
CACHE = os.path.join(os.path.expanduser("~"), ".cache", "r08-voicegen")


def stock_samples(cid):
    """A stock clip as float samples in [-1, 1]."""
    data = commentary.clip_bytes(cid)
    if data is None:
        return None
    samples, _ = decode_schl(data)
    return np.asarray(samples, dtype=np.float32) / 32768.0


def trim(a, lead=0.02, tail=0.08, rate=RATE):
    win = max(1, int(rate * 0.01))
    env = np.sqrt(np.convolve(a * a, np.ones(win) / win, "same"))
    idx = np.where(env > env.max() * 0.06)[0]
    if not len(idx):
        return a
    return a[max(0, idx[0] - int(lead * rate)):idx[-1] + int(tail * rate)]


def level(a):
    rms = float(np.sqrt(np.mean(a * a))) or 1e-9
    a = a * (10 ** (TARGET_RMS_DB / 20) / rms)
    return np.tanh(a * 1.2) / np.tanh(1.2) * 0.98          # soft limit like the stock peaks


def spoken_text(name):
    """What the model reads: hyphens and underscores as spaces."""
    return re.sub(r"[-_]+", " ", name).strip()


def expected_length(text):
    """Seconds of speech of a stock name clip (fit on the 2601 stock clips)."""
    t = text.lower()
    return 0.014 * len(t) + 0.081 * len(re.findall(r"[aeiouy]+", t)) + 0.269


def file_name(name):
    return re.sub(r"[^\w'\-]+", "_", name, flags=re.UNICODE).strip("_") or "Name"


class Take:
    def __init__(self, samples, seed, score):
        self.samples = samples              # float32, 22050 Hz, as it will sound
        self.seed = seed
        self.score = score
        self._dat = None

    @property
    def dat(self):
        if self._dat is None:
            pcm = np.clip(np.round(self.samples * 32767), -32768, 32767).astype(np.int16)
            self._dat = encode_schl(pcm.tolist())
        return self._dat

    def wav_bytes(self):
        """The take as the game will play it (after the MicroTalk codec)."""
        import io
        import wave
        out, rate = decode_schl(self.dat)
        buf = io.BytesIO()
        with wave.open(buf, "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(rate)
            w.writeframes(np.asarray(out, dtype="<i2").tobytes())
        return buf.getvalue()


class Engine:
    def __init__(self, device=None):
        self.device = device
        self._tts = None
        self._enc = None
        self._centroid = None
        self._ref = None

    # ── loading ─────────────────────────────────────────────────────────
    def load(self, progress=lambda text: None):
        if self._tts is not None:
            return
        import torch
        self.device = self.device or ("cuda" if torch.cuda.is_available() else "cpu")
        progress("Loading the voice model")
        from f5_tts.api import F5TTS
        tts = F5TTS(device=self.device)
        # fp32: the half-precision kernels are several times slower on older
        # cards (GTX 16xx) with recent torch builds
        tts.ema_model.float()
        self._tts = tts
        progress("Loading the voice check")
        from resemblyzer import VoiceEncoder
        self._enc = VoiceEncoder(self.device, verbose=False)
        progress("Reading the stock voice")
        self._ref = self._build_reference()
        self._centroid = self._stock_centroid(progress)

    def _build_reference(self):
        import librosa
        import soundfile as sf
        by_name = {n.lower(): cid for cid, n in commentary.names().items()
                   if cid < commentary.CUSTOM_BASE}
        parts, texts = [], []
        for name in REFERENCES:
            cid = by_name.get(name.lower())
            a = stock_samples(cid) if cid else None
            if a is None:
                continue
            a = trim(a, 0.0, 0.05)
            parts += [librosa.resample(a, orig_sr=RATE, target_sr=24000),
                      np.zeros(int(0.25 * 24000), np.float32)]
            texts.append(name + ".")
        if not parts:
            raise RuntimeError("the game's commentary clips (Audio/dat_eng.big) were not found")
        os.makedirs(CACHE, exist_ok=True)
        path = os.path.join(CACHE, "reference.wav")
        ref = np.concatenate(parts)
        sf.write(path, ref, 24000)
        return path, " ".join(texts) + " ", len(ref) / 24000

    def _stock_centroid(self, progress):
        path = os.path.join(CACHE, "stock_voice.npy")
        if os.path.isfile(path):
            return np.load(path)
        from resemblyzer import preprocess_wav
        ids = sorted(c for c in commentary.names() if c < commentary.CUSTOM_BASE)[::8]
        embs = []
        for i, cid in enumerate(ids):
            a = stock_samples(cid)
            if a is not None:
                embs.append(self._enc.embed_utterance(preprocess_wav(a, RATE)))
            if i % 50 == 0:
                progress(f"Reading the stock voice ({i}/{len(ids)})")
        c = np.mean(embs, axis=0)
        c /= np.linalg.norm(c)
        np.save(path, c)
        return c

    # ── making takes ────────────────────────────────────────────────────
    def score(self, samples):
        from resemblyzer import preprocess_wav
        e = self._enc.embed_utterance(preprocess_wav(samples, RATE))
        return float(e @ self._centroid)

    def make(self, name, say_as="", count=3, first_seed=0, steps=32):
        """`count` takes of `name` (said as `say_as` when given), best first."""
        self.load()
        import librosa
        text = spoken_text(say_as or name)
        ref_path, ref_text, ref_len = self._ref
        takes = []
        for seed in range(first_seed, first_seed + count):
            wav, sr, _ = self._tts.infer(
                ref_file=ref_path, ref_text=ref_text, gen_text=text + ".",
                nfe_step=steps, seed=seed, remove_silence=False,
                fix_duration=ref_len + expected_length(text) * 1.15 + 0.3,
                show_info=lambda *a: None, progress=None)
            a = librosa.resample(np.asarray(wav, np.float32), orig_sr=sr, target_sr=RATE)
            a = level(trim(a)).astype(np.float32)
            takes.append(Take(a, seed, self.score(a)))
        takes.sort(key=lambda t: -t.score)
        return takes


# ── the clips in the mod data ─────────────────────────────────────────────
def next_id(folder):
    return commentary.next_id(folder)


def notes_path(folder):
    return os.path.join(folder, "voicegen.json")


def read_notes(folder):
    try:
        with open(notes_path(folder), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def write_notes(folder, notes):
    tmp = notes_path(folder) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(notes, f, indent=1, ensure_ascii=False, sort_keys=True)
    os.replace(tmp, notes_path(folder))


def save(take, name, folder, say_as=""):
    """Write `take` as the clip for `name` (replacing an earlier one for the
    same name, which keeps its id). -> (id, path)"""
    os.makedirs(folder, exist_ok=True)
    existing = [c for c, (n, _) in commentary.custom_clips(folder).items()
                if n.lower() == name.lower()]
    cid = existing[0] if existing else next_id(folder)
    for old in glob.glob(os.path.join(folder, f"{cid:04d}_*.dat")):
        os.remove(old)
    path = os.path.join(folder, f"{cid:04d}_{file_name(name)}.dat")
    with open(path, "wb") as f:
        f.write(take.dat)
    notes = read_notes(folder)
    notes[str(cid)] = {"name": name, "say_as": say_as, "seed": take.seed,
                       "score": round(take.score, 3)}
    write_notes(folder, notes)
    return cid, path


def delete(cid, folder):
    for old in glob.glob(os.path.join(folder, f"{cid:04d}_*.dat")):
        os.remove(old)
    notes = read_notes(folder)
    if notes.pop(str(cid), None) is not None:
        write_notes(folder, notes)
