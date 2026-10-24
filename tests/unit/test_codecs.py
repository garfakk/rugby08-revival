"""Binary formats the mod writes into the game: FSH textures (A8R8G8B8 /
DXT1 / DXT5), BIG archives, RefPack, and the .o models of the 3D preview."""
import glob
import os
import shutil

import numpy as np
import pytest
from PIL import Image

from backend import mod_utils as M
from conftest import FIXTURE_DATA, SRC
from shared.omodel import fshlib, olib
from shared.omodel.bigfile import BigArchive

TEMPLATES = os.path.join(SRC, "assets", "templates")
FSH_TEMPLATES = sorted(glob.glob(os.path.join(TEMPLATES, "*.fsh")))
HEAD = os.path.join(FIXTURE_DATA, "players", "heads", "codie_taylor.big")


def _solid(path, size, rgba):
    Image.new("RGBA", size, rgba).save(path)
    return path


def _entries(path):
    with open(path, "rb") as f:
        return M._read_fsh_directory(f)


# ── FSH ──────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("fsh", FSH_TEMPLATES, ids=os.path.basename)
def test_every_template_fsh_entry_decodes(fsh):
    entries = _entries(fsh)
    assert entries
    for i in range(len(entries)):
        img = M.extract_asset_from_fsh_file(fsh, i)
        assert img.size[0] > 0 and img.mode == "RGBA"


@pytest.mark.parametrize("fsh", FSH_TEMPLATES, ids=os.path.basename)
def test_replace_keeps_layout_and_writes_image(fsh, tmp_path):
    work = shutil.copy(fsh, tmp_path / os.path.basename(fsh))
    size_before = os.path.getsize(work)
    img = _solid(str(tmp_path / "red.png"), (8, 8), (200, 30, 40, 255))
    tag = _entries(work)[0][0]
    assert M.replace_asset_in_fsh_file(work, img, tag=tag)
    assert os.path.getsize(work) == size_before                 # layout never changes
    px = np.asarray(M.extract_asset_from_fsh_file(work, 0)).reshape(-1, 4)
    assert np.abs(px[:, :3].astype(int) - [200, 30, 40]).max() <= 8   # DXT quantisation
    assert _entries(work) == _entries(fsh)


def test_replace_by_index_and_position(tmp_path):
    work = shutil.copy(os.path.join(TEMPLATES, "banners.fsh"), tmp_path / "b.fsh")
    img = _solid(str(tmp_path / "g.png"), (16, 16), (0, 255, 0, 255))
    entries = _entries(work)
    assert M.replace_asset_in_fsh_file(work, img, index=len(entries) - 1)
    assert M.replace_asset_in_fsh_file(work, img, position=entries[0][1] + 16)


@pytest.mark.parametrize("kw", [{"tag": "zzzz"}, {"index": 999}, {"position": 3}, {}])
def test_replace_bad_target_fails_cleanly(tmp_path, kw):
    work = shutil.copy(os.path.join(TEMPLATES, "ball.fsh"), tmp_path / "b.fsh")
    before = open(work, "rb").read()
    img = _solid(str(tmp_path / "x.png"), (8, 8), (1, 2, 3, 255))
    assert M.replace_asset_in_fsh_file(work, img, **kw) is False
    assert open(work, "rb").read() == before


def test_not_an_fsh(tmp_path):
    p = tmp_path / "x.fsh"
    p.write_bytes(b"NOPE" + bytes(20))
    with pytest.raises(ValueError):
        M.extract_asset_from_fsh_file(str(p), 0)


@pytest.mark.parametrize("encode,decode,alpha", [
    (M._encode_dxt1, M._decode_dxt1, False),
    (M._encode_dxt5, M._decode_dxt5, True),
    (M._encode_a8r8g8b8, M._decode_a8r8g8b8, True),
])
def test_mod_utils_codecs_roundtrip(encode, decode, alpha):
    rng = np.random.default_rng(0)
    rgba = np.zeros((16, 16, 4), np.uint8)
    rgba[..., :3] = rng.integers(0, 4, 3) * 60          # flat 4x4 blocks: exact in DXT
    rgba[8:, :, :3] = [250, 10, 10]
    rgba[..., 3] = 255 if not alpha else 128
    out = decode(encode(rgba), 16, 16)
    assert np.abs(out[..., :3].astype(int) - rgba[..., :3]).max() <= 8
    if alpha:
        assert np.abs(out[..., 3].astype(int) - rgba[..., 3]).max() <= 17


def _compare_fshlib(name, index=0):
    path = os.path.join(TEMPLATES, name)
    ours = np.asarray(fshlib.Fsh(open(path, "rb").read()).entries[index].decode())
    theirs = np.asarray(M.extract_asset_from_fsh_file(path, index))
    assert ours.shape == theirs.shape
    return np.abs(ours.astype(int) - theirs.astype(int)).max()


