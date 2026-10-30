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
    # reality mode: the real bans come from reality.py, only the real
    # yellows still add up toward a yellow-card ban
    real = result.source == "real"
    # a result typed in by hand says who is banned and for how long
    # (manual.py): no rolled length, no random citing
    manual = result.source == "manual"
    chosen = (result.extra.get("manual") or {}).get("bans") or {}
    r = rules(t)
    for side in (result.home, result.away):
        for line in side.players:
            p = t.players.get(line.pid)
            if not p:
                continue
            if line.red_cards and not real:
                lo, hi = r["red_ban"]
                n = chosen.get(line.pid)
                if n is None:
                    n = lo + int(round((hi - lo) * rng.random() ** 2))
                if n > 0:
                    _ban(t, p, side.team_id, n, "red card")
                continue
            if line.pid in chosen and chosen[line.pid] > 0:
                _ban(t, p, side.team_id, chosen[line.pid], "cited for foul play")
            if line.yellow_cards and r["yellow_accumulation"]:
                d = component(p, "discipline")
                d["yellows"] = d.get("yellows", 0) + line.yellow_cards
                if d["yellows"] >= r["yellow_accumulation"]:
                    d["yellows"] = 0
                    _ban(t, p, side.team_id, r["yellow_ban"], f"{r['yellow_accumulation']} yellow cards")
        # a citing for something the referee missed
        if r["citing_chance"] and not real and not manual and rng.random() < r["citing_chance"]:
            played = [t.players[l.pid] for l in side.players
                      if l.minutes > 0 and not l.red_cards and l.pid in t.players]
            if played:
                weights = [max(1, int(p.base.get("aggression", 50) or 50)) for p in played]
                p = rng.choices(played, weights)[0]
                _ban(t, p, side.team_id, 1 + (rng.random() < 0.3), "cited for foul play")
