"""Match setup's pitch logo list: one entry per distinct logo pack, and its
preview of the logos on a pitch."""
from types import SimpleNamespace

from PIL import Image

from app import competition_branding
from ui.dressing_picker import pitch_logo_preview


def _pack(folder, colour):
    folder.mkdir(parents=True, exist_ok=True)
    Image.new("RGBA", (64, 64), colour).save(folder / "pitch_logo_1.png")
    Image.new("RGBA", (32, 32), colour).save(folder / "pitch_logo_2.png")


def _ds(tmp_path):
    _pack(tmp_path / "six" / "old", (255, 0, 0, 255))
    _pack(tmp_path / "six" / "new", (0, 0, 255, 255))
    _pack(tmp_path / "tri", (0, 255, 0, 255))
    old, new = "old/pitch_logo_%.png", "new/pitch_logo_%.png"
    six = {s: {"name": "Six", "pitch_logo": p} for s, p in
           (("2008", old), ("2009", old), ("2018", new), ("2019", old))}
    tri = {s: {"name": "Tri", "pitch_logo": "pitch_logo_%.png"} for s in ("2008", "2009")}
    return SimpleNamespace(tournaments={"six": six, "tri": tri},
                           tournaments_folder_path={"six": str(tmp_path / "six"),
                                                    "tri": str(tmp_path / "tri")})


def test_same_files_make_one_entry(tmp_path):
    ds = _ds(tmp_path)
    assert competition_branding.unique_choices(ds, "pitch_logo") == [
        ("six:2008", "Six 2008–2019"), ("six:2018", "Six 2018"), ("tri:2008", "Tri")]


def test_preview_paints_the_logos_on_a_pitch(tmp_path):
    ds = _ds(tmp_path)
    bare = pitch_logo_preview(ds, "none")
    tri = pitch_logo_preview(ds, "tri:2008", layout=[
        {"kind": "centre", "x": 0.0, "z": 0.0, "size": 14.0, "angle": 0.0}])
    assert bare.size == tri.size
    r, g, b, _a = tri.getpixel((tri.width // 2 + 5, tri.height // 2 + 5))
    assert g > 200 and r < 60 and b < 60                 # the green logo on the halfway spot
    assert pitch_logo_preview(ds, "tri:2008", layout=[]).tobytes() == bare.tobytes()
