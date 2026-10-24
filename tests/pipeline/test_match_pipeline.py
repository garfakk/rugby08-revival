"""Match setup -> match_data -> every file the game reads, end to end and
without the game: quick match, every challenge, and a tournament fixture
(including feeding a game result back into the tournament)."""
import hashlib
import json
import os
import random
import threading
import xml.etree.ElementTree as ET

import pytest

from app import challenges as C
from app.match_data_builder import build_match_data
from app.state import DataStore
from app.tournament import bridge, engine
from backend import game_specific_variables as gsv
from backend import mod_utils
from backend.start_match import start_match
from conftest import make_match_config

pytestmark = pytest.mark.slow


@pytest.fixture
def run_match(game_dir, monkeypatch):
    """start_match without the game: every file written into the fake game
    folder (the d3d8 proxy's Wine registry step is a no-op here)."""
    monkeypatch.setattr(mod_utils, "ensure_wine_d3d8_native_override", lambda *a, **k: None)
    monkeypatch.setattr(mod_utils, "disable_wine_virtual_desktop", lambda *a, **k: None)
    os.makedirs(os.path.join(game_dir, "Data"), exist_ok=True)

    def run(md):
        progress = []
        assert start_match(md, start_R08=False,
                           progress_callback=lambda a, b, label: progress.append((a, b))) is None
        assert progress[-1] == (1.0, 1.0)
        assert all(a <= b for a, b in progress)
        return {os.path.relpath(os.path.join(r, f), game_dir): os.path.join(r, f)
                for r, _, files in os.walk(game_dir) for f in files}
    return run


