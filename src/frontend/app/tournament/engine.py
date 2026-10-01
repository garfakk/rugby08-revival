"""
tournament/engine.py — Creating a tournament and moving it forward.

The engine knows about fixtures, results, stages and the calendar, nothing
else: every consequence of a match (injuries, bans, fatigue, stats, news)
is an events.bus subscriber. It works on the Tournament model only and
never touches Qt or the game.
"""
import random
import uuid
from datetime import datetime

from shared.log import get_logger

from . import scheduler, selection, simulator, standings
from .events import bus
from .model import SCHEMA_VERSION, PlayerState, TeamEntry, Tournament

log = get_logger(__name__)


# ── creation ──────────────────────────────────────────────────────────────

def pick_season(seasons, wanted) -> str:
    """`wanted` if the team has it, else the closest one it does have."""
    if wanted in seasons:
        return wanted
    keys = sorted(seasons, key=lambda s: int(s) if str(s).isdigit() else 0)
    if not keys:
        return ""
    try:
        w = int(wanted)
        return min(keys, key=lambda s: (abs(int(s) - w), -int(s)))
    except (TypeError, ValueError):
        return keys[-1]


def default_participants(template, season) -> dict:
    """{stage_id: {group_id: [team ids]}} from the template's participants
    for `season`, else its "default" entry."""
    parts = template.get("participants") or {}
    chosen = parts.get(str(season)) or parts.get("default") or {}
    return {sid: {gid: [str(t) for t in teams] for gid, teams in groups.items()}
            for sid, groups in chosen.items()}


def usable_squad(ds, team_id, season) -> list:
    info = ds.teams.get(team_id, {}).get(season, {})
    return [str(p) for p in info.get("players", []) if p and str(p) in ds.players
            and "stats" in ds.players[str(p)]]


def create_tournament(ds, template, season, participants=None, humans=(), options=None,
                      seed=None, name=None, data_version="") -> Tournament:
    """A new Tournament, scheduled, with every team's first selection made.
    `participants` defaults to the template's; `humans` is the team ids the
    user(s) manage."""
    participants = participants or default_participants(template, season)
    seed = int(seed if seed is not None else random.randrange(1, 2 ** 31))
    now = datetime.now().isoformat(timespec="seconds")
    t = Tournament(
        id=f"{template['id']}-{uuid.uuid4().hex[:8]}", name=name or template.get("name", template["id"]),
        template_id=template["id"], season=str(season), seed=seed, template=template,
        options=dict(template.get("default_options") or {}, **(options or {})),
        created=now, updated=now, data_version=data_version, schema_version=SCHEMA_VERSION)

    team_ids = [tid for groups in participants.values() for teams in groups.values() for tid in teams]
    humans = [str(h) for h in humans]
    controller = 1
    for tid in team_ids:
        seasons = ds.teams[tid]
        tseason = pick_season(seasons, str(season))
        info = seasons[tseason]
        squad = usable_squad(ds, tid, tseason)
        human = tid in humans
        entry = TeamEntry(team_id=tid, season=tseason, name=info.get("name", tid), human=human,
                          controller=controller if human else 0,
                          default_roles={k: str(v) for k, v in (info.get("roles") or {}).items()},
                          set_plays=dict(info.get("setPlays") or {}),
                          stadium_id=str(info.get("primaryStadium") or ""))
        if human:
            controller += 1
        records = ds.get_players(squad, tseason)
        for pid in squad:
            record = records.get(int(pid))
            if record is None:
                continue
            key = pid if pid not in t.players else f"{pid}@{tid}"   # same man in two squads
            record = dict(record)
            record["_source_pid"] = pid
            t.players[key] = PlayerState(pid=key, team_id=tid,
                                         name=record.get("display_name") or record.get("last_name") or pid,
                                         base=record)
            entry.squad.append(key)
        entry.default_roles = {k: (v if v in entry.squad else "") for k, v in entry.default_roles.items()}
        t.teams[tid] = entry

    day = 0
    for spec in template.get("stages", []):
        stage = scheduler.build_stage(spec, participants.get(spec["id"], {}))
        t.stages.append(stage)
        day = scheduler.schedule_stage(t, stage, day)
    if t.stages:
        t.stages[0].status = "active"
    scheduler.assign_stadiums(t, list(ds.stadiums))
    t.components["stadium_ids"] = list(ds.stadiums)

    for tid in t.teams:
        t.teams[tid].selection = selection.auto_select(t, tid)
    bus.emit("tournament_created", t=t)
    return t


# ── refs ──────────────────────────────────────────────────────────────────

def resolve_ref(t, ref):
    """Team id a knockout ref points at, or None while it can't be known."""
    if not ref:
        return None
    if ref.startswith(("W:", "L:")):
        f = t.fixture(ref[2:])
        if not f or not f.result:
            return None
        return f.result.winner_id() if ref[0] == "W" else f.result.loser_id()
    if ":" not in ref:
        return ref if ref in t.teams else None
    sid, rest = ref.split(":", 1)
    stage = t.stage(sid)
    if not stage or stage.status != "done":
        return None
    if rest.startswith("P") and "#" in rest:            # P2#1: best runner-up
        pos, n = rest[1:].split("#")
        ranking = standings.cross_group_ranking(t, stage, int(pos))
        n = int(n)
        return ranking[n - 1].team_id if len(ranking) >= n else None
    gid, pos = rest.rstrip("0123456789"), rest[len(rest.rstrip("0123456789")):]
    group = stage.group(gid)
    if not group or not pos:
        return None
    tab = standings.group_table(t, stage, group)
    pos = int(pos)
    return tab[pos - 1].team_id if len(tab) >= pos else None


