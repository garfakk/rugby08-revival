"""shared/game_profile.py: the binary user_profile.pro (header + CRCs the game
checks) and the user's settings written into it at every launch."""
import os
import struct

import pytest

from shared import game_profile as GP
from shared.config import config

TEMPLATE = os.path.join(config.templates_directory, GP.TEMPLATE_NAME)


@pytest.fixture
def template_bytes():
    with open(TEMPLATE, "rb") as f:
        return f.read()


@pytest.fixture
def profile(tmp_path, monkeypatch):
    monkeypatch.setattr(GP, "SETTINGS_FILE", str(tmp_path / "game_profile.ini"))
    return GP.GameProfile()


def test_template_roundtrips_byte_for_byte(template_bytes):
    payload = GP.split_profile(template_bytes)
    assert payload is not None and len(payload) == GP.PROFILE_SIZE
    assert GP.build_profile(payload) == template_bytes


@pytest.mark.parametrize("corrupt", [
    lambda b: b[:-1],                                    # wrong size
    lambda b: b"XXXX" + b[4:],                           # bad magic
    lambda b: b[:0x30] + bytes([b[0x30] ^ 1]) + b[0x31:],   # payload CRC mismatch
    lambda b: b[:0x08] + b"\x01" + b[0x09:],             # header CRC mismatch
])
def test_split_rejects_invalid(template_bytes, corrupt):
    assert GP.split_profile(corrupt(template_bytes)) is None


def test_crc_known_values():
    assert GP._crc(b"") == 0
    payload = GP.split_profile(open(TEMPLATE, "rb").read())
    header = GP.build_profile(payload)[:0x18]
    assert struct.unpack_from("<I", GP.build_profile(payload), 0x18)[0] == GP._crc(header)


def test_bitfield_read_write():
    s = GP.Setting("x", "X", 0, "range", size=2, shift=4, bits=6, maximum=63)
    buf = bytearray(b"\xff\xff")
    GP._write(buf, s, 5)
    assert GP._read(buf, s) == 5
    assert buf == bytearray(((0xFFFF & ~(0x3F << 4)) | (5 << 4)).to_bytes(2, "little"))
    signed = GP.Setting("y", "Y", 0, "range", bits=8, signed=True, minimum=-128)
    GP._write(buf, signed, -3)
    assert GP._read(buf, signed) == -3


def test_clamp():
    rng = GP.Setting("r", "R", 0, "range", minimum=0, maximum=10)
    assert GP._clamp(rng, 99) == 10 and GP._clamp(rng, -5) == 0
    assert GP._clamp(GP.Setting("b", "B", 0, "bool"), 7) == 1
    assert GP._clamp(GP.DIFFICULTY, 9) == 0


@pytest.mark.parametrize("w,h,recommended,offered", [
    (1920, 1080, (1920, 1080), True),
    (3440, 1440, (3440, 1440), True),        # native size added
    (640, 480, (800, 600), False),           # unsafe: closest instead
])
def test_resolution_choices(w, h, recommended, offered):
    sizes, rec = GP.resolution_choices(w, h)
    assert rec == recommended
    assert ((w, h) in sizes) is offered
    assert sizes == sorted(sizes)


def test_vol_crowd_set_deploy_read(profile, game_dir):
    """Crowd volume (a75d60ca 'crowd sound muted in-game') reaches the file."""
    profile.set("vol_crowd", 70)
    assert profile.deploy(game_dir, difficulty=1)
    with open(os.path.join(game_dir, GP.GAME_FILE_NAME), "rb") as f:
        payload = GP.split_profile(f.read())
    assert payload is not None                           # CRCs valid
    assert GP._read(payload, GP.SETTINGS["vol_crowd"]) == 70
    assert GP._read(payload, GP.DIFFICULTY) == 1


def test_deploy_applies_defaults_and_resolution(profile, game_dir):
    profile.set_resolution(1280, 720)
    profile.deploy(game_dir)
    payload = GP.split_profile(open(os.path.join(game_dir, GP.GAME_FILE_NAME), "rb").read())
    assert struct.unpack_from("<HH", payload, GP._OFF_RES_W) == (1280, 720)
    for s in GP.SETTINGS.values():
        if s.default is not None:
            assert GP._read(payload, s) == GP._clamp(s, s.default), s.key


def test_unsafe_resolution_refused(profile):
    profile.set_resolution(640, 480)
    assert not profile.has_resolution()


def test_settings_persist(profile, tmp_path, monkeypatch):
    profile.set("vol_crowd", 35)
    profile.set_resolution(1600, 900)
    profile.save()
    again = GP.GameProfile()
    assert again.get("vol_crowd") == 35 and again.get_resolution() == (1600, 900)
    (tmp_path / "game_profile.ini").write_text("[profile]\nresolution = 640x480\nvol_crowd = abc\n")
    bad = GP.GameProfile()
    assert not bad.has_resolution()                      # unsafe one ignored
    assert bad.get("vol_crowd") == GP.GameProfile().get("vol_crowd")


def test_import_ingame_keeps_changed_settings(profile, game_dir):
    profile.deploy(game_dir)
    payload = bytearray(profile._deployed)
    GP._write(payload, GP.SETTINGS["vol_crowd"], 15)
    name = os.path.splitext(GP.GAME_FILE_NAME)[0].encode()
    payload[GP._OFF_NAME:GP._OFF_NAME + GP._NAME_LEN] = name.ljust(GP._NAME_LEN, b"\0")
    assert profile.import_ingame(bytes(payload)) == ["vol_crowd"]
    assert profile.get("vol_crowd") == 15
    assert profile.revision == 1


def test_import_ingame_ignores_foreign_profile(profile, game_dir):
    profile.deploy(game_dir)
    payload = bytearray(profile._deployed)
    payload[GP._OFF_NAME:GP._OFF_NAME + 5] = b"other"
    assert profile.import_ingame(bytes(payload)) == []
    assert profile.import_ingame(b"short") == []
