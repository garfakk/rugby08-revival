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
from shared.user_prefs import user_prefs
from app import competition_branding, difficulty
from app.state import MatchConfig, TeamSlot

log = get_logger(__name__)

DIFFICULTIES = list(difficulty.LEVELS)
HALF_LENGTHS = list(gsv.halftime_length)
# A challenge replays a real match from a fixed point: who kicks off (or has
# the restart) and which end each side plays are part of it, never random.
SIDES = ["left", "right"]
KICK_OFFS = ["home", "away"]
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
    # "variant": a squad variant of the season ("" = default squad), "kit_variant":
    # a variant of the kit itself ("" = plain kit), see app/variants.py
    # "squad": None = the team's (variant) squad; otherwise a hand-picked one,
    # {"players": [22 ids, shirts 1-22], "roles": {...}, "set_plays": {...}}
    # "custom_kit": None = the picked kit; otherwise a kit block as in the
    # teams json, files relative to the team's folder (see CUSTOM_KIT_FILES):
    # {"frontKitFile": "kits/x_front.png", "backKitFile": "kits/x_back/x_back_%.png",
    #  "previewFile": "kits/x_preview.png"}
    "home": {"team_id": "", "season": "", "variant": "", "kit": "home", "kit_variant": "",
             "squad": None, "custom_kit": None},
    "away": {"team_id": "", "season": "", "variant": "", "kit": "away", "kit_variant": "",
             "squad": None, "custom_kit": None},
    "stadium_id": "",           # key in stadiums.json; "" = default stadium
    # Competition textures (tournament logo, stadium graphics, pitch logo,
    # ball): a competition_branding choice key, e.g. "world_cup:2007";
    # None = the home team's own.
    "branding": None,
    "difficulty": "elite",
    "halftime_length": "5m",
    "home_team_side": "left",
    "kick_off": "home",         # side kicking off / in possession at the restart
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
    # Where the restart is taken, for a challenge without its own mission_nis
    # (see restart_nis): {"metres_out": metres from the goal line the side in
    # possession attacks, "across": metres from the middle of the pitch, + to
    # the right as that side faces the posts, "offender": jersey of the
    # player penalised (PEN K)}. None = the restart scene's own spot.
    "restart_spot": None,
    "score_events": [],
    # Cards given by the referee (reR08 ENABLE_CARDS, .mis <EVENTS><CARD>):
    # [{"team": "home", "jersey": 12, "type": "yellow", "minute": 46}]
    "cards": [],
    "objectives": [],           # .mis <OBJECTIVES> (the game's own, not read back)
    # What the player must also do to win the challenge, judged by the mod
    # from the match events (see app/challenge_objectives.py).
    "match_objectives": [],
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
    "environment": "environment",
    "pitch_texture": "pitch",
    "precip_mode": "precipitation",
    "kick_assist": "easy goal kick",
}
# Always left to the player, whatever `user_choice` says: the challenge's own
# value is only the starting pick.
ALWAYS_CHOOSABLE = ("difficulty", "halftime_length")

# Points per score event (gsv.score_event_types).
SCORE_POINTS = {"SS_TRY": 5, "SS_CONVERSION": 2, "SS_PENALTY": 3, "SS_DROPGOAL": 3}


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
    # Files from before sides and kick-off were fixed may still say "random".
    if out["home_team_side"] not in SIDES:
        out["home_team_side"] = DEFAULTS["home_team_side"]
    if out["kick_off"] not in KICK_OFFS:
        out["kick_off"] = DEFAULTS["kick_off"]
    out["user_choice"] = [k for k in out.get("user_choice") or [] if k in CHOOSABLE]
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


# The kit fields (teams json naming) a custom_kit may set.
CUSTOM_KIT_FILES = ("frontKitFile", "backKitFile", "previewFile")


def custom_kit(data: dict, side: str) -> dict:
    """{kit field: path relative to the team folder, as in the teams json}
    the challenge's own kit for `side` replaces ({} when it wears the picked
    kit). A field left out keeps the picked kit's file."""
    spec = data[side].get("custom_kit")
    if not isinstance(spec, dict):
        return {}
    return {k: str(v) for k, v in spec.items() if k in CUSTOM_KIT_FILES and v}


