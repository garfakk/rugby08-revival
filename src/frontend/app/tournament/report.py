"""
tournament/report.py — Plain-text descriptions for the UI (no Qt): match
reports, availability lists, fixture captions.
"""
from collections import Counter

from .effects import describe_condition, unavailable_reason
from .fatigue import level as fatigue_level


def fixture_caption(t, f) -> str:
    home = t.team_name(f.home) if f.home else (f.home_ref or "TBD")
    away = t.team_name(f.away) if f.away else (f.away_ref or "TBD")
    return f"{home} v {away}"


def venue_name(ds, f) -> str:
    info = (ds.stadiums if ds else {}).get(str(f.stadium_id)) if f.stadium_id else None
    return info.get("name", "") if info else ""


def _scorers(t, side, key):
    counts = Counter()
    for line in side.players:
        n = getattr(line, key)
        if n and line.pid:
            counts[t.player_name(line.pid)] += n
    return ", ".join(f"{name}{f' {n}' if n > 1 else ''}" for name, n in counts.most_common())


def match_report(t, f) -> str:
    r = f.result
    if not r:
        return "Not played yet."
    lines = [f"{t.team_name(f.home)} {r.score_text()} {t.team_name(f.away)}"]
    if r.source == "game":
        lines.append("Played in the game.")
    elif r.source == "forfeit":
        lines.append("Awarded (forfeit).")
    for side in (r.home, r.away):
        parts = []
        for key, label in (("tries", "Tries"), ("conversions", "Cons"), ("penalties", "Pens"),
                           ("drop_goals", "Drops")):
            s = _scorers(t, side, key)
            if s:
                parts.append(f"{label}: {s}")
        if side.penalty_tries:
            parts.append(f"Penalty tries: {side.penalty_tries}")
        cards = []
        for line in side.players:
            if line.red_cards:
                cards.append(f"{t.player_name(line.pid)} (red)")
            elif line.yellow_cards:
                cards.append(f"{t.player_name(line.pid)} (yellow)")
        if cards:
            parts.append("Cards: " + ", ".join(cards))
        hurt = [t.player_name(l.pid) for l in side.players if l.injured and l.pid]
        if hurt:
            parts.append("Injured: " + ", ".join(hurt))
        lines.append(f"{t.team_name(side.team_id)} — " + ("; ".join(parts) if parts else "no scorers"))
    motm = r.extra.get("motm")
    if motm:
        lines.append(f"Player of the match: {t.player_name(motm)}")
    return "\n".join(lines)


def availability(t, team_id) -> list:
    """[(pid, reason)] for every unavailable squad member."""
    entry = t.teams[team_id]
    out = []
    for pid in entry.squad:
        p = t.players.get(pid)
        if p:
            reason = unavailable_reason(t, p)
            if reason:
                out.append((pid, reason))
    return out


def player_status(t, p) -> str:
    reason = unavailable_reason(t, p)
    if reason:
        return reason
    notes = [describe_condition(c) for c in p.conditions]
    lv = fatigue_level(p)
    if t.options.get("fatigue", True) and lv >= 15:
        notes.append(f"tired {lv}%")
    return ", ".join(notes) or "fit"


def _ordinal(n) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


def campaign_summary(t, team_id) -> str:
    """Where a team's tournament ended (or stands): "champions", "lost the
    Quarter-final to Wales", "4th in Pool A"..."""
    from . import standings
    if t.champion == team_id:
        return "champions"
    mine = [f for f in t.fixtures if f.played and f.involves(team_id)]
    last = mine[-1] if mine else None
    if last and last.knockout:
        won = last.result.winner_id() == team_id
        other = t.team_name(last.away if last.home == team_id else last.home)
        if last.final:
            return "runners-up" if not won else "champions"
        if not won:
            return f"lost the {last.round_name or 'knockout'} to {other}"
        if not any(not f.played and f.involves(team_id) for f in t.fixtures):
            return f"won the {last.round_name or 'knockout'} against {other}"
    for stage in reversed(t.stages):
        if stage.kind != "round_robin":
            continue
        for g in stage.groups:
            tab = standings.group_table(t, stage, g)
            for i, row in enumerate(tab):
                if row.team_id == team_id and row.played:
                    where = g.name if len(stage.groups) > 1 else stage.name
                    return f"{_ordinal(i + 1)} in {where} ({row.points} pts)"
    return ""
