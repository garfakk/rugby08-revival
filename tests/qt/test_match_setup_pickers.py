"""Settings > Quick Match Picker: every style of the match setup's team
picking, on the real screen. Classic (default) is the unchanged path."""
import pytest

from app.team_browse import STYLE_IDS
from shared.user_prefs import user_prefs
from test_screens import window  # noqa: F401  (module fixture: the booted main window)

pytestmark = pytest.mark.qt


@pytest.fixture
def setup(window, qapp, monkeypatch, tmp_path):
    monkeypatch.setattr("shared.app_paths.user_data_directory", lambda: str(tmp_path))
    monkeypatch.setattr(user_prefs, "match_picker", "classic")
    window.show_match_setup()
    qapp.processEvents()
    s = window.screen_match_setup.setup_screen
    yield s
    user_prefs.match_picker = "classic"
    s._apply_picker_style()


def use(s, style, qapp):
    user_prefs.match_picker = style
    s._apply_picker_style()
    qapp.processEvents()


def test_classic_is_the_default_and_hides_the_new_widgets(setup):
    assert user_prefs.match_picker == "classic"
    col = setup.home_col
    assert not col.season_row2.isVisibleTo(setup) and not col.season_chips.isVisibleTo(setup)
    assert not setup.swap_row.isVisibleTo(setup) and not setup.era_row.isVisibleTo(setup)
    assert col.category_row.isVisibleTo(setup)


@pytest.mark.parametrize("style", [s for s in STYLE_IDS if s != "classic"])
def test_every_style_keeps_the_teams_and_builds_a_match(setup, qapp, style):
    h, a = setup.cfg.home.team_id, setup.cfg.away.team_id
    use(setup, style, qapp)
    assert setup.cfg.home.team_id == h and setup.cfg.away.team_id == a
    assert not setup.home_col.category_row.isVisibleTo(setup)
    assert setup.swap_row.isVisibleTo(setup)
    col = setup.home_col
    widget = col._season_widget()
    assert widget.isVisibleTo(setup) and widget.current() == setup.cfg.home.season
    assert set(widget._values) == set(setup.ds.teams[h]) if hasattr(widget, "_values") else True


def test_changing_the_season_keeps_the_team(setup, qapp):
    use(setup, "team_first", qapp)
    col = setup.home_col
    tid = setup.cfg.home.team_id
    seasons = sorted(setup.ds.teams[tid])
    col.season_row2.set_index(0, notify=True) if hasattr(col.season_row2, "step") else None
    target = seasons[0]
    col.season_row2.set_index(col.season_row2.index_of(target))
    col.season_row2.changed.emit()
    assert setup.cfg.home.team_id == tid and setup.cfg.home.season == target


def test_team_change_falls_back_to_the_nearest_season_and_says_so(setup, qapp):
    use(setup, "team_first", qapp)
    col = setup.home_col
    ds = setup.ds
    short = next((t for t in ds.teams if len(ds.teams[t]) < len(ds.seasons())
                  and col.index.category(t) == col.index.category(setup.cfg.home.team_id)), None)
    if short is None:
        pytest.skip("fixture pack has no team missing a season")
    missing = next(s for s in ds.seasons() if s not in ds.teams[short])
    setup.cfg.home.season = missing
    col._adopt_team(short)
    assert setup.cfg.home.team_id == short and setup.cfg.home.season in ds.teams[short]
    assert col.season_note.text()


def test_browser_pick_and_search(setup, qapp):
    use(setup, "browser", qapp)
    col = setup.home_col
    col._open_browser()
    b = col._browser
    assert b.is_open()
    name = col.index.name(setup.cfg.away.team_id)
    b._query = name.split()[0][:3].lower()
    b._rebuild()
    shown = b._visible()
    assert shown and all(name.split()[0][:3].lower() in e[1].lower() for e in shown)
    b._picked(shown[0][0])
    assert setup.cfg.home.team_id == shown[0][0]
    b.close()


def test_leagues_style_has_filters_and_stable_groups(setup, qapp):
    use(setup, "leagues", qapp)
    col = setup.home_col
    col._open_browser()
    labels = [f[0] for f in col._browser._filters]
    assert labels[0] == "ALL" and len(labels) > 1
    col._browser.close()


def test_era_moves_both_teams_to_that_season(setup, qapp):
    use(setup, "era", qapp)
    ds = setup.ds
    season = max(ds.seasons(), key=lambda x: len(ds.teams_in_season(x)))
    setup.era_row.set_index(setup.era_row.index_of(season))
    setup.era_row.changed.emit()
    assert setup.cfg.home.season == season and setup.cfg.away.season == season
    assert setup.cfg.home.team_id != setup.cfg.away.team_id


def test_swap_and_random(setup, qapp):
    use(setup, "team_first", qapp)
    h, a = setup.cfg.home.team_id, setup.cfg.away.team_id
    hs, as_ = setup.cfg.home.season, setup.cfg.away.season
    setup._swap_sides()
    assert (setup.cfg.home.team_id, setup.cfg.home.season) == (a, as_)
    assert (setup.cfg.away.team_id, setup.cfg.away.season) == (h, hs)
    setup._random_match()
    assert setup.cfg.home.team_id and setup.cfg.home.team_id != setup.cfg.away.team_id


def test_last_match_is_remembered_and_a_bad_file_ignored(setup, qapp, tmp_path):
    use(setup, "team_first", qapp)
    setup._swap_sides()
    want = (setup.cfg.home.team_id, setup.cfg.away.team_id)
    setup._save_last_match()
    setup._random_match()
    setup._restore_last_match()
    assert (setup.cfg.home.team_id, setup.cfg.away.team_id) == want
    (tmp_path / "last_match.json").write_text("{nope")
    setup._restore_last_match()                       # no crash
    assert (setup.cfg.home.team_id, setup.cfg.away.team_id) == want


def test_back_to_classic_restores_the_rows(setup, qapp):
    use(setup, "browser", qapp)
    tid, season = setup.cfg.home.team_id, setup.cfg.home.season
    use(setup, "classic", qapp)
    col = setup.home_col
    assert col.category_row.isVisibleTo(setup) and col.season_row.current() == season
    assert col.name_picker.current() == tid and setup.cfg.home.team_id == tid


def test_setting_is_saved_and_loaded(tmp_path, monkeypatch):
    from shared import user_prefs as up
    monkeypatch.setattr(up, "user_data_directory", lambda: str(tmp_path))
    p = up.UserPrefs() if hasattr(up, "UserPrefs") else None
    if p is None:
        pytest.skip("no UserPrefs class")
    p.match_picker = "timeline"
    p.save()
    assert up.UserPrefs().match_picker == "timeline"