def _custom_kit_missing(ds, data: dict, side: str) -> list:
    root = ds.teams_folder_path.get(data[side]["team_id"], "")
    out = []
    for rel in custom_kit(data, side).values():
        path = os.path.join(root, rel)
        # a back pattern needs at least one shirt-number file
        found = (any(os.path.isfile(path.replace("%", str(n))) for n in range(1, 23))
                 if "%" in path else os.path.isfile(path))
        if not found:
            out.append(rel)
    return out


def custom_squad(data: dict, side: str):
    """The hand-picked squad of `side`, or None when it plays the team's own."""
    squad = data[side].get("squad")
    return squad if isinstance(squad, dict) and squad.get("players") else None


def side_lineup(ds, data: dict, side: str) -> dict:
    """{"players_id", "roles", "set_plays"} `side` plays with: its custom squad
    when it has one, else the team's squad for the chosen variant. Roles the
    custom squad leaves out fall back to the team's, if that player is in it."""
    spec = data[side]
    base = ds.get_lineup(spec["team_id"], spec["season"], spec.get("variant", ""))
    squad = custom_squad(data, side)
    if squad is None:
        return base
    ids = [str(p) for p in squad["players"]]
    roles = {k: str(v) for k, v in (squad.get("roles") or {}).items() if v not in (None, "")}
    for key, pid in (base.get("roles") or {}).items():
        roles.setdefault(key, str(pid) if str(pid) in ids else "")
    return {"players_id": ids, "roles": roles,
            "set_plays": dict(squad.get("set_plays") or base.get("set_plays") or {})}


def squad_pool(ds, data: dict, side: str) -> dict:
    """{player_id: player} the squad editor may pick from: the team's squad in
    every variant of the season, plus whoever the custom squad already holds."""
    spec = data[side]
    ids = []
    for variant in [""] + list(ds.variants_of(spec["team_id"], spec["season"])):
        ids += [str(p) for p in ds.get_lineup(spec["team_id"], spec["season"], variant)
                .get("players_id", []) if p]
    squad = custom_squad(data, side)
    if squad:
        ids += [str(p) for p in squad["players"] if p]
    return ds.get_players(list(dict.fromkeys(ids)), spec["season"])


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
        squad = custom_squad(data, side)
        if squad:
            missing = [str(p) for p in squad["players"] if str(p) not in ds.players]
            if missing:
                found.append(f"{side} squad has unknown player(s) {', '.join(missing)}")
        missing_kit = _custom_kit_missing(ds, data, side)
        if missing_kit:
            found.append(f"{side} custom kit file(s) not found: {', '.join(missing_kit)}")
    if data["stadium_id"] and data["stadium_id"] not in ds.stadiums:
        found.append(f"stadium {data['stadium_id']} is not in the data")
    if data.get("branding") and not competition_branding.resolve(ds, data["branding"])[0]:
        found.append(f"competition textures {data['branding']} are not in the data")
    return found


def _nis(script_name, controller=0, team="home", player=0, x=None, z=None):
    # Same shape as the stock missions' restart NIS (team is "home" in all
    # but one of them; no position = the scene's own default spot).
    return {"script_name": script_name, "controller": controller, "team": team,
            "player": player, "angle": None, "x": x, "y": None, "z": z}


# Pitch frame of the NIS x/z (reR08 findings 2026-07-11-22m-lineout-rule-plan:
# X lateral, touchlines at |x| ~33.6; Z longitudinal, goal lines at |z| 50).
TRY_LINE_Z = 50.0
TOUCHLINE_X = 33.0
# World Z sign of the goal the HOME side attacks in the first half with the
# stock ends (.mis side="right"); reR08 ENABLE_SIDE mirrors the ends for
# side="left", and they swap every period. From the stock missions' restart
# spots (home in possession sits at z < 0 in 7 of the 10 period-0/1 scrums,
# lineouts and penalties) — not yet checked in-game: if a penalty challenge
# starts in the wrong half, flip this.
HOME_ATTACKS_Z_FIRST_HALF = -1


