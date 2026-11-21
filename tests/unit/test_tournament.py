"""app/tournament: a small competition on the fixture pack, created, simulated
(seeded, so reproducible) to the end, saved and reloaded; plus the scheduler,
standings, event bus, formats and manual results on their own."""
import copy
import itertools

import pytest

from app.tournament import engine, formats, manual, persistence, report, scheduler, selection, standings
from app.tournament.events import EventBus, bus
from app.tournament.model import MatchResult, PlayerLine, SideResult, Tournament

TEAMS = ["10002", "10001", "1015", "1010"]       # England, France, South Africa, New Zealand
TEMPLATE = {
    "id": "mini_cup", "name": "Mini Cup", "match_type": "world_cup", "venue": "neutral",
    "stages": [
        {"id": "pools", "name": "Pool", "kind": "round_robin", "legs": 1},
        {"id": "ko", "name": "Final", "kind": "knockout", "rounds": [
            {"id": "final", "name": "Final", "match_subtype": "final", "final": True,
             "ties": [["pools:A1", "pools:A2"]]}]},
    ],
    "participants": {"default": {"pools": {"A": TEAMS}}},
    "season": "2024",
}


def new(ds, seed=1234, humans=()):
    return engine.create_tournament(ds, copy.deepcopy(TEMPLATE), "2024", humans=humans, seed=seed)


def fixtures(t, stage_id):
    return [f for f in t.fixtures if f.stage_id == stage_id]


def pool_table(t):
    stage = t.stage("pools")
    return standings.group_table(t, stage, stage.group("A"))


def scores(t):
    return [(f.id, f.home, f.away, f.result.home.points, f.result.away.points)
            for f in t.fixtures if f.result]


# ── formats ──────────────────────────────────────────────────────────────
def test_template_has_no_problem(ds):
    assert formats.problems(ds, TEMPLATE, "2024", engine.default_participants(TEMPLATE, "2024")) == []


def test_template_problems(ds):
    bad = copy.deepcopy(TEMPLATE)
    bad["stages"][1]["rounds"][0]["ties"] = [["W:sf1", "pools:A2"]]
    parts = {"pools": {"A": ["10002", "10002", "999"]}}
    found = formats.problems(ds, bad, "2024", parts)
    assert "team 10002 entered twice" in found
    assert "team 999 is not in the data" in found
    assert "W:sf1: refers to a later or unknown tie" in found
    assert formats.problems(ds, {"stages": []}, "2024", {}) == \
        ["template has no round-robin stage to enter teams into"]


def test_league_editions_by_category_list_and_season_range(ds):
    """A league template's "category" may be a list (a league's old names)
    and "from_season" / "to_season" bound the seasons it covers."""
    for tid, cat in zip(TEAMS, ("Old", "Old", "New", "New")):
        for info in ds.teams[tid].values():
            info["category"] = cat
    league = {"id": "mini_league", "name": "Mini League", "category": ["Old", "New"],
              "stages": [{"id": "league", "name": "League", "kind": "round_robin", "legs": 2}]}

    def offered(tpl):
        return [e for eds in formats.editions(ds, {"mini_league": tpl}).values() for e in eds]

    assert {e.season for e in offered(league)} >= {"2024"}
    assert all(e.team_count() == 4 for e in offered(league) if e.season == "2024")
    assert not any(e.season == "2024" for e in offered(dict(league, category="Old")) if e.team_count() > 2)
    assert not any(e.season == "2024" for e in offered(dict(league, to_season="2023")))
    assert not any(e.season == "2024" for e in offered(dict(league, from_season="2025")))


def test_bundled_templates_load():
    tpls = formats.load_templates()
    assert tpls and all("stages" in t for t in tpls.values())


# ── create / simulate ────────────────────────────────────────────────────
def test_create(ds):
    t = new(ds)
    assert set(t.teams) == set(TEAMS)
    assert len(fixtures(t, "pools")) == 6
    assert len(fixtures(t, "ko")) == 1
    for tid, entry in t.teams.items():
        assert len(entry.squad) >= 22
        errors, _warnings = selection.validate(t, tid, entry.selection)
        assert errors == []
    assert not t.finished


def test_simulate_to_end(ds):
    t = new(ds)
    engine.simulate_to_end(t)
    assert t.finished
    assert all(f.played for f in t.fixtures)
    table = pool_table(t)
    final = fixtures(t, "ko")[0]
    assert {final.home, final.away} == {table[0].team_id, table[1].team_id}
    champion = engine.champion_of(t)
    assert champion == final.result.winner_id()
    assert all(engine.is_eliminated(t, tid) for tid in TEAMS if tid != champion)


