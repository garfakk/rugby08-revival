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

from app import variants as V

from . import calendar, reality, reputation, scheduler, selection, simulator, standings, weather
from .events import bus
from .model import SCHEMA_VERSION, PlayerState, TeamEntry, Tournament

log = get_logger(__name__)


# ── creation ──────────────────────────────────────────────────────────────

def pick_season(seasons, wanted) -> str:
    """`wanted` if the team has it, else the closest one it does have."""
    return V.pick_season(seasons, wanted)


def _ids(value) -> list:
    """A variant field: one id or a list of them, blanks dropped."""
    values = value if isinstance(value, (list, tuple)) else [value]
    return [str(v) for v in values if v]


def variant_choices(template, team_id) -> list:
    """The variants a template asks of `team_id`, most specific first —
    for its squad and, independently, each of its kits; the first one the
    team (or the kit) has is used, else the default.

    A template's own id always comes first, so a squad or kit variant
    named after an edition (rwc_2023, six_nations_2024, lions_2025) is
    picked by that edition with nothing else to set; then its "variant"
    (one id or a list: "world_cup", the competition's squads of any
    edition). A "team_variants" entry for the team replaces the lot
    ("" = the default squad and kits)."""
    template = template or {}
    per_team = template.get("team_variants") or {}
    if str(team_id) in per_team:
        return _ids(per_team[str(team_id)])
    out = []
    for vid in _ids(template.get("id")) + _ids(template.get("variant")):
        if vid not in out:
            out.append(vid)
    return out


def team_variant(template, team_id) -> str:
    """The first variant the template asks of `team_id` ("" = none)."""
    choices = variant_choices(template, team_id)
    return choices[0] if choices else ""


def first_variant(choices, available) -> str:
    """The first of `choices` in `available`, else "" (the default)."""
    return next((v for v in choices if v in available), "")


def entry_variant(ds, template, team_id, season) -> str:
    """The squad variant `team_id` plays in `season`: the first of the
    template's choices the team has there, else "" (its default squad)."""
    return first_variant(variant_choices(template, team_id), ds.variants_of(team_id, season))


def kit_variant(template, team_id, kit) -> str:
    """The version of `kit` (a stored kit dict) the template dresses
    `team_id` in: the first of its choices the kit has, else the plain kit."""
    return first_variant(variant_choices(template, team_id), V.kit_variant_ids(kit))


def default_participants(template, season) -> dict:
    """{stage_id: {group_id: [team ids]}} from the template's participants
    for `season`, else its "default" entry."""
    parts = template.get("participants") or {}
    chosen = parts.get(str(season)) or parts.get("default") or {}
    return {sid: {gid: [str(t) for t in teams] for gid, teams in groups.items()}
            for sid, groups in chosen.items()}


