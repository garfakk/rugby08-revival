"""The user's edits through the real save paths and DataStore (on a writable
copy of the fixture pack): saves never touch the pack, the next start uses
them, a new release is merged into them, and the maintainer writes them into
the pack."""
import copy
import json
import os

import pytest

from app import game_data as G
from app import player_ops as P
from app import team_ops as T
from app.state import DataStore
from shared.config import config


def pack_json(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def bump(path, change):
    """A new data release: `change` applied to the pack file."""
    data = pack_json(path)
    change(data)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))


@pytest.fixture
def ds(data_dir):
    return DataStore()


def test_player_save_goes_to_the_edits(ds):
    pid = "10072"
    path = ds.players_file_path[pid]
    before = open(path, "rb").read()
    record = copy.deepcopy(ds.players[pid])
    record["display_name"] = "Z.Edited"
    G.save_player(path, pid, record)
    assert open(path, "rb").read() == before
    assert G.save_target(path) == "my edits"
    assert os.path.isfile(os.path.join(config.directory_user_edits, "players", f"{pid}.json"))
    again = DataStore()
    assert again.players[pid]["display_name"] == "Z.Edited"
    assert again.players_file_path[pid] == path
    assert again.edits.status("players", pid) == "edited"


def test_team_save_delete_and_restore(ds):
    tid = "10002"
    path = ds.teams_file_path[tid]
    seasons = copy.deepcopy(ds.teams[tid])
    seasons["2024"]["name"] = "England XV"
    G.save_team(path, tid, seasons)
    env = ds.edits.get("teams", tid)
    assert "2007" in env["mine"] and env["mine"]["2007"]["enabled"] is False    # disabled kept
    assert pack_json(path)[tid]["2024"]["name"] != "England XV"
    assert DataStore().teams[tid]["2024"]["name"] == "England XV"

    G.delete_team(path, tid)
    assert os.path.isfile(path)                        # the pack file stays
    again = DataStore()
    assert tid not in again.teams
    home = again.edits.get("teams", tid)["home"]
    again.edits.revert("teams", tid)
    again.refresh_record("teams", tid, home=home)
    assert again.teams[tid]["2024"]["name"] == pack_json(path)[tid]["2024"]["name"]


def test_created_team_and_player_live_in_the_edits(ds):
    pid = P.allocate_player_id(ds.players_files(), ds.players)
    assert int(pid) >= 10_000_000
    path = ds.players_files()[0]
    G.add_player(path, pid, P.blank_player("N.New", "2024"))
    assert pid not in pack_json(path)

    tid = T.allocate_team_id("club", ds.team_json_ids, ds.teams)
    assert int(tid) >= 10_000_000
    folder = T.safe_folder_name("My Club", config.directory_teams)
    json_path, _ = T.create_team(config.directory_teams, folder, tid,
                                 {"2024": T.new_team_season("My Club", "club", "")})
    assert os.path.isdir(os.path.dirname(json_path)) and not os.path.exists(json_path)

    again = DataStore()
    assert again.players[pid]["display_name"] == "N.New"
    assert again.teams[tid]["2024"]["name"] == "My Club"
    assert again.teams_folder_path[tid] == os.path.dirname(json_path)


def test_release_merges_and_conflicts(ds):
    pid = "10072"
    path = ds.players_file_path[pid]
    season = sorted(ds.players[pid]["stats"])[-1]
    record = copy.deepcopy(ds.players[pid])
    record["stats"][season]["height"] = "201"
    record["display_name"] = "Z.Mine"
    G.save_player(path, pid, record)

    def release(data):
        data[pid]["stats"][season]["weight"] = "99"          # merges
        data[pid]["display_name"] = "Z.Release"              # conflicts
    bump(path, release)
    again = DataStore()
    player = again.players[pid]
    assert player["stats"][season]["weight"] == "99" and player["stats"][season]["height"] == "201"
    assert player["display_name"] == "Z.Mine"
    assert [c.path for c in again.edits.conflicts[("players", pid)]] == [("display_name",)]

    again.edits.resolve("players", pid, {("display_name",): "theirs"})
    again.refresh_record("players", pid)
    assert again.players[pid]["display_name"] == "Z.Release"
    final = DataStore()
    assert final.edits.conflicts == {}
    assert final.players[pid]["stats"][season]["height"] == "201"


