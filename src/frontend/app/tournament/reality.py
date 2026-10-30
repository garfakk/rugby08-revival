"""
tournament/reality.py — Reality mode: the rest of the tournament as it really was.

A historical edition (Six Nations, Rugby World Cup...) lists each fixture's
real score in its template (`real_score`, "36–14"), and may list what else
really happened in it (`real_events`) and its real try count (`real_tries`):

  {"date": ..., "home": "10002", "away": "1001", "real_score": "27–10",
   "real_tries": [0, 1],
   "real_events": [
     {"kind": "red", "team": "10002", "player": "Tom Curry", "minute": 3},
     {"kind": "suspension", "team": "10002", "player": "Tom Curry", "matches": 2,
      "reason": "red card"},
     {"kind": "injury", "team": "10001", "player": "Antoine Dupont", "matches": 1,
      "type": "fractured cheekbone"},
     {"kind": "try" | "conversion" | "penalty" | "drop" | "yellow", "team": ..., "player": ...}]}

With the tournament option "reality" (offered by the wizard only when
`available()`), a match between two AI teams that really met gets its real
score (source "real"), and the real injuries and bans from it apply exactly
(the random ones are not rolled for it). The user's matches are played or
simulated as usual: the user's team is only touched by its own games. A
knockout tie the user's results changed (teams that never met) is simulated.

`real_schedule()` works out, once at creation, who really met in every
fixture (the knockout teams from the template's `history` and the real
scores) and keeps it in t.components["reality"], so a save stands alone.
"""
import re
import unicodedata

from shared.log import get_logger

from .conditions import add_condition
from .events import on
from .model import Condition, MatchResult, PlayerLine

log = get_logger(__name__)

SCORE = re.compile(r"(\d+)\s*[–-]\s*(\d+)")
SCORING = {"try": 5, "conversion": 2, "penalty": 3, "drop": 3}
# How likely each position is to score a try (relative).
TRY_WEIGHT = {"winger": 5.0, "fullback": 4.0, "centre": 3.5, "openside_flanker": 2.5,
              "blindside_flanker": 2.2, "number_eight": 2.5, "scrum_half": 2.0, "fly_half": 1.8,
              "hooker": 2.0, "second_row": 1.0, "loosehead_prop": 0.8, "tighthead_prop": 0.8}


# ── reading the template ─────────────────────────────────────────────────
def parse_score(text):
    """("27–10" -> (27, 10, False)); a cancelled match with an awarded score
    keeps it and says so; None when there is no score."""
    if not text:
        return None
    m = SCORE.search(str(text))
    if not m:
        return None
    return int(m.group(1)), int(m.group(2)), "cancel" in str(text).lower()


def _template_fixtures(template):
    """[(stage spec, kind, entry)] of every fixture / tie of the template."""
    out = []
    for spec in template.get("stages", []):
        if spec.get("kind", "round_robin") == "round_robin":
            out += [(spec, "pool", f) for f in spec.get("fixtures") or []]
        else:
            for rnd in spec.get("rounds", []):
                out += [(spec, "tie", tie) for tie in rnd.get("ties", [])]
    return out


def available(template, participants=None, season=None, known_teams=None):
    """(True, "") when reality mode can be offered for this template (and
    draw), else (False, why). `known_teams`: the team ids the data has (a
    real participant missing from it means the real draw can't be played)."""
    fixtures = _template_fixtures(template or {})
    pools = [f for _s, kind, f in fixtures if kind == "pool"]
    if not fixtures or not pools:
        return False, "No real results for this edition"
    for spec in template.get("stages", []):
        if spec.get("kind", "round_robin") == "round_robin" and not spec.get("fixtures"):
            return False, "No real results for this edition"
    for _s, kind, f in fixtures:
        if not isinstance(f, dict) or parse_score(f.get("real_score")) is None:
            return False, "No real results for this edition"
    if any(kind == "tie" for _s, kind, _f in fixtures) and not (template.get("history") or {}).get("pool_winners"):
        return False, "No real knockout bracket for this edition"
    from .engine import default_participants
    real_draw = default_participants(template, season or template.get("season", ""))
    if known_teams is not None:
        # a team the data doesn't have is left out with its matches; the
        # real bracket still holds unless it reached the knockouts
        missing = {t for groups in real_draw.values() for ts in groups.values() for t in ts} - set(known_teams)
        history = template.get("history") or {}
        ko_teams = {str(v) for key in ("pool_winners", "pool_runners_up")
                    for v in (history.get(key) or {}).values()}
        if missing & ko_teams:
            return False, f"Teams of the real knockouts are missing from the data ({', '.join(sorted(missing))})"
        real_draw = {sid: {gid: [t for t in ts if t not in missing] for gid, ts in groups.items()}
                     for sid, groups in real_draw.items()}
    if participants is not None:
        if _norm_parts(participants) != _norm_parts(real_draw):
            return False, "Reality mode needs the real draw"
    return True, ""


