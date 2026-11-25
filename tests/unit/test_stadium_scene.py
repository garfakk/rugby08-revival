"""backend/stadium_scene: lamps from fx.big, junk triangles, the camera ray,
the teams' flags; backend/pitch_lines: the numbers of the pitch lines."""
import os
import struct

import numpy as np
import pytest
from PIL import Image

from backend import stadium_scene as ss
from shared.omodel.bigfile import pack_big


def _jdi(points):
    """A minimal effect file: the chunk table with MESH, the points after the
    80-byte picture path."""
    head = bytearray(0x190)
    head[:4] = b"YMUD"
    head[16:20] = b"MESH"[::-1]
    struct.pack_into("<III", head, 20, 4098, 1, 0x190)
    mesh = bytearray(0x50) + struct.pack("<f", float(len(points)))
    mesh += np.asarray(points, np.float32).tobytes()
    return bytes(head + mesh)


def test_jdi_points():
    pts = [(-8212.0, 4516.0, -3299.0), (8174.0, 4635.0, 6012.0)]
    got = ss._jdi_points(_jdi(pts))
    assert np.allclose(got, pts)
    assert ss._jdi_points(b"nope") is None


def test_read_lights_keeps_lamps_only():
    fx = pack_big([
        ("fx_floods.jdi", _jdi([(-8000.0, 4500.0, 0.0), (8000.0, 4500.0, 0.0)])),
        ("fx_floods01.jdi", _jdi([(-100.0, 20.0, -50.0), (100.0, 170.0, 25.0)])),   # on a node
        ("fx_pin.jdi", _jdi([(-6000.0, 30.0, 0.0), (6000.0, 2000.0, 0.0)])),         # one on the grass
        ("fx_flash.jdi", _jdi([(5000.0, 3000.0, 0.0)])),
    ])

    class Big:
        def find(self, name):
            return "fx.big"

        def read(self, name):
            return fx
    lights = dict(ss.read_lights(Big()))
    assert set(lights) == {"flood", "pin"}
    assert len(lights["flood"]) == 2
    assert np.allclose(lights["pin"], [(6000.0, 2000.0, 0.0)])


def test_drop_over_pitch_and_huge():
    pos = np.array([[-3000, 0, -3000], [3000, 0, 3000], [3000, 50, 3000],      # across the field
                    [-150, 105, 2626], [-150, 700, 2626], [-148, 105, 2622],   # a post
                    [0, 1788, 4211], [600, 1788, 4211], [-300, 1995, -4211]],  # a huge sliver, high up
                   np.float32)
    tri = np.arange(9, dtype=np.uint32)
    kept = ss._drop_over_pitch(pos, tri).reshape(-1, 3).tolist()
    assert kept == [[3, 4, 5], [6, 7, 8]]
    assert ss._drop_huge(pos, np.array([3, 4, 5, 6, 7, 8], np.uint32)).tolist() == [3, 4, 5]


def test_ray_hit_normal():
    # a wall facing -z at z = 1000
    buf = np.zeros((3, 12), np.float32)
    buf[:, :3] = [(-500, 0, 1000), (500, 0, 1000), (0, 900, 1000)]
    buf[:, 3:6] = (0, 0, -1)
    scene = ss.Scene([ss.Part("wall", "Texture2x", "Stadium.o", buf, np.arange(3, dtype=np.uint32))], {})
    t, n = scene.ray_hit((0, 300, 0), (0, 0, 1))
    assert abs(t - 1000) < 1e-3 and np.allclose(n, (0, 0, -1))
    t, n = scene.ray_hit((0, 300, 0), (0, 0, -1))
    assert t == float("inf") and n is None


def test_team_textures(tmp_path):
    for i, colour in enumerate(("red", "blue", "green", "white"), 1):
        Image.new("RGBA", (64, 16), colour).save(tmp_path / f"banner_{i}.png")
    got = ss.team_textures(str(tmp_path / "banner_%.png"), "")
    assert set(got) == {"hflA", "hflB", "hbnA", "hbnB", "Baus"}
    assert got["Baus"].getpixel((0, 0))[:3] == (0, 0, 255)



