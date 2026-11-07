"""FSH chunk chains must end inside the texture: the game follows each
chunk's next offset while loading and a chain running past the end made it
read garbage and crash at random (Rugby08.exe+0x3638b6, Rieko Ioane's head)."""
import glob
import os
import struct

import pytest

from backend.mod_utils import copy_texture_file, repair_fsh_chains
from conftest import REAL_DATA


def broken_chains(data):
    bad = []
    start = data.find(b"SHPI")
    while start != -1:
        size, count = struct.unpack_from("<II", data, start + 4)
        end = min(start + size, len(data))
        for k in range(count):
            tag, off = struct.unpack_from("<4sI", data, start + 16 + 8 * k)
            pos = start + off
            for _ in range(64):
                if pos + 16 > end:
                    bad.append((start, tag))
                    break
                step = struct.unpack_from("<I", data, pos)[0] >> 8
                if not step:
                    break
                pos += step
        start = data.find(b"SHPI", start + 4)
    return bad


def fsh(next_of_last):
    """One entry: a 16-byte pixel chunk then a name chunk with `next_of_last`."""
    body = struct.pack("<IHH", 0x60 | 32 << 8, 4, 4) + b"\0" * 8 + b"\0" * 16
    body += struct.pack("<I", 0x70 | next_of_last << 8) + b"face" + b"\0" * 8
    size = 24 + len(body)
    return b"SHPI" + struct.pack("<I", size) + struct.pack("<I", 1) + b"G264" + b"face" + struct.pack("<I", 24) + body


def test_repair_ends_a_chain_running_past_the_end():
    data = b"BIGF" + b"\0" * 12 + fsh(16)
    assert broken_chains(data)
    fixed = repair_fsh_chains(data)
    assert not broken_chains(fixed) and len(fixed) == len(data)


def test_valid_file_is_returned_as_is():
    data = fsh(0)
    assert repair_fsh_chains(data) is data


def test_copy_repairs(tmp_path):
    src, dst = tmp_path / "a.big", tmp_path / "b.big"
    src.write_bytes(fsh(16))
    assert copy_texture_file(str(src), str(dst))
    assert not broken_chains(dst.read_bytes())


@pytest.mark.parametrize("pattern", ["players/heads/*.big", "teams/**/*.fsh", "teams/**/*.big",
                                     "competitions/**/*.fsh"])
def test_shipped_textures_have_valid_chains(pattern):
    files = glob.glob(os.path.join(REAL_DATA, pattern), recursive=True)
    bad = [os.path.relpath(f, REAL_DATA) for f in files if broken_chains(open(f, "rb").read())]
    assert not bad
