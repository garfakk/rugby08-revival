"""
app/match_data_builder.py — MatchConfig -> backend match_data dict
======================================================================
Ported verbatim from the pre-redesign TeamSelectionWidget._build_match_data /
_build_team_match_data / _player_to_match_data (screens/team_selection.py).
Only the source of truth changed — from QComboBox state to MatchConfig/
DataStore — the ~60 per-player field mappings and asset %-pattern handling
are untouched, per the migration plan's "preserve, do not rewrite blind".
"""
import math
import os
import random

from backend import game_specific_variables as gsv
from shared.config import config
from app import appearance
from app.game_data import normalise_position
from app.state import DataStore, MatchConfig, TeamSlot


from shared.log import get_logger

log = get_logger(__name__)


def _relative_to_mod_data(path: str) -> str:
    if not path:
        return ""
    if not os.path.isabs(path):
        return path.replace("\\", "/")
    return os.path.relpath(path, config.mod_data_directory).replace("\\", "/")


def _team_asset_path(ds: DataStore, team_id: str, relative_path: str) -> str:
    if not relative_path:
        return ""
    team_root = ds.teams_folder_path.get(team_id, "")
    return _relative_to_mod_data(os.path.join(team_root, relative_path))


def _tournament_asset_path(ds: DataStore, tournament_id, relative_path: str) -> str:
    if not tournament_id or not relative_path:
        return ""
    folder = ds.tournaments_folder_path.get(tournament_id, "")
    return _relative_to_mod_data(os.path.join(folder, relative_path))


def _selected_kit_data(ds: DataStore, slot: TeamSlot) -> dict:
    kits = list(ds.teams[slot.team_id][slot.season].get("kits", {}).values())
    if not kits:
        return {}
    return kits[slot.kit_index % len(kits)]


def _appearance_to_match_data(player: dict):
    """(skin, skin_overlay, gloves, boot_style) as the backend expects them.
    Only files that exist are handed over — a missing custom texture would
    otherwise leave the player on an empty custom slot — see app/appearance."""
    mod_dir = config.mod_data_directory
    name = player.get("display_name", "?")
    tone = appearance.normalize_tone(player.get("skin_tone")) or "light"

    skin = str(player.get("skin") or "").strip()
    if skin and appearance.normalize_tone(skin):
        skin = appearance.normalize_tone(skin)
    elif skin and not appearance.exists(mod_dir, skin):
        log.warning(f"{name}: skin image {skin} not found, using {tone}")
        skin = ""
    skin = skin.replace("\\", "/") if skin else tone

    layers = []
    for rel in appearance.overlay_list(player.get("skin_overlay")):
        if appearance.exists(mod_dir, rel):
            layers.append(rel.replace("\\", "/"))
        else:
            log.warning(f"{name}: skin layer {rel} not found, skipped")

    raw_gloves = player.get("gloves", "")
    kind = appearance.gloves_kind(raw_gloves)
    if kind == "image" and appearance.exists(mod_dir, raw_gloves):
        gloves = str(raw_gloves).replace("\\", "/")
    else:
        if kind == "image":
            log.warning(f"{name}: gloves image {raw_gloves} not found, using stock gloves")
        gloves = kind in ("stock", "image")

    raw_boot = str(player.get("boot_style", "") or "").strip()
    bkind = appearance.boot_kind(raw_boot)
    if bkind == "stock":
        boot = int(raw_boot) if raw_boot else 0
    elif bkind == "image" and appearance.exists(mod_dir, raw_boot):
        boot = raw_boot.replace("\\", "/")
    else:
        log.warning(f"{name}: boot style {raw_boot!r} unusable, using style 0")
        boot = 0
    return skin, (layers or False), gloves, boot


