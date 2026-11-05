"""
tournament/trophy.py — who lifts the trophy at the end of a user's match.

A final: its winner (the patch's default). A competition with no final (the
Six Nations, a league): the user's match on the closing matchday of the
last round-robin stage decides it. The trophy is fixed in the .mis before
kick-off, so the day's other matches are played first (decider_prelude);
then, for each result of the user's match (home win, away win, draw), a
grid of scorelines is put through the table: when every scoreline of a
result crowns the same team and that team is on the pitch, it lifts the
trophy on that result — even when it loses the match (a losing bonus point
can be enough). A result that leaves the title open, or crowns a team
elsewhere, lifts nothing.

The patch side (rugby08patches.dll, ENABLE_TROPHY_LIFT) reads it as
trophy_lifter="home_win:home;away_win:away;draw:none".
"""
from dataclasses import dataclass

from . import standings
from .model import MatchResult

RESULTS = ("home_win", "away_win", "draw")
DEFAULT_LIFTERS = {"home_win": "home", "away_win": "away", "draw": None}


@dataclass
class _Side:
    """The few numbers the table reads from a side's result."""
    team_id: str
    points: int
    tries: int
    yellow_cards: int = 0
    red_cards: int = 0


def _flat(result):
    """`result` with its sides' numbers read once."""
    def side(r):
        return _Side(r.team_id, r.points, r.tries, r.yellow_cards, r.red_cards)
    return MatchResult(home=side(result.home), away=side(result.away), source=result.source,
                       winner=result.winner, decided_by=result.decided_by)


def _closing_stage(t):
    """The stage that crowns the champion when nothing else does: the last
    one, a single-group round robin, and no final anywhere."""
    if any(f.final for f in t.fixtures) or not t.stages:
        return None
    last = t.stages[-1]
    if last.kind != "round_robin" or len(last.groups) != 1:
        return None
    return last


def is_decider(t, fixture) -> bool:
    """`fixture` is on the closing matchday of a competition with no final."""
    stage = _closing_stage(t)
    if stage is None or fixture.stage_id != stage.id:
        return False
    days = [f.day for f in t.fixtures if f.stage_id == stage.id]
    return bool(days) and fixture.day == max(days)


def decider_prelude(t, fixture, simulate) -> list:
    """Before a deciding match: the day's other AI matches of the stage,
    played with `simulate(t, f)` (engine.simulate_fixture), so the table
    the user plays for is known. Returns them."""
    if not is_decider(t, fixture):
        return []
    from .engine import is_human_fixture
    done = []
    for f in list(t.fixtures_on(t.day)):
        if f is fixture or f.played or not f.ready or is_human_fixture(t, f):
            continue
        if f.stage_id == fixture.stage_id:
            simulate(t, f)
            done.append(f)
    return done


def _side_scores():
    """(points, tries) a side can end a match with: 0-6 tries, converted or
    not, and 0-4 penalties."""
    out = set()
    for tries in range(7):
        for conv in {0, tries}:
            for pens in range(5):
                out.add((5 * tries + 2 * conv + 3 * pens, tries))
    return sorted(out)


_SCORES = _side_scores()


def _scorelines(result):
    for hp, ht in _SCORES:
        for ap, at in _SCORES:
            if (result == "home_win" and hp > ap) or (result == "away_win" and ap > hp) \
                    or (result == "draw" and hp == ap):
                yield (hp, ht), (ap, at)


def lifters(t, fixture):
    """{result: "home" | "away" | None} for a deciding match, None when the
    match decides nothing (not a decider, or another match of the stage is
    still to be played)."""
    if not is_decider(t, fixture):
        return None
    stage = _closing_stage(t)
    group = stage.groups[0]
    if any(not f.played for f in t.fixtures
           if f.stage_id == stage.id and f.group == group.id and f is not fixture):
        return None
    sides = {fixture.home: "home", fixture.away: "away"}
    rules = t.template.get("points")
    saved = fixture.result
    # the stage's results as plain numbers while the table is worked out
    # thousands of times (a SideResult adds its players up on every read)
    played = [f for f in t.fixtures if f.stage_id == stage.id and f.result and f is not fixture]
    real = {f.id: f.result for f in played}
    for f in played:
        f.result = _flat(f.result)

    def top(score):
        (hp, ht), (ap, at) = score
        fixture.result = MatchResult(home=_Side(fixture.home, hp, ht),
                                     away=_Side(fixture.away, ap, at))
        table = standings.group_table(t, stage, group)
        if not table:
            return None, False
        clear = len(table) < 2 or table[0].points > table[1].points
        return table[0].team_id, clear

    out = {}
    try:
        for result in RESULTS:
            # the table points the match gives each side: scorelines alike in
            # those give the same points table, so one stands for them all
            # unless the top is level on points (then the tiebreakers read the
            # score itself and every scoreline is tried)
            by_points = {}
            for score in _scorelines(result):
                (hp, ht), (ap, at) = score
                h, a = _Side(fixture.home, hp, ht), _Side(fixture.away, ap, at)
                key = (standings.match_points(rules, h, a)[0], standings.match_points(rules, a, h)[0])
                by_points.setdefault(key, []).append(score)
            # settled as soon as two champions differ, or one is off the pitch
            champions = set()
            done = lambda: len(champions) > 1 or not champions <= set(sides)   # noqa: E731
            for scores in by_points.values():
                champion, clear = top(scores[0])
                champions.add(champion)
                if not clear:
                    for score in scores[1:]:
                        if done():
                            break
                        champions.add(top(score)[0])
                if done():
                    break
            (champion,) = champions if len(champions) == 1 else (None,)
            out[result] = sides.get(champion)
    finally:
        fixture.result = saved
        for f in played:
            f.result = real[f.id]
    return out


def lifter_attr(by_result) -> str:
    """The .mis trophy_lifter value, "" when it is the patch's default (the
    winner lifts, a draw lifts nothing)."""
    if not by_result or by_result == DEFAULT_LIFTERS:
        return ""
    return ";".join(f"{r}:{by_result.get(r) or 'none'}" for r in RESULTS)