def _norm_parts(parts):
    return {sid: {gid: sorted(str(t) for t in teams) for gid, teams in groups.items()}
            for sid, groups in (parts or {}).items()}


def real_schedule(t):
    """{fixture id: {"home", "away", "score": [h, a], "tries": [h, a] | None,
    "events": [...], "cancelled": bool}} for every fixture whose real teams
    are known."""
    history = t.template.get("history") or {}
    pools = {}               # (date, home, away) -> template entry
    ties = {}                # tie id -> template entry
    for spec, kind, f in _template_fixtures(t.template):
        if kind == "pool":
            pools[(str(f.get("date")), str(f.get("home")), str(f.get("away")))] = f
    for spec in t.template.get("stages", []):
        if spec.get("kind") == "knockout":
            for rnd in spec.get("rounds", []):
                for i, tie in enumerate(rnd.get("ties", [])):
                    tid = tie.get("id") if isinstance(tie, dict) else f"{rnd['id']}{i + 1}"
                    ties[tid] = tie

    out = {}

    def entry(home, away, raw):
        score = parse_score(raw.get("real_score"))
        tries = raw.get("real_tries")
        winner = str(raw.get("real_winner") or "")
        if score[0] == score[1] and winner not in (home, away):
            champ = str(history.get("champion") or "")
            winner = champ if champ in (home, away) else ""
        return {"home": home, "away": away, "score": [score[0], score[1]],
                "tries": list(tries) if isinstance(tries, list) and len(tries) == 2 else None,
                "events": list(raw.get("real_events") or []), "cancelled": score[2],
                "winner": winner or None}

    for f in t.fixtures:
        if f.knockout:
            continue
        raw = pools.get((f.date, f.home, f.away))
        if raw and parse_score(raw.get("real_score")):
            out[f.id] = entry(f.home, f.away, raw)

    winners, runners = history.get("pool_winners") or {}, history.get("pool_runners_up") or {}

    def team_of(ref):
        if not ref:
            return None
        if ref.startswith(("W:", "L:")):
            e = out.get(ref[2:])
            if not e:
                return None
            h, a = e["score"]
            if h == a:
                win = e.get("winner")
                if win not in (e["home"], e["away"]):
                    return None
                lose = e["away"] if win == e["home"] else e["home"]
                return win if ref[0] == "W" else lose
            return (e["home"] if h > a else e["away"]) if ref[0] == "W" else (e["away"] if h > a else e["home"])
        if ":" in ref:
            rest = ref.split(":", 1)[1]
            gid = rest.rstrip("0123456789")
            pos = rest[len(gid):]
            if pos == "1":
                return winners.get(gid)
            if pos == "2":
                return runners.get(gid)
            return None
        return ref

    for f in sorted((f for f in t.fixtures if f.knockout), key=lambda f: f.day):
        raw = ties.get(f.id)
        if not isinstance(raw, dict) or not parse_score(raw.get("real_score")):
            continue
        home, away = team_of(f.home_ref), team_of(f.away_ref)
        if home and away:
            out[f.id] = entry(home, away, raw)
    return out


# ── playing ──────────────────────────────────────────────────────────────
def enabled(t):
    return bool((t.options or {}).get("reality")) and bool(t.components.get("reality"))


