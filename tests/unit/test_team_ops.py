"""app/team_ops.py: squad, variant, kit and season operations of the team
editor. The squad list IS the shirt assignment, so nobody may be silently
dropped or duplicated."""
import copy

import pytest

from app import team_ops as T
from app import variants as V
from app.game_data import ROLE_KEYS, SHIRT_POSITIONS


def _player(pos, rating=60, pos2="", **stats):
    s = {"position1": pos, "position2": pos2}
    s.update({k: str(rating) for k in ("attack", "handling", "passing", "creativity", "defense",
                                       "tackling", "rucking", "bravery", "discipline", "aggression",
                                       "consitance", "temperament", "speed", "acceleration",
                                       "agility", "strength", "stamina", "fitness", "kicking",
                                       "kicking_power", "goal_kicking", "scrummaging", "hooking",
                                       "lineout")})
    s.update(stats)
    return {"stats": {"2024": s}}


def _squad():
    players = {str(i): _player(SHIRT_POSITIONS.get(i, "centre")) for i in range(1, 23)}
    info = {"players": [str(i) for i in range(1, 23)], "roles": {k: "10" for k in ROLE_KEYS}}
    return info, players


# ── squad ops ────────────────────────────────────────────────────────────
def test_swap_and_swap_past_end():
    info = {"players": ["a", "b", "c"]}
    T.swap(info, 0, 2)
    assert info["players"] == ["c", "b", "a"]
    T.swap(info, 0, 9)
    assert info["players"] == ["b", "a", "c"]
    T.swap(info, 7, 0)                                # out of range: nothing
    assert info["players"] == ["b", "a", "c"]


def test_move():
    info = {"players": ["a", "b", "c", "d"]}
    T.move(info, 0, 2)
    assert info["players"] == ["b", "c", "a", "d"]
    T.move(info, 3, -5)
    assert info["players"] == ["d", "b", "c", "a"]


def test_place_from_outside_keeps_displaced():
    info = {"players": ["a", "b", "c"]}
    T.place(info, 1, "z")
    assert info["players"] == ["a", "z", "c", "b"]
    T.place(info, 0, "c")                             # already in: swap
    assert info["players"] == ["c", "z", "a", "b"]
    T.place(info, 10, "y")
    assert info["players"][-1] == "y"


def test_place_stringifies_ids():
    info = {"players": [1, 2]}
    T.place(info, 0, 3)
    assert info["players"] == ["3", "2", "1"]


def test_remove_clears_roles():
    info = {"players": ["a", "b"], "roles": {"captain": "b", "kickoff": "a"}}
    assert T.remove(info, 1) == "b"
    assert info["roles"] == {"captain": "", "kickoff": "a"}
    assert T.remove(info, 5) is None


def test_remove_on_inheriting_variant_creates_no_roles():
    """A variant that inherits its roles must not get an empty set of its own."""
    entry = {"players": ["a", "b"]}
    T.remove(entry, 0)
    assert "roles" not in entry


def test_remove_duplicate_keeps_roles():
    info = {"players": ["a", "b", "a"], "roles": {"captain": "a"}}
    T.remove(info, 0)
    assert info["roles"]["captain"] == "a"


def test_reverse():
    info = {"players": ["a", "b", "c"]}
    T.reverse(info)
    assert info["players"] == ["c", "b", "a"]


# ── fitting / auto sort / roles ──────────────────────────────────────────
def test_fit_rank():
    p = _player("centre", pos2="winger")
    assert T.fit_rank(p, "2024", 12) == 0
    assert T.fit_rank(p, "2024", 11) == 1
    assert T.fit_rank(p, "2024", 1) is None
    assert T.fit_rank(p, "2024", 20) == 0             # bench: anyone fits
    assert T.fits(_player("prop"), "2024", 3)         # generic prop fits 1 and 3


def test_season_stats_nearest():
    p = {"stats": {"2008": {"position1": "hooker"}, "2020": {"position1": "centre"}}}
    assert T.season_stats(p, "2010")["position1"] == "hooker"
    assert T.season_stats(p, "2024")["position1"] == "centre"
    assert T.season_stats({}, "2024") == {}


