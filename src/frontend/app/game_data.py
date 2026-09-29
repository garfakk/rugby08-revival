"""
app/game_data.py — what the game actually accepts, and how to write it back
==============================================================================
The editors need two things this module owns:

  * the vocabularies the ROSTER FILE understands. These are not conventions —
    backend/game_files_processor.py looks each value up in
    backend/game_specific_variables.py and silently substitutes 0 / a default
    for anything it doesn't recognise, so a plausible-looking value that isn't
    on these lists is data loss with no error. They are duplicated here rather
    than imported because `frontend/` must not depend on `backend/`;
    `check_player` exists to catch them drifting apart.

  * a save path that cannot lose the file it is editing. Records are written
    back into the file they were LOADED from (several files can define the
    same ids — see TeamDataLoader), the rest of that file is preserved
    untouched, unknown keys on the edited record survive, and the write is
    atomic with a one-time .bak of the original.

Formatting matches what the mod data already ships: json.dump(indent=1),
UTF-8, unescaped non-ASCII — so a save produces a minimal diff rather than
reformatting the whole file.
"""
import json
import os
import shutil
from datetime import datetime

# UI range for reR08 ENABLE_WIND's extended wind-power bands.
WIND_POWER_MAX = 10
# UI range for reR08 ENABLE_SNOWFX's intensity levels.
SNOW_INTENSITY_MAX = 26.0

# ── Vocabularies the roster file understands ─────────────────────────────
# backend/game_specific_variables.py::positions_id. The game draws no
# distinction between loosehead/tighthead or blindside/openside, but the
# roster file still stores the specific value, and the generic "prop",
# "flanker", "lock" and "wing" that appear in the mod's own data are NOT
# among them: they resolve to 0, i.e. "no position".
POSITIONS = [
    "loosehead_prop", "hooker", "tighthead_prop", "second_row",
    "blindside_flanker", "openside_flanker", "number_eight", "scrum_half",
    "fly_half", "winger", "centre", "fullback",
]

# What a generic/legacy position most likely meant, offered as the fix.
POSITION_ALIASES = {
    "prop": "loosehead_prop",
    "flanker": "openside_flanker",
    "lock": "second_row",
    "second_rower": "second_row",
    "secondrow": "second_row",
    "wing": "winger",
    "left_wing": "winger",
    "right_wing": "winger",
    "left_winger": "winger",
    "right_winger": "winger",
    "center": "centre",
    "inside_center": "centre",
    "inside_centre": "centre",
    "outside_center": "centre",
    "outside_centre": "centre",
    "full_back": "fullback",
    "number_8": "number_eight",
    "no8": "number_eight",
    "eighthman": "number_eight",
    "scrumhalf": "scrum_half",
    "flyhalf": "fly_half",
    "fly-half": "fly_half",
}


def normalise_position(value: str) -> str:
    """Return the roster vocabulary for a player-data position value."""
    key = str(value or "").strip().lower().replace(" ", "_")
    return POSITION_ALIASES.get(key, key)

# The shirt each position wears, which is what makes a squad list readable as
# a team sheet: entry 0 of a squad is shirt 1 and must be a prop, entry 14 is
# shirt 15 and must be the full-back. backend/game_files_processor.py writes
# the array in list order and resolves roles as players_id[position - 1], so
# this ordering is the game's, not a display convention.
SHIRT_POSITIONS = {
    1: "loosehead_prop", 2: "hooker", 3: "tighthead_prop", 4: "second_row",
    5: "second_row", 6: "blindside_flanker", 7: "openside_flanker",
    8: "number_eight", 9: "scrum_half", 10: "fly_half", 11: "winger",
    12: "centre", 13: "centre", 14: "winger", 15: "fullback",
}

# Where a player of each position belongs in shirt order, used to tell a
# squad that is merely unsorted from one that is stored back-to-front.
POSITION_SHIRT_RANK = {
    "loosehead_prop": 1, "hooker": 2, "tighthead_prop": 3, "second_row": 4.5,
    "lock": 4.5, "blindside_flanker": 6, "openside_flanker": 7, "flanker": 6.5,
    "number_eight": 8, "scrum_half": 9, "fly_half": 10, "winger": 12.5,
    "wing": 12.5, "centre": 12.5, "inside_centre": 12, "outside_centre": 13,
    "fullback": 15, "full_back": 15, "prop": 2,
}

