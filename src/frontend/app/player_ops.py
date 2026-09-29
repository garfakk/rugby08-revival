"""
app/player_ops.py — operations on player records, with no Qt
==============================================================
"""
import copy
import json
import os

from app.game_data import (
    ATTRIBUTES, new_player_season, add_player, delete_player, save_team, _load_json,
    SaveError,
)
from app import team_ops

RATING_KEYS = [k for k, _ in ATTRIBUTES]


def allocate_player_id(players_files, loaded_ids):
    """One past the largest numeric id defined anywhere — in any players
    file (loaded or duplicated) or in memory. Ids must stay numeric: the
    match builder converts them with int()."""
    ids = {int(p) for p in loaded_ids if str(p).isdigit()}
    for path in players_files:
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            ids.update(int(k) for k in data if str(k).isdigit())
        elif isinstance(data, list):
            for rec in data:
                v = str(rec.get("id") or rec.get("player_id") or "")
                if v.isdigit():
                    ids.add(int(v))
    return str(max(ids) + 1 if ids else 10001)


def blank_player(display_name, season, position="centre"):
    block = new_player_season()
    block["position1"] = position or "centre"
    return {"display_name": display_name, "first_name": "", "last_name": "",
            "birthdate": "", "commentary": "", "stats": {str(season): block}}


def truncate_bytes(text, limit=14):
    raw = text.encode("utf-8")
    if len(raw) <= limit:
        return text
    return raw[:limit].decode("utf-8", errors="ignore")


def duplicate_record(record):
    new = copy.deepcopy(record)
    new["display_name"] = truncate_bytes((record.get("display_name") or "Player") + " 2")
    return new


def copy_ratings(record, source, target):
    """Copy the 24 ratings (not positions or appearance) between seasons."""
    stats = record.setdefault("stats", {})
    src = stats.get(source) or {}
    dst = stats.setdefault(target, new_player_season())
    changed = 0
    for key in RATING_KEYS:
        if key in src and dst.get(key) != src[key]:
            dst[key] = src[key]
            changed += 1
    return changed


def add_season(record, year, source=None):
    stats = record.setdefault("stats", {})
    year = str(year)
    if year in stats:
        raise ValueError(f"season {year} already exists")
    stats[year] = copy.deepcopy(stats[source]) if source in stats else new_player_season()
    record["stats"] = dict(sorted(stats.items()))


def delete_season(record, year):
    stats = record.get("stats") or {}
    if len(stats) <= 1:
        raise ValueError("a player needs at least one season")
    stats.pop(str(year), None)


def head_options(mod_data_dir):
    """Relative paths (from mod data) of every head archive, numerically."""
    folder = os.path.join(mod_data_dir, "players", "heads")
    if not os.path.isdir(folder):
        return []
    names = [f for f in os.listdir(folder) if f.lower().endswith(".big")]

    def num(name):
        digits = "".join(c for c in name if c.isdigit())
        return int(digits) if digits else 0
    return [f"players/heads/{n}" for n in sorted(names, key=lambda n: (num(n), n))]


def delete_everywhere(ds, pid, remove_from_squads, skip_team_ids=()):
    """Remove the player from every players file defining him and, if asked,
    from every squad (roles he holds are cleared). Teams in `skip_team_ids`
    (unsaved in the team editor) are left alone and reported.
    Returns (files_changed, teams_changed, teams_skipped)."""
    pid = str(pid)
    files = []
    for path in list(dict.fromkeys(ds.players_sources.get(pid, [ds.players_file_path.get(pid)]))):
        if path:
            delete_player(path, pid)
            files.append(path)
    teams, skipped = [], []
    if remove_from_squads:
        for tid, seasons in ds.teams.items():
            touched = False
            for info in seasons.values():
                while pid in [str(p) for p in info.get("players", [])]:
                    if tid in skip_team_ids:
                        break
                    idx = [str(p) for p in info["players"]].index(pid)
                    team_ops.remove(info, idx)
                    touched = True
            if tid in skip_team_ids and any(pid in [str(p) for p in s.get("players", [])]
                                            for s in seasons.values()):
                skipped.append(tid)
            elif touched:
                save_team(ds.teams_file_path[tid], tid, seasons)
                teams.append(tid)
    return files, teams, skipped
