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
    ("show_tournament_editor", "screen_tournament_editor"),
    ("show_stadium_editor", "screen_stadium_editor"),
    ("show_referee_editor", "screen_referee_editor"),
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


def test_match_setup_dressing_choice(window, qapp, monkeypatch):
    """The pads / posts / ads rows: "Stadium default" gives the stadium's own
    set, a picked one goes to the match data."""
    from app import dressing
    from app.match_data_builder import build_match_data
    real = dressing.library_sets
    monkeypatch.setattr(dressing, "library_sets",
                        lambda kind: [{"label": "mine", "ref": f"stadium_graphics/{kind}/mine"}])
    monkeypatch.setattr(dressing, "look", lambda ref, kind: ref or None)     # every set its own look
    window.show_match_setup()
    qapp.processEvents()
    setup = window.screen_match_setup.setup_screen
    if not setup.cfg.controllers:
        setup.cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}
    for kind, key in (("pads", "pads"), ("posts", "posts"), ("ads", "adboards")):
        row = setup.dressing_rows[kind]
        row.refresh()
        assert row._values[0]["label"] == "Default" and row._values[0]["suggested"]
        mine = next(i for i, o in enumerate(row._values) if o["ref"] == f"stadium_graphics/{kind}/mine")
        assert not row._values[mine].get("suggested")
        assert all(o.get("suggested") for o in row._values[:mine])
        assert getattr(setup.cfg, dressing.CFG_ATTR[kind]) is None
        own = dressing.stadium_default(setup.cfg.stadium["data"], kind)
        assert own.startswith("stock:") or own
        assert build_match_data(window.data, setup.cfg)[key] == own
        row.set_index(mine)
        row.changed.emit()
        assert build_match_data(window.data, setup.cfg)[key] == f"stadium_graphics/{kind}/mine"
        row.set_index(0)
        row.changed.emit()
        assert build_match_data(window.data, setup.cfg)[key] == own
    monkeypatch.setattr(dressing, "library_sets", real)


def test_match_setup_pitch_logo_preview(window, qapp, tmp_path):
    """The pitch logo row's open list shows the logos of the option under
    the cursor; picking one dresses the match."""
    from PyQt5.QtWidgets import QLabel
    from app.match_data_builder import build_match_data
    window.show_match_setup()
    qapp.processEvents()
    setup = window.screen_match_setup.setup_screen
    if not setup.cfg.controllers:
        setup.cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}
    row = setup.pitch_logo_row
    assert row.current()[0] == "none" and len(row._values) > 1
    row._open_popup()
    qapp.processEvents()
    view = row._popup.findChild(QLabel)
    bare = view.pixmap().toImage()                               # "none": the pitch alone
    row._popup.hovered.emit(row._values[1])
    assert not view.pixmap().isNull() and view.pixmap().toImage() != bare
    view.pixmap().save(str(tmp_path / "pitch_logo_preview.png"))
    row._popup.picked.emit(row._values[1])
    row._popup.close_popup()
    qapp.processEvents()
    assert setup.cfg.pitch_logo_choice == row._values[1][0]
    assert build_match_data(window.data, setup.cfg)["pitch_logos"]
    row.set_index(0)
    row.changed.emit()
    assert build_match_data(window.data, setup.cfg)["pitch_logos"] == ""


def test_editors_and_crowd_rows_in_expert_mode_only(window, qapp, monkeypatch):
    """Tools' tournament, stadium and referee editors, the hub's CREATE YOUR
    OWN and quick match's crowd and referee rows show only in expert mode."""
    from shared.user_prefs import user_prefs
    for expert in (False, True):
        monkeypatch.setattr(user_prefs, "expert_mode", expert, raising=False)
        window.screen_tools.on_show()
        assert [t.isHidden() for t in window.screen_tools.expert_tiles] == [not expert] * 3
        hub = window.screen_tournament_hub
        hub.on_show()
        assert hub.create_tile.isHidden() is not expert
        setup = window.screen_match_setup.setup_screen
        setup._apply_expert_mode()
        assert setup.crowd_rows and all(r.isHidden() is not expert for r in setup.crowd_rows.values())
        assert setup.referee_row.isHidden() is not expert
        assert setup.referee_kit_row.isHidden() is not expert


def test_match_setup_expert_start_minute(window, qapp, monkeypatch):
    """Expert mode: quick match kicks off from a given minute and score, as
    the tournament's "play from a given minute"; back to a kick-off after."""
    from shared.user_prefs import user_prefs
    window.show_match_setup()
    qapp.processEvents()
    setup = window.screen_match_setup.setup_screen
    monkeypatch.setattr(user_prefs, "expert_mode", False, raising=False)
    setup._apply_expert_mode()
    assert setup.start_minute_row.isHidden() and setup.late_start() is None
    monkeypatch.setattr(user_prefs, "expert_mode", True, raising=False)
    setup._apply_expert_mode()
    assert not setup.start_minute_row.isHidden()
    assert setup.late_start() is None                       # "kick-off"
    setup.start_minute_row.set_index(70)                    # 70'
    setup.start_minute_row.changed.emit()
    scores = setup.start_score_rows["home"]._values
    setup.start_score_rows["home"].set_index(scores.index(10))
    assert setup.late_start() == (70, 10, 0)
    launched = []
    monkeypatch.setattr(setup, "start_kickoff_sequence", lambda md: launched.append(md))
    if not setup.cfg.controllers:
        setup.cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}
    setup._launch(setup.cfg)
    assert setup.cfg.mission_mode_time == 70 * 60 and setup.cfg.mission_mode_period == 1
    assert len(setup.cfg.score_events) >= 2                 # 10 points: at least two scores
    setup.start_minute_row.set_index(0)
    setup._launch(setup.cfg)
    assert setup.cfg.mission_mode_time is None and setup.cfg.score_events == []
    assert len(launched) == 2


def test_match_setup_controllers(window, qapp):
    """Each device's icon on the board (keyboard, then the pads connected in
    order) becomes the .mis controller slots."""
    from app.match_data_builder import build_match_data
    from ui.controller_board import KBD
    window.show_match_setup()
    qapp.processEvents()
    setup = window.screen_match_setup.setup_screen
    board = setup.controller_board
    board.set_pads((0, 2))                     # two pads plugged in (js0, js2)
    assert {s: c["zone"] for s, c in setup.cfg.controllers.items()} == \
        {1: "home", 2: "none", 3: "none", 4: "none"}
    board.move(0, 1)                           # pad 1 -> away
    board.move(2, -1)                          # pad 2 -> home
    board.move(2, -1)                          # already at the end: stays
    assert setup.cfg.controller_counts() == (2, 1)
    md = build_match_data(window.data, setup.cfg)
    assert md["controllers"] == {1: "team_A", 2: "team_B", 3: "team_A", 4: "cpu"}
    board.set_pads((2,))                       # pad 1 unplugged: pad 2 is now the game's first
    assert build_match_data(window.data, setup.cfg)["controllers"] == \
        {1: "team_A", 2: "team_A", 3: "cpu", 4: "cpu"}
    for device in board.devices():             # every device on CPU: CPU vs CPU
        board.set_zone(device, "none")
    assert setup.cfg.controller_counts() == (0, 0) and setup.cfg.is_ready()
    assert set(build_match_data(window.data, setup.cfg)["controllers"].values()) == {"cpu"}
    setup._init_devices()
    board.set_pads(())
    assert board.zones == {KBD: "home"}


def test_controller_board_each_device_moves_its_own_icon(qapp, monkeypatch):
    """A pad's left/right moves only its own icon while the board has the
    focus (the navigator sends no key for it); the keyboard's arrows move the
    keyboard; a click on an icon's half moves it that way."""
    from PyQt5.QtCore import QPoint, Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QApplication
    import app.gamepad as gp
    from ui.controller_board import KBD, ControllerBoard

    class Pads:
        state = {}
        def pads(self):
            return {n: set(b) for n, b in self.state.items()}
    sent = []
    monkeypatch.setattr(gp, "send_key", lambda key, fallback=None, repeat=False: sent.append(key))
    nav = gp.GamepadNavigator(Pads())
    nav._timer.stop()
    active = QApplication.activeWindow()
    board = None
    try:
        Pads.state = {0: set(), 1: set()}
        nav.poll()
        board = ControllerBoard()
        board.resize(700, 200)
        board.show()
        assert board.devices() == (KBD, 0, 1)
        QApplication.setActiveWindow(board)
        board.setFocus()
        qapp.processEvents()
        assert board.hasFocus()
        assert nav.claim is not None
        Pads.state = {0: {"right"}, 1: {"left"}}
        nav.poll()
        assert board.zones == {KBD: "home", 0: "away", 1: "home"} and sent == []
        Pads.state = {0: {"down"}, 1: set()}     # not left/right: still drives the menus
        nav.poll()
        assert sent == [Qt.Key_Down]
        QTest.keyClick(board, Qt.Key_Right)
        assert board.zones[KBD] == "none"
        rect = board._chip_rects()[1]
        QTest.mouseClick(board, Qt.LeftButton, pos=QPoint(int(rect.right() - 6), int(rect.center().y())))
        assert board.zones[1] == "none"
        Pads.state = {1: set()}                  # pad 0 unplugged
        nav.poll()
        assert board.devices() == (KBD, 1)
        board.hide()
        assert nav.claim is None
    finally:
        gp._navigator = None
        if board is not None:
            board.deleteLater()
        if active is not None:
            QApplication.setActiveWindow(active)


