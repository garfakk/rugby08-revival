"""The real main window, booted offscreen on a writable copy of the fixture
pack: every screen opens, and the main editor / match flows work through the
UI objects themselves."""
import copy
import json
import os
import shutil
import time

import pytest

from conftest import FIXTURE_DATA, point_config
from shared.config import config

pytestmark = pytest.mark.qt


def _wait(qapp, predicate, timeout=60.0):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise TimeoutError("UI did not get there in time")
        qapp.processEvents()
        time.sleep(0.005)


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    data = str(tmp_path_factory.mktemp("ui") / "data")
    shutil.copytree(FIXTURE_DATA, data)
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


SCREENS = [
    ("show_main", "screen_main"),
    ("show_match_setup", "screen_match_setup"),
    ("show_game_modes", "screen_game_modes"),
    ("show_tools", "screen_tools"),
    ("show_user_edits", "screen_user_edits"),
    ("show_updates", "screen_updates"),
    ("show_team_editor", "screen_team_editor"),
    ("show_player_editor", "screen_player_editor"),
    ("show_challenge_editor", "screen_challenge_editor"),
    ("show_challenge_mode", "screen_challenge_mode"),
    ("show_tournament_hub", "screen_tournament_hub"),
    ("show_tournament_wizard", "screen_tournament_wizard"),
    ("show_roster_import", "screen_roster_import"),
    ("show_settings", "screen_settings"),
    ("show_about", "screen_about"),
]


@pytest.mark.parametrize("show,attr", SCREENS, ids=[s for s, _ in SCREENS])
def test_screen_opens(window, qapp, show, attr):
    getattr(window, show)()
    _wait(qapp, lambda: window.screens.currentWidget() is getattr(window, attr), 10)
    for _ in range(20):
        qapp.processEvents()
    assert getattr(window, attr).isVisible()
    window.show_main()


def test_window_resizes_without_crash(window, qapp):
    window.resize(1280, 720)
    qapp.processEvents()
    window.resize(1920, 1080)
    qapp.processEvents()


def test_match_setup_builds_match_data(window, qapp):
    from app.match_data_builder import build_match_data
    window.show_match_setup()
    qapp.processEvents()
    setup = window.screen_match_setup.setup_screen
    assert setup.cfg.home.team_id and setup.cfg.away.team_id
    if not setup.cfg.controllers:
        setup.cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}
    md = build_match_data(window.data, setup.cfg)
    assert md is not None
    assert len(md["team_A"]["players"]) == 22 and len(md["team_B"]["players"]) == 22


def test_match_setup_controllers(window, qapp):
    from app.match_data_builder import build_match_data
    window.show_match_setup()
    qapp.processEvents()
    setup = window.screen_match_setup.setup_screen
    assert {s: c["zone"] for s, c in setup.cfg.controllers.items()} == \
        {1: "home", 2: "none", 3: "none", 4: "none"}
    rows = setup.controller_rows
    rows[2].set_index(1)                       # gamepad 1 -> away
    rows[2].changed.emit()
    rows[3].set_index(0)                       # gamepad 2 -> home
    rows[3].changed.emit()
    assert setup.cfg.controller_counts() == (2, 1)
    md = build_match_data(window.data, setup.cfg)
    assert md["controllers"] == {1: "team_A", 2: "team_B", 3: "team_A", 4: "cpu"}
    for row in rows.values():                  # every device off: CPU vs CPU
        row.set_index(2)
        row.changed.emit()
    assert setup.cfg.controller_counts() == (0, 0) and setup.cfg.is_ready()
    assert set(build_match_data(window.data, setup.cfg)["controllers"].values()) == {"cpu"}
    setup._init_devices()
    for slot_id, row in rows.items():
        row.set_index(0 if slot_id == 1 else 2)


