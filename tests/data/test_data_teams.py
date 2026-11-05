"""Every team folder and every enabled team season of the real data, checked
with the team editor's own rules (game_data.check_team_detailed): only the
problems it rates ERROR (the game misbehaves) fail a test; warnings don't."""
import os

import pytest

from app import game_data as G
from app import variants as V
from conftest import REAL_DATA
from team_data_loader import TeamDataLoader

from realdata import raw, store, team_folders, team_seasons

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


def test_every_team_has_one_known_group():
    """Quick Match's groups picker (app/team_browse.py): each team names one
    of its groups, the same in every season."""
    from app.team_browse import GROUPS
    bad = []
    for tid, seasons in store().teams.items():
        groups = {info.get("group") for info in seasons.values()}
        if len(groups) != 1 or not groups <= set(GROUPS):
            bad.append(f"{tid}: {sorted(map(str, groups))}")
    assert not bad


def test_rwc_2023_variants_only_in_season_2024():
    """The RWC 2023 squads and kit patches belong to season 2024 (the
    2023-2024 season, which the rwc_2023 tournament plays). Elsewhere they
    would be picked up by any later World Cup that asks for the competition's
    variant, or by an edition resolving to another season. Only teams that
    played that World Cup have them."""
    teams = raw()[0]
    stray = []
    for tid, seasons in sorted(teams.items()):
        for season, info in seasons.items():
            if season == "2024":
                continue
            for vid, block in (info.get(V.VARIANT_KEY) or {}).items():
                if vid == "rwc_2023" or "Rugby World Cup 2023" in (block.get("label") or ""):
                    stray.append(f"{tid} {season}: squad variant {vid}")
            for name, kit in (info.get("kits") or {}).items():
                if "rwc_2023" in (kit.get(V.KIT_VARIANTS_KEY) or {}):
                    stray.append(f"{tid} {season}: {name} kit variant rwc_2023")
    assert not stray, stray


def test_rwc_2023_kit_patch_only_with_the_squad():
    """A 2024 kit patch for rwc_2023 on a team without the squad: a team
    that did not play the tournament."""
    teams = raw()[0]
    odd = []
    for tid, seasons in sorted(teams.items()):
        info = seasons.get("2024") or {}
        patched = any("rwc_2023" in (k.get(V.KIT_VARIANTS_KEY) or {})
                      for k in (info.get("kits") or {}).values())
        if patched and "world_cup" not in (info.get(V.VARIANT_KEY) or {}):
            odd.append(tid)
    assert not odd, odd
