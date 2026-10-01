"""
app/difficulty.py — difficulty levels beyond the stock game's elite
=====================================================================
The game only knows club/pro/elite (the .mis diff= attribute). "legend" and
"immortal" run the stock game at elite and then strengthen the CPU-controlled
team's roster records before they are written: ratings raised and floored,
mental/physical ratings floored higher, position special skills switched on,
position AI tendencies set, forwards made slightly bigger and star player
classes (reR08 ENABLE_STARPLAYERS) handed out by position. The human team's
stamina/fitness is capped so it tires while the CPU doesn't.

Only applies to a CPU side against a human side; with humans on both sides
(or none) nothing is changed, the match is plain elite.
"""
import copy

# .mis diff= value each level runs the stock AI at.
MISSION_DIFFICULTY = {"club": 0, "pro": 1, "elite": 2, "legend": 2, "immortal": 2}
LEVELS = list(MISSION_DIFFICULTY)

RATING_KEYS = [
    "attack", "defense", "speed", "acceleration", "agility", "handling", "passing",
    "kicking", "kicking_power", "goal_kicking", "tackling", "strength", "rucking",
    "scrummaging", "hooking", "line_out", "discipline", "aggression", "stamina",
    "consistency", "temperament", "creativity", "bravery", "fitness", "crashball",
    "gap_defense",
]
# Fewer penalties/handling errors, no late-match fade: floored separately so a
# boosted team doesn't give the game away through ill discipline or tiring.
MENTAL_KEYS = ["discipline", "consistency", "temperament", "bravery"]
ENDURANCE_KEYS = ["stamina", "fitness"]

FRONT_FIVE = {"loosehead_prop", "hooker", "tighthead_prop", "second_row"}
FORWARDS = FRONT_FIVE | {"blindside_flanker", "openside_flanker", "number_eight"}

# AI tendency (roster special_ability, see gsv.special_ability_id) that fits
# each position. Only replaces "default" (0) — a hand-set tendency is kept.
POSITION_TENDENCY = {
    "loosehead_prop": 1, "tighthead_prop": 1, "hooker": 1,   # scrum
    "second_row": 2,                                         # lineout
    "blindside_flanker": 3,                                  # tackler
    "openside_flanker": 8,                                   # ruck
    "number_eight": 7,                                       # crasher
    "scrum_half": 5,                                         # passer
    "fly_half": 10,                                          # playmaker
    "centre": 7,                                             # crasher
    "winger": 4,                                             # runner
    "fullback": 6,                                           # kicker
}
TENDENCY_GOALKICKER = 9

# Special skills that fit each position, most important first; a level that
# grants N skills turns on the first N.
POSITION_SKILLS = {
    "loosehead_prop": ["ss_scrummager", "ss_tackling", "ss_ball_winner", "ss_crashball"],
    "tighthead_prop": ["ss_scrummager", "ss_tackling", "ss_ball_winner", "ss_crashball"],
    "hooker": ["ss_scrummager", "ss_ball_winner", "ss_tackling", "ss_crashball"],
    "second_row": ["ss_jumper", "ss_ball_winner", "ss_tackling", "ss_scrummager"],
    "blindside_flanker": ["ss_tackling", "ss_ball_winner", "ss_tackle_breaker", "ss_crashball"],
    "openside_flanker": ["ss_ball_winner", "ss_tackling", "ss_defensive_organisation", "ss_tackle_breaker"],
    "number_eight": ["ss_crashball", "ss_tackle_breaker", "ss_ball_winner", "ss_tackling"],
    "scrum_half": ["ss_passer", "ss_command", "ss_tactical_kicking", "ss_play_maker"],
    "fly_half": ["ss_play_maker", "ss_tactical_kicking", "ss_goal_kicker", "ss_command", "ss_passer"],
    "centre": ["ss_tackle_breaker", "ss_defensive_organisation", "ss_crashball", "ss_tackling"],
    "winger": ["ss_scoring", "ss_tackle_breaker"],
    "fullback": ["ss_scoring", "ss_tactical_kicking", "ss_defensive_organisation", "ss_goal_kicker"],
}

# Star player classes (see screens/player_tabs.STAR_PLAYER_NAMES) whose real
# player played that position. Cycled through per team so two players of the
# same position get different classes while the pool lasts.
POSITION_STARS = {
    "fly_half": [8, 14, 3, 12],            # Carter, Spencer, Wilkinson, Larkham
    "scrum_half": [16],                    # Gregan
    "centre": [11, 21, 20],                # O'Driscoll, Umaga, Giteau
    "winger": [13, 26],                    # Tuqiri, Lewsey
    "fullback": [19, 15],                  # Latham, Montgomery
    "openside_flanker": [22, 24, 10],      # McCaw, G. Smith, Betsen
    "blindside_flanker": [25, 17, 10],     # Burger, Collins, Betsen
    "number_eight": [9, 25],               # Dallaglio, Burger
    # No front-five star in the game: the ball-carrying back-row classes are
    # the closest fit, only handed out by levels with stars_front_five.
    "loosehead_prop": [17, 9],
    "tighthead_prop": [17, 9],
    "hooker": [17, 9],
    "second_row": [9, 17],
}

