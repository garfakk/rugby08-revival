"""
tournament/standings.py — Pool/league tables.

Points come from the template's "points" block:
  {"win": 4, "draw": 2, "loss": 0,
   "try_bonus": {"tries": 4}            # 4+ tries scored
             or {"margin": 3},          # 3+ tries more than the opponent
   "losing_bonus": {"margin": 7}}       # lose by 7 or less
A missing bonus block means no such bonus.

Ties on points are broken by the template's "tiebreakers" chain, applied
cluster by cluster (head-to-head is computed among the tied teams only):
  head_to_head, points_diff, tries_diff, points_for, tries_for,
  fewest_cards, lots (seeded, so a reload gives the same order).
"""
import random
from dataclasses import dataclass, field

DEFAULT_POINTS = {"win": 4, "draw": 2, "loss": 0,
                  "try_bonus": {"tries": 4}, "losing_bonus": {"margin": 7}}
DEFAULT_TIEBREAKERS = ["head_to_head", "points_diff", "tries_diff",
                       "points_for", "tries_for", "fewest_cards", "lots"]


@dataclass
class Row:
    team_id: str
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    points_for: int = 0
    points_against: int = 0
    tries_for: int = 0
    tries_against: int = 0
    try_bonus: int = 0
    losing_bonus: int = 0
    points: int = 0
    yellow: int = 0
    red: int = 0
    form: list = field(default_factory=list)   # "W"/"D"/"L", oldest first

    @property
    def points_diff(self):
        return self.points_for - self.points_against

    @property
    def tries_diff(self):
        return self.tries_for - self.tries_against

    @property
    def bonus(self):
        return self.try_bonus + self.losing_bonus


def match_points(rules, own, opp) -> tuple:
    """(table points, try bonus, losing bonus) for one side's result."""
    rules = rules or DEFAULT_POINTS
    if own.points > opp.points:
        pts = rules.get("win", 4)
    elif own.points == opp.points:
        pts = rules.get("draw", 2)
    else:
        pts = rules.get("loss", 0)
    tb = 0
    try_rule = rules.get("try_bonus")
    if try_rule:
        if "tries" in try_rule and own.tries >= try_rule["tries"]:
            tb = 1
        if "margin" in try_rule and own.tries - opp.tries >= try_rule["margin"]:
            tb = 1
    lb = 0
    lose_rule = rules.get("losing_bonus")
    if lose_rule and own.points < opp.points and opp.points - own.points <= lose_rule.get("margin", 7):
        lb = 1
    return pts + tb + lb, tb, lb


def _rows(fixtures, team_ids, rules) -> dict:
    rows = {tid: Row(tid) for tid in team_ids}
    for f in fixtures:
        if not f.result or f.home not in rows or f.away not in rows:
            continue
        r = f.result
        for own, opp in ((r.home, r.away), (r.away, r.home)):
            row = rows[own.team_id]
            row.played += 1
            row.points_for += own.points
            row.points_against += opp.points
            row.tries_for += own.tries
            row.tries_against += opp.tries
            row.yellow += own.yellow_cards
            row.red += own.red_cards
            pts, tb, lb = match_points(rules, own, opp)
            row.points += pts
            row.try_bonus += tb
            row.losing_bonus += lb
            winner = r.winner_id()
            if r.source == "forfeit" or r.decided_by == "forfeit":
                outcome = "W" if winner == own.team_id else "L"
            elif own.points > opp.points:
                outcome = "W"
            elif own.points == opp.points:
                outcome = "D"
            else:
                outcome = "L"
            row.form.append(outcome)
            if outcome == "W":
                row.won += 1
            elif outcome == "D":
                row.drawn += 1
            else:
                row.lost += 1
    return rows


def _key(criterion, row, h2h):
    if criterion == "head_to_head":
        sub = h2h.get(row.team_id)
        return (sub.points, sub.points_diff) if sub else (0, 0)
    if criterion == "points_diff":
        return row.points_diff
    if criterion == "tries_diff":
        return row.tries_diff
    if criterion == "points_for":
        return row.points_for
    if criterion == "tries_for":
        return row.tries_for
    if criterion == "fewest_cards":
        return -(row.yellow + 2 * row.red)
    if criterion == "wins":
        return row.won
    return 0


def _order(cluster, chain, fixtures, rules, rng):
    """Order a list of rows tied on points."""
    if len(cluster) <= 1:
        return cluster
    if not chain:
        return cluster
    criterion, rest = chain[0], chain[1:]
    if criterion == "lots":
        cluster = sorted(cluster, key=lambda r: r.team_id)
        rng.shuffle(cluster)
        return cluster
    h2h = {}
    if criterion == "head_to_head":
        ids = [r.team_id for r in cluster]
        h2h = _rows([f for f in fixtures if f.home in ids and f.away in ids], ids, rules)
    keyed = sorted(cluster, key=lambda r: _key(criterion, r, h2h), reverse=True)
    out, i = [], 0
    while i < len(keyed):
        j = i
        k = _key(criterion, keyed[i], h2h)
        while j < len(keyed) and _key(criterion, keyed[j], h2h) == k:
            j += 1
        out.extend(_order(keyed[i:j], rest, fixtures, rules, rng))
        i = j
    return out


def table(fixtures, team_ids, rules=None, tiebreakers=None, seed="") -> list:
    """Sorted [Row] for `team_ids` over `fixtures` (unplayed ones ignored)."""
    rules = rules or DEFAULT_POINTS
    chain = list(tiebreakers or DEFAULT_TIEBREAKERS)
    rows = _rows(fixtures, team_ids, rules)
    rng = random.Random(f"lots:{seed}")
    by_points = sorted(rows.values(), key=lambda r: r.points, reverse=True)
    out, i = [], 0
    while i < len(by_points):
        j = i
        while j < len(by_points) and by_points[j].points == by_points[i].points:
            j += 1
        out.extend(_order(by_points[i:j], chain, fixtures, rules, rng))
        i = j
    return out


def group_table(t, stage, group) -> list:
    fixtures = [f for f in t.fixtures if f.stage_id == stage.id and f.group == group.id]
    return table(fixtures, group.teams, t.template.get("points"),
                 t.template.get("tiebreakers"), seed=f"{t.seed}:{stage.id}:{group.id}")


def cross_group_ranking(t, stage, position) -> list:
    """The teams finishing `position` (1-based) in each group of `stage`,
    best first — for "best runner-up" / "best third" qualifiers. Groups of
    different sizes are compared per match played."""
    rows = []
    for g in stage.groups:
        tab = group_table(t, stage, g)
        if len(tab) >= position:
            rows.append(tab[position - 1])

    def key(r):
        n = max(1, r.played)
        return (r.points / n, r.points_diff / n, r.tries_diff / n, r.points_for / n)

    return sorted(rows, key=key, reverse=True)
