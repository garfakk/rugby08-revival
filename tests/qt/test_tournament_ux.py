"""Tournament mode's screens: one primary action on the dashboard's Home,
the rest in MORE / MATCH DETAILS, the moments an action plays (matchday
recap, new stage, champions), the Competition views, the intro and the hub.

Animations are off (user_prefs.animations) unless a test says otherwise:
every moment then opens on its final frame and closes on the next key."""
import copy

import pytest
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

pytestmark = pytest.mark.qt

TEMPLATE = {
    "id": "mini_cup", "name": "Mini Cup", "match_type": "world_cup", "venue": "neutral",
    "stages": [
        {"id": "pools", "name": "Pool", "kind": "round_robin", "legs": 1, "qualify": 2},
        {"id": "ko", "name": "Final", "kind": "knockout", "rounds": [
            {"id": "final", "name": "Final", "match_subtype": "final", "final": True,
             "ties": [["pools:A1", "pools:A2"]]}]},
    ],
    "participants": {"default": {"pools": {"A": ["10002", "10001", "1015", "1010"]}}},
    "season": "2024",
}
HUMAN = "10002"


@pytest.fixture
def no_motion(monkeypatch):
    from shared.user_prefs import user_prefs
    monkeypatch.setattr(user_prefs, "animations", False)


@pytest.fixture
def session(ds, data_dir, no_motion):
    from app.tournament.session import TournamentSession
    return TournamentSession.new(ds, copy.deepcopy(TEMPLATE), "2024", humans=[HUMAN], seed=5)


@pytest.fixture
def dash(qapp, ds, session):
    from screens.tournament import TournamentDashboardScreen
    played = []
    d = TournamentDashboardScreen(ds, on_back=lambda: None, on_play=lambda s, f: played.append(f))
    d.played = played
    d.resize(1600, 900)
    d.set_session(session)
    d.show()
    d.on_show()
    qapp.processEvents()
    yield d
    d.close()
    d.deleteLater()


def _overlays(d):
    from screens.tournament.moments import MomentOverlay
    return [m for m in d.findChildren(MomentOverlay) if m.isVisible()]


def _close_all(qapp, d, limit=10):
    seen = []
    for _ in range(limit):
        shown = _overlays(d)
        if not shown:
            break
        seen.append(type(shown[0]).__name__)
        QTest.keyClick(shown[0], Qt.Key_Return)
        qapp.processEvents()
    return seen


def _visible_buttons(d):
    return [b for b in (d.primary_btn, d.more_btn) if b.isVisible()]


@pytest.fixture
def expert(monkeypatch):
    from shared.user_prefs import user_prefs
    monkeypatch.setattr(user_prefs, "expert_mode", True)


def test_home_shows_one_primary_action(dash, session, expert):
    session.advance_to_human()
    dash.refresh()
    assert session.human_fixture() is not None
    assert dash.primary_btn.isVisible() and dash.primary_btn.text() == "PLAY MATCH"
    # secondary actions are in MORE, not on the card
    data = [d for _l, d, _s in dash._more_items()]
    assert "simulate" in data and "sim_end" in data
    assert set(_visible_buttons(dash)) == {dash.primary_btn, dash.more_btn}
    dash.primary_btn.click()
    assert dash.played == [session.human_fixture()]


def test_more_is_expert_only(dash, session):
    """No MORE out of expert mode (no undo, no your matches there)."""
    session.advance_to_human()
    dash.refresh()
    assert dash._more_items() == [] and not dash.more_btn.isVisible()


def test_expert_actions_are_tagged(qapp, dash, session, expert):
    session.advance_to_human()
    dash.refresh()
    dash._more_menu()
    qapp.processEvents()
    tags = {r.data: r.tag for r in dash._more_popup._rows}
    assert tags["simulate"] == tags["sim_title"] == tags["sim_end"] == "EXPERT"
    dash._more_popup.close_popup()