SKIN_TONES = ["light", "l_medium", "d_medium", "dark"]
TAPES = ["none", "left", "right", "both"]
FEET = ["right_footed", "left_footed"]
SOCKS = ["down", "up"]
BOOT_STYLES = [str(i) for i in range(10)]     # backend: boot_style_id = range(0, 10)
SET_PLAYS = ["classic", "pivot", "pocket", "dummy_switch",
             "miss", "cross_kick", "loop", "miss_pivot"]
TEAM_TYPES = ["club", "international"]     # what the data ships; the game ignores it
TEAM_TYPE_ALIASES = {"national": "international"}
ROLE_KEYS = ["captain", "viceCaptain", "longGK", "shortGK",
             "longPunt", "shortPunt", "kickoff"]
SET_PLAY_KEYS = ["up", "down", "left", "right"]

# The 24 rated attributes, in roster-file order, as (json key, label).
ATTRIBUTES = [
    ("attack", "Attack"), ("defense", "Defence"), ("speed", "Speed"),
    ("acceleration", "Acceleration"), ("agility", "Agility"),
    ("handling", "Handling"), ("passing", "Passing"), ("kicking", "Kicking"),
    ("kicking_power", "Kicking power"), ("goal_kicking", "Goal kicking"),
    ("tackling", "Tackling"), ("strength", "Strength"), ("rucking", "Rucking"),
    ("scrummaging", "Scrummaging"), ("hooking", "Hooking"), ("lineout", "Line-out"),
    ("discipline", "Discipline"), ("aggression", "Aggression"),
    ("stamina", "Stamina"), ("consitance", "Consistency"),
    ("temperament", "Temperament"), ("creativity", "Creativity"),
    ("bravery", "Bravery"), ("fitness", "Fitness"),
]

# Per-season keys that are not rated attributes.
APPEARANCE_KEYS = [
    "position1", "position2", "position3", "nationality", "height", "weight",
    "skin_tone", "skin", "skin_overlay", "face", "foot", "headgear", "boot_style", "socks",
    "gloves", "wrist_tape", "tight_tape", "finger_tape",
]

IDENTITY_KEYS = ["display_name", "first_name", "last_name", "birthdate", "commentary"]


def new_player_season() -> dict:
    """A blank season block carrying every key the loader/back end expects,
    so a newly added season isn't missing fields the roster writer reads."""
    season = {key: "50" for key, _ in ATTRIBUTES}
    season.update({k: "" for k in APPEARANCE_KEYS})
    season["position1"] = "centre"
    season["skin_tone"] = "light"
    season["foot"] = "right_footed"
    season["socks"] = "down"
    season["boot_style"] = "0"
    season["skin_overlay"] = []
    return season


# ── Validation ───────────────────────────────────────────────────────────
# Severity: "error" = the game misreads it or the match breaks; "warn" = the
# game silently substitutes something; "info" = worth knowing, harmless.
ERROR, WARN_, INFO_ = "error", "warn", "info"


