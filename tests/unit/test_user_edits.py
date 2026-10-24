"""app/user_edits.py: the three-way merge and the edit store on their own
(a tiny fake data pack in tmp_path, no DataStore)."""
import json
import shutil
import os
import zipfile

import pytest

from app.user_edits import EditStore, MISSING, merge3, changed_paths, set_path


# ── merge3 ───────────────────────────────────────────────────────────────
def test_merge_takes_each_side_change():
    base = {"a": 1, "b": 1, "c": {"x": 1, "y": 1}}
    mine = {"a": 2, "b": 1, "c": {"x": 2, "y": 1}}
    theirs = {"a": 1, "b": 3, "c": {"x": 1, "y": 3}, "d": 4}
    merged, conflicts = merge3(base, mine, theirs)
    assert merged == {"a": 2, "b": 3, "c": {"x": 2, "y": 3}, "d": 4}
    assert conflicts == []


def test_merge_conflict_keeps_mine():
    merged, conflicts = merge3({"h": "180"}, {"h": "185"}, {"h": "190"})
    assert merged == {"h": "185"}
    assert [(c.path, c.base, c.mine, c.theirs) for c in conflicts] == [(("h",), "180", "185", "190")]


def test_same_change_on_both_sides_is_no_conflict():
    assert merge3({"h": 1}, {"h": 2}, {"h": 2}) == ({"h": 2}, [])


def test_lists_are_one_value():
    base = {"players": [1, 2, 3]}
    merged, conflicts = merge3(base, {"players": [1, 3, 2]}, {"players": [2, 1, 3]})
    assert merged == {"players": [1, 3, 2]} and conflicts[0].path == ("players",)


def test_key_removed_on_one_side():
    merged, conflicts = merge3({"a": 1, "b": 1}, {"a": 1}, {"a": 2, "b": 1})
    assert merged == {"a": 2} and conflicts == []


def test_season_added_on_both_sides_merges_its_fields():
    base = {"2024": {"x": 1}}
    mine = {"2024": {"x": 1}, "2026": {"name": "A", "kit": "k1"}}
    theirs = {"2024": {"x": 1}, "2026": {"name": "A", "kit": "k2"}}
    merged, conflicts = merge3(base, mine, theirs)
    assert merged["2026"] == {"name": "A", "kit": "k1"}
    assert [c.path for c in conflicts] == [("2026", "kit")]


def test_deleted_by_me_changed_in_release():
    merged, conflicts = merge3({"a": 1}, MISSING, {"a": 2})
    assert merged is MISSING and conflicts[0].path == ()


def test_helpers():
    assert changed_paths({"a": 1, "b": {"c": 1}}, {"a": 1, "b": {"c": 2}, "d": 0}) == [("b", "c"), ("d",)]
    assert set_path({"a": {"b": 1}}, ("a", "b"), MISSING) == {"a": {}}
    assert set_path({}, ("a", "b"), 3) == {"a": {"b": 3}}


# ── the store ────────────────────────────────────────────────────────────
@pytest.fixture
def pack(tmp_path):
    root = tmp_path / "pack"
    (root / "players").mkdir(parents=True)
    players = {"1": {"display_name": "A.One", "stats": {"2024": {"height": "180", "weight": "90"}}},
               "2": {"display_name": "B.Two", "stats": {"2024": {"height": "175"}}}}
    (root / "players" / "players.json").write_text(json.dumps(players))
    return root


def release(pack, change):
    """Install a 'new release': rewrite the pack file through `change`."""
    path = pack / "players" / "players.json"
    data = json.loads(path.read_text())
    change(data)
    path.write_text(json.dumps(data))
    st = os.stat(path)
    os.utime(path, ns=(st.st_atime_ns, st.st_mtime_ns + 10_000_000))
    return data


def start(tmp_path, pack):
    """A start-up: the store loaded and laid over the pack as read."""
    store = EditStore(str(tmp_path / "edits"), str(pack), "test").load()
    records = json.loads((pack / "players" / "players.json").read_text())
    store.reconcile("players", records, {})
    return store, records


def edited(record, **stats):
    out = json.loads(json.dumps(record))
    out["stats"]["2024"].update(stats)
    return out


