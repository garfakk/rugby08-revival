"""
tournament/simulator.py — Plays a fixture without the game.

A minute-block model: eight 10-minute blocks. Each block:
  * both sides' unit ratings are taken from the 15 actually on the pitch
    (effective stats, worn down by minutes played vs stamina; sin-binned
    and sent-off players missing),
  * territory is split from scrum/lineout/breakdown/kicking,
  * each side gets a Poisson number of scoring chances from its share,
  * a chance becomes a try (attack vs defence), else maybe a penalty shot
    (opponent discipline), else maybe a drop goal,
  * kicks succeed on the kicker's goal_kicking,
  * cards (discipline/aggression) and injuries (fitness, fatigue) can
    happen; injured players come off for the best bench cover,
  * tactical substitutions around 50-70 minutes.

Each side also has a hidden "day form" draw, and the host gets a small
edge, so upsets happen at a plausible rate. Everything uses the `rng`
passed in (seeded per fixture by the engine), so a tournament replays
identically from its seed.

The constants below are calibrated with tools/tournament_sim_calibrate.py.
"""
import math

from .effects import MatchContext, component, effective_stats
from .model import MatchResult, PlayerLine, SideResult
from .strength import SLOT_POSITIONS, group_of, position_fit, unit_ratings

BLOCKS = 8
BLOCK_MINUTES = 10
CHANCES_PER_BLOCK = 1.35      # per side at an even territory split
TRY_BIAS = -0.80              # logit of P(try | chance) for evenly matched sides
ATTACK_SCALE = 7.0            # rating gap that moves that logit by 1
TERRITORY_SCALE = 8.0
PENALTY_SHOT_BASE = 0.36
DISCIPLINE_PAR = 96.0          # team discipline unit at which base rates apply
DISCIPLINE_SCALE = 8.0
DROP_GOAL_BASE = 0.025
YELLOW_BASE = 0.06            # per side per block
RED_BASE = 0.004
INJURY_BASE = 0.006           # per player per block
HOME_ADVANTAGE = 2.0          # rating points
DAY_FORM_SIGMA = 1.5          # rating points, × the "sim_variance" option


def logistic(x):
    return 1.0 / (1.0 + math.exp(-x))


def _poisson(rng, lam):
    # Knuth; lam is small here
    L, k, p = math.exp(-lam), 0, 1.0
    while True:
        p *= rng.random()
        if p <= L:
            return k
        k += 1


def discipline_factor(unit, lo, hi):
    """Multiplier on penalties/cards: 1 at DISCIPLINE_PAR, more below it.
    The data's discipline ratings bunch up in the high 90s, hence the
    tight scale."""
    return max(lo, min(hi, 1 + (DISCIPLINE_PAR - unit) / DISCIPLINE_SCALE))


def goal_probability(goal_kicking, kind="penalty"):
    p = 0.35 + 0.6 * (goal_kicking - 40) / 60.0
    p += 0.03 if kind == "penalty" else (-0.03 if kind == "conversion" else -0.25)
    return max(0.2, min(0.93, p))


class _Player:
    __slots__ = ("pid", "pos", "positions", "stats", "fit", "on_at", "off_at", "binned_until",
                 "sent_off", "fatigue")

    def __init__(self, pid, pos, positions, stats, fatigue):
        self.pid, self.pos, self.positions, self.stats = pid, pos, positions, stats
        self.fit = position_fit(positions, pos)
        self.on_at, self.off_at, self.binned_until = None, None, -1
        self.sent_off = False
        self.fatigue = fatigue

    def minutes(self):
        if self.on_at is None:
            return 0
        end = self.off_at if self.off_at is not None else BLOCKS * BLOCK_MINUTES
        return max(0, end - self.on_at)


