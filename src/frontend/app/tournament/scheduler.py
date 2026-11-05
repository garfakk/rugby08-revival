"""
tournament/scheduler.py — Turns a template's stages into dated fixtures.

Days are global matchday indexes across the whole tournament: every group
plays its Nth round on the same day, and each knockout round gets the next
free day. Knockout fixtures carry refs that engine.resolve_refs fills in:
  "<stage>:<group><pos>"  e.g. "pools:A1"   (group winner of pool A)
  "<stage>:P<pos>#<n>"    e.g. "pools:P2#1" (best runner-up across groups)
  "W:<tie>" / "L:<tie>"   winner / loser of an earlier knockout tie

A template can pin a real calendar instead (a historical tournament):
  * round-robin stage: "fixtures": [{"date": "2023-09-08", "group": "A",
    "home": "10001", "away": "1010", "stadium": "70"}, ...] — used while
    each group's teams are the ones those fixtures name, give or take
    MAX_STAND_INS teams put in for others or left out (missing from the
    data: their fixtures are dropped); a draw changed further falls back
    to the generated rounds, and the knockout dates are then dropped too;
  * knockout tie as a dict: {"teams": [...], "date": ..., "stadium": ...}.
  A pinned round-robin's matchdays are its rounds, numbered per group so
  each holds a full set of matches (_fixed_rounds); dated knockout ties
  become matchdays in date order, a weekend's dates sharing one. Unknown keys (e.g. "venue", "real_score") are
  reference only.
"""
from datetime import date as _date

from .model import Fixture, Group, Stage

MAX_STAND_INS = 2       # teams per group a historical draw's fixtures can be handed to
ROUND_SPAN = 2          # days: a weekend's dates are one matchday


def _day_map(dates, start_day, teams_on=None, round_of=None):
    """{date: matchday}. Dates up to ROUND_SPAN days apart share a matchday
    (a Six Nations round's Saturday and Sunday) unless a team would play
    twice in it (`teams_on` = {date: set of team ids}) or they belong to
    different knockout rounds (`round_of` = {date: round id})."""
    days, day, first, seen = {}, start_day - 1, None, set()
    for d in sorted(set(dates)):
        teams = (teams_on or {}).get(d, set())
        try:
            near = first is not None and (_date.fromisoformat(d) - _date.fromisoformat(first)).days <= ROUND_SPAN
        except (TypeError, ValueError):
            near = False
        if not near or teams & seen or (round_of and round_of.get(d) != round_of.get(first)):
            day, first, seen = day + 1, d, set()
        days[d] = day
        seen |= teams
    return days


SEARCH_LIMIT = 200000   # nodes per group before settling for the chronological rounds


def _chronological_rounds(fixtures) -> list:
    """Each fixture (in date order) in the round after its two teams'
    previous ones: no team plays out of calendar order, but a bye the
    calendar puts late can leave a short round and an extra one."""
    last, rounds = {}, []
    for f in fixtures:
        home, away = str(f["home"]), str(f["away"])
        rnd = max(last.get(home, 0), last.get(away, 0)) + 1
        last[home] = last[away] = rnd
        rounds.append(rnd)
    return rounds