def test_save_keeps_base_and_leaves_pack(tmp_path, pack):
    store, records = start(tmp_path, pack)
    before = (pack / "players" / "players.json").read_text()
    store.save("players", "1", edited(records["1"], height="185"), str(pack / "players" / "players.json"))
    env = json.loads((tmp_path / "edits" / "players" / "1.json").read_text())
    assert env["home"] == "players/players.json"
    assert env["base"]["stats"]["2024"]["height"] == "180"
    assert env["mine"]["stats"]["2024"]["height"] == "185"
    assert (pack / "players" / "players.json").read_text() == before
    # back to the pack's values: the edit goes away
    store.save("players", "1", records["1"], str(pack / "players" / "players.json"))
    assert not (tmp_path / "edits" / "players" / "1.json").exists()


def test_next_start_uses_mine(tmp_path, pack):
    store, records = start(tmp_path, pack)
    store.save("players", "1", edited(records["1"], height="185"), str(pack / "players" / "players.json"))
    _store, records = start(tmp_path, pack)
    assert records["1"]["stats"]["2024"]["height"] == "185"
    assert records["2"]["stats"]["2024"]["height"] == "175"


def test_release_changing_another_field_merges(tmp_path, pack):
    store, records = start(tmp_path, pack)
    store.save("players", "1", edited(records["1"], height="185"), str(pack / "players" / "players.json"))
    release(pack, lambda d: d["1"]["stats"]["2024"].update(weight="95"))
    store, records = start(tmp_path, pack)
    assert records["1"]["stats"]["2024"] == {"height": "185", "weight": "95"}
    assert store.conflicts == {} and ("merged", "players", "1") in store.notes
    env = store.get("players", "1")
    assert env["base"]["stats"]["2024"]["weight"] == "95"       # rebased on the release


def test_release_changing_the_same_field_is_a_conflict(tmp_path, pack):
    store, records = start(tmp_path, pack)
    store.save("players", "1", edited(records["1"], height="185"), str(pack / "players" / "players.json"))
    release(pack, lambda d: d["1"]["stats"]["2024"].update(height="190", weight="95"))
    store, records = start(tmp_path, pack)
    assert records["1"]["stats"]["2024"] == {"height": "185", "weight": "95"}   # mine until settled
    assert [c.path for c in store.conflicts[("players", "1")]] == [("stats", "2024", "height")]
    assert store.status("players", "1") == "conflict"
    # the conflict survives a restart until it is settled
    store, records = start(tmp_path, pack)
    assert ("players", "1") in store.conflicts
    result = store.resolve("players", "1", {("stats", "2024", "height"): "theirs"})
    assert result["stats"]["2024"] == {"height": "190", "weight": "95"}
    # equal to the release now: nothing left to keep
    assert store.get("players", "1") is None
    store, records = start(tmp_path, pack)
    assert store.conflicts == {} and records["1"]["stats"]["2024"]["height"] == "190"


def test_resolve_keeping_mine_rebases(tmp_path, pack):
    store, records = start(tmp_path, pack)
    store.save("players", "1", edited(records["1"], height="185"), str(pack / "players" / "players.json"))
    release(pack, lambda d: d["1"]["stats"]["2024"].update(height="190"))
    store, _ = start(tmp_path, pack)
    store.resolve("players", "1", {("stats", "2024", "height"): "mine"})
    env = store.get("players", "1")
    assert env["base"]["stats"]["2024"]["height"] == "190" and env["mine"]["stats"]["2024"]["height"] == "185"
    store, records = start(tmp_path, pack)
    assert store.conflicts == {} and records["1"]["stats"]["2024"]["height"] == "185"


def test_release_integrating_the_edit_drops_it(tmp_path, pack):
    store, records = start(tmp_path, pack)
    store.save("players", "1", edited(records["1"], height="185"), str(pack / "players" / "players.json"))
    release(pack, lambda d: d["1"]["stats"]["2024"].update(height="185"))
    store, records = start(tmp_path, pack)
    assert store.get("players", "1") is None and ("integrated", "players", "1") in store.notes


def test_deleted_and_created_records(tmp_path, pack):
    store, records = start(tmp_path, pack)
    home = str(pack / "players" / "players.json")
    store.save("players", "2", None, home)
    store.save("players", "10000001", {"display_name": "N.New", "stats": {}}, home)
    store, records = start(tmp_path, pack)
    assert "2" not in records and records["10000001"]["display_name"] == "N.New"
    assert store.status("players", "2") == "deleted" and store.status("players", "10000001") == "new"
    # deleting a record that only exists in the edits forgets it
    store.save("players", "10000001", None, home)
    assert store.get("players", "10000001") is None


