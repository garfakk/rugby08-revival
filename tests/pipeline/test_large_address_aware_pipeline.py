"""Every match start gives Rugby08.exe its large address space (see
tests/unit/test_large_address_aware.py), unless config.large_address_aware is
off, and a match start with an exe that cannot be patched still goes through."""
import os
from pathlib import Path

import pytest

from app.match_data_builder import build_match_data
from backend import mod_utils
from backend.mod_utils import LAA_BACKUP_SUFFIX, large_address_aware
from backend.start_match import start_match
from conftest import config, make_match_config
from unit.test_large_address_aware import make_pe

pytestmark = pytest.mark.slow


@pytest.fixture
def start(game_dir, monkeypatch, ds):
    monkeypatch.setattr(mod_utils, "ensure_wine_d3d8_native_override", lambda *a, **k: None)
    monkeypatch.setattr(mod_utils, "disable_wine_virtual_desktop", lambda *a, **k: None)
    os.makedirs(os.path.join(game_dir, "Data"), exist_ok=True)
    md = build_match_data(ds, make_match_config(ds))
    return lambda: start_match(md, start_R08=False)


def test_match_start_patches_the_game_exe(game_dir, start):
    exe = make_pe(Path(game_dir) / "Rugby08.exe")
    assert large_address_aware(exe) is False
    start()
    assert large_address_aware(exe) is True
    assert os.path.exists(exe + LAA_BACKUP_SUFFIX)
    start()                                           # next match: nothing more to do
    assert large_address_aware(exe) is True


def test_option_off_leaves_the_exe_alone(game_dir, start, monkeypatch):
    monkeypatch.setattr(config, "large_address_aware", False)
    exe = make_pe(Path(game_dir) / "Rugby08.exe")
    before = open(exe, "rb").read()
    start()
    assert open(exe, "rb").read() == before
    assert not os.path.exists(exe + LAA_BACKUP_SUFFIX)


def test_unpatchable_exe_does_not_stop_the_match(game_dir, start):
    """The tests' fake exe is empty: not a PE, skipped, the match files are still written."""
    assert os.path.getsize(os.path.join(game_dir, "Rugby08.exe")) == 0
    assert start() is None
    assert os.path.getsize(os.path.join(game_dir, "Rugby08.exe")) == 0
    assert os.listdir(game_dir)