def test_simulation_reproducible(ds, golden):
    a, b = new(ds, seed=99), new(ds, seed=99)
    engine.simulate_to_end(a)
    engine.simulate_to_end(b)
    assert scores(a) == scores(b)
    table = pool_table(a)
    golden("tournament_mini_cup.json", {
        "scores": [list(s) for s in scores(a)],
        "table": [[r.team_id, r.played, r.won, r.drawn, r.lost, r.points_for, r.points_against,
                   r.points] for r in table],
        "champion": engine.champion_of(a),
    })


def test_simulate_until_human_stops_at_human_fixture(ds):
    t = new(ds, humans=["10002"])
    engine.simulate_until_human(t)
    nxt = engine.next_human_fixture(t)
    assert nxt is not None and nxt.involves("10002") and not nxt.played
    assert engine.is_human_fixture(t, nxt)


def test_table_consistent_with_results(ds):
    t = new(ds, seed=7)
    engine.simulate_to_end(t)
    table = pool_table(t)
    assert sum(r.points_for for r in table) == sum(r.points_against for r in table)
    assert all(r.played == 3 and r.won + r.drawn + r.lost == 3 for r in table)
    assert [r.points for r in table] == sorted((r.points for r in table), reverse=True)


def test_report_mentions_teams_and_score(ds):
    t = new(ds)
    engine.simulate_to_end(t)
    final = fixtures(t, "ko")[0]
    text = report.match_report(t, final)
    assert t.team_name(final.home) in text and t.team_name(final.away) in text


# ── model / persistence ──────────────────────────────────────────────────
def test_model_roundtrip(ds):
    t = new(ds)
    engine.simulate_to_end(t)
    data = t.to_dict()
    assert Tournament.from_dict(copy.deepcopy(data)).to_dict() == data


def test_persistence_roundtrip(ds, data_dir):
    t = new(ds)
    engine.simulate_day(t)
    persistence.save(t)
    assert [s["id"] for s in persistence.list_saves()] == [t.id]
    loaded = persistence.load(t.id)
    assert loaded.to_dict() == t.to_dict()
    persistence.snapshot(t, "prematch")
    assert persistence.has_snapshot(t.id, "prematch")
    engine.simulate_to_end(t)
    restored = persistence.restore_snapshot(t.id, "prematch")
    assert not restored.finished
    persistence.drop_snapshot(t.id, "prematch")
    assert not persistence.has_snapshot(t.id, "prematch")
    persistence.delete(t.id)
    with pytest.raises(Exception):
        persistence.load(t.id)


def test_list_saves_reads_summaries_not_saves(ds, data_dir, monkeypatch):
    """The hub's list comes from the summaries cache; a save is parsed
    again only when its file changed. Snapshots are never listed."""
    t = new(ds)
    engine.simulate_day(t)
    persistence.save(t)
    persistence.snapshot(t, "last_match")
    persistence._index = None                 # a new start: the cache file on disk
    parsed = []
    real = persistence._from_data
    monkeypatch.setattr(persistence, "_from_data", lambda d: parsed.append(1) or real(d))
    (s,) = persistence.list_saves()
    assert not parsed
    assert s["id"] == t.id and s["where"] == report.where_now(t)
    assert s["played"] == sum(f.played for f in t.fixtures) and s["template"]["name"] == t.template["name"]
    # changed behind the cache's back (another copy of the app, a restore)
    engine.simulate_day(t)
    persistence._write(persistence._path(t.id), t.to_dict() | {"updated": "9999"})
    (s,) = persistence.list_saves()
    assert parsed and s["updated"] == "9999" and s["played"] == sum(f.played for f in t.fixtures)
    persistence.delete(t.id)
    assert persistence.list_saves() == []


def test_migrate_keeps_current_schema(ds):
    data = new(ds).to_dict()
    assert persistence.migrate(copy.deepcopy(data))["schema_version"] == data["schema_version"]