def attack_sign(side: str, home_team_side: str, period) -> int:
    """World Z sign (+1/-1) of the goal `side` attacks during `period`."""
    sign = HOME_ATTACKS_Z_FIRST_HALF
    if home_team_side == "left":
        sign = -sign
    if int(period or 0) % 2:
        sign = -sign
    return sign if side == "home" else -sign


def restart_xz(data: dict, kicker: str):
    """(x, z) of the challenge's restart_spot for the side in possession,
    or (None, None) when it has none."""
    spot = data.get("restart_spot")
    if not isinstance(spot, dict) or spot.get("metres_out") is None:
        return None, None
    sign = attack_sign(kicker, data["home_team_side"], data.get("mission_mode_period"))
    out = min(max(float(spot["metres_out"]), 0.0), 2 * TRY_LINE_Z)
    across = min(max(float(spot.get("across") or 0), -TOUCHLINE_X), TOUCHLINE_X)
    # Facing the +Z goal, +X is on the right (Direct3D left-handed frame).
    return round(sign * across, 1), round(sign * (TRY_LINE_Z - out), 1)


def start_state(data: dict, kicker: str):
    """(mode name, NIS list) the .mis starts on. A challenge's own
    `mission_nis` is kept as is. Without one, the restart scene stock
    missions pair with the mode is added — otherwise the game plays its
    default intro (teams walking out / a kick-off) whatever the mode says:
      mid-match KICK OFF -> MODE name="" + NIS kick_off (stock 2003_match_7)
      PEN K              -> NIS penalty_general_TeamA/B (stock 1987_match_6)
      LINE OUT           -> NIS lineout01_teama/b       (stock 1987_match_7…)
    `kicker` is the side in possession (MODE offensiveteam). The penalty
    scene is named after the side PENALISED: both stock missions that use it
    pair penalty_general_TeamA (team="home") with offensiveteam="away". With
    a restart_spot the penalty is written like 1987_match_6, the one stock
    penalty placed on the pitch: controller 7, team = penalised side, player =
    offender's jersey, x/z = the mark."""
    name = data.get("mission_mode_name") or ""
    authored = copy.deepcopy(data.get("mission_nis") or [])
    if authored:
        return name, authored
    other = "away" if kicker == "home" else "home"
    x, z = restart_xz(data, kicker)
    if name == "KICK OFF" and data.get("mission_mode_time"):
        return "", [_nis("kick_off")]
    if name == "PEN K":
        script = f"penalty_general_Team{'A' if other == 'home' else 'B'}"
        if z is None:
            return name, [_nis(script)]
        offender = int((data.get("restart_spot") or {}).get("offender") or 0)
        return name, [_nis(script, controller=7, team=other, player=offender, x=x, z=z)]
    if name == "LINE OUT":
        # A lineout is on the touchline: only how far up the pitch counts.
        return name, [_nis(f"lineout01_team{'a' if kicker == 'home' else 'b'}", z=z)]
    return name, []


