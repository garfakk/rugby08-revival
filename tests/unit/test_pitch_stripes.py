"""A stadium's pitch stripes (backend/pitch_stripes.py): read from and written
into the scene pack's Config.bin, nothing else in the pack touched."""
import struct

from backend import pitch_stripes as ps
from shared.omodel.bigfile import BigArchive, pack_big


def _pack(tmp_path, opacity=0.35, brightness=1.1):
    config = bytearray(600)
    struct.pack_into("<I", config, 0, ps.MAGIC)
    struct.pack_into("<f", config, 35 * 4, opacity)
    struct.pack_into("<f", config, 36 * 4, brightness)
    path = tmp_path / "scene.big"
    path.write_bytes(pack_big([("Config.bin", bytes(config)), ("Stadium.o", b"model bytes")]))
    return str(path)


def test_read_gives_percent(tmp_path):
    assert ps.read(_pack(tmp_path)) == {"opacity": 35, "brightness": 110}


def test_apply_changes_only_the_asked_floats(tmp_path):
    path = _pack(tmp_path)
    before = BigArchive.open(path)
    assert ps.apply(path, {"opacity": 60})
    after = BigArchive.open(path)
    assert ps.read(path) == {"opacity": 60, "brightness": 110}
    assert after.read("Stadium.o") == before.read("Stadium.o")
    a, b = bytearray(before.read("Config.bin")), bytearray(after.read("Config.bin"))
    struct.pack_into("<f", a, 35 * 4, 0.6)
    assert bytes(a) == bytes(b)


def test_clean_keeps_known_keys_in_range():
    assert ps.clean({"opacity": 500, "brightness": 10, "junk": 1}) == {"opacity": 100, "brightness": 50}
    assert ps.clean({"opacity": "x"}) == {} and ps.clean(None) == {}


def test_a_pack_without_config_is_left_alone(tmp_path):
    path = tmp_path / "x.big"
    path.write_bytes(pack_big([("Stadium.o", b"a")]))
    assert ps.read(str(path)) == {} and not ps.apply(str(path), {"opacity": 10})


def test_scene_vertex_colours_are_the_baked_lighting():
    """A stadium mesh's colour dword is 0xAARRGGBB; without one the mesh is white."""
    import numpy as np
    from backend import stadium_scene as ss

    class Mesh:
        colors = [0xFF808080, 0x80FF0000]
    got = ss._colours(Mesh, 2)
    assert np.allclose(got[0], [128 / 255, 128 / 255, 128 / 255, 1.0])
    assert np.allclose(got[1], [1.0, 0.0, 0.0, 128 / 255])
    assert (ss._colours(type("M", (), {"colors": []}), 3) == 1.0).all()
