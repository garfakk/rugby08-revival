"""The real data/ folder, loaded once at collection time so every team, season,
player and challenge can be its own test case (a failure names the exact item).

Loaded the way the app loads it (DataStore.read_files with config pointed at
data/), so the checks see exactly what the game would."""
import copy
import functools
import glob
import json
import os

import pytest

from conftest import REAL_DATA, point_config

HAS_DATA = os.path.isdir(os.path.join(REAL_DATA, "teams"))


@functools.lru_cache(maxsize=None)
def raw():
    from app.state import DataStore
    if not HAS_DATA:
        return None
    mp = pytest.MonkeyPatch()
    point_config(mp, data_dir=REAL_DATA)
    try:
        return DataStore.read_files()
    finally:
        mp.undo()


def store():
    """A DataStore on the real data (fresh copy per call)."""
    from app.state import DataStore
    return DataStore(copy.deepcopy(raw()))


def team_folders():
    if not HAS_DATA:
        return []
    return sorted(d for d in os.listdir(os.path.join(REAL_DATA, "teams"))
                  if os.path.isdir(os.path.join(REAL_DATA, "teams", d)))


def team_seasons():
    """pytest params (tid, season), id "<Folder>/<tid>/<season>"."""
    if not HAS_DATA:
        return []
    teams, folders = raw()[0], raw()[2]
    out = []
    for tid in sorted(teams, key=lambda t: (os.path.basename(folders.get(t, "")), t)):
        for season in sorted(teams[tid]):
            out.append(pytest.param(tid, season,
                                    id=f"{os.path.basename(folders.get(tid, '?'))}/{tid}/{season}"))
    return out


def player_ids():
    if not HAS_DATA:
        return []
    return [pytest.param(pid, id=pid) for pid in sorted(raw()[1], key=lambda p: (len(p), p))]


def challenge_files():
    return [pytest.param(p, id=os.path.basename(p))
            for p in sorted(glob.glob(os.path.join(REAL_DATA, "challenges", "*.json")))]


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
