"""
tournament/fatigue.py — Accumulated tiredness across a tournament.

Each player has a "fatigue" component, level 0..100. Minutes played add to
it (less for high stamina); every matchday that passes recovers some (more
for high fitness), so byes and rotation matter. Effects:
  * physical ratings drop (StatModifier, so the game feels it too),
  * the simulator's injury risk rises (simulator reads the level),
  * AI selection prefers fresher players (selection weight), more so
    against a much weaker opponent (rotation).
Option "fatigue": False switches all of it off.
"""
from .effects import component, register_component, register_stat_modifier, to_int
from .events import on
from .selection import register_selection_weight

PHYSICAL = ("speed", "acceleration", "agility", "stamina", "strength", "tackling", "rucking")

register_component("fatigue", "player", lambda: {"level": 0})


def level(player) -> int:
    return int(player.components.get("fatigue", {}).get("level", 0))


def _modifier(t, player, stats, ctx):
    if not t.options.get("fatigue", True):
        return
    lv = level(player)
    if lv <= 0:
        return
    factor = 1.0 - lv / 400.0          # 100 fatigue = -25%; 20 = -5%
    for k in PHYSICAL:
        stats[k] = stats[k] * factor


register_stat_modifier("fatigue", _modifier, priority=60)


def _weight(t, player, ctx):
    if not t.options.get("fatigue", True):
        return 1.0
    lv = level(player)
    strength = 1.0
    f = ctx.fixture if ctx else None
    if f is not None and f.home and f.away and not f.knockout:
        from .strength import team_rating
        try:
            own = ctx.team_id
            opp = f.away if f.home == own else f.home
            # cached per fixture so 30x22 picks don't recompute ratings
            cache = t.components.setdefault("_rating_cache", {})
            key = f"{f.id}:{opp}"
            if key not in cache:
                cache[key] = team_rating(t, opp)
            okey = f"{f.id}:{own}"
            if okey not in cache:
                cache[okey] = team_rating(t, own)
            from .simulator import class_gap
            if cache[okey] - cache[key] + class_gap(t, own, opp) > 6:
                strength = 2.0         # rest key men against minnows
        except Exception:
            pass
    return max(0.5, 1.0 - strength * lv / 250.0)


register_selection_weight("fatigue", _weight)


@on("match_completed", priority=50)
def _played(t, fixture, result, rng):
    if not t.options.get("fatigue", True):
        return
    for side in (result.home, result.away):
        for line in side.players:
            p = t.players.get(line.pid)
            if not p or line.minutes <= 0:
                continue
            stamina = to_int(p.base.get("stamina"), 60)
            gain = (line.minutes / 80.0) * (30 - (stamina - 60) / 4.0)
            f = component(p, "fatigue")
            f["level"] = int(min(100, f.get("level", 0) + max(8, gain)))


@on("day_completed", priority=40)
def _recover(t, day):
    t.components.pop("_rating_cache", None)
    if not t.options.get("fatigue", True):
        return
    for p in t.players.values():
        f = p.components.get("fatigue")
        if not f or not f.get("level"):
            continue
        fitness = to_int(p.base.get("fitness"), 60)
        f["level"] = int(max(0, f["level"] - (14 + (fitness - 60) / 5.0)))
