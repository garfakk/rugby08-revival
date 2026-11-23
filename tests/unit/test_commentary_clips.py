"""New commentary name clips: the MicroTalk encoder (decoded back by
shared/ea_mt), the speech archives rebuilt with the new clips, the deploy to
the game folder, and which clip a player gets in a match."""
import math
import os
import random

import pytest

from backend import commentary_deploy
from shared import commentary, speech_bank
from shared.config import config
from shared.ea_mt import decode_schl
from shared.ea_mt_encode import encode_schl


def _voice(seconds=0.5, rate=22050):
    """A buzzy vowel-like signal: harmonics of a gliding pitch plus noise."""
    rnd = random.Random(1)
    out, phase = [], 0.0
    for i in range(int(seconds * rate)):
        f0 = 120 + 30 * i / (seconds * rate)
        phase += 2 * math.pi * f0 / rate
        env = math.sin(math.pi * i / (seconds * rate))
        v = sum(math.sin(k * phase) / k for k in range(1, 12))
        out.append(int(env * (6000 * v + 300 * rnd.uniform(-1, 1))))
    return out


@pytest.fixture(scope="module")
def clip():
    samples = _voice()
    return samples, encode_schl(samples)


def test_encoded_clip_decodes_back(clip):
    samples, data = clip
    assert data[:4] == b"SCHl"
    out, rate = decode_schl(data)
    assert rate == 22050 and len(out) == len(samples)
    err = sum((a - b) ** 2 for a, b in zip(samples, out))
    power = sum(a * a for a in samples)
    assert 10 * math.log10(power / err) > 10          # a lossy codec, but close


def test_encoded_clip_bitrate_is_stock_like(clip):
    samples, data = clip
    kbps = len(data) * 8 / (len(samples) / 22050) / 1000
    assert 25 < kbps < 50                              # stock clips: ~40


def _stock(tmp_path):
    a = encode_schl(_voice(0.3))
    dat = [("10N_NEED_WIN.dat", b"\x01" * 300), ("0060_Bailey.dat", speech_bank.padded_dat(a))]
    hdr = [("10N_NEED_WIN.hdr", b"\x02" * 16), ("0060_Bailey.hdr", speech_bank.name_header(60, dat[1][1]))]
    audio = tmp_path / "Audio"
    audio.mkdir()
    speech_bank.write_big(str(audio / "dat_eng.big"), dat, marker=False)
    speech_bank.write_big(str(audio / "hdr_eng.big"), hdr)
    return audio, dat, hdr


def test_big_round_trip(tmp_path):
    audio, dat, hdr = _stock(tmp_path)
    assert speech_bank.read_big(str(audio / "dat_eng.big")) == dat
    assert speech_bank.read_big(str(audio / "hdr_eng.big")) == hdr


def test_name_header_layout(clip):
    dat = speech_bank.padded_dat(clip[1])
    h = speech_bank.name_header(3001, dat)
    assert len(h) == 24 and h[:2] == b"\xb4\x04"
    assert int.from_bytes(h[2:4], "little") == 3001
    assert int.from_bytes(h[8:10], "little") == len(dat) // 256 - 1
    assert int.from_bytes(h[16:18], "little") == (speech_bank.schl_used(dat) + 255) // 256


def test_add_clips_refuses_a_taken_id(tmp_path, clip):
    _, dat, hdr = _stock(tmp_path)
    with pytest.raises(ValueError):
        speech_bank.add_clips(dat, hdr, [(60, "Bailey", clip[1])])


def _custom(tmp_path, clip, names):
    folder = tmp_path / "commentary"
    folder.mkdir(exist_ok=True)
    for cid, name in names:
        (folder / f"{cid:04d}_{name}.dat").write_bytes(clip[1])
    return commentary.custom_clips(str(folder))


def test_deploy_builds_then_keeps_then_restores(tmp_path, clip):
    audio, dat, hdr = _stock(tmp_path)
    stock_dat = (audio / "dat_eng.big").read_bytes()
    clips = _custom(tmp_path, clip, [(3000, "Dupont"), (3001, "Ntamack")])

    assert commentary_deploy.deploy(str(tmp_path), clips) == "built"
    live = speech_bank.read_big(str(audio / "dat_eng.big"))
    assert [n for n, _ in live][-2:] == ["3000_Dupont.dat", "3001_Ntamack.dat"]
    heads = speech_bank.read_big(str(audio / "hdr_eng.big"))
    assert [n for n, _ in heads][-1] == "3001_Ntamack.hdr"
    assert (audio / "dat_eng.big.stock").read_bytes() == stock_dat

    assert commentary_deploy.deploy(str(tmp_path), clips) == "unchanged"
    assert commentary_deploy.deploy(str(tmp_path), {}) == "restored"
    assert (audio / "dat_eng.big").read_bytes() == stock_dat


def test_match_clip_prefers_an_exact_clip(tmp_path, clip, monkeypatch):
    clips = _custom(tmp_path, clip, [(3000, "Dupont"), (3001, "Bailey")])
    monkeypatch.setattr(commentary, "custom_clips", lambda folder=None: clips)
    monkeypatch.setattr(commentary, "_load", lambda: {
        60: ("Bailey", 0, 0), 451: ("Dupuy", 0, 0), 1389: ("Smith", 0, 0)})
    assert commentary.match_clip(451, "Dupont") == 3000      # sound-alike replaced
    assert commentary.match_clip(0, "dupont") == 3000         # none replaced
    assert commentary.match_clip(60, "Bailey") == 60          # stock exact kept
    assert commentary.match_clip(0, "Bailey") == 60           # stock exact before a new one
    assert commentary.match_clip(0, "Smith") == 1389          # stock exact for none
    assert commentary.match_clip(451, "Jones") == 451         # no exact clip: kept