# ── manual results ───────────────────────────────────────────────────────
def test_manual_result(ds):
    t = new(ds)
    f = fixtures(t, "pools")[0]
    home_xv = t.teams[f.home].selection["players"]
    away_xv = t.teams[f.away].selection["players"]
    result = manual.build_result(t, f,
                                 [{"pid": home_xv[0], "kind": "try", "minute": 10},
                                  {"pid": home_xv[9], "kind": "conversion", "minute": 11},
                                  {"pid": home_xv[16], "kind": "yellow", "minute": 60},
                                  {"pid": "nobody", "kind": "try"}],
                                 [{"pid": away_xv[9], "kind": "penalty", "minute": 30}],
                                 home_penalty_tries=1)
    assert (result.home.points, result.away.points) == (14, 3)
    assert result.home.tries == 2 and result.home.yellow_cards == 1
    assert result.home.line(home_xv[16]).minutes == 20          # the bench player came on
    assert [e["minute"] for e in result.events] == [10, 11, 30, 60]
    engine.record_result(t, f, result)
    assert f.played


def test_manual_level_knockout_gets_a_winner(ds):
    t = new(ds)
    engine.simulate_until_human(t)
    for f in fixtures(t, "pools"):
        if not f.played:
            engine.record_result(t, f, engine.simulate_fixture(t, f) or f.result)
    final = fixtures(t, "ko")[0]
    engine.resolve_refs(t)
    r = manual.build_result(t, final, [], [], winner=final.away, decided_by="kicks")
    assert r.winner_id() == final.away and r.decided_by == "kicks"


def test_manual_injury_and_ban_lengths_apply(ds):
    t = new(ds)
    f = fixtures(t, "pools")[0]
    home_xv = t.teams[f.home].selection["players"]
    away_xv = t.teams[f.away].selection["players"]
    result = manual.build_result(t, f,
                                 [{"pid": home_xv[0], "kind": "injury", "type": "ankle sprain",
                                   "matches": 4},
                                  {"pid": home_xv[1], "kind": "red", "matches": 5}],
                                 [{"pid": away_xv[2], "kind": "suspension", "matches": 2},
                                  {"pid": away_xv[3], "kind": "red", "matches": 0}])
    engine.record_result(t, f, result)

    def cond(pid, kind):
        return [(c.matches_left, c.data) for c in t.players[pid].conditions_of(kind)]
    assert cond(home_xv[0], "injury") == [(4, {"type": "ankle sprain"})]
    assert [n for n, _ in cond(home_xv[1], "suspension")] == [5]
    assert [d["reason"] for _, d in cond(away_xv[2], "suspension")] == ["cited for foul play"]
    assert cond(away_xv[3], "suspension") == []                  # sent off, no ban
    assert result.away.points == 0                               # a suspension scores nothing


def test_manual_events_from_a_simulated_result(ds):
    import random
    from app.tournament import simulator
    t = new(ds)
    f = fixtures(t, "pools")[0]
    engine.prepare_fixture(t, f)
    sim = simulator.simulate(t, f, random.Random(3))
    home, away, hpt, apt = manual.from_result(t, sim, random.Random(3))
    assert all("matches" in e and "type" in e for e in home + away if e["kind"] == "injury")
    typed = manual.build_result(t, f, home, away, hpt, apt)
    assert (typed.home.points, typed.away.points) == (sim.home.points, sim.away.points)
    assert typed.home.tries == sim.home.tries and typed.away.red_cards == sim.away.red_cards


# ── scheduler / standings / events ───────────────────────────────────────
@pytest.mark.parametrize("n", [2, 3, 4, 5, 6, 8])
def test_round_robin(n):
    teams = [str(i) for i in range(n)]
    rounds = scheduler.round_robin(teams)
    pairs = [frozenset(p) for rnd in rounds for p in rnd]
    assert sorted(map(sorted, pairs)) == sorted(map(sorted, map(frozenset,
                                                                itertools.combinations(teams, 2))))
    for rnd in rounds:
        seen = [t for p in rnd for t in p]
        assert len(seen) == len(set(seen))                    # nobody plays twice a round


@pytest.mark.parametrize("n", [3, 4, 5, 6, 7, 12, 14])
def test_round_robin_shares_home_games(n):
    """Everyone hosts half their games (one more or less), never three
    weeks running — a Six Nations side used to play all five away."""
    rounds = scheduler.round_robin([str(i) for i in range(n)])
    venues = {}
    for rnd in rounds:
        for home, away in rnd:
            venues.setdefault(home, []).append("H")
            venues.setdefault(away, []).append("A")
    for seq in venues.values():
        assert abs(seq.count("H") - seq.count("A")) <= 1, seq
        assert "HHH" not in "".join(seq) and "AAA" not in "".join(seq), seq