def check_player_detailed(record: dict, season: str, mod_dir: str = None) -> list:
    """[(field_key, message, severity)] for everything the game would silently
    drop or substitute. Empty optional fields are fine — the back end defaults
    them — so only values that are set AND unrecognised are reported.
    With `mod_dir`, appearance images (skin, layers, gloves, boots) are also
    checked on disk."""
    problems = []
    stats = (record.get("stats") or {}).get(season) or {}

    for key in ("position1", "position2", "position3"):
        value = (stats.get(key) or "").strip()
        if not value:
            continue
        if value not in POSITIONS:
            fix = POSITION_ALIASES.get(value)
            hint = f" — did you mean {fix.replace('_', ' ')}?" if fix else ""
            problems.append((key, f"'{value}' is not a roster position, the game reads 0{hint}", ERROR))

    if not (stats.get("position1") or "").strip():
        problems.append(("position1", "no primary position", ERROR))

    problems += _appearance_problems(stats, mod_dir)

    for key in ("wrist_tape", "tight_tape", "finger_tape"):
        value = (stats.get(key) or "").strip()
        if value and value not in TAPES:
            problems.append((key, f"'{value}' is not a tape value", WARN_))

    foot = (stats.get("foot") or "").strip().lower()
    if foot and "left" not in foot and "right" not in foot:
        problems.append(("foot", f"'{foot}' reads as neither left nor right", WARN_))


    height = (stats.get("height") or "").strip()
    if height and not height.isdigit():
        problems.append(("height", f"'{height}' is not a number", ERROR))
    elif height and int(height) < 151:
        problems.append(("height", f"{height} cm is below 151 — the roster write fails", ERROR))
    weight = (stats.get("weight") or "").strip()
    if weight and not weight.isdigit():
        problems.append(("weight", f"'{weight}' is not a number", ERROR))

    for key in [k for k, _ in ATTRIBUTES] + ["crashball", "gap_defense"]:
        value = (stats.get(key) or "").strip()
        if value and (not value.isdigit() or int(value) > 99):
            problems.append((key, f"'{value}' is not a rating between 0 and 99", ERROR))

    name = (record.get("display_name") or "").strip()
    if not name:
        problems.append(("display_name", "no display name — the game shows 'Unknown'", WARN_))
    elif len(name.encode("utf-8")) > 14:
        problems.append(("display_name",
                         f"{len(name.encode('utf-8'))} bytes — the game cuts names at 14", WARN_))

    birthdate = (record.get("birthdate") or "").strip()
    if birthdate:
        try:
            datetime.strptime(birthdate, "%Y/%m/%d")
        except ValueError:
            problems.append(("birthdate", f"'{birthdate}' is not a YYYY/MM/DD date", WARN_))

    ability = str(stats.get("special_ability", "") or "").strip()
    if ability and (not ability.isdigit() or int(ability) > 10):
        problems.append(("special_ability", f"'{ability}' is not a tendency (0-10)", WARN_))

    commentary = (record.get("commentary") or "").strip()
    if commentary and not commentary.isdigit():
        problems.append(("commentary", f"'{commentary}' is not a number — read as 0", WARN_))

    return problems


def _appearance_problems(stats: dict, mod_dir: str = None) -> list:
    from app import appearance as A
    out = []
    tone = str(stats.get("skin_tone") or "").strip()
    named = A.normalize_tone(tone)
    if tone and named is None:
        out.append(("skin_tone", f"'{tone}' is not a skin tone — falls back to light", WARN_))
    elif tone and tone != named:
        pretty = {"l_medium": "light-medium", "d_medium": "dark-medium"}.get(named, named)
        out.append(("skin_tone", f"skin tone stored as index '{tone}' = {pretty}", INFO_))

    skin = stats.get("skin", "")
    if skin and not isinstance(skin, str):
        out.append(("skin", "custom skin must be an image path", ERROR))
    elif skin and A.normalize_tone(skin) is None and mod_dir:
        out += [("skin", m, sev) for m, sev in A.asset_problems(mod_dir, skin, "skin")]

    raw_layers = stats.get("skin_overlay", [])
    if raw_layers not in ("", None, False, []) and not isinstance(raw_layers, list):
        out.append(("skin_overlay", "skin layers should be a list of image paths", INFO_))
    if mod_dir:
        for i, rel in enumerate(A.overlay_list(raw_layers)):
            out += [(f"skin_overlay.{i}", m, sev) for m, sev in A.asset_problems(mod_dir, rel, "layer")]

    gloves = stats.get("gloves", "")
    kind = A.gloves_kind(gloves)
    if kind == "invalid":
        out.append(("gloves", f"'{gloves}' is neither yes/blank nor an image — the game "
                              "shows a placeholder skin", WARN_))
    elif kind == "image" and mod_dir:
        out += [("gloves", m, sev) for m, sev in A.asset_problems(mod_dir, gloves, "gloves")]

    boot = str(stats.get("boot_style") or "").strip()
    bkind = A.boot_kind(boot)
    if bkind == "invalid":
        what = f"style {boot} is outside 0-9" if boot.isdigit() else \
            f"'{boot}' is neither a style number nor an image"
        out.append(("boot_style", f"{what} — the game uses style 0", WARN_))
    elif bkind == "image" and mod_dir:
        out += [("boot_style", m, sev) for m, sev in A.asset_problems(mod_dir, boot, "boots")]
    return out


def check_player(record: dict, season: str) -> list:
    return [(k, m) for k, m, _ in check_player_detailed(record, season)]