def test_simulate_to_the_title_match(qapp, dash, session, expert):
    """MORE > Simulate to your title match: the dialog's PLAYS FOR THE TITLE
    (the default) simulates up to the users' final or decider, won on the
    way; then the item is gone."""
    from app.tournament import engine
    from ui.editor_kit import ConfirmDialog
    session.advance_to_human()
    dash.refresh()
    assert any(d == "sim_title" for _l, d, _s in dash._more_items())
    dash._sim_to_title()
    qapp.processEvents()
    [d for d in dash.findChildren(ConfirmDialog) if d.isVisible()][-1].choose("ok")
    qapp.processEvents()
    due = session.human_fixture()
    human = next(tid for tid, e in session.t.teams.items() if e.human)
    if due is not None:
        assert engine.is_title_match(session.t, due)
        assert all(f.result.winner_id() == human for f in session.t.fixtures
                   if f.played and f.involves(human))
    assert not any(d == "sim_title" for _l, d, _s in dash._more_items())


def test_match_simulation_form(qapp, ds, session):
    from screens.tournament.manual_result import ManualResultView
    session.advance_to_human()
    f = session.human_fixture()
    session.prepare(f)
    view = ManualResultView(session.t, f)
    assert view.result().source == "manual" and view.result().home.points == 0
    view.auto_generate()
    generated = view.result()
    assert generated.source == "sim" and "manual" in generated.extra
    # an edit turns it into a typed-in result with the same lines
    view.home.add_row()
    view.home.rows[-1].set_event({"minute": 79, "kind": "try", "pid": view.home.players[0][0]})
    edited = view.result()
    assert edited.source == "manual" and edited.home.points == generated.home.points + 5
    view.deleteLater()


def test_more_menu_lists_the_secondary_actions(qapp, dash, session, expert):
    from ui.dropdown import PopupList
    session.advance_to_human()
    dash.refresh()
    dash._more_menu()
    qapp.processEvents()
    popup = dash._more_popup
    assert popup.isVisible() and isinstance(popup, PopupList)
    assert [r.data for r in popup._rows] == [d for _l, d, _s in dash._more_items()]
    popup.close_popup()


def test_home_shows_the_rest_of_the_round(qapp, dash, session):
    """Home: the round next to NEXT MATCH, the round's other matches under
    the hero; no tags, no match details."""
    session.advance_to_human()
    dash.refresh()
    f = session.human_fixture()
    assert dash.hero_round.text() == f.label.upper()
    others = [g for g in session.t.fixtures if g.day == f.day and g is not f]
    assert dash.round_grid.count() == len(others) and dash.round_section.isVisibleTo(dash)
    assert not hasattr(dash, "details_btn") and not hasattr(dash.home_block, "tags")


def test_simulating_plays_the_matchday_recap(qapp, dash, session):
    session.advance_to_human()
    dash.refresh()
    f = session.human_fixture()
    dash._run(lambda: session.simulate(f))
    qapp.processEvents()
    shown = _overlays(dash)
    assert shown and type(shown[0]).__name__ == "MatchdayRecap"
    assert shown[0].mine is f and shown[0].settled          # animations off: the final frame
    assert "MatchdayRecap" in _close_all(qapp, dash)
    assert not _overlays(dash)
    assert dash.tabs.index() == 0 and dash.primary_btn.isVisible()


def test_playing_to_the_end_shows_the_champions(qapp, dash, session):
    seen = []
    for _ in range(12):
        if session.t.finished:
            break
        f = session.human_fixture()
        dash._run((lambda f=f: session.simulate(f)) if f else session.advance_to_human)
        qapp.processEvents()
        seen += _close_all(qapp, dash)
        if not f and not session.human_fixture():
            # out of the running: the rest is simulated
            played = {g.id for g in session.t.fixtures if g.played}
            dash._run(lambda: (session.simulate_to_end(),
                               [g for g in session.t.fixtures if g.played and g.id not in played])[1])
            seen += _close_all(qapp, dash)
    assert session.t.finished
    assert "ChampionMoment" in seen
    assert "StageCard" in seen                          # pools -> the final
    assert dash.primary_btn.text() == "SEE THE AWARDS"
    dash.primary_btn.click()
    assert dash.tabs.index() == 3