def test_settings_screen_ratio_rows(window, qapp, monkeypatch):
    """One Screen Ratio row (4:3 = widescreen off), no Fill the Screen."""
    from shared.user_prefs import user_prefs
    from ui.widgets import ChoiceRow
    from PyQt5.QtWidgets import QLabel
    for attr in ("widescreen", "widescreen_aspect"):
        monkeypatch.setattr(user_prefs, attr, getattr(user_prefs, attr))
    monkeypatch.setattr(user_prefs, "save", lambda: None)
    window.show_settings()
    qapp.processEvents()

    def row(cls, text):
        return next(r for r in window.screen_settings.findChildren(cls)
                    if any(l.text() == text for l in r.findChildren(QLabel)))
    ratio = row(ChoiceRow, "Screen Ratio").combo
    ratio.setCurrentText("16:10")
    assert user_prefs.widescreen and user_prefs.widescreen_aspect == "16:10"
    ratio.setCurrentText("4:3")
    assert not user_prefs.widescreen
    assert not any(l.text() in ("Widescreen", "Aspect Ratio", "Fill the Screen")
                   for l in window.screen_settings.findChildren(QLabel))
    window.show_main()


def test_updates_screen_installs_and_undoes(window, qapp, tmp_path):
    """Install shows what the update changes, then writes it; undo puts it back."""
    import zipfile
    from app.updates import Updates
    screen = window.screen_updates
    mod = tmp_path / "mod"
    (mod / "kits").mkdir(parents=True)
    (mod / "kits" / "a.png").write_bytes(b"old")
    real = screen.updates
    screen.updates = Updates({"mod_data": str(mod), "app_data": str(tmp_path / "app")},
                             str(tmp_path / "updates"), "0.2")
    upd = tmp_path / "u.zip"
    with zipfile.ZipFile(upd, "w") as z:
        z.writestr("update.json", '{"name": "Kits", "version": "2"}')
        z.writestr("mod_data/kits/a.png", b"new")
    try:
        window.show_updates()
        qapp.processEvents()
        screen.offer(str(upd))
        assert screen._dialog is not None
        screen._dialog._on_choice("ok")
        assert (mod / "kits" / "a.png").read_bytes() == b"new"
        assert "Installed Kits" in screen.status.text() and screen.undo_btn.isEnabled()
        screen._undo()
        screen._dialog._on_choice("ok")
        assert (mod / "kits" / "a.png").read_bytes() == b"old" and not screen.undo_btn.isEnabled()
    finally:
        screen._dialog = None
        screen.updates = real
        window.show_main()


def test_team_editor_edit_save_reload(window, qapp):
    window.open_team("10001", "2024")
    _wait(qapp, lambda: window.screen_team_editor.record_id == "10001", 10)
    editor = window.screen_team_editor
    assert editor.edit("rename", lambda w: w["2024"].__setitem__("name", "France XV"))
    assert editor.session.is_dirty()
    assert editor.save()
    path = window.data.teams_file_path["10001"]
    on_disk = json.load(open(path, encoding="utf-8"))["10001"]
    assert on_disk["2024"]["name"] == "France XV"
    assert "2008" in on_disk                                      # disabled season kept
    editor.undo()
    assert editor.session.working["2024"]["name"] == "France"
    editor.redo()
    assert editor.session.working["2024"]["name"] == "France XV"


def test_team_editor_refuses_incomplete_squad(window, qapp):
    window.open_team("1010", "2024")
    _wait(qapp, lambda: window.screen_team_editor.record_id == "1010", 10)
    editor = window.screen_team_editor
    before = open(window.data.teams_file_path["1010"], "rb").read()
    editor.edit("cut squad", lambda w: w["2024"].__setitem__("players", w["2024"]["players"][:20]))
    assert editor.save() is False
    assert open(window.data.teams_file_path["1010"], "rb").read() == before
    editor.edit("restore", lambda w: w.__setitem__("2024", copy.deepcopy(window.data.teams["1010"]["2024"])))


