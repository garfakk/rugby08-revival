"""Data integrity checks for squads: every player a team, variant or
challenge refers to must exist in data/players/players.json, with a name.

Run from the repo root:  python3 -m unittest discover -s tests -v
"""
import glob
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")


def _load(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


PLAYERS = _load(os.path.join(DATA, "players", "players.json"))


def _squads():
    """Yield (label, season_entry, squad) for every base squad and variant of
    every enabled team/season: squad = {"players": [...], "roles": {...}}."""
    for path in sorted(glob.glob(os.path.join(DATA, "teams", "*", "*.json"))):
        rel = os.path.relpath(path, DATA)
        for team_id, seasons in _load(path).items():
            if not isinstance(seasons, dict):
                continue
            for season, entry in seasons.items():
                # Disabled seasons are never loaded by the game.
                if not isinstance(entry, dict) or entry.get("enabled") is False:
                    continue
                label = f"{rel} [{team_id}/{season}]"
                yield label, season, {"players": entry.get("players") or [],
                                      "roles": entry.get("roles") or {}}
                variants = entry.get("variant")
                for vname, v in (variants.items() if isinstance(variants, dict) else ()):
                    yield (f"{label} variant '{vname}'", season,
                           {"players": v.get("players") or [],
                            "roles": v.get("roles") or {}})


class TeamSquads(unittest.TestCase):
    def test_players_exist_and_are_named(self):
        bad = []
        for label, season, sq in _squads():
            missing = [p for p in sq["players"] if str(p) not in PLAYERS]
            if missing:
                bad.append(f"{label}: not in players.json: {', '.join(map(str, missing))}")
            unnamed = [p for p in sq["players"]
                       if str(p) in PLAYERS and not PLAYERS[str(p)].get("display_name")]
            if unnamed:
                bad.append(f"{label}: no display_name: {', '.join(map(str, unnamed))}")
        self.assertFalse(bad, "\n" + "\n".join(bad))

    def test_no_duplicate_players(self):
        bad = []
        for label, _, sq in _squads():
            ids = [str(p) for p in sq["players"]]
            dups = sorted({p for p in ids if ids.count(p) > 1})
            if dups:
                bad.append(f"{label}: duplicated: {', '.join(dups)}")
        self.assertFalse(bad, "\n" + "\n".join(bad))

    def test_roles_point_into_squad(self):
        bad = []
        for label, _, sq in _squads():
            ids = {str(p) for p in sq["players"]}
            off = {k: v for k, v in sq["roles"].items() if v not in (None, "") and str(v) not in ids}
            if off:
                bad.append(f"{label}: roles outside squad: {off}")
        self.assertFalse(bad, "\n" + "\n".join(bad))


class ChallengeSquads(unittest.TestCase):
    def setUp(self):
        self.files = sorted(glob.glob(os.path.join(DATA, "challenges", "*.json")))

    def _teams(self):
        teams = {}
        for path in glob.glob(os.path.join(DATA, "teams", "*", "*.json")):
            for tid, seasons in _load(path).items():
                teams[tid] = seasons
        return teams

    def test_challenge_teams_and_variants_exist(self):
        teams, bad = self._teams(), []
        for path in self.files:
            name = os.path.basename(path)
            data = _load(path)
            for side in ("home", "away"):
                slot = data.get(side) or {}
                seasons = teams.get(str(slot.get("team_id")))
                if seasons is None:
                    bad.append(f"{name}: {side} team {slot.get('team_id')} not in data")
                    continue
                entry = seasons.get(str(slot.get("season")))
                if not isinstance(entry, dict) or entry.get("enabled") is False:
                    bad.append(f"{name}: {side} team has no enabled {slot.get('season')} squad")
                    continue
                variant = slot.get("variant") or ""
                if variant and variant not in (entry.get("variant") or {}):
                    bad.append(f"{name}: {side} variant '{variant}' not defined")
        self.assertFalse(bad, "\n" + "\n".join(bad))

    def test_challenge_custom_squads_valid(self):
        bad = []
        for path in self.files:
            name = os.path.basename(path)
            data = _load(path)
            for side in ("home", "away"):
                squad = (data.get(side) or {}).get("squad")
                if not (isinstance(squad, dict) and squad.get("players")):
                    continue
                ids = [str(p) for p in squad["players"]]
                missing = [p for p in ids if p not in PLAYERS]
                if missing:
                    bad.append(f"{name}: {side} squad unknown players: {', '.join(missing)}")
                if len(ids) != len(set(ids)):
                    bad.append(f"{name}: {side} squad has duplicates")
                off = {k: v for k, v in (squad.get("roles") or {}).items()
                       if v not in (None, "") and str(v) not in ids}
                if off:
                    bad.append(f"{name}: {side} roles outside squad: {off}")
        self.assertFalse(bad, "\n" + "\n".join(bad))


if __name__ == "__main__":
    unittest.main()
