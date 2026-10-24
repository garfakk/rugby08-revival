"""Every player of the real data, each season checked with the player editor's
own rules (game_data.check_player_detailed): ERRORs fail (e.g. height < 151
makes the roster write fail), warnings don't. Plus the files players point at."""
import os

import pytest

from app import game_data as G
from app.stock_faces import load_stock_faces
from conftest import REAL_DATA

from realdata import player_ids, raw

pytestmark = pytest.mark.data


@pytest.mark.parametrize("pid", player_ids())
def test_player(pid, known_issue):
    record = raw()[1][pid]
    problems = []
    for season in sorted(record.get("stats") or {}):
        problems += [f"{season} {key}: {msg}"
                     for key, msg, severity in G.check_player_detailed(record, season, REAL_DATA)
                     if severity == G.ERROR]
    known_issue(problems)


def test_player_files_exist(known_issue):
    """Custom heads, boots and skin layers the players refer to."""
    missing = {}
    for pid, record in raw()[1].items():
        for season, stats in (record.get("stats") or {}).items():
            paths = [stats.get("face", ""), stats.get("boot_style", ""), stats.get("skin", "")]
            paths += stats.get("skin_overlay") or []
            for rel in paths:
                rel = str(rel or "")
                if "/" in rel and not os.path.isfile(os.path.join(REAL_DATA, rel)):
                    missing.setdefault(rel, set()).add(pid)
    known_issue([f"{rel} (players {', '.join(sorted(pids, key=int)[:5])}"
                 f"{'...' if len(pids) > 5 else ''})" for rel, pids in sorted(missing.items())])


def test_stock_faces_exist(known_issue):
    known = {int(f["id"]) for f in load_stock_faces()}
    bad = {}
    for pid, record in raw()[1].items():
        for stats in (record.get("stats") or {}).values():
            face = str(stats.get("face", ""))
            if face.isdigit() and int(face) not in known:
                bad.setdefault(face, set()).add(pid)
    known_issue([f"stock face {face} unknown (players {', '.join(sorted(p)[:5])})"
                 for face, p in sorted(bad.items(), key=lambda kv: int(kv[0]))])