def test_moments_after_nothing_played_is_empty(ds, session):
    from screens.tournament import moments
    assert moments.moments_after(ds, session.t, moments.snapshot(session.t), []) == []


def test_competition_views(qapp, dash):
    from screens.tournament.dashboard import BRACKET, COMP, FIXTURES, TABLE
    dash.tabs.set_index(COMP)
    assert dash.view_pages.currentIndex() == TABLE
    dash._set_view(FIXTURES)
    assert dash.view_pages.currentIndex() == FIXTURES and dash.fixtures.rowCount() > 0
    dash._set_view(BRACKET)
    assert dash.view_pages.currentIndex() == BRACKET
    # X cycles the views
    QTest.keyClick(dash, Qt.Key_X)
    assert dash.view_pages.currentIndex() == TABLE


def test_home_links_open_the_details(qapp, dash):
    from screens.tournament.dashboard import COMP, FIXTURES, NEWS
    dash._open_view(FIXTURES)
    assert dash.tabs.index() == COMP and dash.view_pages.currentIndex() == FIXTURES
    dash._go_tab(NEWS)
    assert dash.tabs.index() == NEWS


def test_animations_on_do_not_crash(qapp, dash, session, monkeypatch):
    """With motion on: tab fades, staggered cards and a recap playing out."""
    from shared.user_prefs import user_prefs
    monkeypatch.setattr(user_prefs, "animations", True)
    for i in range(5):
        dash.tabs.set_index(i)
        qapp.processEvents()
        dash.refresh()
    dash.tabs.set_index(0)
    session.advance_to_human()
    f = session.human_fixture()
    dash._run(lambda: session.simulate(f))
    shown = _overlays(dash)
    assert shown and not shown[0].settled
    QTest.keyClick(shown[0], Qt.Key_Return)              # first key: the final frame
    assert shown[0].settled
    QTest.qWait(50)
    for _ in range(6):
        for m in _overlays(dash):
            QTest.keyClick(m, Qt.Key_Return)
            QTest.keyClick(m, Qt.Key_Return)
        QTest.qWait(250)
    assert not _overlays(dash)


def test_recap_rides_out_a_stall(qapp, dash, session, monkeypatch):
    """A slow frame (the window coming back from the game) moves the recap on
    by MAX_STEP_MS at most, the recap covers the dashboard (opaque: nothing
    behind is repainted) and the garbage collector waits until it settles."""
    import gc
    import time
    from shared.user_prefs import user_prefs
    from screens.tournament import moments
    monkeypatch.setattr(user_prefs, "animations", True)
    session.advance_to_human()
    f = session.human_fixture()
    dash._run(lambda: session.simulate(f))
    recap = _overlays(dash)[0]
    assert not gc.isenabled()
    time.sleep(0.4)
    recap._tick()
    assert 0 < recap._ms <= moments.MAX_STEP_MS
    assert recap.testAttribute(Qt.WA_OpaquePaintEvent)
    recap.skip()
    assert gc.isenabled()
    QTest.keyClick(recap, Qt.Key_Return)                 # closing: fades over the dashboard
    assert not recap.testAttribute(Qt.WA_OpaquePaintEvent)
    for _ in range(6):
        for m in _overlays(dash):
            m.skip()
            m.close_moment()
        QTest.qWait(250)
    assert not _overlays(dash) and gc.isenabled()


def test_intro_skips_to_the_dashboard(qapp, ds, session):
    from screens.tournament import TournamentIntroScreen
    done = []
    intro = TournamentIntroScreen(ds, lambda: done.append(True))
    intro.set_session(session)
    intro.resize(1280, 720)
    intro.show()
    intro.on_show()
    assert intro._ms == intro._duration                  # animations off: the whole draw
    assert sum(len(t) for _n, t in intro._columns) == 4
    intro.grab()                                          # paints without error
    QTest.keyClick(intro, Qt.Key_Return)
    assert done == [True]
    intro.close()