def test_unreadable_edit_file_is_set_aside(tmp_path, pack):
    folder = tmp_path / "edits" / "players"
    folder.mkdir(parents=True)
    (folder / "1.json").write_text("{not json")
    store, records = start(tmp_path, pack)
    assert records["1"]["display_name"] == "A.One"
    assert (folder / "1.json.broken").exists()


def test_id_block_is_this_installs(tmp_path):
    store = EditStore(str(tmp_path / "edits"), str(tmp_path), "")
    first = int(store.ids.next_id(set()))
    assert first >= 10_000_000
    assert store.ids.next_id({first, first + 1}) == str(first + 2)
    again = EditStore(str(tmp_path / "edits"), str(tmp_path), "")
    assert again.ids.next_id(set()) == str(first)


def test_edits_export_round_trip(tmp_path, pack):
    store, records = start(tmp_path, pack)
    (pack / "players" / "heads").mkdir()
    (pack / "players" / "heads" / "new.big").write_bytes(b"head")
    record = edited(records["1"], height="185")
    record["stats"]["2024"]["face"] = "players/heads/new.big"
    store.save("players", "1", record, str(pack / "players" / "players.json"))
    export = tmp_path / "my_edits"
    assert store.export(str(export)) == (1, 1)
    assert (export / "files" / "players" / "heads" / "new.big").read_bytes() == b"head"
    assert (export / "edits" / "players" / "1.json").is_file() and (export / "manifest.json").is_file()
    with pytest.raises(OSError):
        store.export(str(export))                       # not into a folder already used

    # the maintainer's side: same pack without the head file
    other = tmp_path / "maintainer"
    other.mkdir()
    (other / "players").mkdir()
    (other / "players" / "players.json").write_text((pack / "players" / "players.json").read_text())
    theirs = EditStore(str(tmp_path / "m_edits"), str(other), "").load()
    out = theirs.import_bundle(str(export / "manifest.json"))
    assert out["records"] == [("players", "1")] and out["files"] == 1
    assert (other / "players" / "heads" / "new.big").read_bytes() == b"head"
    assert theirs.effective("players", "1")["stats"]["2024"]["height"] == "185"
    # importing again leaves the record alone (already edited here); the
    # folder itself and a zip of it read the same
    assert theirs.import_bundle(str(export))["skipped"] == [("players", "1")]
    zipped = shutil.make_archive(str(tmp_path / "my_edits"), "zip", str(export))
    assert theirs.import_bundle(zipped)["skipped"] == [("players", "1")]


def test_record_moved_by_release_follows_its_file(tmp_path, pack):
    store, records = start(tmp_path, pack)
    store.save("players", "1", edited(records["1"], height="185"), str(pack / "players" / "players.json"))
    # the release moves player 1, unchanged, into another file
    data = release(pack, lambda d: None)
    (pack / "players" / "more.json").write_text(json.dumps({"1": data.pop("1")}))
    (pack / "players" / "players.json").write_text(json.dumps(data))
    store = EditStore(str(tmp_path / "edits"), str(pack), "test").load()
    records = {**data, **json.loads((pack / "players" / "more.json").read_text())}
    store.reconcile("players", records, {"1": str(pack / "players" / "more.json"),
                                         "2": str(pack / "players" / "players.json")})
    assert store.get("players", "1")["home"] == "players/more.json"
    assert store.conflicts == {} and store.effective("players", "1")["stats"]["2024"]["height"] == "185"
    again = EditStore(str(tmp_path / "edits"), str(pack), "test").load()
    assert again.get("players", "1")["home"] == "players/more.json"     # written


@pytest.mark.parametrize("bad", ["../evil.png", "..\\..\\evil.png", "/abs/evil.png",
                                 "C:/evil.png", "players/../../evil.png"])
def test_import_refuses_paths_outside_the_pack(tmp_path, pack, bad):
    bundle = tmp_path / "bad.zip"
    env = {"format": 1, "kind": "players", "id": "1", "home": "players/players.json",
           "base": None, "mine": {"display_name": "X"}}
    with zipfile.ZipFile(bundle, "w") as z:
        z.writestr("manifest.json", "{}")
        z.writestr("edits/players/1.json", json.dumps(env))
        z.writestr("edits/players/2.json", json.dumps({**env, "id": "2", "home": bad}))
        z.writestr(f"files/{bad}", b"x")
    store = EditStore(str(tmp_path / "edits"), str(pack), "").load()
    out = store.import_bundle(str(bundle))
    assert out["records"] == [("players", "1")] and out["files"] == 0
    assert not (tmp_path / "evil.png").exists() and not (pack.parent.parent / "evil.png").exists()
