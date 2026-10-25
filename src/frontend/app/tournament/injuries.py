"""
tournament/injuries.py — Turning "injured in the match" into an absence.

Both the simulator and the game only say that a player got hurt (the
game's per-player injury byte is treated as a flag), so the type and how
many matches he misses are rolled here from INJURY_TABLE, scaled by the
"injury_duration" option. Concussions always cost at least one match
(return-to-play protocol). A "knock" costs nothing; it makes the news
only for a team the user manages.
"""
from .conditions import add_condition
from .effects import register_condition_kind
from .events import on
from .model import Condition

# (type, weight, min matches, max matches). max None = rest of tournament.
INJURY_TABLE = [
    ("knock", 30, 0, 0),
    ("dead leg", 10, 0, 1),
    ("hamstring strain", 14, 1, 3),
    ("ankle sprain", 12, 1, 3),
    ("calf strain", 8, 1, 2),
    ("concussion", 10, 1, 2),
    ("shoulder injury", 7, 2, 5),
    ("rib cartilage damage", 4, 1, 3),
    ("knee ligament damage", 3, 3, 8),
    ("broken hand", 1.5, 2, 4),
    ("ruptured ACL", 0.5, None, None),
]
OUT_FOR_TOURNAMENT = 99
_UNCOUNTABLE = {"concussion", "knee ligament damage", "rib cartilage damage"}


def with_article(kind) -> str:
    if kind in _UNCOUNTABLE:
        return kind
    return ("an " if kind[0] in "aeiou" else "a ") + kind


def _describe(c):
    n = c.matches_left
    kind = c.data.get("type", "injury")
    if n is None or n >= OUT_FOR_TOURNAMENT:
        return f"{kind} (out for the tournament)"
    return f"{kind} ({n} match{'es' if n != 1 else ''})"


register_condition_kind("injury", "Injured", blocks_selection=True, describe=_describe)


def roll_injury(rng, duration_scale=1.0) -> tuple:
    """(type, matches out)."""
    kind, _w, lo, hi = rng.choices(INJURY_TABLE, [row[1] for row in INJURY_TABLE])[0]
    if lo is None:
        return kind, OUT_FOR_TOURNAMENT
    # skew toward the short end: most strains clear quickly
    span = hi - lo
    n = lo + int(round(span * rng.random() ** 1.6))
    n = int(round(n * duration_scale)) if n else 0
    if kind == "concussion":
        n = max(1, n)
    return kind, n


@on("match_completed", priority=50)
def _injuries(t, fixture, result, rng):
    if not t.options.get("injuries", True):
        return
    if result.source == "real":       # reality mode: only what really happened (reality.py)
        return
    scale = float(t.options.get("injury_duration", 1.0))
    for side in (result.home, result.away):
        entry = t.teams.get(side.team_id)
        for line in side.players:
            if not line.injured or line.pid not in t.players:
                continue
            p = t.players[line.pid]
            kind, n = roll_injury(rng, scale)
            team = entry.name if entry else side.team_id
            if n <= 0:
                # Only the user's own knocks are news: everyone else's
                # would bury the headlines that matter.
                if entry and entry.human:
                    t.add_news("knock", f"{p.name} ({team}) took {with_article(kind)} but should be fine",
                               [side.team_id], p.pid)
                continue
            add_condition(t, p, Condition(kind="injury", matches_left=n, data={"type": kind}))
            if n >= OUT_FOR_TOURNAMENT:
                t.add_news("injury", f"Blow for {team}: {p.name} is out of the tournament ({kind})",
                           [side.team_id], p.pid)
            else:
                t.add_news("injury", f"{p.name} ({team}) will miss {n} match{'es' if n != 1 else ''}"
                           f" with {with_article(kind)}", [side.team_id], p.pid)
