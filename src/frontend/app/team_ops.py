"""
app/team_ops.py — operations on a team's data, with no Qt
===========================================================
Pure functions over the team JSON shape so they can be tested directly and
applied through an EditSession (`session.apply(label, lambda w: op(w, ...))`).

The squad model: `players` is a plain list with no holes. Index i wears shirt
i+1; 0-14 start, 15-21 are the bench, 22+ are extras the game does not load.
"""
import copy
import os
import re
import shutil

from app.game_data import (
    SHIRT_POSITIONS, ASSET_SPECS, STARTING_XV, SQUAD_SIZE,
    blank_kit, new_team_season, create_json_file,
)
from app.ratings import position_overall

# Shirt → positions that fit it, using the roster vocabulary plus the generic
# names found in real data (a generic "flanker" still fits 6 or 7).
SHIRT_FITS = {
    1: {"loosehead_prop", "prop"}, 2: {"hooker"}, 3: {"tighthead_prop", "prop"},
    4: {"second_row", "lock"}, 5: {"second_row", "lock"},
    6: {"blindside_flanker", "openside_flanker", "flanker"},
    7: {"openside_flanker", "blindside_flanker", "flanker"},
    8: {"number_eight"}, 9: {"scrum_half"}, 10: {"fly_half"},
    11: {"winger", "wing"}, 12: {"centre", "inside_centre"},
    13: {"centre", "outside_centre"}, 14: {"winger", "wing"},
    15: {"fullback", "full_back"},
}


# ── helpers ──────────────────────────────────────────────────────────────
def season_stats(player, season):
    stats = (player or {}).get("stats") or {}
    if season in stats:
        return stats[season]
    if not stats:
        return {}
    try:
        target = int(season)
        best = min(stats, key=lambda y: abs(int(y) - target))
    except (TypeError, ValueError):
        best = sorted(stats)[-1]
    return stats[best]


def player_positions(player, season):
    s = season_stats(player, season)
    return [p for p in (s.get("position1", ""), s.get("position2", ""), s.get("position3", "")) if p]


def fit_rank(player, season, shirt):
    """0 = position1 fits, 1 = position2, 2 = position3, None = doesn't fit."""
    fits = SHIRT_FITS.get(shirt)
    if not fits:
        return 0
    s = season_stats(player, season)
    for rank, key in enumerate(("position1", "position2", "position3")):
        if s.get(key, "") in fits:
            return rank
    return None


def fits(player, season, shirt):
    return fit_rank(player, season, shirt) is not None


def overall_for_shirt(player, season, shirt):
    s = season_stats(player, season)
    pos = SHIRT_POSITIONS.get(shirt) or s.get("position1") or ""
    return position_overall(s, pos) or 0


# ── squad operations (mutate the season block in place) ─────────────────
def _roster(info):
    info["players"] = [str(p) for p in info.get("players", [])]
    return info["players"]


def swap(info, i, j):
    """Swap shirts i and j (0-based). j past the end moves i to the end."""
    roster = _roster(info)
    if not (0 <= i < len(roster)):
        return
    if j >= len(roster):
        roster.append(roster.pop(i))
        return
    roster[i], roster[j] = roster[j], roster[i]


def move(info, i, j):
    """Take the player at i out and insert him at j (later shirts shift)."""
    roster = _roster(info)
    if not (0 <= i < len(roster)):
        return
    pid = roster.pop(i)
    roster.insert(max(0, min(j, len(roster))), pid)


def place(info, i, pid):
    """Put `pid` in shirt i. Already in the squad → the two swap. From
    outside → he takes the shirt and the man displaced goes to the end, so
    nobody is ever silently dropped from the squad."""
    roster = _roster(info)
    pid = str(pid)
    if pid in roster:
        swap(info, roster.index(pid), i)
        return
    if i >= len(roster):
        roster.append(pid)
        return
    displaced = roster[i]
    roster[i] = pid
    roster.append(displaced)


def remove(info, i):
    """Remove shirt i (later shirts shift up). Roles held by him are cleared
    — a role pointing at a player who isn't in the squad resolves to nothing."""
    roster = _roster(info)
    if not (0 <= i < len(roster)):
        return None
    pid = roster.pop(i)
    if pid not in roster:
        roles = info.setdefault("roles", {})
        for key, value in list(roles.items()):
            if str(value) == pid:
                roles[key] = ""
    return pid


def reverse(info):
    roster = _roster(info)
    roster.reverse()


BENCH_ORDER = [
    {"loosehead_prop", "tighthead_prop", "prop"},
    {"hooker"},
    {"tighthead_prop", "loosehead_prop", "prop", "second_row", "lock"},
    {"second_row", "lock", "blindside_flanker", "openside_flanker", "flanker", "number_eight"},
    {"scrum_half"},
    {"fly_half", "centre"},
    {"winger", "fullback", "centre"},
]


