"""Tattoo editor backend (app/tattoos): motifs, flattening, picture import, skin adjust, what the player wears."""
import io
import json
import os

import pytest
from PIL import Image, ImageDraw

from app.tattoos import generate as G
from app.tattoos import motifs as M
from app.tattoos import render as R
from app.tattoos import store as S


def _stock(_entry):
    """A stand-in for the game's stock skin: a warm gradient with some texture."""
    im = Image.new("RGBA", R.ATLAS, (200, 160, 130, 255))
    d = ImageDraw.Draw(im)
    for y in range(0, 256, 8):
        d.line([(0, y), (511, y)], fill=(190, 150, 122, 255))
    return im


# ── motifs ───────────────────────────────────────────────────────────────────
def test_every_motif_draws_ink_at_any_size():
    for key, m in M.REG.items():
        for w in (24, 90):
            h = max(4, round(w / m.aspect))
            mask = M.draw_mask(key, w, h, None, seed=2)
            assert mask.size == (w, h), key
            assert mask.getextrema()[1] > 100, f"{key} drew nothing at {w}px"


def test_same_seed_same_ink_other_seed_other_ink():
    a = M.draw_mask("gen:tribal_shape", 60, 60, None, 5).tobytes()
    assert a == M.draw_mask("gen:tribal_shape", 60, 60, None, 5).tobytes()
    assert a != M.draw_mask("gen:tribal_shape", 60, 60, None, 6).tobytes()


def test_params_are_clamped_and_unknown_ones_dropped():
    p = M.clean_params(M.get("gen:rope"), {"turns": 999, "strands": "9", "bogus": 1})
    assert p == {"turns": 12, "thick": 1.0, "strands": "2"}


def test_lettering_fonts_ship_with_the_mod():
    for name in M.TEXT_FONTS.values():
        assert (M.FONTS / name).is_file(), name


def test_fully_inked_category_has_presets_for_arms_and_legs():
    fills = [m for m in M.REG.values() if m.cat == "Fully inked"]
    assert len(fills) >= 15
    limbs = {m.place["limb"] for m in fills if m.place}
    assert limbs == {"arm", "leg"}
    for m in fills:
        if m.place:
            assert 0 <= m.place["y0"] < m.place["y1"] <= 256, m.id


@pytest.mark.parametrize("mid", ["gen:full_sleeve", "gen:full_leg", "gen:solid_band"])
def test_a_blackout_sleeve_inks_its_whole_area(mid):
    m = M.get(mid)
    mask = M.draw_mask(mid, 91, 120, None, 1)
    ink = sum(1 for v in mask.getdata() if v > 128) / (91 * 120)
    assert ink > .97, ink


def test_a_wrapped_band_is_seamless_round_the_limb():
    """Left and right edges of a band meet on the body: the columns must match."""
    for mid in ("gen:half_sleeve", "gen:knee_band", "gen:blackout_polynesian", "gen:flame_sleeve"):
        d = R.clean_design({"layers": [{"motif": mid, "limb": "arm", "wrap": True, "y": 80, "h": 60, "side": "a"}]})
        tile = R.render_tile(d["layers"], "arm")
        a = tile.getchannel("A")
        left = [a.getpixel((0, y)) for y in range(256)]
        right = [a.getpixel((127, y)) for y in range(256)]
        assert sum(abs(x - y) for x, y in zip(left, right)) / 256 < 40, mid


def test_cut_out_patterns_leave_skin_showing():
    full = M.draw_mask("gen:solid_band", 91, 60, None, 1)
    cut = M.draw_mask("gen:blackout_stars", 91, 60, None, 1)
    ink = lambda m: sum(1 for v in m.getdata() if v > 128)
    assert ink(cut) < ink(full) * .92


def test_ready_made_designs_stay_on_their_limb():
    for style in G.STYLES:
        for limb in ("arm", "leg"):
            for L in G.generate(style, 3, limb):
                assert L["limb"] == limb
                assert -10 <= L["y"] <= 266, (style, limb, L["y"])


