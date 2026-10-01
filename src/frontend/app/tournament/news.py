"""
tournament/news.py — Headlines for the dashboard feed: results worth a
line (upsets, thrashings), qualification and elimination, the champion.
Injury, ban and return headlines are written by their own modules.
"""
from . import standings
from .events import on

UPSET_GAP = 5.0       # rating points between the sides
THRASHING = 40


@on("pre_match", priority=90)
def _ratings(t, fixture):
    """Remember the sides' pre-match ratings for upset detection."""
    from .strength import team_rating
    t.components.setdefault("pre_ratings", {})[fixture.id] = {
        fixture.home: round(team_rating(t, fixture.home), 1),
        fixture.away: round(team_rating(t, fixture.away), 1),
    }


@on("match_completed", priority=90)
def _result(t, fixture, result, rng):
    ratings = t.components.get("pre_ratings", {}).pop(fixture.id, None)
    winner, loser = result.winner_id(), result.loser_id()
    home, away = t.team_name(fixture.home), t.team_name(fixture.away)
    score = result.score_text()
    if fixture.final and winner:
        t.add_news("champion", f"{t.team_name(winner)} win the {t.name}! Final: {home} {score} {away}",
                   [winner])
        return
    if winner and ratings and ratings.get(loser, 0) - ratings.get(winner, 0) >= UPSET_GAP:
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
