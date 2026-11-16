"""A custom stadium's giant screen (backend/stadium_screen.py): the texture is
repainted in place, its format and attachment kept, its mipmaps dropped, and
the scene pack around it left intact."""
import struct

from PIL import Image

from backend import mod_utils as mu
from backend import stadium_screen as ss
from shared.omodel.bigfile import BigArchive, pack_big

W, H = 824, 212


def _screen_fsh():
    size = mu._fsh_pixel_data_size(mu.FSH_CODE_DXT5, W, H)
    mips = b"\x11" * 2000
    trailer = b"\x70" + b"\0" * 15
    nxt = 16 + size + len(mips)
    head = struct.pack("<IHHIHH", mu.FSH_CODE_DXT5 | (nxt << 8), W, H, 0, 0, 0x9000)
    scre = head + b"\0" * size + mips + trailer
    other = struct.pack("<IHHIHH", mu.FSH_CODE_DXT1, 4, 4, 0, 0, 0) + b"\x22" * 8
    return mu.build_fsh(b"G359", [("blac", other), ("scre", scre)])


def _teams():
    crest = Image.new("RGBA", (64, 80), (200, 30, 30, 255))
    return {"name": "Racing 92", "logo": crest}, {"name": "Pacific Islanders", "logo": None}


def test_render_is_the_texture_size():
    home, away = _teams()
    assert ss.render((W, H), home, away).size == (W, H)
    assert ss.render((W, H), home, away, Image.new("RGBA", (50, 50), "white")).size == (W, H)


def test_texture_replaced_without_mipmaps():
    data = _screen_fsh()
    home, away = _teams()
    new = ss.with_texture(data, "scre", ss.render((W, H), home, away))
    before, after = dict(mu.fsh_entries(data)), dict(mu.fsh_entries(new))
    assert [t for t, _ in mu.fsh_entries(new)] == ["blac", "scre"]
    assert after["blac"] == before["blac"]
    block = after["scre"]
    word, w, h = struct.unpack_from("<IHH", block, 0)
    size = mu._fsh_pixel_data_size(mu.FSH_CODE_DXT5, W, H)
    assert (word & 0xFF, w, h) == (mu.FSH_CODE_DXT5, W, H)
    assert word >> 8 == 16 + size and block[15] >> 4 == 0
    assert block[16 + size:] == b"\x70" + b"\0" * 15
    assert mu.fsh_entry_image(block).size == (W, H)


def test_dress_scene_keeps_the_pack(tmp_path):
    path = tmp_path / "scene.big"
    path.write_bytes(pack_big([("Config.bin", b"cfg"), ("Textures.fsh", _screen_fsh()),
                               ("Stadium.o", b"\x7fELF" + b"x" * 33)]))
    home, away = _teams()
    assert ss.dress_scene(str(path), "scre", home, away)
    archive = BigArchive(path.read_bytes())
    assert list(archive.entries) == ["Config.bin", "Textures.fsh", "Stadium.o"]
    assert archive.read("Config.bin") == b"cfg" and archive.read("Stadium.o").startswith(b"\x7fELF")
    assert ss.screen_size(path.read_bytes(), "scre") == (W, H)
    assert not ss.dress_scene(str(path), "nope", home, away)


def test_pack_big_header():
    blob = pack_big([("a.bin", b"1234"), ("bb.fsh", b"x")])
    assert blob[:4] == b"BIGF" and struct.unpack_from("<I", blob, 4)[0] == len(blob)
    count, head = struct.unpack_from(">II", blob, 8)
    assert count == 2 and head == (16 + 8 + 6 + 8 + 7 + 3) // 4 * 4
    archive = BigArchive(blob)
    assert archive.read("a.bin") == b"1234" and archive.read("bb.fsh") == b"x"
    assert all(off % 16 == 0 for off, _ in archive.entries.values())