def test_round_robin_two_legs_mirror():
    rounds = scheduler.round_robin(["a", "b", "c", "d"], legs=2)
    first = {p for rnd in rounds[:3] for p in rnd}
    second = {p for rnd in rounds[3:] for p in rnd}
    assert second == {(b, a) for a, b in first}
    assert scheduler.round_robin(["a"]) == []


def _side(tid, tries, points):
    lines = [PlayerLine(pid=f"{tid}{i}", tries=1) for i in range(tries)]
    s = SideResult(team_id=tid, players=lines, penalty_tries=0)
    extra = points - s.points
    if extra:
        s.players.append(PlayerLine(pid=f"{tid}k", penalties=extra // 3))
    return s


@pytest.mark.parametrize("own,opp,expected", [
    ((4, 28), (1, 20), (5, 1, 0)),           # win + try bonus (4 tries)
    ((1, 20), (4, 28), (1, 0, 1)),           # loss within 7 + losing bonus
    ((0, 9), (2, 30), (0, 0, 0)),
    ((1, 8), (1, 8), (2, 0, 0)),             # draw
])
def test_match_points_bonus(own, opp, expected):
    rules = {"win": 4, "draw": 2, "loss": 0, "try_bonus": {"tries": 4},
             "losing_bonus": {"margin": 7}}
    assert standings.match_points(rules, _side("a", *own), _side("b", *opp)) == expected


def test_event_bus_dedupes_and_orders():
    b = EventBus()
    calls = []
    b.subscribe("match_completed", lambda **k: calls.append("late"), priority=90, name="late")
    b.subscribe("match_completed", lambda **k: calls.append("early"), priority=10, name="early")
    b.subscribe("match_completed", lambda **k: calls.append("early2"), priority=10, name="early")
    b.emit("match_completed")
    assert calls == ["early2", "late"]
    with pytest.raises(ValueError):
        b.subscribe("nope", lambda **k: None)


def test_conditions_plugin_runs_first():
    for event in ("match_completed", "day_completed"):
        subs = bus.subscribers(event)
        cond = [s for s in subs if ".conditions." in s]
        if cond:
            assert subs.index(cond[0]) == 0


# ── points rules by competition and era ──────────────────────────────────
def _fixture(fid, home, away, own, opp, day=0, group="A"):
    from app.tournament.model import Fixture
    f = Fixture(id=fid, stage_id="s", day=day, home=home, away=away, group=group)
    if own is not None:
        f.result = MatchResult(home=_side(home, *own), away=_side(away, *opp), source="manual")
    return f


SIX_NEW = {"win": 4, "draw": 2, "loss": 0, "try_bonus": {"tries": 4}, "losing_bonus": {"margin": 7},
           "grand_slam": 3}


def test_grand_slam_bonus_once_every_match_is_won():
    played = [_fixture("1", "a", "b", (4, 30), (0, 6)), _fixture("2", "c", "a", (1, 10), (2, 17))]
    unplayed = _fixture("3", "b", "c", None, None)
    rows = {r.team_id: r for r in standings.table(played + [unplayed], ["a", "b", "c"], SIX_NEW)}
    assert (rows["a"].slam_bonus, rows["a"].points) == (3, 4 + 1 + 4 + 3)
    assert rows["b"].slam_bonus == 0 and rows["c"].slam_bonus == 0
    rows = {r.team_id: r for r in standings.table(played + [_fixture("4", "a", "c", None, None)],
                                                   ["a", "b", "c"], SIX_NEW)}
    assert rows["a"].slam_bonus == 0                       # a match still to play
    no_slam = dict(SIX_NEW, grand_slam=0)
    assert {r.team_id: r.slam_bonus for r in standings.table(played, ["a", "b", "c"], no_slam)}["a"] == 0


def test_pre_2017_six_nations_points_have_no_bonus():
    rules = {"win": 2, "draw": 1, "loss": 0}
    assert not standings.has_bonus(rules) and standings.has_bonus(SIX_NEW)
    assert standings.has_bonus(None)                       # the default rules have bonuses
    rows = {r.team_id: r for r in standings.table(
        [_fixture("1", "a", "b", (5, 40), (1, 36)), _fixture("2", "b", "c", (1, 8), (1, 8))],
        ["a", "b", "c"], rules)}
    assert (rows["a"].points, rows["b"].points, rows["c"].points) == (2, 1, 1)
    assert all(r.bonus == 0 for r in rows.values())


# ── a historical calendar ────────────────────────────────────────────────
def _dated_template(teams=TEAMS):
    a, b, c, d = TEAMS
    days = [("2024-02-03", a, b), ("2024-02-04", c, d), ("2024-02-10", a, c), ("2024-02-10", b, d),
            ("2024-02-24", d, a), ("2024-02-25", b, c)]
    tpl = copy.deepcopy(TEMPLATE)
    tpl["stages"][0]["fixtures"] = [{"date": dt, "group": "A", "home": h, "away": w} for dt, h, w in days]
    tpl["stages"][1]["rounds"][0]["ties"] = [{"teams": ["pools:A1", "pools:A2"], "date": "2024-03-16"}]
    tpl["participants"] = {"default": {"pools": {"A": list(teams)}}}
    return tpl


def test_weekend_dates_share_a_matchday(ds):
    t = engine.create_tournament(ds, _dated_template(), "2024", seed=3)
    days = sorted({(f.day, f.date) for f in fixtures(t, "pools")})
    assert [d for d, _ in days] == [0, 0, 1, 2, 2]          # Sat + Sun of a round, one matchday
    assert [f.label for f in fixtures(t, "pools")][:1] == ["Round 1"]   # one league: no pool name
    final = fixtures(t, "ko")[0]
    assert (final.day, final.date) == (3, "2024-03-16")


def test_stand_in_takes_over_a_missing_teams_fixtures(ds):
    tpl = _dated_template()
    for f in tpl["stages"][0]["fixtures"]:                   # the real draw had team "999"
        f["home"], f["away"] = ["999" if x == "1010" else x for x in (f["home"], f["away"])]
    t = engine.create_tournament(ds, tpl, "2024", seed=3)    # the wizard put New Zealand in
    pools = fixtures(t, "pools")
    assert all(f.date for f in pools) and sum(f.involves("1010") for f in pools) == 3
    assert fixtures(t, "ko")[0].date == "2024-03-16"


def test_changed_draw_drops_the_real_calendar(ds):
    tpl = _dated_template()
    for f in tpl["stages"][0]["fixtures"]:
        for side in ("home", "away"):
            f[side] = {"1010": "997", "1015": "998", "10001": "999"}.get(f[side], f[side])
    t = engine.create_tournament(ds, tpl, "2024", seed=3)    # three teams differ: too many
    assert all(f.round_name.startswith("Round") for f in fixtures(t, "pools"))
    final = fixtures(t, "ko")[0]
    assert final.date > max(f.date for f in fixtures(t, "pools"))   # generated, after the pools


def _cross_template(dated=False):
    """Two groups that only play each other (Nations Championship), then
    1st v 1st and 2nd v 2nd."""
    a, b, c, d = TEAMS
    tpl = copy.deepcopy(TEMPLATE)
    tpl["stages"][0].update(cross=True, group_names={"N": "North", "S": "South"})
    tpl["stages"][1]["rounds"] = [
        {"id": "p3", "name": "3rd place", "ties": [["pools:N2", "pools:S2"]]},
        {"id": "final", "name": "Final", "final": True, "ties": [["pools:N1", "pools:S1"]]}]
    tpl["participants"] = {"default": {"pools": {"N": [a, b], "S": [c, d]}}}
    if dated:
        tpl["stages"][0]["fixtures"] = [{"date": dt, "home": h, "away": w} for dt, h, w in (
            ("2024-07-06", c, a), ("2024-07-06", d, b), ("2024-11-09", a, d), ("2024-11-09", b, c))]
    return tpl


@pytest.mark.parametrize("dated", [False, True])
def test_cross_groups_play_only_each_other(ds, dated):
    t = engine.create_tournament(ds, _cross_template(dated), "2024", seed=5)
    stage = t.stage("pools")
    north, south = stage.group("N"), stage.group("S")
    pools = fixtures(t, "pools")
    assert len(pools) == 4 and len({f.day for f in pools}) == 2
    for f in pools:
        assert (f.home in north.teams) != (f.away in north.teams)      # never two of one group
    if dated:
        assert [f.date for f in pools] == ["2024-07-06"] * 2 + ["2024-11-09"] * 2
    engine.simulate_to_end(t)
    for g in (north, south):
        tab = standings.group_table(t, stage, g)
        assert [r.played for r in tab] == [2, 2] and {r.team_id for r in tab} == set(g.teams)
        points = {tid: 0 for tid in g.teams}
        for f in pools:
            for side, opp in ((f.result.home, f.result.away), (f.result.away, f.result.home)):
                if side.team_id in points:
                    points[side.team_id] += standings.match_points(t.template.get("points"), side, opp)[0]
        assert {r.team_id: r.points for r in tab} == points
    final = next(f for f in t.fixtures if f.final)
    assert final.home == standings.group_table(t, stage, north)[0].team_id
    assert final.away == standings.group_table(t, stage, south)[0].team_id
    assert t.champion == final.result.winner_id()


def test_a_tie_can_name_itself_and_be_the_final(ds):
    """Finals Weekend: one round per day, its placing matches named on their own."""
    tpl = _cross_template()
    tpl["stages"][1]["rounds"] = [{"id": "sun", "name": "Sunday", "ties": [
        {"teams": ["pools:N2", "pools:S2"], "name": "3rd place"},
        {"teams": ["pools:N1", "pools:S1"], "name": "Final", "final": True, "match_subtype": "final"}]}]
    t = engine.create_tournament(ds, tpl, "2024", seed=5)
    ko = fixtures(t, "ko")
    assert [f.label for f in ko] == ["3rd place", "Final"]
    assert [f.final for f in ko] == [False, True] and ko[1].match_subtype == "final"
    engine.simulate_to_end(t)
    assert t.champion == ko[1].result.winner_id()


def test_earlier_kick_offs_of_the_users_matchday_are_played_first(ds):
    from app.tournament.session import TournamentSession
    s = TournamentSession(engine.create_tournament(ds, _dated_template(), "2024", humans=["1010"], seed=3), ds)
    s.advance_to_human()
    f = s.human_fixture()
    assert f.date == "2024-02-04"                            # New Zealand play on the Sunday
    saturday = next(g for g in s.today() if g.date == "2024-02-03")
    assert not saturday.played                               # waits for the user's kick-off
    s.prepare(f)
    assert saturday.played and not f.played


def test_a_round_is_never_mixed_with_the_next(ds):
    """After the user's match only its round is played: the next round's
    earlier kick-offs wait for the user's next match."""
    from app.tournament.session import TournamentSession
    s = TournamentSession(engine.create_tournament(ds, _dated_template(), "2024", humans=["1010"], seed=3), ds)
    s.advance_to_human()
    f = s.human_fixture()
    done = s.simulate(f)
    assert {g.day for g in done} == {f.day}
    assert not any(g.played for g in s.t.fixtures if g.day > f.day)


def test_template_climate_overrides_the_ground(ds):
    from app.tournament import weather
    t = engine.create_tournament(ds, _dated_template(), "2024", seed=3)
    f = fixtures(t, "pools")[0]
    base = weather.forecast(t, f, ds)
    t.template["climate"] = "tropical"
    assert weather.forecast(t, f, ds)["temp"] > base["temp"]


def test_pitch_texture_follows_the_region_and_light():
    from app.tournament import weather
    assert weather.pitch_texture("muddy", "night", "Reg2") == "Reg2_08_muddy_n"
    assert weather.pitch_texture("muddy", "overcast", "Reg2") == "Reg2_08_muddy_o"
    # a wet day in Sydney stays on the Australian pack, day-lit for overcast
    assert weather.pitch_texture("muddy", "overcast", "Reg1") == "Reg1_08_norm_d"
    assert weather.pitch_texture("hard", "day", "Reg3") == "Reg3_08_hard_d"
    assert weather.pitch_texture("soggy", "night", "Reg4") == "Reg4_08_hard_n"
    assert weather.region_of(weather.climate_of({"name": "Cape Town", "country": "South Africa"})) == "Reg3"
    assert weather.region_of(weather.climate_of({"name": "Brisbane", "country": "Australia"})) == "Reg1"


def test_every_ground_gets_its_region_and_its_light(ds):
    from app.tournament import weather
    t = engine.create_tournament(ds, _dated_template(), "2024", seed=3)
    for f in t.fixtures:
        for sid, info in ds.stadiums.items():
            f.stadium_id = sid
            fc = weather.forecast(t, f, ds)
            region = weather.region_of(weather.climate_of(info))
            assert fc["pitch"].startswith(region + "_"), (info["name"], fc["pitch"])
            assert fc["environment"] in info["environments"]
            want = {"day": "d", "night": "n"}.get(fc["environment"])
            if want and region == "Reg2":
                assert fc["pitch"].endswith("_" + want), (info["name"], fc)


def test_millennium_roof_closed_in_the_rain_and_the_cold(ds):
    """Rain or cold at the Millennium Stadium closes the roof: its covered
    scene (the "cold" environment), a dry pitch and no wind."""
    from app.tournament import bridge, weather
    t = engine.create_tournament(ds, _dated_template(), "2024", seed=3)
    seen = set()
    for f in t.fixtures:
        f.stadium_id = "32"
        fc = weather.forecast(t, f, ds)
        seen.add(fc["roof_closed"])
        if fc["roof_closed"]:
            assert fc["environment"] == "cold" and fc["precip"] == "none"
            assert fc["pitch"] in ("Reg2_08_best_o", "Reg2_08_norm_o")
            assert "roof closed" in fc["summary"]
            cfg = bridge.to_match_config(ds, t, f)
            assert cfg.wind_power == 0 and not cfg.rain and cfg.environment == "cold"
        else:
            assert fc["environment"] != "cold" and fc["precip"] == "none" and fc["temp"] > weather.COLD
        f.stadium_id = "36"                     # Cardiff Arms Park next door: open to the rain
        assert not weather.forecast(t, f, ds)["roof_closed"]
    assert seen == {True, False}


def _pinned_pool_stages():
    import glob
    import json
    import os
    from conftest import REAL_DATA
    for path in sorted(glob.glob(os.path.join(REAL_DATA, "competitions", "*", "*.json"))):
        with open(path, encoding="utf-8") as fh:
            comp = json.load(fh)
        for season, entry in (comp.get("seasons") or {}).items():
            for spec in ((entry or {}).get("template") or {}).get("stages", []):
                if spec.get("kind", "round_robin") == "round_robin" and spec.get("fixtures"):
                    yield pytest.param(spec, id=f"{comp.get('id')}-{season}")


@pytest.mark.parametrize("spec", list(_pinned_pool_stages()))
def test_pinned_calendar_rounds_are_full(spec):
    """A real calendar's pool rounds each hold every pool's full set of
    matches (RWC 2023's staggered pools used to split into rounds of 8, 5, 3...)."""
    fx = sorted(spec["fixtures"], key=lambda f: (f["date"], f.get("time", "")))
    rounds = scheduler._fixed_rounds(fx)
    per_group = {}
    group = (lambda f: "x") if spec.get("cross") else (lambda f: f["group"])
    for r, f in zip(rounds, fx):
        per_group.setdefault(group(f), {}).setdefault(r, []).append(f)
    for gid, by_round in per_group.items():
        teams = {t for f in spec["fixtures"] if group(f) == gid for t in (f["home"], f["away"])}
        assert sorted(by_round) == list(range(1, len(by_round) + 1)), gid
        for r, games in by_round.items():
            assert len(games) == len(teams) // 2, (gid, r)
            playing = [t for f in games for t in (f["home"], f["away"])]
            assert len(playing) == len(set(playing)), (gid, r)


def test_cpu_squads_default_or_best(ds):
    """Teams the user doesn't manage: their own 22 in the data's slot order
    ("default", the wizard's default) or the best available ("best", also a
    tournament saved before the option)."""
    from app.tournament.model import Condition
    t = engine.create_tournament(ds, copy.deepcopy(TEMPLATE), "2024", humans=["10002"], seed=1,
                                 options={"cpu_squads": "default"})
    fra = t.teams["10001"]
    own = [p for p in fra.squad if p in t.players][:22]
    assert fra.selection["players"] == own
    assert t.teams["10002"].selection == selection.auto_select(t, "10002")   # the user's: unchanged
    hurt = t.players[own[3]]
    hurt.conditions.append(Condition(kind="injury", matches_left=2))
    sel = selection.ai_select(t, "10001")
    assert own[3] not in sel["players"] and sel["players"][:3] == own[:3]   # only the injured man changes
    assert len(sel["players"]) == 22 and selection.validate(t, "10001", sel)[0] == []
    t.options["cpu_squads"] = "best"
    assert selection.ai_select(t, "10001") == selection.auto_select(t, "10001")
    t.options.pop("cpu_squads")
    assert selection.ai_select(t, "10001") == selection.auto_select(t, "10001")
