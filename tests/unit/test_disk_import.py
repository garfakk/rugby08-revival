"""app/disk_import.py: "Load from disk" copies into the user's mod_data."""
import os

import pytest

from app import disk_import as D


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    pack, user = tmp_path / "pack", tmp_path / "user"
    (pack / "players" / "skins").mkdir(parents=True)
    (pack / "players" / "skins" / "a.png").write_bytes(b"pack-a")
    (pack / "teams" / "Agen" / "kits_2024").mkdir(parents=True)
    (pack / "teams" / "Agen" / "kits_2024" / "home_front.webp").write_bytes(b"pack-kit")
    monkeypatch.setattr(D.config, "mod_data_directory", str(pack))
    monkeypatch.setattr(D.config, "pack_directory", str(pack))
    monkeypatch.setattr(D, "user_data_directory", lambda: str(user))
    monkeypatch.setattr(D.G, "saves_to_user_edits", lambda: True)
    return pack, user


def _w(path, data=b"x"):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "wb") as fh:
        fh.write(data)
    return str(path)


def test_file_goes_to_the_overlay_and_is_usable(dirs, tmp_path):
    pack, user = dirs
    src = _w(tmp_path / "dl" / "glow.png", b"glow")
    assert D.import_files([src], str(pack), "players/skins", (".png",)) == ["players/skins/glow.png"]
    assert (user / "mod_data" / "players" / "skins" / "glow.png").read_bytes() == b"glow"
    assert (pack / "players" / "skins" / "glow.png").read_bytes() == b"glow"     # listed now


def test_a_used_name_is_never_replaced(dirs, tmp_path):
    pack, user = dirs
    src = _w(tmp_path / "mine" / "a.png", b"other")
    assert D.import_files([src], str(pack), "players/skins", (".png",)) == ["players/skins/mine/a.png"]
    assert (pack / "players" / "skins" / "a.png").read_bytes() == b"pack-a"
    # identical file: reused, nothing copied
    same = _w(tmp_path / "copy" / "a.png", b"pack-a")
    assert D.import_files([same], str(pack), "players/skins", (".png",)) == ["players/skins/a.png"]
    assert not (user / "mod_data" / "players" / "skins" / "a.png").exists()


def test_flatten_renames_instead(dirs, tmp_path):
    pack, _user = dirs
    (pack / "players" / "heads").mkdir()
    (pack / "players" / "heads" / "head_1.big").write_bytes(b"h1")
    folder = tmp_path / "heads pack"
    _w(folder / "head_1.big", b"new")
    _w(folder / "sub" / "head_2.big", b"h2")
    _w(folder / "notes.txt")
    out = D.import_files([str(folder)], str(pack), "players/heads", (".big",), flatten=True)
    assert out == ["players/heads/head_1_2.big", "players/heads/head_2.big"]


def test_folder_keeps_its_name_relative_to_a_team(dirs, tmp_path):
    pack, user = dirs
    team = pack / "teams" / "Agen"
    kits = tmp_path / "kits_2026"
    _w(kits / "home_front.webp", b"f")
    _w(kits / "home_back.webp", b"b")
    out = D.import_files([str(kits)], str(team), "", (".webp",))
    assert out == ["kits_2026/home_back.webp", "kits_2026/home_front.webp"]
    assert (user / "mod_data" / "teams" / "Agen" / "kits_2026" / "home_front.webp").is_file()


def test_maintainer_writes_the_data_folder(dirs, tmp_path, monkeypatch):
    pack, user = dirs
    monkeypatch.setattr(D.G, "saves_to_user_edits", lambda: False)
    src = _w(tmp_path / "b.png", b"b")
    D.import_files([src], str(pack), "players/skins", (".png",))
    assert (pack / "players" / "skins" / "b.png").is_file() and not (user / "mod_data").exists()


def test_nothing_matching(dirs, tmp_path):
    pack, _ = dirs
    assert D.import_files([_w(tmp_path / "x.txt")], str(pack), "players/skins", (".png",)) == []