def test_maintainer_writes_the_edits_into_the_pack(ds):
    pid, tid = "10072", "10002"
    ppath, tpath = ds.players_file_path[pid], ds.teams_file_path[tid]
    record = copy.deepcopy(ds.players[pid])
    record["display_name"] = "Z.Pack"
    G.save_player(ppath, pid, record)
    seasons = copy.deepcopy(ds.teams[tid])
    seasons["2024"]["name"] = "England Pack"
    G.save_team(tpath, tid, seasons)
    assert ds.promote_edits([("players", pid), ("teams", tid)]) == 2
    assert pack_json(ppath)[pid]["display_name"] == "Z.Pack"
    assert pack_json(tpath)[tid]["2024"]["name"] == "England Pack"
    assert "2007" in pack_json(tpath)[tid]                       # disabled season kept
    assert ds.edits.count() == 0
    assert not os.listdir(os.path.join(config.directory_user_edits, "players"))


def test_promote_writes_the_merged_record(ds):
    """An edit made on an older release (imported from an edits export): writing it
    into the pack keeps what the newer pack changed elsewhere."""
    pid = "10072"
    path = ds.players_file_path[pid]
    season = sorted(ds.players[pid]["stats"])[-1]
    record = copy.deepcopy(ds.players[pid])
    record["display_name"] = "Z.Mine"
    G.save_player(path, pid, record)
    bump(path, lambda d: d[pid]["stats"][season].update(weight="99"))
    assert ds.promote_edits([("players", pid)]) == 1
    written = pack_json(path)[pid]
    assert written["display_name"] == "Z.Mine" and written["stats"][season]["weight"] == "99"


def test_mod_mode_writes_the_pack(data_dir, monkeypatch):
    monkeypatch.setattr(config, "save_edits_to", "mod")
    ds = DataStore()
    pid = "10072"
    path = ds.players_file_path[pid]
    record = copy.deepcopy(ds.players[pid])
    record["display_name"] = "Z.Direct"
    G.save_player(path, pid, record)
    assert pack_json(path)[pid]["display_name"] == "Z.Direct"
    assert ds.edits.count() == 0
    assert G.save_target(path) == os.path.basename(path)


def test_edits_turned_off_and_on(ds, monkeypatch):
    from shared.user_prefs import user_prefs
    monkeypatch.setattr(user_prefs, "save", lambda: None)
    monkeypatch.setattr(user_prefs, "use_edits", True)
    pid = "10072"
    path = ds.players_file_path[pid]
    original = ds.players[pid]["display_name"]
    record = copy.deepcopy(ds.players[pid])
    record["display_name"] = "Z.Mine"
    G.save_player(path, pid, record)
    new_pid = P.allocate_player_id(ds.players_files(), ds.players)
    G.add_player(path, new_pid, {**copy.deepcopy(record), "display_name": "N.New"})
    ds.refresh_record("players", new_pid)
    assert new_pid in ds.players

    ds.set_edits_enabled(False)
    assert user_prefs.use_edits is False
    assert ds.players[pid]["display_name"] == original and new_pid not in ds.players
    assert ds.edits.count() == 2                                   # kept
    with pytest.raises(G.SaveError, match="turned off"):
        G.save_player(path, pid, ds.players[pid])                  # would replace the edit
    assert ds.edits.get("players", pid)["mine"]["display_name"] == "Z.Mine"
    # the next start leaves the edits out too
    off = DataStore()
    assert off.players[pid]["display_name"] == original and not off.edits.enabled

    ds.set_edits_enabled(True)
    assert ds.players[pid]["display_name"] == "Z.Mine" and new_pid in ds.players
    assert DataStore().players[pid]["display_name"] == "Z.Mine"