def player_position(player: dict, season: str = None) -> str:
    """position1 for `season`, falling back to whatever season the player
    does have — squads routinely reference a season the player predates."""
    stats = player.get("stats") or {}
    block = stats.get(season) if season else None
    if block is None:
        block = stats.get(sorted(stats)[-1]) if stats else {}
    return (block or {}).get("position1", "") or ""


def looks_reversed(roster: list, players: dict, season: str = None) -> bool:
    """True when a squad is stored back-to-front — the front row at the end
    of the list instead of the start.

    Worth detecting rather than just sorting blind: the array IS the shirt
    assignment, so a reversed file quietly fields a full-back at 1 and a
    prop at 15 without anything failing loudly."""
    ranked = []
    for index, pid in enumerate(roster[:15]):
        rank = POSITION_SHIRT_RANK.get(player_position(players.get(str(pid), {}), season))
        if rank is not None:
            ranked.append((index, rank))
    if len(ranked) < 6:
        return False
    half = len(ranked) // 2
    front = sum(r for _, r in ranked[:half]) / half
    back = sum(r for _, r in ranked[-half:]) / half
    # A correctly ordered squad climbs from props (1) to full-back (15); a
    # reversed one falls. Require a real gap so a merely scrappy order — the
    # normal case — isn't reported as reversed.
    return front - back > 3


SQUAD_SIZE = 22
STARTING_XV = 15


def check_team_detailed(season_info: dict, players: dict, season: str = None) -> list:
    """[(field_key, message, severity)] for a single season of a team.
    Keys point at the control that shows the problem: `players.<index>`
    for a squad slot, `roles.<key>`, `setPlays.<key>`, `kits`."""
    problems = []
    roster = [str(pid) for pid in season_info.get("players", [])]

    if not (season_info.get("name") or "").strip():
        problems.append(("name", "no team name", ERROR))

    seen = {}
    for index, pid in enumerate(roster):
        if pid in seen:
            problems.append((f"players.{index}",
                             f"shirt {index + 1}: player {pid} already wears {seen[pid] + 1}", ERROR))
        else:
            seen[pid] = index
        if pid not in players:
            problems.append((f"players.{index}",
                             f"shirt {index + 1}: player {pid} is not in the player files", ERROR))

    if len(roster) < SQUAD_SIZE:
        problems.append(("players", f"{len(roster)} players — the game needs 22 or the"
                                    f" squad is not written", ERROR))

    if looks_reversed(roster, players, season):
        problems.append(("players",
                         "squad looks back-to-front — shirt 1 is a back and the "
                         "front row is at the end of the list", WARN_))

    starters = roster[:STARTING_XV]
    for key in ROLE_KEYS:
        value = str((season_info.get("roles") or {}).get(key, "") or "").strip()
        if not value:
            problems.append((f"roles.{key}", f"{key} is unset — the game uses shirt 10", WARN_))
        elif value not in starters:
            problems.append((f"roles.{key}",
                             f"{key} is not in the starting XV — the game uses shirt 10", WARN_))

    for key, value in (season_info.get("setPlays") or {}).items():
        if value and value not in SET_PLAYS:
            problems.append((f"setPlays.{key}", f"{key}: '{value}' is not a set play", ERROR))

    if not (season_info.get("kits") or {}):
        problems.append(("kits", "no kits — match setup has nothing to dress the team in", ERROR))

    team_type = season_info.get("type", "")
    if team_type and team_type not in TEAM_TYPES:
        problems.append(("type", f"'{team_type}' is not club or international (unused by the game)",
                         INFO_))

    return problems


def check_team(season_info: dict, players: dict, season: str = None) -> list:
    return [(k, m) for k, m, _ in check_team_detailed(season_info, players, season)]


# ── Blank records ────────────────────────────────────────────────────────
def blank_kit() -> dict:
    return {"frontKitFile": "", "backKitFile": "", "previewFile": "", "color": ""}


def new_team_season(name="", team_type="club", category="") -> dict:
    """A season block carrying every key a real team file has, so a new
    season is indistinguishable in shape from a shipped one."""
    return {
        "name": name, "type": team_type, "category": category,
        "ball": "", "banners": "", "pads": "",
        "logos": {"main": "", "small": "", "left": "", "right": ""},
        "kits": {"home": blank_kit(), "away": blank_kit()},
        "roles": {k: "" for k in ROLE_KEYS},
        "setPlays": {k: "" for k in ("left", "up", "right", "down")},
        "players": [],
    }


