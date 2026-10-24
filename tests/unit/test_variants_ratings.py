"""app/variants.py (squad and kit variants), app/ratings.py, app/season.py."""
import copy

import pytest

from app import ratings as R
from app import variants as V
from app.season import season_label

SEASON = {
    "name": "France", "players": ["1", "2", "3"], "roles": {"captain": "2", "kickoff": "3"},
    "setPlays": {"up": "classic"},
    "kits": {"home": {"frontKitFile": "kits_2024/home_front.png", "color": "",
                      "variants": {"world_cup": {"label": "RWC patch",
                                                 "frontKitFile": "kits_2024_world_cup/home_front.png"}}}},
    "variant": {
        "world_cup": {"label": "Rugby World Cup 2023", "players": ["2", "4"]},
        "six_nations": {"roles": {"captain": "1"}},
    },
}


def test_variant_ids_and_labels():
    assert V.variant_ids(SEASON) == ["world_cup", "six_nations"]
    assert V.variant_label(SEASON, "") == "Default"
    assert V.variant_label(SEASON, "world_cup") == "Rugby World Cup 2023"
    assert V.variant_label(SEASON, "six_nations") == "Six Nations"
    assert V.has_variant(SEASON, "world_cup") and not V.has_variant(SEASON, "nope")


def test_resolve_default_is_copy_without_variants():
    out = V.resolve(SEASON)
    assert "variant" not in out and out["players"] == ["1", "2", "3"]
    out["players"].append("x")
    assert SEASON["players"] == ["1", "2", "3"]


def test_resolve_squad_variant_keeps_roles_of_players_still_listed():
    out = V.resolve(SEASON, "world_cup")
    assert out["players"] == ["2", "4"]
    assert out["roles"] == {"captain": "2", "kickoff": ""}
    assert "label" not in out


def test_resolve_roles_only_variant():
    out = V.resolve(SEASON, "six_nations")
    assert out["players"] == ["1", "2", "3"] and out["roles"] == {"captain": "1"}


def test_resolve_unknown_variant_is_default():
    assert V.resolve(SEASON, "nope") == V.resolve(SEASON)


def test_resolve_kit_variant():
    kit = SEASON["kits"]["home"]
    assert V.kit_variant_ids(kit) == ["world_cup"]
    assert V.kit_variant_label(kit, "world_cup") == "RWC patch"
    plain = V.resolve_kit(kit)
    assert "variants" not in plain and plain["frontKitFile"] == "kits_2024/home_front.png"
    wc = V.resolve_kit(kit, "world_cup")
    assert wc["frontKitFile"] == "kits_2024_world_cup/home_front.png" and "label" not in wc
    assert V.resolve_kit(kit, "nope") == plain


@pytest.mark.parametrize("seasons,wanted,expected", [
    ({"2008": 0, "2024": 0}, "2024", "2024"),
    ({"2008": 0, "2024": 0}, "2010", "2008"),
    ({"2008": 0, "2024": 0}, "2016", "2024"),       # tie -> the later one
    ({"2008": 0, "2024": 0}, "2030", "2024"),
    ({"2008": 0, "2024": 0}, "", "2024"),
    ({}, "2024", ""),
])
def test_pick_season(seasons, wanted, expected):
    assert V.pick_season(seasons, wanted) == expected


def test_team_season_fallbacks():
    teams = {"7": {"2020": SEASON, "2024": dict(SEASON, variant={})}}
    assert V.team_season(teams, "7", "2020", "world_cup")["players"] == ["2", "4"]
    # a variant the season doesn't have = that season's default, never another season's
    assert V.team_season(teams, "7", "2024", "world_cup")["players"] == ["1", "2", "3"]
    assert V.team_season(teams, "7", "2022")["name"] == "France"
    assert V.team_season(teams, "7", "2022", exact=True) == {}
    assert V.team_season(teams, "8", "2024") == {}


def test_migrate_season_moves_variant_kits():
    info = copy.deepcopy(SEASON)
    info["variant"]["world_cup"]["kits"] = {"home": {"frontKitFile": "kits_2024/home_front.png",
                                                     "previewFile": "wc_preview.png"}}
    info["variant"]["world_cup"]["name"] = "dropped"
    assert V.migrate_season(info)
    assert set(info["variant"]["world_cup"]) == {"label", "players"}
    moved = info["kits"]["home"]["variants"]["world_cup"]
    # existing kit variant kept (setdefault); otherwise only differing keys are moved
    assert moved["frontKitFile"] == "kits_2024_world_cup/home_front.png"


def test_migrate_season_new_kit_variant_has_only_diff():
    info = {"kits": {"away": {"frontKitFile": "a.png", "previewFile": "p.png"}},
            "variant": {"wc": {"label": "WC", "kits": {"away": {"frontKitFile": "a.png",
                                                                "previewFile": "q.png"}}}}}
    assert V.migrate_season(info)
    assert info["kits"]["away"]["variants"]["wc"] == {"previewFile": "q.png", "label": "WC"}


def test_migrate_season_noop():
    info = copy.deepcopy(SEASON)
    assert not V.migrate_season(info) and info == SEASON


def test_asset_folder_and_all_variant_ids():
    assert V.asset_folder("2024", "") == "kits_2024"
    assert V.asset_folder("2024", "world_cup") == "kits_2024_world_cup"
    assert V.all_variant_ids({"1": {"2024": SEASON}}) == ["six_nations", "world_cup"]


# ── season / ratings ─────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,label", [("2024", "2023-2024"), (2008, "2007-2008"),
                                       ("", ""), (None, None), ("—", "—")])
def test_season_label(raw, label):
    assert season_label(raw) == label


def _stats(value=60, **kw):
    s = {k: str(value) for k in R.rating_keys()}
    s.update(kw)
    return s


def test_group_averages():
    s = _stats(60, kicking="90", kicking_power="90", goal_kicking="90")
    avgs = R.group_averages(s)
    assert avgs["Kicking"] == 90 and avgs["Attack"] == 60
    assert R.group_avg({}, ["attack"]) is None
    assert R.group_avg({"attack": "150"}, ["attack"]) == 99      # clamped


def test_position_overall_weights_by_position():
    s = _stats(50, kicking="99", kicking_power="99", goal_kicking="99")
    assert R.position_overall(s, "fly_half") > R.position_overall(s, "hooker")
    assert R.position_overall(_stats(70), "centre") == 70
    assert R.position_overall(_stats(70, position1="winger")) == 70
    assert R.position_overall(_stats(70), "unknown") == 70
    assert R.position_overall({}, "centre") is None


def test_previous_season():
    rec = {"stats": {"2008": {}, "2020": {}, "2024": {}}}
    assert R.previous_season(rec, "2024") == "2020"
    assert R.previous_season(rec, "2008") is None
