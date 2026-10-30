"""app/difficulty.py: club/pro/elite map onto the stock AI; legend/immortal
boost only the CPU side against a human side."""
import copy

import pytest

from app import difficulty as D
from app import star_classes as SC

POSITIONS = ["loosehead_prop", "hooker", "tighthead_prop", "second_row", "second_row",
             "blindside_flanker", "openside_flanker", "number_eight", "scrum_half",
             "fly_half", "winger", "centre", "centre", "winger", "fullback"] + ["centre"] * 7


def _team(rating=50):
    players = []
    for pos in POSITIONS:
        p = {k: rating for k in D.RATING_KEYS}
        p.update(pos1=pos, height=180, weight=100, special_ability=0, star_attribute=0)
        players.append(p)
    return {"players": players, "roles": {"long_GK": 15}}


@pytest.mark.parametrize("level,expected", [
    ("club", 0), ("pro", 1), ("elite", 2), ("legend", 2), ("immortal", 2), ("unknown", 2),
])
def test_mission_difficulty(level, expected):
    assert D.mission_difficulty(level) == expected


def test_boosted_levels_in_selectors():
    assert D.LEVELS == ["club", "pro", "elite", "legend", "immortal"]
    assert set(D.PROFILES) <= set(D.MISSION_DIFFICULTY)


@pytest.mark.parametrize("home,away,expected", [
    (1, 0, ["team_B"]), (0, 1, ["team_A"]), (1, 1, []), (0, 0, []), (2, 0, ["team_B"]),
])
def test_cpu_teams(home, away, expected):
    assert D.cpu_teams(home, away) == expected


@pytest.mark.parametrize("level", ["club", "pro", "elite"])
def test_stock_levels_change_nothing(level):
    md = {"team_A": _team(), "team_B": _team()}
    before = copy.deepcopy(md)
    assert D.apply(md, level, 1, 0) == before


@pytest.mark.parametrize("home,away", [(1, 1), (0, 0)])
def test_no_boost_without_exactly_one_human_side(home, away):
    md = {"team_A": _team(), "team_B": _team()}
    before = copy.deepcopy(md)
    assert D.apply(md, "immortal", home, away) == before


@pytest.mark.parametrize("level", ["legend", "immortal"])
def test_apply_boosts_cpu_and_tires_human(level):
    md = {"team_A": _team(), "team_B": _team()}
    D.apply(md, level, 1, 0)
    prof = D.PROFILES[level]
    cpu, human = md["team_B"]["players"], md["team_A"]["players"]
    for p in cpu:
        assert all(p[k] >= prof["rating_floor"] for k in D.RATING_KEYS)
        assert all(p[k] >= prof["mental_floor"] for k in D.MENTAL_KEYS)
        assert all(0 <= p[k] <= 99 for k in D.RATING_KEYS)
    for p in human:
        assert all(p[k] <= prof["human_endurance_cap"] for k in D.ENDURANCE_KEYS)
        assert p["attack"] == 50                      # only endurance touched
    assert md["cpu_edge"] == prof["cpu_edge"]


def test_cpu_edge_only_for_boosted_human_vs_cpu():
    for level, home, away in [("elite", 1, 0), ("immortal", 1, 1), ("immortal", 0, 0)]:
        md = {"team_A": _team(), "team_B": _team()}
        D.apply(md, level, home, away)
        assert "cpu_edge" not in md


@pytest.mark.parametrize("level", ["legend", "immortal"])
def test_cpu_team_floor_and_chemistry_skills(level):
    team = _team()
    team["roles"] = {"long_GK": 15, "captain": 7, "short_GK": 10}
    out = D.boost_team(team, level)
    assert out["performance_floor"] == {k: D.PROFILES[level]["team_floor"] for k in D.TEAM_PERFORMANCE}
    players = out["players"]
    for shirt, skills in D.CHEMISTRY_SKILLS.items():
        assert all(players[shirt - 1][s] for s in skills)
    assert players[6]["ss_command"] and players[9]["ss_goal_kicker"]
    assert "performance_floor" not in team


def test_immortal_cpu_edge_beyond_legend():
    legend, immortal = D.PROFILES["legend"]["cpu_edge"], D.PROFILES["immortal"]["cpu_edge"]
    assert set(legend) == set(immortal)
    numbers = [k for k in legend if not isinstance(legend[k], str)]
    assert all(immortal[k] > legend[k] for k in numbers)
    assert all(0 < immortal[k] <= 100 for k in numbers)
    for level in (legend, immortal):
        zones = [int(v) for v in level["cpu_fh_kick"].split(",")]
        assert len(zones) == 4 and zones == sorted(zones, reverse=True)


