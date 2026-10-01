"""
app/challenges.py — challenge definitions (mod_data/challenges/*.json)
=========================================================================
A challenge is one hand-authored match: two squads, the rules, the weather,
and optionally a mid-match starting state (score so far, a scrum or lineout
restart) plus objectives. It is stored as a plain JSON file and turned into
the same MatchConfig the match-setup screen edits, so everything downstream
(build_match_data, create_mission_file) is shared with quick match.

Keys not present in a file fall back to DEFAULTS, so files written by an
older editor keep loading after a field is added.
"""
import copy
import json
import os
import re

from backend import game_specific_variables as gsv
from shared.config import config
from shared.log import get_logger
from app import difficulty
from app.state import MatchConfig, TeamSlot

log = get_logger(__name__)

DIFFICULTIES = list(difficulty.LEVELS)
HALF_LENGTHS = list(gsv.halftime_length)
SIDES = ["random", "left", "right"]
KICK_OFFS = ["random", "home", "away"]
ENVIRONMENTS = ["day", "night", "overcast", "cold"]
PRECIP_MODES = ["stock", "none", "rain", "snow"]
USER_SIDES = ["home", "away"]

DEFAULTS = {
    "name": "New challenge",
    "description": "",          # shown before the match
    "win_text": "",             # shown after a win / draw / loss
    "draw_text": "",
    "loss_text": "",
    "order": 0,                 # position in the challenge list
    "user_side": "home",        # which team the player controls
    "home": {"team_id": "", "season": "", "kit": "home"},
    "away": {"team_id": "", "season": "", "kit": "away"},
    "stadium_id": "",           # key in stadiums.json; "" = default stadium
    "difficulty": "elite",
    "halftime_length": "5m",
    "home_team_side": "random",
    "kick_off": "random",
    "match_type": "exhibition",
    "match_subtype": "none",
    "environment": "day",
    "pitch_texture": "default",
    "rain": False,
    "precip_mode": "stock",
    "snow_intensity": None,
    "wind_power": None,
    "wind_dir_deg": 0,
    "breath": None,
    "anthem": "stock",
    "haka_home": False,
    "haka_away": False,
    "trophy_lift": "stock",
    "stadium_flags": None,
    "kick_assist": False,
    "mission_mode_name": "",
    "mission_mode_time": None,
    "mission_mode_period": None,
    "mission_nis": [],
    "score_events": [],
    "objectives": [],
    "unlockables": [],          # [{"name": "MATCH BALL 1", "id": 1}]
    "user_choice": [],          # CHOOSABLE keys the player sets before kick-off
}

# Fields a challenge can leave to the player: picked on the match
# presentation screen, starting from the challenge's own value. Not listed in
# `user_choice` = fixed by the challenge (a kit included).
CHOOSABLE = {
    "home_kit": "home kit",
    "away_kit": "away kit",
    "user_side": "you control",
    "stadium_id": "stadium",
    "difficulty": "difficulty",
    "halftime_length": "half length",
    "kick_off": "kick-off",
    "home_team_side": "home plays",
    "environment": "environment",
    "pitch_texture": "pitch",
    "precip_mode": "precipitation",
    "kick_assist": "easy goal kick",
}


def challenges_directory() -> str:
    return config.directory_challenges


def new_challenge() -> dict:
    return copy.deepcopy(DEFAULTS)