def _player_to_match_data(player: dict) -> dict:
    birthdate = str(player.get("birthdate", ""))
    age = 24
    if len(birthdate) >= 4 and birthdate[:4].isdigit():
        age = max(16, 2026 - int(birthdate[:4]))

    face_value = player.get("face", "")
    if isinstance(face_value, str) and face_value.isdigit():
        face_value = int(face_value)

    foot = str(player.get("foot", "right")).lower()
    best_foot = "left" if "left" in foot else "right"

    skin_value, skin_overlay, gloves_value, boot_value = _appearance_to_match_data(player)

    def position_value(key):
        return normalise_position(player.get(key, ""))

    def to_int(value, default=0):
        try:
            return int(value)
        except (TypeError, ValueError):
            return default

    def to_bool(value):
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "on", "up"}

    return {
        "name": player.get("display_name", player.get("name", "Unknown")),
        "commentary": to_int(player.get("commentary", 0), 0),
        "age": age,
        "weight": to_int(player.get("weight", 80), 80),
        "height": to_int(player.get("height", 180), 180),
        "pos1": position_value("position1") or normalise_position(player.get("pos1", "")),
        "pos2": position_value("position2") or normalise_position(player.get("pos2", "")),
        "pos3": position_value("position3") or normalise_position(player.get("pos3", "")),
        "face": face_value,
        "best_foot": best_foot,
        "skin": skin_value,
        "skin_overlay": skin_overlay,
        "headgear": to_int(player.get("headgear", 0), 0),
        "boot_style": boot_value,
        "socks_up": str(player.get("socks", "")).strip().lower() == "up",
        "gloves": gloves_value,
        "wrist_tape": player.get("wrist_tape", "none") or "none",
        "thigh_tape": player.get("thigh_tape", player.get("tight_tape", "none")) or "none",
        "finger_tape": player.get("finger_tape", "none") or "none",
        "special_ability": to_int(player.get("special_ability", 0), 0),
        "goal_kicking_style": str(player.get("goal_kicking_style") or "default"),
        "star_attribute": to_int(player.get("star_attribute", 0), 0),
        "attack": to_int(player.get("attack", 0), 0),
        "defense": to_int(player.get("defense", 0), 0),
        "speed": to_int(player.get("speed", 0), 0),
        "acceleration": to_int(player.get("acceleration", 0), 0),
        "agility": to_int(player.get("agility", 0), 0),
        "handling": to_int(player.get("handling", 0), 0),
        "passing": to_int(player.get("passing", 0), 0),
        "kicking": to_int(player.get("kicking", 0), 0),
        "kicking_power": to_int(player.get("kicking_power", 0), 0),
        "goal_kicking": to_int(player.get("goal_kicking", 0), 0),
        "tackling": to_int(player.get("tackling", 0), 0),
        "strength": to_int(player.get("strength", 0), 0),
        "rucking": to_int(player.get("rucking", 0), 0),
        "scrummaging": to_int(player.get("scrummaging", 0), 0),
        "hooking": to_int(player.get("hooking", 0), 0),
        "line_out": to_int(player.get("lineout", player.get("line_out", 0)), 0),
        "discipline": to_int(player.get("discipline", 0), 0),
        "aggression": to_int(player.get("aggression", 0), 0),
        "stamina": to_int(player.get("stamina", 0), 0),
        "consistency": to_int(player.get("consistency", player.get("consitance", 0)), 0),
        "temperament": to_int(player.get("temperament", 0), 0),
        "creativity": to_int(player.get("creativity", 0), 0),
        "bravery": to_int(player.get("bravery", 0), 0),
        "fitness": to_int(player.get("fitness", 0), 0),
        "crashball": to_int(player.get("crashball", 0), 0),
        "gap_defense": to_int(player.get("gap_defense", 0), 0),
        "ss_command": to_bool(player.get("ss_command", False)),
        "ss_passer": to_bool(player.get("ss_passer", False)),
        "ss_play_maker": to_bool(player.get("ss_play_maker", False)),
        "ss_scoring": to_bool(player.get("ss_scoring", False)),
        "ss_goal_kicker": to_bool(player.get("ss_goal_kicker", False)),
        "ss_tactical_kicking": to_bool(player.get("ss_tactical_kicking", False)),
        "ss_crashball": to_bool(player.get("ss_crashball", False)),
        "ss_tackle_breaker": to_bool(player.get("ss_tackle_breaker", False)),
        "ss_tackling": to_bool(player.get("ss_tackling", False)),
        "ss_ball_winner": to_bool(player.get("ss_ball_winner", False)),
        "ss_defensive_organisation": to_bool(player.get("ss_defensive_organisation", False)),
        "ss_scrummager": to_bool(player.get("ss_scrummager", False)),
        "ss_jumper": to_bool(player.get("ss_jumper", False)),
    }


