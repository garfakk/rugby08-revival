"""The roof-flag texture a team banners file needs for the World Cup stadium
dressing (backend.mod_utils.complete_banners)."""
import os

from PIL import Image

from backend.mod_utils import WCB_SIZE, complete_banners, fsh_entries, fsh_entry_image
from conftest import SRC
from shared.omodel import fshlib

TEMPLATE = os.path.join(SRC, "assets", "templates", "banners.fsh")


def _template():
    with open(TEMPLATE, "rb") as f:
        return f.read()


def test_template_gets_a_roof_flag():
    data = _template()
    assert "_wcb" not in dict(fsh_entries(data))
    full = complete_banners(data)
    tags = [t for t, _ in fsh_entries(full)]
    assert tags == ["_flA", "_flB", "_bnA", "_bnB", "_wcb"]
    wcb = next(e for e in fshlib.Fsh(full).entries if e.name == "_wcb")
    assert (wcb.code, wcb.w, wcb.h) == (0x60, *WCB_SIZE)
    # the four banners are untouched
    old = dict(fsh_entries(data))
    new = dict(fsh_entries(full))
    for tag in ("_flA", "_flB", "_bnA", "_bnB"):
        assert new[tag][:16 + 512 * 128 * 4] == old[tag][:16 + 512 * 128 * 4]


def test_roof_flag_is_the_teams_flag():
    data = _template()
    flag = Image.new("RGBA", (64, 32), (200, 30, 30, 255))
    full = complete_banners(data, flag)
    img = fsh_entry_image(dict(fsh_entries(full))["_wcb"]).convert("RGB")
    r, g, b = img.getpixel((100, 200))
    assert r > 150 and g < 80 and b < 80


def test_existing_roof_flag_is_kept():
    full = complete_banners(_template())
    assert complete_banners(full) is full


def test_every_chunk_chain_ends_inside_the_file():
    """The game follows each chunk's next offset; the first roof flag pointed
    16 bytes past the end of the file and crashed loading at random."""
    import struct
    full = complete_banners(_template())
    count = struct.unpack_from("<I", full, 8)[0]
    for i in range(count):
        tag, pos = struct.unpack_from("<4sI", full, 16 + 8 * i)
        while True:
            assert pos + 16 <= len(full), tag
            step = struct.unpack_from("<I", full, pos)[0] >> 8
            if not step:
                break
            pos += step
