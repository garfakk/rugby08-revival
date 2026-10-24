"""Every team folder and every enabled team season of the real data, checked
with the team editor's own rules (game_data.check_team_detailed): only the
problems it rates ERROR (the game misbehaves) fail a test; warnings don't."""
import os

import pytest

from app import game_data as G
from app import variants as V
from conftest import REAL_DATA
from team_data_loader import TeamDataLoader

from realdata import raw, team_folders, team_seasons

pytestmark = pytest.mark.data


@pytest.mark.parametrize("folder", team_folders())
def test_folder_has_team_json(folder, known_issue):
    """The loader only reads <folder>.json: a folder without it is silently
    skipped, so the team vanishes from the game."""
    name = TeamDataLoader.team_json_name(folder)
    path = os.path.join(REAL_DATA, "teams", folder, name)
    known_issue([] if os.path.isfile(path) else [f"teams/{folder}/{name} not found"])


def test_team_ids_unique(known_issue):
    owners = {}
    for path, ids in raw()[6].items():
        for tid in ids:
            owners.setdefault(tid, []).append(os.path.relpath(path, REAL_DATA))
    known_issue([f"team id {tid} defined in {', '.join(paths)}"
                 for tid, paths in sorted(owners.items()) if len(paths) > 1])


def _errors(problems):
    return [f"{key}: {msg}" for key, msg, severity in problems if severity == G.ERROR]


@pytest.mark.parametrize("tid,season", team_seasons())
def test_team_season(tid, season, known_issue):
    teams, players = raw()[0], raw()[1]
    info = teams[tid][season]
    problems = _errors(G.check_team_detailed(info, players, season))
    problems += _errors(G.check_team_variants(info, players, season))
    for variant in V.variant_ids(info):
        if "players" in V.overrides(info, variant):
            problems += [f"variant {variant}: {p}" for p in
                         _errors(G.check_team_detailed(V.resolve(info, variant), players, season))]
    known_issue(problems)
