"""app/player_batch: one change set applied to many player records."""
from app import player_batch as B
from app.game_data import new_player_season
from app.ratings import position_overall


def _player(*seasons, rating="60"):
    stats = {}
    for s in seasons:
        block = new_player_season()
        for k in B.RATING_KEYS:
            block[k] = rating
        stats[s] = block
    return {"display_name": "T. Test", "stats": stats}


def test_empty_changes_touch_nothing():
    r = _player("2025")
    assert B.is_empty({}) and B.is_empty({"shift": 0, "groups": {"Attack": 0}, "set": {"socks": ""}})
    assert not B.apply(r, {})


def test_shift_all_and_one_group_clamped():
    r = _player("2025", "2026", rating="97")
    assert B.apply(r, {"shift": 5, "groups": {"Kicking": -10}}, "all")
    for block in r["stats"].values():
        assert block["speed"] == "99"
        assert block["goal_kicking"] == "89"


def test_scope_latest_and_year():
    r = _player("2024", "2025", "2026")
    B.apply(r, {"set": {"socks": "up"}}, "latest")
    assert [b["socks"] for b in r["stats"].values()] == ["down", "down", "up"]
    B.apply(r, {"set": {"socks": "up"}}, "2024")
    assert [b["socks"] for b in r["stats"].values()] == ["up", "down", "up"]
    # a player without that season keeps his ratings
    assert not B.apply(_player("2020"), {"shift": 3}, "2024")


def test_level_sets_the_position_overall_and_keeps_strengths():
    r = _player("2026")
    block = r["stats"]["2026"]
    block["speed"] = "80"
    B.apply(r, {"level": "world"})
    assert position_overall(block) == 88
    assert int(block["speed"]) > int(block["tackling"])


def test_add_and_delete_season():
    r = _player("2025", "2026")
    r["stats"]["2026"]["socks"] = "up"
    B.apply(r, {"add_season": "2027", "delete_season": "2025"})
    assert list(r["stats"]) == ["2026", "2027"]
    assert r["stats"]["2027"]["socks"] == "up"
    # the last season is never deleted, an existing one never replaced
    one = _player("2026")
    B.apply(one, {"delete_season": "2026", "add_season": "2026"})
    assert list(one["stats"]) == ["2026"]


def test_overall_change_for_a_new_season():
    r = _player("2026")
    now, after = B.overall_change(r, {"add_season": "2027", "shift": 10}, "latest")
    assert now == 60 and after == 70


def test_seasons_of():
    assert B.seasons_of([_player("2025", "2026"), _player("2026")]) == {"2025": 1, "2026": 2}


def test_overall_change_matches_apply():
    import copy
    r = _player("2024", "2025", rating="70")
    r["stats"]["2025"]["speed"] = "90"
    for changes, scope in (({"level": "club"}, "all"), ({"shift": -4, "groups": {"Attack": 6}}, "2024"),
                           ({"delete_season": "2025", "shift": 2}, "latest"), ({"set": {"socks": "up"}}, "all")):
        after = copy.deepcopy(r)
        B.apply(after, changes, scope)
        season = B.target_seasons(after, scope)[-1]
        assert B.overall_change(r, changes, scope)[1] == position_overall(after["stats"][season])
