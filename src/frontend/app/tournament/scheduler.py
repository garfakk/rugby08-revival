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
    "home": "10001", "away": "1010", "stadium": "70"}, ...] — used only
    while each group's teams are exactly the ones those fixtures name (an
    edited or shuffled draw falls back to the generated rounds);
  * knockout tie as a dict: {"teams": [...], "date": ..., "stadium": ...}.
  Each distinct date becomes one matchday, in date order; the date and any
  "venue" text show in the fixture label. Unknown keys (e.g. "real_score")
  are ignored.
"""
from datetime import date as _date

from .model import Fixture, Group, Stage


def _short_date(iso):
    try:
        d = _date.fromisoformat(iso)
    except (TypeError, ValueError):
        return iso or ""
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}"


def _day_map(dates, start_day):
    return {d: start_day + i for i, d in enumerate(sorted(set(dates)))}


def _fixed_fixtures(spec, groups):
    """The spec's pinned fixtures if they cover exactly these groups' teams,
    else None."""
    fixtures = spec.get("fixtures") or []
    if not fixtures or not all(f.get("date") and f.get("group") for f in fixtures):
        return None
    named = {}
    for f in fixtures:
        named.setdefault(f["group"], set()).update((str(f["home"]), str(f["away"])))
    actual = {g.id: set(g.teams) for g in groups}
    return fixtures if named == actual else None


def round_robin(teams, legs=1) -> list:
    """Berger/circle-method rounds: [[(home, away), ...], ...]. An odd team
    count gets a bye each round (that team simply has no fixture). Home and
    away alternate as evenly as the method allows; a second leg mirrors the
    first with venues swapped."""
    teams = list(teams)
    if len(teams) < 2:
        return []
    if len(teams) % 2:
        teams.append(None)
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
            # Alternate the fixed team's venue; for the rest, alternate by
            # round parity so nobody hosts every week.
            if i == 0:
                pairs.append((a, b) if r % 2 == 0 else (b, a))
            else:
                pairs.append((a, b) if (r + i) % 2 else (b, a))
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


def schedule_stage(t, stage, start_day) -> int:
    """Append the stage's fixtures to t.fixtures from `start_day`; returns the
    next free day."""
    spec = stage.spec
    venue = spec.get("venue", t.template.get("venue", "home"))
    neutral = venue == "neutral"
    subtype = spec.get("match_subtype", "pool" if stage.kind == "round_robin" else "none")
    if stage.kind == "round_robin":
        fixed = _fixed_fixtures(spec, stage.groups)
        if fixed:
            days = _day_map([f["date"] for f in fixed], start_day)
            names = {g.id: g.name for g in stage.groups}
            for i, fx in enumerate(sorted(fixed, key=lambda f: (f["date"], f.get("time", "")))):
                day = days[fx["date"]]
                where = f" · {fx['venue']}" if fx.get("venue") else ""
                t.fixtures.append(Fixture(
                    id=f"{stage.id}-{fx['group']}-{i + 1}", stage_id=stage.id, day=day,
                    home=str(fx["home"]), away=str(fx["away"]), group=fx["group"],
                    round_id=f"d{day - start_day + 1}", round_name=_short_date(fx["date"]),
                    label=f"{names.get(fx['group'], fx['group'])} · {_short_date(fx['date'])}{where}",
                    neutral=neutral, stadium_id=str(fx.get("stadium") or ""),
                    match_subtype=subtype))
            return start_day + len(days)
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
                        round_name=f"Round {r + 1}", label=f"{g.name} · Round {r + 1}",
                        neutral=neutral, match_subtype=subtype))
        return last + 1
    # knockout: each round is a day — or, when every tie is dated, each date
    rounds = spec.get("rounds", [])
    ties = [tie for rnd in rounds for tie in rnd.get("ties", [])]
    dated = bool(ties) and all(isinstance(tie, dict) and tie.get("date") for tie in ties)
    days = _day_map([tie["date"] for tie in ties], start_day) if dated else {}
    day = start_day
    for rnd in rounds:
        rnd_neutral = rnd.get("venue", venue) == "neutral"
        for i, tie in enumerate(rnd.get("ties", [])):
            tie_id = tie.get("id") if isinstance(tie, dict) else f"{rnd['id']}{i + 1}"
            refs = tie.get("teams") if isinstance(tie, dict) else tie
            label = rnd.get("name", rnd["id"]) + (f" {i + 1}" if len(rnd.get("ties", [])) > 1 else "")
            if dated:
                label += f" · {_short_date(tie['date'])}" + (f" · {tie['venue']}" if tie.get("venue") else "")
            t.fixtures.append(Fixture(
                id=tie_id, stage_id=stage.id, day=days[tie["date"]] if dated else day,
                round_id=rnd["id"], round_name=rnd.get("name", rnd["id"]), label=label,
                home_ref=refs[0], away_ref=refs[1], knockout=True, neutral=rnd_neutral,
                stadium_id=str(tie.get("stadium") or "") if isinstance(tie, dict) else "",
                match_subtype=rnd.get("match_subtype", "none"),
                final=bool(rnd.get("final"))))
        day += 1
    return start_day + len(days) if dated else day


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