def test_hub_lists_saves_by_state_and_deletes_after_asking(qapp, ds, session):
    """NEW TOURNAMENT on its own; the saves under IN PROGRESS / COMPLETED,
    no preview; the card's delete zone asks first."""
    from PyQt5.QtCore import Qt
    from PyQt5.QtTest import QTest
    from screens.tournament import TournamentHubScreen
    from ui.editor_kit import ConfirmDialog
    news = []
    hub = TournamentHubScreen(ds, on_back=lambda: None, on_new=lambda: news.append(1),
                              on_open=lambda *a: None)
    hub.resize(1600, 900)
    hub.show()
    hub.on_show()
    assert len(hub._cards) == 1 and not hasattr(hub, "detail")
    assert hub.sections["progress"][0].isVisibleTo(hub) and not hub.sections["done"][0].isVisibleTo(hub)
    hub.new_tile.activated.emit()
    assert news
    QTest.mouseClick(hub._cards[0].delete_zone, Qt.LeftButton)
    dialog = [d for d in hub.findChildren(ConfirmDialog) if d.isVisible()][-1]
    dialog.choose("cancel")
    assert len(hub._cards) == 1
    QTest.mouseClick(hub._cards[0].delete_zone, Qt.LeftButton)
    [d for d in hub.findChildren(ConfirmDialog) if d.isVisible()][-1].choose("ok")
    assert not hub._cards and not hub.sections["progress"][0].isVisibleTo(hub)
    hub.close()


def test_match_stats_rows(ds, session):
    from app.tournament import report
    session.advance_to_human()
    f = session.human_fixture()
    session.simulate(f)
    r = f.result
    rows = {label: (h, a) for label, h, a in report.match_stats(r)}
    assert rows["TRIES"] == (r.home.tries, r.away.tries)
    assert rows["TACKLES"] == (sum(l.tackles for l in r.home.players), sum(l.tackles for l in r.away.players))
    assert "SCRUMS WON" not in rows                     # simulated: the game's team stats are unknown
    r.home.stats, r.away.stats = {"scrums_won": 5}, {"scrums_won": 3, "lineouts_won": 9}
    rows = {label: (h, a) for label, h, a in report.match_stats(r)}
    assert rows["SCRUMS WON"] == (5, 3) and rows["LINEOUTS WON"] == (0, 9)


def test_your_matches_filter_and_static_stats(qapp, dash, session):
    """Fixtures: nothing highlighted under ALL MATCHES; YOUR MATCHES is its
    own table, one row per match. The stats' tables can't be picked."""
    from screens.tournament.dashboard import FIXTURES, STATS
    from screens.tournament.common import DataTable
    from PyQt5.QtWidgets import QAbstractItemView
    session.advance_to_human()
    f = session.human_fixture()
    dash._run(lambda: session.simulate(f))
    _close_all(qapp, dash)
    dash._open_view(FIXTURES)
    assert dash.fixtures.current_key() is None
    assert dash.fixtures.selectionMode() == QAbstractItemView.NoSelection
    # a REPORT button on each played match, opening its report
    from ui.editor_kit import ConfirmDialog
    from screens.tournament.dashboard import MatchReportView
    played = [g for g in session.t.fixtures if g.played]
    assert played and len(dash.fixtures.row_buttons) == len(played)
    dash.fixtures.row_buttons[0].click()
    dialog = [d for d in dash.findChildren(ConfirmDialog) if d.isVisible()][-1]
    assert isinstance(dialog.content, MatchReportView)
    dialog.choose("ok")
    dash._set_mine(True)
    assert dash.my_fixtures.isVisibleTo(dash) and not dash.fixtures.isVisibleTo(dash)
    mine = [g.id for g in sorted(session.t.fixtures, key=lambda g: g.day) if g.involves(HUMAN)]
    assert dash.my_fixtures.keys == mine
    dash.tabs.set_index(STATS)
    tables = [t for t in dash.pages[STATS].findChildren(DataTable)]
    assert tables and all(t.selectionMode() == QAbstractItemView.NoSelection for t in tables)