class _Side:
    def __init__(self, t, team_id, fixture, home):
        self.team_id, self.home = team_id, home
        entry = t.teams[team_id]
        sel = entry.selection
        pids = sel.get("players", [])
        positions = sel.get("positions") or SLOT_POSITIONS
        self.roles = sel.get("roles", {})
        self.field, self.bench, self.all = [], [], []
        for slot, pid in enumerate(pids[:22]):
            ps = t.players.get(pid)
            if ps is None:
                continue
            pos = positions[slot] if slot < len(positions) else SLOT_POSITIONS[slot]
            ctx = MatchContext(fixture=fixture, team_id=team_id, position=pos, slot=slot + 1)
            fatigue = component(ps, "fatigue").get("level", 0) if "fatigue" in ps.components else 0
            p = _Player(pid, pos, ps.positions, effective_stats(t, ps, ctx), fatigue)
            self.all.append(p)
            if slot < 15:
                p.on_at = 0
                self.field.append(p)
            else:
                self.bench.append(p)
        self.lines = {p.pid: PlayerLine(pid=p.pid, started=p in self.field, minutes=0) for p in self.all}
        self.form = 0.0

    def active(self, block):
        return [p for p in self.field if p.binned_until < block and not p.sent_off]

    def units(self, block):
        minute = block * BLOCK_MINUTES
        on = []
        for p in self.active(block):
            played = minute - (p.on_at or 0)
            tired = 1.0 - (played / 80.0) * (105 - p.stats["stamina"]) / 450.0
            tired *= 1.0 - p.fatigue / 600.0
            on.append(({k: v * tired for k, v in p.stats.items()}, p.pos, p.fit))
        return unit_ratings(on)

    def kicker(self, block):
        active = self.active(block)
        designated = self.roles.get("longGK")
        for p in active:
            if p.pid == designated:
                return p
        return max(active, key=lambda p: p.stats["goal_kicking"]) if active else None

    def substitute(self, rng, block, out, reason, events):
        """Replace `out` with the best bench cover for his slot."""
        if not self.bench:
            out.off_at = block * BLOCK_MINUTES + rng.randint(0, BLOCK_MINUTES - 1)
            self.field.remove(out)
            return None
        group = group_of(out.pos)
        same = [b for b in self.bench if group_of(b.pos) == group]
        pool = same or self.bench
        sub = max(pool, key=lambda b: position_fit_value(b, out.pos))
        minute = block * BLOCK_MINUTES + (rng.randint(0, BLOCK_MINUTES - 1) if reason == "injury" else 0)
        out.off_at = minute
        sub.on_at = minute
        if group_of(sub.pos) != group:
            sub.pos = out.pos
            sub.fit = position_fit(sub.positions, sub.pos)
        self.bench.remove(sub)
        self.field[self.field.index(out)] = sub
        events.append({"minute": minute, "team": self.team_id, "kind": "sub",
                       "pid": sub.pid, "off": out.pid, "reason": reason})
        return sub


def position_fit_value(player, pos):
    g_from, g_to = group_of(player.pos), group_of(pos)
    return (2 if g_from == g_to else 0) + player.stats.get("attack", 50) / 100.0


_TRY_WEIGHT = {"back_three": 3.0, "centre": 2.0, "back_row": 1.5, "scrum_half": 1.2,
               "fly_half": 1.0, "hooker": 1.0, "lock": 0.6, "prop": 0.4}
_TACKLE_WEIGHT = {"back_row": 1.6, "lock": 1.3, "centre": 1.2, "hooker": 1.1,
                  "prop": 1.0, "scrum_half": 0.8, "fly_half": 0.9, "back_three": 0.7}
_TACTICAL_SUBS = {5: ("prop", "hooker"), 6: ("lock", "back_row"), 7: ("scrum_half", "centre", "fly_half")}


