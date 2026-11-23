"""The tournament editor, driven through its own widgets on the fixture pack:
starting shapes, the multi-team picker, moving teams between pools, a draw's
order, auto-fill, save / copy / delete, and PLAY handing over to the wizard."""
import shutil
import time

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

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


def _settle(qapp, n=10):
    for _ in range(n):
        qapp.processEvents()


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    root = tmp_path_factory.mktemp("tced")
    data = str(root / "data")
    shutil.copytree(FIXTURE_DATA, data)
    mp = pytest.MonkeyPatch()
    point_config(mp, data_dir=data)
    mp.setattr(config, "directory_custom_tournaments", str(root / "custom"))
    mp.setattr(config, "directory_tournament_saves", str(root / "saves"))
    from main import MainWindow
    w = MainWindow()
    _wait(qapp, lambda: w._boot_done)
    yield w
    w._menus_ready = True
    w.close()
    w.deleteLater()
    qapp.processEvents()
    mp.undo()


@pytest.fixture
def editor(window, qapp):
    from app.tournament import custom as C
    from ui.dropdown import PopupList
    for tid in list(C.load_all()):
        C.delete(tid)
    ed = window.screen_tournament_editor
    ed._drafts.clear()
    ed.session = None
    ed.record_id = None
    ed._starting = False
    window.show_tournament_editor()
    _wait(qapp, lambda: window.screens.currentWidget() is ed)
    _settle(qapp)
    yield ed
    for p in list(PopupList._open_stack):
        p.close_popup()
    ed._dialog = None
    window.show_main()


def _popup():
    from ui.dropdown import PopupList
    return PopupList._open_stack[-1]


def test_empty_editor_offers_the_starting_shapes(editor, qapp):
    assert editor.start_panel.isVisible()
    assert not editor.shell.tabs.isVisible() and not editor.shell.preview_pane.isVisible()
    assert not editor.shell.header.issues_btn.isVisible()
    card = editor.start_panel.cards[0]
    card.setFocus()
    QTest.keyClick(card, Qt.Key_Return)             # a key picks it, no mouse needed
    _settle(qapp)
    assert editor.session is not None and editor.shell.tabs.isVisible()
    assert not editor.start_panel.isVisible()
    assert editor.d["format"] == "league"


@pytest.mark.parametrize("key", ["six_nations", "world_cup", "club_league", "champions_cup", "knockout"])
def test_starters_come_filled_from_the_best_teams(editor, qapp, key):
    from app.tournament import custom as C
    editor._create(key)
    teams = C.all_teams(editor.d)
    assert len(teams) == len(set(teams))
    assert teams or key in ("club_league", "champions_cup")      # the fixture pack has no clubs
    assert editor.record_id in editor._drafts


def test_new_asks_before_leaving_unsaved_changes(editor, qapp):
    editor._create("blank")
    editor.f_name.edited.emit("Mine")
    _settle(qapp)
    editor.new_record()
    _settle(qapp)
    assert editor._dialog is not None and not editor.start_panel.isVisible()
    editor._dialog.choose("cancel")
    _settle(qapp)
    assert editor.session.working["name"] == "Mine" and not editor._starting


def test_a_new_tournament_is_asked_about_even_untouched(editor, qapp):
    editor._create("knockout")
    first = editor.record_id
    editor.new_record()
    _settle(qapp)
    assert editor._dialog is not None
    editor._dialog.choose("discard")
    _settle(qapp)
    assert first not in editor._drafts and editor.start_panel.isVisible()
    editor._create("knockout")
    editor.request_leave()
    _settle(qapp)
    assert editor._dialog is not None
    editor._dialog.choose("cancel")
    _settle(qapp)
    assert editor.record_id in editor._drafts


def test_picker_ticks_several_teams_and_adds_them_at_once(editor, qapp):
    from app.tournament import custom as C
    editor._create("blank")
    editor.shell.tabs.set_index(1)
    editor._ask_teams(0, editor.fill_btn)
    _settle(qapp)
    pop = _popup()
    rows = [r.data for r in pop._rows]
    assert len(rows) >= 3
    bar = pop._toolbar_v.itemAt(0).widget()
    buttons = {b.text().split()[0]: b for b in bar.findChildren(type(editor.fill_btn))}
    assert not buttons["ADD"].isEnabled()
    pop._on_row_picked(rows[0])
    pop._on_row_picked(rows[1])
    assert buttons["ADD"].text() == "ADD 2" and pop.isVisible()      # stays open to tick more
    pop._on_row_picked(rows[1])                                      # ticking again unticks
    assert buttons["ADD"].text() == "ADD 1"
    buttons["ALL"].click()
    assert buttons["ADD"].text() == f"ADD {len(rows)}"
    buttons["ALL"].click()                                           # ALL again clears the shown ones
    assert not buttons["ADD"].isEnabled()
    pop._on_row_picked(rows[2])
    pop._on_row_picked(rows[0])
    buttons["ADD"].click()
    _settle(qapp)
    assert not pop.isVisible()
    assert C.all_teams(editor.d) == [rows[2], rows[0]]               # in the order ticked
    editor.undo()
    _settle(qapp)
    assert C.all_teams(editor.d) == []


