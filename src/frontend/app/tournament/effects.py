"""
tournament/effects.py — Registries that turn tournament state into what a
player can do on the day.

  effective_stats(t, player)   base ratings run through every registered
                               StatModifier. Both the simulator and the
                               in-game roster use it, so a modifier changes
                               simulated AND played matches.
  unavailable_reason(t, player) first registered availability rule that
                               objects, or None.

Extension points (all keyed by name, so registering twice replaces):
  register_condition_kind  a Condition kind (injury, suspension...): label,
                           whether it blocks selection, how to describe it
  register_stat_modifier   fn(t, player, stats, ctx) editing `stats` in place
  register_availability_rule fn(t, player, ctx) -> reason or None
  register_component       per-player / per-team / per-tournament state with
                           a default, created on first access, so old saves
                           without it load unchanged

Future features plug in here: form (component + modifier), morale (team
component + modifier), playing out of position (modifier reading
ctx.position against the player's positions).
"""
from dataclasses import dataclass
from typing import Callable, Optional

# Ratings the game and the simulator read (players.json spelling).
RATINGS = (
    "attack", "defense", "speed", "acceleration", "agility", "handling",
    "passing", "kicking", "kicking_power", "goal_kicking", "tackling",
    "strength", "rucking", "scrummaging", "hooking", "lineout", "discipline",
    "aggression", "stamina", "consitance", "temperament", "creativity",
    "bravery", "fitness", "crashball", "gap_defense",
)


@dataclass
class MatchContext:
    """What a modifier may want to know about where the player is used.
    Every field is optional: squad screens ask without a fixture."""
    fixture: object = None
    team_id: str = ""
    position: str = ""     # the slot's position (repositioning hook)
    slot: int = 0          # 1..22


@dataclass
class ConditionKind:
    kind: str
    label: str
    blocks_selection: bool
    describe: Callable = None   # fn(condition) -> str


_conditions: dict = {}
_modifiers: dict = {}        # name -> (priority, fn)
_availability: dict = {}     # name -> fn
_components: dict = {}       # name -> (scope, default_factory)


def register_condition_kind(kind, label, blocks_selection, describe=None):
    _conditions[kind] = ConditionKind(kind, label, blocks_selection, describe)


def condition_kind(kind) -> Optional[ConditionKind]:
    return _conditions.get(kind)


def register_stat_modifier(name, fn, priority=50):
    _modifiers[name] = (priority, fn)


def register_availability_rule(name, fn):
    _availability[name] = fn


def register_component(name, scope, default_factory):
    if scope not in ("player", "team", "tournament"):
        raise ValueError(scope)
    _components[name] = (scope, default_factory)


def component(owner, name) -> dict:
    """The named component on a PlayerState / TeamEntry / Tournament,
    created from its registered default if the owner has none yet."""
    comps = owner.components
    if name not in comps:
        spec = _components.get(name)
        comps[name] = spec[1]() if spec else {}
    return comps[name]


def to_int(value, default=0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return default


def base_ratings(player) -> dict:
    return {k: to_int(player.base.get(k), 50) for k in RATINGS}


def effective_stats(t, player, ctx: MatchContext = None) -> dict:
    """Ratings after every modifier, clamped to the game's 1..99."""
    stats = base_ratings(player)
    ctx = ctx or MatchContext(team_id=player.team_id)
    for _priority, fn in sorted(_modifiers.values(), key=lambda m: m[0]):
        fn(t, player, stats, ctx)
    return {k: max(1, min(99, int(round(v)))) for k, v in stats.items()}


def effective_record(t, player, ctx: MatchContext = None) -> dict:
    """The player's full flattened record with effective ratings in place —
    what the match builder writes into the game's roster."""
    record = dict(player.base)
    for k, v in effective_stats(t, player, ctx).items():
        record[k] = str(v)
    return record


def _blocking_conditions(t, player, ctx):
    for c in player.conditions:
        kind = _conditions.get(c.kind)
        if kind and kind.blocks_selection and (c.matches_left is None or c.matches_left > 0):
            return describe_condition(c)
    return None


register_availability_rule("conditions", _blocking_conditions)


def unavailable_reason(t, player, ctx: MatchContext = None) -> Optional[str]:
    for fn in _availability.values():
        reason = fn(t, player, ctx)
        if reason:
            return reason
    return None


def is_available(t, player, ctx: MatchContext = None) -> bool:
    return unavailable_reason(t, player, ctx) is None


def describe_condition(c) -> str:
    kind = _conditions.get(c.kind)
    if kind and kind.describe:
        return kind.describe(c)
    label = kind.label if kind else c.kind
    if c.matches_left:
        return f"{label} ({c.matches_left} match{'es' if c.matches_left != 1 else ''})"
    return label
