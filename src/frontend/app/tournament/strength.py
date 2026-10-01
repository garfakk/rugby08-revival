"""
tournament/strength.py — How good a player is in a slot, and how good a side
is unit by unit. Used by the simulator (the match engine) and by AI squad
selection.

Positions use the roster vocabulary (app.game_data.POSITIONS); generic
values from older data (prop, lock, wing...) go through normalise_position.
"""
from app.game_data import SHIRT_POSITIONS, normalise_position

from .effects import MatchContext, effective_stats

# Slot positions 1..22. 1..15 are the game's shirt order; the bench is the
# usual 5 forwards / 2 backs split (16 hooker, 17-18 props, 19 lock,
# 20 back row, 21 scrum half, 22 utility back).
BENCH_POSITIONS = ["hooker", "loosehead_prop", "tighthead_prop", "second_row",
                   "openside_flanker", "scrum_half", "fly_half"]
SLOT_POSITIONS = [SHIRT_POSITIONS[i] for i in range(1, 16)] + BENCH_POSITIONS

GROUP = {
    "loosehead_prop": "prop", "tighthead_prop": "prop", "hooker": "hooker",
    "second_row": "lock", "blindside_flanker": "back_row",
    "openside_flanker": "back_row", "number_eight": "back_row",
    "scrum_half": "scrum_half", "fly_half": "fly_half", "centre": "centre",
    "winger": "back_three", "fullback": "back_three",
}
FORWARD_GROUPS = {"prop", "hooker", "lock", "back_row"}

# How well a player of one group covers another (symmetric; 1.0 = same).
_GROUP_FIT = {
    frozenset(("prop", "hooker")): 0.80,
    frozenset(("lock", "back_row")): 0.85,
    frozenset(("prop", "lock")): 0.70,
    frozenset(("scrum_half", "fly_half")): 0.75,
    frozenset(("fly_half", "centre")): 0.85,
    frozenset(("centre", "back_three")): 0.88,
    frozenset(("fly_half", "back_three")): 0.80,
}

# What each group's job is made of (players.json rating names -> weight).
POSITION_WEIGHTS = {
    "prop": {"scrummaging": 3, "strength": 2.5, "rucking": 1.5, "tackling": 1,
             "stamina": 1, "defense": 1, "attack": 0.5, "handling": 0.5},
    "hooker": {"hooking": 2, "lineout": 2, "scrummaging": 2, "strength": 1.5,
               "rucking": 1.5, "tackling": 1, "handling": 0.5, "stamina": 1},
    "lock": {"lineout": 3, "strength": 2, "rucking": 2, "scrummaging": 1.5,
             "tackling": 1, "stamina": 1, "defense": 1},
    "back_row": {"tackling": 2.5, "rucking": 2, "defense": 1.5, "speed": 1,
                 "strength": 1, "attack": 1, "crashball": 1, "stamina": 1.5,
                 "handling": 1},
    "scrum_half": {"passing": 3, "handling": 2, "speed": 1, "agility": 1.5,
                   "kicking": 1, "creativity": 1.5, "defense": 0.5,
                   "attack": 1, "acceleration": 1},
    "fly_half": {"kicking": 2.5, "passing": 2, "creativity": 2,
                 "goal_kicking": 1, "handling": 1.5, "attack": 1,
                 "kicking_power": 1, "defense": 0.5},
    "centre": {"attack": 2, "handling": 1.5, "tackling": 1.5, "crashball": 1.5,
               "speed": 1.5, "passing": 1, "gap_defense": 1, "strength": 1,
               "defense": 1},
    "back_three": {"speed": 3, "acceleration": 2, "agility": 2, "attack": 2,
                   "handling": 1, "kicking": 1, "defense": 1, "tackling": 0.5,
                   "gap_defense": 0.5},
}

# Team units: (slot groups it is drawn from with weights, ratings with weights)
_ALL = {"prop": 1, "hooker": 1, "lock": 1, "back_row": 1, "scrum_half": 1,
        "fly_half": 1, "centre": 1, "back_three": 1}
