"""app/tournament/reality.py: reality mode. Two AI teams that really met get
the real score and only the real injuries / bans (exact durations, no
random roll); the user's matches are untouched; a tie the user's results
changed is simulated; it is offered only with real results and the real
draw."""
import copy

import pytest

from app.tournament import engine, reality
from app.tournament.session import TournamentSession

ENG, FRA, RSA, NZL = "10002", "10001", "1015", "1010"


def _fx(date, home, away, score, **extra):
    return dict({"date": date, "group": "A", "home": home, "away": away, "real_score": score}, **extra)


TEMPLATE = {
    "id": "real_cup", "name": "Real Cup", "match_type": "world_cup", "venue": "neutral", "season": "2024",
    "stages": [
        {"id": "pools", "name": "Pool", "kind": "round_robin", "qualify": 2, "fixtures": [
            _fx("2024-09-01", ENG, FRA, "27–10", real_events=[
                {"kind": "injury", "team": FRA, "player": "PLACEHOLDER", "matches": 2, "type": "hamstring strain"},
                {"kind": "red", "team": ENG, "player": "PLACEHOLDER_E"},
                {"kind": "suspension", "team": ENG, "player": "PLACEHOLDER_E", "matches": 3,
                 "reason": "red card"}]),
            _fx("2024-09-01", RSA, NZL, "18–18"),
            _fx("2024-09-08", ENG, RSA, "12–20"),
            _fx("2024-09-08", FRA, NZL, "cancelled (storm), 0–0 draw awarded"),
            _fx("2024-09-15", ENG, NZL, "9–30"),
            _fx("2024-09-15", FRA, RSA, "14–33"),
        ]},
        {"id": "ko", "name": "Final", "kind": "knockout", "rounds": [
            {"id": "final", "name": "Final", "match_subtype": "final", "final": True,
             "ties": [{"id": "final1", "teams": ["pools:A1", "pools:A2"], "date": "2024-09-29",
                       "real_score": "15–13"}]}]},
    ],
    "participants": {"default": {"pools": {"A": [ENG, FRA, RSA, NZL]}}},
    "history": {"champion": RSA, "pool_winners": {"A": RSA}, "pool_runners_up": {"A": NZL}},
}


def _template(ds):
    """The template, with two real player names from the fixture squads."""
    tpl = copy.deepcopy(TEMPLATE)
    t = engine.create_tournament(ds, copy.deepcopy(tpl), "2024", seed=1)
    fra = t.players[t.teams[FRA].squad[3]].base
    eng = t.players[t.teams[ENG].squad[5]].base
    ev = tpl["stages"][0]["fixtures"][0]["real_events"]
    ev[0]["player"] = f"{fra['first_name']} {fra['last_name']}"
    ev[1]["player"] = ev[2]["player"] = f"{eng['first_name']} {eng['last_name']}"
    return tpl


def test_offered_only_with_real_results_and_the_real_draw(ds):
    assert reality.available(TEMPLATE) == (True, "")
    assert reality.available(TEMPLATE, known_teams=ds.teams)[0]
    no_scores = copy.deepcopy(TEMPLATE)
    del no_scores["stages"][0]["fixtures"][2]["real_score"]
    assert not reality.available(no_scores)[0]
    assert not reality.available({"stages": [{"id": "p", "kind": "round_robin"}]})[0]
    shuffled = {"pools": {"A": [ENG, FRA, RSA, "9999"]}}
    assert reality.available(TEMPLATE, participants=shuffled) == (False, "Reality mode needs the real draw")
    assert not reality.available(TEMPLATE, known_teams=[ENG, FRA, RSA])[0]


def test_score_parsing_and_decomposition():
    assert reality.parse_score("27–10") == (27, 10, False)
    assert reality.parse_score("cancelled (storm), 0–0 draw awarded") == (0, 0, True)
    assert reality.parse_score("") is None
    for pts in range(0, 80):
        if pts in (1, 2, 4):
            continue                                  # no rugby score
        T, C, K, D = reality.decompose(pts)
        assert 5 * T + 2 * C + 3 * (K + D) == pts and C <= T
    assert reality.decompose(27, tries=0) == (0, 0, 9, 0)
    assert reality.decompose(7, tries=3)[0] == 1     # a try count that can't make the score is dropped