def auto_sort(info, players, season):
    """Order the squad by position: starters who already fit their shirt
    stay; the other shirts are filled scarcest first, preferring a player's
    primary position and then the higher position-weighted overall; the bench
    follows the usual 1-2-3-4-9-10-15 cover. Extras keep their order."""
    roster = _roster(info)
    if not roster:
        return 0
    before = list(roster)
    pool = list(dict.fromkeys(roster))          # dedupe, keep first order
    assigned = {}
    used = set()

    for shirt in range(1, STARTING_XV + 1):
        if shirt - 1 < len(before):
            pid = before[shirt - 1]
            if pid not in used and fits(players.get(pid), season, shirt):
                assigned[shirt] = pid
                used.add(pid)

    def candidates(shirt):
        return [pid for pid in pool if pid not in used and fits(players.get(pid), season, shirt)]

    open_shirts = [s for s in range(1, STARTING_XV + 1) if s not in assigned]
    while open_shirts:
        open_shirts.sort(key=lambda s: len(candidates(s)))
        shirt = open_shirts.pop(0)
        cands = candidates(shirt)
        if not cands:
            continue
        best = min(cands, key=lambda pid: (fit_rank(players.get(pid), season, shirt),
                                           -overall_for_shirt(players.get(pid), season, shirt)))
        assigned[shirt] = best
        used.add(best)

    rest = [pid for pid in pool if pid not in used]
    for shirt in range(1, STARTING_XV + 1):
        if shirt not in assigned and rest:
            best = max(rest, key=lambda pid: overall_for_shirt(players.get(pid), season, shirt))
            assigned[shirt] = best
            used.add(best)
            rest.remove(best)

    bench = []
    for wanted in BENCH_ORDER:
        if len(bench) >= SQUAD_SIZE - STARTING_XV:
            break
        options = [pid for pid in rest if set(player_positions(players.get(pid), season)) & wanted]
        if options:
            best = max(options, key=lambda pid: position_overall(
                season_stats(players.get(pid), season)) or 0)
            bench.append(best)
            rest.remove(best)
    while len(bench) < SQUAD_SIZE - STARTING_XV and rest:
        bench.append(rest.pop(0))

    starters = [assigned[s] for s in range(1, STARTING_XV + 1) if s in assigned]
    new = starters + bench + rest
    # Duplicates in the original (same id twice) are kept at the end rather
    # than silently deleted.
    extras = list(before)
    for pid in new:
        if pid in extras:
            extras.remove(pid)
    new += extras
    info["players"] = new
    return sum(1 for a, b in zip(before, new) if a != b)


# ── roles ────────────────────────────────────────────────────────────────
ROLE_RATING = {
    "longGK": "goal_kicking", "shortGK": "goal_kicking",
    "longPunt": "kicking_power", "shortPunt": "kicking", "kickoff": "kicking_power",
}


def best_for_role(info, players, season, role):
    starters = _roster(info)[:STARTING_XV]
    key = ROLE_RATING.get(role)
    if not starters:
        return ""
    if not key:
        return starters[9] if len(starters) > 9 else starters[0]

    def score(pid):
        try:
            return int(season_stats(players.get(pid), season).get(key, 0) or 0)
        except ValueError:
            return 0
    return max(starters, key=score)


# ── kits (order matters: the game picks a kit by position) ─────────────
KIT_NAME_RE = re.compile(r"^[a-z0-9_]+$")


def reorder_kits(info, from_i, to_i):
    kits = info.get("kits") or {}
    keys = list(kits)
    if not (0 <= from_i < len(keys)):
        return
    keys.insert(max(0, min(to_i, len(keys) - 1)), keys.pop(from_i))
    info["kits"] = {k: kits[k] for k in keys}


def rename_kit(info, old, new):
    kits = info.get("kits") or {}
    if old not in kits:
        raise ValueError(f"no kit named {old}")
    if not KIT_NAME_RE.match(new or ""):
        raise ValueError("use lowercase letters, digits and _ only")
    if new != old and new in kits:
        raise ValueError(f"a kit named {new} already exists")
    info["kits"] = {(new if k == old else k): v for k, v in kits.items()}


def free_kit_name(info):
    kits = info.get("kits") or {}
    for name in ("home", "away", "third"):
        if name not in kits:
            return name
    n = 1
    while f"alt{n}" in kits:
        n += 1
    return f"alt{n}"