def test_picker_search_narrows_what_all_ticks(editor, qapp):
    from app.tournament import custom as C
    editor._create("blank")
    editor._ask_teams(0, editor.fill_btn)
    _settle(qapp)
    pop = _popup()
    name = editor._team_name(pop._rows[0].data)
    pop.search_box.setText(name[:4])
    _settle(qapp)
    shown = [r.data for r in pop._rows]
    assert shown and all(name[:4].lower() in editor._team_name(t).lower()
                         or name[:4].lower() in str(pop._rows[i].subtitle).lower()
                         for i, t in enumerate(shown))
    bar = pop._toolbar_v.itemAt(0).widget()
    next(b for b in bar.findChildren(type(editor.fill_btn)) if b.text() == "ALL").click()
    next(b for b in bar.findChildren(type(editor.fill_btn)) if b.text().startswith("ADD")).click()
    _settle(qapp)
    assert C.all_teams(editor.d) == shown


def test_teams_move_between_pools_and_pools_are_named(editor, qapp):
    from app.tournament import custom as C
    editor._create("world_cup")
    d = editor.d
    first = d["groups"][0]["teams"][0]
    before = [len(g["teams"]) for g in d["groups"]]
    editor._ask_move(0, 0)
    _settle(qapp)
    _popup().picked.emit(1)
    _popup().close_popup()
    _settle(qapp)
    assert first in editor.d["groups"][1]["teams"] and first not in editor.d["groups"][0]["teams"]
    assert [len(g["teams"]) for g in editor.d["groups"]][:2] == [before[0] - 1, before[1] + 1]
    editor._rename_group(2, "Group of death")
    _settle(qapp)
    assert C.group_name(editor.d, 2) == "Group of death"
    editor.undo()
    editor.undo()
    _settle(qapp)
    assert editor.d["groups"][0]["teams"][0] == first


def test_cup_draw_order_is_the_seeding(editor, qapp):
    from app.tournament import custom as C
    editor._create("knockout")
    teams = C.all_teams(editor.d)
    assert len(teams) >= 2
    editor._move_team(0, 0, 1)
    _settle(qapp)
    assert C.all_teams(editor.d)[:2] == [teams[1], teams[0]]


def test_format_change_keeps_the_teams(editor, qapp):
    from app.tournament import custom as C
    editor._create("six_nations")
    teams = sorted(C.all_teams(editor.d))
    editor._pick_format("groups")
    _settle(qapp)
    assert editor.d["format"] == "groups" and len(editor.d["groups"]) >= 2
    assert sorted(C.all_teams(editor.d)) == teams
    editor._pick_format("league")
    _settle(qapp)
    assert sorted(C.all_teams(editor.d)) == teams


def test_clear_and_auto_fill(editor, qapp):
    from app.tournament import custom as C
    editor._create("blank")
    editor._ask_fill()
    _settle(qapp)
    dialog = editor._dialog
    dialog.fields["count"].set_value(4)
    dialog.fields["how"].set_value("random")
    dialog.choose("ok")
    _settle(qapp)
    assert len(C.all_teams(editor.d)) == 4
    editor._clear_teams()
    _settle(qapp)
    assert C.all_teams(editor.d) == []
    assert not editor.clear_btn.isEnabled()
    editor.undo()
    _settle(qapp)
    assert len(C.all_teams(editor.d)) == 4


def test_save_copy_open_delete(editor, qapp):
    from app.tournament import custom as C
    editor._create("knockout")
    four = C.all_teams(editor.d)[:4]
    editor._replace("four", dict(editor.d, groups=[{"name": "", "teams": four}]))
    editor.f_name.edited.emit("Test cup")
    _settle(qapp)
    assert [it for it in editor.list_rows() if it["text"] == "Test cup"]      # the list follows the name
    assert editor.save()
    tid = editor.record_id
    assert tid in C.load_all() and tid not in editor._drafts
    editor.duplicate_record()
    _settle(qapp)
    copy_id = editor.record_id
    assert copy_id != tid and editor.d["name"] == "Test cup (copy)"
    assert editor.save()
    assert {tid, copy_id} <= set(C.load_all())
    editor.request_open(tid)
    _settle(qapp)
    assert editor.record_id == tid and editor.d["format"] == "cup"
    editor.delete_record()
    editor._dialog.choose("ok")
    _settle(qapp)
    assert tid not in C.load_all() and copy_id in C.load_all()
    assert editor.record_id == copy_id                                    # lands on another one
    editor.delete_record()
    editor._dialog.choose("ok")
    _settle(qapp)
    assert editor.session is None and editor.start_panel.isVisible()