def test_boost_does_not_mutate_input():
    team = _team()
    before = copy.deepcopy(team)
    D.boost_team(team, "legend")
    assert team == before


def test_ratings_clamped_at_99():
    out = D.boost_team(_team(rating=95), "immortal")
    assert max(p[k] for p in out["players"] for k in D.RATING_KEYS) == 99


def test_forwards_grow_backs_dont():
    out = D.boost_team(_team(), "immortal")["players"]
    prof = D.PROFILES["immortal"]
    assert out[0]["weight"] == 100 + prof["forward_weight_kg"]
    assert out[0]["height"] == 180 + prof["forward_height_cm"]
    assert out[9]["weight"] == 100                    # fly half


def test_skills_per_level():
    # position skills only (boost_team adds the chemistry ones on top)
    fly_half = _team()["players"][9]
    legend = D.boost_player(fly_half, D.PROFILES["legend"])
    immortal = D.boost_player(fly_half, D.PROFILES["immortal"])
    skills = D.POSITION_SKILLS["fly_half"]
    assert [s for s in skills if legend.get(s)] == skills[:2]
    assert [s for s in skills if immortal.get(s)] == skills


def test_tendency_set_only_when_default():
    team = _team()
    team["players"][0]["special_ability"] = 4          # hand-set: kept
    out = D.boost_team(team, "legend")["players"]
    assert out[0]["special_ability"] == 4
    assert out[1]["special_ability"] == D.POSITION_TENDENCY["hooker"]


def test_goal_kicker_tendency_for_long_gk_shirt():
    out = D.boost_team(_team(), "legend")["players"]
    assert out[14]["special_ability"] == D.TENDENCY_GOALKICKER     # shirt 15 = long_GK


def test_stars_legend_some_starters_no_front_five():
    out = D.boost_team(_team(), "legend")["players"]
    stars = [i for i, p in enumerate(out) if p.get("star_attribute")]
    assert len(stars) == D.PROFILES["legend"]["stars"]
    assert all(i < D.STARTERS for i in stars)
    assert all(i >= 5 for i in stars)                                  # no front five
    assert {9, 8, 6} <= set(stars)                                     # 10, 9, 7 first


def test_stars_fit_the_position():
    out = D.boost_team(_team(), "immortal")["players"]
    for p in out:
        assert SC.position_fit(p["star_attribute"], p["pos1"]) > 0
    assert SC.CLASSES[out[9]["star_attribute"]][0][0] == "fly_half"
    assert SC.CLASSES[out[8]["star_attribute"]][0][0] == "scrum_half"


def test_stars_immortal_whole_team_distinct_backs():
    out = D.boost_team(_team(), "immortal")["players"]
    assert all(p.get("star_attribute") for p in out)
    backs = [p["star_attribute"] for p in out[8:15]]
    assert len(set(backs)) == len(backs)


def test_stars_follow_ratings():
    team = _team()
    team["players"][10].update(speed=99, acceleration=99, strength=20)    # pure pace
    team["players"][13].update(strength=99, handling=99, speed=60)       # power wing
    out = D.boost_team(team, "immortal")["players"]
    assert out[10]["star_attribute"] in {6, 10, 22}                      # speed wingers
    assert out[13]["star_attribute"] in {19, 23}                         # Lewsey, Tuqiri


def test_goal_kicker_gets_a_kicking_class():
    out = D.boost_team(_team(), "immortal")["players"]
    assert out[14]["star_attribute"] in SC.GOAL_KICKERS                  # shirt 15 = long_GK


def test_given_stars_hidden_existing_star_kept_and_shown():
    team = _team()
    team["players"][9]["star_attribute"] = 3
    out = D.boost_team(team, "immortal")["players"]
    assert out[9]["star_attribute"] == 3
    assert not out[9].get("hide_star")
    assert all(p["hide_star"] for i, p in enumerate(out) if i != 9)
    assert all(not p.get("hide_star") for p in D.tire_team(_team(), "immortal")["players"])


def test_immortal_attackers_are_sharper_than_legend():
    base = {"pos1": "prop", **{k: 40 for k in D.RATING_KEYS}}
    imm = D.boost_player(base, D.PROFILES["immortal"])
    leg = D.boost_player(base, D.PROFILES["legend"])
    for key in ("attack", "speed", "acceleration", "agility"):
        assert imm[key] >= 90 and imm[key] > leg[key]
    assert imm["ss_tackle_breaker"] and not leg.get("ss_tackle_breaker")
