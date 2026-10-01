"""
tournament/scheduler.py — Turns a template's stages into dated fixtures.

Days are global matchday indexes across the whole tournament: every group
plays its Nth round on the same day, and each knockout round gets the next
free day. Knockout fixtures carry refs that engine.resolve_refs fills in:
  "<stage>:<group><pos>"  e.g. "pools:A1"   (group winner of pool A)
  "<stage>:P<pos>#<n>"    e.g. "pools:P2#1" (best runner-up across groups)
  "W:<tie>" / "L:<tie>"   winner / loser of an earlier knockout tie
"""
from .model import Fixture, Group, Stage


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
    # knockout: each round is a day
    day = start_day
    rounds = spec.get("rounds", [])
    for rnd in rounds:
        rnd_neutral = rnd.get("venue", venue) == "neutral"
        for i, tie in enumerate(rnd.get("ties", [])):
            tie_id = tie.get("id") if isinstance(tie, dict) else f"{rnd['id']}{i + 1}"
            refs = tie.get("teams") if isinstance(tie, dict) else tie
            t.fixtures.append(Fixture(
                id=tie_id, stage_id=stage.id, day=day, round_id=rnd["id"],
                round_name=rnd.get("name", rnd["id"]),
                label=rnd.get("name", rnd["id"]) + (f" {i + 1}" if len(rnd.get("ties", [])) > 1 else ""),
                home_ref=refs[0], away_ref=refs[1], knockout=True, neutral=rnd_neutral,
                match_subtype=rnd.get("match_subtype", "none"),
                final=bool(rnd.get("final"))))
        day += 1
    return day


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
