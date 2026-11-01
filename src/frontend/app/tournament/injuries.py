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
    ("bruised thigh", 10, 0, 1),
    ("pulled hamstring", 14, 1, 3),
    ("twisted ankle", 12, 1, 3),
    ("pulled calf", 8, 1, 2),
    ("concussion", 10, 1, 2),
    ("dislocated shoulder", 7, 2, 5),
    ("cracked ribs", 4, 1, 3),
    ("sprained knee", 3, 3, 8),
    ("broken thumb", 1.5, 2, 4),
    ("torn ACL", 0.5, None, None),
]
OUT_FOR_TOURNAMENT = 99


def _matches(n) -> str:
    return "the next match" if n == 1 else f"the next {n} matches"


def _describe(c):
    n = c.matches_left
    kind = c.data.get("type", "injury")
    if n is None or n >= OUT_FOR_TOURNAMENT:
        return f"{kind}: out for the rest of the tournament"
    return f"{kind}: misses {_matches(n)}"


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
    # a result typed in by hand may say how long (manual.py)
    chosen = (result.extra.get("manual") or {}).get("injuries") or {}
    for side in (result.home, result.away):
        entry = t.teams.get(side.team_id)
        for line in side.players:
            if not line.injured or line.pid not in t.players:
                continue
            p = t.players[line.pid]
            if line.pid in chosen:
                kind, n = chosen[line.pid]["type"], int(chosen[line.pid]["matches"])
            else:
                kind, n = roll_injury(rng, scale)
            team = entry.name if entry else side.team_id
            if n <= 0:
                # Only the user's own knocks are news: everyone else's
                # would bury the headlines that matter.
                if entry and entry.human:
                    t.add_news("knock", f"{p.name} ({team}) was hurt"
                               f"{'' if kind == 'knock' else f' ({kind})'} but should be fine",
                               [side.team_id], p.pid)
                continue
            add_condition(t, p, Condition(kind="injury", matches_left=n, data={"type": kind}))
            if n >= OUT_FOR_TOURNAMENT:
                t.add_news("injury", f"{p.name} ({team}) will miss the rest of the tournament ({kind})",
                           [side.team_id], p.pid)
            else:
                t.add_news("injury", f"{p.name} ({team}) will miss {_matches(n)} ({kind})",
                           [side.team_id], p.pid)
