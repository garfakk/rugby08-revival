"""Settings > Advanced > Quick Match Picker: the classic season > category > team rows
and the groups picker (default), group > team > season, on the real screen."""
import pytest

from app.team_browse import info_group

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


def test_classic_hides_the_group_widgets(setup):
    assert user_prefs.match_picker == "classic"
    col = setup.home_col
    assert not col.group_picker.isVisibleTo(setup) and not col.season_row2.isVisibleTo(setup)
    assert col.category_row.isVisibleTo(setup) and col.season_row.isVisibleTo(setup)


def test_groups_keep_the_teams_and_list_only_their_seasons(setup, qapp):
    h, a = setup.cfg.home.team_id, setup.cfg.away.team_id
    use(setup, "groups", qapp)
    assert setup.cfg.home.team_id == h and setup.cfg.away.team_id == a
    col = setup.home_col
    assert not col.category_row.isVisibleTo(setup)
    assert col.group_picker.isVisibleTo(setup) and col.season_row2.isVisibleTo(setup)
    assert col.group_picker.current() == col.index.group(h)
    assert col.season_row2._values == sorted(setup.ds.teams[h])
    assert col.season_row2.current() == setup.cfg.home.season
    assert col.season_row2._use_popup()                   # a dropdown, whatever the setting
    assert h in col.name_picker._values
    assert all(col.index.group(t) == col.group_picker.current() for t in col.name_picker._values)


def test_changing_the_season_keeps_the_team(setup, qapp):
    use(setup, "groups", qapp)
    col = setup.home_col
    tid = setup.cfg.home.team_id
    target = sorted(setup.ds.teams[tid])[0]
    col.season_row2.set_index(col.season_row2.index_of(target))
    col.season_row2.changed.emit()
    assert setup.cfg.home.team_id == tid and setup.cfg.home.season == target


def test_changing_the_group_picks_its_first_team(setup, qapp):
    use(setup, "groups", qapp)
    col = setup.home_col
    groups = col.group_picker._values
    other = next(g for g in groups if g != col.group_picker.current())
    col.group_picker.set_values(groups, index=groups.index(other))
    col.group_picker.changed.emit()
    tid = setup.cfg.home.team_id
    assert col.index.group(tid) == other and tid == col.index.in_group(other)[0]
    assert setup.cfg.home.season in setup.ds.teams[tid]


def test_team_change_falls_back_to_the_nearest_season(setup, qapp):
    use(setup, "groups", qapp)
    col = setup.home_col
    ds = setup.ds
    short = next((t for t in ds.teams if len(ds.teams[t]) < len(ds.seasons())
                  and t != setup.cfg.home.team_id), None)
    if short is None:
        pytest.skip("fixture pack has no team missing a season")
    missing = next(s for s in ds.seasons() if s not in ds.teams[short])
    setup.cfg.home.season = missing
    col._adopt_team(short)
    assert setup.cfg.home.team_id == short and setup.cfg.home.season in ds.teams[short]


@pytest.mark.parametrize("style", ["classic", "groups"])
def test_random_opening_is_one_season_and_group(setup, qapp, style):
    use(setup, style, qapp)
    ds, ix = setup.ds, setup.home_col.index
    for _ in range(30):
        setup.roll_opening()
        h, a = setup.cfg.home, setup.cfg.away
        assert h.team_id != a.team_id and h.season == a.season
        assert info_group(ds.teams[h.team_id][h.season]) == info_group(ds.teams[a.team_id][a.season])
        assert ix.group(h.team_id) == ix.group(a.team_id)


def _pairs(window, qapp, setup, new, n=12):
    seen = set()
    for _ in range(n):
        window.show_main()
        qapp.processEvents()
        window.show_match_setup(new=new)
        qapp.processEvents()
        seen.add((setup.cfg.home.team_id, setup.cfg.home.season,
                  setup.cfg.away.team_id, setup.cfg.away.season))
    return seen


def test_groups_roll_a_new_pair_from_the_menu(window, setup, qapp):
    use(setup, "groups", qapp)
    assert len(_pairs(window, qapp, setup, new=True)) > 1
    h, a = setup.cfg.home, setup.cfg.away
    assert h.team_id != a.team_id and h.season == a.season


def test_return_to_the_screen_keeps_the_pair(window, setup, qapp):
    use(setup, "groups", qapp)
    window.show_match_setup(new=True)
    qapp.processEvents()
    assert len(_pairs(window, qapp, setup, new=False)) == 1   # back from the game


def test_classic_keeps_its_pick_from_the_menu(window, setup, qapp):
    window.show_match_setup(new=True)
    qapp.processEvents()
    assert len(_pairs(window, qapp, setup, new=True)) == 1


def test_back_to_classic_restores_the_rows(setup, qapp):
    use(setup, "groups", qapp)
    tid, season = setup.cfg.home.team_id, setup.cfg.home.season
    use(setup, "classic", qapp)
    col = setup.home_col
    assert col.category_row.isVisibleTo(setup) and col.season_row.current() == season
    assert col.name_picker.current() == tid and setup.cfg.home.team_id == tid


def test_setting_is_saved_and_an_old_style_falls_back(tmp_path, monkeypatch):
    from shared import user_prefs as up
    monkeypatch.setattr(up, "user_data_directory", lambda: str(tmp_path))
    p = up.UserPrefs() if hasattr(up, "UserPrefs") else None
    if p is None:
        pytest.skip("no UserPrefs class")
    assert up.UserPrefs().match_picker == "groups"     # the default
    p.match_picker = "classic"
    p.save()
    assert up.UserPrefs().match_picker == "classic"
    p.match_picker = "timeline"                       # a style that no longer exists
    p.save()
    assert up.UserPrefs().match_picker == "groups"



def _ground(s, game_id):
    s.stadium_row.set_index(next(i for i, (_sid, info) in enumerate(s._stadium_list)
                                 if info["game_id"] == game_id))
    s._on_stadium_changed()


def _environment(s, name):
    s.environment_row.set_index(s.environment_row.index_of(name))
    s.environment_row.changed.emit()


@pytest.mark.parametrize("mode", ["advanced", "standard"])
def test_closed_roof_means_no_wind(setup, monkeypatch, mode):
    """The Millennium Stadium's cold scene is the roof closed: the wind
    row goes to none and the match gets no wind, whatever Settings > Wind
    says; any other ground or light gets its wind back."""
    monkeypatch.setattr(user_prefs, "wind_mode", mode)
    setup.wind_power_row.set_index(setup.wind_power_row.index_of(3))
    _ground(setup, 32)
    _environment(setup, "day")
    assert setup.cfg.wind_power == (3 if mode == "advanced" else None)
    _environment(setup, "cold")
    assert setup.cfg.wind_power == 0
    setup._roll_wind()
    assert setup.cfg.wind_power == 0
    _environment(setup, "night")
    setup._roll_wind()
    assert setup.cfg.wind_power == (3 if mode == "advanced" else None)
    _environment(setup, "cold")
    _ground(setup, 14)                       # an open ground
    setup._roll_wind()
    assert setup.cfg.wind_power == (3 if mode == "advanced" else None)