# ── Asset specs — what each team asset path points at ───────────────────
# frames: count substituted for "%" in a pattern path; size: expected pixels.
ASSET_SPECS = {
    "ball":         {"frames": 2, "size": (256, 128), "ext": (".png", ".fsh"),
                     "note": ""},
    "banners":      {"frames": 4, "size": (512, 128), "ext": (".png", ".fsh"),
                     "note": ""},
    "pads":         {"frames": 0, "size": None, "ext": (".fsh",),
                     "note": ""},
    "logos.main":   {"frames": 0, "size": (256, 256), "ext": (".png",),
                     "note": ""},
    "logos.small":  {"frames": 0, "size": (128, 64), "ext": (".png",), "note": ""},
    "logos.left":   {"frames": 0, "size": (128, 64), "ext": (".png",), "note": ""},
    "logos.right":  {"frames": 0, "size": (128, 64), "ext": (".png",), "note": ""},
    "frontKitFile": {"frames": 0, "size": (1024, 1024), "ext": (".png", ".big"),
                     "note": ""},
    "backKitFile":  {"frames": 22, "size": (1024, 1024), "ext": (".png", ".fsh"),
                     "note": ""},
    "previewFile":  {"frames": 0, "size": None, "ext": (".png",),
                     "note": ""},
}


# ── Saving ───────────────────────────────────────────────────────────────
class SaveError(Exception):
    pass


def _write_json(path: str, data) -> None:
    """Atomic, and never the first thing to touch the original: the .bak is
    taken before the replace, and only once — a second save would otherwise
    overwrite the backup with the already-edited file, which is exactly when
    the user needs the original."""
    backup = path + ".bak"
    try:
        if os.path.exists(path) and not os.path.exists(backup):
            shutil.copy2(path, backup)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        raise SaveError(str(e)) from e


def _load_json(path: str):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError) as e:
        raise SaveError(f"{os.path.basename(path)}: {e}") from e


def save_player(path: str, pid: str, record: dict) -> str:
    """Write one player back into `path`, leaving every other player in that
    file exactly as it was. Re-reads the file first, so edits made elsewhere
    since startup aren't clobbered by our in-memory copy."""
    if not path:
        raise SaveError("no source file recorded for this player")
    data = _load_json(path)
    if isinstance(data, list):
        raise SaveError(f"{os.path.basename(path)} is a list, not a player map")
    data[str(pid)] = record
    _write_json(path, data)
    return path


def create_json_file(path: str, data) -> str:
    """Write a brand-new file. Refuses to overwrite: creating a record must
    never be a way to lose an existing one."""
    if os.path.exists(path):
        raise SaveError(f"{os.path.basename(path)} already exists")
    try:
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, path)
    except OSError as e:
        raise SaveError(str(e)) from e
    return path


def soft_delete_file(path: str) -> str:
    """Rename rather than remove, so a deleted team can be recovered by hand.
    The loader only reads <folder>.json, so the renamed file is ignored."""
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    target = f"{path}.deleted-{stamp}"
    try:
        os.replace(path, target)
    except OSError as e:
        raise SaveError(str(e)) from e
    return target


def delete_player(path: str, pid: str) -> str:
    data = _load_json(path)
    if isinstance(data, list):
        raise SaveError(f"{os.path.basename(path)} is a list, not a player map")
    if str(pid) in data:
        del data[str(pid)]
        _write_json(path, data)
    return path


def add_player(path: str, pid: str, record: dict) -> str:
    data = _load_json(path)
    if isinstance(data, list):
        raise SaveError(f"{os.path.basename(path)} is a list, not a player map")
    if str(pid) in data:
        raise SaveError(f"player {pid} already exists in {os.path.basename(path)}")
    data[str(pid)] = record
    _write_json(path, data)
    return path


def save_team(path: str, team_id: str, seasons: dict) -> str:
    """Write one team's seasons back into `path`. A team file holds a single
    team, but it is written whole so any sibling key survives."""
    if not path:
        raise SaveError("no source file recorded for this team")
    data = _load_json(path)
    data[str(team_id)] = seasons
    _write_json(path, data)
    return path
