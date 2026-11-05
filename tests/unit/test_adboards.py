"""Adboard sets: the nine-board grounds (Castres, Le Parc, Perpignan, La
Beaujoire) look up ads7/ads8, so every set the game can be given has them
(backend.mod_utils.complete_adboards)."""
import glob
import os

import pytest

from backend.mod_utils import build_fsh, complete_adboards, extract_asset_from_fsh_file, fsh_entries

ROOT = os.path.join(os.path.dirname(__file__), "..", "..")
STATIC_WC = os.path.join(ROOT, "src", "assets", "static_files", "485c3bef5972390ec66b2ff013c45d14.fsh")


def _seven_board_set():
    entries = [(f"ads{i}", b"\x60" + b"\0" * 3 + (256).to_bytes(2, "little") * 2 + b"\0" * 8
                + bytes([i]) * (256 * 256 // 2)) for i in range(7)]
    return build_fsh(b"G359", entries)


def test_build_fsh_round_trips():
    data = _seven_board_set()
    assert [t for t, _ in fsh_entries(data)] == [f"ads{i}" for i in range(7)]
    assert build_fsh(data[12:16], fsh_entries(data)) == data


def test_missing_boards_copied_from_their_twins():
    data = _seven_board_set()
    full = dict(fsh_entries(complete_adboards(data)))
    assert sorted(full) == [f"ads{i}" for i in range(9)]
    assert full["ads7"] == full["ads4"] and full["ads8"] == full["ads5"]
    assert dict(fsh_entries(complete_adboards(data, {"ads7": full["ads0"]})))["ads7"] == full["ads0"]


def test_a_full_set_is_left_as_it_is():
    full = complete_adboards(_seven_board_set())
    assert complete_adboards(full) is full


@pytest.mark.parametrize("path", [STATIC_WC] + sorted(glob.glob(
    os.path.join(ROOT, "data", "competitions", "**", "adboards.fsh"), recursive=True)))
def test_shipped_adboards_have_nine_boards(path):
    if not os.path.isfile(path):
        pytest.skip("not in this checkout")
    tags = [t for t, _ in fsh_entries(open(path, "rb").read())]
    assert set(tags) >= {f"ads{i}" for i in range(9)}
    for i in range(len(tags)):
        extract_asset_from_fsh_file(path, i)          # every board decodes
