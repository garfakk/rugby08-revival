"""
tournament/selection.py — Picking a matchday 22 and its roles.

AI teams get auto_select() before each match. A human team keeps its own
selection ("manual"); repair() swaps out anyone who has become unavailable
since, so a selection never sends an injured or banned player out.

register_selection_weight(name, fn(t, player, ctx) -> multiplier) lets a
feature bias the AI's picks without being worth a stat change (fatigue
rotation today; form or morale could use it later).
"""
from .effects import MatchContext, effective_stats, is_available, unavailable_reason
from .strength import (SLOT_POSITIONS, group_of, position_fit, slot_rating)

ROLE_KEYS = ("captain", "viceCaptain", "longGK", "shortGK", "longPunt", "shortPunt", "kickoff")

# Fill the scarce specialists first so a versatile player isn't spent on an
# easy slot. 0-based slot indexes.
_START_ORDER = [1, 0, 2, 8, 9, 3, 4, 7, 5, 6, 14, 11, 12, 10, 13]
_BENCH_ORDER = [15, 16, 17, 20, 18, 19, 21]
_UTILITY_SLOT = 21
_UTILITY_POSITIONS = ("fly_half", "centre", "fullback")

_weights = {}


def register_selection_weight(name, fn):
    _weights[name] = fn


def _score(t, player, team_id, slot, pos, fixture, weighted=True):
    ctx = MatchContext(fixture=fixture, team_id=team_id, position=pos, slot=slot + 1)
    value = slot_rating(effective_stats(t, player, ctx), pos, player.positions)
    if weighted:
        for fn in _weights.values():
            value *= fn(t, player, ctx)
    return value


def auto_select(t, team_id, fixture=None) -> dict:
    """Best available 22 for `team_id`, with roles. Never raises: a squad
    too thin to fill 22 from fit players dips into the unavailable ones (the
    game needs exactly 22), and says so in "problems"."""
    entry = t.teams[team_id]
    squad = [t.players[pid] for pid in entry.squad if pid in t.players]
    fit = [p for p in squad if is_available(t, p)]
    unfit = [p for p in squad if p not in fit]
    players = [None] * 22
    positions = list(SLOT_POSITIONS)
    problems = []
    used = set()

    def pick(slot, candidates_positions):
        best = None
        for pool, label in ((fit, None), (unfit, "unavailable")):
            for p in pool:
                if p.pid in used:
                    continue
                for pos in candidates_positions:
                    s = _score(t, p, team_id, slot, pos, fixture)
                    if best is None or s > best[0]:
                        best = (s, p, pos)
            if best:
                if label:
                    problems.append(f"{best[1].name} picked despite being {label}")
                return best
        return None

    for slot in _START_ORDER + _BENCH_ORDER:
        cands = _UTILITY_POSITIONS if slot == _UTILITY_SLOT else (SLOT_POSITIONS[slot],)
        best = pick(slot, cands)
        if best is None:
            problems.append(f"no player left for slot {slot + 1}")
            continue
        _s, p, pos = best
        players[slot] = p.pid
        positions[slot] = pos
        used.add(p.pid)

    players = [pid for pid in players if pid]
    positions = positions[:len(players)] if len(players) < 22 else positions
    sel = {"players": players, "positions": positions, "set_plays": dict(entry.set_plays),
           "manual": False}
    sel["roles"] = pick_roles(t, team_id, players)
    if problems:
        sel["problems"] = problems
    return sel


