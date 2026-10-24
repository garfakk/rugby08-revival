"""app/player_ops.py and app/roster_import/names.py: player editor operations
and the 14-byte in-game name convention."""
import json
import os

import pytest

from app import player_ops as P
from app.game_data import new_player_season
from app.roster_import import names as N


# ── player_ops ───────────────────────────────────────────────────────────
def test_allocate_player_id(tmp_path):
    a = tmp_path / "a.json"
    a.write_text(json.dumps({"10": {}, "200": {}, "x": {}}))
    b = tmp_path / "b.json"
    b.write_text(json.dumps([{"id": "500"}, {"player_id": 7}]))
    bad = tmp_path / "bad.json"
    bad.write_text("{nope")
    assert P.allocate_player_id([str(a), str(b), str(bad)], ["30"]) == "501"
    assert P.allocate_player_id([], ["99999"]) == "100000"
    assert P.allocate_player_id([], []) == "10001"


def test_blank_player():
    rec = P.blank_player("A.Name", 2024, position="")
    assert rec["display_name"] == "A.Name"
    assert rec["stats"]["2024"]["position1"] == "centre"


@pytest.mark.parametrize("text,expected", [
    ("Short", "Short"), ("Abcdefghijklmnop", "Abcdefghijklmn"),
    ("Éééééééé", "Ééééééé"),               # never cuts a UTF-8 character in half
])
def test_truncate_bytes(text, expected):
    out = P.truncate_bytes(text)
    assert out == expected and len(out.encode("utf-8")) <= 14


def test_duplicate_record():
    assert P.duplicate_record({"display_name": "A.Dupont"})["display_name"] == "A.Dupont 2"
    rec = {"display_name": "A.Longername1", "stats": {"2024": {"attack": "50"}}}
    dup = P.duplicate_record(rec)
    assert dup["display_name"] == "A.Longername1 "            # cut at 14 bytes
    dup["stats"]["2024"]["attack"] = "60"
    assert rec["stats"]["2024"]["attack"] == "50"


def test_copy_ratings_only_ratings():
    src = new_player_season()
    src.update(attack="90", position1="hooker")
    rec = {"stats": {"2023": src}}
    changed = P.copy_ratings(rec, "2023", "2024")
    assert changed == 1
    assert rec["stats"]["2024"]["attack"] == "90"
    assert rec["stats"]["2024"]["position1"] == "centre"


def test_seasons():
    rec = {"stats": {"2024": {"attack": "1"}}}
    P.add_season(rec, 2008)
    P.add_season(rec, "2020", source="2024")
    assert list(rec["stats"]) == ["2008", "2020", "2024"]
    assert rec["stats"]["2020"] == {"attack": "1"}
    with pytest.raises(ValueError):
        P.add_season(rec, "2020")
    P.delete_season(rec, "2008")
    P.delete_season(rec, "2020")
    with pytest.raises(ValueError):
        P.delete_season(rec, "2024")


def test_head_options(tmp_path):
    heads = tmp_path / "players" / "heads"
    heads.mkdir(parents=True)
    for n in ("b10.big", "a2.big", "zed.big", "x.png"):
        (heads / n).write_bytes(b"")
    assert P.head_options(str(tmp_path)) == ["players/heads/zed.big", "players/heads/a2.big",
                                             "players/heads/b10.big"]
    assert P.head_options(str(tmp_path / "nope")) == []


def test_delete_everywhere(data_dir):
    from app.state import DataStore
    ds = DataStore()                                   # loaded from the writable copy
    tid = next(t for t, s in ds.teams.items() if any(i.get("players") for i in s.values()))
    season = next(s for s, i in ds.teams[tid].items() if i.get("players"))
    pid = str(ds.teams[tid][season]["players"][0])
    files, teams, skipped = P.delete_everywhere(ds, pid, remove_from_squads=True)
    assert files and tid in teams and not skipped
    reloaded = DataStore()
    assert pid not in reloaded.players
    for seasons in reloaded.teams.values():
        for info in seasons.values():
            assert pid not in [str(p) for p in info.get("players", [])]


def test_delete_everywhere_skips_unsaved_team(data_dir):
    from app.state import DataStore
    ds = DataStore()
    tid = next(iter(ds.teams))
    season = next(s for s, i in ds.teams[tid].items() if i.get("players"))
    pid = str(ds.teams[tid][season]["players"][0])
    _, teams, skipped = P.delete_everywhere(ds, pid, True, skip_team_ids={tid})
    assert tid in skipped and tid not in teams


# ── names ────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("raw,initial,surname,star", [
    ("A.Dupont", "a", "Dupont", False),
    ("A Dupont", "a", "Dupont", False),
    ("Antoine Dupont", "a", "Dupont", False),
    ("DUPONT", "", "DUPONT", False),
    ("Dupont A.", "a", "Dupont", False),
    ("Dupont, Antoine", "a", "Dupont", False),
    ("Francois du Plessis", "f", "du Plessis", False),
    ("^R.Bobo", "r", "Bobo", True),
    ("JM.Doussain", "j", "Doussain", False),
    ("", "", "", False),
])
def test_parse_name(raw, initial, surname, star):
    p = N.parse_name(raw)
    assert (p.initial, p.surname, p.star) == (initial, surname, star)


def test_fold_and_display_surname():
    assert N.fold("Élie-Jean d'Arc") == "eliejeandarc"
    assert N.display_surname(N.parse_name("DU PLESSIS")) == "du Plessis"
    assert N.display_surname(N.parse_name("BEN-ARFA")) == "Ben-Arfa"
    assert N.display_surname(N.parse_name("McCaw")) == "McCaw"


@pytest.mark.parametrize("args,kw,expected", [
    (("a", "Dupont"), {}, "A. Dupont"),
    (("a", "Dupont"), {"star": True}, "^A. Dupont"),
    (("a", "Vunipolavunipola"), {}, "A. Vunipolavun"),
    (("a", "Vunipolavunip"), {"fit": "tight"}, "A.Vunipolavuni"),
    (("a", "Vunipolavunipola"), {"fit": "keep"}, "A. Vunipolavunipola"),
    (("", "Dupont"), {}, "Dupont"),
])
def test_game_name(args, kw, expected):
    out = N.game_name(*args, **kw)
    assert out == expected
    if kw.get("fit") != "keep":
        assert not N.too_long(out)


@pytest.mark.parametrize("roster,record,expected_score", [
    ("A.Dupont", {"display_name": "A.Dupont"}, 5),
    ("Dupont", {"display_name": "A.Dupont"}, 3),
    ("B.Dupont", {"display_name": "A.Dupont"}, -1),
    ("Plessis", {"display_name": "J.du Plessis"}, 2),
    ("A.Dupont", {"display_name": "X", "first_name": "Antoine", "last_name": "Dupont"}, 5),
    ("", {"display_name": "A.Dupont"}, -1),
])
def test_name_score(roster, record, expected_score):
    assert N.name_score(roster, record)[0] == expected_score


def test_name_score_loose_initial():
    assert N.name_score("B.Dupont", {"display_name": "A.Dupont"}, loose=True) == (3, "initial differs")