def resolve_refs(t) -> None:
    changed = False
    for f in t.fixtures:
        if f.played:
            continue
        if f.home_ref and not f.home:
            f.home = resolve_ref(t, f.home_ref)
            changed |= bool(f.home)
        if f.away_ref and not f.away:
            f.away = resolve_ref(t, f.away_ref)
            changed |= bool(f.away)
    if changed:
        scheduler.assign_stadiums(t, t.components.get("stadium_ids", []))


# ── playing ───────────────────────────────────────────────────────────────

def fixture_rng(t, fixture, purpose="sim") -> random.Random:
    return random.Random(f"{t.seed}:{fixture.id}:{purpose}")


def current_fixtures(t) -> list:
    """Unplayed fixtures on the current matchday."""
    return [f for f in t.fixtures_on(t.day) if not f.played]


def is_human_fixture(t, fixture) -> bool:
    return any(t.teams[tid].human for tid in (fixture.home, fixture.away) if tid in t.teams)


def prepare_fixture(t, fixture) -> dict:
    """Selections ready for kick-off. Returns {team_id: [(out, in)]} for
    human teams whose selection had to be repaired."""
    repairs = {}
    for tid in (fixture.home, fixture.away):
        changes = selection.prepare(t, tid, fixture)
        if changes:
            repairs[tid] = changes
    bus.emit("pre_match", t=t, fixture=fixture)
    return repairs


def simulate_fixture(t, fixture):
    """Prepare, simulate and record one fixture."""
    if fixture.played or not fixture.ready:
        return None
    prepare_fixture(t, fixture)
    result = simulator.simulate(t, fixture, fixture_rng(t, fixture))
    record_result(t, fixture, result)
    return result


def record_result(t, fixture, result) -> None:
    fixture.result = result
    t.updated = datetime.now().isoformat(timespec="seconds")
    bus.emit("match_completed", t=t, fixture=fixture, result=result,
             rng=fixture_rng(t, fixture, "post"))
    resolve_refs(t)
    _advance(t)


def _advance(t) -> None:
    while not t.finished and t.day <= t.last_day():
        todays = t.fixtures_on(t.day)
        if any(not f.played for f in todays):
            return
        bus.emit("day_completed", t=t, day=t.day)
        for stage in t.stages:
            if stage.status == "active" and all(f.played for f in t.fixtures if f.stage_id == stage.id):
                stage.status = "done"
                bus.emit("stage_completed", t=t, stage=stage)
                nxt = next((s for s in t.stages if s.status == "pending"), None)
                if nxt:
                    nxt.status = "active"
        resolve_refs(t)
        t.day += 1
    if not t.finished and t.day > t.last_day():
        t.champion = champion_of(t)
        bus.emit("tournament_completed", t=t)


def champion_of(t):
    finals = [f for f in t.fixtures if f.final and f.result]
    if finals:
        return finals[-1].result.winner_id()
    last = t.stages[-1] if t.stages else None
    if last and last.kind == "round_robin" and last.groups:
        tab = standings.group_table(t, last, last.groups[0])
        return tab[0].team_id if tab else None
    return None


def simulate_day(t, include_human=False) -> list:
    """Simulate today's fixtures (AI-only ones unless `include_human`).
    Returns the fixtures simulated."""
    done = []
    day = t.day
    for f in list(t.fixtures_on(day)):
        if f.played or not f.ready:
            continue
        if is_human_fixture(t, f) and not include_human:
            continue
        simulate_fixture(t, f)
        done.append(f)
    return done


def next_human_fixture(t):
    """The next unplayed fixture with a human team, once it is playable."""
    for f in t.fixtures:
        if not f.played and f.ready and f.day == t.day and is_human_fixture(t, f):
            return f
    return None


def simulate_until_human(t) -> list:
    """Simulate AI fixtures until a human fixture is due (or the end)."""
    done = []
    while not t.finished:
        f = next_human_fixture(t)
        if f:
            break
        sims = simulate_day(t)
        done += sims
        if not sims and not next_human_fixture(t):
            # nothing simulated and nothing for the humans: stuck on an
            # unresolvable ref — should not happen with a valid template
            log.warning("tournament %s: day %s has nothing playable", t.id, t.day)
            break
    return done


def simulate_to_end(t) -> None:
    guard = 0
    while not t.finished and guard < 10000:
        guard += 1
        if not simulate_day(t, include_human=True):
            break


def is_eliminated(t, team_id) -> bool:
    """True once the team has no fixture left and can't get one from a ref."""
    if t.finished:
        return team_id != t.champion
    for f in t.fixtures:
        if f.played:
            continue
        if f.involves(team_id):
            return False
        for ref, filled in ((f.home_ref, f.home), (f.away_ref, f.away)):
            if ref and not filled and _could_be(t, ref, team_id):
                return False
    return True


def _could_be(t, ref, team_id) -> bool:
    if ref.startswith(("W:", "L:")):
        src = t.fixture(ref[2:])
        if not src:
            return False
        if src.result:
            return resolve_ref(t, ref) == team_id
        if src.ready:
            return src.involves(team_id)
        return any(_could_be(t, r, team_id) for r in (src.home_ref, src.away_ref) if r)
    if ":" in ref:
        sid = ref.split(":", 1)[0]
        stage = t.stage(sid)
        if stage and stage.status != "done":
            return any(team_id in g.teams for g in stage.groups)
        return resolve_ref(t, ref) == team_id
    return ref == team_id