def test_settings_screen_ratio_rows(window, qapp, monkeypatch):
    """One Screen Ratio row (4:3 = widescreen off), no Fill the Screen."""
    from shared.user_prefs import user_prefs
    from ui.widgets import CycleRow
    from PyQt5.QtWidgets import QLabel
    for attr in ("widescreen", "widescreen_aspect"):
        monkeypatch.setattr(user_prefs, attr, getattr(user_prefs, attr))
    monkeypatch.setattr(user_prefs, "save", lambda: None)
    window.show_settings()
    qapp.processEvents()

    def row(cls, text):
        return next(r for r in window.screen_settings.findChildren(cls)
                    if any(l.text() == text for l in r.findChildren(QLabel)))
    ratio = row(CycleRow, "Screen Ratio")
    ratio.set_current("16:10")
    assert user_prefs.widescreen and user_prefs.widescreen_aspect == "16:10"
    ratio.set_current("4:3")
    assert not user_prefs.widescreen
    assert not any(l.text() in ("Widescreen", "Aspect Ratio", "Fill the Screen")
                   for l in window.screen_settings.findChildren(QLabel))
    window.show_main()


def _settings_rows(screen, tab):
    from screens.settings import TABS
    return {row.label.text(): row for row in screen._rows[TABS.index(tab)]}


def test_settings_tabs_and_reset(window, qapp):
    """Tabs by topic; resetting a tab puts its settings back to their defaults."""
    from shared.game_profile import game_profile
    from screens.settings import TABS
    s = window.screen_settings
    window.show_settings()
    qapp.processEvents()
    assert s.tabs.titles == list(TABS)

    display = _settings_rows(s, "Display")
    assert list(display)[:3] == ["Windowed Mode", "Resolution", "Screen Ratio"]
    assert "Shadows" in display and "Gamma" not in display
    audio = _settings_rows(s, "Audio")

    default = game_profile.default("vol_crowd")
    audio["Crowd"].set_value(default - 10 if default >= 10 else default + 10)
    assert game_profile.get("vol_crowd") != default
    s.reset_tab(TABS.index("Audio"))
    assert game_profile.get("vol_crowd") == default
    window.show_main()


def test_settings_gameplay_controls_group(window, qapp):
    """Gameplay groups offload mode, line-out control and lineout maul or
    pass under "controls", between match setup and rules."""
    from screens.settings import TABS
    s = window.screen_settings
    window.show_settings()
    qapp.processEvents()
    layout = s._pages[TABS.index("Gameplay")].layout_
    order = []
    for i in range(layout.count()):
        w = layout.itemAt(i).widget()
        if w is None:
            continue
        order.append(getattr(w, "label", None) and getattr(w.label, "text", lambda: None)() or
                     (w.text() if hasattr(w, "text") else None))
    texts = [t for t in order if t]
    lower = [t.lower() for t in texts]
    c = lower.index("controls")
    assert lower[c + 1:c + 4] == ["offload mode", "line-out control", "lineout maul or pass"]
    assert lower.index("match setup") < c < lower.index("rules")
    assert "offload mode" not in lower[lower.index("rules"):]
    window.show_main()


def test_settings_preferred_difficulty(window, qapp, monkeypatch):
    """Settings > Preferred Difficulty is what quick match starts on; no
    screen centre offsets any more."""
    from shared.user_prefs import user_prefs
    monkeypatch.setattr(user_prefs, "difficulty", user_prefs.difficulty)
    monkeypatch.setattr(user_prefs, "save", lambda: None)
    s = window.screen_settings
    window.show_settings()
    qapp.processEvents()
    assert not {"Screen Centre Horizontal", "Screen Centre Vertical"} & set(_settings_rows(s, "Display"))
    row = _settings_rows(s, "Gameplay")["Preferred Difficulty"]
    row.set_current("Legend")
    assert user_prefs.difficulty == "legend"
    window.show_match_setup()
    qapp.processEvents()
    setup = window.screen_match_setup.setup_screen
    assert setup.difficulty_row.current() == "legend" and setup.cfg.difficulty == "legend"
    window.show_main()


def test_settings_keyboard(window, qapp):
    """Left/Right change the row, Q/E switch tabs, Y asks before resetting, Esc goes back."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from shared.game_profile import game_profile
    from screens.settings import TABS
    from ui.editor_kit import ConfirmDialog
    s = window.screen_settings
    window.show_settings()
    qapp.processEvents()
    s.tabs.set_index(TABS.index("Audio"))
    row = _settings_rows(s, "Audio")["Crowd"]
    before = game_profile.get("vol_crowd")
    QTest.keyClick(row, Qt.Key_Left if before else Qt.Key_Right)
    assert game_profile.get("vol_crowd") == (before - 5 if before else 5)
    QTest.keyClick(row, Qt.Key_E)
    assert s.tabs.index() == TABS.index("Gameplay")
    QTest.keyClick(s.tabs, Qt.Key_Q)
    assert s.tabs.index() == TABS.index("Audio")

    QTest.keyClick(s.tabs, Qt.Key_Y)
    dialog = next(d for d in s.findChildren(ConfirmDialog) if d.isVisible())
    dialog.choose("reset")
    assert game_profile.get("vol_crowd") == game_profile.default("vol_crowd")

    row = _settings_rows(s, "Audio")["Crowd"]
    QTest.keyClick(row, Qt.Key_Escape)
    assert window.screens.currentWidget() is not s
    window.show_main()


def _pad(window, qapp, key):
    """A pad button: its key, sent where app.gamepad sends it."""
    from app.gamepad import send_key
    send_key(key, window.screens.currentWidget)
    for _ in range(3):
        qapp.processEvents()


def test_pad_leaves_a_card_list_inside_a_scroll_area(window, qapp):
    """Down moves from card to card instead of scrolling the list holding them."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    window.show_challenge_mode()
    qapp.processEvents()
    screen = window.screen_challenge_mode
    tiles = [t for t in screen._tiles if t.isVisible()]
    assert len(tiles) >= 2
    tiles[0].setFocus()
    _pad(window, qapp, Qt.Key_Down)
    assert QApplication.focusWidget() is tiles[1]
    _pad(window, qapp, Qt.Key_Escape)
    assert window.screens.currentWidget() is not screen
    window.show_main()


def test_pad_about_goes_back(window, qapp):
    from PyQt5.QtCore import Qt
    window.show_main()
    window.show_about()
    qapp.processEvents()
    _pad(window, qapp, Qt.Key_Down)                         # scrolls, stays
    assert window.screens.currentWidget() is window.screen_about
    _pad(window, qapp, Qt.Key_Escape)
    assert window.screens.currentWidget() is not window.screen_about
    window.show_main()