def simulate(t, fixture, rng) -> MatchResult:
    opts = t.options or {}
    variance = float(opts.get("sim_variance", 1.0))
    injury_rate = float(opts.get("injury_rate", 1.0)) if opts.get("injuries", True) else 0.0
    cards_on = opts.get("cards", True)
    home = _Side(t, fixture.home, fixture, True)
    away = _Side(t, fixture.away, fixture, False)
    sides = (home, away)
    edge = 0.0 if fixture.neutral else HOME_ADVANTAGE
    home.form = rng.gauss(0, DAY_FORM_SIGMA * variance) + edge
    away.form = rng.gauss(0, DAY_FORM_SIGMA * variance)
    events = []
    shares = []

    for block in range(BLOCKS):
        # ── tactical substitutions ──
        for side in sides:
            for group in _TACTICAL_SUBS.get(block, ()):
                if rng.random() < (0.85 if block < 7 else 0.5):
                    cands = [p for p in side.active(block) if group_of(p.pos) == group and p.on_at == 0]
                    if cands and any(group_of(b.pos) == group for b in side.bench):
                        tired = min(cands, key=lambda p: p.stats["stamina"])
                        side.substitute(rng, block, tired, "tactical", events)
        u = {s: s.units(block) for s in sides}

        def territory(s):
            x = u[s]
            return 0.3 * x["scrum"] + 0.2 * x["lineout"] + 0.3 * x["breakdown"] + 0.2 * x["kicking"] + s.form

        share_home = logistic((territory(home) - territory(away)) / TERRITORY_SCALE)
        shares.append(share_home)

        for side, opp, share in ((home, away, share_home), (away, home, 1 - share_home)):
            chances = _poisson(rng, CHANCES_PER_BLOCK * 2 * share)
            att = u[side]["attack"] + side.form
            dfn = u[opp]["defence"] + opp.form
            p_try = logistic((att - dfn) / ATTACK_SCALE + TRY_BIAS)
            p_pen = PENALTY_SHOT_BASE * discipline_factor(u[opp]["discipline"], 0.6, 2.0)
            for _ in range(chances):
                minute = block * BLOCK_MINUTES + rng.randint(0, BLOCK_MINUTES - 1)
                active = side.active(block)
                if not active:
                    break
                roll = rng.random()
                if roll < p_try:
                    weights = [_TRY_WEIGHT.get(group_of(p.pos), 1.0)
                               * (p.stats["attack"] + p.stats["speed"]) / 100.0 for p in active]
                    scorer = rng.choices(active, weights)[0]
                    side.lines[scorer.pid].tries += 1
                    events.append({"minute": minute, "team": side.team_id, "kind": "try", "pid": scorer.pid})
                    kicker = side.kicker(block)
                    if kicker:
                        side.lines[kicker.pid].conversions_attempted += 1
                        if rng.random() < goal_probability(kicker.stats["goal_kicking"], "conversion"):
                            side.lines[kicker.pid].conversions += 1
                            events.append({"minute": minute, "team": side.team_id, "kind": "conversion",
                                           "pid": kicker.pid})
                elif rng.random() < p_pen:
                    kicker = side.kicker(block)
                    if kicker:
                        side.lines[kicker.pid].penalties_attempted += 1
                        if rng.random() < goal_probability(kicker.stats["goal_kicking"], "penalty"):
                            side.lines[kicker.pid].penalties += 1
                            events.append({"minute": minute, "team": side.team_id, "kind": "penalty",
                                           "pid": kicker.pid})
                elif rng.random() < DROP_GOAL_BASE:
                    dropper = max(active, key=lambda p: p.stats["kicking"]
                                  * (1.5 if group_of(p.pos) == "fly_half" else 1.0))
                    if rng.random() < goal_probability(dropper.stats["kicking"], "drop"):
                        side.lines[dropper.pid].drop_goals += 1
                        events.append({"minute": minute, "team": side.team_id, "kind": "drop",
                                       "pid": dropper.pid})

        # ── cards ──
        if cards_on:
            for side in sides:
                active = side.active(block)
                if not active:
                    continue
                disc = u[side]["discipline"]
                factor = discipline_factor(disc, 0.4, 3.0)
                weights = [max(1, 100 - p.stats["discipline"] + p.stats["aggression"]) for p in active]
                minute = block * BLOCK_MINUTES + rng.randint(0, BLOCK_MINUTES - 1)
                if rng.random() < RED_BASE * factor:
                    p = rng.choices(active, weights)[0]
                    p.sent_off = True
                    side.lines[p.pid].red_cards += 1
                    events.append({"minute": minute, "team": side.team_id, "kind": "red", "pid": p.pid})
                elif rng.random() < YELLOW_BASE * factor:
                    p = rng.choices(active, weights)[0]
                    p.binned_until = block + 1
                    side.lines[p.pid].yellow_cards += 1
                    if side.lines[p.pid].yellow_cards >= 2:   # second yellow = red
                        p.sent_off = True
                        side.lines[p.pid].red_cards += 1
                        events.append({"minute": minute, "team": side.team_id, "kind": "red", "pid": p.pid})
                    else:
                        events.append({"minute": minute, "team": side.team_id, "kind": "yellow", "pid": p.pid})

        # ── injuries ──
        if injury_rate > 0:
            for side in sides:
                for p in list(side.active(block)):
                    risk = INJURY_BASE * injury_rate * (1 + (70 - p.stats["fitness"]) / 80.0)
                    risk *= 1 + p.fatigue / 100.0
                    if rng.random() < risk:
                        side.lines[p.pid].injured = True
                        events.append({"minute": block * BLOCK_MINUTES, "team": side.team_id,
                                       "kind": "injury", "pid": p.pid})
                        side.substitute(rng, block, p, "injury", events)

    # ── minutes and tackles ──
    avg_share = sum(shares) / len(shares) if shares else 0.5
    for side in sides:
        for p in side.all:
            side.lines[p.pid].minutes = p.minutes()
        opp_share = (1 - avg_share) if side is home else avg_share
        total = max(20, int(rng.gauss(60 + 100 * opp_share, 12)))
        played = [p for p in side.all if p.minutes() > 0]
        weights = [_TACKLE_WEIGHT.get(group_of(p.pos), 1.0) * p.stats["tackling"] / 100.0
                   * p.minutes() / 80.0 for p in played]
        if played and sum(weights) > 0:
            for p in rng.choices(played, weights, k=total):
                side.lines[p.pid].tackles += 1

    events.sort(key=lambda e: e["minute"])
    result = MatchResult(
        home=SideResult(team_id=home.team_id, players=list(home.lines.values())),
        away=SideResult(team_id=away.team_id, players=list(away.lines.values())),
        source="sim", events=events,
        extra={"territory": round(avg_share, 3)})
    if fixture.knockout and result.home.points == result.away.points:
        settle_knockout_draw(t, result, rng, home_kickers=_kickers(home), away_kickers=_kickers(away))
    return result


