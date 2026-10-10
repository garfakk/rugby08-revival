"""
tournament/manual.py — A MatchResult typed in by hand (expert mode), for a
match that was played elsewhere or that the user wants to decide themselves.

The input is a list of events per side; the scorers' lines (and so the score,
the stats, cards and injuries every subscriber reads) are derived from them.
"""
from .model import MatchResult, PlayerLine, SideResult

# event kind -> PlayerLine counters it adds to
EVENT_KINDS = ("try", "conversion", "penalty", "drop", "yellow", "red", "injury")


def _side(t, team_id, events, penalty_tries, team_key):
    sel = list(t.teams[team_id].selection.get("players", []))
    lines = {pid: PlayerLine(pid=pid, started=i < 15, minutes=80 if i < 15 else 0)
             for i, pid in enumerate(sel)}
    out_events = []
    for ev in events:
        line = lines.get(ev.get("pid"))
        kind = ev.get("kind")
        if line is None or kind not in EVENT_KINDS:
            continue
        if kind == "try":
            line.tries += 1
        elif kind == "conversion":
            line.conversions += 1
            line.conversions_attempted += 1
        elif kind == "penalty":
            line.penalties += 1
            line.penalties_attempted += 1
        elif kind == "drop":
            line.drop_goals += 1
        elif kind == "yellow":
            line.yellow_cards += 1
        elif kind == "red":
            line.red_cards += 1
        elif kind == "injury":
            line.injured = True
        if not line.started and line.minutes == 0:
            line.minutes = 20                 # a bench player with an event did come on
        out_events.append({"minute": int(ev.get("minute", 0)), "team": team_id,
                           "kind": kind, "pid": line.pid})
    return SideResult(team_id=team_id, players=list(lines.values()),
                      penalty_tries=int(penalty_tries or 0)), out_events


def build_result(t, fixture, home_events, away_events, home_penalty_tries=0,
                 away_penalty_tries=0, winner=None, decided_by="") -> MatchResult:
    """`winner` / `decided_by` only count for a level knockout match."""
    home, home_ev = _side(t, fixture.home, home_events, home_penalty_tries, "home")
    away, away_ev = _side(t, fixture.away, away_events, away_penalty_tries, "away")
    result = MatchResult(home=home, away=away, source="manual",
                         events=sorted(home_ev + away_ev, key=lambda e: e["minute"]))
    if fixture.knockout and home.points == away.points:
        result.winner = winner if winner in (fixture.home, fixture.away) else fixture.home
        result.decided_by = decided_by if decided_by in ("tries", "kicks") else "tries"
    return result