def test_auto_sort_restores_shirt_order():
    info, players = _squad()
    shuffled = list(reversed(info["players"][:15])) + info["players"][15:]
    info["players"] = shuffled
    changed = T.auto_sort(info, players, "2024")
    assert changed > 0
    for shirt in range(1, 16):
        assert T.fits(players[info["players"][shirt - 1]], "2024", shirt)
    assert sorted(info["players"]) == sorted(shuffled)            # nobody lost or added


def test_auto_sort_keeps_fitting_starters_and_duplicates():
    info, players = _squad()
    before = list(info["players"])
    assert T.auto_sort(info, players, "2024") == 0
    assert info["players"] == before
    info["players"] = before + ["1"]
    T.auto_sort(info, players, "2024")
    assert info["players"].count("1") == 2                        # duplicate kept at the end


def test_auto_sort_prefers_better_player():
    info, players = _squad()
    players["10"] = _player("winger")                  # shirt 10 no longer fits
    players["23"] = _player("fly_half", rating=40)
    players["24"] = _player("fly_half", rating=90)
    info["players"] += ["23", "24"]
    T.auto_sort(info, players, "2024")
    assert info["players"][9] == "24"


def test_auto_sort_empty():
    assert T.auto_sort({"players": []}, {}, "2024") == 0


def test_best_for_role():
    info, players = _squad()
    players["15"]["stats"]["2024"]["goal_kicking"] = "95"
    assert T.best_for_role(info, players, "2024", "longGK") == "15"
    assert T.best_for_role(info, players, "2024", "captain") == "10"
    assert T.best_for_role({"players": []}, players, "2024", "longGK") == ""


# ── squad variants ───────────────────────────────────────────────────────
def test_variant_lifecycle():
    info, _ = _squad()
    T.add_variant(info, "world_cup", "RWC")
    assert info["variant"]["world_cup"] == {"label": "RWC"}
    with pytest.raises(ValueError):
        T.add_variant(info, "world_cup")
    with pytest.raises(ValueError):
        T.add_variant(info, "World Cup")
    T.set_variant_label(info, "world_cup", "")
    assert info["variant"]["world_cup"] == {}
    T.delete_variant(info, "world_cup")
    assert "variant" not in info


def test_edit_variant_stores_only_differences():
    info, _ = _squad()
    T.add_variant(info, "wc", "WC")
    T.edit_variant(info, "wc", lambda v: T.remove(v, 21))
    entry = info["variant"]["wc"]
    assert set(entry) == {"label", "players"}
    assert len(entry["players"]) == 21
    T.edit_variant(info, "wc", lambda v: v.__setitem__("players", list(info["players"])))
    assert info["variant"]["wc"] == {"label": "WC"}               # back to default: override dropped
    T.edit_variant(info, "wc", lambda v: v.__setitem__("name", "ignored"))
    assert "name" not in info["variant"]["wc"]


def test_clear_variant_keeps_label():
    info = {"players": ["a"], "variant": {"wc": {"label": "WC", "players": ["b"]}}}
    T.clear_variant(info, "wc")
    assert info["variant"]["wc"] == {"label": "WC"}


def test_squad_blocks():
    info = {"players": ["a"], "variant": {"wc": {"players": ["b"]}, "sn": {"label": "x"}}}
    assert [vid for vid, _ in T.squad_blocks(info)] == ["", "wc"]


# ── kit variants / kits ──────────────────────────────────────────────────
def test_kit_variant_lifecycle():
    kit = {"frontKitFile": "a.png", "previewFile": "p.png"}
    T.add_kit_variant(kit, "wc", "patch")
    with pytest.raises(ValueError):
        T.add_kit_variant(kit, "wc")
    T.edit_kit_variant(kit, "wc", lambda k: k.__setitem__("frontKitFile", "b.png"))
    assert kit["variants"]["wc"] == {"label": "patch", "frontKitFile": "b.png"}
    assert V.resolve_kit(kit, "wc")["previewFile"] == "p.png"
    T.clear_kit_variant(kit, "wc")
    assert kit["variants"]["wc"] == {"label": "patch"}
    T.set_kit_variant_label(kit, "wc", "")
    T.delete_kit_variant(kit, "wc")
    assert "variants" not in kit


