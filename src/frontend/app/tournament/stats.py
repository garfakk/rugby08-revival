"""
tournament/stats.py — Running player aggregates and leaderboards.

t.stats["players"][pid] = {apps, starts, minutes, tries, conversions,
penalties, drop_goals, points, tackles, yellow, red, motm}. Player of the
match is picked here (a weighted contribution score) and stored in the
result's `extra`.
"""
from .events import on

FIELDS = ("apps", "starts", "minutes", "tries", "conversions", "penalties", "drop_goals",
          "points", "tackles", "yellow", "red", "motm")

LEADERBOARDS = {
    "points": "Points",
    "tries": "Tries",
    "tackles": "Tackles",
    "motm": "Player of the match",
    "minutes": "Minutes",
    "yellow": "Yellow cards",
}


def contribution(line) -> float:
    return (line.tries * 6 + line.conversions * 1.5 + line.penalties * 2.2 + line.drop_goals * 2.5
            + line.tackles * 0.35 - line.yellow_cards * 3 - line.red_cards * 8
            + line.minutes / 40.0)


def player_of_the_match(result):
    winner = result.winner_id()
    best = None
    for side in (result.home, result.away):
        bonus = 1.15 if side.team_id == winner else 1.0
        for line in side.players:
            score = contribution(line) * bonus
            if best is None or score > best[0]:
                best = (score, line.pid)
    return best[1] if best else None


@on("match_completed", priority=80)
def _aggregate(t, fixture, result, rng):
    table = t.stats.setdefault("players", {})
    motm = player_of_the_match(result)
    result.extra["motm"] = motm
    for side in (result.home, result.away):
        for line in side.players:
            if line.minutes <= 0 and not line.started:
                continue
            s = table.setdefault(line.pid, {k: 0 for k in FIELDS})
            s["apps"] += 1
            s["starts"] += 1 if line.started else 0
            s["minutes"] += line.minutes
            s["tries"] += line.tries
            s["conversions"] += line.conversions
            s["penalties"] += line.penalties
            s["drop_goals"] += line.drop_goals
            s["points"] += line.points
            s["tackles"] += line.tackles
            s["yellow"] += line.yellow_cards
            s["red"] += line.red_cards
            s["motm"] += 1 if line.pid == motm else 0


def leaders(t, key, limit=10, team_id=None) -> list:
    """[(pid, value)] best first, zero values left out."""
    rows = [(pid, s.get(key, 0)) for pid, s in t.stats.get("players", {}).items()
            if s.get(key, 0) and (team_id is None or (pid in t.players and t.players[pid].team_id == team_id))]
    rows.sort(key=lambda r: (-r[1], t.player_name(r[0])))
    return rows[:limit]


def team_of_the_tournament(t) -> list:
    """[(slot position, pid)] — best contribution per minute among regulars,
    one per XV slot."""
    from .strength import SLOT_POSITIONS, position_fit
    table = t.stats.get("players", {})
    used, team = set(), []
    for pos in SLOT_POSITIONS[:15]:
        best = None
        for pid, s in table.items():
            p = t.players.get(pid)
            if not p or pid in used or s["minutes"] < 120:
                continue
            fit = position_fit(p.positions, pos)
            if fit < 0.95:
                continue
            per80 = (s["tries"] * 6 + s["points"] * 0.4 + s["tackles"] * 0.35 + s["motm"] * 4) \
                / max(1.0, s["minutes"] / 80.0)
            if best is None or per80 > best[0]:
                best = (per80, pid)
        if best:
            used.add(best[1])
            team.append((pos, best[1]))
    return team