# ── design / flattening ──────────────────────────────────────────────────────
def test_design_is_cleaned():
    d = R.clean_design({"layers": [{"motif": "bank:fern", "x": 9999, "color": "red", "limb": "tail"},
                                   {"motif": "bank:nope"}]})
    assert len(d["layers"]) == 1
    L = d["layers"][0]
    assert L["limb"] == "arm" and L["color"] == R.INK and L["x"] <= 128 + 64


def test_overlay_is_the_skin_atlas_with_ink_only_where_tattooed():
    d = R.clean_design({"layers": [{"motif": "bank:anchor", "limb": "arm", "side": "a", "x": 64, "y": 90, "w": 30}]})
    over = R.render_overlay(d, _stock(""))
    assert over.size == (512, 256) and over.mode == "RGBA"
    box = over.getbbox()
    assert box and box[2] <= 128, box                 # right arm tile only
    assert over.crop((256, 0, 512, 256)).getbbox() is None


def test_both_sides_paint_both_tiles():
    d = R.clean_design({"layers": [{"motif": "bank:anchor", "limb": "leg", "side": "both", "y": 180}]})
    over = R.render_overlay(d)
    assert over.crop((128, 0, 256, 256)).getbbox() and over.crop((384, 0, 512, 256)).getbbox()
    assert over.crop((0, 0, 128, 256)).getbbox() is None


def test_real_ink_keeps_its_colour_and_the_skin_texture():
    d = R.clean_design({"layers": [{"motif": "gen:solid_band", "limb": "arm", "side": "a", "wrap": True, "y": 100,
                                    "h": 60, "opacity": 1, "soft": 0, "color": "#1c2433"}]})
    over = R.render_overlay(d, _stock(""))
    px = [over.getpixel((64, y))[:3] for y in range(80, 120)]
    assert all(r < 60 and g < 60 and b < 80 for r, g, b in px)      # dark blue-black, not brown
    assert len(set(px)) > 1                                           # the skin's lines show through


def test_moving_a_layer_reuses_its_drawing():
    R._IMG_CACHE.clear()
    L = R.clean_layer({"motif": "gen:mandala", "x": 40, "y": 90})
    R.render_tile([L], "arm")
    n = len(R._IMG_CACHE)
    R.render_tile([dict(L, x=70, y=120)], "arm")
    assert len(R._IMG_CACHE) == n


# ── skin adjust ──────────────────────────────────────────────────────────────
def test_skin_adjust_zero_is_identity_and_each_slider_moves_its_channel():
    base = _stock("")
    assert R.adjust_skin(base, {}) is base
    mean = lambda im, c: sum(im.getchannel(c).getdata()) / (512 * 256)
    lighter = R.adjust_skin(base, {"light": .5})
    assert mean(lighter, "R") > mean(base, "R")
    warmer = R.adjust_skin(base, {"warm": 1})
    assert mean(warmer, "R") > mean(base, "R") and mean(warmer, "B") < mean(base, "B")
    redder = R.adjust_skin(base, {"red": 1})
    assert mean(redder, "R") - mean(redder, "G") > mean(base, "R") - mean(base, "G")
    grey = R.adjust_skin(base, {"sat": -1})
    r, g, b = grey.getpixel((10, 10))[:3]
    assert abs(r - g) <= 1 and abs(g - b) <= 1
    flat = R.adjust_skin(base, {"contrast": -1})
    assert flat.getchannel("R").getextrema()[1] - flat.getchannel("R").getextrema()[0] <= \
        base.getchannel("R").getextrema()[1] - base.getchannel("R").getextrema()[0]


# ── files and the player ─────────────────────────────────────────────────────
@pytest.fixture
def mod(data_dir):
    return data_dir


def _player():
    return {"stats": {"2023": {"skin_tone": "light", "skin_overlay": ["players/baselayers/x.png"]},
                      "2024": {"skin_tone": "light", "skin_overlay": []}}}


