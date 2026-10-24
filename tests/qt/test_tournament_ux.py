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
    return [b for b in (d.primary_btn, d.more_btn, d.details_btn) if b.isVisible()]


def test_home_shows_one_primary_action(dash, session):
    session.advance_to_human()
    dash.refresh()
    assert session.human_fixture() is not None
    assert dash.primary_btn.isVisible() and dash.primary_btn.text() == "PLAY MATCH"
    # secondary actions are in MORE, not on the card
    data = [d for _l, d, _s in dash._more_items()]
    assert "simulate" in data and "sim_end" in data
    assert set(_visible_buttons(dash)) == {dash.primary_btn, dash.more_btn, dash.details_btn}
    dash.primary_btn.click()
    assert dash.played == [session.human_fixture()]


def test_more_menu_lists_the_secondary_actions(qapp, dash, session):
    from ui.dropdown import PopupList
    session.advance_to_human()
    dash.refresh()
    dash._more_menu()
    qapp.processEvents()
    popup = dash._more_popup
    assert popup.isVisible() and isinstance(popup, PopupList)
    assert [r.data for r in popup._rows] == [d for _l, d, _s in dash._more_items()]
    popup.close_popup()


def test_match_details_dialog(qapp, dash, session):
    from ui.editor_kit import ConfirmDialog
    from screens.tournament.dashboard import MatchPreviewView
    session.advance_to_human()
    dash.refresh()
    dash._match_details()
    dialogs = dash.findChildren(ConfirmDialog)
    assert dialogs and isinstance(dialogs[-1].content, MatchPreviewView)
    dialogs[-1].choose("ok")


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


def test_hub_details_toggle(qapp, ds, session):
    from screens.tournament import TournamentHubScreen
    hub = TournamentHubScreen(ds, on_back=lambda: None, on_new=lambda: None, on_open=lambda *a: None)
    hub.resize(1600, 900)
    hub.show()
    hub.on_show()
    assert len(hub._cards) == 1 and hub.d_more.isHidden()
    hub.more_btn.click()
    assert not hub.d_more.isHidden() and hub.d_opts.text()
    hub.close()
