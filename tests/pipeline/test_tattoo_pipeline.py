"""A player's tattoos (the tattoo editor's flattened picture, first in skin_overlay) reach the skin texture the
game reads, under the other layers, and the adjusted skin replaces the stock tone."""
import json
import os
import shutil

import pytest
from PIL import Image

from app.match_data_builder import build_match_data
from app.state import DataStore
from app.tattoos import render as R
from app.tattoos import store as S
from backend import game_specific_variables as gsv
from backend import mod_utils
from backend.start_match import start_match
from conftest import FIXTURE_DATA, make_match_config, point_config

pytestmark = pytest.mark.slow


def _stock(_entry):
    return Image.new("RGBA", R.ATLAS, (200, 160, 130, 255))


def test_tattoos_and_adjusted_skin_reach_the_game(tmp_path, monkeypatch, game_dir):
    monkeypatch.setattr(mod_utils, "ensure_wine_d3d8_native_override", lambda *a, **k: None)
    monkeypatch.setattr(mod_utils, "disable_wine_virtual_desktop", lambda *a, **k: None)
    os.makedirs(os.path.join(game_dir, "Data"), exist_ok=True)
    data = str(tmp_path / "data")
    shutil.copytree(FIXTURE_DATA, data)
    point_config(monkeypatch, data_dir=data)

    # a blackout band round the right forearm, on a darker skin
    design = R.clean_design({"layers": [{"motif": "gen:solid_band", "limb": "arm", "side": "a", "wrap": True,
                                         "y": 90, "h": 30, "opacity": 1, "soft": 0}]})
    base = _stock("")
    tattoo = S.write_tattoos(data, "1", design, base, S.Library(data))
    skin = S.write_skin(data, "1", "", {"light": -.5}, base)
    path = os.path.join(data, "players", "players.json")
    players = json.load(open(path, encoding="utf-8"))
    for rec in players.values():
        for st in (rec.get("stats") or {}).values():
            st["gloves"] = ""
            S.put_on(st, tattoo, skin)
    json.dump(players, open(path, "w", encoding="utf-8"))

    ds = DataStore(DataStore.read_files())
    md = build_match_data(ds, make_match_config(ds))
    assert md["team_A"]["players"][0]["skin_overlay"][0].endswith(tattoo.split("/")[-1])
    assert start_match(md, start_R08=False, progress_callback=lambda *a: None) is None

    out = os.path.join(game_dir, gsv.game_filenames["skins"])
    entry = mod_utils.extract_asset_from_fsh_file(out, 8).convert("RGB")      # team A's first player
    w, h = entry.size
    sx, sy = w / 512, h / 256
    ink = entry.getpixel((int(64 * sx), int(90 * sy)))
    bare = entry.getpixel((int(64 * sx), int(40 * sy)))
    other_arm = entry.getpixel((int((256 + 64) * sx), int(90 * sy)))
    assert sum(ink) < 150, ink                         # the band is there, dark
    assert sum(bare) > sum(ink) + 100 and sum(other_arm) > sum(ink) + 100
    assert bare[0] < 160                               # the darker (adjusted) skin, not the stock tone
