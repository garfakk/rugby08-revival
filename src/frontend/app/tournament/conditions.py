"""
tournament/conditions.py — Condition bookkeeping shared by every kind.

After each of a team's matches, every squad member's counted conditions
lose one match (whether he was selected or not — a ban or an injury is
served in team matches). This runs before the match's own consequences
(priority 10), so an injury picked up today isn't immediately ticked down.
"""
from .effects import describe_condition
from .events import on


def add_condition(t, player, condition) -> None:
    """Add, merging with an existing condition of the same kind by keeping
    the longer absence."""
    for c in player.conditions:
        if c.kind == condition.kind:
            if c.matches_left is not None and (condition.matches_left is None
                                               or condition.matches_left > c.matches_left):
                c.matches_left = condition.matches_left
                c.data.update(condition.data)
            return
    condition.since_day = t.day
    player.conditions.append(condition)


@on("match_completed", priority=10)
def _tick(t, fixture, result, rng):
    for tid in (fixture.home, fixture.away):
        entry = t.teams.get(tid)
        if not entry:
            continue
        for pid in entry.squad:
            p = t.players.get(pid)
            if not p or not p.conditions:
                continue
            kept = []
            for c in p.conditions:
                if c.matches_left is not None:
                    c.matches_left -= 1
                    if c.matches_left <= 0:
                        if c.data.get("announce_return", True):
                            t.add_news("return", f"{p.name} ({entry.name}) is available again"
                                       f" after {describe_condition_past(c)}", [tid], pid)
                        continue
                kept.append(c)
            p.conditions = kept


def describe_condition_past(c) -> str:
    if c.kind == "injury":
        return f"his {c.data.get('type', 'injury')}"
    if c.kind == "suspension":
        return "his suspension"
    return describe_condition(c).lower()