def real_entry(t, fixture):
    """The fixture's real entry, oriented to its home / away, or None when
    it is not a real match (yet): reality off, a user's match, or teams
    that never met."""
    if not enabled(t) or not fixture.ready:
        return None
    if any(t.teams[tid].human for tid in (fixture.home, fixture.away) if tid in t.teams):
        return None
    e = t.components["reality"].get(fixture.id)
    if not e:
        return None
    if (e["home"], e["away"]) == (fixture.home, fixture.away):
        return e
    if (e["home"], e["away"]) == (fixture.away, fixture.home):
        flip = dict(e, home=e["away"], away=e["home"], score=e["score"][::-1],
                    tries=e["tries"][::-1] if e["tries"] else None)
        return flip
    return None


def would_be_real(t, fixture):
    """A fixture reality had a result for, that will not get it (diverged)."""
    return enabled(t) and fixture.id in t.components["reality"] and real_entry(t, fixture) is None


def _norm(text):
    text = unicodedata.normalize("NFKD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z]+", " ", text).strip()


def find_player(t, team_id, ev):
    """The squad player an event names (pid, or a name), or None."""
    pid = str(ev.get("pid") or "")
    entry = t.teams.get(team_id)
    if not entry:
        return None
    if pid:
        for key in entry.squad:
            if key == pid or t.players[key].base.get("_source_pid") == pid:
                return key
    want = _norm(ev.get("player"))
    if not want:
        return None
    full, last = [], []
    for key in entry.squad:
        base = t.players[key].base
        names = {_norm(f"{base.get('first_name', '')} {base.get('last_name', '')}"),
                 _norm(base.get("display_name")), _norm(t.players[key].name)}
        if want in names:
            full.append(key)
        elif _norm(base.get("last_name")) == want.split(" ")[-1]:
            last.append(key)
    if len(full) == 1:
        return full[0]
    return last[0] if len(last) == 1 and not full else None


