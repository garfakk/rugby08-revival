"""
tournament/manual.py — A MatchResult typed in by hand (expert mode), for a
match that was played elsewhere or that the user wants to decide themselves.

The input is a list of events per side; the scorers' lines (and so the score,
the stats, cards and injuries every subscriber reads) are derived from them.
An injury or a ban may carry its length ("matches", and "type" for an
injury): kept in result.extra["manual"] so injuries.py / discipline.py apply
it instead of rolling one. A "suspension" event is a ban without a card
(a citing).

from_result() turns a simulated MatchResult into the same event lists, for
the form's AUTO-GENERATE.
"""
from .model import MatchResult, PlayerLine, SideResult

# event kind -> PlayerLine counters it adds to
EVENT_KINDS = ("try", "conversion", "penalty", "drop", "yellow", "red", "injury", "suspension")
# kinds whose length in matches can be set
LENGTH_KINDS = ("red", "injury", "suspension")


def _side(t, team_id, events, penalty_tries, overrides):
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
        matches = ev.get("matches", 1 if kind == "suspension" else None)
        if kind == "injury" and matches is not None:
            overrides["injuries"][line.pid] = {"type": str(ev.get("type") or "injury"),
                                               "matches": max(0, int(matches))}
        elif kind in ("red", "suspension") and matches is not None:
            overrides["bans"][line.pid] = max(0, int(matches))
        if not line.started and line.minutes == 0:
            line.minutes = 20                 # a bench player with an event did come on
        out_events.append({"minute": int(ev.get("minute", 0)), "team": team_id,
                           "kind": kind, "pid": line.pid})
    return SideResult(team_id=team_id, players=list(lines.values()),
                      penalty_tries=int(penalty_tries or 0)), out_events


def build_result(t, fixture, home_events, away_events, home_penalty_tries=0,
                 away_penalty_tries=0, winner=None, decided_by="") -> MatchResult:
    """`winner` / `decided_by` only count for a level knockout match."""
    overrides = {"injuries": {}, "bans": {}}
    home, home_ev = _side(t, fixture.home, home_events, home_penalty_tries, overrides)
    away, away_ev = _side(t, fixture.away, away_events, away_penalty_tries, overrides)
    result = MatchResult(home=home, away=away, source="manual",
                         events=sorted(home_ev + away_ev, key=lambda e: e["minute"]),
                         extra={"manual": overrides})
    if fixture.knockout and home.points == away.points:
        result.winner = winner if winner in (fixture.home, fixture.away) else fixture.home
        result.decided_by = decided_by if decided_by in ("tries", "kicks") else "tries"
    return result


def from_result(t, result, rng) -> tuple:
    """(home events, away events, home penalty tries, away penalty tries) of
    a simulated result, injuries and red-card bans with a rolled length so
    the form shows what will apply."""
    from . import discipline, injuries
    scale = float(t.options.get("injury_duration", 1.0))
    lo, hi = discipline.rules(t)["red_ban"]
    out = {result.home.team_id: [], result.away.team_id: []}
    for ev in result.events:
        kind = ev.get("kind")
        if kind not in EVENT_KINDS or ev.get("team") not in out:
            continue
        row = {"minute": int(ev.get("minute", 0)), "kind": kind, "pid": ev.get("pid")}
        if kind == "injury":
            row["type"], row["matches"] = injuries.roll_injury(rng, scale)
        elif kind == "red":
            row["matches"] = lo + int(round((hi - lo) * rng.random() ** 2))
        out[ev["team"]].append(row)
    return (out[result.home.team_id], out[result.away.team_id],
            result.home.penalty_tries, result.away.penalty_tries)