def test_issue_points_at_the_tab_and_field(editor, qapp):
    from screens import tournament_editor as TE
    editor._create("blank")
    editor.f_name.edited.emit("")
    _settle(qapp)
    assert any(k == "name" for k, _m, s in editor.issues if s == "error")
    assert not editor.play_btn.isEnabled()
    editor.shell.tabs.set_index(TE.TAB_RULES)
    editor.reveal("name")
    _settle(qapp)
    assert editor.shell.tabs.index() == TE.TAB_SETUP


def test_play_saves_and_opens_the_wizard(editor, window, qapp, monkeypatch):
    from app.tournament import custom as C
    editor._create("knockout")
    four = C.all_teams(editor.d)[:4]
    editor._replace("four", dict(editor.d, groups=[{"name": "", "teams": four}]))
    _settle(qapp)
    assert editor.play_btn.isEnabled()
    editor._play()
    tid = editor.record_id
    wiz = window.screen_tournament_wizard
    _wait(qapp, lambda: window.screens.currentWidget() is wiz)
    assert tid in C.load_all() and wiz.current_edition().id == tid


def test_tournament_editor_is_reachable_from_tools_and_the_hub(window, qapp):
    hub = window.screen_tournament_hub
    assert hub.create_tile is not None


def test_a_data_competition_can_be_edited_and_reset(editor, qapp):
    from app.tournament import custom as C, formats
    from screens import tournament_editor as TE
    stock = [tid for tid in editor.list_ids() if editor.is_base(tid)]
    assert stock
    tid = next(t for t in stock if editor._stock[t].get("participants"))
    editor.request_open(tid)
    _settle(qapp)
    assert editor.record_id == tid and editor.is_base()
    assert not editor.format_row.isVisible() or not editor.shell.tabs.isVisible()
    assert TE.TAB_SCHEDULE in editor.shell.tabs.hidden
    assert not editor.dup_btn.isEnabled() and editor.del_btn.text() == "RESET"
    import copy
    old = C.all_teams(editor.d)[0]
    new = "99999"                                   # a team of its own, outside the competition
    editor.ds.teams[new] = copy.deepcopy(editor.ds.teams[old])
    editor._replace("swap", C.swap_team(editor.d, old, new))
    editor.f_name.edited.emit("My edition")
    _settle(qapp)
    assert any("not in the data" in m for _k, m, s in editor.issues if s == "warn")   # left out, not an error
    assert editor.save()
    assert C.load_edits()[tid]["team_swaps"] == {old: new}
    assert formats.load_templates()[tid]["name"] == "My edition"
    assert [r for r in editor.list_rows() if r["id"] == tid][0]["tag"] == "EDITED"
    editor.delete_record()
    editor._dialog.choose("ok")
    _settle(qapp)
    assert tid not in C.load_edits() and editor.record_id == tid
    assert editor.d["name"] != "My edition"
    del editor.ds.teams[new]


def test_simple_steps_hide_rules_and_dates_until_more_options(editor, qapp):
    from screens import tournament_editor as TE
    editor._create("six_nations")
    _settle(qapp)
    assert editor.shell.tabs.index() == TE.TAB_TEAMS             # the shape is picked: on to the teams
    assert {TE.TAB_RULES, TE.TAB_SCHEDULE} <= editor.shell.tabs.hidden
    assert "LOOK" in editor.next_btn.text()
    editor._next_step()
    assert editor.shell.tabs.index() == TE.TAB_LOOK and not editor.next_btn.isVisibleTo(editor)
    editor._set_more(True)
    assert not ({TE.TAB_RULES, TE.TAB_SCHEDULE} & editor.shell.tabs.hidden)
    editor._set_more(False)


def test_crest_tiles_put_teams_in_and_out(editor, qapp):
    from app.tournament import custom as C
    editor._create("blank")
    _settle(qapp)
    tiles = editor.team_picker.tiles
    assert tiles
    tid = tiles[0].tid
    editor._toggle_team(tid)
    _settle(qapp)
    assert tid in C.all_teams(editor.d)
    assert next(t for t in editor.team_picker.tiles if t.tid == tid).selected
    editor._toggle_team(tid)
    _settle(qapp)
    assert tid not in C.all_teams(editor.d)


def test_look_gallery_picks_the_competition_look(editor, qapp):
    editor._create("blank")
    editor.look_gallery.picked.emit("")
    _settle(qapp)
    assert editor.look_gallery.cards[0].key == "" and editor.look_gallery.cards[0].selected
    looks = [c.key for c in editor.look_gallery.cards if c.key]
    if looks:
        editor.look_gallery.picked.emit(looks[0])
        _settle(qapp)
        assert editor.d["branding"] == looks[0]
        assert any(p.pix is not None for p in editor.look_graphics.pictures.values())
