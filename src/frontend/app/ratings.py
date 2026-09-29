"""
app/ratings.py — rating groups and position-weighted overall
==============================================================
Presentation helpers for the 24 ratings. The game has no "overall" value;
`position_overall` is an editor estimate to make comparisons and sorting
possible, and is labelled as such wherever it is shown.
"""
from app.game_data import ATTRIBUTES, POSITIONS

LABELS = dict(ATTRIBUTES)

GROUPS = [
    ("Attack", ["attack", "handling", "passing", "creativity"]),
    ("Defence", ["defense", "tackling", "rucking", "bravery"]),
    ("Mental", ["discipline", "aggression", "consitance", "temperament"]),
    ("Physical", ["speed", "acceleration", "agility", "strength", "stamina", "fitness"]),
    ("Kicking", ["kicking", "kicking_power", "goal_kicking"]),
    ("Set piece", ["scrummaging", "hooking", "lineout"]),
]

assert sorted(k for _, keys in GROUPS for k in keys) == sorted(LABELS), "rating groups drifted"

_FRONT = {"Set piece": .30, "Physical": .25, "Defence": .25, "Mental": .10, "Attack": .10}
_LOCK = {"Set piece": .25, "Physical": .30, "Defence": .25, "Mental": .10, "Attack": .10}
_BACKROW = {"Defence": .35, "Physical": .30, "Attack": .15, "Mental": .10, "Set piece": .10}
_HALF = {"Attack": .30, "Kicking": .25, "Mental": .20, "Physical": .15, "Defence": .10}
_CENTRE = {"Attack": .35, "Defence": .25, "Physical": .30, "Mental": .10}
_BACK3 = {"Attack": .30, "Physical": .35, "Kicking": .15, "Defence": .10, "Mental": .10}

POSITION_WEIGHTS = {
    "loosehead_prop": _FRONT, "tighthead_prop": _FRONT, "hooker": _FRONT,
    "second_row": _LOCK,
    "blindside_flanker": _BACKROW, "openside_flanker": _BACKROW, "number_eight": _BACKROW,
    "scrum_half": _HALF, "fly_half": _HALF,
    "centre": _CENTRE,
    "winger": _BACK3, "fullback": _BACK3,
}
assert set(POSITION_WEIGHTS) == set(POSITIONS)


def _num(stats, key):
    try:
        return max(0, min(99, int(str(stats.get(key, "")).strip())))
    except (TypeError, ValueError):
        return None


def group_avg(stats, keys):
    vals = [v for v in (_num(stats, k) for k in keys) if v is not None]
    return round(sum(vals) / len(vals)) if vals else None


def group_averages(stats):
    return {name: group_avg(stats, keys) for name, keys in GROUPS}


def position_overall(stats, position=None):
    """Weighted mean of group averages for `position` (defaults to the
    player's position1); plain mean of all ratings for unknown positions."""
    position = position or (stats.get("position1") or "")
    weights = POSITION_WEIGHTS.get(position)
    avgs = group_averages(stats)
    if not weights:
        vals = [v for v in avgs.values() if v is not None]
        return round(sum(vals) / len(vals)) if vals else None
    total = sum(w for g, w in weights.items() if avgs.get(g) is not None)
    if not total:
        return None
    return round(sum(avgs[g] * w for g, w in weights.items() if avgs.get(g) is not None) / total)


def previous_season(record, season):
    """The latest season before `season` that the player has, or None."""
    seasons = sorted((record.get("stats") or {}).keys())
    earlier = [s for s in seasons if s < season]
    return earlier[-1] if earlier else None


def rating_keys():
    return [k for k, _ in ATTRIBUTES]
