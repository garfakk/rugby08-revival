"""
tournament/discipline.py — Bans.

Template "discipline" block (defaults shown):
  {"red_ban": [1, 3],          # matches, rolled toward the short end
   "yellow_accumulation": 3,   # yellows that earn a ban (0 = off)
   "yellow_ban": 1,
   "citing_chance": 0.01}      # per team per match: a foul play citing
                               # nobody carded (1-2 matches)

Yellow counts live in the player's "discipline" component.
"""
from .conditions import add_condition
from .effects import component, register_component, register_condition_kind
from .events import on
from .model import Condition

DEFAULTS = {"red_ban": [1, 3], "yellow_accumulation": 3, "yellow_ban": 1, "citing_chance": 0.01}

register_condition_kind("suspension", "Suspended", blocks_selection=True,
                        describe=lambda c: f"suspended ({c.matches_left} match"
                                           f"{'es' if c.matches_left != 1 else ''})")
register_component("discipline", "player", lambda: {"yellows": 0})


def rules(t) -> dict:
    return dict(DEFAULTS, **(t.template.get("discipline") or {}))


def _ban(t, p, team, matches, why):
    add_condition(t, p, Condition(kind="suspension", matches_left=matches, data={"reason": why}))
    t.add_news("suspension", f"{p.name} ({t.team_name(team)}) banned for {matches} match"
               f"{'es' if matches != 1 else ''} ({why})", [team], p.pid)


@on("match_completed", priority=50)
def _discipline(t, fixture, result, rng):
    if not t.options.get("suspensions", True):
        return
    r = rules(t)
    for side in (result.home, result.away):
        for line in side.players:
            p = t.players.get(line.pid)
            if not p:
                continue
            if line.red_cards:
                lo, hi = r["red_ban"]
                _ban(t, p, side.team_id, lo + int(round((hi - lo) * rng.random() ** 2)), "red card")
                continue
            if line.yellow_cards and r["yellow_accumulation"]:
                d = component(p, "discipline")
                d["yellows"] = d.get("yellows", 0) + line.yellow_cards
                if d["yellows"] >= r["yellow_accumulation"]:
                    d["yellows"] = 0
                    _ban(t, p, side.team_id, r["yellow_ban"], f"{r['yellow_accumulation']} yellow cards")
        # a citing for something the referee missed
        if r["citing_chance"] and rng.random() < r["citing_chance"]:
            played = [t.players[l.pid] for l in side.players
                      if l.minutes > 0 and not l.red_cards and l.pid in t.players]
            if played:
                weights = [max(1, int(p.base.get("aggression", 50) or 50)) for p in played]
                p = rng.choices(played, weights)[0]
                _ban(t, p, side.team_id, 1 + (rng.random() < 0.3), "cited for foul play")