def _balanced_rounds(fixtures):
    """Rounds for one group's fixtures (in date order) that are all full
    (teams // 2 matches, a team once per round), with as few pairs of a
    team's matches played against calendar order as possible — 0 for a
    tidy calendar; a World Cup pool that hands one team two byes, or a
    postponed match, costs one or two. None when no such split exists."""
    teams = {t for f in fixtures for t in (str(f["home"]), str(f["away"]))}
    cap = len(teams) // 2
    if not cap or len(fixtures) % cap:
        return None
    n_rounds = len(fixtures) // cap
    load, busy = [0] * (n_rounds + 1), [set() for _ in range(n_rounds + 1)]
    played = {t: [] for t in teams}           # rounds given to a team so far
    out, best, nodes = [0] * len(fixtures), [None, float("inf")], [0]

    def go(i, cost):
        nodes[0] += 1
        if cost >= best[1] or nodes[0] > SEARCH_LIMIT:
            return
        if i == len(fixtures):
            best[:] = [out[:], cost]
            return
        home, away = str(fixtures[i]["home"]), str(fixtures[i]["away"])
        # earliest round after both teams' last first, so the first answer is the tidy one
        start = max(max(played[home], default=0), max(played[away], default=0)) + 1
        for r in list(range(start, n_rounds + 1)) + list(range(min(start, n_rounds + 1) - 1, 0, -1)):
            if load[r] >= cap or home in busy[r] or away in busy[r]:
                continue
            extra = sum(1 for t in (home, away) for p in played[t] if p > r)
            load[r] += 1
            busy[r] |= {home, away}
            played[home].append(r)
            played[away].append(r)
            out[i] = r
            go(i + 1, cost + extra)
            played[home].pop()
            played[away].pop()
            busy[r] -= {home, away}
            load[r] -= 1

    go(0, 0)
    return best[0]


def _fixed_rounds(fixtures) -> list:
    """Round number (1-based) of each pinned fixture, given in date order.
    Rounds are numbered per group so every pool's rounds hold the same match
    count even when the pools' dates are staggered (a World Cup: a team's
    gaps run 4-8 days and the pools never share a weekend), which
    clustering dates by weekend cannot follow."""
    rounds = [0] * len(fixtures)
    by_group = {}
    for i, f in enumerate(fixtures):
        by_group.setdefault(f.get("group"), []).append(i)
    for idx in by_group.values():
        group = [fixtures[i] for i in idx]
        for i, r in zip(idx, _balanced_rounds(group) or _chronological_rounds(group)):
            rounds[i] = r
    return rounds


def _fixed_fixtures(spec, groups):
    """The spec's pinned fixtures if they cover these groups' teams, else
    None. A group may differ from the fixtures by at most MAX_STAND_INS
    teams: a team put in for one the fixtures name takes over its fixtures,
    and a team left out (missing from the data) has its fixtures dropped,
    so the real calendar is kept."""
    fixtures = spec.get("fixtures") or []
    if not fixtures or not all(f.get("date") and f.get("group") for f in fixtures):
        return None
    named = {}
    for f in fixtures:
        named.setdefault(f["group"], []).extend(t for t in (str(f["home"]), str(f["away"]))
                                                if t not in named.get(f["group"], []))
    actual = {g.id: list(g.teams) for g in groups}
    if set(named) != set(actual):
        return None
    swap, dropped = {}, set()
    for gid, teams in actual.items():
        gone = [t for t in named[gid] if t not in teams]
        new = [t for t in teams if t not in named[gid]]
        if len(new) > len(gone) or len(gone) > MAX_STAND_INS:
            return None
        swap.update({(gid, old): stand_in for old, stand_in in zip(gone, new)})
        dropped.update(gone[len(new):])
    if not swap and not dropped:
        return fixtures
    return [dict(f, home=swap.get((f["group"], str(f["home"])), str(f["home"])),
                 away=swap.get((f["group"], str(f["away"])), str(f["away"])))
            for f in fixtures if str(f["home"]) not in dropped and str(f["away"]) not in dropped]


