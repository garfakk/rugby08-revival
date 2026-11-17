"""A data update is used right away: MainWindow.reload_data() reads the mod
data again and rebuilds the screens built on it, with no restart."""
import json
import os
import shutil
import time

import pytest

from conftest import FIXTURE_DATA, point_config

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
    data = str(tmp_path_factory.mktemp("reload") / "data")
    shutil.copytree(FIXTURE_DATA, data)
    mp = pytest.MonkeyPatch()
    point_config(mp, data_dir=data)
    # no user's-files mirror in tests: the data folder is read as it is
    from shared.config import config
    mp.setattr(config, "refresh_mod_data", lambda: None)
    from main import MainWindow
    w = MainWindow()
    _wait(qapp, lambda: w._boot_done)
    w.data_dir = data
    yield w
    w._menus_ready = True
    w.close()
    w.deleteLater()
    qapp.processEvents()
    mp.undo()


def test_reload_uses_the_new_data_without_a_restart(window, qapp):
    from main import DATA_SCREENS
    window.show_tools()
    window.show_updates()
    qapp.processEvents()
    old_data = window.data
    old = {name: getattr(window, "screen_" + name) for name in DATA_SCREENS}

    path = os.path.join(window.data_dir, "teams", "England", "england.json")
    with open(path, encoding="utf-8") as f:
        teams = json.load(f)
    tid = next(iter(teams))
    for info in teams[tid].values():
        info["name"] = "Reloaded XV"
    with open(path, "w", encoding="utf-8") as f:
        json.dump(teams, f)

    result = []
    window.reload_data(result.append)
    _wait(qapp, lambda: result)
    assert result == [None]
    assert window.data is not old_data
    assert all(s.get("name") == "Reloaded XV" for s in window.data.teams[tid].values())
    for name, before in old.items():
        after = getattr(window, "screen_" + name)
        assert after is not before and window.screens.indexOf(before) < 0, name
        assert window.screens.indexOf(after) >= 0, name
    # still on the updates screen, and Back goes to the new tools screen
    assert window.screens.currentWidget() is window.screen_updates
    assert window.screens._history[-1] is window.screen_tools
    window.show_team_editor()
    qapp.processEvents()
    assert window.screens.currentWidget() is window.screen_team_editor
    window.show_match_setup(new=True)
    qapp.processEvents()
    assert window.screens.currentWidget() is window.screen_match_setup


def test_updates_screen_loads_installed_data_in_place(qapp):
    """Install / undo say the data is in use once loaded, not "restart"."""
    from screens.updates import UpdatesScreen, RESTART
    calls = []
    screen = UpdatesScreen(lambda: None, on_data_changed=calls.append)
    screen._apply("Installed Test (1 file).", "#fff")
    assert screen._busy() and "Loading" in screen.status.text()
    calls[0](None)
    assert not screen._busy()
    assert "in use" in screen.status.text() and RESTART not in screen.status.text()
    screen._apply("Installed Test (1 file).", "#fff")
    calls[1]("disk full")
    assert RESTART in screen.status.text()
    screen.deleteLater()


def test_match_setup_follows_team_editor_saves(window, qapp):
    """A team saved in the editor shows in match setup without a restart:
    a new kit is offered, the kit picked stays; a deleted team is replaced."""
    import copy
    window.show_match_setup()
    qapp.processEvents()
    screen = window.screen_match_setup.setup_screen
    ds = window.data
    col = screen.home_col
    tid, season = col._slot().team_id, col._slot().season
    picked = col.kit_row.current()
    seasons = copy.deepcopy(ds.teams[tid])
    kits = seasons[season]["kits"]
    kits["third"] = copy.deepcopy(next(iter(kits.values())))
    ds.register_team(tid, seasons, ds.teams_folder_path[tid], ds.teams_file_path[tid])
    qapp.processEvents()
    assert "third" in list(col._slot().kits(ds))
    assert col.kit_row.index_of("third") is not None
    assert col.kit_row.current() == picked

    other = screen.away_col._slot().team_id
    ds.unregister_team(other)
    qapp.processEvents()
    assert screen.away_col._slot().team_id not in (other, None, "")