def test_recap_opens_the_match_report_and_says_forfeited(qapp, ds, session):
    """A match played in the game: the recap's MATCH STATS (X) opens the
    match report popup (as the Competition tab's REPORT); a forfeit reads
    FORFEITED, not DEFEAT."""
    from ui.editor_kit import ConfirmDialog
    from screens.tournament.dashboard import MatchReportView
    from PyQt5.QtWidgets import QWidget
    from screens.tournament import moments
    host = QWidget()
    host.resize(1600, 900)
    host.show()
    session.advance_to_human()
    f = session.human_fixture()
    before = moments.snapshot(session.t)
    result = {"finished": True,
              "team_A": {"score": {"points": 12, "tries": 2}, "stats": {}, "players": []},
              "team_B": {"score": {"points": 3, "penalties": 1}, "stats": {}, "players": []}}
    session.begin_game(f)
    done = session.finish_game(f, result)
    recap = moments.moments_after(ds, session.t, before, done, game=({}, result))[0]
    recap.open(host)
    assert recap.backdrop_alpha() == 1.0 and recap.stats_popup is None
    QTest.keyClick(recap, Qt.Key_X)
    assert isinstance(recap.stats_popup, ConfirmDialog)
    assert isinstance(recap.stats_popup.content, MatchReportView)
    recap.stats_popup.choose("ok")
    assert recap.stats_popup is None and recap.isVisible()
    QTest.keyClick(recap, Qt.Key_Return)
    session2_before = moments.snapshot(session.t)
    g = session.human_fixture() or (session.advance_to_human() and session.human_fixture())
    if g:
        done = session.forfeit(g, HUMAN)
        recap = moments.moments_after(ds, session.t, session2_before, done)[0]
        assert recap.outcome()[0] == "FORFEITED"
    host.close()


def test_post_match_shows_stats(qapp, no_motion):
    from screens.post_match import PostMatchScreen
    screen = PostMatchScreen(lambda: None)
    screen.resize(1600, 900)
    screen.show()
    result = {"team_A": {"score": {"points": 12, "tries": 2}, "stats": {"scrums_won": 4}, "players": []},
              "team_B": {"score": {"points": 3, "penalties": 1}, "stats": {}, "players": []}}
    screen.set_result({"team_A": {"name": "A"}, "team_B": {"name": "B"}}, result)
    assert screen.stats_card.isVisible() and screen.stats.progress == 1.0
    assert ("TRIES", 2, 0) in screen.stats.rows
    screen.set_result({"team_A": {}, "team_B": {}}, None)              # no result: said so
    assert screen.stats.rows == [("NO RESULT READ FROM THE GAME", 0, 0)]
    screen.close()


def test_settings_tab_changes_the_tournament_options(dash, session):
    """SETTINGS: the wizard's match options, changed for the rest of the
    tournament and saved at once; the squad rules are fixed (no rows)."""
    from screens.tournament.dashboard import PREFS
    from app.tournament import persistence
    session.t.options.update(difficulty="pro", injuries=True)
    dash._go_tab(PREFS)
    rows = dash.prefs.rows
    assert rows["difficulty"].current() == "Pro"
    assert not {"injuries", "fatigue", "suspensions"} & set(rows)
    rows["difficulty"].adjust(1)
    assert session.t.options["difficulty"] == "elite" and session.t.options["injuries"] is True
    assert persistence.load(session.t.id).options["difficulty"] == "elite"


def test_mid_match_start_config():
    """A start at a minute with a score: the stock mid-match restart and
    .mis score events."""
    from app.challenges import kick_off_start, mid_match_start, possible_scores, score_shape
    from app.state import MatchConfig
    assert 1 not in possible_scores() and 2 not in possible_scores() and 4 not in possible_scores()
    assert {0, 3, 5, 7, 99} <= set(possible_scores())
    cfg = MatchConfig()
    mid_match_start(cfg, 78, 24, 13)
    pts = {"SS_TRY": 5, "SS_CONVERSION": 2, "SS_PENALTY": 3, "SS_DROPGOAL": 3}
    total = {"home": 0, "away": 0}
    for ev in cfg.score_events:
        total[ev["team"]] += pts[ev["type"]]
        assert 0 < ev["time"] < 78 * 60
    assert total == {"home": 24, "away": 13}
    assert (cfg.mission_mode_time, cfg.mission_mode_period, cfg.mission_mode_name) == (4680, 1, "")
    assert cfg.mission_nis[0]["script_name"] == "kick_off"
    kick_off_start(cfg)
    assert cfg.mission_mode_time is None and not cfg.score_events and not cfg.mission_nis
    assert score_shape(1) is None


