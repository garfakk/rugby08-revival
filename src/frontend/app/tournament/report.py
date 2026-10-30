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


def group_title(stage, group) -> str:
    """What a pool is called on screen: its own name ("Pool A") when the
    stage has several, "Table" for a stage that is one league."""
    return group.name if len(stage.groups) > 1 else "Table"


def in_group(stage, group) -> str:
    """"in Pool A" / "in the table", after a position."""
    return f"in {group.name}" if len(stage.groups) > 1 else "in the table"


def round_title(t, day) -> str:
    """What matchday `day` is called: "Round 3" (its stage's third round)
    or a knockout round's name ("Quarter-final")."""
    f = next((f for f in t.fixtures if f.day == day), None)
    return (f.round_name if f else "") or f"Round {day + 1}"


def round_short(t, day) -> str:
    """round_title() in a few letters, for tags: "R3", "QF", "FINAL"."""
    title = round_title(t, day)
    if title.startswith("Round ") and title[6:].isdigit():
        return f"R{title[6:]}"
    words = title.replace("-", " ").split()
    return title.upper() if len(words) == 1 else "".join(w[0] for w in words).upper()


def round_position(t, f):
    """(round number, round count) of a pool fixture within its stage, else
    None (a knockout round goes by its name)."""
    if f.knockout:
        return None
    days = sorted({g.day for g in t.fixtures if g.stage_id == f.stage_id})
    return (days.index(f.day) + 1, len(days)) if f.day in days else None


def where_now(t) -> str:
    """Where the tournament stands, by the next match to play: "Pool stage
    · Round 3 of 7", "Round 2 of 5" (a one-stage competition), "Quarter-
    final"; "Tournament complete" at the end."""
    if t.finished:
        return "Tournament complete"
    nxt = next((f for f in sorted(t.fixtures, key=lambda f: f.day) if not f.played), None)
    if not nxt:
        return ""
    if nxt.knockout:
        return nxt.round_name or "Knockouts"
    stage = t.stage(nxt.stage_id)
    n, total = round_position(t, nxt) or (0, 0)
    where = f"Round {n} of {total}" if n else ""
    if stage and len(t.stages) > 1:
        where = f"{stage.name} · {where}" if where else stage.name
    return where


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
                    return f"{_ordinal(i + 1)} {in_group(stage, g)} ({row.points} pts)"
    return ""


def match_stats(result) -> list:
    """[(label, home, away)] comparing the two sides of a recorded match:
    scoring, kicks made/attempted, tackles, cards; scrums and lineouts only
    when the game reported them (matches played in it)."""
    h, a = result.home, result.away

    def total(side, key):
        return sum(getattr(line, key) for line in side.players)

    def kicks(side, made, tried):
        n, of = total(side, made), total(side, tried)
        return f"{n}/{of}" if of else n

    rows = [("TRIES", h.tries, a.tries)]
    if h.penalty_tries or a.penalty_tries:
        rows.append(("PENALTY TRIES", h.penalty_tries, a.penalty_tries))
    rows += [("CONVERSIONS", kicks(h, "conversions", "conversions_attempted"),
              kicks(a, "conversions", "conversions_attempted")),
             ("PENALTIES", kicks(h, "penalties", "penalties_attempted"),
              kicks(a, "penalties", "penalties_attempted")),
             ("DROP GOALS", total(h, "drop_goals"), total(a, "drop_goals")),
             ("TACKLES", total(h, "tackles"), total(a, "tackles"))]
    for key, label in (("scrums_won", "SCRUMS WON"), ("lineouts_won", "LINEOUTS WON")):
        if key in h.stats or key in a.stats:
            rows.append((label, h.stats.get(key, 0), a.stats.get(key, 0)))
    rows += [("YELLOW CARDS", h.yellow_cards, a.yellow_cards),
             ("RED CARDS", h.red_cards, a.red_cards)]
    return rows


def top_tacklers(t, side, n=3) -> str:
    """ "J.Smith 14, A.Jones 11, ..." for one side of a recorded match."""
    lines = sorted((line for line in side.players if line.tackles and line.pid),
                   key=lambda line: -line.tackles)[:n]
    return ", ".join(f"{t.player_name(line.pid)} {line.tackles}" for line in lines)
