"""The tattoo / skin editor, driven through its own buttons on the real main
window: every control that rebuilds part of the editor while it is being
clicked (layer rows, settings chips, catalogue) must not take the clicked
widget down with it, and no slot may raise (an exception in a Qt slot ends
the program)."""
import shutil
import sys
import time

import pytest
from PyQt5.QtCore import Qt, QPoint
from PyQt5.QtTest import QTest
from PyQt5.QtWidgets import QPushButton

from conftest import FIXTURE_DATA, point_config

pytestmark = pytest.mark.qt


def _wait(qapp, predicate, timeout=60.0):
    end = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() > end:
            raise TimeoutError("UI did not get there in time")
        qapp.processEvents()
        time.sleep(0.005)


def _settle(qapp, n=5):
    for _ in range(n):
        qapp.processEvents()
        time.sleep(0.01)


@pytest.fixture(scope="module")
def window(qapp, tmp_path_factory):
    data = str(tmp_path_factory.mktemp("tattoo") / "data")
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


@pytest.fixture
def slot_errors(monkeypatch):
    """Exceptions raised in Qt slots (PyQt5 would abort on them)."""
    errors = []
    monkeypatch.setattr(sys, "excepthook", lambda *exc: errors.append(exc))
    return errors


def _open(window, qapp, start="add"):
    from screens.player_tabs import AppearanceTab
    from ui.tattoo_editor import TattooEditor
    pid = next(p for p, r in window.data.players.items() if len(r.get("stats") or {}) > 1)
    window.open_player(pid, None)
    _wait(qapp, lambda: window.screen_player_editor.record_id == pid, 10)
    screen = window.screen_player_editor
    tab = next(t for t in screen.tabs if isinstance(t, AppearanceTab))
    tab._open_tattoos(start)
    _settle(qapp)
    ed = next(c for c in screen.children() if isinstance(c, TattooEditor) and not c._closed)
    return screen, tab, ed


def _click(qapp, w):
    QTest.mouseClick(w, Qt.LeftButton, Qt.NoModifier, w.rect().center())
    _settle(qapp, 3)


def _row_buttons(ed):
    rows = [ed.list_v.itemAt(i).widget() for i in range(ed.list_v.count())]
    rows = [r for r in rows if r is not None and r.findChildren(QPushButton)]
    return [r.findChildren(QPushButton) for r in rows]


def test_tattoo_editor_clicks(window, qapp, slot_errors):
    screen, tab, ed = _open(window, qapp)
    try:
        # pick a spot, then add a few shapes from the catalogue
        QTest.mouseClick(ed.map, Qt.LeftButton, Qt.NoModifier, QPoint(ed.map.width() // 3, ed.map.height() // 2))
        _settle(qapp)
        _wait(qapp, lambda: ed.grid.count() > 0, 10)
        tiles = [ed.grid.itemAt(i).widget() for i in range(ed.grid.count())]
        for t in tiles[:3]:
            _click(qapp, t)
        assert len(ed.design["layers"]) == 3
        ed.mode.set_value("layers", emit=True)
        _settle(qapp)

        # every button of every layer row, rows rebuilt under the pointer
        for _ in range(2):
            for buttons in _row_buttons(ed):
                _click(qapp, buttons[0])               # show / hide
                break
        _click(qapp, _row_buttons(ed)[1][1])           # select by name
        assert ed.sel_id
        n = len(ed.design["layers"])
        _click(qapp, _row_buttons(ed)[0][2])           # ▲
        _click(qapp, _row_buttons(ed)[1][3])           # ▼
        top = ed.design["layers"][-1]["id"]
        _click(qapp, _row_buttons(ed)[0][4])           # ✕ on the top one (not necessarily selected)
        assert len(ed.design["layers"]) == n - 1 and top not in [L["id"] for L in ed.design["layers"]]
        assert len(_row_buttons(ed)) == n - 1           # the list follows

        # the selected tattoo's settings: chips and toggles rebuild the panel
        ed.set_selected(ed.design["layers"][0]["id"])
        _settle(qapp)
        host = ed.props_scroll.widget()
        for label in ("FLAT", "REAL INK", "LEFT", "BOTH", "LEG", "ARM", "MIRROR", "ALL ROUND"):
            b = next((b for b in ed.props_scroll.widget().findChildren(QPushButton)
                      if b.text() == label and b.isVisible()), None)
            if b is not None:
                _click(qapp, b)
        assert ed.props_scroll.widget() is not host

        # undo / redo everything, a ready-made design, the skin page
        while ed._undo:
            ed.undo()
        _settle(qapp)
        while ed._redo:
            ed.redo()
        _settle(qapp)
        ed.mode.set_value("add", emit=True)
        ed.cat.set_value("Ready-made", emit=True)
        _settle(qapp)
        _click(qapp, ed.grid.itemAt(0).widget())
        ed.mode.set_value("skin", emit=True)
        _settle(qapp)
        ed.skin_sliders["light"].s.setValue(150)
        _settle(qapp)
        assert not slot_errors, slot_errors
    finally:
        ed._close()
        _settle(qapp)
        screen.session.revert()


def test_tattoo_editor_save(window, qapp, slot_errors):
    from app.tattoos import store
    screen, tab, ed = _open(window, qapp)
    try:
        QTest.mouseClick(ed.map, Qt.LeftButton, Qt.NoModifier, QPoint(ed.map.width() // 3, ed.map.height() // 2))
        _wait(qapp, lambda: ed.grid.count() > 0, 10)
        _click(qapp, ed.grid.itemAt(0).widget())
        _click(qapp, ed.save_btn)
        assert ed._closed
        assert store.tattoo_of(tab.stats())
        assert not slot_errors, slot_errors
        # open again on the saved design
        _, _, ed = _open(window, qapp)
        assert len(ed.design["layers"]) == 1
        ed._close()
    finally:
        _settle(qapp)
        screen.session.revert()


def test_tattoo_map_sides_and_default(window, qapp, slot_errors, tmp_path):
    """Left arm/leg drawn left of the right ones; new tattoos go on one side."""
    screen, tab, ed = _open(window, qapp)
    try:
        rects, _ = ed.map._layout()
        assert rects[("arm", "b")].x() < rects[("arm", "a")].x() < rects[("leg", "b")].x() < rects[("leg", "a")].x()
        assert ed.side_mode == "one" and ed.side_chips.value() == "one"
    finally:
        ed._close()
        _settle(qapp)
        screen.session.revert()
    assert not slot_errors
