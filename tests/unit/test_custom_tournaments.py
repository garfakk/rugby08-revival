"""Tournaments the user designs (app/tournament/custom.py): every format
compiles to a template the engine plays to a champion, the bracket is
drawn the way the screen says, problems are named on the right field, and
a saved one is offered by the wizard as a competition of its own."""
import random

import pytest

from app.tournament import custom as C
from app.tournament import engine, formats

TEAMS = ["10002", "10001", "1015", "1010"]      # England, France, South Africa, New Zealand


def _play(ds, design):
    tpl = C.compile_template(design, "my_test")
    parts = engine.default_participants(tpl, design["season"])
    assert formats.problems(ds, tpl, design["season"], parts) == []
    t = engine.create_tournament(ds, tpl, design["season"], parts, humans=[], seed=7)
    engine.simulate_to_end(t)
    assert t.finished and t.champion in TEAMS
    return tpl, t


def test_league_with_a_final(ds):
    d = C.new_design("league", name="L", season="2024", playoff_teams=2, legs=2,
                     groups=[{"name": "", "teams": TEAMS}])
    tpl, t = _play(ds, d)
    league = [f for f in t.fixtures if f.stage_id == "league"]
    assert len(league) == 12                      # 4 teams, home and away
    final = [f for f in t.fixtures if f.final]
    assert len(final) == 1 and {final[0].home_ref, final[0].away_ref} == {"league:A1", "league:A2"}
    assert C.match_count(d) == 13


def test_groups_cross_seeded_semis_and_bronze(ds):
    d = C.new_design("groups", name="G", season="2024", qualify=2, seeding="cross", third_place=True,
                     groups=[{"name": "North", "teams": TEAMS[:2]}, {"name": "", "teams": TEAMS[2:]}])
    tpl, t = _play(ds, d)
    ko = tpl["stages"][1]["rounds"]
    assert [r["id"] for r in ko] == ["sf", "bronze", "final"]
    assert ko[0]["ties"] == [["pools:A1", "pools:B2"], ["pools:B1", "pools:A2"]]
    assert ko[1]["ties"] == [["L:sf1", "L:sf2"]]
    assert tpl["stages"][0]["group_names"] == {"A": "North", "B": "Pool B"}
    assert len([f for f in t.fixtures if f.knockout]) == 4


def test_cup_draw_is_the_bracket(ds):
    d = C.new_design("cup", name="Cup", season="2024", seeding="listed",
                     groups=[{"name": "", "teams": TEAMS}], final_stadium="70")
    tpl, t = _play(ds, d)
    first = [f for f in t.fixtures if f.round_id == "sf"]
    assert [(f.home, f.away) for f in first] == [("10002", "10001"), ("1015", "1010")]
    final = next(f for f in t.fixtures if f.final)
    assert final.stadium_id == "70"
    # seeds show as teams from the start: nobody is out before playing
    t2 = engine.create_tournament(ds, tpl, "2024", engine.default_participants(tpl, "2024"), seed=1)
    assert all(not engine.is_eliminated(t2, tid) for tid in TEAMS)


def test_bracket_order_keeps_top_seeds_apart():
    assert C.bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    d = C.new_design("cup", seeding="ranked", groups=[{"name": "", "teams": [str(i) for i in range(8)]}])
    rounds = C.compile_template(d)["stages"][0]["rounds"]
    assert rounds[0]["ties"][0] == ["cup:S1", "cup:S8"]
    assert [r["name"] for r in rounds] == ["Quarter-final", "Semi-final", "Final"]


def test_top_six_playoffs_give_byes():
    d = C.new_design("league", playoff_teams=6, groups=[{"name": "", "teams": [str(i) for i in range(10)]}])
    rounds = C.compile_template(d)["stages"][1]["rounds"]
    assert rounds[0]["ties"] == [["league:A3", "league:A6"], ["league:A4", "league:A5"]]
    assert rounds[1]["ties"] == [["league:A1", "W:po2"], ["league:A2", "W:po1"]]
    assert rounds[-1]["final"]


def test_best_runners_up():
    teams = [str(i) for i in range(20)]
    d = C.new_design("groups", qualify=1, best_extra=3,
                     groups=[{"name": "", "teams": teams[i::5]} for i in range(5)])
    assert C.qualifiers(d) == 8
    ties = C.compile_template(d)["stages"][1]["rounds"][0]["ties"]
    refs = {r for tie in ties for r in tie}
    assert refs == {f"pools:P1#{k}" for k in range(1, 6)} | {f"pools:P2#{k}" for k in range(1, 4)}


def test_problems_point_at_the_field(ds):
    d = C.new_design("groups", season="2024", qualify=2,
                     groups=[{"name": "", "teams": TEAMS[:3]}, {"name": "", "teams": TEAMS[3:]}])
    keys = {k for k, _m, sev in C.problems(ds, d) if sev == "error"}
    assert {"name", "groups", "qualify"} <= keys
    cup = C.new_design("cup", name="c", season="2024", groups=[{"name": "", "teams": TEAMS[:3]}])
    assert any("2, 4, 8, 16 or 32" in m for _k, m, _s in C.problems(ds, cup))
    ok = C.new_design("league", name="ok", season="2024", groups=[{"name": "", "teams": TEAMS}])
    assert [p for p in C.problems(ds, ok) if p[2] == "error"] == []


def test_format_changes_keep_the_teams():
    d = C.new_design("league", groups=[{"name": "", "teams": [str(i) for i in range(8)]}])
    g = C.change_format(d, "groups")
    assert len(g["groups"]) == 2 and sorted(C.all_teams(g)) == sorted(C.all_teams(d))
    back = C.change_format(g, "cup")
    assert len(back["groups"]) == 1 and len(C.all_teams(back)) == 8
    three = C.set_group_count(g, 3)
    assert len(three["groups"]) == 3 and len(C.all_teams(three)) == 8
    one = C.set_group_count(three, 1)
    assert len(C.all_teams(one)) == 8


def test_auto_fill_and_shuffle(ds):
    d = C.new_design("groups", season="2024", groups=[{"name": "", "teams": []} for _ in range(2)])
    d = C.auto_fill(ds, d, "internationals", 2, random.Random(1))
    assert sorted(C.all_teams(d)) == sorted(TEAMS)
    s = C.shuffle_draw(d, random.Random(3))
    assert [len(g["teams"]) for g in s["groups"]] == [2, 2] and sorted(C.all_teams(s)) == sorted(TEAMS)


def test_saved_tournament_is_its_own_competition(ds, data_dir):
    d = C.new_design("league", name="Home Nations Cup", season="2024", branding="",
                     groups=[{"name": "", "teams": TEAMS}])
    tid = C.save(d)
    assert tid == "my_home_nations_cup"
    assert C.load_all()[tid]["name"] == "Home Nations Cup"
    tpls = formats.load_templates()
    assert tpls[tid]["custom"] and tpls[tid]["stages"][0]["kind"] == "round_robin"
    eds = formats.editions(ds, tpls)
    assert [e.id for e in eds[f"custom:{tid}"]] == [tid]
    # a name used twice gets its own id
    assert C.unique_id("Home Nations Cup", {tid}) == tid + "_2"
    C.delete(tid)
    assert tid not in C.load_all()


def test_starters_compile(ds):
    for key, _title, _sub in C.STARTERS:
        d = C.starter(ds, key, "2024")
        tpl = C.compile_template(d, "s")
        assert tpl["stages"]
    six = C.starter(ds, "six_nations", "2024")
    assert set(C.all_teams(six)) == {"10002", "10001"}      # the two the fixture pack has
