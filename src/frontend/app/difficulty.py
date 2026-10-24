"""
app/difficulty.py — difficulty levels beyond the stock game's elite
=====================================================================
The game only knows club/pro/elite (the .mis diff= attribute). "legend" and
"immortal" run the stock game at elite and then strengthen the CPU-controlled
team's roster records before they are written: ratings raised and floored,
mental/physical ratings floored higher, position special skills switched on,
position AI tendencies set, forwards made slightly bigger and star player
classes (reR08 ENABLE_STARPLAYERS) handed out to the players they suit, with
the star over their heads hidden. The human team's stamina/fitness is capped
so it tires while the CPU doesn't.

Only applies to a CPU side against a human side; with humans on both sides
(or none) nothing is changed, the match is plain elite.
"""
import copy

from app import star_classes as SC

# .mis diff= value each level runs the stock AI at.
MISSION_DIFFICULTY = {"club": 0, "pro": 1, "elite": 2, "legend": 2, "immortal": 2}
LEVELS = ["club", "pro", "elite", "legend", "immortal"]

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

# Who gets a star first when a level hands out fewer stars than it could:
# the decision makers, then the breakdown, then the outside backs. A second
# player of a position only comes after every position had its first.
STAR_PRIORITY = ["fly_half", "scrum_half", "openside_flanker", "number_eight", "centre",
                 "fullback", "winger", "blindside_flanker", "second_row", "hooker",
                 "loosehead_prop", "tighthead_prop"]
# Ranking terms: a class in its own position always beats a better-rated
# player out of position; a class already used in the team loses to any
# fitting unused one, so a team gets as many different classes as it can.
FIT_WEIGHT = 100
REUSE_PENALTY = 150
GOAL_KICKER_BONUS = 40

# Immortal attackers: much better attack, faster, harder to bring down.
ATTACK_FLOORS = {
    "attack": 97, "speed": 96, "acceleration": 96, "agility": 95,
    "strength": 93, "crashball": 95, "handling": 92, "passing": 90,
}

PROFILES = {
    "legend": {
        "rating_boost": 8,        # added to every rating
        "rating_floor": 70,       # ...then no rating below this
        "mental_floor": 85,
        "endurance_floor": 85,
        "skills": 2,              # position special skills switched on
        "stars": 8,               # how many players get a star class
        "star_pool": "starters",  # starters | all
        "stars_front_five": False,
        # Kept small: the body model scales with height/weight.
        "forward_weight_kg": 2,
        "forward_height_cm": 1,
        "human_endurance_cap": 80,   # human team's stamina/fitness ceiling
    },
    "immortal": {
        "rating_boost": 15,
        "rating_floor": 82,
        "key_floor": ATTACK_FLOORS,   # raised further for the attacking ratings
        "mental_floor": 96,
        "endurance_floor": 99,
        "skills": 99,
        "all_skills": ["ss_tackle_breaker", "ss_scoring"],   # every player, any position
        "stars": 99,
        "star_pool": "all",
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
    for key, floor in profile.get("key_floor", {}).items():
        p[key] = _clamp(max(p[key], floor))
    for key in MENTAL_KEYS:
        p[key] = _clamp(max(p[key], profile["mental_floor"]))
    for key in ENDURANCE_KEYS:
        p[key] = _clamp(max(p[key], profile["endurance_floor"]))
    for skill in POSITION_SKILLS.get(p.get("pos1"), [])[:profile["skills"]]:
        p[skill] = True
    for skill in profile.get("all_skills", []):
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
        # The abilities stay a surprise: no star over the head (rugby08patches.dll)
        p["hide_star"] = True
    return p


def _star_score(player, flag, goal_kicker):
    fit = SC.position_fit(flag, player.get("pos1"))
    if not fit:
        return None
    ratings = SC.CLASSES[flag][1]
    score = fit * FIT_WEIGHT + sum(player.get(k, 0) for k in ratings) / len(ratings)
    if goal_kicker and flag in SC.GOAL_KICKERS:
        score += GOAL_KICKER_BONUS
    return score


def _star_candidates(players, profile):
    """Indices of the players a level gives a star to, best first."""
    pool = len(players) if profile["star_pool"] == "all" else STARTERS
    eligible = [i for i, p in enumerate(players[:pool])
                if not p.get("star_attribute")
                and (profile["stars_front_five"] or p.get("pos1") not in FRONT_FIVE)]
    seen = {}

    def rank(i):
        pos = players[i].get("pos1")
        nth = seen[pos] = seen.get(pos, -1) + 1
        order = STAR_PRIORITY.index(pos) if pos in STAR_PRIORITY else len(STAR_PRIORITY)
        return (nth, order, i)

    ranked = sorted((rank(i) for i in eligible))
    return [i for _, _, i in ranked][:profile["stars"]]


def assign_stars(players, profile, kicker_index):
    """{player index: star class}. Each step takes the best remaining
    (player, class) pair: the class that plays the player's position and
    rewards his strongest ratings, used once per team while unused ones fit."""
    candidates = _star_candidates(players, profile)
    uses = {}
    for p in players:
        if p.get("star_attribute"):
            uses[p["star_attribute"]] = uses.get(p["star_attribute"], 0) + 1
    assigned = {}
    while candidates:
        best = None
        for i in candidates:
            for flag in SC.CLASSES:
                score = _star_score(players[i], flag, i == kicker_index)
                if score is None:
                    continue
                score -= REUSE_PENALTY * uses.get(flag, 0)
                if best is None or score > best[0]:
                    best = (score, i, flag)
        if best is None:
            break
        _, i, flag = best
        assigned[i] = flag
        uses[flag] = uses.get(flag, 0) + 1
        candidates.remove(i)
    return assigned


def boost_team(team: dict, level: str) -> dict:
    """Copy of a match_data team with its players strengthened for `level`;
    the team unchanged for the stock levels."""
    profile = PROFILES.get(level)
    if not profile:
        return team
    team = dict(team)
    players = team.get("players", [])
    # roles hold shirt numbers (1-15)
    kicker_index = team.get("roles", {}).get("long_GK", 10) - 1
    stars = assign_stars(players, profile, kicker_index)
    team["players"] = [boost_player(player, profile, stars.get(index, 0), index == kicker_index)
                       for index, player in enumerate(players)]
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