def pick_roles(t, team_id, players, current=None) -> dict:
    """Keep the team's own captain/kickers when they start, otherwise give
    the job to the best starter for it."""
    entry = t.teams[team_id]
    starters = [pid for pid in players[:15] if pid in t.players]
    wanted = dict(entry.default_roles)
    wanted.update({k: v for k, v in (current or {}).items() if v})

    def eff(pid):
        return effective_stats(t, t.players[pid])

    def best(key_fn, exclude=()):
        pool = [pid for pid in starters if pid not in exclude]
        return max(pool, key=key_fn) if pool else ""

    def leadership(pid):
        s, base = eff(pid), t.players[pid].base
        return s["temperament"] + s["discipline"] + (25 if str(base.get("ss_command", "")).strip() else 0)

    roles = {}
    roles["captain"] = wanted.get("captain") if wanted.get("captain") in starters else best(leadership)
    vc = wanted.get("viceCaptain")
    roles["viceCaptain"] = vc if vc in starters and vc != roles["captain"] else best(leadership, (roles["captain"],))
    goal = best(lambda pid: eff(pid)["goal_kicking"])
    punt = best(lambda pid: eff(pid)["kicking"] + eff(pid)["kicking_power"] * 0.5)
    for key, fallback in (("longGK", goal), ("shortGK", goal), ("longPunt", punt),
                          ("shortPunt", punt)):
        roles[key] = wanted.get(key) if wanted.get(key) in starters else fallback
    fly_half = players[9] if len(players) > 9 else ""
    roles["kickoff"] = wanted.get("kickoff") if wanted.get("kickoff") in starters else (fly_half or punt)
    return roles


def validate(t, team_id, sel) -> tuple:
    """(errors, warnings). Errors make the selection unplayable."""
    entry = t.teams[team_id]
    pids = sel.get("players", [])
    positions = sel.get("positions") or SLOT_POSITIONS
    errors, warnings = [], []
    if len(pids) != 22:
        errors.append(f"{len(pids)} players selected, 22 needed")
    if len(set(pids)) != len(pids):
        errors.append("a player is selected twice")
    for slot, pid in enumerate(pids):
        p = t.players.get(pid)
        if p is None or pid not in entry.squad:
            errors.append(f"slot {slot + 1}: not in the squad")
            continue
        reason = unavailable_reason(t, p)
        if reason:
            errors.append(f"{p.name}: {reason}")
        pos = positions[slot] if slot < len(positions) else SLOT_POSITIONS[slot]
        if position_fit(p.positions, pos) < 0.9:
            warnings.append(f"{p.name} is out of position at {pos.replace('_', ' ')}")
    bench_groups = {group_of(positions[i]) for i in range(15, min(22, len(positions)))
                    if i < len(pids) and pids[i] in t.players
                    and group_of(t.players[pids[i]].position) in ("prop", "hooker")}
    if not bench_groups:
        warnings.append("no front-row cover on the bench")
    return errors, warnings


def repair(t, team_id, fixture=None) -> list:
    """Replace selected players who are no longer available with the best
    available cover for their slot. Returns [(out_pid, in_pid)]."""
    entry = t.teams[team_id]
    sel = entry.selection
    pids = list(sel.get("players", []))
    positions = list(sel.get("positions") or SLOT_POSITIONS)
    changes = []
    used = set(pids)
    for slot, pid in enumerate(pids):
        p = t.players.get(pid)
        if p and is_available(t, p):
            continue
        pos = positions[slot] if slot < len(positions) else SLOT_POSITIONS[slot]
        cands = [t.players[q] for q in entry.squad
                 if q in t.players and q not in used and is_available(t, t.players[q])]
        if not cands:
            continue
        sub = max(cands, key=lambda c: _score(t, c, team_id, slot, pos, fixture, weighted=False))
        pids[slot] = sub.pid
        used.add(sub.pid)
        changes.append((pid, sub.pid))
    if changes:
        sel["players"] = pids
        sel["roles"] = pick_roles(t, team_id, pids, sel.get("roles"))
    return changes


def prepare(t, team_id, fixture=None) -> list:
    """Make the team's selection ready for `fixture`: AI teams re-pick,
    human teams keep theirs (repaired, or auto-picked if they never chose).
    Returns the repair changes for a human team."""
    entry = t.teams[team_id]
    if entry.human and entry.selection.get("manual") and entry.selection.get("players"):
        return repair(t, team_id, fixture)
    entry.selection = auto_select(t, team_id, fixture)
    return []