def test_more_play_from_a_given_minute(qapp, dash, session, monkeypatch):
    """Expert MORE > Play from a given minute: 78th and 0-0 to start with,
    passed to on_play as start=(minute, home, away)."""
    from shared.user_prefs import user_prefs
    from ui.editor_kit import ConfirmDialog
    from ui import CycleRow
    monkeypatch.setattr(user_prefs, "expert_mode", True)
    session.advance_to_human()
    dash.refresh()
    assert any(d == "late_start" for _l, d, _s in dash._more_items())
    calls = []
    dash.on_play = lambda s, f, start=None: calls.append((f, start))
    dash._late_start()
    dialog = [d for d in dash.findChildren(ConfirmDialog) if d.isVisible()][-1]
    rows = dialog.content.findChildren(CycleRow)
    assert rows[0].current() == "78'"
    rows[1].adjust(1)                 # home: 3
    dialog.choose("ok")
    assert calls and calls[0][1] == (78, 3, 0)


def test_squad_tab_keyboard_and_picker(qapp, dash, session):
    """Down from the tab bar enters the team sheet; A opens the picker on
    that shirt; picking a player already in the 22 swaps the two shirts."""
    from PyQt5.QtWidgets import QApplication
    from screens.tournament.dashboard import TEAM
    from ui.team_sheet import SlotAvatar
    dash.tabs.set_index(TEAM)
    dash.tabs.setFocus()
    qapp.processEvents()
    QTest.keyClick(dash.tabs, Qt.Key_Down)
    qapp.processEvents()
    shirt = QApplication.focusWidget()
    assert isinstance(shirt, SlotAvatar) and shirt.number == 1
    sq = dash.squad
    before = list(sq._sel()["players"])
    QTest.keyClick(shirt, Qt.Key_Return)
    qapp.processEvents()
    assert sq.picker.isVisible()
    sq._on_pick(before[1])                       # number 2 onto number 1
    after = sq._sel()["players"]
    assert after[0] == before[1] and after[1] == before[0] and len(after) == 22
    sq.picker.hide()
    qapp.processEvents()
    QTest.keyClick(QApplication.focusWidget(), Qt.Key_Escape)   # back to the tabs
    qapp.processEvents()
    assert QApplication.focusWidget() is dash.tabs


def test_squad_roles_panel_sets_roles(qapp, dash, session):
    from screens.tournament.dashboard import TEAM
    dash.tabs.set_index(TEAM)
    qapp.processEvents()
    sq = dash.squad
    starters = sq._sel()["players"][:15]
    sq.toggle_panel("roles")
    assert sq._panel == "roles"
    sq.role_fields["captain"].edited.emit(starters[4])
    assert sq._sel()["roles"]["captain"] == starters[4]
    sq.play_fields["up"].edited.emit("loop")
    assert sq._sel()["set_plays"]["up"] == "loop"
    sq.toggle_panel("roles")
    assert sq._panel is None


def test_squad_lineups_panel(qapp, dash, session):
    """Auto pick until a shirt changes; a lineup saved under a name is
    shown as the current one and loads back; the squad view lists the 22."""
    from app.tournament import lineups
    from screens.tournament.dashboard import TEAM
    dash.tabs.set_index(TEAM)
    qapp.processEvents()
    sq = dash.squad
    entry = session.t.teams[sq.team_id]
    assert lineups.is_auto(entry) and sq.mode_field.value() == "auto"
    sq._swap(0, 2)
    assert not lineups.is_auto(entry) and sq.mode_field.value() == "default"
    session.save_lineup(sq.team_id, "Props swapped")
    sq.refresh()
    assert "PROPS SWAPPED" in sq.lineup_title.text()
    sq._auto()
    assert "PROPS SWAPPED" not in sq.lineup_title.text()
    sq._load(lineups.saved(entry)[0])
    assert "PROPS SWAPPED" in sq.lineup_title.text()
    sq.view_tabs.set_index(1)
    qapp.processEvents()
    assert sq.table.keys.count(None) >= 1 and len([k for k in sq.table.keys if k]) == len(entry.squad)