def _build_team_match_data(ds: DataStore, slot: TeamSlot, is_home: bool) -> dict:
    team_info = ds.teams[slot.team_id][slot.season]
    lineup = slot.lineup or {}
    selected_player_ids = list(lineup.get("players_id", []))[:22]
    selected_players = []

    for player_id in selected_player_ids:
        # A source roster can carry an empty "" slot (a reserve jersey with
        # no valid player behind it) rather than dropping the slot outright
        # — see squad_editor.py's same guard. int("") would otherwise crash
        # kick-off for a team whose squad was never opened/edited first.
        if not player_id:
            continue
        player = slot.players.get(int(player_id))
        if player is None:
            continue
        selected_players.append(_player_to_match_data(player))

    role_key_map = {
        "captain": "captain",
        "viceCaptain": "vice-captain",
        "longGK": "long_GK",
        "shortGK": "short_GK",
        "longPunt": "long_punt",
        "shortPunt": "short_punt",
        "kickoff": "kick_off",
    }
    starting_ids = selected_player_ids[:15]
    roles = {}
    for source_key, target_key in role_key_map.items():
        selected_player_id = lineup.get("roles", {}).get(source_key)
        try:
            roles[target_key] = starting_ids.index(int(selected_player_id)) + 1
        except (ValueError, TypeError):
            roles[target_key] = 10

    set_play_defaults = {"up": "classic", "down": "pivot", "left": "pocket", "right": "dummy_switch"}
    set_play_data = lineup.get("set_plays", {})
    set_plays = [
        set_play_data.get(direction) or set_play_defaults[direction]
        for direction in ("up", "down", "left", "right")
    ]

    selected_kit = _selected_kit_data(ds, slot)
    logos = team_info.get("logos", {})

    return {
        "name": team_info.get("name", "team_A" if is_home else "team_B"),
        "kit_front": _team_asset_path(ds, slot.team_id, selected_kit.get("frontKitFile", "")),
        "kit_back": _team_asset_path(ds, slot.team_id, selected_kit.get("backKitFile", "")),
        "banners": _team_asset_path(ds, slot.team_id, team_info.get("banners", "")),
        "logo": _team_asset_path(ds, slot.team_id, logos.get("main", "")),
        "logo_small": _team_asset_path(ds, slot.team_id, logos.get("small", "")),
        "logo_left": _team_asset_path(ds, slot.team_id, logos.get("left", "")),
        "logo_right": _team_asset_path(ds, slot.team_id, logos.get("right", "")),
        "roles": roles,
        "set_plays": set_plays,
        "players": selected_players,
    }


