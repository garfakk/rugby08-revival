"""The stadium editor on the fixture pack plus one mod stadium: picks are
tried, SAVE writes them in the stadium's JSON (what a match there then
wears), RESET goes back to the stock sets. A scene that can't be read is
said in the 3D view instead of failing."""
import json
import os
import shutil
import time

import pytest

from conftest import FIXTURE_DATA, point_config
from shared.config import config

pytestmark = pytest.mark.qt


def _wait(qapp, predicate, timeout=30.0):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise TimeoutError("UI did not get there in time")
        qapp.processEvents()
        time.sleep(0.005)


def _settle(qapp, n=20):
    for _ in range(n):
        qapp.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    root = tmp_path_factory.mktemp("sted")
    data = str(root / "data")
    shutil.copytree(FIXTURE_DATA, data)
    folder = os.path.join(data, "stadiums", "Test Ground")
    os.makedirs(folder)
    with open(os.path.join(folder, "test_ground.json"), "w") as fh:
        json.dump({"test_ground": {"name": "Test Ground", "country": "england", "game_id": 14,
                                   "scenes": {"day": "test_ground.day.big"}}}, fh)
    with open(os.path.join(folder, "test_ground.day.big"), "wb") as fh:
        fh.write(b"not a scene pack")
    mp = pytest.MonkeyPatch()
    point_config(mp, data_dir=data)
    from main import MainWindow
    w = MainWindow()
    _wait(qapp, lambda: w._boot_done)
    yield w
    w._menus_ready = True
    w.close()
    w.deleteLater()
    qapp.processEvents()
    mp.undo()


def test_pick_save_and_reset(window, qapp):
    from app import dressing
    window.show_stadium_editor()
    ed = window.screen_stadium_editor
    _wait(qapp, lambda: window.screens.currentWidget() is ed)
    _settle(qapp)
    sid = "test_ground"
    assert [r["id"] for r in ed.list_rows()] == [sid]          # the mod's own stadiums only
    ed.request_open(sid)
    _settle(qapp, 40)
    assert ed.record_id == sid and ed.d == {"pads": "", "posts": "", "ads": "", "pitches": [], "logos": None,
                                                   "stripes": {}, "environments": ["day"]}
    assert ed.view._message                              # no game here: said, not crashed
    choices = ed._choices("pads", "")
    other = next(o["ref"] for o in choices if o["ref"])
    ed._pick("pads", other)
    _settle(qapp)
    assert ed.session.is_dirty() and ed.d["pads"] == other
    ed.undo()
    _settle(qapp)
    assert ed.d["pads"] == ""
    ed.redo()
    assert ed.save()
    path = dressing.stadium_json_path(sid)
    with open(path) as fh:
        assert json.load(fh)[sid]["dressing"] == {"pads": other}
    info = window.data.stadiums[sid]
    assert dressing.stadium_default(info, "pads") == other         # a match there wears it
    assert [r for r in ed.list_rows() if r["id"] == sid][0]["tag"] == "EDITED"
    ed._reset()
    assert ed.save()
    with open(path) as fh:
        assert "dressing" not in json.load(fh)[sid]
    assert dressing.stadium_default(info, "pads") == dressing.own_default(info, "pads")


def test_competition_look_sets_all_three(window, qapp):
    from app import dressing
    ed = window.screen_stadium_editor
    window.show_stadium_editor()
    _settle(qapp)
    ed.request_open("test_ground")
    _settle(qapp)
    looks = dressing.competition_looks(window.data)
    if not looks:
        pytest.skip("no competition with its own dressing in the fixture pack")
    ed._pick_look("0")
    _settle(qapp)
    for kind, ref in looks[0]["refs"].items():
        assert ed.d[kind] == ref
    ed.session.revert()


def test_pitches_ticked_are_saved_and_limit_quick_match(window, qapp):
    from backend import pitches
    ed = window.screen_stadium_editor
    window.show_stadium_editor()
    _settle(qapp)
    ed.request_open("test_ground")
    _settle(qapp)
    ed.f_pitches.toggled.emit("Reg2_08_snow_n", True)
    ed.f_pitches.toggled.emit("Reg2_08_best_d", True)
    _settle(qapp)
    assert ed.d["pitches"] == ["Reg2_08_best_d", "Reg2_08_snow_n"]            # the game's order
    assert ed.pitch_count.text() == "2 of %d allowed" % len(pitches.NAMES)
    assert ed.save()
    from app import dressing
    with open(dressing.stadium_json_path("test_ground")) as fh:
        assert json.load(fh)["test_ground"]["pitches"] == ["Reg2_08_best_d", "Reg2_08_snow_n"]
    # quick match at that ground offers those pitches and "default"
    setup = window.screen_match_setup.setup_screen
    setup.cfg.stadium = {"stadium_id": 14, "data": window.data.stadiums["test_ground"]}
    setup._sync_pitch_choices()
    assert sorted(v[0] for v in setup.pitch_row._values) == ["Reg2_08_best_d", "Reg2_08_snow_n", "default"]
    setup.pitch_row.set_index([v[0] for v in setup.pitch_row._values].index("Reg2_08_snow_n"))
    setup.pitch_row.changed.emit()
    assert setup.cfg.pitch_texture == "Reg2_08_snow_n"
    setup.cfg.stadium = {"stadium_id": 14, "data": {}}
    setup._sync_pitch_choices()                       # a ground without a list: all of the game's
    assert len(setup.pitch_row._values) == 1 + len(pitches.NAMES)
    assert setup.cfg.pitch_texture == "Reg2_08_snow_n"
    ed._reset()
    assert ed.d["pitches"] == [] and ed.save()
    with open(dressing.stadium_json_path("test_ground")) as fh:
        assert "pitches" not in json.load(fh)["test_ground"]