def test_player_editor_edit_save(window, qapp):
    """A save is kept in the user's edits; the pack file is not written. My
    edits lists it and drops it on request."""
    from app import game_data as G
    G.set_edit_store(window.data.edits)
    pid = str(window.data.teams["10002"]["2024"]["players"][0])
    window.open_player(pid, "2024")
    _wait(qapp, lambda: window.screen_player_editor.record_id == pid, 10)
    editor = window.screen_player_editor
    path = window.data.players_file_path[pid]
    before = open(path, "rb").read()
    editor.edit("rename", lambda w: w.__setitem__("display_name", "Z.Tested"))
    assert editor.save()
    assert open(path, "rb").read() == before
    assert window.data.edits.get("players", pid)["mine"]["display_name"] == "Z.Tested"

    window.show_user_edits()
    screen = window.screen_user_edits
    _wait(qapp, lambda: window.screens.currentWidget() is screen, 10)
    screen._show(("players", pid))
    assert "Z.Tested" in screen.title.text()
    # turned off: the pack's record is used, the edit kept; back on: used again
    screen.enabled_field._emit("off")
    assert window.data.players[pid]["display_name"] != "Z.Tested"
    assert "TURNED OFF" in screen.summary.text() and window.data.edits.get("players", pid)
    screen.enabled_field._emit("on")
    assert window.data.players[pid]["display_name"] == "Z.Tested"
    window.data.edits.revert("players", pid)
    window.data.refresh_record("players", pid)
    assert window.data.players[pid]["display_name"] != "Z.Tested"
    screen.reload()
    window.show_main()


def test_player_editor_all_seasons_box(window, qapp):
    """A card's ALL SEASONS box (ticked by default) sends its edits to every
    season; unticked, only the season shown changes."""
    pid = next(p for p, r in window.data.players.items() if len(r.get("stats") or {}) > 1)
    window.open_player(pid, None)
    _wait(qapp, lambda: window.screen_player_editor.record_id == pid, 10)
    editor = window.screen_player_editor
    profile = editor.tabs[0]
    stats = editor.session.working["stats"]
    profile.edit_stat("height", "height", "199")
    assert {s: v.get("height") for s, v in stats.items()} == dict.fromkeys(stats, "199")
    box = profile._scopes["height"]
    box._toggle()
    try:
        profile.edit_stat("height", "height", "150")
        assert {s: v.get("height") for s, v in stats.items()} == {
            s: "150" if s == editor.season else "199" for s in stats}
    finally:
        box._toggle()
    editor.session.revert()


def test_challenge_mode_lists_fixture_challenges(window, qapp):
    window.show_challenge_mode()
    qapp.processEvents()
    from app import challenges as C
    assert set(C.load_all()) >= {"rwc2023_sf_rsa_eng"}


def test_competition_emblem_prefers_the_menu_logo(qapp, tmp_path):
    from PyQt5.QtGui import QColor, QImage
    from screens.tournament.common import competition_emblem

    def png(name, colour):
        img = QImage(8, 8, QImage.Format_RGB32)
        img.fill(QColor(colour))
        img.save(str(tmp_path / name))

    png("game.png", "#ff0000")
    png("menu.png", "#00ff00")

    class Store:
        tournaments_folder_path = {"cup": str(tmp_path)}
        tournaments = {"cup": {"2015": {"logo": "game.png", "logo_frontend": "menu.png"},
                               "2019": {"logo": "game.png"}, "2023": {"logo_frontend": "missing.png"}}}

    def colour(edition):
        tpl = {"name": "Cup", "branding": "cup", "branding_season": edition}
        return competition_emblem(Store(), tpl, 8).toImage().pixelColor(4, 4).name()

    assert colour("2015") == "#00ff00"          # the menu logo
    assert colour("2019") == "#ff0000"          # no menu logo: the in-game one
    assert colour("2023") not in ("#00ff00", "#ff0000")   # never another edition's: the roundel


def _geometries(w):
    from PyQt5.QtWidgets import QWidget
    return {id(c): (type(c).__name__, c.mapTo(w, c.rect().topLeft()), c.size())
            for c in w.findChildren(QWidget) if c.isVisible()}


@pytest.mark.parametrize("show,attr", SCREENS, ids=[s for s, _ in SCREENS])
def test_screen_first_frame_is_final(window, qapp, show, attr):
    """A screen is shown already laid out: nothing moves or resizes in the moments after it appears
    (match setup's selectors and crests used to jump, scroll bars to pop in)."""
    window.show_main()
    for _ in range(30):
        qapp.processEvents()
    getattr(window, show)()
    screen = getattr(window, attr)
    first = _geometries(screen)
    end = time.monotonic() + 0.4
    while time.monotonic() < end:
        qapp.processEvents()
        time.sleep(0.005)
    later = _geometries(screen)
    moved = [first[k][0] for k in first if k in later and first[k] != later[k]]
    window.show_main()
    assert not moved