def test_pad_y_removes_the_focused_row(window, qapp):
    """A row's ✕ is past fields that keep Left/Right: Y presses it."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication, QAbstractButton
    window.show_challenge_editor()
    qapp.processEvents()
    screen = window.screen_challenge_editor

    def removers():
        return [b for b in screen.findChildren(QAbstractButton)
                if b.property("removesRow") and b.isVisible()]
    next(b for b in screen.findChildren(QAbstractButton)
         if b.text() == "+ CHALLENGE OBJECTIVE").click()     # the row Y takes away again
    qapp.processEvents()
    before = removers()
    assert before
    row = before[0].parentWidget()
    field = next(w for w in screen.focus.alive() if row.isAncestorOf(w) and w is not before[0])
    field.setFocus()
    _pad(window, qapp, Qt.Key_Y)
    assert len(removers()) == len(before) - 1
    focus = QApplication.focusWidget()
    assert focus is not None and focus.isVisible() and screen.isAncestorOf(focus)
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
        _wait(qapp, lambda: not screen._busy())          # the new data loaded, no restart
        assert "Installed Kits" in screen.status.text() and "in use" in screen.status.text()
        assert screen.undo_btn.isEnabled()
        screen._undo()
        screen._dialog._on_choice("ok")
        _wait(qapp, lambda: not screen._busy())
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


def test_team_editor_saves_incomplete_squad_as_draft(window, qapp):
    """A squad with errors is saved, but the mod does not use the season until
    it is fixed and saved again."""
    window.open_team("1010", "2024")
    _wait(qapp, lambda: window.screen_team_editor.record_id == "1010", 10)
    editor = window.screen_team_editor
    ds = window.data
    path = ds.teams_file_path["1010"]
    good = copy.deepcopy(ds.teams["1010"]["2024"])
    editor.edit("cut squad", lambda w: w["2024"].__setitem__("players", w["2024"]["players"][:20]))
    assert editor.save()
    assert "not used in the mod" in editor.shell.footer.status.text().lower()
    assert "2024" not in ds.teams.get("1010", {})          # the mod no longer sees it
    assert ds.team_seasons("1010")["2024"]["draft"] is True  # the editor still does
    assert ds.team_seasons("1010")["2024"]["players"] == good["players"][:20]
    assert "1010" in [r["id"] for r in editor.list_rows()]
    # and after a restart
    from app.state import DataStore
    fresh = DataStore(DataStore.read_files())
    assert "2024" not in fresh.teams.get("1010", {})
    assert fresh.team_drafts["1010"]["2024"]["players"] == good["players"][:20]
    editor.edit("restore", lambda w: w.__setitem__("2024", copy.deepcopy(good)))
    assert editor.save()
    assert "draft" not in ds.teams["1010"]["2024"]
    assert ds.teams["1010"]["2024"]["players"] == good["players"]


def test_team_editor_fills_any_shirt_of_an_empty_squad(window, qapp):
    """An empty shirt is picked where it is, not at the end of the list; the
    shirts before it stay empty (and not painted red) until they are filled."""
    from screens.team_tabs import TAB_SQUAD
    window.open_team("1010", "2024")
    _wait(qapp, lambda: window.screen_team_editor.record_id == "1010", 10)
    editor = window.screen_team_editor
    squad = editor.tabs[TAB_SQUAD]
    full = list(editor.session.working["2024"]["players"])
    editor.edit("empty squad", lambda w: w["2024"].__setitem__("players", []))
    editor.refresh_all()
    squad.open_picker(10)
    assert squad._picker_shirt == 10 and "FLY-HALF" in squad.picker._popup.title_lbl.text().upper()
    squad._on_pick(full[9])
    roster = editor.session.working["2024"]["players"]
    assert roster == [""] * 9 + [full[9]]
    editor.refresh_all()
    assert squad.slots[10].player is not None and squad.slots[1].player is None
    assert squad.slots[1].empty_label == "+"
    squad.open_picker(1)                                   # any other shirt: its own
    squad._on_pick(full[0])
    assert editor.session.working["2024"]["players"][0] == full[0]
    assert len(editor.session.working["2024"]["players"]) == 10
    editor.refresh_all()
    # the shirts in between are flagged: nobody picked
    assert any(k == "players.1" for k, _, _ in editor.issues)
    assert squad.slots[2].issue_color is None
    # dropped on a far empty shirt: that very shirt
    squad._swap(10, 14)
    assert editor.session.working["2024"]["players"][13] == full[9]
    editor.session.revert()
    editor.refresh_all()


def test_clear_button_replaces_the_none_rows(window, qapp):
    """A clearable field has a × instead of a "none" row in its list; an asset
    field has one too; an empty rating shows its default, not a dash."""
    from PyQt5.QtCore import QPointF, QPoint, Qt
    from PyQt5.QtTest import QTest
    from ui.editor_kit import ChoiceField, AssetField, RatingField, NumberField
    field = ChoiceField("Role", ["a", "b"], clearable=True, blank_label="default · player 10")
    field.resize(500, 40)
    got = []
    field.edited.connect(got.append)
    field.set_value("a")
    assert not field._blank_row() and field._cycle() == ["a", "b"]
    QTest.mouseClick(field, Qt.LeftButton, Qt.NoModifier, field._clear_rect().center().toPoint())
    assert got == [""] and field.value() == ""
    plain = ChoiceField("Kit variant", ["x"], blank_label="Default")     # a real choice stays a row
    assert plain._blank_row()
    asset = AssetField("Crest", {"ext": (".png",)})
    asset.resize(600, 48)
    asset.set_value("logos_1/logo.png")
    got.clear()
    asset.edited.connect(got.append)
    QTest.mouseClick(asset, Qt.LeftButton, Qt.NoModifier, asset._clear_rect().center().toPoint())
    assert got == [""] and asset.value() == ""
    rating = RatingField("Crash ball")
    rating.set_value("")
    got.clear()
    rating.edited.connect(got.append)
    rating.step(1)
    assert got == ["1"] and rating.default == 0           # blank is 0: stepping starts there
    number = NumberField("Season", 1900, 2100, formatter=lambda v: f"{int(v) - 1}-{v}")
    number.set_value("2026")
    assert number.formatter(number.value()) == "2025-2026"


def test_new_player_dialog_has_no_file_choice(window, qapp):
    from app.season import season_label
    from ui.editor_kit import FormDialog
    window.show_player_editor()
    qapp.processEvents()
    editor = window.screen_player_editor
    editor.new_record()
    qapp.processEvents()
    dialog = editor._dialog
    assert isinstance(dialog, FormDialog)
    assert "target" not in dialog.fields and set(dialog.fields) == {"first", "last", "year", "position", "level", "team"}
    year = dialog.fields["year"]
    assert year.formatter(year.value()) == season_label(year.value()) and "-" in year.formatter(year.value())
    dialog.close()
    editor._dialog = None


def test_kit_files_added_to_an_empty_kit_go_to_the_season_folder(window, qapp):
    """A file loaded into a kit with no files goes to kits_<season> (kits_<season>_<variant>
    for a kit variant), not the team root; once the kit has files, next to them."""
    from screens.team_tabs import TAB_KITS
    window.open_team("1010", "2024")
    _wait(qapp, lambda: window.screen_team_editor.record_id == "1010", 10)
    editor = window.screen_team_editor
    kits = editor.tabs[TAB_KITS]
    kits._add("third", None)
    kits.kit_index = kits.kit_names().index("third")
    editor.refresh_all()
    assert kits._kit_dir() == "kits_2024"
    kits.kit_variant = "world_cup"
    editor.edit("variant", lambda w: kits.stored_kit() is not None and w["2024"]["kits"]["third"].setdefault(
        "variants", {}).setdefault("world_cup", {}))
    editor.refresh_all()
    assert kits._kit_dir() == "kits_2024_world_cup"
    kits.kit_variant = ""
    editor.edit("file", lambda w: w["2024"]["kits"]["third"].__setitem__("frontKitFile", "kits_2019/x_front.png"))
    editor.refresh_all()
    assert kits._kit_dir() == "kits_2019"
    editor.session.revert()
    editor.refresh_all()


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


def test_player_editor_save_with_edits_off(window, qapp):
    """Edits turned off: SAVE asks to turn them on instead of failing, the
    typed change survives the question and is saved once they are on; the
    unsaved-changes guard then carries on where the user was going."""
    from app import game_data as G
    G.set_edit_store(window.data.edits)
    pid = str(window.data.teams["10002"]["2024"]["players"][1])
    window.open_player(pid, "2024")
    _wait(qapp, lambda: window.screen_player_editor.record_id == pid, 10)
    editor = window.screen_player_editor
    window.data.set_edits_enabled(False)
    try:
        editor.edit("rename", lambda w: w.__setitem__("display_name", "Z.Off"))
        assert editor.save() is False
        dialog = editor._dialog
        assert dialog is not None and editor.session.is_dirty()
        dialog.choose("cancel")
        assert not window.data.edits.enabled and editor.session.is_dirty()

        went = []
        editor.guard_dirty(lambda: went.append(True))
        editor._dialog.choose("save")                  # unsaved changes: SAVE
        assert not went
        editor._dialog.choose("on")                    # edits off: TURN ON AND SAVE
        assert went and window.data.edits.enabled
        assert not editor.session.is_dirty()
        assert window.data.edits.get("players", pid)["mine"]["display_name"] == "Z.Off"
    finally:
        window.data.set_edits_enabled(True)
        window.data.edits.revert("players", pid)
        window.data.refresh_record("players", pid)
    window.show_main()


def test_player_editor_loads_a_commentary_recording(window, qapp, tmp_path, monkeypatch):
    """Commentary > Load from disk… keeps the recording as <id>_<last name>.wav
    in the mod data's commentary folder and gives the player that clip."""
    import shutil
    import wave
    from PyQt5.QtWidgets import QFileDialog
    from app import disk_import
    from shared import commentary
    from ui.editor_kit import LOAD_FILES
    src = tmp_path / "take.wav"
    with wave.open(str(src), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(22050)
        w.writeframes(b"".join(int(8000 * ((i // 40) % 2 * 2 - 1)).to_bytes(2, "little", signed=True)
                               for i in range(11025)))
    folder = tmp_path / "commentary"
    monkeypatch.setattr(commentary, "custom_folder", lambda: str(folder))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(src), ""))

    def copy(a, b):
        os.makedirs(os.path.dirname(b), exist_ok=True)
        shutil.copy2(a, b)
    monkeypatch.setattr(disk_import, "copy_into_data", copy)
    pid = str(window.data.teams["10002"]["2024"]["players"][0])
    window.open_player(pid, "2024")
    _wait(qapp, lambda: window.screen_player_editor.record_id == pid, 10)
    editor = window.screen_player_editor
    try:
        assert editor.commentary.options[0] == LOAD_FILES
        editor.commentary._emit(LOAD_FILES)
        _wait(qapp, lambda: os.listdir(folder) if folder.exists() else False, 10)
        (fn,) = os.listdir(folder)
        cid = fn.split("_", 1)[0].lstrip("0")
        assert editor.session.working["commentary"] == cid
        assert int(cid) >= commentary.CUSTOM_BASE and cid in editor.commentary.options
        last = editor.session.working.get("last_name") or "take"
        assert editor._commentary_label(cid).startswith(commentary.custom_clips()[int(cid)][0])
        assert last.split()[0][:3].lower() in fn.lower() or not last
    finally:
        editor.session.revert()
    window.show_main()


def test_player_editor_star_marker(window, qapp):
    """The Skills tab hides the star above the head (hide_star) apart from
    the star ability, and shows it again when cleared."""
    from screens.player_editor import TAB_SKILLS
    pid = str(window.data.teams["10002"]["2024"]["players"][0])
    window.open_player(pid, "2024")
    _wait(qapp, lambda: window.screen_player_editor.record_id == pid, 10)
    editor = window.screen_player_editor
    tab = editor.tabs[TAB_SKILLS]
    shown = [""] + list(tab.star_attribute.options)          # blank = "— none"
    assert sum(1 for v in shown if v in ("", "0")) == 1      # listed once
    tab.star_attribute._emit("5")
    tab.star_marker._emit("yes")
    stats = editor.session.working["stats"]["2024"]
    assert stats["star_attribute"] == "5" and stats["hide_star"] == "yes"
    tab.refresh()
    assert tab.star_marker.value() == "yes"
    tab.star_marker._emit("")
    assert not editor.session.working["stats"]["2024"].get("hide_star")
    # star commentary: an expert-mode field of its own
    from shared.user_prefs import user_prefs
    expert = user_prefs.expert_mode
    try:
        user_prefs.expert_mode = False
        tab.refresh()
        assert tab.star_voice.isHidden()
        user_prefs.expert_mode = True
        tab.refresh()
        assert not tab.star_voice.isHidden()
        tab.star_voice._emit("4")
        assert editor.session.working["stats"]["2024"]["star_voice"] == "4"
    finally:
        user_prefs.expert_mode = expert
        # leave nothing unsaved: the next open would stop at "Unsaved changes"
        editor.session.revert()
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


def test_asset_popup_loads_from_disk(qapp, tmp_path, monkeypatch):
    """"Load from disk…" in an asset popup copies the file next to the current
    one and picks it; a numbered series is picked as its %-pattern."""
    from PyQt5.QtWidgets import QFileDialog, QWidget
    from ui import editor_kit as K
    screen = QWidget()
    screen.resize(900, 600)
    anchor = QWidget(screen)
    screen.show()
    root = tmp_path / "Team"
    (root / "logos_1").mkdir(parents=True)
    (root / "logos_1" / "logo.png").write_bytes(b"old")
    disk = tmp_path / "disk"
    disk.mkdir()
    for name in ("crest.png", "ball_1.png", "ball_2.png"):
        (disk / name).write_bytes(name.encode())
    picks, got = [[str(disk / "crest.png")], [str(disk / "ball_1.png"), str(disk / "ball_2.png")]], []
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", lambda *a, **k: (picks.pop(0), ""))
    for spec, current in (({"ext": (".png",)}, "logos_1/logo.png"), ({"ext": (".png",), "frames": 2}, "")):
        popup = K.browse_assets(screen, anchor, str(root), spec, current, got.append,
                                default_dir="ball_2025")
        qapp.processEvents()
        rows = [r.data for r in popup._rows]
        assert "" not in rows                       # no "none" row: the field has a × button
        # one file is loaded from a file; only a numbered series offers a folder
        assert rows[:2] == ([K.LOAD_FILES, K.LOAD_FOLDER] if spec.get("frames") else [K.LOAD_FILES, ("__dir__", "logos_1")])
        popup.picked.emit(K.LOAD_FILES)
        for _ in range(5):
            qapp.processEvents()
    # a field with a file loads next to it; an empty one into the default folder
    assert got == ["logos_1/crest.png", "ball_2025/ball_%.png"]
    assert (root / "logos_1" / "crest.png").read_bytes() == b"crest.png"
    assert (root / "ball_2025" / "ball_2.png").read_bytes() == b"ball_2.png"
    screen.close()


def test_head_picker_loads_from_disk(window, qapp, tmp_path, monkeypatch):
    from PyQt5.QtWidgets import QFileDialog
    from shared.app_paths import user_data_directory
    from shared.config import config as cfg
    from ui.face_picker import FacePicker
    (tmp_path / "head_777.big").write_bytes(b"head")
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a, **k: ([str(tmp_path / "head_777.big")], ""))
    window.show_player_editor()
    qapp.processEvents()
    picker = FacePicker(window.screen_player_editor)
    try:
        picker._load(False)
        assert os.path.isfile(os.path.join(cfg.mod_data_directory, "players", "heads", "head_777.big"))
        assert picker._mode == "custom" and picker._current == "players/heads/head_777.big"
        assert "players/heads/head_777.big" in picker._cells
    finally:
        picker._close()
        for d in (cfg.mod_data_directory, cfg.pack_directory,
                  os.path.join(user_data_directory(), "mod_data")):
            p = os.path.join(d, "players", "heads", "head_777.big")
            if os.path.isfile(p):
                os.remove(p)
        window.show_main()


def test_team_editor_shirt_names_tab(window, qapp):
    """The Shirt names tab: switching names on, dragging the name area and
    picking a kit colour edit the season through the undo stack, and save."""
    from screens.team_tabs import TAB_NAMES
    window.open_team("10001", "2024")
    _wait(qapp, lambda: window.screen_team_editor.record_id == "10001", 10)
    editor = window.screen_team_editor
    editor.shell.tabs.set_index(TAB_NAMES)
    tab = editor.tabs[TAB_NAMES]
    for _ in range(10):
        qapp.processEvents()
    assert not editor.session.working["2024"].get("shirtNames")
    assert not editor.session.is_dirty()             # looking edits nothing

    kit = tab.kit_name
    tab.enabled.edited.emit("on")
    working = editor.session.working["2024"]
    assert working["kits"][kit]["shirtName"] == {"enabled": True}      # the shown kit's own
    assert "shirtNames" not in working                                 # nothing season-wide
    tab.font.edited.emit("Oswald")
    tab.canvas.area_changed.emit([0.2, 0.15, 0.6, 0.08])
    assert working["kits"][kit]["shirtName"]["area"] == [0.2, 0.15, 0.6, 0.08]
    assert not hasattr(tab, "copy_btn")
    tab.refresh()
    tab._render()
    size = tab._texture_size()
    if size:                                    # the fixture's backs: typed in pixels of the image
        assert tab.area_fields[1].value() == str(round(0.15 * size[1]))
        tab.area_fields[1].edited.emit(str(size[1] // 4))
        assert working["kits"][kit]["shirtName"]["area"][1] == 0.25
    tab.color.edited.emit("#ffffff")
    assert working["kits"][kit]["shirtName"]["color"] == "#ffffff"
    editor.undo()
    working = editor.session.working["2024"]                    # undo restores a copy
    assert "color" not in working["kits"][kit]["shirtName"]
    assert not hasattr(tab, "placement") and not hasattr(tab, "gap")
    tab.refresh()
    tab.reset_pos_btn.click()                                   # back above the number
    block = working["kits"][kit]["shirtName"]
    assert block["placement"] == "above" and "area" not in block
    other = next((k for k in working["kits"] if k != kit), None)
    if other:
        assert "shirtName" not in working["kits"][other]        # the other kits are untouched
    assert editor.save()
    # saved (into the data pack or the user's edits, as the save target says)
    assert window.data.teams["10001"]["2024"]["kits"][kit]["shirtName"]["font"] == "Oswald"
    editor.edit("names off", lambda w: w["2024"]["kits"][kit].pop("shirtName"))
    assert editor.save()


def test_coin_toss_not_offered(qapp, tmp_path, monkeypatch):
    """The coin toss is off for now: user_prefs.ini can't turn it on."""
    from shared import user_prefs as up
    ini = tmp_path / "user_prefs.ini"
    ini.write_text("[prefs]\ncoin_toss = True\n")
    monkeypatch.setattr(up, "_PREFS_FILE", str(ini))
    assert up.UserPrefs().coin_toss is False


@pytest.mark.parametrize("starter,fmt", [("knockout", "cup"), ("club_league", "league")])
def test_tournament_editor_make_and_play(window, qapp, monkeypatch, tmp_path, starter, fmt):
    """Tournament editor: start from a ready-made shape, fill it, save, PLAY IT —
    the wizard opens on it, and the tournament it starts plays to a champion."""
    from shared.config import config
    from app.tournament import custom as C, engine
    monkeypatch.setattr(config, "directory_custom_tournaments", str(tmp_path / "custom"))
    window.show_tournament_editor()
    ed = window.screen_tournament_editor
    _wait(qapp, lambda: window.screens.currentWidget() is ed, 10)
    ed._create(starter)
    assert ed.d["format"] == fmt and ed.record_id in ed._drafts
    four = C.all_teams(C.auto_fill(ed.ds, dict(ed.d, groups=[{"name": "", "teams": []}]),
                                   "internationals", 4))
    ed._replace("four teams", dict(ed.d, groups=[{"name": "", "teams": four}]))
    qapp.processEvents()
    assert len(C.all_teams(ed.d)) == 4
    if fmt == "league":
        ed._set("playoff_teams", 2)
    ed.refresh_all()
    errors = [m for _k, m, sev in ed.issues if sev == "error"]
    assert errors == [] and ed.play_btn.isEnabled()
    created = []
    monkeypatch.setattr(window.screen_tournament_wizard, "on_created", created.append)
    ed._play()                                  # saves, then the wizard on it
    tid = ed.record_id
    assert tid in C.load_all() and tid not in ed._drafts
    wiz = window.screen_tournament_wizard
    _wait(qapp, lambda: window.screens.currentWidget() is wiz, 10)
    assert wiz.current_edition().id == tid and wiz._step == 1
    wiz._toggle_human(C.all_teams(ed.d)[0])
    assert wiz._validate(), wiz.problems.text()
    wiz._start()
    assert created
    t = created[0].t
    engine.simulate_to_end(t)
    assert t.finished and t.champion
    window.show_main()


@pytest.mark.parametrize("show,attr", SCREENS, ids=[s for s, _ in SCREENS])
def test_screen_fits_the_smallest_window(window, qapp, show, attr):
    """Every screen fits the window's own minimum size (1000x640): what
    doesn't fit scrolls instead of being squashed or cut off."""
    smallest = window.minimumSize()
    window.resize(smallest)
    getattr(window, show)()
    _wait(qapp, lambda: window.screens.currentWidget() is getattr(window, attr), 10)
    for _ in range(20):
        qapp.processEvents()
    need = getattr(window, attr).minimumSizeHint()
    assert need.width() <= smallest.width() and need.height() <= smallest.height(), need
    window.show_main()
    window.resize(1280, 720)


def test_boots_picker_folds_sections_and_player_teams_lists_every_season(window, qapp):
    """Boots: thumbnails, headers that fold (only the picked boots' section
    open), no load rows. The Teams tab lists the squads of every season."""
    from screens.player_tabs import TAB_APPEARANCE, TAB_TEAMS
    pid = str(window.data.teams["10002"]["2024"]["players"][0])
    window.open_player(pid, "2024")
    _wait(qapp, lambda: window.screen_player_editor.record_id == pid, 10)
    editor = window.screen_player_editor
    tab = editor.tabs[TAB_APPEARANCE]
    boots = tab.boots
    boots.open_popup()
    popup = boots._popup
    qapp.processEvents()
    heads = [r for r in popup._rows if isinstance(r.data, tuple)]
    values = [r.data for r in popup._rows if not isinstance(r.data, tuple)]
    assert len(heads) > 1 and all(r.text[0] in "▸▾" for r in heads)
    assert len(values) < len(boots.options)                      # folded
    assert values[0] == "__disk_files__" and not any(str(v).startswith("__") for v in values[1:])
    assert popup._rows[0].text == "Load from file…"              # one load row, above the sections
    boots.set_value("1")
    boots.step(1)
    assert boots.value() != "__disk_files__"                     # arrows never run it
    assert not any(r.subtitle for r in popup._rows)
    image = next(v for v in boots.options if not str(v).isdigit() and not v.startswith("__"))
    assert not tab._boot_icon(image).isNull() and tab._boot_icon("3") is None
    shut = next(r for r in heads if r.text.startswith("▸"))
    popup._on_row_picked(shut.data)                              # unfolds in place
    assert popup.isVisible()
    assert len([r for r in popup._rows if not isinstance(r.data, tuple)]) > len(values)
    popup.close_popup()

    teams = editor.tabs[TAB_TEAMS]
    teams.refresh()
    ds = window.data
    seasons = {m[2] for m in ds.memberships(pid, with_variants=True)}
    assert len(teams._row_btns) == len(ds.memberships(pid, with_variants=True))
    assert len(seasons) >= 1


def test_match_setup_crowd_rows(window, qapp, monkeypatch):
    """crowd / supporters / atmosphere (expert mode): the game's own by
    default, a choice goes to the match data."""
    from backend import crowd
    from shared.user_prefs import user_prefs
    monkeypatch.setattr(user_prefs, "expert_mode", True, raising=False)
    if not crowd.OPTIONS_ENABLED:
        # switched off for now: no rows, and a stored choice changes nothing
        setup = window.screen_match_setup.setup_screen
        assert setup.crowd_rows == {}
        setup.cfg.crowd_size = "half"
        from app.match_data_builder import build_match_data
        if not setup.cfg.controllers:
            setup.cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}
        assert build_match_data(window.data, setup.cfg)["crowd"] is None
        setup.cfg.crowd_size = "full"
        return
    from app.match_data_builder import build_match_data
    window.show_match_setup()
    qapp.processEvents()
    setup = window.screen_match_setup.setup_screen
    if not setup.cfg.controllers:
        setup.cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}
    assert build_match_data(window.data, setup.cfg)["crowd"] is None
    rows = setup.crowd_rows
    rows["crowd_size"].set_values(["full", "busy", "half", "sparse"], index=2)
    rows["crowd_size"].changed.emit()
    rows["crowd_colours"].set_values(["neutral", "colours"], index=1)
    rows["crowd_colours"].changed.emit()
    shot = os.environ.get("R08_SHOT")
    if shot:
        window.resize(1280, 800)
        for _ in range(20):
            qapp.processEvents()
        window.screen_match_setup.grab().save(shot)
    crowd = build_match_data(window.data, setup.cfg)["crowd"]
    assert crowd["size"] == "half" and crowd["colours"] is True and crowd["mood"] == "normal"
    setup.cfg.crowd_size, setup.cfg.crowd_colours = "full", False


def test_new_player_joins_a_team_with_ratings_for_his_position(window, qapp):
    from app.ratings import position_overall
    from app import player_ops as P
    window.show_player_editor()
    editor = window.screen_player_editor
    editor._create_player("Ann", "Tester", "2024", "winger", "world", "10002")
    qapp.processEvents()
    pid = editor.record_id
    rec = window.data.players[pid]
    assert rec["display_name"] == "A. Tester" and rec["last_name"] == "Tester"
    block = rec["stats"]["2024"]
    assert abs(position_overall(block) - P.level_overall("world")) <= 1
    assert pid in [str(p) for p in window.data.teams["10002"]["2024"]["players"]]


def test_add_to_a_team_from_the_teams_tab(window, qapp):
    from screens.player_tabs import TAB_TEAMS
    editor = window.screen_player_editor
    editor._create_player("Bo", "Lonely", "2024", "hooker", "club", "")
    qapp.processEvents()
    pid = editor.record_id
    assert not window.data.memberships(pid)
    tab = editor.tabs[TAB_TEAMS]
    tab._add_to("10002")
    roster = [str(p) for p in window.data.teams["10002"]["2024"]["players"]]
    assert pid in roster
    assert any(m[0] == "10002" for m in window.data.memberships(pid))


def test_squad_picker_creates_a_player_for_the_shirt(window, qapp):
    from screens.team_tabs import TAB_SQUAD
    window.open_team("10002", "2024")
    _wait(qapp, lambda: window.screen_team_editor.record_id == "10002", 10)
    team_ed = window.screen_team_editor
    squad = team_ed.tabs[TAB_SQUAD]
    n = len(window.data.players)
    squad._new_player(2, "Joe Bloggs")
    dialog = team_ed._dialog
    assert dialog.fields["first"].value() == "Joe" and dialog.fields["last"].value() == "Bloggs"
    assert dialog.fields["position"].value() == "hooker"
    dialog._on_choice("ok")
    qapp.processEvents()
    assert len(window.data.players) == n + 1
    new = [p for p in window.data.players if window.data.players[p].get("last_name") == "Bloggs"][0]
    assert str(team_ed.season_block()["players"][1]) == new
    team_ed.session.revert() if hasattr(team_ed.session, "revert") else None


def test_new_team_dialog_needs_a_name_and_a_group(window, qapp):
    """New team: name, type, group, season only; CREATE stays off until the
    name and the group are filled, and empty fields show no "not set"."""
    from ui.editor_kit import FormDialog
    window.show_team_editor()
    qapp.processEvents()
    editor = window.screen_team_editor
    editor.new_record()
    qapp.processEvents()
    dialog = editor._dialog
    assert isinstance(dialog, FormDialog)
    assert set(dialog.fields) == {"name", "type", "group", "year"}
    create = next(b for b, role in dialog.buttons if role == "ok")
    name, group = dialog.fields["name"], dialog.fields["group"]
    assert name.blank_text == "" and group.blank_label == ""
    assert not create.isEnabled()
    name.set_value("Test Fifteen")
    name.edited.emit("Test Fifteen")
    assert not create.isEnabled()
    dialog.choose("ok")                         # refused: no group yet
    assert editor._dialog is dialog
    group.set_value(group.options[0])
    group.edited.emit(group.options[0])
    assert create.isEnabled()
    dialog.choose("ok")
    qapp.processEvents()
    tid = editor.record_id
    info = window.data.team_seasons(tid)[max(window.data.team_seasons(tid))]
    assert info["name"] == "Test Fifteen" and info.get("group") == group.options[0]


def test_editor_list_filters_and_season_pane(window, qapp):
    """Team type and nationality filters; the season list back in its own
    pane; the filter box hint has no dash."""
    window.show_team_editor()
    qapp.processEvents()
    teams = window.screen_team_editor
    kind = teams.extra_filters["type"]
    assert set(kind.options) <= {"club", "international", "special"} and kind.options
    kind.set_value("international")
    kind.edited.emit("international")
    shown = teams.list.count()
    assert all((window.data.team_seasons(tid)[max(window.data.team_seasons(tid))].get("type")) == "international"
               for tid, *_ in teams.list_items()[0])
    kind.set_value("")
    kind.edited.emit("")
    assert teams.list.count() >= shown
    assert teams.shell.mid_pane is not None and teams.season_list.isVisibleTo(teams)
    assert not teams.list.search.dash

    window.show_player_editor()
    qapp.processEvents()
    players = window.screen_player_editor
    nat = players.extra_filters["nationality"]
    assert nat.options
    nat.set_value(nat.options[0])
    nat.edited.emit(nat.options[0])
    for pid, *_ in players.list_items()[0]:
        stats = window.data.players[pid]["stats"]
        assert stats[max(stats)].get("nationality") == nat.options[0]
    nat.set_value("")
    nat.edited.emit("")
    assert players.shell.mid_pane is not None and players.season_list.count() >= 1


def test_shirt_names_preview_without_squad_says_player_name(window, qapp):
    from screens import team_tabs
    from shared import shirt_names as SN
    assert SN.shirt_text(team_tabs.SAMPLE_PLAYER, "surname", "upper") == "PLAYER NAME"
    assert SN.shirt_text(team_tabs.SAMPLE_PLAYER, "full", "asis") == "Player name"
    assert SN.shirt_text(team_tabs.SAMPLE_PLAYER, "initial", "asis") == "Player name"


def test_head_picker_click_assigns(window, qapp):
    from ui.face_picker import FacePicker
    from app.stock_faces import search_stock_faces
    pid = next(iter(window.data.players))
    window.open_player(pid, None)
    _wait(qapp, lambda: window.screen_player_editor.record_id == pid, 10)
    editor = window.screen_player_editor
    got = []
    picker = FacePicker(editor)
    picker.picked.connect(got.append)
    face = str(search_stock_faces("")[0]["id"])
    picker._cells[search_stock_faces("")[0]["id"]].clicked.emit()
    assert got == [face] and picker.isVisible()            # assigned, still open to try others
    picker._cells[search_stock_faces("")[0]["id"]].activated.emit()
    assert not picker.isVisible()                          # double-click closes
    qapp.processEvents()

    # real mouse on the thumbnail image (not the cell margin) picks the head too
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from PyQt5.QtWidgets import QWidget
    got.clear()
    picker = FacePicker(editor)
    picker.picked.connect(got.append)
    second = search_stock_faces("")[1]["id"]
    thumb = picker._cells[second].thumb
    for splash in window.findChildren(QWidget, options=Qt.FindChildrenRecursively):
        if type(splash).__name__ == "IntroSplash":
            splash.hide()                                  # it covers the window in tests
    qapp.processEvents()
    # through the QWindow, so Qt hit-tests like a real click (a QWidget target
    # would get the event directly, whatever is on top of it)
    win, at = window.windowHandle(), thumb.mapTo(window, thumb.rect().center())
    QTest.mouseClick(win, Qt.LeftButton, pos=at)
    assert got == [str(second)] and picker.isVisible()
    QTest.mouseDClick(win, Qt.LeftButton, pos=at)
    from PyQt5 import sip
    assert sip.isdeleted(picker) or not picker.isVisible()   # double-click closed it
    qapp.processEvents()


def test_narrow_editor_keeps_every_tab_on_the_bar(window, qapp):
    window.resize(1000, 640)
    window.show_player_editor()
    for _ in range(5):
        qapp.processEvents()
    editor = window.screen_player_editor
    tabs = editor.shell.tabs
    assert tabs._rects()[-1].right() <= tabs.width()
    assert editor.shell.list_pane.width() <= 210
    window.resize(1600, 900)
    qapp.processEvents()


def test_player_editor_batch_changes_many_players(window, qapp):
    """SELECT ticks players; the batch form applies one change to all of
    them in one save, UNDO puts them back, DONE leaves batch mode."""
    from app import game_data as G
    G.set_edit_store(window.data.edits)
    roster = [str(p) for p in window.data.teams["10002"]["2024"]["players"] if p][:3]
    window.open_player(roster[0], "2024")
    _wait(qapp, lambda: window.screen_player_editor.record_id == roster[0], 10)
    editor = window.screen_player_editor
    before = {p: copy.deepcopy(window.data.players[p]) for p in roster}

    editor.enter_batch()
    assert editor.batch.active and editor.list.is_checkable()
    assert editor.list.checked_data() == [roster[0]]
    editor.list.set_checked(roster)
    assert editor.batch.pids() == [p for p in editor.list.checked_data()]
    assert not editor.shell.footer.save_btn.isEnabled()

    editor.batch.socks._emit("up")
    editor.batch.shift._emit("2")
    editor.batch.scope.set_value("latest")
    qapp.processEvents()
    assert editor.shell.footer.save_btn.isEnabled()
    assert editor.shell.footer.save_btn.text() == "APPLY TO 3"
    editor.batch._refresh_preview()
    assert editor.batch.preview_list.count() == 3

    assert editor.save()
    for p in roster:
        latest = max(window.data.players[p]["stats"])
        block = window.data.players[p]["stats"][latest]
        old = before[p]["stats"][latest]
        assert block["socks"] == "up"
        assert int(block["speed"]) == min(99, int(old["speed"]) + 2)
        assert window.data.edits.get("players", p)["mine"]["stats"][latest]["socks"] == "up"
    # the form is clear again, UNDO is offered
    assert editor.batch.socks.value() == "" and editor.shell.footer.revert_btn.text() == "UNDO"
    # the open record shows the new data too
    assert editor.session.working == window.data.players[roster[0]]

    editor.confirm_revert()
    for p in roster:
        assert window.data.players[p] == before[p]

    editor.leave_batch()
    assert not editor.batch.active and not editor.list.is_checkable()
    assert editor.shell.tabs.isVisible() or not editor.isVisible()
    for p in roster:
        window.data.edits.revert("players", p)
        window.data.refresh_record("players", p)
    window.show_main()


def test_player_list_ctrl_click_starts_picking(window, qapp):
    from PyQt5.QtCore import Qt
    from PyQt5.QtWidgets import QApplication
    pids = sorted(window.data.players)[:2]
    window.open_player(pids[0], None)
    _wait(qapp, lambda: window.screen_player_editor.record_id == pids[0], 10)
    editor = window.screen_player_editor
    orig = QApplication.keyboardModifiers
    QApplication.keyboardModifiers = staticmethod(lambda: Qt.ControlModifier)
    try:
        editor.list._on_row_picked(pids[1])
    finally:
        QApplication.keyboardModifiers = orig
    assert editor.batch.active and set(editor.list.checked_data()) == set(pids)
    editor.list._on_row_picked(pids[1])          # a plain click in tick mode unticks
    assert editor.list.checked_data() == [pids[0]]
    editor.leave_batch()
    window.show_main()


def test_referee_editor_new_rename_kit_delete(window, qapp, monkeypatch, tmp_path):
    """Tools' referee editor: + NEW makes a referee, a new name and kit are
    SAVEd in the user's edits, quick match lists it, DELETE takes it away."""
    from app import referees as R
    monkeypatch.setattr(config, "directory_user_edits", str(tmp_path / "edits"))
    window.data.referees = R.load()
    window.show_referee_editor()
    _wait(qapp, lambda: window.screens.currentWidget() is window.screen_referee_editor, 10)
    ed = window.screen_referee_editor
    before = set(R.load())
    ed.new_record()
    qapp.processEvents()
    rid = ed.record_id
    assert rid not in before and rid in R.load()
    ed._set_name("Test Referee")
    ed._set_kit("stock:d")
    assert ed.save()
    saved = R.load()[rid]
    assert saved["name"] == "Test Referee" and saved["kit"] == "stock:d"
    assert window.data.referees[rid]["name"] == "Test Referee"
    setup = window.screen_match_setup.setup_screen
    setup._sync_referees()
    assert (rid, "Test Referee") in setup.referee_row._values
    assert ("stock:d", "green") in setup.referee_kit_row._values
    ed.delete_record()
    dialog = ed._dialog
    assert dialog is not None
    dialog.choose("ok")
    qapp.processEvents()
    assert rid not in R.load() and rid not in window.data.referees
    window.show_main()


def test_tournament_prefs_referee_kits(qapp, monkeypatch):
    """The tournament settings' referee group: a toggle per referee kit,
    the ticked ones in option "referee_kits"."""
    from shared.user_prefs import user_prefs
    from screens.tournament.prefs import KIT_ROW, PrefsPanel
    monkeypatch.setattr(user_prefs, "expert_mode", True, raising=False)
    panel = PrefsPanel(groups=("referee",))
    seen = []
    panel.changed.connect(lambda k, v: seen.append((k, v)))
    assert KIT_ROW + "stock:a" in panel.rows and KIT_ROW + "stock:d" in panel.rows
    panel.set_values({"referee_kits": ["stock:d"]})
    assert panel.rows[KIT_ROW + "stock:d"].state() and not panel.rows[KIT_ROW + "stock:a"].state()
    panel._set_kit("stock:a", True)
    assert seen[-1] == ("referee_kits", ["stock:d", "stock:a"])
    panel._set_kit("stock:d", False)
    assert panel.values()["referee_kits"] == ["stock:a"]
    assert panel.rows[KIT_ROW + "stock:a"] in panel.focus_rows()


def test_head_picker_referees_side(window, qapp, monkeypatch, tmp_path):
    """The referee editor's head picker opens on REFEREES: the game's six
    referee heads and the mod's players/heads/referee_*.big."""
    from shared.config import config
    from ui.face_picker import FacePicker
    heads = tmp_path / "players" / "heads"
    heads.mkdir(parents=True)
    (heads / "referee_wayne_barnes.big").write_bytes(b"BIGF")
    (heads / "head_1.big").write_bytes(b"BIGF")
    monkeypatch.setattr(config, "mod_data_directory", str(tmp_path))
    picker = FacePicker(window, current="45002", referees=True)
    try:
        assert picker._mode == "referees" and picker._current == 45002
        ids = [e["id"] for e in picker._entries()]
        assert ids == [45000, 45001, 45002, 45003, 45004, 45005, "players/heads/referee_wayne_barnes.big"]
        assert picker._referee_entries()[-1]["name"] == "Wayne Barnes"
        picker.search.setText("barnes")
        assert [e["id"] for e in picker._entries()] == ["players/heads/referee_wayne_barnes.big"]
        seen = []
        picker.picked.connect(seen.append)
        picker._arm("players/heads/referee_wayne_barnes.big")
        assert seen == ["players/heads/referee_wayne_barnes.big"]
    finally:
        picker._close()
    plain = FacePicker(window, current="45002")
    try:
        assert plain._mode == "stock"
    finally:
        plain._close()


def test_quick_match_referee_rows_preview(window, qapp, monkeypatch):
    """Quick match's referee rows open a list with the hovered referee (or
    the current referee in the hovered kit) shown in 3D."""
    from app import referees as R
    from backend import referee as B
    from ui.referee_picker import RefereeRow
    monkeypatch.setattr(B, "stock_kit_paths", lambda letter, cache_dir=None: (f"kit.{letter}", "numbers"))
    monkeypatch.setattr(B.mod_utils, "stock_head_path", lambda face, cache: f"head.{face}")
    setup = window.screen_match_setup.setup_screen
    assert isinstance(setup.referee_row, RefereeRow) and isinstance(setup.referee_kit_row, RefereeRow)
    rid = next(iter(window.data.referees))
    face = window.data.referees[rid]["face"]
    setup.cfg.referee_kit = R.OWN_KIT
    assert setup._referee_preview(R.RANDOM, "") is None
    assert setup._referee_preview(R.STOCK, "")[0] == "head.45000"
    assert setup._referee_preview(rid, "stock:d")[:2] == (f"head.{face}", "kit.d")
    shown = []
    monkeypatch.setattr("ui.player_stage.KitStage.update_kit",
                        lambda self, *a, **k: shown.append((a[1], k.get("head_path"))))
    setup.referee_kit_row._open_popup()
    popup = setup.referee_kit_row._popup
    try:
        popup.hovered.emit(("stock:d", "green"))
        assert shown[-1][0] == "kit.d"
    finally:
        popup.close_popup()


def test_match_card_wind_and_weather(window, qapp):
    """Quick match's match card: wind and weather side by side; the weather
    is one of rain, snow or fog; the crowd rows are in ADVANCED."""
    from app.game_data import WEATHER
    setup = window.screen_match_setup.setup_screen
    for row in (setup.wind_power_row, setup.weather_row):
        assert not setup.advanced_panel.isAncestorOf(row)
    assert all(setup.advanced_panel.isAncestorOf(r) for r in setup.crowd_rows.values())
    setup.environment_row.set_values(["cold", "day"], index=0)
    setup._on_environment_changed()
    assert list(WEATHER) == setup.weather_row._values
    assert "fog_light" not in WEATHER

    def pick(key):
        setup.weather_row.set_index(setup.weather_row.index_of(key))
        setup.weather_row.changed.emit()
        c = setup.cfg
        return c.rain, c.precip_mode, c.snow_intensity, c.fog

    assert pick("snow") == (False, "snow", 13.0, "off")
    assert pick("rain") == (True, "stock", None, "off")
    assert pick("fog_thick") == (False, "stock", None, "thick")
    assert pick("clear") == (False, "stock", None, "off")


def test_snow_weather_cold_only_and_snow_pitch(window, qapp):
    """Snow is offered in the cold environment only and brings a snow pitch;
    elsewhere a frosty or snow pitch is never the default."""
    from backend import pitches
    setup = window.screen_match_setup.setup_screen
    setup.cfg.pitch_texture = "default"
    setup.environment_row.set_values(["day", "cold"], index=0)
    setup._on_environment_changed()
    assert "snow" not in setup.weather_row._values
    shown = setup.pitch_row.current()[0]
    assert shown == "default" or pitches.condition(shown) not in ("snow", "frosty")

    setup.environment_row.set_index(1)
    setup._on_environment_changed()
    setup.weather_row.set_index(setup.weather_row.index_of("snow"))
    setup.weather_row.changed.emit()
    assert pitches.condition(setup.cfg.pitch_texture) == "snow"
    assert setup.cfg.pitch_texture == setup.pitch_row.current()[0]

    setup.environment_row.set_index(0)          # back to day: no snow, no snow pitch
    setup._on_environment_changed()
    assert setup.weather_row.current() == "clear"
    assert setup.cfg.precip_mode == "stock"
    assert setup.cfg.pitch_texture == "default" or \
        pitches.condition(setup.cfg.pitch_texture) not in ("snow", "frosty")


def test_closed_roof_defaults_to_calm_and_clear(window, qapp):
    """The Millennium Stadium's cold scene (roof closed): no wind and clear
    weather by default; leaving it puts the picks back."""
    setup = window.screen_match_setup.setup_screen
    entries = setup.stadium_row._values
    i = next(i for i, (_sid, info) in enumerate(entries) if int(info.get("game_id", -1)) == 32)
    setup.stadium_row.set_index(i)
    setup._on_stadium_changed()
    envs = setup.environment_row._values
    other = next(e for e in envs if e != "cold")
    setup.environment_row.set_index(envs.index(other))
    setup._on_environment_changed()
    setup.weather_row.set_index(setup.weather_row.index_of("rain"))
    setup.weather_row.changed.emit()

    setup.environment_row.set_index(envs.index("cold"))
    setup._on_environment_changed()
    assert setup.weather_row.current() == "clear"
    assert setup.cfg.rain is False and setup.cfg.fog == "off"
    assert setup.wind_power_row.current() == 0

    setup.environment_row.set_index(envs.index(other))
    setup._on_environment_changed()
    assert setup.weather_row.current() == "rain"


def test_season_pane_delete_button_and_year_dropdown(window, qapp):
    """Team and player editors: no ⋯ menu by the seasons list, a DELETE
    SEASON button by the season name, and a new season's year is a dropdown
    without the seasons already there."""
    from ui.editor_kit import ChoiceField
    window.open_team("1010", "2024")
    _wait(qapp, lambda: window.screen_team_editor.record_id == "1010", 10)
    for editor in (window.screen_team_editor,):
        assert not hasattr(editor, "season_menu_btn")
        assert editor.season_delete_btn.parent() is editor.season_row
        editor.season_action("add")
        year = editor._dialog.fields["year"]
        assert isinstance(year, ChoiceField)
        assert year.value() and not set(year.options) & set(editor.session.working)
        assert year.options == sorted(year.options, reverse=True)
        editor._dialog.close()
        editor._dialog = None


def test_squad_editor_role_follows_the_shirt(qapp):
    """Replacing a starter who holds a role gives the role to the man who
    takes his shirt, not to shirt 1."""
    from screens.squad_editor import SquadEditorScreen
    players = {str(i): {"display_name": f"P{i}", "last_name": f"P{i}"} for i in range(1, 25)}
    lineup = {"players_id": [str(i) for i in range(1, 23)],
              "roles": {"captain": "10", "goalKicker": "10", "viceCaptain": "9"}}
    ed = SquadEditorScreen("home", "Team", players, lineup, lambda *a: None, lambda: None)
    ed._picker_slot = 10
    ed._on_picker_pick(23)                       # from outside the squad into shirt 10
    assert ed.roles["captain"] == 23 and ed.roles["goalKicker"] == 23
    assert ed.roles["viceCaptain"] == 9
    ed._picker_slot = 9
    ed._on_picker_pick(16)                       # a replacement moves up into shirt 9
    assert ed.roles["viceCaptain"] == 16
    ed.deleteLater()


# A 1080p laptop at 150 % scaling leaves the UI about 1280x720 of layout
# (main._fit_ui_scale), less a window title bar.
LAPTOP = (1280, 690)
_KEEP = []


def _no_vertical_scroll(widget):
    from PyQt5.QtWidgets import QScrollArea
    bars = [a.verticalScrollBar() for a in widget.findChildren(QScrollArea) if a.isVisibleTo(widget)]
    return [b.maximum() for b in bars]


def test_squad_editor_fits_a_laptop_screen(qapp):
    """Starting XV, replacements and the side panel without scrolling, also
    with a competition squad picker."""
    from screens.squad_editor import SquadEditorScreen
    players = {str(i): {"display_name": f"P{i}", "last_name": f"Player{i}", "first_name": "First",
                        "attack": 70} for i in range(1, 25)}
    lineup = {"players_id": [str(i) for i in range(1, 23)], "roles": {}}
    for variants in ((), (("world_cup", "World Cup"),)):
        ed = SquadEditorScreen("home", "Team", players, lineup, lambda *a: None, lambda: None,
                               variants=variants, load_variant=lambda vid: (players, lineup))
        ed.resize(*LAPTOP)
        ed.show()
        for _ in range(5):
            qapp.processEvents()
        body = ed._body_layout.parentWidget()
        assert ed.height() == LAPTOP[1]
        assert all(m == 0 for m in _no_vertical_scroll(ed)[:1]), variants
        assert body.minimumSizeHint().height() <= body.height(), variants
        ed.hide()
        _KEEP.append(ed)            # not deleted: queued animations still point at it


def test_full_time_with_scorers_fits_a_laptop_screen(qapp):
    """Nine statistics rows and the scorers beside them, not cut off."""
    from screens.post_match import PostMatchScreen
    screen = PostMatchScreen(on_main_menu=lambda: None)
    players = [{"id": i, "name": f"Scorer{i}", "tries": 1} for i in range(1, 7)]
    side = {"players": players, "score": {"points": 30, "tries": 6}, "stats": {}}
    screen.set_result({"team_A": {"name": "British & Irish Lions"}, "team_B": {"name": "Capibaras XV"}},
                      {"team_A": side, "team_B": side, "finished": True})
    screen.resize(*LAPTOP)
    screen.show()
    for _ in range(5):
        qapp.processEvents()
    report = screen.report
    assert screen.minimumSizeHint().height() <= LAPTOP[1]       # nothing forced the window taller
    assert report.minimumSizeHint().height() <= report.height()
    assert report.stats.height() >= report.stats.minimumHeight()
    screen.hide()
    _KEEP.append(screen)


def test_quick_match_fits_a_laptop_screen(window, qapp):
    """No scrolling on a 1080p laptop: KICK OFF moves into the header,
    the kits shrink to what is left; full size again on a big window."""
    size = window.size()
    try:
        window.resize(*LAPTOP)
        window.show_match_setup()
        for _ in range(10):
            qapp.processEvents()
        s = window.screen_match_setup.setup_screen
        assert s.body_scroll.verticalScrollBar().maximum() == 0
        assert s.play_btn.parent() is s.header_widget
        window.resize(1920, 1030)
        for _ in range(10):
            qapp.processEvents()
        assert s.play_btn.parent() is not s.header_widget
        assert s.body_scroll.verticalScrollBar().maximum() == 0
    finally:
        window.resize(size)
        qapp.processEvents()


def test_settings_use_dgvoodoo(window, qapp, monkeypatch, tmp_path):
    """Advanced > Use dgVoodoo2: ADD FILES while it is not found, then a
    toggle (on), which turns it off by choice."""
    from backend import mod_utils
    from screens.settings import TABS
    from shared.user_prefs import user_prefs
    from ui.widgets import ActionRow
    from ui import ToggleRow
    monkeypatch.setattr(user_prefs, "use_dgvoodoo", "")
    monkeypatch.setattr(user_prefs, "save", lambda: None)
    found = {"path": ""}
    monkeypatch.setattr(mod_utils, "find_dgvoodoo", lambda *a: found["path"])
    monkeypatch.setattr(mod_utils, "add_dgvoodoo",
                        lambda path: (found.update(path=path) or True, "dgVoodoo2 added."))
    from PyQt5.QtWidgets import QFileDialog
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(tmp_path / "D3D8.dll"), ""))
    screen = window.screen_settings
    advanced = TABS.index("Advanced")
    screen._fill_page(advanced)
    row = _settings_rows(screen, "Advanced")["Use dgVoodoo2"]
    assert isinstance(row, ActionRow)
    row.activate()                                   # pick the file: added, toggle on
    qapp.processEvents()
    row = _settings_rows(screen, "Advanced")["Use dgVoodoo2"]
    assert isinstance(row, ToggleRow) and row.state() and user_prefs.use_dgvoodoo == "on"
    row.adjust(1)
    assert user_prefs.use_dgvoodoo == "off"
    from ui.editor_kit import ConfirmDialog
    for dialog in screen.findChildren(ConfirmDialog):
        dialog.hide()
        dialog.deleteLater()