def _slug(text: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return slug or "challenge"


def unique_id(name: str, taken) -> str:
    base, n, candidate = _slug(name), 2, _slug(name)
    while candidate in taken:
        candidate = f"{base}_{n}"
        n += 1
    return candidate


def _path(cid: str) -> str:
    return os.path.join(challenges_directory(), cid + ".json")


def normalise(data: dict) -> dict:
    """`data` over DEFAULTS, one level deep for the two team blocks."""
    out = new_challenge()
    for key, value in (data or {}).items():
        if key in ("home", "away") and isinstance(value, dict):
            out[key].update(value)
        else:
            out[key] = value
    return out


def load_all() -> dict:
    """{challenge_id: challenge}, ordered by `order` then name. A file that
    cannot be read is skipped with a warning rather than hiding the rest."""
    found = {}
    folder = challenges_directory()
    if not os.path.isdir(folder):
        return found
    for fname in os.listdir(folder):
        if not fname.endswith(".json"):
            continue
        try:
            with open(os.path.join(folder, fname), encoding="utf-8") as f:
                found[fname[:-5]] = normalise(json.load(f))
        except (OSError, ValueError) as e:
            log.warning(f"challenge {fname} skipped: {e}")
    return dict(sorted(found.items(), key=lambda kv: (kv[1]["order"], kv[1]["name"].lower())))


def save(cid: str, data: dict) -> str:
    os.makedirs(challenges_directory(), exist_ok=True)
    path = _path(cid)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")
    os.replace(tmp, path)
    return path


def delete(cid: str) -> None:
    try:
        os.remove(_path(cid))
    except FileNotFoundError:
        pass


def problems(ds, data: dict) -> list:
    """Human-readable reasons this challenge cannot be played as it stands."""
    found = []
    for side in ("home", "away"):
        slot = data[side]
        seasons = ds.teams.get(slot["team_id"])
        if not slot["team_id"]:
            found.append(f"{side} team not chosen")
        elif seasons is None:
            found.append(f"{side} team {slot['team_id']} is not in the data")
        elif slot["season"] not in seasons:
            found.append(f"{side} team has no {slot['season'] or 'season'} squad")
    if data["stadium_id"] and data["stadium_id"] not in ds.stadiums:
        found.append(f"stadium {data['stadium_id']} is not in the data")
    return found


def to_match_config(ds, data: dict) -> MatchConfig:
    """The MatchConfig that plays this challenge. The player's controller is
    the keyboard, on `user_side`."""
    cfg = MatchConfig()
    for side, slot in (("home", cfg.home), ("away", cfg.away)):
        spec = data[side]
        slot.team_id, slot.season = spec["team_id"], spec["season"]
        info = ds.teams[slot.team_id][slot.season]
        kit_keys = list(info.get("kits", {}))
        slot.kit_index = kit_keys.index(spec["kit"]) if spec["kit"] in kit_keys else 0
        slot.lineup = ds.get_lineup(slot.team_id, slot.season)
        slot.players = ds.get_players(slot.lineup.get("players_id", []), slot.season)

    sid = data["stadium_id"] or next(iter(ds.stadiums), "")
    if sid in ds.stadiums:
        info = ds.stadiums[sid]
        cfg.stadium = {"stadium_id": int(info.get("game_id", sid)), "data": info}

    for key in ("difficulty", "halftime_length", "home_team_side", "kick_off",
                "match_type", "match_subtype", "environment", "pitch_texture",
                "rain", "precip_mode", "snow_intensity", "wind_power",
                "breath", "anthem", "haka_home", "haka_away", "trophy_lift",
                "stadium_flags", "kick_assist", "mission_mode_name",
                "mission_mode_time", "mission_mode_period"):
        setattr(cfg, key, data[key])
    cfg.wind_dir_deg = float(data["wind_dir_deg"] or 0)
    cfg.mission_nis = copy.deepcopy(data["mission_nis"])
    cfg.score_events = copy.deepcopy(data["score_events"])
    cfg.objectives = copy.deepcopy(data["objectives"])
    cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": data["user_side"]}}
    return cfg


def is_choice(data: dict, key: str) -> bool:
    return key in (data.get("user_choice") or [])


def _kits(ds, data, side):
    slot = data[side]
    return list(ds.teams.get(slot["team_id"], {}).get(slot["season"], {}).get("kits", {}))


def choice_options(ds, data: dict, key: str):
    """(values, display) the player picks `key` from. The challenge's own
    value is always among them, so it can stay the starting pick."""
    def yes_no(v):
        return "yes" if v else "no"
    if key in ("home_kit", "away_kit"):
        return _kits(ds, data, key[:-4]), str
    if key == "stadium_id":
        stadiums = sorted(ds.stadiums.items(), key=lambda kv: kv[1].get("name", "").lower())
        names = {sid: info.get("name", sid) for sid, info in stadiums}
        values = [sid for sid, _ in stadiums]
        if data["stadium_id"] not in values:
            values.insert(0, data["stadium_id"])
        return values, lambda s: names.get(s, "default")
    values, display = {
        "user_side": (USER_SIDES, str),
        "difficulty": (DIFFICULTIES, str),
        "halftime_length": (HALF_LENGTHS, str),
        "kick_off": (KICK_OFFS, str),
        "home_team_side": (SIDES, str),
        "environment": (ENVIRONMENTS, str),
        "pitch_texture": (["default"] + list(gsv.pitch_textures), str),
        "precip_mode": (PRECIP_MODES, str),
        "kick_assist": ([False, True], yes_no),
    }[key]
    values = list(values)
    if data.get(key) not in values:
        values.insert(0, data.get(key))
    return values, display


def get_choice(data: dict, key: str):
    if key in ("home_kit", "away_kit"):
        return data[key[:-4]]["kit"]
    return data[key]


def set_choice(data: dict, key: str, value) -> None:
    if key in ("home_kit", "away_kit"):
        data[key[:-4]]["kit"] = value
    else:
        data[key] = value


def summary(ds, data: dict) -> str:
    def team(side):
        slot = data[side]
        info = ds.teams.get(slot["team_id"], {}).get(slot["season"], {})
        return info.get("name") or slot["team_id"] or "?"
    half = "your pick of half length" if is_choice(data, "halftime_length") \
        else f"{data['halftime_length']} halves"
    level = "your pick of difficulty" if is_choice(data, "difficulty") else data["difficulty"]
    return f"{team('home')} v {team('away')} · {half} · {level}"
