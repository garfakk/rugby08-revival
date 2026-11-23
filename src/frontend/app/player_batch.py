"""
app/player_batch.py — one set of changes applied to many players, no Qt
=========================================================================
The player editor's batch mode collects a `changes` dict and hands it here
with the players picked in the list:

    {"level": "world",                   # position overall set to a LEVELS value
     "shift": 3,                         # every rating up (or down) by this
     "groups": {"Physical": -2},         # one rating group up or down
     "set": {"socks": "up", ...},        # season keys given one value
     "add_season": "2027",               # a new season, copied from the latest
     "delete_season": "2008"}            # that season removed (never the last)

Missing keys change nothing. `scope` says which seasons the rating and
"set" changes go to: "all", "latest" (each player's newest) or a year.
"""
import copy

from app.game_data import ATTRIBUTES
from app.player_ops import level_overall
from app.ratings import GROUPS, position_overall

RATING_KEYS = [k for k, _ in ATTRIBUTES]
GROUP_KEYS = dict(GROUPS)
#: season keys a batch may give one value to
SET_KEYS = ("nationality", "foot", "boot_style", "goal_kicking_style", "socks",
            "wrist_tape", "tight_tape", "finger_tape")


def is_empty(changes):
    """Nothing in `changes` would touch a player."""
    c = changes or {}
    return not (c.get("level") or c.get("shift") or any((c.get("groups") or {}).values())
                or any(v not in (None, "") for v in (c.get("set") or {}).values())
                or c.get("add_season") or c.get("delete_season"))


def target_seasons(record, scope, changes=None):
    """The seasons of `record` the rating / "set" changes go to (after the
    batch's own season add / delete)."""
    stats = sorted((record.get("stats") or {}))
    if not stats:
        return []
    if scope == "all":
        return stats
    if scope == "latest" or not scope:
        return [stats[-1]]
    return [scope] if str(scope) in stats else []


def _int(v):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _shift(block, keys, by):
    for k in keys:
        n = _int(block.get(k))
        if n is not None and n > 0:
            block[k] = str(max(1, min(99, n + by)))


def set_overall(block, overall):
    """Move every rating up or down together until the position overall is
    `overall`: the player keeps his strengths."""
    base = {k: _int(block.get(k)) for k in RATING_KEYS}
    base = {k: v for k, v in base.items() if v is not None and v > 0}
    if not base:
        return
    shift = 0
    for _ in range(8):          # clamping moves the overall: settle in a few steps
        for k, v in base.items():
            block[k] = str(max(1, min(99, v + shift)))
        got = position_overall(block)
        if got is None or got == overall:
            break
        shift += overall - got


def apply(record, changes, scope="all"):
    """Apply `changes` to `record` in place. Returns True when it changed."""
    before = copy.deepcopy(record)
    c = changes or {}
    stats = record.setdefault("stats", {})

    gone = str(c.get("delete_season") or "")
    if gone and gone in stats and len(stats) > 1:
        del stats[gone]
    new = str(c.get("add_season") or "")
    if new and new not in stats and stats:
        stats[new] = copy.deepcopy(stats[max(stats)])
        record["stats"] = stats = dict(sorted(stats.items()))

    level = c.get("level")
    shift = _int(c.get("shift")) or 0
    groups = {g: _int(v) or 0 for g, v in (c.get("groups") or {}).items()}
    values = {k: v for k, v in (c.get("set") or {}).items() if v not in (None, "")}
    for season in target_seasons(record, scope):
        block = stats[season]
        if level:
            set_overall(block, level_overall(level))
        if shift:
            _shift(block, RATING_KEYS, shift)
        for g, by in groups.items():
            if by and g in GROUP_KEYS:
                _shift(block, GROUP_KEYS[g], by)
        for k, v in values.items():
            block[k] = v
    return record != before


def overall_change(record, changes, scope="all"):
    """(overall now, overall after) of the season the change shows best:
    the newest season it reaches ((None, None) when it reaches none).
    Works on that one season only: cheap enough for thousands of players."""
    c = changes or {}
    stats = record.get("stats") or {}
    if not stats:
        return None, None
    keys = set(stats)
    gone = str(c.get("delete_season") or "")
    if gone in keys and len(keys) > 1:
        keys.discard(gone)
    new = str(c.get("add_season") or "")
    if new:
        keys.add(new)
    seasons = target_seasons({"stats": dict.fromkeys(keys)}, scope)
    if not seasons:
        return None, None
    season = seasons[-1]
    # a season the batch adds starts as a copy of the newest one
    now = stats.get(season) or stats[max(k for k in keys if k in stats)]
    before = position_overall(now)
    if not (c.get("level") or c.get("shift") or any((c.get("groups") or {}).values())):
        return before, before
    block = dict(now)
    if c.get("level"):
        set_overall(block, level_overall(c["level"]))
    if _int(c.get("shift")):
        _shift(block, RATING_KEYS, _int(c["shift"]))
    for g, by in (c.get("groups") or {}).items():
        if _int(by) and g in GROUP_KEYS:
            _shift(block, GROUP_KEYS[g], _int(by))
    return before, position_overall(block)


def seasons_of(records):
    """{season: how many of `records` have it}, oldest first."""
    counts = {}
    for r in records:
        for s in (r.get("stats") or {}):
            counts[s] = counts.get(s, 0) + 1
    return dict(sorted(counts.items()))
