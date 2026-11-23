"""
app/player_ops.py — operations on player records, with no Qt
==============================================================
"""
import copy
import json
import os

from app.game_data import (
    ATTRIBUTES, new_player_season, add_player, delete_player, save_team, _load_json,
    user_record_id,
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
    own = user_record_id(ids)       # a player the user creates: their own id block
    if own:
        return own
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
        for tid in ds.team_ids():
            seasons = ds.team_seasons(tid)
            touched = False
            # the default squad and every competition variant with its own squad
            blocks = [b for season_info in seasons.values()
                      for _vid, b in team_ops.squad_blocks(season_info)]
            for info in blocks:
                while pid in [str(p) for p in info.get("players", [])]:
                    if tid in skip_team_ids:
                        break
                    idx = [str(p) for p in info["players"]].index(pid)
                    team_ops.remove(info, idx)
                    touched = True
            if tid in skip_team_ids and any(pid in [str(p) for p in b.get("players", [])]
                                            for b in blocks):
                skipped.append(tid)
            elif touched:
                save_team(ds.teams_file_path[tid], tid, seasons)
                teams.append(tid)
    return files, teams, skipped


# ── New players: where they go, what they start with ──────────────────────
# Starting levels offered when a player is created: the position overall the
# new player's ratings are set to.
LEVELS = [("club", "Club", 70), ("international", "International", 80), ("world", "World class", 88)]


def level_overall(level):
    return next((ovr for key, _label, ovr in LEVELS if key == level), LEVELS[0][2])


def target_players_file(ds, near_pid=None):
    """The file a new player is written to: the one holding `near_pid`, else
    the players file holding the most players ("" when there is none)."""
    files = ds.players_files()
    near = ds.players_file_path.get(near_pid) if near_pid else None
    if near in files:
        return near
    if not files:
        return ""
    counts = {}
    for path in ds.players_file_path.values():
        counts[path] = counts.get(path, 0) + 1
    return max(files, key=lambda f: counts.get(f, 0))


def _latest_block(record):
    stats = (record or {}).get("stats") or {}
    return stats[max(stats)] if stats else None


def typical_season(players, position, overall):
    """A season block for a new player at `position`: the ratings, height and
    weight are the average of the players already playing there, moved up or
    down until the position overall is `overall`. Every rating at the same
    value when nobody plays there yet."""
    from app.ratings import position_overall
    block = new_player_season()
    block["position1"] = position
    peers = [b for b in (_latest_block(r) for r in players.values())
             if b and b.get("position1") == position]

    def num(b, key):
        try:
            return float(b.get(key))
        except (TypeError, ValueError):
            return None

    means = {}
    for key in RATING_KEYS + ["height", "weight"]:
        vals = [v for v in (num(b, key) for b in peers) if v is not None and v > 0]
        means[key] = sum(vals) / len(vals) if vals else None
    for key in ("height", "weight"):
        if means[key]:
            block[key] = str(round(means[key]))
    base = {k: (means[k] if means[k] is not None else overall) for k in RATING_KEYS}
    shift = 0.0
    for _ in range(6):          # clamping can move the overall: settle in a few steps
        for k in RATING_KEYS:
            block[k] = str(max(1, min(99, round(base[k] + shift))))
        got = position_overall(block)
        if got is None or got == overall:
            break
        shift += overall - got
    return block


def create_player(ds, first, last, season, position, level=None, path=None, near_pid=None):
    """Write a new player to the players file and register him. Returns his id."""
    first, last = (first or "").strip(), (last or "").strip()
    if not (first or last):
        raise ValueError("the player needs a first or last name")
    path = path or target_players_file(ds, near_pid)
    if not path:
        raise ValueError("there is no players file to save into")
    name = truncate_bytes(f"{first[0]}. {last}" if first and last else (last or first))
    pid = allocate_player_id(ds.players_files(), ds.players)
    record = blank_player(name, season, position)
    if level:
        record["stats"][str(season)] = typical_season(ds.players, position, level_overall(level))
    record["first_name"], record["last_name"] = first, last
    add_player(path, pid, record)
    ds.register_player(pid, record, path)
    return pid


def add_to_squad(ds, pid, tid, season):
    """Put the player in a team's squad for that season: the first empty
    shirt up to 22, else after the last player. Saved at once. Returns his
    shirt number (the one he has if he is already there)."""
    pid = str(pid)
    seasons = ds.team_seasons(tid)
    info = seasons.get(str(season))
    if info is None:
        raise ValueError("the team has no squad that season")
    roster = info.setdefault("players", [])
    ids = [str(p) for p in roster]
    if pid in ids:
        return ids.index(pid) + 1
    empty = next((i for i, p in enumerate(ids[:22]) if not p), None)
    if empty is None:
        empty = len(roster)
    team_ops.place(info, empty, pid)
    save_team(ds.teams_file_path[tid], tid, seasons)
    ds.events.team_changed.emit(tid)
    return empty + 1