def test_ai_matches_get_the_real_result_and_the_real_events(ds, data_dir):
    s = TournamentSession.new(ds, _template(ds), "2024", options={"reality": True}, seed=4)
    t = s.t
    assert t.components["reality"]["final1"]["home"] == RSA            # bracket from history
    s.simulate_to_end()
    for f in t.fixtures:
        e = t.components["reality"][f.id]
        assert f.result.source == "real"
        assert [f.result.home.points, f.result.away.points] == e["score"]
    assert t.champion == RSA
    opener = t.fixture(next(f.id for f in t.fixtures if f.date == "2024-09-01" and f.home == ENG))
    tpl_ev = t.template["stages"][0]["fixtures"][0]["real_events"]
    fra_pid = reality.find_player(t, FRA, tpl_ev[0])
    eng_pid = reality.find_player(t, ENG, tpl_ev[1])
    assert fra_pid and eng_pid
    assert sum(l.red_cards for l in opener.result.home.players if l.pid == eng_pid) == 1
    texts = [n["text"] for n in t.news]
    assert any("will miss 2 matches (hamstring strain)" in x for x in texts)
    assert any("banned for 3 matches (red card)" in x for x in texts)
    # no random roll on a real result: only the real events made injury / ban news
    real_days = {n["day"] for n in t.news if n["kind"] in ("injury", "suspension")}
    assert real_days == {0}
    cancelled = next(f for f in t.fixtures if f.date == "2024-09-08" and f.home == FRA)
    assert cancelled.result.extra["reality"]["cancelled"]
    assert cancelled.result.home.points == cancelled.result.away.points == 0


def test_users_matches_stay_theirs(ds, data_dir):
    s = TournamentSession.new(ds, _template(ds), "2024", humans=[ENG], options={"reality": True}, seed=4)
    s.advance_to_human()
    f = s.human_fixture()
    assert f.involves(ENG)
    s.simulate(f)
    assert f.result.source == "sim"                     # the user's match: never the real result
    others = [g for g in s.t.fixtures if g.played and not g.involves(ENG)]
    assert others and all(g.result.source == "real" for g in others)
    # the real injury from England's own (real) match isn't applied: England played it
    assert not any("banned for 3 matches" in n["text"] for n in s.t.news)


def test_a_tie_that_never_happened_is_simulated(ds, data_dir):
    tpl = _template(ds)
    s = TournamentSession.new(ds, tpl, "2024", options={"reality": True}, seed=4)
    t = s.t
    final = t.fixture("final1")
    t.components["reality"]["final1"] = dict(t.components["reality"]["final1"], home=ENG)   # not who'll meet
    s.simulate_to_end()
    assert final.result.source == "sim" and final.result.extra["reality"] == {"diverged": True}


def test_off_by_default_and_saved_with_the_tournament(ds, data_dir):
    s = TournamentSession.new(ds, _template(ds), "2024", seed=4)
    assert "reality" not in s.t.components
    s.simulate_to_end()
    assert all(f.result.source == "sim" for f in s.t.fixtures)
    on = TournamentSession.new(ds, _template(ds), "2024", options={"reality": True}, seed=4)
    again = TournamentSession.load(on.t.id, ds)
    assert again.t.components["reality"] == on.t.components["reality"] and again.t.options["reality"]


@pytest.mark.qt
def test_wizard_offers_reality_mode_only_where_it_can_be_played(qapp, ds, data_dir, monkeypatch):
    from app.tournament import formats
    from screens.tournament import TournamentWizardScreen
    real = _template(ds)
    open_cup = dict(copy.deepcopy(TEMPLATE), id="open_cup", name="Open Cup")
    for st in open_cup["stages"]:
        for f in st.get("fixtures", []):
            f.pop("real_score")
    monkeypatch.setattr(formats, "load_templates", lambda: {"real_cup": real, "open_cup": open_cup})
    created = []
    w = TournamentWizardScreen(ds, on_back=lambda: None, on_created=created.append)
    w.resize(1400, 900)
    w.show()
    w.on_show()
    w._pick_competition("open_cup")
    assert not w._reality_offered and not w.reality_row.isVisibleTo(w)
    w._pick_competition("real_cup")
    assert w._reality_offered
    w.reality.set_value("on")
    parts = w.participants()
    parts["pools"]["A"] = list(reversed(parts["pools"]["A"]))       # same teams, other order: still real
    w._build_groups(parts)
    assert not any("real draw" in p for p in w._step_problems()[1])
    w._go(1)
    w._start()
    assert not created                                   # no team taken for you
    w._toggle_human(parts["pools"]["A"][0])
    w._start()
    assert created and created[0].t.options["reality"] is True and created[0].t.components["reality"]
    w.close()
