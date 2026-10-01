"""
tournament/bridge.py — Between a tournament fixture and the real game.

to_match_config()  fixture + both selections -> app.state.MatchConfig, fed
                   to build_match_data like any quick match. Players carry
                   their *effective* ratings (effects.effective_record), so
                   fatigue and future form/morale reach the game's roster.
from_game_result() R08_handler.read_match_result() dict -> MatchResult.

The game reports per-player lines by roster id (gsv.players_roster_id:
the fixed ids the 22 slots of each team are written under), team_A = home.
"""
from backend import game_specific_variables as gsv
from shared.log import get_logger

from app.state import MatchConfig

from .effects import MatchContext, effective_record, effective_stats
from .model import MatchResult, PlayerLine, SideResult
from .simulator import settle_knockout_draw
from .strength import SLOT_POSITIONS

log = get_logger(__name__)

# More "injured" players than this in one team means the byte isn't the
# flag we think it is for this build: ignore it rather than gut the squad.
MAX_PLAUSIBLE_INJURIES = 4


def _source_pid(t, pid) -> int:
    p = t.players[pid]
    return int(p.base.get("_source_pid", pid))


def to_match_config(ds, t, fixture) -> MatchConfig:
    cfg = MatchConfig()
    humans = []
    for side, tid, slot in (("home", fixture.home, cfg.home), ("away", fixture.away, cfg.away)):
        entry = t.teams[tid]
        slot.team_id, slot.season = tid, entry.season
        info = ds.teams.get(tid, {}).get(entry.season, {})
        kits = list(info.get("kits", {}))
        slot.kit_index = 0 if side == "home" or len(kits) < 2 else 1
        sel = entry.selection
        positions = sel.get("positions") or SLOT_POSITIONS
        ids, players = [], {}
        for i, pid in enumerate(sel.get("players", [])[:22]):
            if pid not in t.players:
                continue
            pos = positions[i] if i < len(positions) else SLOT_POSITIONS[i]
            ctx = MatchContext(fixture=fixture, team_id=tid, position=pos, slot=i + 1)
            src = _source_pid(t, pid)
            ids.append(src)
            players[src] = effective_record(t, t.players[pid], ctx)
        roles = {k: _source_pid(t, v) for k, v in (sel.get("roles") or {}).items() if v in t.players}
        slot.lineup = {"players_id": ids, "roles": roles, "set_plays": dict(sel.get("set_plays") or {})}
        slot.players = players
        if entry.human:
            humans.append(side)

    sid = str(fixture.stadium_id or "")
    if sid not in ds.stadiums:
        sid = next(iter(ds.stadiums), "")
    if sid:
        info = ds.stadiums[sid]
        cfg.stadium = {"stadium_id": int(info.get("game_id", sid)), "data": info}
        envs = info.get("environments") or []
        if envs:
            cfg.environment = envs[0] if isinstance(envs, list) else str(envs)

    opts = t.options
    cfg.difficulty = opts.get("difficulty", "pro")
    cfg.halftime_length = opts.get("halftime_length", "5m")
    tpl = t.template
    cfg.match_type = tpl.get("match_type", "exhibition") if tpl.get("match_type") in gsv.match_type else "exhibition"
    cfg.match_subtype = fixture.match_subtype if fixture.match_subtype in gsv.match_subtype else "none"
    if fixture.final and tpl.get("trophy_lift", True):
        cfg.trophy_lift = "on"
    branding = tpl.get("branding")
    if branding and branding in ds.tournaments:
        cfg.tournament_logo_choice = branding
        cfg.stadium_graphics_choice = branding
        if any(s.get("pitch_logo") for s in ds.tournaments[branding].values()):
            cfg.pitch_logo_choice = branding

    if len(humans) == 2:
        cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"},
                           2: {"kind": "pad", "label": "PAD 2", "zone": "away"}}
    else:
        cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": humans[0] if humans else "home"}}
    return cfg


def from_game_result(t, fixture, result: dict, rng) -> MatchResult:
    """The game's result dict -> MatchResult. Players are matched to the
    selection by roster id; bench players with nothing on the sheet are
    assumed not to have come on (the game's substitutions aren't read yet),
    starters to have played 80."""
    sides = []
    raw_injury = {}
    for key, tid in (("team_A", fixture.home), ("team_B", fixture.away)):
        sel = t.teams[tid].selection.get("players", [])
        roster_ids = gsv.players_roster_id.get(key, [])
        lines = []
        raw = (result or {}).get(key, {}).get("players", [])
        for i, row in enumerate(raw):
            slot = roster_ids.index(row.get("id")) if row.get("id") in roster_ids else i
            if slot >= len(sel):
                continue
            started = slot < 15
            did = any(row.get(k) for k in ("tries", "conversions_attempted", "penalties_attempted",
                                           "drop_goals", "tackles", "yellow_cards", "red_cards"))
            lines.append(PlayerLine(
                pid=sel[slot], started=started, minutes=80 if started else (20 if did else 0),
                tries=row.get("tries", 0), conversions=row.get("conversions_scored", 0),
                conversions_attempted=row.get("conversions_attempted", 0),
                penalties=row.get("penalties_scored", 0),
                penalties_attempted=row.get("penalties_attempted", 0),
                drop_goals=row.get("drop_goals", 0), yellow_cards=row.get("yellow_cards", 0),
                red_cards=row.get("red_cards", 0), tackles=row.get("tackles", 0),
                injured=bool(row.get("injury"))))
            raw_injury[sel[slot]] = row.get("injury", 0)
        flagged = [l for l in lines if l.injured]
        if len(flagged) > MAX_PLAUSIBLE_INJURIES:
            log.warning("tournament: %d players flagged injured for %s — ignoring the injury byte",
                        len(flagged), tid)
            for l in flagged:
                l.injured = False
        sides.append(SideResult(team_id=tid, players=lines,
                                stats=dict((result or {}).get(key, {}).get("stats", {}))))
    mr = MatchResult(home=sides[0], away=sides[1], source="game",
                     extra={"raw_injury": raw_injury})
    if fixture.knockout and mr.home.points == mr.away.points:
        def kickers(tid):
            sel = t.teams[tid].selection.get("players", [])[:15]
            return sorted((effective_stats(t, t.players[p])["goal_kicking"] for p in sel if p in t.players),
                          reverse=True)[:5]
        settle_knockout_draw(t, mr, rng, kickers(fixture.home), kickers(fixture.away))
    return mr


def forfeit_result(t, fixture, losing_team) -> MatchResult:
    """Walkover: the template's forfeit score (default 25-0 / 5 tries,
    the usual "bonus point win" award)."""
    winner = fixture.away if losing_team == fixture.home else fixture.home
    tries = int(t.template.get("forfeit_tries", 5))
    sides = {}
    for tid in (fixture.home, fixture.away):
        sel = t.teams[tid].selection.get("players", [])
        lines = [PlayerLine(pid=p, started=i < 15, minutes=0) for i, p in enumerate(sel)]
        side = SideResult(team_id=tid, players=lines)
        if tid == winner:
            # Awarded tries belong to nobody: a scorer-less line (pid "")
            # that every subscriber skips since it isn't a squad member.
            side.players.append(PlayerLine(pid="", started=False, minutes=0, tries=tries))
        sides[tid] = side
    return MatchResult(home=sides[fixture.home], away=sides[fixture.away], source="forfeit",
                       winner=winner, decided_by="forfeit")