def _kickers(side):
    on = [p for p in side.field if not p.sent_off] or side.all
    return sorted((p.stats["goal_kicking"] for p in on), reverse=True)[:5] or [50]


def settle_knockout_draw(t, result, rng, home_kickers=None, away_kickers=None):
    """A drawn knockout tie: template "knockout_draw" decides —
    "tries_then_kicks" (default) or "kicks". The kicking competition is
    five each from the best goal kickers, then sudden death."""
    rule = (t.template or {}).get("knockout_draw", "tries_then_kicks")
    if rule == "tries_then_kicks" and result.home.tries != result.away.tries:
        result.winner = result.home.team_id if result.home.tries > result.away.tries else result.away.team_id
        result.decided_by = "tries"
        return
    hk = home_kickers or [70]
    ak = away_kickers or [70]
    h = a = 0
    for i in range(5):
        h += rng.random() < goal_probability(hk[i % len(hk)])
        a += rng.random() < goal_probability(ak[i % len(ak)])
    i = 5
    while h == a and i < 40:
        h += rng.random() < goal_probability(hk[i % len(hk)])
        a += rng.random() < goal_probability(ak[i % len(ak)])
        i += 1
    if h == a:
        h += 1
    result.shootout = [h, a]
    result.winner = result.home.team_id if h > a else result.away.team_id
    result.decided_by = "kicks"