def test_logo_layout_is_saved_and_reset(window, qapp):
    from app import dressing
    ed = window.screen_stadium_editor
    window.show_stadium_editor()
    _settle(qapp)
    ed.request_open("test_ground")
    _settle(qapp)
    assert ed.d["logos"] is None                       # the game's own
    ed._add_logo()
    _settle(qapp)
    ed._set_logo("x", "12")
    _settle(qapp)
    assert ed.d["logos"] and ed.d["logos"][-1]["x"] == 12.0
    assert ed.save()
    with open(dressing.stadium_json_path("test_ground")) as fh:
        assert json.load(fh)["test_ground"]["pitch_logos"] == ed.d["logos"]
    ed._stock_logos()
    assert ed.d["logos"] is None and ed.save()
    with open(dressing.stadium_json_path("test_ground")) as fh:
        assert "pitch_logos" not in json.load(fh)["test_ground"]


def test_logo_types_are_main_and_side(window, qapp):
    from backend import pitch_logos
    ed = window.screen_stadium_editor
    window.show_stadium_editor()
    _settle(qapp)
    ed.request_open("test_ground")
    _settle(qapp)
    ed._edit_logos("test", lambda ls: ls.extend([
        {"kind": "centre", "x": 0.0, "z": 0.0, "size": 14.0, "angle": 0.0},
        {"kind": "side_a", "x": 0.0, "z": 28.0, "size": 8.0, "angle": 10.0}]))
    ed._logo_index = 0
    ed._set_logo("kind", "side")                    # main -> side: the half the others lack
    assert ed.d["logos"][0]["kind"] == "side_b"
    ed._set_logo("kind", "centre")
    assert ed.d["logos"][0]["kind"] == "centre"
    assert [ed._logo_label(i) for i in range(2)] == ["1. Main logo", "2. Side logo"]
    ed._logo_index = 1
    ed._add_logo()                                  # a side logo again: the other half
    assert ed.d["logos"][-1]["kind"] == "side_b"
    assert pitch_logos.TYPES == ("centre", "side")
    ed.undo()
    ed.undo()
    ed.undo()
    ed.undo()


def test_stripes_are_per_environment_and_saved(window, qapp, monkeypatch):
    from app import dressing
    from backend import pitch_stripes
    ed = window.screen_stadium_editor
    window.show_stadium_editor()
    _settle(qapp)
    ed.request_open("test_ground")
    _settle(qapp)
    monkeypatch.setattr(ed, "_pack_stripes", lambda: {"opacity": 35, "brightness": 110})
    ed._env = "day"
    assert ed._stripes() == {"opacity": 35, "brightness": 110}      # the pack's own
    ed._set_stripe("opacity", "60")
    _settle(qapp)
    assert ed.d["stripes"] == {"day": {"opacity": 60, "brightness": 110}}
    assert ed.save()
    with open(dressing.stadium_json_path("test_ground")) as fh:
        assert json.load(fh)["test_ground"]["stripes"] == {"day": {"opacity": 60, "brightness": 110}}
    ed._env = "night"
    assert ed._stripes() == {"opacity": 35, "brightness": 110}      # another environment keeps its own
    ed._env = "day"
    ed._stock_stripes()
    assert ed.d["stripes"] == {} and ed.save()
    with open(dressing.stadium_json_path("test_ground")) as fh:
        assert "stripes" not in json.load(fh)["test_ground"]
    assert pitch_stripes.clean({"opacity": 500, "brightness": "x"}) == {"opacity": 100}


def test_environments_are_chosen_and_saved(window, qapp):
    from app import dressing
    ed = window.screen_stadium_editor
    window.show_stadium_editor()
    _settle(qapp)
    ed.request_open("test_ground")
    _settle(qapp)
    assert [k for k, _l in ed.f_envs.items] == ["day", "overcast", "night"]     # the stadium's and its slot's
    assert ed.f_envs.on == {"day"} and ed.d["environments"] == ["day"]
    ed._toggle_env("day", False)                                  # the last one stays
    assert ed.d["environments"] == ["day"] and ed.f_envs.on == {"day"}
    ed._toggle_env("night", True)
    _settle(qapp)
    assert ed.d["environments"] == ["day", "night"] and ed.save()
    with open(dressing.stadium_json_path("test_ground")) as fh:
        assert json.load(fh)["test_ground"]["environments"] == ["day", "night"]
    assert window.data.stadiums["test_ground"]["environments"] == ["day", "night"]
    assert [r for r in ed.list_rows() if r["id"] == "test_ground"][0]["tag"] == "EDITED"
    ed._reset()                                                   # back to the scenes it has
    assert ed.d["environments"] == ["day"] and ed.save()
    with open(dressing.stadium_json_path("test_ground")) as fh:
        assert "environments" not in json.load(fh)["test_ground"]
    assert window.data.stadiums["test_ground"]["environments"] == ["day"]


def test_a_roofed_stadiums_closed_environment_is_named_closed(window, qapp):
    from app.tournament import weather
    millennium = {"game_id": 32, "environments": ["day", "cold"]}
    assert [weather.env_label(millennium, e) for e in ("day", "cold")] == ["day", "closed"]
    assert weather.env_label({"game_id": 14}, "cold") == "cold"
    ed = window.screen_stadium_editor
    window.show_stadium_editor()
    _settle(qapp)
    ed.request_open("test_ground")
    _settle(qapp)
    assert ed._env_label("night") == "night"
