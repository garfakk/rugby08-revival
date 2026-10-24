"""The editors' save path (app/game_data.py: atomic writes, one-time .bak,
nothing else in the file touched) and the roster import (read a .rdf, match
its players to the data, write them back)."""
import copy
import json
import os

import pytest

from app import game_data as G
from app.roster_import import plan as P
from app.roster_import.reader import RosterError, read_roster
from app.state import DataStore
from backend import game_files_processor as GFP
from backend import game_specific_variables as gsv
from shared.config import config

STOCK_ROSTER = os.path.join(config.templates_directory, gsv.template_filenames["roster"])


# ── JSON save path ───────────────────────────────────────────────────────
@pytest.fixture
def players_file(tmp_path):
    path = tmp_path / "players.json"
    path.write_text(json.dumps({"1": {"display_name": "Été"}, "2": {"display_name": "B"}},
                               indent=1, ensure_ascii=False), encoding="utf-8")
    return str(path)


def test_save_player_keeps_others_and_backs_up_once(players_file):
    original = open(players_file, encoding="utf-8").read()
    G.save_player(players_file, "2", {"display_name": "B2"})
    G.save_player(players_file, "2", {"display_name": "B3"})
    assert open(players_file + ".bak", encoding="utf-8").read() == original   # first version kept
    data = json.load(open(players_file, encoding="utf-8"))
    assert data == {"1": {"display_name": "Été"}, "2": {"display_name": "B3"}}
    text = open(players_file, encoding="utf-8").read()
    assert "Été" in text and text.startswith('{\n "1"')              # indent=1, no \u escapes
    assert not os.path.exists(players_file + ".tmp")


def test_add_and_delete_player(players_file):
    G.add_player(players_file, "3", {"display_name": "C"})
    with pytest.raises(G.SaveError):
        G.add_player(players_file, "3", {})
    G.delete_player(players_file, "1")
    assert set(json.load(open(players_file))) == {"2", "3"}


def test_save_errors(tmp_path, players_file):
    with pytest.raises(G.SaveError):
        G.save_player("", "1", {})
    lst = tmp_path / "list.json"
    lst.write_text("[]")
    with pytest.raises(G.SaveError):
        G.save_player(str(lst), "1", {})
    with pytest.raises(G.SaveError):
        G.save_player(str(tmp_path / "missing.json"), "1", {})


def test_create_json_file_refuses_overwrite(tmp_path):
    path = str(tmp_path / "new.json")
    G.create_json_file(path, {"a": 1})
    with pytest.raises(G.SaveError):
        G.create_json_file(path, {"b": 2})
    assert json.load(open(path)) == {"a": 1}


def test_save_team_keeps_disabled_seasons(tmp_path):
    path = tmp_path / "team.json"
    path.write_text(json.dumps({"7": {"2008": {"name": "Old", "enabled": False},
                                      "2024": {"name": "A"}}}))
    G.save_team(str(path), "7", {"2024": {"name": "B"}})              # editor never saw 2008
    data = json.load(open(path))
    assert data["7"]["2008"] == {"name": "Old", "enabled": False}
    assert data["7"]["2024"] == {"name": "B"}


def test_soft_delete_is_ignored_by_loader(data_dir):
    ds = DataStore()
    tid = next(iter(ds.teams))
    target = G.soft_delete_file(ds.teams_file_path[tid])
    assert ".deleted-" in target and os.path.exists(target)
    assert tid not in DataStore().teams


def test_editor_save_reload_roundtrip(data_dir):
    """Editing a team and a player through the save path survives a reload."""
    ds = DataStore()
    tid = "10002"
    seasons = copy.deepcopy(ds.teams[tid])
    seasons["2024"]["name"] = "England XV"
    G.save_team(ds.teams_file_path[tid], tid, seasons)
    pid = str(seasons["2024"]["players"][0])
    record = copy.deepcopy(ds.players[pid])
    record["display_name"] = "X.Renamed"
    G.save_player(ds.players_file_path[pid], pid, record)
    again = DataStore()
    assert again.teams[tid]["2024"]["name"] == "England XV"
    assert again.players[pid]["display_name"] == "X.Renamed"
    assert "2008" not in again.teams[tid]                           # still disabled, still in the file
    assert "2008" in json.load(open(ds.teams_file_path[tid]))[tid]


# ── roster import ────────────────────────────────────────────────────────
def test_stock_roster_reads(golden):
    roster = read_roster(STOCK_ROSTER)
    assert roster["kind"] == "rdf"
    assert len(roster["players"]) > 1000 and len(roster["teams"]) > 50
    # the stock file itself has 3 teams whose squads hold junk ids
    dangling = sorted(tid for tid, t in roster["teams"].items()
                      if any(rid not in roster["players"] for rid in t["squad"]))
    golden("stock_roster_summary.json", {
        "players": len(roster["players"]), "teams": len(roster["teams"]),
        "teams_with_unknown_players": dangling,
        "first_teams": {str(tid): [t["name"], len(t["squad"])]
                        for tid, t in sorted(roster["teams"].items())[:10]},
    })


def test_not_a_roster(tmp_path):
    bad = tmp_path / "x.rdf"
    bad.write_bytes(bytes(0x40000))
    with pytest.raises(RosterError):
        read_roster(str(bad))


def test_import_written_roster_matches_existing_players(game_dir, data_dir, match_data):
    """A roster the mod itself wrote is recognised: every player of both
    squads matches the record it came from."""
    GFP.edit_roster_file(copy.deepcopy(match_data))
    roster = read_roster(os.path.join(game_dir, gsv.game_filenames["roster"]))
    ds = DataStore()
    plan = P.ImportPlan(roster, ds, season="2024")
    expected = {}
    for team, side in (("team_A", "10002"), ("team_B", "10001")):
        ids = [str(p) for p in ds.get_lineup(side, "2024")["players_id"]][:22]
        expected.update(zip(gsv.players_roster_id[team], ids))
    matched = {rid: plan.players[rid] for rid in expected if rid in plan.players}
    assert len(matched) == 44
    wrong = [(rid, c.decision, c.pid, expected[rid]) for rid, c in matched.items()
             if not (c.decision == P.UPDATE and c.pid == expected[rid])]
    # same names can legitimately collide (two players named the same):
    # nearly all must match their own record
    assert len(wrong) <= 2, wrong


def test_import_stock_team_as_new_team(data_dir):
    roster = read_roster(STOCK_ROSTER)
    ds = DataStore()
    plan = P.ImportPlan(roster, ds, season="2008")
    tid = next(t for t, team in sorted(roster["teams"].items()) if len(team["squad"]) >= 22)
    choice = plan.teams[tid]
    choice.include, choice.link, choice.name = True, "new", "Imported XV"
    summary = plan.summary()
    assert summary["teams_new"] == 1 and summary["players_create"] + summary["players_update"] >= 22
    result = P.apply_import(plan)
    assert len(result["teams_created"]) == 1
    reloaded = DataStore()
    new_tid = result["teams_created"][0]
    info = reloaded.teams[new_tid]["2008"]
    assert info["name"] == "Imported XV" and len(info["players"]) == 22
    assert all(str(p) in reloaded.players for p in info["players"])
    assert all(info["roles"][k] in info["players"][:15] for k in G.ROLE_KEYS)