PROFILES = {
    "legend": {
        "rating_boost": 8,        # added to every rating
        "rating_floor": 70,       # ...then no rating below this
        "mental_floor": 85,
        "endurance_floor": 85,
        "skills": 2,              # position special skills switched on
        "stars": "starters",      # starters | all
        "stars_front_five": False,
        # Kept small: the body model scales with height/weight.
        "forward_weight_kg": 2,
        "forward_height_cm": 1,
        "human_endurance_cap": 80,   # human team's stamina/fitness ceiling
    },
    "immortal": {
        "rating_boost": 15,
        "rating_floor": 82,
        "mental_floor": 96,
        "endurance_floor": 99,
        "skills": 99,
        "stars": "all",
        "stars_front_five": True,
        "forward_weight_kg": 4,
        "forward_height_cm": 2,
        "human_endurance_cap": 70,
    },
}

STARTERS = 15


def mission_difficulty(level: str) -> int:
    return MISSION_DIFFICULTY.get(level, 2)


def cpu_teams(home_humans: int, away_humans: int) -> list:
    """The match_data team keys controlled by the CPU against a human."""
    if home_humans and not away_humans:
        return ["team_B"]
    if away_humans and not home_humans:
        return ["team_A"]
    return []


def _clamp(value):
    return max(0, min(99, int(value)))


def boost_player(player: dict, profile: dict, star_class: int = 0,
                 goal_kicker: bool = False) -> dict:
    p = copy.deepcopy(player)
    for key in RATING_KEYS:
        p[key] = _clamp(max(p.get(key, 0) + profile["rating_boost"], profile["rating_floor"]))
    for key in MENTAL_KEYS:
        p[key] = _clamp(max(p[key], profile["mental_floor"]))
    for key in ENDURANCE_KEYS:
        p[key] = _clamp(max(p[key], profile["endurance_floor"]))
    for skill in POSITION_SKILLS.get(p.get("pos1"), [])[:profile["skills"]]:
        p[skill] = True
    if p.get("pos1") in FORWARDS:
        p["weight"] = p.get("weight", 0) + profile["forward_weight_kg"]
        p["height"] = p.get("height", 0) + profile["forward_height_cm"]
    if not p.get("special_ability"):
        if goal_kicker and p.get("pos1") != "fly_half":
            p["special_ability"] = TENDENCY_GOALKICKER
        else:
            p["special_ability"] = POSITION_TENDENCY.get(p.get("pos1"), 0)
    if star_class and not p.get("star_attribute"):
        p["star_attribute"] = star_class
    return p


def _star_for(position, profile, used):
    if position in FRONT_FIVE and not profile["stars_front_five"]:
        return 0
    pool = POSITION_STARS.get(position, [])
    for star in pool:
        if star not in used:
            return star
    return pool[0] if pool else 0


def boost_team(team: dict, level: str) -> dict:
    """Copy of a match_data team with its players strengthened for `level`;
    the team unchanged for the stock levels."""
    profile = PROFILES.get(level)
    if not profile:
        return team
    team = dict(team)
    players = team.get("players", [])
    used = {p.get("star_attribute") for p in players if p.get("star_attribute")}
    # roles hold shirt numbers (1-15)
    kicker_index = team.get("roles", {}).get("long_GK", 10) - 1
    boosted = []
    for index, player in enumerate(players):
        star = 0
        if not player.get("star_attribute") and (profile["stars"] == "all" or index < STARTERS):
            star = _star_for(player.get("pos1"), profile, used)
            if star:
                used.add(star)
        boosted.append(boost_player(player, profile, star, index == kicker_index))
    team["players"] = boosted
    return team


def tire_team(team: dict, level: str) -> dict:
    """Copy of a match_data team with stamina/fitness capped for `level`, so
    the human side fades late in the match while the CPU side doesn't."""
    cap = PROFILES[level]["human_endurance_cap"]
    team = dict(team)
    team["players"] = [dict(p, **{k: min(p.get(k, 0), cap) for k in ENDURANCE_KEYS})
                       for p in team.get("players", [])]
    return team


def apply(match_data: dict, level: str, home_humans: int, away_humans: int) -> dict:
    if level not in PROFILES:
        return match_data
    for key in cpu_teams(home_humans, away_humans):
        human = "team_A" if key == "team_B" else "team_B"
        match_data[key] = boost_team(match_data[key], level)
        match_data[human] = tire_team(match_data[human], level)
    return match_data