def test_number_triangles():
    from backend import pitch_lines
    glyph = np.array([[1500, 0, 0], [1610, 0, 0], [1610, 0, 65], [1500, 0, 65]], np.float32)
    dash = np.array([[1490, 0, 300], [1500, 0, 300], [1500, 0, 400], [1490, 0, 400]], np.float32)
    line = np.array([[-1770, 0, 676], [1770, 0, 676], [1770, 0, 686], [-1770, 0, 686]], np.float32)
    quad = np.array([[0, 1, 2], [0, 2, 3]])
    pos = np.concatenate([glyph, dash])
    tri = np.concatenate([quad, quad + 4])
    found = pitch_lines.number_triangles([(pos, tri), (line, quad)])
    assert sorted(found) == [(0, 0), (0, 1)]


def _area(part):
    v = part.buf[:, [0, 2]][part.tri.reshape(-1, 3).astype(int)]
    return 0.5 * float(np.abs(np.cross(v[:, 1] - v[:, 0], v[:, 2] - v[:, 0])).sum())


REAL_PACK = os.path.join(os.path.dirname(__file__), "..", "..", "data", "stadiums", "Eden Park", "eden_park.day.big")


@pytest.mark.skipif(not os.path.isfile(REAL_PACK), reason="no data pack")
def test_pitch_lines_apply(tmp_path):
    import shutil
    from backend import pitch_lines
    from shared.omodel.bigfile import BigArchive
    pack = tmp_path / "scene.big"
    shutil.copy(REAL_PACK, pack)
    before = ss.read(str(pack))
    assert sum(len(p.tri) for p in before.parts if p.numbers)
    assert pitch_lines.apply(str(pack), "no_numbers")
    after = ss.read(str(pack))
    assert not any(p.numbers for p in after.parts)          # the glyphs have no area left

    lines = lambda sc, numbers: sum(_area(p) for p in sc.parts
                                    if p.model == "PitchLines.o" and p.numbers == numbers)
    assert lines(after, False) == pytest.approx(lines(before, False))    # the lines as they were
    old, new = BigArchive.open(REAL_PACK), BigArchive.open(str(pack))
    assert [n for n in old.entries if old.read(n) != new.read(n)] == ["PitchLines.o"]
    assert not pitch_lines.apply(str(pack), "no_numbers")   # nothing left to fold
    assert not pitch_lines.apply(str(pack), "")


def test_grid_strip_join_dropped():
    # a pitch tile grid read as a strip: one join across the field
    xs, zs = np.meshgrid(np.arange(4) * 683.0, np.arange(4) * 683.0)
    pos = np.stack([xs.ravel(), np.zeros(16), zs.ravel()], axis=1).astype(np.float32)
    quads = [(r * 4 + c, r * 4 + c + 1, r * 4 + c + 5) for r in range(3) for c in range(3)]
    tri = np.array(quads + [(0, 1, 15)], np.int64)
    kept = ss._drop_streaks(pos, tri, factor=2.5, floor=0.0)
    assert len(kept) == 9 and (0, 1, 15) not in map(tuple, kept.tolist())


def test_cut_out_mipmaps_keep_people():
    from ui.stadium_view import CUT, _alpha_mipmaps
    rgba = np.zeros((64, 64, 4), np.uint8)
    rgba[8:56, 28:36] = (200, 90, 40, 255)        # a thin figure on black, see-through
    base, levels = _alpha_mipmaps(rgba, CUT)
    assert [lv.shape[:2] for lv in levels][-1] == (1, 1)
    assert base[0, 0, :3].tolist() == [200, 90, 40]   # no black around the figure
    for lv in levels[:3]:                             # still as much figure, no box
        cover = (lv[..., 3] / 255.0 >= CUT).mean()
        assert 0.06 < cover < 0.2
        assert lv[..., :3][lv[..., 3] > 0].min() > 30
