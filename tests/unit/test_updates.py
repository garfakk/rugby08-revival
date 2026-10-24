"""app.updates: an update zip / folder adds and replaces files of the data
pack and the program's assets, writes records into their pack files, keeps
the user's edits apart, refuses what is not its business, and can be undone."""
import json
import os
import shutil
import zipfile

import pytest

from app.updates import Updates, UpdateError


@pytest.fixture
def install(tmp_path):
    mod = tmp_path / "mod_data"
    (mod / "players").mkdir(parents=True)
    (mod / "players" / "players.json").write_text(json.dumps(
        {"1": {"display_name": "A.One"}, "2": {"display_name": "B.Two"}}))
    (mod / "teams" / "France").mkdir(parents=True)
    (mod / "teams" / "France" / "france.json").write_text(json.dumps({"10": {"2024": {"name": "France"}}}))
    (mod / "teams" / "France" / "kit.png").write_bytes(b"old kit")
    app = tmp_path / "app_data"
    (app / "assets" / "static_files").mkdir(parents=True)
    (app / "assets" / "static_files" / "rugby08patches.dll").write_bytes(b"old dll")
    return Updates({"mod_data": str(mod), "app_data": str(app)}, str(tmp_path / "user_data" / "updates"),
                   "0.2")


def make(tmp_path, files, manifest=None, name="u.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("update.json", json.dumps(manifest or {"format": 1, "name": "Fix", "version": "1"}))
        for n, data in files.items():
            z.writestr(n, data if isinstance(data, (bytes, str)) else json.dumps(data))
    return str(path)


def record(kind, rid, home, mine):
    return {"kind": kind, "id": rid, "home": home, "mine": mine}


def test_install_and_undo(tmp_path, install):
    mod, app = install.roots["mod_data"], install.roots["app_data"]
    upd = make(tmp_path, {
        "mod_data/teams/France/kit.png": b"new kit",
        "mod_data/teams/France/kit_away.png": b"away",
        "app_data/assets/static_files/rugby08patches.dll": b"new dll",
        "edits/players/1.json": record("players", "1", "players/players.json", {"display_name": "A.Fixed"}),
        "edits/players/9.json": record("players", "9", "players/players.json", {"display_name": "N.New"}),
        "edits/players/2.json": record("players", "2", "players/players.json", None),
    })
    plan = install.read(upd)
    assert sorted(a for *_, a in plan.files) == ["add", "replace", "replace"]
    assert sorted(a for *_, a in plan.records) == ["add", "delete", "replace"]
    entry = install.install(upd)
    assert open(os.path.join(mod, "teams/France/kit.png"), "rb").read() == b"new kit"
    assert open(os.path.join(app, "assets/static_files/rugby08patches.dll"), "rb").read() == b"new dll"
    players = json.load(open(os.path.join(mod, "players/players.json")))
    assert players == {"1": {"display_name": "A.Fixed"}, "9": {"display_name": "N.New"}}
    assert [e["id"] for e in install.installed()] == [entry["id"]]

    assert install.undo_last()["id"] == entry["id"]
    assert open(os.path.join(mod, "teams/France/kit.png"), "rb").read() == b"old kit"
    assert not os.path.exists(os.path.join(mod, "teams/France/kit_away.png"))
    assert open(os.path.join(app, "assets/static_files/rugby08patches.dll"), "rb").read() == b"old dll"
    assert set(json.load(open(os.path.join(mod, "players/players.json")))) == {"1", "2"}
    assert install.installed() == [] and install.undo_last() is None


def test_folder_update_same_as_zip(tmp_path, install):
    folder = tmp_path / "upd"
    (folder / "mod_data" / "teams" / "France").mkdir(parents=True)
    (folder / "update.json").write_text(json.dumps({"name": "Kits"}))
    (folder / "mod_data" / "teams" / "France" / "kit.png").write_bytes(b"old kit")
    plan = install.read(str(folder / "update.json"))
    assert plan.files[0][-1] == "same" and plan.summary() == "1 file(s) already up to date"


@pytest.mark.parametrize("bad", ["user_data/config.ini", "game_files/Rugby08.exe", "app_data/main.py",
                                 "mod_data/../evil.png", "mod_data/C:/evil.png", "other/x.png",
                                 "_internal/python.dll"])
def test_refuses_what_is_not_its_business(tmp_path, install, bad):
    upd = make(tmp_path, {bad: b"x", "mod_data/ok.png": b"ok"})
    plan = install.read(upd)
    assert plan.ignored == [bad] and [a for *_, a in plan.files] == ["add"]
    install.install(upd)
    assert not (tmp_path / "evil.png").exists() and not (tmp_path / "user_data" / "config.ini").exists()


def test_bad_records_are_ignored(tmp_path, install):
    upd = make(tmp_path, {
        "edits/players/1.json": record("players", "1", "../players.json", {"display_name": "X"}),
        "edits/players/2.json": record("cars", "2", "players/players.json", {}),
        "edits/players/3.json": "not json",
    })
    assert len(install.read(upd).ignored) == 3


def test_not_an_update_or_too_new(tmp_path, install):
    path = tmp_path / "x.zip"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("readme.txt", "hi")
    with pytest.raises(UpdateError):
        install.read(str(path))
    with pytest.raises(UpdateError, match="0.9"):
        install.read(make(tmp_path, {}, {"name": "Later", "min_program": "0.9"}, "later.zip"))
    with pytest.raises(UpdateError):
        install.read(make(tmp_path, {}, {"format": 99}, "future.zip"))


def test_failed_install_changes_nothing(tmp_path, install, monkeypatch):
    mod = install.roots["mod_data"]
    upd = make(tmp_path, {"mod_data/teams/France/kit.png": b"new kit",
                          "edits/players/1.json": record("players", "1", "players/players.json",
                                                         {"display_name": "A.Fixed"})})
    import app.updates as U
    monkeypatch.setattr(U, "_write_record", lambda *a: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(UpdateError, match="disk full"):
        install.install(upd)
    assert open(os.path.join(mod, "teams/France/kit.png"), "rb").read() == b"old kit"
    assert install.installed() == []


def test_deleting_a_team_removes_its_file_and_undo_brings_it_back(tmp_path, install):
    mod = install.roots["mod_data"]
    upd = make(tmp_path, {"edits/teams/10.json": record("teams", "10", "teams/France/france.json", None)})
    install.install(upd)
    assert not os.path.exists(os.path.join(mod, "teams/France/france.json"))
    install.undo_last()
    assert json.load(open(os.path.join(mod, "teams/France/france.json")))["10"]["2024"]["name"] == "France"
