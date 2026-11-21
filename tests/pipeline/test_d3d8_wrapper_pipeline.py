"""Match starts with and without a D3D8 wrapper (dgVoodoo2) in the game folder,
through the real start_match flow: the static files (which hold the proxy
d3d8.dll) must not overwrite the wrapper, and a game folder without one must
come out exactly as before (proxy, RealD3D8Dll empty, no extra files)."""
import os
import shutil

import pytest

from app.match_data_builder import build_match_data
from backend import mod_utils
from backend.start_match import start_match
from conftest import SRC, config, make_match_config
from unit.test_codecs import _fake_d3d8

pytestmark = pytest.mark.slow

PROXY = os.path.join(SRC, "assets", "static_files", "d3d8.dll")


@pytest.fixture
def start(game_dir, monkeypatch, ds):
    monkeypatch.setattr(mod_utils, "ensure_wine_d3d8_native_override", lambda *a, **k: None)
    monkeypatch.setattr(mod_utils, "disable_wine_virtual_desktop", lambda *a, **k: None)
    monkeypatch.setattr(config, "large_address_aware", False)
    os.makedirs(os.path.join(game_dir, "Data"), exist_ok=True)
    md = build_match_data(ds, make_match_config(ds))
    return lambda: start_match(md, start_R08=False)


def real_d3d8(game_dir):
    with open(os.path.join(game_dir, "rugby08_windowed.ini")) as f:
        return next(l.split("=", 1)[1].strip() for l in f if l.startswith("RealD3D8Dll="))


def proxy_is_d3d8(game_dir):
    return open(os.path.join(game_dir, "d3d8.dll"), "rb").read() == open(PROXY, "rb").read()


@pytest.mark.parametrize("platform", ["windows", "linux"])
def test_no_wrapper_unchanged(game_dir, start, monkeypatch, tmp_path, platform):
    monkeypatch.setattr(config, "platform", platform)
    original = tmp_path / "original"                      # installer copy: an original folder
    original.mkdir()
    shutil.copy(PROXY, original / "d3d8.dll")            # leftovers of a mod run in place
    monkeypatch.setattr(config, "R08_original_directory", str(original), raising=False)
    for _ in range(2):
        start()
        assert proxy_is_d3d8(game_dir) and real_d3d8(game_dir) == ""
        assert not [f for f in os.listdir(game_dir) if "dgvoodoo" in f.lower()]


def test_dgvoodoo_next_to_exe_kept(game_dir, start, monkeypatch):
    monkeypatch.setattr(config, "platform", "windows")
    dgv = _fake_d3d8()
    with open(os.path.join(game_dir, "D3D8.dll"), "wb") as f:
        f.write(dgv)
    for _ in range(2):                                    # and still used at the next match
        start()
        assert proxy_is_d3d8(game_dir)
        assert real_d3d8(game_dir) == mod_utils.AUTO_D3D8_WRAPPER
        assert open(os.path.join(game_dir, mod_utils.AUTO_D3D8_WRAPPER), "rb").read() == dgv


def test_dgvoodoo_in_original_folder(game_dir, start, monkeypatch, tmp_path):
    monkeypatch.setattr(config, "platform", "windows")
    original = tmp_path / "original"
    original.mkdir()
    (original / "D3D8.dll").write_bytes(_fake_d3d8())
    (original / "dgVoodoo.conf").write_text("[General]")
    monkeypatch.setattr(config, "R08_original_directory", str(original), raising=False)
    start()
    assert proxy_is_d3d8(game_dir) and real_d3d8(game_dir) == mod_utils.AUTO_D3D8_WRAPPER
    assert os.path.exists(os.path.join(game_dir, "dgVoodoo.conf"))
    assert (original / "D3D8.dll").read_bytes() == _fake_d3d8()


def test_named_wrapper_kept(game_dir, start, monkeypatch):
    """d3d8_real_dll set (any DLL, any platform): renamed before the static
    files overwrite it. Before this fix the static files won."""
    monkeypatch.setattr(config, "platform", "linux")
    monkeypatch.setattr(config, "d3d8_real_dll", "my_d3d8.dll")
    with open(os.path.join(game_dir, "d3d8.dll"), "wb") as f:
        f.write(b"some D3D8 wrapper")
    start()
    assert proxy_is_d3d8(game_dir) and real_d3d8(game_dir) == "my_d3d8.dll"
    assert open(os.path.join(game_dir, "my_d3d8.dll"), "rb").read() == b"some D3D8 wrapper"