def test_squad_list_takes_any_player_to_the_sheet(qapp, dash, session):
    """A on a player of the 22 goes to his shirt; on one outside the 22,
    to the picker on the shirt that suits him, him highlighted: one more A
    puts him in. B in the list goes back to the team sheet, not the tabs."""
    from PyQt5.QtWidgets import QApplication
    from screens.tournament.dashboard import TEAM
    from screens.tournament.squad import SHEET, SQUAD_VIEW
    from ui.team_sheet import SlotAvatar, SubChip
    dash.tabs.set_index(TEAM)
    qapp.processEvents()
    sq = dash.squad
    sq.view_tabs.set_index(SQUAD_VIEW)
    qapp.processEvents()
    assert sq.name_lbl.text() not in ("", "—", "EMPTY")      # the panel follows the list
    outsider = sq.table.keys[-1]
    assert outsider not in sq._players()
    sq.table.setFocus()
    sq.table.setCurrentCell(len(sq.table.keys) - 1, 1)
    QTest.keyClick(sq.table, Qt.Key_Return)
    qapp.processEvents()
    assert sq.views.currentIndex() == SHEET and sq.picker.isVisible()
    assert sq.picker.highlighted_pid() == outsider
    slot = sq._picker_slot
    sq._on_pick(sq.picker.highlighted_pid())
    sq.picker.hide()
    assert sq._players()[slot] == outsider
    sq.view_tabs.set_index(SQUAD_VIEW)
    sq.table.setFocus()
    qapp.processEvents()
    QTest.keyClick(sq.table, Qt.Key_Escape)
    qapp.processEvents()
    assert sq.views.currentIndex() == SHEET
    assert isinstance(QApplication.focusWidget(), (SlotAvatar, SubChip))


def test_squad_lineup_use_keeps_the_focus_in_the_panel(qapp, dash, session):
    """USE rebuilds the rows: the focus lands on the used row's next button,
    not on the deleted USE button (keys would go nowhere)."""
    from PyQt5.QtWidgets import QApplication
    from app.tournament import lineups
    from screens.tournament.dashboard import TEAM
    dash.tabs.set_index(TEAM)
    qapp.processEvents()
    sq = dash.squad
    sq._swap(0, 2)
    session.save_lineup(sq.team_id, "A")
    sq._swap(3, 4)
    session.save_lineup(sq.team_id, "B")
    sq.refresh()
    sq.toggle_panel("lineups")
    qapp.processEvents()
    use = sq._row_buttons[0][0]
    assert use.text() == "USE"
    use.setFocus()
    QTest.keyClick(use, Qt.Key_Return)
    for _ in range(3):
        qapp.processEvents()
    assert lineups.matching(sq._entry(), sq._sel()) == 0
    assert QApplication.focusWidget() is sq._row_buttons[0][0]
    assert sq._row_buttons[0][0].text() == "RENAME"
    assert "YOUR LINEUP · A" == sq.lineup_title.text()


def test_squad_auto_pick_asks_before_dropping_an_unsaved_lineup(qapp, dash, session):
    from ui.editor_kit import ConfirmDialog
    from screens.tournament.dashboard import TEAM
    dash.tabs.set_index(TEAM)
    qapp.processEvents()
    sq = dash.squad
    assert not sq.auto_btn.isVisible() or sq._auto_mode() is False   # auto mode: no button
    sq._swap(0, 2)
    mine = list(sq._players())
    sq._auto()
    dialogs = [w for w in sq.window().findChildren(ConfirmDialog) if w.isVisible()]
    assert dialogs and sq._players() == mine
    dialogs[-1].choose("ok")
    qapp.processEvents()
    assert sq._players() != mine