def test_kit_ops():
    info = {"kits": {}}
    assert T.add_kit(info) == "home"
    assert T.add_kit(info) == "away"
    assert T.add_kit(info) == "third"
    assert T.add_kit(info) == "alt1"
    with pytest.raises(ValueError):
        T.add_kit(info, "home")
    T.reorder_kits(info, 0, 3)
    assert list(info["kits"]) == ["away", "third", "alt1", "home"]
    T.rename_kit(info, "alt1", "retro")
    assert list(info["kits"]) == ["away", "third", "retro", "home"]
    for bad in ("Retro", "home"):
        with pytest.raises(ValueError):
            T.rename_kit(info, "retro", bad)
    T.delete_kit(info, "retro")
    assert "retro" not in info["kits"]


def test_add_kit_copies_source():
    src = {"frontKitFile": "x.png"}
    info = {}
    name = T.add_kit(info, source=src)
    info["kits"][name]["frontKitFile"] = "y.png"
    assert src["frontKitFile"] == "x.png"


def test_set_model3d():
    kit = {}
    T.set_model3d(kit, "socks", "red")
    assert kit["model3d"] == {"socks": "red"}
    T.set_model3d(kit, "socks", "")
    assert "model3d" not in kit


# ── seasons ──────────────────────────────────────────────────────────────
def test_seasons():
    seasons = {"2024": {"name": "A"}}
    T.add_season(seasons, 2008, name="B")
    assert list(seasons) == ["2008", "2024"]
    T.add_season(seasons, "2020", source="2024")
    assert seasons["2020"] == {"name": "A"} and seasons["2020"] is not seasons["2024"]
    with pytest.raises(ValueError):
        T.add_season(seasons, "2020")
    T.delete_season(seasons, "2008")
    T.delete_season(seasons, "2020")
    with pytest.raises(ValueError):
        T.delete_season(seasons, "2024")                          # at least one season


# ── whole teams ──────────────────────────────────────────────────────────
def test_safe_folder_name(tmp_path):
    (tmp_path / "France").mkdir()
    (tmp_path / "New Zealand").mkdir()
    assert T.safe_folder_name("Toulon!", str(tmp_path)) == "Toulon"
    assert T.safe_folder_name("france", str(tmp_path)) == "france 2"
    assert T.safe_folder_name("New_Zealand", str(tmp_path)) == "New_Zealand 2"
    with pytest.raises(ValueError):
        T.safe_folder_name("!!!", str(tmp_path))


def test_allocate_team_id():
    assert T.allocate_team_id("international", {}, []) == "1001"
    assert T.allocate_team_id("club", {"a.json": ["2001", "2005"]}, ["1003"]) == "2006"
    assert T.allocate_team_id("international", {"x": ["1999"]}, []) == "2000"
    ids = {"x": [str(n) for n in range(2001, 3000)]}
    assert T.allocate_team_id("club", ids, []) == "3000"


def test_referenced_assets_expand_patterns():
    seasons = {"2024": {"ball": "ball/ball_%.png", "logos": {"main": "logos/logo.png"},
                        "kits": {"home": {"frontKitFile": "k/f.png", "backKitFile": "k/b_%.png",
                                          "variants": {"wc": {"previewFile": "k/wc.png"}}}}}}
    paths = T.referenced_assets(seasons)
    assert "ball/ball_1.png" in paths and "ball/ball_2.png" in paths
    assert "k/b_22.png" in paths and "k/b_23.png" not in paths
    assert {"logos/logo.png", "k/f.png", "k/wc.png"} <= set(paths)


def test_create_team_copies_assets_and_rolls_back(tmp_path):
    src = tmp_path / "Src"
    (src / "k").mkdir(parents=True)
    (src / "k" / "f.png").write_bytes(b"png")
    seasons = {"2024": {"kits": {"home": {"frontKitFile": "k/f.png", "previewFile": "k/p.png"}}}}
    teams = tmp_path / "teams"
    teams.mkdir()
    path, missing = T.create_team(str(teams), "New Team", "2001", seasons, str(src))
    assert path.endswith("New Team/new_team.json")
    assert (teams / "New Team" / "k" / "f.png").read_bytes() == b"png"
    assert missing == ["k/p.png"]
    with pytest.raises(FileExistsError):
        T.create_team(str(teams), "New Team", "2002", seasons)
