"""
tournament/news.py — Headlines for the dashboard feed: results worth a
line (upsets, thrashings), qualification and elimination, the champion.
Injury, ban and return headlines are written by their own modules.
"""
from . import standings
from .events import on

UPSET_CHANCE = 0.30   # a win the winner had less than this chance of
THRASHING = 40


@on("pre_match", priority=90)
def _odds(t, fixture):
    """Remember the home side's pre-match win chance for upset detection."""
    from .simulator import win_probability
    t.components.setdefault("pre_odds", {})[fixture.id] = round(win_probability(t, fixture), 3)


@on("match_completed", priority=90)
def _result(t, fixture, result, rng):
    t.components.get("pre_ratings", {}).pop(fixture.id, None)     # older saves
    home_chance = t.components.get("pre_odds", {}).pop(fixture.id, None)
    winner, loser = result.winner_id(), result.loser_id()
    home, away = t.team_name(fixture.home), t.team_name(fixture.away)
    score = result.score_text()
    if fixture.final and winner:
        t.add_news("champion", f"{t.team_name(winner)} win the {t.name}! Final: {home} {score} {away}",
                   [winner])
        return
    chance = None if home_chance is None else (home_chance if winner == fixture.home else 1 - home_chance)
    if winner and chance is not None and chance < UPSET_CHANCE:
        t.add_news("upset", f"Upset! {t.team_name(winner)} beat {t.team_name(loser)} ({home} {score} {away})",
                   [winner, loser])
    elif abs(result.home.points - result.away.points) >= THRASHING:
        t.add_news("result", f"{t.team_name(winner)} run riot: {home} {score} {away}", [winner, loser])
    elif fixture.knockout and winner:
        t.add_news("result", f"{t.team_name(winner)} through: {home} {score} {away}", [winner, loser])


@on("stage_completed", priority=90)
def _stage(t, stage):
    if stage.kind != "round_robin":
        return
    for g in stage.groups:
        tab = standings.group_table(t, stage, g)
        if tab:
            t.add_news("stage", f"{g.name} won by {t.team_name(tab[0].team_id)}"
                       f" ({tab[0].points} pts)", [tab[0].team_id])


@on("tournament_completed", priority=90)
def _done(t):
    from .stats import leaders
    top = leaders(t, "points", 1)
    tries = leaders(t, "tries", 1)
    if top:
        t.add_news("award", f"Top points scorer: {t.player_name(top[0][0])} ({top[0][1]})", [], top[0][0])
    if tries:
        t.add_news("award", f"Top try scorer: {t.player_name(tries[0][0])} ({tries[0][1]})", [], tries[0][0])