def usable_squad(ds, team_id, season, variant="") -> list:
    # The players list as ds.team_season() would resolve it, read in place:
    # resolving deep-copies the whole season block, and the tournament
    # wizard asks this for every team and season.
    from app import variants as V
    info = ((ds.teams or {}).get(str(team_id)) or {}).get(str(season))
    if not isinstance(info, dict):
        return []
    over = V.overrides(info, variant if V.has_variant(info, variant) else V.DEFAULT)
    players = over["players"] if "players" in over else info.get("players", [])
    return [str(p) for p in players or [] if p and str(p) in ds.players
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
    team_names = {s.get("name") for seasons in ds.teams.values() for s in seasons.values()
                  if isinstance(s, dict)}
    controller = 1
    for tid in team_ids:
        seasons = ds.teams[tid]
        tseason = pick_season(seasons, str(season))
        variant = entry_variant(ds, template, tid, tseason)
        info = ds.team_season(tid, tseason, variant)
        squad = usable_squad(ds, tid, tseason, variant)
        human = tid in humans
        entry = TeamEntry(team_id=tid, season=tseason, variant=variant,
                          name=info.get("name", tid), human=human,
                          controller=controller if human else 0,
                          default_roles={k: str(v) for k, v in (info.get("roles") or {}).items()},
                          set_plays=dict(info.get("setPlays") or {}),
                          stadium_id=scheduler.home_ground(ds.stadiums, tid, info, team_names))
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
    reputation.assign(ds, t)

    day = 0
    for spec in template.get("stages", []):
        stage = scheduler.build_stage(spec, participants.get(spec["id"], {}))
        t.stages.append(stage)
        day = scheduler.schedule_stage(t, stage, day)
    if t.stages:
        t.stages[0].status = "active"
    scheduler.assign_stadiums(t, list(ds.stadiums))
    t.components["stadium_ids"] = list(ds.stadiums)
    weather.keep_stadiums(t, ds)
    calendar.assign_dates(t)

    for tid in t.teams:
        t.teams[tid].selection = selection.auto_select(t, tid)
    if t.options.get("reality"):
        # who really met in every fixture, and how it went (reality.py)
        t.components["reality"] = reality.real_schedule(t)
    simulator.field_par(t)
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
    real = reality.real_entry(t, fixture)
    if real:
        # Reality mode: two AI teams that really met get the real result
        result = reality.real_result(t, fixture, real, fixture_rng(t, fixture))
    else:
        result = simulator.simulate(t, fixture, fixture_rng(t, fixture))
        if reality.would_be_real(t, fixture):
            result.extra["reality"] = {"diverged": True}
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


def simulate_earlier(t) -> list:
    """Simulate today's AI fixtures that kick off on an earlier date than
    the humans' next match (a round's Saturday matches when the user plays
    on the Sunday). Returns them."""
    f = next_human_fixture(t)
    if not f or not f.date:
        return []
    done = []
    for g in list(t.fixtures_on(t.day)):
        if not g.played and g.ready and g.date and g.date < f.date and not is_human_fixture(t, g):
            simulate_fixture(t, g)
            done.append(g)
    return done


def simulate_until_human(t) -> list:
    """Simulate AI fixtures until a human fixture is due (or the end). That
    day's earlier kick-offs are left for simulate_earlier, when the human
    match is about to be played."""
    done = []
    while not t.finished:
        if next_human_fixture(t):
            break
        sims = simulate_day(t)
        done += sims
        if not sims and not next_human_fixture(t):
            # nothing simulated and nothing for the humans: stuck on an
            # unresolvable ref — should not happen with a valid template
            log.warning("tournament %s: day %s has nothing playable", t.id, t.day)
            break
    return done


# play for the title: rolls per step, and the form boost (rating points) of
# each step — natural results first, a bigger push only when they never win
TITLE_ROLLS = 20
TITLE_BOOSTS = (0.0, 1.5, 3.0, 5.0, 8.0, 12.0, 20.0, 35.0)


def is_title_match(t, fixture) -> bool:
    """The match that hands out the trophy: a final, or the decider of a
    competition with no final (tournament/trophy.py)."""
    from . import trophy
    return bool(fixture.final or trophy.is_decider(t, fixture))


def _wins(t, result, team_id) -> int:
    """0 a loss or a draw, 1 a win, 2 a win with every table point going."""
    if result.winner_id() != team_id:
        return 0
    own, opp = result.side(team_id), result.opponent(team_id)
    rules = t.template.get("points") or standings.DEFAULT_POINTS
    pts = standings.match_points(rules, own, opp)[0]
    best = rules.get("win", 4) + (1 if rules.get("try_bonus") else 0)
    return 2 if pts >= best else 1


def _simulate_for_the_title(t, fixture, team_id):
    """`fixture` simulated as usual, then rolled again (each roll seeded) until
    `team_id` wins it — with a try bonus where there is one — so the team
    reaches its title match. Natural rolls come first; only when none wins
    is the team's form pushed, step by step (TITLE_BOOSTS)."""
    if fixture.played or not fixture.ready:
        return None
    prepare_fixture(t, fixture)
    best = simulator.simulate(t, fixture, fixture_rng(t, fixture))
    grade = _wins(t, best, team_id)
    for step, boost in enumerate(TITLE_BOOSTS):
        if grade == 2 or (grade and step):
            break                   # a win: a bonus one is only tried for in its own step
        for i in range(TITLE_ROLLS):
            result = simulator.simulate(t, fixture, fixture_rng(t, fixture, f"title{step}:{i}"),
                                        boost=(team_id, boost) if boost else None)
            g = _wins(t, result, team_id)
            if g > grade:
                best, grade = result, g
            if grade == 2:
                break
    record_result(t, fixture, best)
    return best


def simulate_to_title_match(t, for_title=False) -> list:
    """Expert mode: every match, the users' included, until a user's title
    match is due (their final, or the deciding round of a competition with
    no final) — that one is left to play. `for_title`: a user's team wins
    each of its matches on the way (a match between two users' teams is
    simulated as it comes). Stops too when no user's team is left in it.
    Returns the fixtures simulated."""
    done = []
    guard = 0
    while not t.finished and guard < 10000:
        guard += 1
        humans = [tid for tid, e in t.teams.items() if e.human]
        if not any(not is_eliminated(t, h) for h in humans):
            break
        due = next_human_fixture(t)
        if due is not None and is_title_match(t, due):
            break
        day = t.day
        sims = []
        for f in list(t.fixtures_on(day)):
            if f.played or not f.ready:
                continue
            mine = [tid for tid in (f.home, f.away) if t.teams[tid].human]
            if mine and is_title_match(t, f):
                continue              # another user's title match on this day: theirs to play
            if for_title and len(mine) == 1:
                _simulate_for_the_title(t, f, mine[0])
            else:
                simulate_fixture(t, f)
            sims.append(f)
        done += sims
        if not sims:
            break                     # nothing playable today (a ref the template can't resolve)
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