def add_kit(info, name=None, source=None):
    kits = info.setdefault("kits", {})
    name = name or free_kit_name(info)
    if name in kits:
        raise ValueError(f"a kit named {name} already exists")
    kits[name] = copy.deepcopy(source) if source is not None else blank_kit()
    return name


def delete_kit(info, name):
    kits = info.get("kits") or {}
    kits.pop(name, None)


def set_model3d(kit, key, value):
    """"" removes the key (use the preview default); an empty block goes too,
    so the file only gains model3d when the user actually sets something."""
    block = dict(kit.get("model3d") or {})
    if value:
        block[key] = value
    else:
        block.pop(key, None)
    if block:
        kit["model3d"] = block
    else:
        kit.pop("model3d", None)


# ── seasons ──────────────────────────────────────────────────────────────
def sort_seasons(seasons):
    ordered = dict(sorted(seasons.items(), key=lambda kv: kv[0]))
    seasons.clear()
    seasons.update(ordered)


def add_season(seasons, year, source=None, name="", team_type="club", category=""):
    year = str(year)
    if year in seasons:
        raise ValueError(f"season {year} already exists")
    if source is not None and source in seasons:
        seasons[year] = copy.deepcopy(seasons[source])
    else:
        seasons[year] = new_team_season(name, team_type, category)
    sort_seasons(seasons)


def delete_season(seasons, year):
    if len(seasons) <= 1:
        raise ValueError("a team needs at least one season")
    seasons.pop(year, None)


# ── whole teams ──────────────────────────────────────────────────────────
def safe_folder_name(name, teams_dir):
    """A folder name for a new team that can't collide with any existing
    folder — including ones the loader ignores — nor with another folder's
    <folder>.json name."""
    base = re.sub(r"[^A-Za-z0-9 _-]", "", name or "").strip()
    base = re.sub(r"\s+", " ", base)
    if not base:
        raise ValueError("the team needs a name made of letters or digits")
    existing = set()
    stems = set()
    if os.path.isdir(teams_dir):
        for d in os.listdir(teams_dir):
            existing.add(d.lower())
            stems.add(d.lower().replace(" ", "_"))
    candidate, n = base, 1
    while candidate.lower() in existing or candidate.lower().replace(" ", "_") in stems:
        n += 1
        candidate = f"{base} {n}"
    return candidate


def allocate_team_id(team_type, team_json_ids, loaded_ids):
    ids = set()
    for values in team_json_ids.values():
        ids.update(v for v in values if str(v).isdigit())
    ids.update(str(t) for t in loaded_ids if str(t).isdigit())
    nums = {int(v) for v in ids}
    block = 1000 if team_type == "international" else 2000
    in_block = [n for n in nums if block <= n <= block + 999]
    candidate = (max(in_block) + 1) if in_block else block + 1
    if candidate > block + 999 or candidate in nums:
        candidate = max(nums | {block}) + 1
    return str(candidate)


def referenced_assets(seasons):
    """Relative paths every season references, %-patterns expanded."""
    paths = set()
    for info in seasons.values():
        for key in ("ball", "banners", "pads"):
            paths.update(_expand(info.get(key, ""), ASSET_SPECS.get(key)))
        for slot, rel in (info.get("logos") or {}).items():
            paths.update(_expand(rel, ASSET_SPECS.get(f"logos.{slot}")))
        for kit in (info.get("kits") or {}).values():
            for key in ("frontKitFile", "backKitFile", "previewFile"):
                paths.update(_expand(kit.get(key, ""), ASSET_SPECS.get(key)))
    return sorted(p for p in paths if p)


def _expand(rel, spec):
    rel = (rel or "").strip()
    if not rel:
        return []
    if "%" in rel:
        frames = (spec or {}).get("frames") or 0
        return [rel.replace("%", str(i), 1) for i in range(1, frames + 1)]
    return [rel]


def create_team(teams_dir, folder_name, team_id, seasons, copy_from_folder=None):
    """Create <teams_dir>/<folder>/<folder>.json. With `copy_from_folder`,
    every asset the seasons reference is copied across to the same relative
    path. Rolls back the folder if anything fails. Returns (json_path, missing)."""
    folder = os.path.join(teams_dir, folder_name)
    os.makedirs(folder, exist_ok=False)
    missing = []
    try:
        if copy_from_folder:
            for rel in referenced_assets(seasons):
                src = os.path.join(copy_from_folder, rel)
                if os.path.isfile(src):
                    dst = os.path.join(folder, rel)
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(src, dst)
                else:
                    missing.append(rel)
        json_path = os.path.join(folder, folder_name.lower().replace(" ", "_") + ".json")
        create_json_file(json_path, {str(team_id): seasons})
    except Exception:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    return json_path, missing