@pytest.mark.parametrize("name", ["boots.fsh", "kit_back.fsh", "skins.fsh"])
def test_fshlib_matches_mod_utils_on_dxt(name):
    """The 3D preview's own FSH reader decodes like the game-file writer."""
    assert _compare_fshlib(name) <= 2


@pytest.mark.xfail(strict=True, reason="suspected bug: shared/omodel/fshlib.py decodes "
                   "A8R8G8B8 (0x7d) entries as RGBA, but they are stored BGRA (see "
                   "mod_utils._decode_a8r8g8b8), so the 3D preview swaps red and blue on "
                   "the stock kit/ball/logo textures")
@pytest.mark.parametrize("name", ["kit.fsh"])
def test_fshlib_matches_mod_utils_on_a8r8g8b8(name):
    assert _compare_fshlib(name) <= 2


# ── BIG ──────────────────────────────────────────────────────────────────
def test_big_reader_lists_template():
    big = BigArchive.open(os.path.join(TEMPLATES, "kit_front.big"))
    assert set(big.entries) == {"config.bin", "kit.fsh"}
    assert big.find(".FSH") == "kit.fsh" and big.find(".zip") is None
    with pytest.raises(ValueError):
        BigArchive(b"NOPE" + bytes(12))


def test_big_add_replace_extract(tmp_path):
    work = shutil.copy(os.path.join(TEMPLATES, "kit_front.big"), tmp_path / "k.big")
    new = tmp_path / "kit.fsh"
    new.write_bytes(b"new kit bytes")
    assert M.add_file_to_big_archive(work, str(new))
    extra = tmp_path / "extra.bin"
    extra.write_bytes(b"\x01\x02\x03")
    assert M.add_file_to_big_archive(work, str(extra), "extra.bin")
    big = BigArchive.open(work)
    assert big.read("kit.fsh") == b"new kit bytes"
    assert big.read("extra.bin") == b"\x01\x02\x03"
    assert big.read("config.bin") == BigArchive.open(
        os.path.join(TEMPLATES, "kit_front.big")).read("config.bin")
    out = tmp_path / "out"
    out.mkdir()
    status = M.extract_files_from_big_archive(work, ["extra.bin", "missing.bin"], str(out))
    assert status["extra.bin"] and not status["missing.bin"]
    assert (out / "extra.bin").read_bytes() == b"\x01\x02\x03"


def test_big_missing_inputs(tmp_path):
    assert M.add_file_to_big_archive(str(tmp_path / "no.big"), __file__) is False
    work = shutil.copy(os.path.join(TEMPLATES, "kit_front.big"), tmp_path / "k.big")
    assert M.add_file_to_big_archive(work, str(tmp_path / "nofile")) is False
    assert M.extract_files_from_big_archive(str(tmp_path / "no.big"), "x") is False


# ── RefPack ──────────────────────────────────────────────────────────────
def test_refpack_literals_and_backreference():
    #        flags  magic size=7   literal "abcd"   copy 3 from 4 back   stop
    stream = bytes([0x10, 0xFB, 0, 0, 7, 0xE0]) + b"abcd" + bytes([0x00, 3, 0xFC])
    assert M.is_refpack(stream)
    assert M.refpack_decompress(stream) == b"abcdabc"


def test_refpack_overlapping_copy_and_tail_literal():
    # copy 4 bytes from 1 back (overlapping run), then 1 literal byte and stop
    stream = bytes([0x10, 0xFB, 0, 0, 9, 0xE0]) + b"abcd" + bytes([0x04, 0, 0xFD]) + b"z"
    assert M.refpack_decompress(stream) == b"abcdddddz"


def test_not_refpack():
    assert not M.is_refpack(b"\x00\x00")
    with pytest.raises(ValueError):
        M.refpack_decompress(b"\x00\x00\x00")


# ── 3D models (a75d60ca: custom face rendered as a strip) ────────────────
def test_triangles_detects_list_vs_strip():
    # a closed tetrahedron stored as a triangle list: read as a strip it
    # stacks overlapping triangles (the old streaky-face bug)
    tetra = [0, 1, 2, 0, 2, 3, 0, 3, 1, 1, 3, 2]
    assert olib._triangles(tetra, 4) == [(0, 1, 2), (0, 2, 3), (0, 3, 1), (1, 3, 2)]
    # a real strip (quad grid): stays a strip
    strip = [0, 1, 2, 3, 4, 5, 6, 7]
    assert len(olib._triangles(strip, 8)) == 6
    # indices past the vertex count are dropped
    assert all(max(t) < 4 for t in olib._triangles([0, 1, 2, 3, 9, 1], 4))