def test_save_writes_the_flattened_tattoos_under_everything_else(mod):
    lib = S.Library(mod)
    st = _player()["stats"]["2023"]
    d = R.clean_design({"layers": [{"motif": "gen:full_sleeve", "limb": "arm", "wrap": True, "y": 64, "h": 120}]})
    rel = S.write_tattoos(mod, "123", d, S.source_image(st, mod, "", _stock), lib)
    assert rel.startswith("players/tattoos/123_") and rel.endswith(".png")
    assert Image.open(os.path.join(mod, rel)).size == (512, 256)
    S.put_on(st, rel)
    assert st["skin_overlay"] == [rel, "players/baselayers/x.png"]
    # editing again replaces the tattoo layer, the rest stays in order
    d["layers"][0]["opacity"] = .5
    rel2 = S.write_tattoos(mod, "123", d, S.source_image(st, mod, "", _stock), lib)
    assert rel2 != rel
    S.put_on(st, rel2)
    assert st["skin_overlay"] == [rel2, "players/baselayers/x.png"]
    S.put_on(st, "")
    assert st["skin_overlay"] == ["players/baselayers/x.png"]


def test_an_empty_design_writes_nothing(mod):
    assert S.write_tattoos(mod, "123", R.clean_design({}), _stock(""), S.Library(mod)) == ""


def test_design_round_trip(mod):
    lib = S.Library(mod)
    d = R.clean_design({"layers": [{"motif": "gen:name_script", "params": {"text": "Lou"}, "limb": "leg", "y": 120},
                                   {"motif": "bank:fern", "side": "b"}]})
    st = {"skin_tone": "dark"}
    S.put_on(st, S.write_tattoos(mod, "77", d, _stock(""), lib))
    back = S.load_design(st, mod, lib)
    assert back["layers"] == d["layers"]


def test_a_tattoo_picture_made_elsewhere_opens_as_one_layer_per_limb(mod):
    os.makedirs(os.path.join(mod, "players", "tattoos"), exist_ok=True)
    pic = Image.new("RGBA", (512, 256), (0, 0, 0, 0))
    ImageDraw.Draw(pic).rectangle((10, 60, 100, 90), fill=(20, 20, 30, 255))
    pic.save(os.path.join(mod, "players", "tattoos", "999.png"))
    lib = S.Library(mod)
    st = {"skin_overlay": ["players/tattoos/999.png"]}
    d = S.load_design(st, mod, lib)
    assert [L["motif"] for L in d["layers"]] == [R.ATLAS_MOTIF, R.ATLAS_MOTIF]
    over = R.render_overlay(d, None, lib)
    assert over.getpixel((50, 75))[3] > 200 and over.getpixel((300, 75))[3] == 0     # kept where it was


def test_skin_adjust_is_made_from_the_source_never_twice(mod):
    st = {"skin_tone": "light", "skin": ""}
    src = S.skin_source(st, mod)
    assert src == {"skin": "", "adjust": R.clean_adjust({}), "rel": ""}
    base = S.source_image(st, mod, src["skin"], _stock)
    rel = S.write_skin(mod, "55", "", {"light": -.4}, base)
    st["skin"] = rel
    again = S.skin_source(st, mod)
    assert again["skin"] == "" and again["adjust"]["light"] == -.4 and again["rel"] == rel
    # reopened: the source is still the stock tone, not the adjusted picture
    src2 = S.source_image(st, mod, again["skin"], _stock)
    assert src2.tobytes() == base.tobytes()
    assert S.write_skin(mod, "55", "", {}, base) == ""          # back to 0: no file, the source again


def test_skin_adjust_of_a_custom_skin_keeps_its_path(mod):
    os.makedirs(os.path.join(mod, "players", "skins"), exist_ok=True)
    Image.new("RGB", (512, 256), (120, 80, 60)).save(os.path.join(mod, "players", "skins", "mine.png"))
    st = {"skin": "players/skins/mine.png"}
    base = S.source_image(st, mod, "players/skins/mine.png", _stock)
    assert base.getpixel((5, 5))[:3] == (120, 80, 60)
    rel = S.write_skin(mod, "55", "players/skins/mine.png", {"warm": .5}, base)
    assert S.skin_source({"skin": rel}, mod)["skin"] == "players/skins/mine.png"