def _digest(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def _jsonable(md):
    return json.loads(json.dumps(md, default=str))


# ── quick match ──────────────────────────────────────────────────────────
def test_match_data_golden(ds, golden):
    md = build_match_data(ds, make_match_config(ds, wind_power=2, wind_dir_deg=90.0))
    golden("match_data_eng_fra.json", _jsonable(md))


def test_quick_match_writes_every_game_file(ds, run_match, golden):
    md = build_match_data(ds, make_match_config(ds, wind_power=2, wind_dir_deg=90.0))
    files = run_match(md)
    generated = set(files) - {"Rugby08.exe"}
    must = {gsv.game_filenames[k] for k in ("missionFile", "roster", "game_strings_english",
                                           "game_strings_french", "ball")}
    assert must <= generated
    assert "user_profile.pro" in generated
    assert md["lock_controllers"] is False                # quick match: the game's own controller screen
    assert "controller_lock = 0" in open(files["rugby08patches.ini"]).read()
    # golden for the files generated from the match (not the static files
    # copied as they are, which change whenever a DLL is updated)
    from backend.game_files_processor import generated_game_filenames
    ours = generated_game_filenames() | {"user_profile.pro", "rugby08_windowed.ini"}
    golden("quick_match_files.json", {name: _digest(path) for name, path in sorted(files.items())
                                      if name in ours})


def test_quick_match_is_deterministic(ds, run_match):
    md = build_match_data(ds, make_match_config(ds, wind_power=2, wind_dir_deg=90.0))
    first = {n: _digest(p) for n, p in run_match(md).items()}
    second = {n: _digest(p) for n, p in run_match(md).items()}
    assert first == second


def test_previous_match_files_removed(ds, run_match, game_dir):
    """Nothing stale from a previous match leaks into the next one."""
    stale = os.path.join(game_dir, gsv.face_id_for_custom_faces[next(iter(gsv.face_id_for_custom_faces))][0]["filename"])
    open(stale, "wb").close()
    md = build_match_data(ds, make_match_config(ds))
    run_match(md)
    # removed, or rewritten for this match — never the empty leftover
    assert not os.path.exists(stale) or os.path.getsize(stale) > 0


# ── build_match_data edge cases ──────────────────────────────────────────
def test_incomplete_selection_is_none(ds):
    cfg = make_match_config(ds)
    cfg.away.season = None
    assert build_match_data(ds, cfg) is None


def test_empty_player_slots_skipped(ds):
    """An empty "" slot in a lineup must not crash (int(""))."""
    cfg = make_match_config(ds)
    cfg.home.lineup = dict(cfg.home.lineup, players_id=[""] + list(cfg.home.lineup["players_id"]))
    md = build_match_data(ds, cfg)
    assert len(md["team_A"]["players"]) == 21


@pytest.mark.parametrize("side", ["left", "right"])
def test_home_team_side_reaches_match_data(ds, side):
    """It used to be dropped, so the .mis side= was always "left"."""
    assert build_match_data(ds, make_match_config(ds, home_team_side=side))["home_team_side"] == side


def test_random_side_and_kick_off_resolved(ds):
    md = build_match_data(ds, make_match_config(ds, home_team_side="random", kick_off="random"))
    assert md["home_team_side"] in ("left", "right") and md["kick_off"] in ("home", "away")


@pytest.mark.parametrize("side,period,expected", [
    ("left", None, (1.0, 0.0)), ("right", None, (-1.0, 0.0)), ("left", 1, (-1.0, 0.0)),
])
def test_wind_uses_attack_sign(ds, side, period, expected):
    md = build_match_data(ds, make_match_config(ds, wind_power=3, wind_dir_deg=90.0,
                                                home_team_side=side, mission_mode_period=period))
    assert (md["wind_x"] + 0.0, md["wind_z"] + 0.0) == expected


def test_no_wind_power_no_vector(ds):
    md = build_match_data(ds, make_match_config(ds, wind_power=None, wind_dir_deg=90.0))
    assert (md["wind_x"], md["wind_z"]) == (0.0, 0.0) and md["wind_power"] is None


def test_roles_are_shirt_numbers(ds):
    md = build_match_data(ds, make_match_config(ds))
    for team in ("team_A", "team_B"):
        assert all(1 <= v <= 15 for v in md[team]["roles"].values())


def test_difficulty_and_half_length(ds):
    md = build_match_data(ds, make_match_config(ds, difficulty="club", halftime_length="20m"))
    assert md["difficulty"] == 0 and md["halftime_length"] == 3


def test_player_age_from_season(ds):
    md = build_match_data(ds, make_match_config(ds))
    assert all(16 <= p["age"] <= 45 for p in md["team_A"]["players"])


def test_mission_state_only_when_set(ds):
    assert build_match_data(ds, make_match_config(ds))["mission_state"] == {}
    md = build_match_data(ds, make_match_config(ds, mission_mode_name="", mission_mode_time=600))
    assert md["mission_state"]["mode_time"] == 600


# ── challenges ───────────────────────────────────────────────────────────
def _playable_challenges():
    from conftest import FIXTURE_DATA
    out = []
    for name in sorted(os.listdir(os.path.join(FIXTURE_DATA, "challenges"))):
        out.append(pytest.param(name[:-5], id=name[:-5]))
    return out


@pytest.mark.parametrize("cid", _playable_challenges())
def test_challenge_pipeline(cid, ds, run_match, monkeypatch):
    from shared.user_prefs import user_prefs
    monkeypatch.setattr(user_prefs, "wind_mode", "advanced", raising=False)
    data = C.load_all()[cid]
    if C.problems(ds, data):
        pytest.skip("not playable on the fixture pack: " + "; ".join(C.problems(ds, data)))
    md = build_match_data(ds, C.to_match_config(ds, data))
    files = run_match(md)
    root = ET.parse(files[gsv.game_filenames["missionFile"]]).getroot()
    assert root.find("GAME/ENVIRONMENT/WEATHER/WIND") is not None
    events = root.findall("GAME/STATE/SCORE/EVENT")
    assert len(events) == len([e for e in data["score_events"] if e.get("type")])
    if data["score_events"]:
        assert int(events[0].get("player")) == max(0, int(data["score_events"][0].get("player") or 0) - 1)


# ── tournament ───────────────────────────────────────────────────────────
TEMPLATE = {
    "id": "mini_cup", "name": "Mini Cup", "match_type": "world_cup", "venue": "neutral",
    "branding": "world_cup", "branding_season": "2023",
    "stages": [{"id": "pools", "name": "Pool", "kind": "round_robin", "legs": 1}],
    "participants": {"default": {"pools": {"A": ["10002", "10001", "1015", "1010"]}}},
}


def test_tournament_fixture_to_game_and_back(ds, run_match):
    import copy
    t = engine.create_tournament(ds, copy.deepcopy(TEMPLATE), "2024", humans=["10002"], seed=5)
    engine.simulate_until_human(t)
    fixture = engine.next_human_fixture(t)
    cfg = bridge.to_match_config(ds, t, fixture)
    assert cfg.controllers[1]["zone"] == ("home" if fixture.home == "10002" else "away")
    md = build_match_data(ds, cfg)
    assert md["lock_controllers"] is True                 # the human can't take over the opponent
    assert len(md["team_A"]["players"]) == 22 and len(md["team_B"]["players"]) == 22
    files = run_match(md)
    assert gsv.game_filenames["missionFile"] in files

    # the game's result, as R08_handler.read_match_result returns it
    def side(tries):
        players = [{"id": rid, "tries": 0, "conversions_scored": 0, "penalties_scored": 0,
                    "drop_goals": 0, "yellow_cards": 0, "red_cards": 0, "tackles": 1,
                    "conversions_attempted": 0, "penalties_attempted": 0, "injury": 0}
                   for rid in gsv.players_roster_id["team_A"]]
        for p in players[:tries]:
            p["tries"] = 1
        return {"players": players, "stats": {}}
    raw = {"team_A": side(3), "team_B": side(1)}
    raw["team_B"]["players"] = [dict(p, id=rid) for p, rid in
                                zip(raw["team_B"]["players"], gsv.players_roster_id["team_B"])]
    result = bridge.from_game_result(t, fixture, raw, random.Random(1))
    assert (result.home.points, result.away.points) == (15, 5)
    # without lineup tracking: starters 80, bench players who did something 20
    assert [l.minutes for l in result.home.players[:16]] == [80] * 15 + [20]

    # with it: the time on the pitch the game was followed for
    tracked = copy.deepcopy(raw)
    tracked["lineup_events"] = []
    for key in ("team_A", "team_B"):
        rows = tracked[key]["players"]
        tracked[key]["starting_lineup"] = {i + 1: rows[i]["id"] for i in range(15)}
        for i, row in enumerate(rows):
            row["seconds_on_field"] = 4800.0 if i < 14 else (3000.0 if i == 14 else 0.0)
        rows[15]["seconds_on_field"] = 1800.0
    played = bridge.from_game_result(t, fixture, tracked, random.Random(1))
    assert [(l.started, l.minutes) for l in played.home.players[13:17]] == \
        [(True, 80), (True, 50), (False, 30), (False, 0)]
    engine.record_result(t, fixture, result)
    assert fixture.played
    stage = t.stage("pools")
    from app.tournament import standings
    table = {r.team_id: r for r in standings.group_table(t, stage, stage.group("A"))}
    assert table[fixture.home].won >= 1


# ── start-up data loading (e0c4a86a) ─────────────────────────────────────
def test_datastore_from_raw_equals_direct_load():
    raw = DataStore.read_files()
    a, b = DataStore(raw), DataStore()
    assert (a.teams, a.players, a.stadiums, a.tournaments) == (b.teams, b.players, b.stadiums, b.tournaments)


def test_read_files_works_on_a_thread_without_qt():
    """Start-up parses the data behind the splash on a worker thread: it must
    not touch any Qt object."""
    out = {}
    th = threading.Thread(target=lambda: out.setdefault("raw", DataStore.read_files()))
    th.start()
    th.join(60)
    assert out["raw"][0]
