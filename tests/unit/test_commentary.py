"""Commentary name clips: the id -> name index read from Audio/dat_eng.big,
and the MicroTalk decode of a clip (real game files only)."""
import io
import os
import struct
import wave

import pytest

from shared import commentary
from shared.config import config


def _bigf(entries):
    """A BIGF archive holding `entries` [(name, payload)]."""
    table = b"".join(struct.pack(">II", 0, 0) + n.encode() + b"\0" for n, _ in entries)
    header = 16 + len(table)
    out, body, pos = [], b"", header
    for n, data in entries:
        out.append(struct.pack(">II", pos, len(data)) + n.encode() + b"\0")
        body += data
        pos += len(data)
    table = b"".join(out)
    return b"BIGF" + struct.pack("<I", header + len(body)) + struct.pack(">II", len(entries), header) + table + body


@pytest.fixture
def fake_game(tmp_path, monkeypatch):
    os.makedirs(tmp_path / "Audio")
    (tmp_path / "Audio" / "dat_eng.big").write_bytes(_bigf([
        ("10N_NEED_WIN.dat", b"x"), ("0060_Bailey.dat", b"y"), ("2193_O_Mahony.dat", b"z")]))
    monkeypatch.setattr(config, "R08_directory", str(tmp_path), raising=False)
    monkeypatch.setattr(commentary, "_index", None)
    return tmp_path


def test_names_come_from_numbered_clips(fake_game):
    assert commentary.names() == {60: "Bailey", 2193: "O Mahony"}


def test_no_archive_means_no_names(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "R08_directory", str(tmp_path), raising=False)
    monkeypatch.setattr(commentary, "_index", None)
    assert commentary.names() == {}
    assert commentary.wav_bytes(60) is None


def test_bad_clip_does_not_raise(fake_game):
    assert commentary.wav_bytes(60) is None
    assert commentary.wav_bytes("abc") is None


REAL = os.path.join(getattr(config, "R08_directory", "") or "", "Audio", "dat_eng.big")


@pytest.mark.skipif(not os.path.isfile(REAL), reason="needs the game's Audio/dat_eng.big")
def test_real_clip_decodes(monkeypatch):
    monkeypatch.setattr(commentary, "_index", None)
    assert commentary.names()[60] == "Bailey"
    with wave.open(io.BytesIO(commentary.wav_bytes(60))) as w:
        assert w.getframerate() == 22050
        frames = w.readframes(w.getnframes())
    assert 0.3 < len(frames) / 2 / 22050 < 2.0
    assert max(abs(v) for (v,) in struct.iter_unpack("<h", frames)) > 2000