def test_squad_list_rates_the_22_like_the_sheet(qapp, dash, session):
    """The matchday 22 are rated in their shirt (the sheet's number), the
    rest at their own position; each section header says which."""
    from screens.tournament.dashboard import TEAM
    from screens.tournament.squad import SQUAD_VIEW
    dash.tabs.set_index(TEAM)
    qapp.processEvents()
    sq = dash.squad
    sq.view_tabs.set_index(SQUAD_VIEW)
    qapp.processEvents()
    players = sq._players()
    for row, pid in enumerate(sq.table.keys):
        if pid in players:
            slot = players.index(pid)
            assert sq.table.item(row, 3).text() == sq.shirts[slot + 1].value
    sections = [sq.table.item(r, 0).data(Qt.UserRole + 5) for r, k in enumerate(sq.table.keys) if k is None]
    assert sections[0] == "rating: in his shirt" and sections[1] == "rating: at his own position"


def test_squad_picker_keeps_off_the_side_panel(qapp, dash, session):
    from PyQt5.QtCore import QPoint
    from screens.tournament.dashboard import TEAM
    dash.resize(1920, 1080)
    dash.tabs.set_index(TEAM)
    qapp.processEvents()
    sq = dash.squad
    sq._open_picker(19)                       # a replacement on the right
    qapp.processEvents()
    pop = sq.picker._popup
    assert pop.isVisible()
    assert pop.geometry().right() < sq.side_card.mapTo(sq, QPoint(0, 0)).x()
    sq.picker.hide()


def test_squad_fits_a_short_window(qapp, dash, session):
    """1280x720: 15 joins the back row and nothing on the squad page scrolls."""
    from PyQt5.QtWidgets import QScrollArea
    from screens.tournament.dashboard import TEAM
    dash.resize(1280, 720)
    dash.tabs.set_index(TEAM)
    for _ in range(5):
        qapp.processEvents()
    sq = dash.squad
    sq._fit_shirts()
    for _ in range(5):
        qapp.processEvents()
    assert sq.sheet_rows[-2].indexOf(sq.shirts[15]) >= 0
    area = next(a for a in dash.findChildren(QScrollArea) if a.isAncestorOf(sq))
    assert area.widget().height() <= area.viewport().height()
    dash.resize(1920, 1080)
    for _ in range(5):
        qapp.processEvents()
    sq._fit_shirts()
    assert sq.sheet_rows[-1].indexOf(sq.shirts[15]) >= 0


def test_squad_edited_saved_lineup_updates_or_reverts(qapp, dash, session):
    """A saved lineup changed on the sheet is shown as edited: UPDATE writes
    the change into it, REVERT puts it back on the sheet."""
    from app.tournament import lineups
    from screens.tournament.dashboard import TEAM
    dash.tabs.set_index(TEAM)
    qapp.processEvents()
    sq = dash.squad
    entry = session.t.teams[sq.team_id]
    sq._swap(0, 2)
    session.save_lineup(sq.team_id, "Plan A")
    sq.refresh()
    original = list(sq._players())
    sq._swap(3, 4)
    assert sq.lineup_title.text() == "YOUR LINEUP · PLAN A (EDITED)"
    assert sq._edited_index() == 0
    assert [b.text() for b in sq._row_buttons[0]][:2] == ["UPDATE", "REVERT"]
    sq._load(lineups.saved(entry)[0], row=0)            # REVERT
    assert sq._players() == original and sq.lineup_title.text() == "YOUR LINEUP · PLAN A"
    sq._swap(3, 4)
    edited = list(sq._players())
    sq._update(0)                                        # UPDATE
    assert lineups.saved(entry)[0]["players"] == edited
    assert sq.lineup_title.text() == "YOUR LINEUP · PLAN A" and sq._edited_index() is None
    sq._do_auto()                                        # no longer from Plan A
    assert lineups.source(entry) is None
