"""app/game_data.py: wind frame, roster vocabularies (must match the backend's,
or values are silently written as 0) and the editors' validation rules."""
import copy
import random

import pytest

from app import game_data as G
from backend import game_specific_variables as gsv


# ── wind (memory note: .mis wind is world blow-toward; UI bearing is home-relative)
@pytest.mark.parametrize("deg,sign,expected", [
    (0, -1, (0.0, -1.0)),       # tailwind for home, home attacking -Z
    (0, 1, (0.0, 1.0)),
    (90, -1, (-1.0, 0.0)),      # toward home's right as it attacks -Z = world -X
    (90, 1, (1.0, 0.0)),
    (180, 1, (0.0, -1.0)),
    (270, 1, (-1.0, 0.0)),
])
def test_wind_world_xz(deg, sign, expected):
    x, z = G.wind_world_xz(deg, sign)
    assert (x + 0.0, z + 0.0) == expected


@pytest.mark.parametrize("deg,label", [
    (0, "with home"), (44, "with home, to home's right"), (90, "across, to home's right"),
    (180, "against home"), (270, "across, to home's left"), (359, "with home"),
])
def test_wind_direction_label_rounds_to_45(deg, label):
    assert G.wind_direction_label(deg) == label


def test_random_wind_in_range():
    rng = random.Random(3)
    for _ in range(300):
        power, bearing = G.random_wind(rng)
        assert 0 <= power <= G.WIND_POWER_MAX
        assert bearing in G.WIND_BEARINGS


# ── vocabularies duplicated from the backend ────────────────────────────
def test_positions_match_backend():
    assert set(G.POSITIONS) <= set(gsv.positions_id)
    assert set(G.SHIRT_POSITIONS.values()) <= set(G.POSITIONS)


def test_set_plays_match_backend():
    assert set(G.SET_PLAYS) == set(gsv.set_plays_id)


def test_tapes_skin_tones_boots_match_backend():
    assert set(G.TAPES) == set(gsv.tape_id)
    assert set(G.SKIN_TONES) == set(gsv.skin_tone_id)
    assert G.BOOT_STYLES == [str(i) for i in gsv.boot_style_id]


def test_aliases_resolve_to_real_positions():
    assert set(G.POSITION_ALIASES.values()) <= set(G.POSITIONS)


@pytest.mark.parametrize("raw,expected", [
    ("Prop", "loosehead_prop"), ("full back", "fullback"), ("fly_half", "fly_half"),
    ("", ""), (None, ""), ("Wing", "winger"),
])
def test_normalise_position(raw, expected):
    assert G.normalise_position(raw) == expected


def test_new_player_season_is_valid():
    rec = {"display_name": "A.Name", "stats": {"2024": G.new_player_season()}}
    rec["stats"]["2024"]["height"] = "180"
    assert [p for p in G.check_player_detailed(rec, "2024") if p[2] == G.ERROR] == []


# ── player checks ────────────────────────────────────────────────────────
def _player(**stats):
    season = G.new_player_season()
    season.update(height="180", weight="90")
    season.update(stats)
    return {"display_name": "A.Name", "birthdate": "1990/01/02", "commentary": "12",
            "stats": {"2024": season}}


def _keys(record, severity=None):
    return {k for k, _, s in G.check_player_detailed(record, "2024")
            if severity is None or s == severity}


@pytest.mark.parametrize("stats,key,severity", [
    ({"position1": "prop"}, "position1", G.ERROR),
    ({"position1": ""}, "position1", G.ERROR),
    ({"position2": "wing"}, "position2", G.ERROR),
    ({"height": "150"}, "height", G.ERROR),          # roster write fails below 151
    ({"height": "tall"}, "height", G.ERROR),
    ({"weight": "x"}, "weight", G.ERROR),
    ({"attack": "100"}, "attack", G.ERROR),
    ({"tackling": "-1"}, "tackling", G.ERROR),
    ({"crashball": "abc"}, "crashball", G.ERROR),
    ({"wrist_tape": "both_wrists"}, "wrist_tape", G.WARN_),
    ({"foot": "ambidextrous"}, "foot", G.WARN_),
    ({"special_ability": "11"}, "special_ability", G.WARN_),
    ({"boot_style": "12"}, "boot_style", G.WARN_),
    ({"gloves": "maybe"}, "gloves", G.WARN_),
    ({"skin_tone": "purple"}, "skin_tone", G.WARN_),
])
def test_player_rule(stats, key, severity):
    assert key in _keys(_player(**stats), severity)