def build_match_data(ds: DataStore, cfg: MatchConfig):
    """Returns the backend match_data dict, or None if the selection is
    incomplete. Difficulty/half length/home side are the three newly-exposed
    keys the advanced panel adds — everything else matches the pre-redesign
    output byte-for-byte for a fixed selection."""
    if not (cfg.home.team_id and cfg.home.season and cfg.away.team_id and cfg.away.season):
        return None

    home_info = ds.teams[cfg.home.team_id][cfg.home.season]
    selected_ball = _team_asset_path(ds, cfg.home.team_id, home_info.get("ball", ""))
    selected_banners = _team_asset_path(ds, cfg.home.team_id, home_info.get("banners", ""))

    ball_entry = cfg.ball_choice
    if isinstance(ball_entry, dict):
        source = ball_entry.get("source")
        if source == "teams_json":
            selected_ball = _team_asset_path(ds, ball_entry.get("team_id"), ball_entry.get("path", ""))
        elif source == "tournament":
            selected_ball = _tournament_asset_path(ds, ball_entry.get("team_id"), ball_entry.get("path", ""))
        elif ball_entry.get("path"):
            selected_ball = _relative_to_mod_data(ball_entry.get("path"))

    stadium_id = 70  # default (Stade de France)
    if cfg.stadium and cfg.stadium.get("stadium_id"):
        stadium_id = int(cfg.stadium["stadium_id"])

    home_count, away_count = cfg.controller_counts()
    user_controlled = 1 if home_count > 0 else 2

    kick_off = cfg.kick_off
    if kick_off == "random":
        kick_off = random.choice(["home", "away"])

    home_team_side = cfg.home_team_side
    if home_team_side == "random":
        home_team_side = random.choice(["left", "right"])

    tournament = cfg.shared_tournament
    if tournament:
        tid = tournament.get("tournament_id")
        tournament_logo = _tournament_asset_path(ds, tid, tournament.get("logo", ""))
        stadium_graphics = _tournament_asset_path(ds, tid, tournament.get("pads", ""))
    else:
        tournament_logo = _team_asset_path(ds, cfg.home.team_id, home_info.get("logos", {}).get("main", ""))
        stadium_graphics = _team_asset_path(ds, cfg.home.team_id, home_info.get("pads", ""))

    # The advanced panel's "tournament logo" and "stadium graphics" pickers: a
    # tournament's own files instead of the home team's.
    logo_choice = getattr(cfg, "tournament_logo_choice", "")
    if logo_choice in ds.tournaments:
        t_info = next(iter(ds.tournaments[logo_choice].values()), {})
        tournament_logo = _tournament_asset_path(ds, logo_choice, t_info.get("logo", "")) or tournament_logo
    pads_choice = getattr(cfg, "stadium_graphics_choice", "")
    if pads_choice in ds.tournaments:
        t_info = next(iter(ds.tournaments[pads_choice].values()), {})
        stadium_graphics = _tournament_asset_path(ds, pads_choice, t_info.get("pads", "")) or stadium_graphics

    # cfg.pitch_logo_choice (the advanced panel's own picker) overrides
    # whatever the tournament/team fallback above would have given — that
    # fallback in practice never fires anyway, since nothing ever sets
    # cfg.shared_tournament (see on_team_changed).
    if cfg.pitch_logo_choice and cfg.pitch_logo_choice in ds.tournaments:
        pl_seasons = ds.tournaments[cfg.pitch_logo_choice]
        pl_info = next(iter(pl_seasons.values()), {})
        pl_raw = pl_info.get("pitch_logo", "")
        pitch_logo = _tournament_asset_path(ds, cfg.pitch_logo_choice, pl_raw) if pl_raw else ""
    elif tournament:
        pitch_logo_raw = tournament.get("pitch_logo", "")
        pitch_logo = (_tournament_asset_path(ds, tournament.get("tournament_id"), pitch_logo_raw)
                     if pitch_logo_raw else "")
    else:
        pitch_logo = ""

    difficulty_map = {"club": 0, "pro": 1, "elite": 2}
    halftime_length_map = {"2m": 0, "5m": 1, "10m": 2, "20m": 3, "40m": 4}

    # ── Advanced/.mis fields (config.advanced_user) ─────────────────────
    # Every one of these stays at its "omit the attribute" value unless the
    # advanced panel was actually used — see MatchConfig's own comment and
    # game_files_processor.create_mission_file, which is what treats these
    # keys as optional. wind_dir_deg (a compass bearing, the natural UI
    # control) is turned into a ground-plane unit vector here since x/y/z is
    # the .mis's own representation, not something the UI needs to expose.
    wind_x = wind_z = 0.0
    if cfg.wind_power:
        heading = math.radians(cfg.wind_dir_deg % 360.0)
        wind_x = round(math.sin(heading), 4)
        wind_z = round(math.cos(heading), 4)

    mission_state = {}
    if cfg.mission_mode_name:
        mission_state = {
            "mode_name": cfg.mission_mode_name,
            "mode_time": cfg.mission_mode_time,
            "mode_period": cfg.mission_mode_period,
        }

    return {
        "difficulty": difficulty_map.get(cfg.difficulty, 2),
        "halftime_length": halftime_length_map.get(cfg.halftime_length, 1),
        "matchType": gsv.match_type.get(cfg.match_type, 0),
        "matchSubType": gsv.match_subtype.get(cfg.match_subtype, 0),
        "user_controlled_team": user_controlled,
        "controllers": {
            slot_id: {"kbd": "cpu", "cpu": "cpu"}.get(c["zone"], c["zone"]).replace("home", "team_A").replace("away", "team_B")
            if c["zone"] in ("home", "away") else "cpu"
            for slot_id, c in cfg.controllers.items()
        },
        "stadium": stadium_id,
        "stadium_graphics": stadium_graphics,
        "kick_off": kick_off,
        # Was set on cfg by the advanced panel's side row but never actually
        # read into this dict — create_mission_file's side= always fell back
        # to its own "left" default regardless of the picker.
        "home_team_side": home_team_side,
        "environment": cfg.environment,
        "pitch_texture": cfg.pitch_texture,
        "rain": cfg.rain,
        "ball": selected_ball,
        "banners": selected_banners,
        "tournament_logo": tournament_logo,
        # NOT "pitch_logo" — game_files_processor.edit_graphics_files reads
        # match_data["pitch_logos"] (plural); the singular key here meant
        # this was silently a no-op for every match until now.
        "pitch_logos": pitch_logo,
        "flags": _team_asset_path(ds, cfg.home.team_id, home_info.get("flags", "")),
        "referee": {"face": "", "kit_back": "", "kit_front": ""},
        # ── Advanced/.mis fields — see the comment above and MatchConfig's
        # own for what each depends on. All at their "omit" default unless
        # the advanced panel (config.advanced_user) was used.
        "wind_power": cfg.wind_power,
        "wind_x": wind_x,
        "wind_z": wind_z,
        "precip_mode": cfg.precip_mode,
        "snow_intensity": cfg.snow_intensity,
        "breath": cfg.breath,
        "anthem": cfg.anthem,
        "haka_home": cfg.haka_home,
        "haka_away": cfg.haka_away,
        "trophy_lift": cfg.trophy_lift,
        "stadium_flags": cfg.stadium_flags,
        "kick_assist": cfg.kick_assist,
        "mission_state": mission_state,
        "mission_nis": list(cfg.mission_nis),
        "score_events": list(cfg.score_events),
        "objectives": list(cfg.objectives),
        "team_A": _build_team_match_data(ds, cfg.home, True),
        "team_B": _build_team_match_data(ds, cfg.away, False),
    }