def round_robin(teams, legs=1) -> list:
    """Berger/circle-method rounds: [[(home, away), ...], ...]. An odd team
    count gets a bye each round (that team simply has no fixture). Home and
    away alternate as evenly as the method allows; a second leg mirrors the
    first with venues swapped."""
    teams = list(teams)
    if len(teams) < 2:
        return []
    if len(teams) % 2:
        teams.insert(0, None)       # the bye is the fixed slot: every team rotates
    n = len(teams)
    fixed, rotating = teams[0], teams[1:]
    rounds = []
    for r in range(n - 1):
        line = [fixed] + rotating
        pairs = []
        for i in range(n // 2):
            a, b = line[i], line[n - 1 - i]
            if a is None or b is None:
                continue
            # Alternate the fixed team's venue; for the rest, the venue
            # follows the pair's slot: a team moves one slot a round, so it
            # alternates home and away and hosts half its games.
            if i == 0:
                pairs.append((a, b) if r % 2 == 0 else (b, a))
            else:
                pairs.append((a, b) if i % 2 else (b, a))
        rounds.append(pairs)
        rotating = rotating[-1:] + rotating[:-1]
    if legs >= 2:
        rounds += [[(b, a) for a, b in rnd] for rnd in rounds]
    return rounds


def build_stage(spec, participants) -> Stage:
    """Stage object from a template stage spec. `participants` for a
    round-robin stage: {group_id: [team ids]}."""
    stage = Stage(id=spec["id"], name=spec.get("name", spec["id"]),
                  kind=spec.get("kind", "round_robin"), spec=spec)
    if stage.kind == "round_robin":
        names = spec.get("group_names") or {}
        for gid, teams in participants.items():
            label = names.get(gid) if isinstance(names, dict) else None
            stage.groups.append(Group(id=gid, name=label or f"Pool {gid}", teams=list(teams)))
    return stage


def _label(group_name, round_name, groups) -> str:
    """"Pool A · Round 2"; just "Round 2" in a stage that is one league."""
    return f"{group_name} · {round_name}" if groups > 1 else round_name


def schedule_stage(t, stage, start_day) -> int:
    """Append the stage's fixtures to t.fixtures from `start_day`; returns the
    next free day."""
    spec = stage.spec
    venue = spec.get("venue", t.template.get("venue", "home"))
    neutral = venue == "neutral"
    subtype = spec.get("match_subtype", "pool" if stage.kind == "round_robin" else "none")
    if stage.kind == "round_robin":
        fixed = _fixed_fixtures(spec, stage.groups)
        if spec.get("fixtures") and not fixed:
            # a historical draw changed past what its calendar can follow:
            # the later stages' real dates no longer fit either
            t.components["calendar_free"] = True
        if fixed:
            ordered = sorted(fixed, key=lambda f: (f["date"], f.get("time", "")))
            rounds = _fixed_rounds(ordered)
            names = {g.id: g.name for g in stage.groups}
            for i, (fx, rnd) in enumerate(zip(ordered, rounds)):
                day = start_day + rnd - 1
                t.fixtures.append(Fixture(
                    id=f"{stage.id}-{fx['group']}-{i + 1}", stage_id=stage.id, day=day,
                    home=str(fx["home"]), away=str(fx["away"]), group=fx["group"],
                    round_id=f"d{day - start_day + 1}", round_name=f"Round {day - start_day + 1}",
                    label=_label(names.get(fx['group'], fx['group']), f"Round {day - start_day + 1}",
                                 len(stage.groups)),
                    neutral=neutral, stadium_id=str(fx.get("stadium") or ""),
                    match_subtype=subtype, date=str(fx["date"])))
            return start_day + max(rounds, default=0)
        legs = int(spec.get("legs", 1))
        last = start_day - 1
        for g in stage.groups:
            for r, pairs in enumerate(round_robin(g.teams, legs)):
                day = start_day + r
                last = max(last, day)
                for i, (home, away) in enumerate(pairs):
                    t.fixtures.append(Fixture(
                        id=f"{stage.id}-{g.id}-r{r + 1}-{i + 1}", stage_id=stage.id, day=day,
                        home=home, away=away, group=g.id, round_id=f"r{r + 1}",
                        round_name=f"Round {r + 1}", label=_label(g.name, f"Round {r + 1}", len(stage.groups)),
                        neutral=neutral, match_subtype=subtype))
        return last + 1
    # knockout: each round is a day — or, when every tie is dated, each date
    rounds = spec.get("rounds", [])
    ties = [tie for rnd in rounds for tie in rnd.get("ties", [])]
    dated = (bool(ties) and all(isinstance(tie, dict) and tie.get("date") for tie in ties)
             and not t.components.get("calendar_free"))
    days = {}
    if dated:
        # a round's ties share a matchday; two rounds never do
        round_of = {tie["date"]: rnd["id"] for rnd in rounds for tie in rnd.get("ties", [])}
        days = _day_map([tie["date"] for tie in ties], start_day, round_of=round_of)
    day = start_day
    for rnd in rounds:
        rnd_neutral = rnd.get("venue", venue) == "neutral"
        for i, tie in enumerate(rnd.get("ties", [])):
            tie_id = tie.get("id") if isinstance(tie, dict) else f"{rnd['id']}{i + 1}"
            refs = tie.get("teams") if isinstance(tie, dict) else tie
            label = rnd.get("name", rnd["id"]) + (f" {i + 1}" if len(rnd.get("ties", [])) > 1 else "")
            t.fixtures.append(Fixture(
                id=tie_id, stage_id=stage.id, day=days[tie["date"]] if dated else day,
                round_id=rnd["id"], round_name=rnd.get("name", rnd["id"]), label=label,
                home_ref=refs[0], away_ref=refs[1], knockout=True, neutral=rnd_neutral,
                stadium_id=str(tie.get("stadium") or "") if isinstance(tie, dict) else "",
                match_subtype=rnd.get("match_subtype", "none"),
                final=bool(rnd.get("final")),
                date=str(tie.get("date") or "") if dated else ""))
        day += 1
    return max(days.values()) + 1 if dated else day


# A nation's usual ground when its team data names none (by stadium name).
NATIONAL_GROUNDS = {
    "england": "twickenham", "scotland": "murrayfield", "wales": "millennium stadium",
    "ireland": "lansdowne road", "france": "stade de france", "italy": "rome",
    "georgia": "tblissi", "argentina": "buenos aires", "new zealand": "auckland",
    "south africa": "johannesburg", "australia": "australia stadium", "fiji": "suva",
    "canada": "vancouver", "usa": "san francisco",
}
# Where a club competition's clubs play, for clubs without a ground.
CATEGORY_COUNTRY = {"top 14": "france", "pro d2": "france", "premiership": "england"}


def home_ground(stadiums, team_id, info, others=()) -> str:
    """The stadium id a team plays its home games at: its data's
    "primaryStadium", else its nation's usual ground, else a ground named
    after it, else one in its country that isn't named after one of
    `others` (other teams' names), spread over the clubs by team id.
    "" when none fits (the template's venues are used then)."""
    primary = str(info.get("primaryStadium") or "")
    if primary in stadiums:
        return primary
    name = str(info.get("name") or "").lower()
    by_name = {sid: str(s.get("name", "")).lower() for sid, s in stadiums.items()}
    wanted = NATIONAL_GROUNDS.get(name)
    for sid, sname in by_name.items():
        if wanted and sname == wanted:
            return sid
    for sid, sname in by_name.items():
        if name and len(name) > 3 and (name in sname or sname in name):
            return sid
    country = CATEGORY_COUNTRY.get(str(info.get("category") or "").lower(), name)
    local = sorted(sid for sid, st in stadiums.items() if str(st.get("country", "")).lower() == country)
    if country == name and local:     # a nation: its biggest ground (most lighting setups)
        return max(local, key=lambda sid: len(stadiums[sid].get("environments") or []))
    names = [str(o).lower() for o in others if o and len(str(o)) > 3 and str(o).lower() != name]
    free = [sid for sid in local if not any(o in by_name[sid] or by_name[sid] in o for o in names)]
    pool = free or local
    return pool[sum(map(ord, str(team_id))) % len(pool)] if pool else ""


def assign_stadiums(t, stadium_ids) -> None:
    """Home ties at the host's stadium; neutral ones cycle the template's
    venue list (or every known stadium). Knockout fixtures get theirs when
    their teams resolve (engine.resolve_refs)."""
    venues = list(t.template.get("venues") or stadium_ids or [])
    i = 0
    for f in t.fixtures:
        if f.stadium_id:
            continue
        if f.neutral or not f.home:
            if f.neutral and venues:
                f.stadium_id = str(venues[i % len(venues)])
                i += 1
            continue
        entry = t.teams.get(f.home)
        f.stadium_id = (entry.stadium_id if entry and entry.stadium_id
                        else (str(venues[i % len(venues)]) if venues else ""))
