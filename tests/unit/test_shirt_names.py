"""shared/shirt_names.py and its two users: the match files (names lettered
onto each player's back-number texture) and the team editor's edit helpers.
The kits here are drawn on the fly (22 white backs, a black number each), so
the number detection, the placement and the lettering are checked on real
512 px images rather than the fixture pack's 8x8 placeholders."""
import copy
import os

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app import team_ops as T
from shared import shirt_names as SN

NUMBER_BOX = (0.36, 0.40, 0.64, 0.70)      # where the drawn numbers sit (fractions)


@pytest.fixture(scope="module")
def kit(tmp_path_factory):
    """A 22-back series: white shirt, black numbers in NUMBER_BOX. Returns
    the absolute %-pattern."""
    folder = tmp_path_factory.mktemp("kit")
    font = ImageFont.truetype(SN.resolve_font("Anton")[0], 200)
    x0, y0, x1, y1 = (int(v * 512) for v in NUMBER_BOX)
    for n in range(1, 23):
        im = Image.new("RGB", (512, 512), (240, 240, 240))
        d = ImageDraw.Draw(im)
        text = str(n)
        box = d.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        layer = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
        ImageDraw.Draw(layer).text((-box[0], -box[1]), text, font=font, fill=(10, 10, 10, 255))
        # every number fills the box's height; width as the digits need
        w = min(x1 - x0, int(tw * (y1 - y0) / th))
        layer = layer.resize((w, y1 - y0))
        im.paste(layer, ((x0 + x1 - w) // 2, y0), layer)
        im.save(folder / f"back_{n}.png")
    return str(folder / "back_%.png")


def _style(**season):
    kit = {k: season.pop(k) for k in list(season) if k in SN.KIT_DEFAULTS}
    return SN.normalise_style(dict({"enabled": True}, **season), kit)


def _ink_bbox(before, after):
    """Bounding box (pixels) of what lettering changed between two images."""
    a = np.asarray(before.convert("RGB"), dtype=int)
    b = np.asarray(after.convert("RGB"), dtype=int)
    ys, xs = np.nonzero(np.abs(a - b).sum(-1) > 30)
    return (xs.min(), ys.min(), xs.max(), ys.max()) if len(xs) else None


# ── configuration ────────────────────────────────────────────────────────
def test_style_defaults_and_bad_values():
    s = SN.normalise_style(None, None)
    assert s["enabled"] is False and s["font"] == SN.DEFAULT_FONT and s["color"] == "auto"
    s = SN.normalise_style({"enabled": 1, "size": "abc", "arch": 999, "text": "nope",
                            "placement": "custom", "area": [0.1, 0.2]},
                           {"color": "red", "outline": "00ff00", "outlineWidth": -3})
    assert s["enabled"] is True
    assert s["size"] == SN.SEASON_DEFAULTS["size"]       # unreadable: default
    assert s["arch"] == SN.LIMITS["arch"][1]               # clamped
    assert s["text"] == "surname"
    assert s["placement"] == "auto"                        # custom without a valid area
    assert s["color"] == "auto" and s["outline"] == "#00ff00" and s["outlineWidth"] == 0


def test_area_is_kept_inside_the_texture():
    s = _style(placement="custom", area=[0.9, -0.2, 0.5, 0.1])
    x, y, w, h = s["area"]
    assert (x, y, w, h) == (0.5, 0.0, 0.5, 0.1)


def test_fonts_resolve_and_fall_back(tmp_path):
    for name in SN.BUILTIN_FONTS:
        path, _variation, found = SN.resolve_font(name)
        assert found and os.path.isfile(path), name
    path, _, found = SN.resolve_font("fonts/missing.ttf", str(tmp_path))
    assert not found and os.path.isfile(path)            # the default instead
    (tmp_path / "fonts").mkdir()
    own = tmp_path / "fonts" / "club.ttf"
    own.write_bytes(open(SN.resolve_font("Anton")[0], "rb").read())
    assert SN.resolve_font("fonts/club.ttf", str(tmp_path)) == (str(own), None, True)
    assert SN.team_font_files(str(tmp_path)) == ["fonts/club.ttf"]


# ── the text ─────────────────────────────────────────────────────────────
@pytest.mark.parametrize("player,mode,case,expected", [
    ({"first_name": "Owen", "last_name": "Farrell"}, "surname", "upper", "FARRELL"),
    ({"first_name": "Owen", "last_name": "Farrell"}, "initial", "upper", "O. FARRELL"),
    ({"first_name": "Owen", "last_name": "Farrell"}, "full", "asis", "Owen Farrell"),
    ({"first_name": "Faf", "last_name": "de Klerk", "display_name": "F.de Klerk"}, "display", "asis",
     "F.de Klerk"),
    ({"display_name": "J.Smith"}, "surname", "upper", "SMITH"),          # no last name stored
    ({"display_name": "J. Smith"}, "initial", "upper", "SMITH"),
    ({"last_name": "Lienert-Brown", "shirt_name": "ALB"}, "surname", "upper", "ALB"),
    ({"last_name": "  du   Plessis "}, "surname", "upper", "DU PLESSIS"),
    (None, "surname", "upper", ""),
])
def test_shirt_text(player, mode, case, expected):
    assert SN.shirt_text(player, mode, case) == expected


def test_missing_glyphs_fall_back_to_plain_letters():
    path, variation, _ = SN.resolve_font("Graduate")
    out = SN.displayable("ÉLIÇE 中", path, variation)
    assert "中" not in out
    assert out.replace(" ", "").isalpha()


# ── the kit's numbers ────────────────────────────────────────────────────
def test_numbers_found_with_their_colour(kit):
    a = SN.analyse_numbers(SN.expand_back_paths(kit))
    box = a["box"]
    assert box is not None
    for got, want in zip(box, NUMBER_BOX):
        assert abs(got - want) < 0.03
    assert max(a["ink"]) < 60                         # black numbers…
    assert min(a["background"]) > 200                 # …on a white shirt


def test_auto_area_above_and_below_the_number(kit):
    a = SN.analyse_numbers(SN.expand_back_paths(kit))
    above = SN.name_area(_style(placement="above", gap=8), a)
    below = SN.name_area(_style(placement="below", gap=8), a)
    assert above[1] + above[3] <= NUMBER_BOX[1] + 0.01
    assert below[1] >= NUMBER_BOX[3] - 0.01
    centre = (NUMBER_BOX[0] + NUMBER_BOX[2]) / 2
    assert abs(above[0] + above[2] / 2 - centre) < 0.02
    custom = SN.name_area(_style(placement="custom", area=[0.1, 0.1, 0.3, 0.05]), a)
    assert custom == [0.1, 0.1, 0.3, 0.05]


def _with_sponsor(kit, folder, box):
    """The kit with a dark 'sponsor' block at `box` (fractions) on every back."""
    out = []
    for i, path in enumerate(SN.expand_back_paths(kit), 1):
        im = Image.open(path).convert("RGB")
        ImageDraw.Draw(im).rectangle([v * 512 for v in box], fill=(200, 20, 30))
        target = folder / f"back_{i}.png"
        im.save(target)
        out.append(str(target))
    return out


def test_auto_area_avoids_a_sponsor(kit, tmp_path):
    style = _style()                                    # placement "auto"
    clean = SN.name_area(style, SN.analyse_numbers(SN.expand_back_paths(kit)))
    assert clean[1] + clean[3] <= NUMBER_BOX[1] + 0.01  # free above: above
    # a sponsor right above the number: the name goes below it
    (tmp_path / "a").mkdir()
    busy = SN.analyse_numbers(_with_sponsor(kit, tmp_path / "a", (0.2, 0.30, 0.8, 0.38)))
    area = SN.name_area(style, busy)
    assert area[1] >= NUMBER_BOX[3] - 0.01
    # a sponsor below too, with a little room left above: squeezed in above
    (tmp_path / "b").mkdir()
    paths = _with_sponsor(kit, tmp_path / "b", (0.2, 0.30, 0.8, 0.33))
    for p in paths:
        im = Image.open(p)
        ImageDraw.Draw(im).rectangle([0.2 * 512, 0.72 * 512, 0.8 * 512, 0.9 * 512], fill=(0, 90, 40))
        im.save(p)
    area = SN.name_area(style, SN.analyse_numbers(paths))
    assert 0.33 - 0.005 <= area[1] and area[1] + area[3] <= NUMBER_BOX[1]
    assert area[3] < style["size"] * 1.5 / 512          # made smaller to fit


# ── lettering ────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", ["NTAMACK", "LIENERT-BROWN-VAN-DER-WESTHUIZEN"])
@pytest.mark.parametrize("arch", [0, 30, -30])
def test_name_stays_inside_its_area(kit, name, arch):
    style = _style(placement="custom", area=[0.25, 0.2, 0.5, 0.1], arch=arch,
                   outline="#ff0000", outlineWidth=2)
    path, variation, _ = SN.resolve_font(style["font"])
    printer = SN.BackPrinter(style, path, SN.expand_back_paths(kit), variation)
    plain = printer.render(9, "")
    lettered = printer.render(9, name)
    box = _ink_bbox(plain, lettered)
    assert box is not None
    x, y, w, h = (v * 512 for v in style["area"])
    tolerance = 2
    assert box[0] >= x - tolerance and box[2] <= x + w + tolerance
    assert box[1] >= y - tolerance and box[3] <= y + h + tolerance


def test_auto_colour_matches_the_numbers(kit):
    style = _style()
    path, variation, _ = SN.resolve_font(style["font"])
    printer = SN.BackPrinter(style, path, SN.expand_back_paths(kit), variation)
    assert max(printer.color) < 60
    img = np.asarray(printer.render(0, "WILKINSON").convert("RGB"), dtype=int)
    x, y, w, h = (int(v * 512) for v in printer.area)
    assert img[y:y + h, x:x + w].min() < 60           # dark letters are there


def test_fixed_colour_and_missing_texture(kit, tmp_path):
    style = _style(color="#c8102e")
    path, variation, _ = SN.resolve_font(style["font"])
    printer = SN.BackPrinter(style, path, SN.expand_back_paths(kit), variation)
    assert printer.color == (0xc8, 0x10, 0x2e)
    missing = SN.BackPrinter(style, path, SN.expand_back_paths(str(tmp_path / "x_%.png")), variation)
    assert missing.render(3, "SMITH") is None
    assert missing.analysis["box"] is None             # nothing to analyse: no crash


# ── match files ──────────────────────────────────────────────────────────
def test_backend_printer_letters_each_back(kit):
    from backend.game_files_processor import shirt_name_printer
    style = _style()
    path, variation, _ = SN.resolve_font(style["font"])
    team = {"name": "X", "shirt_names": {"style": style, "font_path": path,
                                         "font_variation": variation,
                                         "names": ["ONE", "", "THREE"]}}
    printer, names = shirt_name_printer(team, kit)
    assert names == ["ONE", "", "THREE"]
    assert _ink_bbox(Image.open(kit.replace("%", "1")), printer.render(0, names[0])) is not None
    # no names, or a single .fsh back: nothing to letter
    assert shirt_name_printer({"name": "X"}, kit) == (None, [])
    assert shirt_name_printer(team, kit.replace("%", "1").replace(".png", ".fsh")) == (None, [])
    # a font that went missing: the bundled default, not a failed match
    broken = copy.deepcopy(team)
    broken["shirt_names"]["font_path"] = "/nowhere/font.ttf"
    assert shirt_name_printer(broken, kit)[0] is not None


def test_match_data_carries_the_names(ds):
    from app.match_data_builder import build_match_data
    from conftest import make_match_config
    md = build_match_data(ds, make_match_config(ds))
    assert "shirt_names" not in md["team_A"]           # off by default: match_data unchanged
    season = ds.teams["10002"]["2024"]
    season["shirtNames"] = {"enabled": True, "text": "initial", "font": "Oswald"}
    md = build_match_data(ds, make_match_config(ds))
    spec = md["team_A"]["shirt_names"]
    players = md["team_A"]["players"]
    assert len(spec["names"]) == len(players)
    assert spec["style"]["font"] == "Oswald" and os.path.isfile(spec["font_path"])
    assert spec["font_variation"] == "Bold"
    ids = [p for p in ds.get_lineup("10002", "2024")["players_id"] if p][:22]
    first = ds.get_players(ids[:1], "2024")[int(ids[0])]
    assert spec["names"][0] == SN.shirt_text(first, "initial", "upper")
    assert "shirt_names" not in md["team_B"]


# ── team editor helpers ──────────────────────────────────────────────────
def test_team_ops_store_only_what_is_set():
    info = {"kits": {"home": {}, "away": {}}}
    T.set_shirt_names(info, "enabled", True)
    T.set_shirt_names(info, "font", "Anton")
    assert info["shirtNames"] == {"enabled": True, "font": "Anton"}
    T.set_shirt_name_area(info, [0.123456, 0.2, 0.5, 0.08])
    assert info["shirtNames"]["placement"] == "custom"
    assert info["shirtNames"]["area"] == [0.1235, 0.2, 0.5, 0.08]
    T.set_shirt_name_area(info, None)
    assert "area" not in info["shirtNames"] and "placement" not in info["shirtNames"]   # auto
    T.set_kit_shirt_name(info["kits"]["home"], "color", "#ffffff")
    assert info["kits"]["home"]["shirtName"] == {"color": "#ffffff"}
    T.set_kit_shirt_name(info["kits"]["home"], "color", "")
    assert "shirtName" not in info["kits"]["home"]
    for key in ("enabled", "font"):
        T.set_shirt_names(info, key, None)
    assert "shirtNames" not in info


def test_copy_shirt_names_to_other_seasons():
    seasons = {
        "2024": {"shirtNames": {"enabled": True, "font": "Anton"},
                 "kits": {"home": {"shirtName": {"color": "#000000"}}, "away": {}}},
        "2025": {"kits": {"home": {}, "third": {"shirtName": {"color": "#ff0000"}}}},
        "2026": {"shirtNames": {"enabled": True, "font": "Anton"},
                 "kits": {"home": {"shirtName": {"color": "#000000"}}}},
    }
    assert T.copy_shirt_names(seasons, "2024") == 1          # 2026 already the same
    assert seasons["2025"]["shirtNames"] == {"enabled": True, "font": "Anton"}
    assert seasons["2025"]["kits"]["home"]["shirtName"] == {"color": "#000000"}
    assert seasons["2025"]["kits"]["third"]["shirtName"] == {"color": "#ff0000"}   # no such kit in 2024
    seasons["2025"]["shirtNames"]["font"] = "Teko"
    assert seasons["2024"]["shirtNames"]["font"] == "Anton"   # a copy, not shared


def test_overlap_with_a_logo_is_reported(kit, tmp_path):
    clean = SN.analyse_numbers(SN.expand_back_paths(kit))
    assert SN.area_overlap([0.2, 0.30, 0.6, 0.08], clean) == 0.0
    busy = SN.analyse_numbers(_with_sponsor(kit, tmp_path, (0.2, 0.30, 0.8, 0.38)))
    assert SN.area_overlap([0.2, 0.30, 0.6, 0.08], busy) > 0.9
