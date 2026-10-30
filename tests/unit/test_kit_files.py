"""shared/kit_files.py: back-number strips (one lossless WebP for the 22
backs), their unpacking into one file per shirt, and edits naming the .png a
pack file used to be."""
import os

import numpy as np
import pytest
from PIL import Image

from shared import kit_files as KF
from shared.config import config


@pytest.fixture(autouse=True)
def _tmp(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "temp_directory", str(tmp_path / "tmp"))


def _backs(size=16, alpha=False):
    rng = np.random.default_rng(1)
    mode = "RGBA" if alpha else "RGB"
    return [Image.fromarray(rng.integers(0, 256, (size, size, len(mode)), dtype=np.uint8), mode)
            for _ in range(KF.BACK_COUNT)]


@pytest.mark.parametrize("alpha", [False, True])
def test_strip_round_trip_is_lossless(tmp_path, alpha):
    backs = _backs(alpha=alpha)
    path = str(tmp_path / "home_back.webp")
    KF.write_strip(backs, path)
    frames = KF.strip_frames(path)
    assert len(frames) == KF.BACK_COUNT
    for got, want in zip(frames, backs):
        assert np.array_equal(np.asarray(got.convert("RGBA")), np.asarray(want.convert("RGBA")))


def test_strip_frames_follow_the_width(tmp_path):
    path = str(tmp_path / "big.webp")
    KF.write_strip(_backs(size=32), path)
    assert KF.strip_frame_count(Image.open(path).size) == KF.BACK_COUNT
    assert KF.strip_frames(path)[0].size == (32, 32)


def test_write_strip_refuses_mixed_sizes(tmp_path):
    with pytest.raises(ValueError):
        KF.write_strip(_backs(16)[:2] + _backs(32)[:1], str(tmp_path / "x.webp"))


def test_back_pattern_unpacks_one_file_per_shirt(tmp_path):
    backs = _backs()
    path = str(tmp_path / "home_back.webp")
    KF.write_strip(backs, path)
    pattern = KF.back_pattern(path)
    assert "%" in pattern and pattern.startswith(config.temp_directory)
    for n in (1, 15, 22):
        got = np.asarray(Image.open(pattern.replace("%", str(n))))
        assert np.array_equal(got, np.asarray(backs[n - 1]))
    assert KF.back_pattern(path) == pattern                    # cached


def test_back_file_unpacks_only_the_shirt_asked(tmp_path):
    path = str(tmp_path / "home_back.webp")
    KF.write_strip(_backs(), path)
    one = KF.back_file(path, 7)
    assert os.path.basename(one) == "back_7.png"
    assert os.listdir(os.path.dirname(one)) == ["back_7.png"]


def test_patterns_and_missing_strips_pass_through(tmp_path):
    assert KF.back_pattern("/x/home_back_%.png") == "/x/home_back_%.png"
    assert KF.back_file("/x/home_back_%.png", 3) == "/x/home_back_3.png"
    assert KF.back_file("") == ""
    assert KF.back_pattern(str(tmp_path / "gone.webp")) == ""


def test_packed_rel():
    assert KF.packed_rel("kits_2020/home_back/home_back_%.png") == "kits_2020/home_back.webp"
    assert KF.packed_rel("kits_2020/away_wc_back/away_back_%.png") == "kits_2020/away_back.webp"
    assert KF.packed_rel("kits_2020/home_back_%.png") == "kits_2020/home_back.webp"
    assert KF.packed_rel("kits_2020/home_back/home_back.webp") == "kits_2020/home_back.webp"
    assert KF.packed_rel("kits_2020/home_back.webp") == "kits_2020/home_back.webp"
    assert KF.packed_rel("kits_2020/home_front.png") == "kits_2020/home_front.webp"
    assert KF.packed_rel("kits_2020/home_front.big") == "kits_2020/home_front.big"
    assert KF.packed_rel("kits/back.fsh") == "kits/back.fsh"


def test_migrate_kit_files_points_old_edits_at_packed_files(tmp_path):
    (tmp_path / "k").mkdir()
    (tmp_path / "k" / "home_front.webp").write_bytes(b"x")
    (tmp_path / "k" / "home_back.webp").write_bytes(b"x")
    (tmp_path / "k" / "away_back.webp").write_bytes(b"x")
    (tmp_path / "k" / "away_front.png").write_bytes(b"x")      # not packed: kept
    info = {"kits": {
        "home": {"frontKitFile": "k/home_front.png", "backKitFile": "k/home_back/home_back_%.png",
                 "variants": {"wc": {"frontKitFile": "k/home_front.png"}}},
        "away": {"frontKitFile": "k/away_front.png", "backKitFile": "k/nothing_%.png"},
        "third": {"backKitFile": "k/away_back/away_back.webp"}}}       # packed before the move
    assert KF.migrate_kit_files(info, str(tmp_path))
    home, away = info["kits"]["home"], info["kits"]["away"]
    assert home["frontKitFile"] == "k/home_front.webp"
    assert home["backKitFile"] == "k/home_back.webp"
    assert home["variants"]["wc"]["frontKitFile"] == "k/home_front.webp"
    assert away == {"frontKitFile": "k/away_front.png", "backKitFile": "k/nothing_%.png"}
    assert info["kits"]["third"]["backKitFile"] == "k/away_back.webp"
    assert not KF.migrate_kit_files(info, str(tmp_path))