UNITS = {
    "scrum": ({"prop": 1.2, "hooker": 1.2, "lock": 1, "back_row": 0.5},
              {"scrummaging": 0.5, "strength": 0.35, "hooking": 0.15}),
    "lineout": ({"hooker": 2, "lock": 3, "back_row": 1},
                {"lineout": 1}),
    "breakdown": ({"prop": 1, "hooker": 1, "lock": 1, "back_row": 1.6},
                  {"rucking": 0.45, "strength": 0.25, "bravery": 0.15, "agility": 0.15}),
    "attack": ({"prop": 0.4, "hooker": 0.4, "lock": 0.4, "back_row": 0.8,
                "scrum_half": 1.5, "fly_half": 2, "centre": 2, "back_three": 2},
               {"attack": 0.3, "speed": 0.2, "handling": 0.15, "passing": 0.1,
                "creativity": 0.1, "crashball": 0.1, "agility": 0.05}),
    "defence": (_ALL, {"tackling": 0.4, "defense": 0.35, "gap_defense": 0.25}),
    "kicking": ({"fly_half": 3, "back_three": 0.75, "scrum_half": 1},
                {"kicking": 0.6, "kicking_power": 0.4}),
    "discipline": (_ALL, {"discipline": 0.6, "temperament": 0.4}),
    "fitness": (_ALL, {"stamina": 0.6, "fitness": 0.4}),
}
OVERALL_WEIGHTS = {"scrum": 0.15, "lineout": 0.10, "breakdown": 0.15,
                   "attack": 0.25, "defence": 0.20, "kicking": 0.10,
                   "discipline": 0.05}


def group_of(position: str) -> str:
    return GROUP.get(normalise_position(position), "")


def is_forward(position: str) -> bool:
    return group_of(position) in FORWARD_GROUPS


def position_fit(player_positions, slot_position) -> float:
    """1.0 for the player's main position, a little less for his listed
    alternatives, less again for a neighbouring role, and a heavy penalty
    across the forwards/backs divide."""
    slot = normalise_position(slot_position)
    slot_group = GROUP.get(slot, "")
    best = 0.5
    for i, raw in enumerate(player_positions or []):
        pos = normalise_position(raw)
        group = GROUP.get(pos, "")
        if not group:
            continue
        rank_penalty = 1.0 if i == 0 else 0.95
        if pos == slot:
            fit = 1.0
        elif group == slot_group:
            fit = 0.96
        else:
            fit = _GROUP_FIT.get(frozenset((group, slot_group)))
            if fit is None:
                same_unit = (group in FORWARD_GROUPS) == (slot_group in FORWARD_GROUPS)
                fit = 0.65 if same_unit else 0.5
        best = max(best, fit * rank_penalty)
    return best


def _weighted(stats, weights) -> float:
    total = sum(weights.values())
    return sum(stats.get(k, 50) * w for k, w in weights.items()) / total


def slot_rating(stats: dict, slot_position: str, player_positions=None) -> float:
    """0..99: the player's ratings weighed for the slot, times his fit there
    (fit skipped when positions aren't given)."""
    group = group_of(slot_position) or "centre"
    value = _weighted(stats, POSITION_WEIGHTS[group])
    if player_positions is not None:
        value *= position_fit(player_positions, slot_position)
    return value


def player_overall(stats: dict, position: str) -> float:
    return slot_rating(stats, position)


def unit_ratings(on_field) -> dict:
    """`on_field`: [(stats, slot_position, fit)] for the players on the pitch.
    Returns the unit ratings plus "overall". A missing player (red card)
    simply isn't in the list, which drags the averages down via the
    `numbers` factor."""
    out = {}
    for unit, (group_weights, rating_weights) in UNITS.items():
        num = den = 0.0
        for stats, pos, fit in on_field:
            w = group_weights.get(group_of(pos), 0)
            if not w:
                continue
            num += w * _weighted(stats, rating_weights) * fit
            den += w
        out[unit] = num / den if den else 40.0
    numbers = min(1.0, len(on_field) / 15.0)
    shorthanded = 1.0 - (1.0 - numbers) * 1.6   # one man down ≈ −10%
    for unit in ("attack", "defence", "breakdown", "scrum"):
        out[unit] *= shorthanded
    out["overall"] = sum(out[u] * w for u, w in OVERALL_WEIGHTS.items())
    return out


def selection_units(t, team_id, selection=None, fixture=None) -> dict:
    """Unit ratings of a team's selected XV (+ "bench" = mean bench slot
    rating), from effective stats."""
    entry = t.teams[team_id]
    sel = selection or entry.selection
    pids = sel.get("players", [])
    positions = sel.get("positions") or SLOT_POSITIONS
    on_field, bench = [], []
    for slot, pid in enumerate(pids[:22]):
        player = t.players.get(pid)
        if not player:
            continue
        pos = positions[slot] if slot < len(positions) else SLOT_POSITIONS[slot]
        ctx = MatchContext(fixture=fixture, team_id=team_id, position=pos, slot=slot + 1)
        stats = effective_stats(t, player, ctx)
        fit = position_fit(player.positions, pos)
        if slot < 15:
            on_field.append((stats, pos, fit))
        else:
            bench.append(slot_rating(stats, pos) * fit)
    units = unit_ratings(on_field)
    units["bench"] = sum(bench) / len(bench) if bench else 40.0
    return units


def team_rating(t, team_id) -> float:
    """Single number for previews and upset detection: XV overall nudged by
    the bench."""
    u = selection_units(t, team_id)
    return 0.85 * u["overall"] + 0.15 * u["bench"]
