"""Rugby08.exe gets 2 GB of address space and loading a match maps the 127 MB
data/motion/script.big in one piece: the only gap that size is a 128 MB one,
so a graphics-driver buffer or a heavy head landing in it made the map fail
("BigFile: Opening data/motion/script.big", then the engine's fatal-error loop,
black screen). Seen on Linux/Wine at random in about 1 match in 25 with the
same files. The fix sets the exe's large-address-aware flag; these tests cover
the patcher (the real effect, 0 hangs in a long soak, only the game can show)."""
import os
import stat
import struct

import pytest

from backend import mod_utils
from backend.mod_utils import (IMAGE_FILE_LARGE_ADDRESS_AWARE, LAA_BACKUP_SUFFIX,
                               ensure_large_address_aware, large_address_aware)

PE_OFFSET = 0x80
CHARACTERISTICS_AT = PE_OFFSET + 4 + 18          # COFF Characteristics, after "PE\0\0" + 18 bytes
STOCK_CHARACTERISTICS = 0x010F                    # Rugby08.exe: 32-bit, not large address aware


def make_pe(path, characteristics=STOCK_CHARACTERISTICS, machine=0x014C, tail=b"\xAA" * 300):
    head = bytearray(PE_OFFSET)
    head[:2] = b"MZ"
    struct.pack_into("<I", head, 0x3C, PE_OFFSET)
    coff = b"PE\0\0" + struct.pack("<HHIIIHH", machine, 4, 0, 0, 0, 0xE0, characteristics)
    path.write_bytes(bytes(head) + coff + tail)
    return str(path)


def characteristics_of(path):
    with open(path, "rb") as f:
        f.seek(CHARACTERISTICS_AT)
        return struct.unpack("<H", f.read(2))[0]


def test_flag_is_read(tmp_path):
    assert large_address_aware(make_pe(tmp_path / "a.exe")) is False
    assert large_address_aware(make_pe(tmp_path / "b.exe", STOCK_CHARACTERISTICS | 0x20)) is True


def test_patch_sets_only_the_flag_and_keeps_the_original(tmp_path):
    exe = make_pe(tmp_path / "Rugby08.exe")
    before = open(exe, "rb").read()
    assert ensure_large_address_aware(exe) == "patched"
    after = open(exe, "rb").read()
    assert large_address_aware(exe) is True
    assert characteristics_of(exe) == STOCK_CHARACTERISTICS | IMAGE_FILE_LARGE_ADDRESS_AWARE
    assert len(after) == len(before)
    assert [i for i in range(len(before)) if before[i] != after[i]] == [CHARACTERISTICS_AT]
    assert open(exe + LAA_BACKUP_SUFFIX, "rb").read() == before


def test_patch_is_idempotent_and_never_overwrites_the_backup(tmp_path):
    exe = make_pe(tmp_path / "Rugby08.exe")
    original = open(exe, "rb").read()
    assert ensure_large_address_aware(exe) == "patched"
    patched = open(exe, "rb").read()
    assert ensure_large_address_aware(exe) == "already"
    assert open(exe, "rb").read() == patched
    assert open(exe + LAA_BACKUP_SUFFIX, "rb").read() == original
    # the user puts the stock exe back (game repair): patched again, the first
    # backup is still the stock one
    open(exe, "wb").write(original)
    assert ensure_large_address_aware(exe) == "patched"
    assert open(exe + LAA_BACKUP_SUFFIX, "rb").read() == original


@pytest.mark.parametrize("make", [
    lambda p: p.write_bytes(b""),                                       # the empty fake exe of the tests
    lambda p: p.write_bytes(b"not an executable at all" * 10),
    lambda p: p.write_bytes(b"MZ" + b"\0" * 10),                        # truncated DOS header
    lambda p: make_pe(p, machine=0x8664),                               # 64-bit: not ours to change
    lambda p: p.write_bytes(b"MZ" + b"\0" * 0x3A + struct.pack("<I", 0x7FFFFFF0)),   # PE offset past the end
])
def test_anything_but_a_32bit_pe_is_left_alone(tmp_path, make):
    exe = tmp_path / "Rugby08.exe"
    make(exe)
    before = exe.read_bytes()
    assert large_address_aware(str(exe)) is None
    assert ensure_large_address_aware(str(exe)) == "skipped"
    assert exe.read_bytes() == before
    assert not os.path.exists(str(exe) + LAA_BACKUP_SUFFIX)


def test_missing_exe_is_skipped(tmp_path):
    assert ensure_large_address_aware(str(tmp_path / "nope.exe")) == "skipped"


@pytest.mark.skipif(os.name == "nt" or os.geteuid() == 0, reason="needs a read-only file the user cannot write")
def test_read_only_exe_is_skipped_without_raising(tmp_path, caplog):
    exe = make_pe(tmp_path / "Rugby08.exe")
    os.chmod(exe, stat.S_IRUSR)
    try:
        assert ensure_large_address_aware(exe) == "skipped"
        assert large_address_aware(exe) is False
    finally:
        os.chmod(exe, stat.S_IRUSR | stat.S_IWUSR)
    assert "Could not set the large-address-aware flag" in caplog.text


def test_failed_backup_leaves_the_exe_untouched(tmp_path, monkeypatch):
    """No backup, no patch: the original is never lost."""
    exe = make_pe(tmp_path / "Rugby08.exe")
    before = open(exe, "rb").read()

    def boom(*a, **k):
        raise OSError("disk full")
    monkeypatch.setattr(mod_utils.shutil, "copy2", boom)
    assert ensure_large_address_aware(exe) == "skipped"
    assert open(exe, "rb").read() == before