def test_height_151_is_fine():
    assert "height" not in _keys(_player(height="151"))


@pytest.mark.parametrize("name,flag", [("", True), ("O.Farrell", False),
                                       ("Abcdefghijklmn", False), ("Abcdefghijklmno", True),
                                       ("Éééééééé", True)])   # 14 bytes, not chars
def test_display_name_rules(name, flag):
    rec = _player()
    rec["display_name"] = name
    assert ("display_name" in _keys(rec, G.WARN_)) is flag


def test_identity_rules():
    rec = _player()
    rec.update(birthdate="24/09/1991", commentary="abc")
    assert {"birthdate", "commentary"} <= _keys(rec, G.WARN_)


def test_check_player_shortcut():
    assert ("position1", "no primary position") in G.check_player(_player(position1=""), "2024")


# ── team checks ──────────────────────────────────────────────────────────
def _squad_players():
    players = {}
    for i in range(1, 23):
        pos = G.SHIRT_POSITIONS.get(i, "centre")
        players[str(i)] = {"stats": {"2024": {"position1": pos}}}
    return players


def _team(**kw):
    team = {"name": "T", "players": [str(i) for i in range(1, 23)],
            "roles": {k: "10" for k in G.ROLE_KEYS},
            "setPlays": {"up": "classic"}, "kits": {"home": G.blank_kit()}}
    team.update(kw)
    return team


def _team_problems(team, severity=None):
    return {k for k, _, s in G.check_team_detailed(team, _squad_players(), "2024")
            if severity is None or s == severity}


def test_valid_team_has_no_problem():
    assert _team_problems(_team()) == set()


@pytest.mark.parametrize("change,key,severity", [
    ({"name": ""}, "name", G.ERROR),
    ({"players": [str(i) for i in range(1, 22)]}, "players", G.ERROR),          # 21 players
    ({"players": ["1"] + [str(i) for i in range(1, 22)]}, "players.1", G.ERROR),  # duplicate
    ({"players": [str(i) for i in range(1, 22)] + ["999"]}, "players.21", G.ERROR),
    ({"setPlays": {"up": "hail_mary"}}, "setPlays.up", G.ERROR),
    ({"kits": {}}, "kits", G.ERROR),
    ({"roles": {}}, "roles.captain", G.WARN_),
    ({"roles": dict.fromkeys(G.ROLE_KEYS, "20")}, "roles.kickoff", G.WARN_),   # not in the XV
    ({"type": "franchise"}, "type", G.INFO_),
])
def test_team_rule(change, key, severity):
    assert key in _team_problems(_team(**change), severity)


def test_reversed_squad_detected():
    players = _squad_players()
    roster = [str(i) for i in range(1, 23)]
    assert not G.looks_reversed(roster, players, "2024")
    assert G.looks_reversed(list(reversed(roster[:15])) + roster[15:], players, "2024")
    assert "players" in _team_problems(_team(players=list(reversed(roster[:15])) + roster[15:]),
                                       G.WARN_)


def test_looks_reversed_needs_enough_known_positions():
    assert not G.looks_reversed(["x"] * 15, {}, "2024")


def test_player_position_falls_back_to_latest_season():
    p = {"stats": {"2008": {"position1": "hooker"}, "2010": {"position1": "fly_half"}}}
    assert G.player_position(p, "2008") == "hooker"
    assert G.player_position(p, "2024") == "fly_half"
    assert G.player_position({}, "2024") == ""


def test_team_variants_checked_as_they_resolve():
    team = _team(variant={"World Cup": {"players": ["1", "2"]}})
    found = {k: s for k, _, s in G.check_team_variants(team, _squad_players(), "2024")}
    assert found["variant.World Cup"] == G.WARN_                # bad id
    assert found["variant.World Cup.players"] == G.ERROR        # 2 players


def test_kit_variant_id_checked():
    kit = dict(G.blank_kit(), variants={"Bad Id": {"label": "x"}})
    found = {k for k, _, _ in G.check_team_variants(_team(kits={"home": kit}), _squad_players())}
    assert "kits.home.variants.Bad Id" in found


def test_frontend_logo_fallback():
    assert G.frontend_logo({"logos": {"frontend": "a.png", "main": "b.png"}}) == "a.png"
    assert G.frontend_logo({"logos": {"main": "b.png"}}) == "b.png"
    assert G.frontend_logo(None) == ""


def test_new_team_season_shape():
    t = G.new_team_season("X", "club")
    assert t["name"] == "X" and t["type"] == "club"
    assert copy.deepcopy(t) == t