def test_cleanup_keeps_what_is_used_and_never_other_files(mod):
    lib = S.Library(mod)
    d = R.clean_design({"layers": [{"motif": "bank:anchor"}]})
    old = S.write_tattoos(mod, "12", d, _stock(""), lib)
    d["layers"][0]["y"] = 40
    new = S.write_tattoos(mod, "12", d, _stock(""), lib)
    other = S.write_tattoos(mod, "120", d, _stock(""), lib)       # another player whose id starts the same
    legacy = os.path.join(mod, "players", "tattoos", "12.png")
    Image.new("RGBA", (512, 256)).save(legacy)
    gone = S.cleanup(mod, "12", S.referenced([{"stats": {"2024": {"skin_overlay": [new]}}}]))
    assert old in gone and old[:-4] + ".json" in gone
    for rel in (new, other):
        assert os.path.isfile(os.path.join(mod, rel))
    assert os.path.isfile(os.path.join(mod, new[:-4] + ".json"))
    assert os.path.isfile(legacy)


def test_files_go_to_the_users_own_data_not_the_pack(mod, monkeypatch, tmp_path):
    """With the user's edits on, a tattoo lands in user_data/mod_data (kept across releases)."""
    from app import game_data as Gd
    from shared import mod_overlay
    from shared.app_paths import user_data_directory
    monkeypatch.setattr(Gd, "_edits", object())
    monkeypatch.setattr(Gd, "_into_pack", False)
    rel = S.write_tattoos(mod, "8", R.clean_design({"layers": [{"motif": "bank:anchor"}]}), _stock(""), S.Library(mod))
    kept = os.path.join(mod_overlay.overlay_directory(user_data_directory()), *rel.split("/"))
    assert os.path.isfile(kept)
    S.cleanup(mod, "8", set())
    assert not os.path.isfile(kept) and not os.path.isfile(os.path.join(mod, rel))


# ── picture import ───────────────────────────────────────────────────────────
def _png(img, fmt="PNG"):
    buf = io.BytesIO()
    img.save(buf, fmt)
    return buf.getvalue()


def test_import_a_dark_drawing_on_white(mod):
    pic = Image.new("RGB", (200, 100), "white")
    ImageDraw.Draw(pic).ellipse((50, 20, 110, 80), fill="black")
    lib = S.Library(mod)
    item = lib.add(_png(pic, "JPEG"), "Dot")
    iid = item["id"][5:]
    info = lib.item(iid)
    assert info["mode"] == "ink" and .8 < info["aspect"] < 1.25          # cropped to the drawing
    m, rgb = lib.picture(iid, 40, 40)
    assert rgb is None and m.getpixel((20, 20)) > 200 and m.getpixel((1, 1)) < 60
    assert [i["name"] for i in lib.items()] == ["Dot"]
    L = R.clean_layer({"motif": item["id"]}, lib)
    assert L["name"] == "Dot"
    lib.remove(iid)
    assert lib.items() == []
    # off the list, but a tattoo made with it still opens with it
    assert lib.item(iid)["name"] == "Dot"
    assert R.clean_layer({"motif": item["id"]}, lib)["name"] == "Dot"
    assert lib.add(_png(pic, "JPEG"), "Dot")["id"] == item["id"] and len(lib.items()) == 1


def test_import_light_on_dark_and_transparent_and_colour(mod):
    lib = S.Library(mod)
    dark = Image.new("RGB", (100, 100), "black")
    ImageDraw.Draw(dark).rectangle((30, 30, 70, 70), fill="white")
    iid = lib.add(_png(dark), "Neg", light_on_dark=True)["id"][5:]
    m, _ = lib.picture(iid, 20, 20)
    assert m.getpixel((10, 10)) > 200
    clear = Image.new("RGBA", (100, 50), (0, 0, 0, 0))
    ImageDraw.Draw(clear).rectangle((0, 0, 99, 49), fill=(200, 20, 20, 255))
    item = lib.add(_png(clear), "Red", mode="colour")
    m, rgb = lib.picture(item["id"][5:], 20, 10)
    assert rgb is not None and rgb.getpixel((10, 5))[0] > 150
    d = R.clean_design({"layers": [{"motif": item["id"], "w": 40, "opacity": 1, "soft": 0, "ink": "opaque"}]}, lib)
    over = R.render_overlay(d, None, lib)
    r, g, b, a = over.getpixel((64, 128))
    assert a > 200 and r > 150 and g < 80                           # its own colour, not the ink colour


def test_import_rejects_a_blank_picture(mod):
    with pytest.raises(ValueError):
        S.Library(mod).add(_png(Image.new("RGB", (50, 50), "white")), "Blank")