def to_match_config(ds, data: dict) -> MatchConfig:
    """The MatchConfig that plays this challenge. The player's controller is
    the keyboard, on `user_side`."""
    cfg = MatchConfig()
    for side, slot in (("home", cfg.home), ("away", cfg.away)):
        spec = data[side]
        slot.team_id, slot.season = spec["team_id"], spec["season"]
        slot.variant = spec.get("variant", "") if spec.get("variant", "") in \
            ds.variants_of(slot.team_id, slot.season) else ""
        info = slot.info(ds)
        kit_keys = list(info.get("kits", {}))
        slot.kit_index = kit_keys.index(spec["kit"]) if spec["kit"] in kit_keys else 0
        slot.kit_variant = spec.get("kit_variant", "")
        slot.kit_override = custom_kit(data, side)
        slot.lineup = side_lineup(ds, data, side)
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
    # Wind is fixed by the challenge file (band 0..10): no strength set means
    # calm, never the game's random stock wind.
    cfg.wind_power = int(data["wind_power"] or 0)
    cfg.wind_dir_deg = float(data["wind_dir_deg"] or 0)
    # Settings > Wind: Standard ignores the file and leaves the game's own
    # random wind (None).
    if user_prefs.wind_mode != "advanced":
        cfg.wind_power = None
    cfg.mission_mode_name, cfg.mission_nis = start_state(data, cfg.kick_off)
    # The JSON names the scorer by shirt (1-15); the .mis counts from 0.
    cfg.score_events = [dict(ev, player=max(0, int(ev.get("player") or 0) - 1))
                        for ev in copy.deepcopy(data["score_events"])]
    cfg.cards = copy.deepcopy(data.get("cards") or [])
    cfg.objectives = copy.deepcopy(data["objectives"])
    cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": data["user_side"]}}
    # Quick match's pickers default to the "default" competition (pitch logo,
    # tournament logo, stadium graphics = the advertising boards); a bare
    # MatchConfig leaves them unset ("none" pitch logo, the home team's own
    # pads), so a challenge without branding showed neither. Lay the default
    # down first, then the chosen competition over it: a season lacking a
    # texture (WC 2007 has no pitch logo) keeps the default's.
    competition_branding.apply(ds, cfg, "default")
    if data.get("branding"):
        competition_branding.apply(ds, cfg, data["branding"])
    # A World Cup challenge left on "stock" gets the World Cup stadium
    # dressing (roof flags, IRB/RWC banners; reR08 ENABLE_STADIUM_FLAGS —
    # RWC 2007 venues only, a no-op elsewhere). An explicit false is kept.
    if cfg.stadium_flags is None and cfg.match_type == "world_cup":
        cfg.stadium_flags = True
    return cfg


def is_choice(data: dict, key: str) -> bool:
    return key in ALWAYS_CHOOSABLE or key in (data.get("user_choice") or [])


def start_score(data: dict):
    """(home points, away points) the challenge starts on."""
    pts = {"home": 0, "away": 0}
    for event in data.get("score_events") or []:
        if event.get("team") in pts:
            pts[event["team"]] += SCORE_POINTS.get(event.get("type"), 0)
    return pts["home"], pts["away"]


def start_minute(data: dict):
    """Match minute the challenge starts at, or None for a kick-off start."""
    t = data.get("mission_mode_time")
    return int(t) // 60 if t else None


def _kits(ds, data, side):
    slot = data[side]
    return list(ds.team_season(slot["team_id"], slot["season"], slot.get("variant", ""))
                .get("kits", {}))


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
        info = ds.team_season(slot["team_id"], slot["season"], slot.get("variant", ""))
        return info.get("name") or slot["team_id"] or "?"
    half = "your pick of half length" if is_choice(data, "halftime_length") \
        else f"{data['halftime_length']} halves"
    level = "your pick of difficulty" if is_choice(data, "difficulty") else data["difficulty"]
    return f"{team('home')} v {team('away')} · {half} · {level}"


def shirt_names(ds, data: dict) -> dict:
    """{side: {shirt number: player name}} as the challenge lines up."""
    out = {}
    for side in ("home", "away"):
        ids = side_lineup(ds, data, side).get("players_id", [])
        out[side] = {i + 1: (ds.players.get(str(pid), {}).get("display_name") or str(pid))
                     for i, pid in enumerate(ids) if pid}
    return out


def team_names(ds, data: dict) -> dict:
    return {side: ds.team_season(data[side]["team_id"], data[side]["season"],
                                 data[side].get("variant", "")).get("name") or side
            for side in ("home", "away")}


def objective_lines(ds, data: dict) -> list:
    """The challenge's match objectives, one line each, win first."""
    from app import challenge_objectives as co
    names, teams = shirt_names(ds, data), team_names(ds, data)
    return ["Win the match"] + [co.describe(o, names, teams, data["user_side"])
                                for o in data.get("match_objectives") or []]