def _wav(path, seconds=0.5, rate=44100, channels=2, lead=0.3):
    import wave
    import numpy as np
    voice = np.asarray(_voice(seconds, rate), dtype=np.float32)
    quiet = np.zeros(int(lead * rate), np.float32)
    mono = np.concatenate([quiet, voice, quiet]) * 0.3
    data = np.repeat(mono[:, None], channels, axis=1).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(channels)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(data.tobytes())
    return path


def test_recording_becomes_a_stock_like_clip(tmp_path):
    from shared import commentary_audio
    src = _wav(tmp_path / "Dupont.wav")
    data = commentary_audio.to_clip(str(src), str(tmp_path / "cache"))
    out, rate = decode_schl(data)
    assert rate == 22050
    assert 0.4 < len(out) / rate < 0.7                 # the silence around it cut
    assert len(os.listdir(tmp_path / "cache")) == 1    # cached
    assert commentary_audio.to_clip(str(src), str(tmp_path / "cache")) == data


def test_unusable_recording_is_refused(tmp_path):
    from shared import commentary_audio
    bad = tmp_path / "x.wav"
    bad.write_bytes(b"not audio")
    with pytest.raises(ValueError):
        commentary_audio.to_clip(str(bad), str(tmp_path / "cache"))


def test_recordings_in_the_folder_get_ids(tmp_path, clip):
    folder = tmp_path / "commentary"
    folder.mkdir()
    (folder / "3000_Dupont.dat").write_bytes(clip[1])
    _wav(folder / "3001_Itoje.wav")
    _wav(folder / "Ntamack.wav")
    _wav(folder / "Du_Toit.wav")
    clips = commentary.custom_clips(str(folder))
    assert clips[3000][0] == "Dupont" and clips[3001][0] == "Itoje"
    auto = {n: c for c, (n, _) in clips.items() if c >= commentary.AUTO_BASE}
    assert set(auto) == {"Ntamack", "Du Toit"}
    assert all(commentary.AUTO_BASE <= c < commentary.AUTO_END for c in auto.values())
    (folder / "Zzz.wav").write_bytes(b"")                      # another name: same ids
    again = commentary.custom_clips(str(folder))
    assert {n: c for c, (n, _) in again.items() if n in auto} == auto


def test_deploy_converts_recordings(tmp_path, clip, monkeypatch):
    from shared import commentary_audio
    monkeypatch.setattr(commentary_audio, "_cache_dir", lambda: str(tmp_path / "cache"))
    audio, _, _ = _stock(tmp_path)
    folder = tmp_path / "commentary"
    folder.mkdir()
    _wav(folder / "Ntamack.wav")
    (folder / "Broken.wav").write_bytes(b"nope")
    clips = commentary.custom_clips(str(folder))
    assert commentary_deploy.deploy(str(tmp_path), clips) == "built"
    live = speech_bank.read_big(str(audio / "dat_eng.big"))
    added = [(n, d) for n, d in live if n.endswith("_Ntamack.dat")]
    assert len(added) == 1 and added[0][1][:4] == b"SCHl"
    assert not any("Broken" in n for n, _ in live)             # left out, not fatal


def test_removed_new_clip_falls_back(monkeypatch):
    monkeypatch.setattr(commentary, "custom_clips", lambda folder=None: {})
    monkeypatch.setattr(commentary, "_load", lambda: {60: ("Bailey", 0, 0)})
    assert commentary.match_clip(3005, "Nobody") == 0
    assert commentary.match_clip(3005, "Bailey") == 60


def test_new_clips_get_low_ids_in_the_game(tmp_path, clip, monkeypatch):
    """The game is given 3000, 3001... in id order, whatever the file ids."""
    audio, _, _ = _stock(tmp_path)
    clips = _custom(tmp_path, clip, [(3002, "Dupont"), (7869, "Ntamack"), (5010, "Itoje")])
    monkeypatch.setattr(commentary, "custom_clips", lambda folder=None: clips)
    assert commentary_deploy.deploy(str(tmp_path), clips) == "built"
    live = [n for n, _ in speech_bank.read_big(str(audio / "dat_eng.big"))]
    assert live[-3:] == ["3000_Dupont.dat", "3001_Itoje.dat", "3002_Ntamack.dat"]
    assert [commentary.in_game(c) for c in (3002, 5010, 7869, 60, 4000)] == [3000, 3001, 3002, 60, 0]


def test_deploy_rebuilds_when_game_ids_move(tmp_path, clip):
    """Adding a clip with a lower id shifts the game ids of the others:
    the archives are rebuilt, never left with the old numbers."""
    audio, _, _ = _stock(tmp_path)
    clips = _custom(tmp_path, clip, [(7869, "Ntamack")])
    assert commentary_deploy.deploy(str(tmp_path), clips) == "built"
    clips = _custom(tmp_path, clip, [(3000, "Dupont")])
    assert set(clips) == {3000, 7869}
    assert commentary_deploy.deploy(str(tmp_path), clips) == "built"
    live = [n for n, _ in speech_bank.read_big(str(audio / "dat_eng.big"))]
    assert live[-2:] == ["3000_Dupont.dat", "3001_Ntamack.dat"]
