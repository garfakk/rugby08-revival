"""A head whose model.o has hundreds of mesh primitives (guido_petti.big,
400+ in a 5 MB model) hung the match load: the game ran out of memory loading
data/motion/script.big and sat in its fatal-error loop on a black screen."""
import glob
import os
import struct

import pytest

from backend.mod_utils import MAX_HEAD_PRIMITIVES, head_model_primitives, head_too_heavy
from conftest import REAL_DATA


def make_big(path, entries):
    names = b"".join(struct.pack(">II", 0, 0) + n + b"\0" for n, _ in entries)
    header = 16 + len(names)
    out = bytearray(b"BIGF" + struct.pack("<I", 0) + struct.pack(">II", len(entries), header))
    offset, table = header, bytearray()
    for name, blob in entries:
        table += struct.pack(">II", offset, len(blob)) + name + b"\0"
        offset += len(blob)
    out += table
    for _, blob in entries:
        out += blob
    path.write_bytes(bytes(out))
    return str(path)


def test_counts_model_primitives(tmp_path):
    light = make_big(tmp_path / "light.big", [(b"model.o", b"\x7fELF" + b"__geoprimdatabuf" * 3),
                                               (b"textures.fsh", b"SHPI")])
    heavy = make_big(tmp_path / "heavy.big", [(b"model.o", b"__geoprimdatabuf" * (MAX_HEAD_PRIMITIVES + 1))])
    assert head_model_primitives(light) == 3
    assert not head_too_heavy(light)
    assert head_too_heavy(heavy)


def test_unreadable_is_not_heavy(tmp_path):
    junk = tmp_path / "junk.big"
    junk.write_bytes(b"nope")
    assert head_model_primitives(str(junk)) is None
    assert not head_too_heavy(str(junk))
    assert not head_too_heavy(str(tmp_path / "missing.big"))


@pytest.mark.skipif(not os.path.isdir(os.path.join(REAL_DATA, "players", "heads")), reason="no data")
def test_shipped_heads_are_light():
    heavy = [os.path.basename(p) for p in glob.glob(os.path.join(REAL_DATA, "players", "heads", "*.big"))
             if head_too_heavy(p)]
    assert heavy == []