def test_no_popup_about_edits_at_start(window, qapp):
    """Edits merged with a data update are logged, never announced in a dialog at start."""
    from types import SimpleNamespace
    from ui.editor_kit import ConfirmDialog
    real = window.data.edits
    window.data.edits = SimpleNamespace(notes=[("merged", "x"), ("integrated", "y")], conflicts=[1])
    try:
        window._report_edits_after_update()
        qapp.processEvents()
        assert not [d for d in window.findChildren(ConfirmDialog) if d.isVisible()]
    finally:
        window.data.edits = real



def test_3d_previews_never_paint_a_stretched_image(qapp):
    """A 3D preview shown with an image rendered at another size (prepared hidden at start-up)
    renders at its own size before painting, instead of stretching the old image for a frame."""
    from PyQt5.QtCore import QTimer
    from PyQt5.QtGui import QImage
    from PyQt5.QtWidgets import QWidget
    from ui.ball_view import BallView
    from ui.player_view import PlayerView

    class Surface:                      # stands in for the GL surface (no GL here)
        failed = False

        def render_image(self, w, h):
            return QImage(w, h, QImage.Format_ARGB32)
    for cls in (PlayerView, BallView):
        v = cls.__new__(cls)
        QWidget.__init__(v)
        v._surface, v._timer, v._unavailable_sent = Surface(), QTimer(v), False
        v._image = QImage(7, 5, QImage.Format_ARGB32)        # rendered at another size
        v.resize(120, 80)
        v.grab()                                             # paints the widget once
        assert (v._image.width(), v._image.height()) == v._target_size(), cls.__name__
        v.deleteLater()


def test_number_fields_have_up_down_arrows(qapp):
    """Ratings (and every other number field) are a number with up / down arrows, not a bar to drag."""
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtTest import QTest
    from ui.editor_kit import NumberField, RatingField
    for cls, kw in ((RatingField, {}), (NumberField, {"lo": 0, "hi": 99})):
        f = cls("Speed", **kw)
        f.resize(420, f.height())
        f.set_value("50")
        got = []
        f.edited.connect(got.append)
        up, down = f._arrow_rects()
        QTest.mouseClick(f, Qt.LeftButton, Qt.NoModifier, up.center().toPoint())
        QTest.mouseClick(f, Qt.LeftButton, Qt.NoModifier, down.center().toPoint())
        QTest.mouseClick(f, Qt.LeftButton, Qt.ShiftModifier, up.center().toPoint())
        assert got == ["51", "50", "55"], cls.__name__
        f.set_value("99")
        QTest.mouseClick(f, Qt.LeftButton, Qt.NoModifier, up.center().toPoint())
        assert f.value() == "99"                              # stays inside 0-99
        assert f.grab().width() > 0                           # paints with the arrows
        # a click on the number itself only focuses
        before = f.value()
        QTest.mouseClick(f, Qt.LeftButton, Qt.NoModifier, QPoint(f.label_width + 20, f.height() // 2))
        assert f.value() == before


def test_dialog_ok_is_one_click_while_typing(qapp):
    """Renaming (kit, variant, anything asked with a text box): one click on OK both ends the edit and
    confirms. It used to take two: the first only moved focus out of the box."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QWidget
    from ui.editor_kit import FormDialog, TextField
    screen = QWidget()
    screen.resize(900, 600)
    screen.show()
    field = TextField("Kit name")
    field.set_value("home")
    got = []
    dialog = FormDialog(screen, "Rename kit", "", {"value": field},
                        [("CANCEL", "neutral", "cancel"), ("OK", "primary", "ok")], got.append)
    qapp.processEvents()
    field.begin_edit()
    field._edit.setText("away 2009")
    qapp.processEvents()
    assert field.is_editing()
    ok = next(b for b, role in dialog.buttons if role == "ok")
    QTest.mouseClick(ok, Qt.LeftButton)                       # ONE click
    for _ in range(5):
        qapp.processEvents()
    assert got == ["ok"]
    assert field.value() == "away 2009"
    screen.close()
