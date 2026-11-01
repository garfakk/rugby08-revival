"""
tournament/returning.py — A man back from injury gets his shirt back, probably.

When a starter is hurt (and misses at least one match) his slot is
remembered. Once he is fit again the AI's pick gets a small nudge toward him
for that slot: enough to settle a close call, not enough to keep a clearly
worse player in the side. The memory is dropped as soon as he plays again.
"""
from .effects import component, register_component
from .events import on
from .selection import register_selection_weight

REGAIN_NUDGE = 1.05       # ~4 rating points of the slot score

register_component("returning", "player", lambda: {})


def _weight(t, player, ctx):
    slot = player.components.get("returning", {}).get("slot")
    if slot is not None and ctx.slot == slot + 1:
        return REGAIN_NUDGE
    return 1.0


register_selection_weight("returning", _weight)


@on("match_completed", priority=55)
def _forget(t, fixture, result, rng):
    for side in (result.home, result.away):
        for line in side.players:
            p = t.players.get(line.pid)
            if p and line.minutes > 0 and "returning" in p.components:
                p.components["returning"].pop("slot", None)


@on("match_completed", priority=60)
def _remember(t, fixture, result, rng):
    for side in (result.home, result.away):
        entry = t.teams.get(side.team_id)
        chosen = list((entry.selection or {}).get("players", [])) if entry else []
        for line in side.players:
            p = t.players.get(line.pid)
            if not p or not line.started or line.pid not in chosen:
                continue
            # hurt badly enough to miss a match (knocks add no condition)
            if not (line.injured and any(c.kind == "injury" for c in p.conditions)):
                continue
            slot = chosen.index(line.pid)
            if slot < 15:
                component(p, "returning")["slot"] = slot
