"""
app/star_classes.py — the game's 25 star player classes (roster star_attribute)
================================================================================
star_attribute N (reR08 ENABLE_STARPLAYERS) gives a player the star class
the stock game built for one real player. Verified from the class factory
FUN_0069c010 (roster id -> class ctor -> RTTI name) and the stock player DB.
1 is the generic base class (tackle breaking only, no star shown).

Each class lists the positions its real player played (best fit first) and
the ratings its abilities lean on (STAR_ABILITIES.md in reR08), so a class
can be matched to a player who plays like it.
"""

NAMES = {
    0: "— none", 1: "Star player (generic)",
    2: "Carter", 3: "Wilkinson", 4: "O'Driscoll", 5: "McCaw", 6: "S. Williams",
    7: "Umaga", 8: "Gregan", 9: "Giteau", 10: "Habana", 11: "Henson",
    12: "Robinson", 13: "G. Smith", 14: "Larkham", 15: "Montgomery", 16: "Pichot",
    17: "Spencer", 18: "Dallaglio", 19: "Lewsey", 20: "O'Gara", 21: "Collins",
    22: "Rokocoko", 23: "Tuqiri", 24: "Latham", 25: "Betsen", 26: "Burger",
}

# flag -> (positions, ratings the class's abilities reward)
CLASSES = {
    2: (["fly_half", "centre"], ["passing", "creativity", "kicking", "goal_kicking"]),
    3: (["fly_half"], ["goal_kicking", "kicking_power", "kicking", "tackling"]),
    4: (["centre"], ["speed", "agility", "handling", "tackling"]),
    5: (["openside_flanker"], ["rucking", "tackling", "defense"]),
    6: (["winger"], ["speed", "acceleration", "agility"]),
    7: (["centre"], ["strength", "crashball", "tackling"]),
    8: (["scrum_half"], ["passing", "handling", "creativity"]),
    9: (["scrum_half", "fly_half", "centre"], ["passing", "kicking", "speed"]),
    10: (["winger"], ["speed", "acceleration"]),
    11: (["centre", "fly_half"], ["kicking_power", "strength", "tackling"]),
    12: (["fullback", "winger"], ["agility", "acceleration", "speed"]),
    13: (["openside_flanker"], ["rucking", "handling", "tackling"]),
    14: (["fly_half", "centre", "fullback"], ["creativity", "passing", "agility"]),
    15: (["fullback"], ["goal_kicking", "kicking_power", "kicking"]),
    16: (["scrum_half"], ["passing", "aggression", "speed"]),
    17: (["fly_half"], ["creativity", "agility", "kicking"]),
    18: (["number_eight", "blindside_flanker"], ["strength", "crashball", "aggression"]),
    19: (["winger", "fullback"], ["speed", "tackling", "strength"]),
    20: (["fly_half"], ["goal_kicking", "kicking", "passing"]),
    21: (["blindside_flanker", "number_eight"], ["tackling", "strength", "aggression"]),
    22: (["winger"], ["speed", "acceleration", "strength"]),
    23: (["winger", "centre"], ["strength", "handling", "speed"]),
    24: (["fullback"], ["handling", "kicking", "speed"]),
    25: (["blindside_flanker", "openside_flanker"], ["tackling", "aggression", "rucking"]),
    26: (["blindside_flanker", "openside_flanker", "number_eight"], ["tackling", "strength", "aggression"]),
}

# No front-five star exists in the game: the closest forward classes (big
# hits and carries for props and locks, breakdown work for the hooker).
FRONT_FIVE_FIT = {
    "loosehead_prop": [18, 21, 26],
    "tighthead_prop": [18, 21, 26],
    "hooker": [13, 5, 25],
    "second_row": [26, 21, 18],
}

# Classes whose abilities are mostly about kicking at goal.
GOAL_KICKERS = {3, 15, 20, 2}


def position_fit(flag: int, position: str) -> int:
    """3 = the class's own position, 2 = another position its player played,
    1 = front-five stand-in, 0 = doesn't fit."""
    positions = CLASSES[flag][0]
    if positions and positions[0] == position:
        return 3
    if position in positions:
        return 2
    if flag in FRONT_FIVE_FIT.get(position, []):
        return 1
    return 0