def decompose(points, tries=None):
    """(tries, conversions, penalties, drops) adding up to `points`: the
    real try count when known, else a usual shape for that score."""
    best, best_cost = None, None
    t_range = [tries] if tries is not None else range(points // 5 + 1)
    for T in t_range:
        rest = points - 5 * T
        if rest < 0:
            continue
        for C in range(T, -1, -1):
            k = rest - 2 * C
            if k < 0 or k % 3:
                continue
            K = k // 3
            # a usual match: ~70% of tries converted, a try for ~every 8 points
            cost = (abs(C - 0.7 * T) + (0 if tries is not None else abs(T - points / 8.0) * 1.5)
                    + max(0, K - 5) * 0.5)
            if best_cost is None or cost < best_cost:
                best, best_cost = (T, C, K, 0), cost
    if best is None and tries is not None:
        return decompose(points)                  # the try count can't make this score
    return best or (0, 0, 0, 0)


def _goal_kicker(t, team_id, lines):
    from .effects import effective_stats
    roles = (t.teams[team_id].selection or {}).get("roles") or {}
    on_pitch = [l.pid for l in lines if l.minutes > 0 and l.pid in t.players]
    k = roles.get("longGK") or roles.get("shortGK")
    if k in on_pitch:
        return k
    best = max(on_pitch, key=lambda pid: effective_stats(t, t.players[pid]).get("goal_kicking", 0), default=None)
    return best or (lines[0].pid if lines else None)


def _side_lines(t, side, points, tries, events, rng):
    """Rebuild one side's scoring and cards for the real score. Returns
    True when the real scorers were used."""
    for l in side.players:
        l.tries = l.conversions = l.conversions_attempted = l.penalties = 0
        l.penalties_attempted = l.drop_goals = l.yellow_cards = l.red_cards = 0
        l.injured = False
    side.penalty_tries = 0
    by_pid = {l.pid: l for l in side.players}

    def line(pid):
        if pid not in by_pid:
            by_pid[pid] = PlayerLine(pid=pid, started=False, minutes=20)
            side.players.append(by_pid[pid])
        return by_pid[pid]

    scoring = [(ev, find_player(t, side.team_id, ev)) for ev in events if ev.get("kind") in SCORING]
    real = bool(scoring) and all(pid for _ev, pid in scoring) and \
        sum(SCORING[ev["kind"]] for ev, _pid in scoring) == points
    if real:
        for ev, pid in scoring:
            l = line(pid)
            kind = ev["kind"]
            if kind == "try":
                l.tries += 1
            elif kind == "conversion":
                l.conversions += 1
                l.conversions_attempted += 1
            elif kind == "penalty":
                l.penalties += 1
                l.penalties_attempted += 1
            else:
                l.drop_goals += 1
    else:
        T, C, K, D = decompose(points, tries)
        playing = [l for l in side.players if l.minutes > 0] or side.players
        weights = [TRY_WEIGHT.get(t.players[l.pid].position, 1.0) * (1.0 if l.started else 0.4)
                   for l in playing]
        for _ in range(T):
            rng.choices(playing, weights)[0].tries += 1
        kicker = _goal_kicker(t, side.team_id, side.players)
        if kicker:
            k = line(kicker)
            k.conversions += C
            k.conversions_attempted += T
            k.penalties += K
            k.penalties_attempted += K + (1 if K and rng.random() < 0.4 else 0)
    for ev in events:
        if ev.get("kind") in ("yellow", "red"):
            pid = find_player(t, side.team_id, ev)
            if pid:
                if ev["kind"] == "yellow":
                    line(pid).yellow_cards += 1
                else:
                    line(pid).red_cards += 1
    return real


def real_result(t, fixture, e, rng):
    """The fixture's MatchResult with its real score (source "real"): the
    simulator's minutes and tackles, real scorers when the data has them
    (else plausible ones), real cards."""
    from . import simulator
    result = simulator.simulate(t, fixture, rng)
    h_pts, a_pts = e["score"]
    tries = e.get("tries") or [None, None]
    evs = e.get("events") or []
    real_h = _side_lines(t, result.home, h_pts, tries[0], [v for v in evs if str(v.get("team")) == fixture.home], rng)
    real_a = _side_lines(t, result.away, a_pts, tries[1], [v for v in evs if str(v.get("team")) == fixture.away], rng)
    out = MatchResult(home=result.home, away=result.away, source="real",
                      extra={"reality": {"scorers": "real" if real_h and real_a else "generated",
                                         "cancelled": bool(e.get("cancelled"))}})
    if out.home.points != h_pts or out.away.points != a_pts:      # never: decompose always adds up
        log.warning("reality: %s rebuilt as %s-%s instead of %s-%s", fixture.id,
                    out.home.points, out.away.points, h_pts, a_pts)
    if fixture.knockout and h_pts == a_pts:
        win = e.get("winner")
        out.winner = win if win in (fixture.home, fixture.away) else fixture.home
        out.decided_by = "tries"
    return out


# ── real events after the match ──────────────────────────────────────────
OUT_FOR_TOURNAMENT = 99


def matches_of(ev):
    """An event's matches missed: a number, or "tournament" (the rest of it)."""
    n = ev.get("matches")
    if str(n).strip().lower() in ("tournament", "rest"):
        return OUT_FOR_TOURNAMENT
    try:
        return max(0, int(n or 0))
    except (TypeError, ValueError):
        return 0

@on("match_completed", priority=60)
def _real_events(t, fixture, result, rng):
    if result.source != "real":
        return
    e = (t.components.get("reality") or {}).get(fixture.id)
    if not e:
        return
    for ev in e.get("events") or []:
        kind = ev.get("kind")
        if kind not in ("injury", "suspension"):
            continue
        if kind == "injury" and not t.options.get("injuries", True):
            continue
        if kind == "suspension" and not t.options.get("suspensions", True):
            continue
        team = str(ev.get("team") or "")
        pid = find_player(t, team, ev)
        if not pid:
            log.info("reality: %s %s (%s) not in the squad: skipped", kind, ev.get("player"), team)
            continue
        p = t.players[pid]
        n = matches_of(ev)
        name = t.team_name(team)
        if kind == "injury":
            what = str(ev.get("type") or "an injury")
            if n <= 0:
                continue
            add_condition(t, p, Condition(kind="injury", matches_left=n, data={"type": what, "real": True}))
            out = "is out of the tournament" if n >= OUT_FOR_TOURNAMENT else f"will miss {n} match{'es' if n != 1 else ''}"
            t.add_news("injury", f"{p.name} ({name}) {out} ({what})", [team], pid)
        else:
            why = str(ev.get("reason") or "suspension")
            if n <= 0:
                continue
            add_condition(t, p, Condition(kind="suspension", matches_left=n, data={"reason": why, "real": True}))
            t.add_news("suspension", f"{p.name} ({name}) banned for {n} match{'es' if n != 1 else ''} ({why})",
                       [team], pid)

