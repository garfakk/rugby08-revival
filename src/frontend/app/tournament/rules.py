"""
tournament/rules.py — The rules a tournament is played under, as short
(label, value) lines for the dashboard's RULES tab.

The laws are the edition's (template default_options), unless the wizard or
the settings tab set them; a tournament saved before they existed gets its
template's.
"""
from . import discipline, standings
from .custom import KNOCKOUT_DRAWS, TIEBREAKERS

LAWS = (("law_5022", "50/22"), ("law_22m", "22m"), ("law_penalty_touch", "80' penalty touch"))


# One plain sentence per law, and a lead-in for the tie-breaker list (the
# dashboard shows them under the line / the title)
NOTES = {
    "50/22": "Kick from your own half that bounces into touch in their 22: you throw in.",
    "22m": "Ball brought back into your 22, then kicked out: no gain in ground.",
    "80' penalty touch": "A penalty kicked to touch after full time still gets its line-out.",
}
INTROS = {"Tie-breakers": "Teams on the same points are split by the first of these that differs."}


def laws(t) -> dict:
    """{"law_5022": bool, "law_22m": bool, "law_penalty_touch": bool} of tournament `t`."""
    base = (t.template or {}).get("default_options") or {}
    return {key: bool(t.options.get(key, base.get(key, True))) for key, _label in LAWS}


def _on(flag) -> str:
    return "On" if flag else "Off"


def _bonus_lines(points) -> list:
    lines = []
    tries = points.get("try_bonus")
    if tries:
        lines.append(("Try bonus", f"{tries['tries']} tries scored" if "tries" in tries
                      else f"{tries.get('margin', 3)} tries more than the opponent"))
    losing = points.get("losing_bonus")
    if losing:
        lines.append(("Losing bonus", f"lose by {losing.get('margin', 7)} or less"))
    if points.get("grand_slam"):
        lines.append(("Grand Slam", f"+{points['grand_slam']} for winning every match"))
    return lines


def _matches(n) -> str:
    return f"{n} match" + ("" if n == 1 else "es")


def _ban(lo, hi) -> str:
    return _matches(lo) if lo == hi else f"{lo} to {hi} matches"


def sections(t) -> list:
    """[(title, [(label, value)])] of the rules of `t`: laws, discipline, the
    table's points and tie-breaks (when there is a table) and how a drawn
    knockout is decided (when there are knockouts)."""
    tpl = t.template or {}
    kinds = {s.kind for s in t.stages}
    out = [("Laws", [(label, _on(laws(t)[key])) for key, label in LAWS])]
    table = []
    if "round_robin" in kinds:
        points = tpl.get("points") or standings.DEFAULT_POINTS
        table = [("Win", points.get("win", 4)), ("Draw", points.get("draw", 2)),
                 ("Loss", points.get("loss", 0))] + _bonus_lines(points)
        table = [(a, str(b)) for a, b in table]
    if "knockout" in kinds:
        table.append(("Drawn knockout", KNOCKOUT_DRAWS.get(tpl.get("knockout_draw", "tries_then_kicks"),
                                                           "most tries, then kicks").capitalize()))
    if table:
        out.append(("Points" if "round_robin" in kinds else "Knockouts", table))
    if t.options.get("suspensions", True):
        d = discipline.rules(t)
        lines = [("Red card", "ban of " + _ban(*d["red_ban"]))]
        if d["yellow_accumulation"]:
            lines.append((f"{d['yellow_accumulation']} yellow cards", "ban of " + _matches(d["yellow_ban"])))
        else:
            lines.append(("Yellow cards", "no ban"))
        out.append(("Discipline", lines))
    else:
        out.append(("Discipline", [("Suspensions", "Off")]))
    if "round_robin" in kinds:
        chain = tpl.get("tiebreakers") or standings.DEFAULT_TIEBREAKERS
        out.append(("Tie-breakers", [(str(i + 1), TIEBREAKERS.get(k, k)) for i, k in enumerate(chain)]))
    return out