def test_overshared_edges():
    assert olib._overshared_edges([]) == 0.0
    fan = [(0, 1, 2), (0, 1, 3), (0, 1, 4)]
    assert olib._overshared_edges(fan) > 0


def test_custom_head_parses_as_clean_surface():
    big = BigArchive.open(HEAD)
    meshes = olib.parse_o(big.read("model.o"))
    assert meshes
    for mesh in meshes:
        assert mesh.triangles
        assert olib._overshared_edges(mesh.triangles) < 0.05


@pytest.mark.parametrize("path", sorted(glob.glob(os.path.join(SRC, "assets", "static_files", "*.o"))),
                         ids=os.path.basename)
def test_bundled_body_models_parse(path):
    meshes = olib.parse_o(open(path, "rb").read())
    assert meshes and all(m.positions is not None and len(m.positions) for m in meshes)


# ── small helpers ────────────────────────────────────────────────────────
def test_set_ini_value(tmp_path):
    ini = tmp_path / "x.ini"
    M._set_ini_value(str(ini), "Window", "Width", 800)
    assert ini.read_text() == "[Window]\nWidth = 800\n"
    ini.write_text("; keep me\n[Window]\nwidth=1\nHeight = 2\n\n[Other]\nA = 1\n")
    M._set_ini_value(str(ini), "window", "Width", 1280)
    M._set_ini_value(str(ini), "Window", "Mode", "all")
    M._set_ini_value(str(ini), "New", "K", "v")
    assert ini.read_text() == ("; keep me\n[Window]\nWidth = 1280\nHeight = 2\nMode = all\n\n"
                               "[Other]\nA = 1\n[New]\nK = v\n")


@pytest.mark.parametrize("value,expected", [("auto", 0.0), ("", 0.0), ("0", 0.0), ("16:9", 16 / 9),
                                            ("1.7777778", 1.7777778), ("21:9", 21 / 9),
                                            ("wide", 0.0), ("4:0", 0.0), ("-2", 0.0)])
def test_widescreen_aspect(value, expected):
    assert M._widescreen_aspect(value) == pytest.approx(expected)


def test_configure_game_widescreen(tmp_path, monkeypatch):
    ini = tmp_path / "rugby08patches.ini"
    ini.write_text("[patches]\nwind = 1\n")
    monkeypatch.setattr(M.user_prefs, "widescreen", True)
    monkeypatch.setattr(M.user_prefs, "widescreen_aspect", "16:9")
    M.configure_game_widescreen(str(tmp_path))
    assert ini.read_text() == "[patches]\nwind = 1\nwidescreen = 1\n[widescreen]\naspect = 1.777778\n"
    monkeypatch.setattr(M.user_prefs, "widescreen", False)
    monkeypatch.setattr(M.user_prefs, "widescreen_aspect", "auto")
    M.configure_game_widescreen(str(tmp_path))
    assert ini.read_text() == "[patches]\nwind = 1\nwidescreen = 0\n[widescreen]\naspect = 0\n"


def test_configure_controller_lock(tmp_path):
    ini = tmp_path / "rugby08patches.ini"
    ini.write_text("[patches]\nwind = 1\n")
    M.configure_controller_lock(str(tmp_path), True)
    assert ini.read_text() == "[patches]\nwind = 1\ncontroller_lock = 1\n"
    M.configure_controller_lock(str(tmp_path), False)
    assert ini.read_text() == "[patches]\nwind = 1\ncontroller_lock = 0\n"


def test_resolve_player_skin_layers(tmp_path):
    (tmp_path / "players" / "skins").mkdir(parents=True)
    (tmp_path / "players" / "skins" / "s.png").write_bytes(b"")
    (tmp_path / "players" / "straps").mkdir()
    (tmp_path / "players" / "straps" / "w.png").write_bytes(b"")
    player = {"name": "X", "skin": "players/skins/s.png",
              "skin_overlay": ["players/straps/w.png", "players/straps/missing.png", "False"],
              "gloves": "players/gloves/none.png"}
    skin, overlays = M.resolve_player_skin_layers(player, str(tmp_path))
    assert skin == os.path.join(str(tmp_path), "players/skins/s.png")
    assert overlays == [os.path.join(str(tmp_path), "players/straps/w.png")]
    assert M.resolve_player_skin_layers({"skin": "light"}, str(tmp_path), ("light",)) == (None, [])


@pytest.mark.parametrize("cm,expected", [(180, (5, 10.87)), (151, (4, 11.45)), (0, (0, 0.0))])
def test_cm_to_feet_and_inches(cm, expected):
    assert M.cm_to_feet_and_inches(cm) == expected


def test_is_custom_asset():
    assert M.is_custom_asset("players/boots/b.png")
    assert not any(M.is_custom_asset(v) for v in ("", "True", "False", True, 3, None))
