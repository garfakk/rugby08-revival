""" 
This file contains the core functions of the patch that are used to start a match with the desired configuration
The function start_match() is the only function that you should be using (unless you know what you are doing, like debugging etc.)

You can load this script as a module, in this case you need to call the function start_match().
This is the preferred option if you are using the user interface to start the game.
The function start_match() take one input argument 'match_data', which shall be a dict filled with the proper data.
The content of this variable must match the structure provided in 'match_data.yaml', converted as a python dict.

Alternatively you can run this script directly, in this case the match data will be read from the file 'match_data.yaml'.


"""
import struct
import os
import time
from PIL import Image
import subprocess
import xml.etree.ElementTree as ET
import xml.dom.minidom
import yaml
import configparser
import argparse
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

# Custom modules
import backend.process_handler
from backend.game_specific_variables import *
from backend.mod_utils import *
from shared.config import *

from shared.log import get_logger

log = get_logger(__name__)


# This function creates a mission file into the game directory with the match configuration (teams, stadium, environment, etc.)
def create_mission_file(match_data):

    missionFilePath = os.path.join(config.game_launcher_directory, game_filenames['missionFile'])

    try:
        ctrl_map = {"team_A": "home", "team_B": "away", "cpu": "off"}
        controllers = match_data.get("controllers", {})
        c0 = ctrl_map.get(controllers.get(1, "cpu"), "off")
        c1 = ctrl_map.get(controllers.get(2, "cpu"), "off")
        c2 = ctrl_map.get(controllers.get(3, "cpu"), "off")
        c3 = ctrl_map.get(controllers.get(4, "cpu"), "off")

        # match_data["kick_off"] is "home" or "away" (resolved from "random" upstream)
        if match_data.get("kick_off", "home") == "home":
            kickoff = "home"
        else:
            kickoff = "away"

        mission_attrs = {
            "name": "user_mission",
            "date": "20061231",
            "type": "1",
            "league": "international",
            "halflength": str(match_data.get('halftime_length', 1)),
            "stadiumid": str(match_data.get("stadium", 70)),
            "hometeamid": str(teams_id['team_A']),
            "awayteamid": str(teams_id['team_B']),
            "diff": str(match_data.get('difficulty', 0)),
            "matchtype": str(match_data.get('matchType', 0)),
            "matchsubtype": str(match_data.get('matchSubType', 0)),
            "control": "0",
            # "control": str(1 if match_data.get('user_controlled_team', 0) == 1 else 0), # Should determined based on controllers, to be changed? if really necessary (hard coded 0 seems to works well also)
            "side": str(match_data.get('home_team_side', 'left')),
            "c0": c0,
            "c1": c1,
            "c2": c2,
            "c3": c3,
        }

        # ── advanced: presentation (each a real reR08 patch, default-on) ───
        anthem = match_data.get("anthem")
        if anthem in ("home", "away"):
            # reR08 ENABLE_ANTHEM.
            mission_attrs["anthem"] = anthem
        if match_data.get("haka_home"):
            mission_attrs["haka0"] = "1"          # reR08 ENABLE_HAKA
        if match_data.get("haka_away"):
            mission_attrs["haka1"] = "1"
        trophy_lift = match_data.get("trophy_lift")
        if trophy_lift and trophy_lift not in ("stock", "off"):
            mission_attrs["trophy_lift"] = trophy_lift   # reR08 ENABLE_TROPHY_LIFT
        stadium_flags = match_data.get("stadium_flags")
        if stadium_flags is not None:
            # reR08 ENABLE_STADIUM_FLAGS — no-op on stadiums without RWC
            # dressing groups, harmless everywhere else.
            mission_attrs["stadium_flags"] = "on" if stadium_flags else "off"
        if match_data.get("kick_assist"):
            # reR08 ENABLE_EASY_GOALKICK — depends on wind (below) being on.
            mission_attrs["kickassist"] = "on"

        mission = ET.Element("MISSION", mission_attrs)

        # Create the GAME element
        game = ET.SubElement(mission, "GAME")

        # Add ENVIRONMENT element under GAME
        environment = ET.SubElement(game, "ENVIRONMENT")

        # Add WEATHER element under ENVIRONMENT
        # env/pitchtex: reR08 patches_dll ENABLE_ENVIRONMENT/ENABLE_PITCH.
        # pitch_texture's UI default/unset state is "default" (env is
        # always a concrete stadium environment, never unset) — neither
        # is in either patch's whitelist, so it's always safe to emit:
        # an unrecognized value just falls back to the stadium's own
        # stock behaviour.
        weather_attrs = {
            "pitch": "0",
            "temp": "0",
            # reR08 ENABLE_WEATHER: 0 = none, 1/2 = rain, 3 = snow.
            "precipitation": "1" if match_data.get("rain") else "0",
            "env": str(match_data.get("environment") or "default"),
            "pitchtex": str(match_data.get("pitch_texture") or "default"),
        }
        # ── advanced: precipitation mode (supersedes the plain rain flag
        # above when set) + real falling snow. precipitation="3" alone
        # renders no snow — reR08 ENABLE_SNOWFX needs its own precip=/
        # intensity= pair to actually show it; see game_specific_variables.
        precip_mode = match_data.get("precip_mode")
        if precip_mode and precip_mode != "stock":
            weather_attrs["precipitation"] = str(precipitation_id.get(precip_mode, 0))
            weather_attrs["precip"] = precip_mode
            if precip_mode == "snow" and match_data.get("snow_intensity") is not None:
                weather_attrs["intensity"] = str(match_data["snow_intensity"])
        breath = match_data.get("breath")
        if breath is not None:
            weather_attrs["breath"] = "on" if breath else "off"   # reR08 ENABLE_BREATH

        weather = ET.SubElement(environment, "WEATHER", weather_attrs)

        # Add WIND element under WEATHER. reR08 ENABLE_WIND: power = band
        # 0..10 (0 = calm, 1..3 stock bands, 4..10 extended); x/y/z direction
        # only (normalized) — match_data_builder turns the UI's compass
        # bearing into wind_x/wind_z (ground plane, y always 0).
        wind_power = match_data.get("wind_power") or 0
        wind_x = match_data.get("wind_x", 0) if wind_power else 0
        wind_z = match_data.get("wind_z", 0) if wind_power else 0
        wind = ET.SubElement(weather, "WIND", {
            "power": str(wind_power),
            "x": str(wind_x),
            "y": "0",
            "z": str(wind_z),
        })

        state = ET.SubElement(game, "STATE")

        # ── advanced: hand-authored score-so-far. Empty by default (an
        # ordinary 0-0 kickoff, same as before this existed) — each entry
        # becomes one <EVENT>, in the same shape 93 stock missions use.
        score = ET.SubElement(state, "SCORE")
        for ev in match_data.get("score_events") or []:
            if not ev.get("type"):
                continue
            ET.SubElement(score, "EVENT", {
                "type": ev["type"],
                "team": ev.get("team") or "home",
                "player": str(ev.get("player", 0)),
                "time": str(ev.get("time", 0)),
            })

        # ── advanced: hand-authored start mode. "" (default) keeps the
        # mod's own long-standing behaviour: no name/time/period, just a
        # plain kickoff. EXPERIMENTAL beyond that — mode_name/time/period
        # are real stock <MODE> attrs (verified: this is the schema all 93
        # stock .mis files use), but dropping a mode like "PEN K" into an
        # otherwise-ordinary exhibition match (no matching NIS/history) is
        # not in-game confirmed.
        mission_state = match_data.get("mission_state") or {}
        mode = ET.SubElement(state, "MODE", {
            'name': mission_state.get("mode_name", ""),
            'offensiveteam': kickoff,
            'time': str(mission_state["mode_time"]) if mission_state.get("mode_time") is not None else "",
            'period': str(mission_state["mode_period"]) if mission_state.get("mode_period") is not None else "",
        })

        # ── advanced: restart position(s) that go with the start mode
        # above (where to place the ball/players for a scrum/lineout/
        # penalty). Stock missions carry 0-2 of these, always right after
        # <MODE> inside <STATE> — same placement here. EXPERIMENTAL, same
        # caveat as MODE: schema verified, in-game behaviour outside a
        # plain kickoff is not.
        def _num_or_blank(v):
            return "" if v is None or v == "" else str(v)

        for nis in match_data.get("mission_nis") or []:
            ET.SubElement(state, "NIS", {
                "script_name": nis.get("script_name", ""),
                "controller": str(nis.get("controller", 0) or 0),
                "team": nis.get("team") or "home",
                "player": str(nis.get("player", 0) or 0),
                "angle": _num_or_blank(nis.get("angle")),
                "x": _num_or_blank(nis.get("x")),
                "y": _num_or_blank(nis.get("y")),
                "z": _num_or_blank(nis.get("z")),
            })

        # Add OBJECTIVES element under MISSION. Empty by default (same as
        # before). Each entry's Type must be one of gsv.objective_types —
        # anything else is a no-op UnknownObjective in the stock dispatcher,
        # see game_specific_variables.py.
        objectives = ET.SubElement(mission, "OBJECTIVES")
        for obj in match_data.get("objectives") or []:
            if not obj.get("type"):
                continue
            obj_el = ET.SubElement(objectives, "OBJECTIVE", {
                "stringid": obj.get("stringid", ""),
                "type": obj["type"],
                "mustpass": "1" if obj.get("mustpass") else "0",
            })
            for param in obj.get("parameters") or []:
                if not param.get("name"):
                    continue
                ET.SubElement(obj_el, "PARAMETER", {
                    "name": param["name"],
                    "value": str(param.get("value", "")),
                })

        # Write the XML to the file
        xml_str = ET.tostring(mission, encoding='utf-8', method='xml').decode()
        pretty_xml = xml.dom.minidom.parseString(xml_str).toprettyxml(indent="    ")

        with open(missionFilePath, 'w', encoding='utf-8') as file:
            file.write(pretty_xml)

        log.info(f"Mission file created successfully")

    except Exception as e:
        log.error(f"Error while creating mission file: {e}")


# True when the player's boot_style is an image path whose file exists (custom boots slot).
def has_custom_boots(player):
    value = player.get("boot_style", 0)
    return not isinstance(value, int) and custom_asset_exists(str(value), config.mod_data_directory)


# Stock boot style (0-9). Out-of-range ints and unusable paths fall back to 0.
def stock_boot_style(player):
    value = player.get("boot_style", 0)
    if isinstance(value, int) and value in boot_style_id:
        return value
    log.warning(f"Invalid boot style for player {player.get('name')}: {value!r}. Using style 0.")
    return 0


# True when the stock gloved skin texture should be used: gloves switched on, or a
# custom gloves image that cannot be found (keep gloves rather than a placeholder).
def wears_stock_gloves(player):
    gloves = player.get("gloves", False)
    if gloves is True:
        return True
    return is_custom_asset(gloves) and not custom_asset_exists(gloves, config.mod_data_directory)


# This function copies all the graphics files (logos, kits, etc) into the game folder and edit them if necessary
def edit_graphics_files(match_data):

  # Copy tournament logo file from template and edit it
  tournament_logo_filepath = os.path.join(config.game_launcher_directory, game_filenames['tournament_logo'])
  tournament_logo_template_filepath = os.path.join(config.templates_directory, template_filenames['tournament_logo'])
  tournament_logo_source_filepath = os.path.join(config.mod_data_directory, match_data['tournament_logo'])
  if copy_file(tournament_logo_template_filepath, tournament_logo_filepath):
    #   add_image_to_fsh_file(tournament_logo_filepath, tournament_logo_source_filepath, fsh_image_sizes["tournament_logo"], fsh_files_offsets["tournament_logo"])
      replace_asset_in_fsh_file(tournament_logo_filepath, tournament_logo_source_filepath, index = 0)
 
  # Create ball file (either copy .fsh file or create it from images)
  ball_filepath = os.path.join(config.game_launcher_directory, game_filenames['ball'])
  if match_data['ball'][-4:] == ".fsh":
      copy_file(os.path.join(config.mod_data_directory, match_data['ball']), ball_filepath)
  else:
        if copy_file(os.path.join(config.templates_directory, template_filenames['ball']), ball_filepath):
            for index in range (0, 2):
              ball_image_filepath = os.path.join(config.mod_data_directory, match_data['ball'].replace("%", str(index+1)))
            #   add_image_to_fsh_file(ball_filepath, ball_image_filepath, fsh_image_sizes['ball'], fsh_files_offsets[f"ball_{index+1}"])
              replace_asset_in_fsh_file(ball_filepath, ball_image_filepath, index = index)
        else:
            log.error("Error while copying ball template file")

  # Copy stadium graphics files
  stadium_graphics_filepath = os.path.join(config.game_launcher_directory, game_filenames['stadium_graphics'])
  copy_file(os.path.join(config.mod_data_directory, match_data['stadium_graphics']), stadium_graphics_filepath)

  # Copy pitch logo file template and edit it
  pitch_logo_filepath = os.path.join(config.game_launcher_directory, game_filenames['pitch_logo'])
  pitch_logo_template_filepath = os.path.join(config.templates_directory, template_filenames['pitch_logo'])
  pitch_logo_pattern = match_data.get('pitch_logos', '')
  pitch_logo_1 = pitch_logo_pattern.replace('%', '1', 1)
  pitch_logo_2 = pitch_logo_pattern.replace('%', '2', 1)

  if copy_file(pitch_logo_template_filepath, pitch_logo_filepath):
    if pitch_logo_1:
      #   add_image_to_fsh_file(pitch_logo_filepath, os.path.join(config.mod_data_directory, pitch_logo_1), fsh_image_sizes["pitch_logo_1"], fsh_files_offsets["pitch_logo_1"])
      replace_asset_in_fsh_file(pitch_logo_filepath, os.path.join(config.mod_data_directory, pitch_logo_1), index = 0)
    if pitch_logo_2:
      #   add_image_to_fsh_file(pitch_logo_filepath, os.path.join(config.mod_data_directory, pitch_logo_2), fsh_image_sizes["pitch_logo_2"], fsh_files_offsets["pitch_logo_2"])
      replace_asset_in_fsh_file(pitch_logo_filepath, os.path.join(config.mod_data_directory, pitch_logo_2), index = 1)

  for team in ['team_A', 'team_B']:

    # Create banners file
    banners_filepath = os.path.join(config.game_launcher_directory, game_filenames[team]['banners'])
    if match_data[team]['banners'][-4:] == ".fsh":
        copy_file(os.path.join(config.mod_data_directory, match_data[team]['banners']), banners_filepath)
    else:
        if copy_file(os.path.join(config.templates_directory, template_filenames['banners']), banners_filepath):
            for index in range(0, 4):
                banner_image_filepath = os.path.join(config.mod_data_directory, match_data[team]['banners'].replace("%", str(index+1)))
                #   add_image_to_fsh_file(banners_filepath, banner_image_filepath, fsh_image_sizes['banners'], fsh_files_offsets["banner_1"] + (fsh_files_offsets["banner_n"] * index))
                replace_asset_in_fsh_file(banners_filepath, banner_image_filepath, index = index)


    # Create crowd file
    # Warning: work in progress, not fully implemented yet
    # # 1. Extract the stadium BIG file from data.gob (temporary working file)
    # stadium_big_filename = "f989db0b8ad1f2a3c8b5ab10f314c1ed.big"
    # stadium_big_filepath = os.path.join(config.R08_directory, stadium_big_filename)
    # extract_result = extract_files_from_big_archive(config.R08_data_gob_filepath, stadium_big_filename, config.R08_directory)
    # # extract_result = extract_files_from_big_archive(stadium_big_filepath, "Crowd.fsh", config.temp_directory)
    # # 2. Create the crowd.fsh file (temporary working file, inserted into the BIG below)
    # crowd_filepath = os.path.join(config.temp_directory, game_filenames['crowd'])
    # if match_data['crowd'][-4:] == ".fsh":
    #     copy_file(os.path.join(config.mod_data_directory, match_data['crowd']), crowd_filepath)
    # else:
    #     if copy_file(os.path.join(config.templates_directory, template_filenames['crowd']), crowd_filepath):
    #         for index in range(0, 4):
    #             crowd_image_filepath = os.path.join(config.mod_data_directory, match_data['crowd'].replace("%", str(index+1)))
    #             add_image_to_fsh_file(crowd_filepath, crowd_image_filepath, fsh_image_sizes['crowd'], fsh_files_offsets["crowd_1"] + (fsh_files_offsets["crowd_n"] * index))
    # # 3. Add the edited crowd.fsh file into the stadium BIG file
    # add_file_to_big_archive(stadium_big_filepath, crowd_filepath, "Crowd.fsh", True)

    # Filepaths for minikits
    # minikit_filepath = os.path.join(config.game_launcher_directory, game_filenames[team]['minikit'])
    # minikit_template_filepath = os.path.join(config.templates_directory, template_filenames[team]['minikit'])

    # Kits filepaths
    kit_front_big_template_filepath = os.path.join(config.templates_directory, template_filenames[team]['kit_front_big'])
    kit_front_fsh_template_filepath = os.path.join(config.templates_directory, template_filenames[team]['kit_front_fsh'])
    kit_back_fsh_template_filepath = os.path.join(config.templates_directory, template_filenames[team]['kit_back'])
    kit_front_fsh_filepath = os.path.join(config.temp_directory, template_filenames[team]['kit_front_fsh'])   # This is a temporary file that will be inserted in the BIG file
    kit_front_big_filepath = os.path.join(config.game_launcher_directory, game_filenames[team]['kit_front'])    
    kit_back_fsh_filepath = os.path.join(config.game_launcher_directory, game_filenames[team]['kit_back'])
    kit_front_source_filepath = os.path.join(config.mod_data_directory, match_data[team]['kit_front'])
    kit_back_source_filepath = os.path.join(config.mod_data_directory, match_data[team]['kit_back'])
    
    # Filepaths for logos
    logos_filepath = os.path.join(config.game_launcher_directory, game_filenames[team]['logos'])
    logos_template_filepath = os.path.join(config.templates_directory, template_filenames[team]['logos'])
    logo_main_source_filepath = os.path.join(config.mod_data_directory, match_data[team]['logo'])
    logo_small_source_filepath = os.path.join(config.mod_data_directory, match_data[team]['logo_small'])
    logo_left_source_filepath = os.path.join(config.mod_data_directory, match_data[team]['logo_left'])
    logo_right_source_filepath = os.path.join(config.mod_data_directory, match_data[team]['logo_right'])

    # Copy minikit FSH template and edit it (the team logo is used for the in-game minikit)
    # if copy_file(minikit_template_filepath, minikit_filepath):
        # replace_asset_in_fsh_file(minikit_filepath, logo_main_source_filepath, index = 0)
        
    # Create logos FSH file
    if copy_file(logos_template_filepath, logos_filepath):
        # add_image_to_fsh_file(logos_filepath, logo_main_source_filepath, fsh_image_sizes['logo_main'], fsh_files_offsets["logo_main"])
        replace_asset_in_fsh_file(logos_filepath, logo_main_source_filepath, index = 0)
        # add_image_to_fsh_file(logos_filepath, logo_small_source_filepath, fsh_image_sizes['logo_small'], fsh_files_offsets["logo_small"])
        replace_asset_in_fsh_file(logos_filepath, logo_small_source_filepath, index = 1)
        # add_image_to_fsh_file(logos_filepath, logo_left_source_filepath, fsh_image_sizes['logo_left'], fsh_files_offsets["logo_left"])
        replace_asset_in_fsh_file(logos_filepath, logo_left_source_filepath, index = 2)
        # add_image_to_fsh_file(logos_filepath, logo_right_source_filepath, fsh_image_sizes['logo_right'], fsh_files_offsets["logo_right"])
        replace_asset_in_fsh_file(logos_filepath, logo_right_source_filepath, index = 3)

    # Create front kit .big file (either copy .big file or create it from images)
    if match_data[team]['kit_front'][-4:] == ".big":
      # Copy BIG file into game directory
      copy_file(kit_front_source_filepath, kit_front_big_filepath)

    else:
      # Create .fsh file from image and import it into a .big file
      copy_file(kit_front_fsh_template_filepath, kit_front_fsh_filepath)
      copy_file(kit_front_big_template_filepath, kit_front_big_filepath)
      add_image_to_fsh_file(kit_front_fsh_filepath, kit_front_source_filepath, fsh_image_sizes['front_kit'], fsh_files_offsets["front_kit"])
      add_file_to_big_archive(kit_front_big_filepath, kit_front_fsh_filepath)
      # Remove the temporary FSH file now that it has been inserted into the BIG archive
      try:
        os.remove(kit_front_fsh_filepath)
      except OSError as e:
        log.warning(f"could not remove temp file {kit_front_fsh_filepath}: {e}")

    # Create back kit .fsh file (either copy .fsh file or create it from images)
    if match_data[team]['kit_back'][-4:] == ".fsh":
      # Copy FSH file into game directory
      copy_file(kit_back_source_filepath, kit_back_fsh_filepath)

    else:
      # Create .fsh file from images
        copy_file(kit_back_fsh_template_filepath, kit_back_fsh_filepath)

        for index_file in range(0, 22):
            kit_back_image = os.path.join(config.mod_data_directory, match_data[team]['kit_back'].replace("%", str(index_file+1)))
            replace_asset_in_fsh_file(kit_back_fsh_filepath, kit_back_image, index = index_file)

    # Create custom boots for players
    template_boots_filepath = os.path.join(config.templates_directory, template_filenames['boots'])
    boots_fsh_filepath = os.path.join(config.game_launcher_directory, game_filenames['boots'])
    if copy_file(template_boots_filepath, boots_fsh_filepath):

        for team in ['team_A', 'team_B']:
                team_offset = 0 if team == 'team_A' else len(match_data['team_A']['players'])
                for player_index, player in enumerate(match_data[team]['players']):
                    if has_custom_boots(player):
                        custom_boot_filepath = os.path.join(config.mod_data_directory, str(player["boot_style"]))
                        replace_asset_in_fsh_file(boots_fsh_filepath, custom_boot_filepath, index = 10 + player_index + team_offset) # hardcoded offset value (10), to be replaced by variable in game_specific_variables.py


    # Create custom skins for players (custom skin textures, overlays and/or gloves)
    template_skins_filepath = os.path.join(config.templates_directory, template_filenames['skins'])
    skins_fsh_filepath = os.path.join(config.game_launcher_directory, game_filenames['skins'])
    if copy_file(template_skins_filepath, skins_fsh_filepath):

        for team in ['team_A', 'team_B']:
                team_offset = 0 if team == 'team_A' else len(match_data['team_A']['players'])
                for player_index, player in enumerate(match_data[team]['players']):
                    dest_index = 8 + player_index + team_offset # hardcoded offset value (8), to be replaced by variable in game_specific_variables.py
                    # Textures to superpose, from bottom to top: the skin_overlay list (first item
                    # at the bottom), then custom gloves on top. Missing files are already dropped.
                    custom_skin_filepath, overlay_paths = resolve_player_skin_layers(player, config.mod_data_directory, skin_texture_id)

                    if overlay_paths:
                        # Determine the base skin image to superpose the overlays on
                        base_image = None
                        if custom_skin_filepath:
                            base_image = Image.open(custom_skin_filepath)
                        elif player["skin"] in skin_texture_id:
                            # Stock skin tone: extract it from the skins template FSH file.
                            # A custom glove overlay replaces the stock glove, so use the no-glove stock tone as the base.
                            stock_index = skin_texture_id[player["skin"]] + (1 if wears_stock_gloves(player) else 0) - 1
                            base_image = extract_asset_from_fsh_file(template_skins_filepath, stock_index)
                        else:
                            log.warning(f"Invalid skin for player {player['name']} ({player['skin']}), cannot apply overlays")

                        if base_image is not None:
                            temp_skin_filepath = os.path.join(config.temp_directory, f"skin_{team}_{player_index}.png")
                            composite_baselayers_on_image(base_image, overlay_paths, temp_skin_filepath)
                            replace_asset_in_fsh_file(skins_fsh_filepath, temp_skin_filepath, index = dest_index)
                            try:
                                os.remove(temp_skin_filepath)
                            except OSError as e:
                                log.warning(f"could not remove temp file {temp_skin_filepath}: {e}")

                    elif custom_skin_filepath:
                        replace_asset_in_fsh_file(skins_fsh_filepath, custom_skin_filepath, index = dest_index)

    else:
        log.error(f"Error while copying skins template file")


    

    # Create custom boots for players (if any)
    #TO DO

# This function edits the teams names by editing the game strings files (.english and .french)
# The new strings (with their ID) are added at the end of a template file (from which the strings we want to write have been previously removed)
def edit_teams_name(game_data):
  
  for game_strings in ['game_strings_english', 'game_strings_french']:
    game_strings_filepath = os.path.join(config.game_launcher_directory, game_filenames[game_strings])
    copy_file(os.path.join(config.templates_directory, template_filenames[game_strings]), game_strings_filepath)

    try:
        with open(game_strings_filepath, 'ab') as file:
            for team in ['team_A', 'team_B']:
                file.write(teams_string_id[team])
                file.write(game_data[team]['name'].encode('utf-8'))
                file.write(b'\x00')
    except Exception as e:
        log.error(f"Error while editing teams names in {game_strings_filepath}: {e}")

# This function copies all the "static files" necessary for the mod
def copy_static_files():

    excluded_files = config.exclude_static_files

    # Check if source directory exists
    if not os.path.exists(config.static_files_directory):
        log.warning(f"Source directory '{config.static_files_directory}' does not exist.")
        return
    
    # Ensure destination directory exists
    if not os.path.exists(config.game_launcher_directory):
        log.warning(f"Destination directory '{config.game_launcher_directory}' does not exist.")
        return

    # Loop through all files in the statics file directory
    for root, dirs, files in os.walk(config.static_files_directory):

        # Determine the relative path to preserve subfolders structure
        relative_path = os.path.relpath(root, config.static_files_directory)
        
        # Determine the absolute destination directory
        dest_subdir = os.path.join(config.game_launcher_directory, relative_path)
        
        # Ensure destination directory exists
        if not os.path.exists(dest_subdir):
            os.makedirs(dest_subdir)
        
        # Copy each file
        for file_name in files:
            if file_name not in excluded_files:
                log.debug(file_name)

                src_file = os.path.join(root, file_name)

                if file_name in ["eaenpc.vp6", "inenpc.vp6"]:
                    file_name = os.path.join("Data", file_name)

                dest_file = os.path.join(dest_subdir, file_name)
                
                # Copy file and overwrite if it already exists
                copy_file(src_file, dest_file)

            else:
                log.debug(f"Skipped excluded file {file_name}")

    log.info("Static files copied successfully")

# Names of the game files the mod writes for a match (graphics, kits, roster,
# mission, game strings, and the custom-face slots).
def generated_game_filenames():
    names = set()
    for value in game_filenames.values():
        if isinstance(value, dict):
            names.update(value.values())
        else:
            names.add(value)
    for faces in face_id_for_custom_faces.values():
        names.update(face['filename'] for face in faces)
    return names

# Removes what a previous match left in the game folder, so nothing stale
# (custom faces, kits, logos...) leaks into the next one. Only the files named
# by generated_game_filenames() are touched, never the game's own data, and the
# game falls back to its archive (data.gob) for the ones it ships. Must run
# before copy_static_files, which re-deploys the static files that share a name.
def clean_generated_files(directory=None):
    directory = directory or config.game_launcher_directory
    removed = 0
    for name in generated_game_filenames():
        path = os.path.join(directory, name)
        try:
            if os.path.isfile(path):
                os.remove(path)
                removed += 1
        except OSError as e:
            log.error(f"Could not remove {name}: {e}")
    log.info(f"Removed {removed} files left by the previous match")
    return removed

# Warning not implemented
# This function remves all the non-original R08 files
def clean_non_original_files():
    for file in os.listdir(config.game_launcher_directory):
        if file not in config.original_game_files:
            file_path = os.path.join(config.game_launcher_directory, file)
            try:
                if os.path.isfile(file_path):
                    os.remove(file_path)
                    log.debug(f"Removed non-original file: {file}")
            except Exception as e:
                log.error(f"Error while removing file {file}: {e}")

# # This function determines the players ID (depending on their position in the team and wether they are a star player or not)
# # DEPRECATED
# def determine_players_roster_id(star_players):
#   roster_ids = {'team_A': None, 'team_B': None}

#   id_normal_players = players_roster_id['normal_players']
#   id_star_players = players_roster_id['star_players']

#   for team in ['team_A', 'team_B']:
#     roster_ids[team] = [id_star_player if star_player else id_normal_player for id_star_player, id_normal_player, star_player in zip(id_star_players[team], id_normal_players[team], star_players[team])]

#   return roster_ids

# This function configures the players and team data in the roster file
def edit_roster_file(match_data):
  
  # Copy roster file from template
  roster_filepath = os.path.join(config.game_launcher_directory, game_filenames['roster'])
  copy_file(os.path.join(config.templates_directory, template_filenames['roster']), roster_filepath)

  for team in ['team_A', 'team_B']:
    nb_players = len(match_data[team]['players'])
    if nb_players != 22:
        log.warning(f"Invalid number of players for {team}: {nb_players} (expected 22). Skipping roster modification.")
        return

  star_players = {
    'team_A': [False for i in range(22)],
    'team_B': [False for i in range(22)]
  }

  # Determine the ID to use for each player (depending on their position and if they are a star player or not)
  players_id = players_roster_id
  
  # Inserts the players ID into match_data
  for team, ids in players_id.items():
    for player, player_id in zip(match_data[team]['players'], ids):
      player['roster_id'] = player_id

  write_team_data_to_roster(roster_filepath, match_data)
  write_players_data_to_roster(roster_filepath, match_data)

# This function writes the team info in the roster (composition, roles and set plays)
def write_team_data_to_roster(roster_filepath, match_data):
    
    def pack_players_id(players_id):
        packed = bytearray()
        
        for player_id in players_id:
            packed.append(player_id & 0x00FF)
            packed.append((player_id >> 8) & 0x00FF)

        return packed

    try:
        with open(roster_filepath, 'r+b') as file:

          for team in ['team_A', 'team_B']:

            # Getting players id
            players_id = [p['roster_id'] for p in match_data[team]['players']]
        
            # Getting roles players ID
            ordered_roles_as_position_in_team = [match_data[team]['roles'][i] for i in team_roles]
            ordered_roles_as_player_ID = []
            
            for index_role in range(len(ordered_roles_as_position_in_team)):
                position = ordered_roles_as_position_in_team[index_role]
                if position not in range(1, 16):
                    log.warning(f"Position for role #{index_role} ({team_roles[index_role]}) is invalid: {position}. Must be between 1 and 15. Using player 10 by default")
                
                ordered_roles_as_player_ID.append(players_id[position-1])
        
            # Getting set plays IDs
            try:
              set_plays = [set_plays_id[i] for i in match_data[team]['set_plays']]
            except:
              set_plays = []
              log.warning(f"Set plays for {team} contains invalid data: {match_data[team]['set_plays']}. Authorized values are: {', '.join(set_plays_id.keys())}")

            
            # Write team players id
            players_data = pack_players_id(players_id)
            file.seek(roster_data_addresses[team])
            file.write(players_data)

            # Write team roles
            roles_data = pack_players_id(ordered_roles_as_player_ID)
            file.seek(roster_data_addresses[team] + 0x40)
            file.write(roles_data)

            # Write team set plays
            set_plays_data = bytearray(set_plays)
            file.seek(roster_data_addresses[team] + 0x5C)
            file.write(set_plays_data)
            
    except Exception as e:
        log.error(f"Error while writing team data to roster: {e}")
    
# This function writes the players
def write_players_data_to_roster(roster_filepath, match_data):

    # This function return a dict with all the players IDs and their position in the roster file
    def find_roster_positions(file):
        """Find and return player positions in the roster file."""
        roster_positions = {}
        file.seek(0x04)

        while file.tell() < min(0x2E7D0 - 0x64, os.fstat(file.fileno()).st_size - 0x64):
            # Read Player ID
            current_id = file.read(2)
            player_id = (current_id[1] << 8) + current_id[0]
            current_id_pos = file.tell() - 2
            roster_positions[player_id] = current_id_pos

            # Skip player data and go to next player
            file.seek(file.tell() + 0x62)

        return roster_positions


    def get_player_index_from_roster_id(roster_id):
        """Get player position (0-43) in concatenated team_A + team_B given roster ID"""
        try:
            # Check team_A (positions 0-21)
            return players_roster_id['team_A'].index(roster_id)
        except ValueError:
            # Check team_B (positions 22-43)
            return 22 + players_roster_id['team_B'].index(roster_id)

    # This function writes a player data at a given address in a roster file
    def write_player_data(file, position, player):
        """Write player data at the given position in the roster file."""
        file.seek(position + 2)  # Skip Player ID

        log.debug(f"Writing data for player: {player['roster_id']}")
        player_index =  get_player_index_from_roster_id(player["roster_id"])

        # Write Commentary
        commentary = player["commentary"].to_bytes(2, byteorder="little")
        file.write(commentary)

        # Write Player Name
        player_name = player["name"].encode("utf-8")[:14]
        file.write(player_name.ljust(14, b"\x00"))

        # Skip empty space
        file.seek(file.tell() + 2)

        # Write Player Position
        pos1 = positions_id.get(player["pos1"], 0)
        pos2 = positions_id.get(player["pos2"], 0)
        pos3 = positions_id.get(player["pos3"], 0)
        
        pos1 = pos1 & 0x0F
        pos2 = (pos2 << 4) & 0xF0
        positions = bytes([pos1 + pos2, pos3])
        file.write(positions)

        # Write Weight
        weight = int(player["weight"] / 0.453 - 100) # Conversion from kg to lbs, with offset of 100 (ingame offset)
        file.write(bytes([weight % 256]))

        # Skip empty space
        file.seek(file.tell() + 1)

        # Write Nationality
        file.write(b"\x40\x00\x00")

        # Skip empty space
        file.seek(file.tell() + 1)

        # Write Height
        height = int(player["height"] / 2.54 - 59.21259842519685) # Conversion from cm to inches, with offset of ~60 (ingame offset)
        file.write(bytes([height]))

        # Write Birthdate
        birth_year = 107 - player['age']
        birth_month = 1
        birth_day_and_foot = 1 + foot_id.get(player['best_foot'], 0)
        birthdate = bytes([birth_year, birth_month, birth_day_and_foot])
        file.write(birthdate)

        # Write Special Ability
        file.write(bytes([player["special_ability"]]))

        # Write Stats Part 1
        stats_part1 = [
            player["attack"], player["defense"], player["speed"], player["acceleration"],
            player["agility"], player["handling"], player["passing"], player["kicking"],
            player["kicking_power"], player["goal_kicking"], player["tackling"],
            player["strength"], player["rucking"], player["scrummaging"], player["hooking"],
            player["line_out"], player["discipline"], player["aggression"]
        ]
        file.write(bytes(stats_part1))

        # Skip empty space
        file.seek(file.tell() + 3)

        # Write Stats Part 2
        stats_part2 = [
            player["stamina"], player["consistency"], player["temperament"], player["creativity"],
            player["bravery"], player["fitness"], player["crashball"], player["gap_defense"]
        ]
        file.write(bytes(stats_part2))

        # Skip empty space
        file.seek(file.tell() + 16)

        # Write player star attribute value
        file.write(bytes([player.get("star_attribute", 0)]))
        # file.write(b"\x03")

        # Skip empty space
        file.seek(file.tell() + 1)

        # Write player goal kicking style value
        goal_kicking_style_value = goal_kicking_style_values.get(player.get("goal_kicking_style"), 0)
        log.debug(f"Player {player['name']} ({player['roster_id']}) goal kicking style: {player.get('goal_kicking_style', 'default')} (value: {goal_kicking_style_value})")
        file.write(bytes([goal_kicking_style_value]))
        
        file.seek(file.tell() + 1)

        # Write player boot style value (new location, to allow more values using exe patch)
        if has_custom_boots(player):
            boot_style_value = 10 + player_index + 1 # hardcoded value (10), to be replaced by variable in game_specific_variables.py
        else:
            boot_style_value = stock_boot_style(player)
        log.debug(f"Player {player['name']} ({player['roster_id']}) boot style: {player['boot_style']} (value: {boot_style_value})")
        file.write(bytes([boot_style_value]))

        # Skip empty space
        file.seek(file.tell() + 1)

        # Write Special Skills
        special_skills_1 = player["ss_command"] + player["ss_passer"] * 2 + player["ss_play_maker"] * 4 + player["ss_scoring"] * 8 + player["ss_goal_kicker"] * 16 + player["ss_tactical_kicking"] * 32 + player["ss_crashball"] * 64 + player["ss_tackle_breaker"] * 128
        special_skills_2 = player["ss_tackling"] + player["ss_ball_winner"] * 2 + player["ss_defensive_organisation"] * 4 + player["ss_scrummager"] * 8 + player["ss_jumper"] * 16
            
        file.write(bytes([special_skills_1, special_skills_2]))

        # Write skin texture (new location, to allow more values using exe patch)
        # TO DO: add support for default skin tones (light, dark, etc) and image files to be added in FSH. Also add support for baselayers.
        log.debug(f"Player {player['name']} ({player['roster_id']}) skin: {player['skin']}")
        custom_skin_filepath, overlay_paths = resolve_player_skin_layers(player, config.mod_data_directory, skin_texture_id)
        has_valid_base = player["skin"] in skin_texture_id.keys() or custom_skin_filepath is not None
        # If player has overlays (baselayers/gloves) on top of a valid skin, a composited custom texture was written to the skins FSH file, so use the custom slot
        if overlay_paths and has_valid_base:
            skin_texture_value = 8 + player_index + 1  # hardcoded offset value (8), to be replaced by variable in game_specific_variables.py
        # If player skin is a stock texture (original skin tone + glove), use the original texture (first 8 textures of the skins FSH file)
        elif player["skin"] in skin_texture_id.keys():
            skin_texture_value = skin_texture_id.get(player["skin"]) + (1 if wears_stock_gloves(player) else 0)
        # If player skin is a custom texture, use the corresponding texture in the skins FSH file (textures 9-44 of the skins FSH file)
        elif custom_skin_filepath:
            skin_texture_value = 8 + player_index + 1  # hardcoded offset value (8), to be replaced by variable in game_specific_variables.py
        # Otherwise fallback to stock skin tone byte (0 here bypasses the skin patch and uses the stock one)
        else:
            skin_texture_value = 0 # warning: hardcoded value, to be replaced by default value in game_specific_variables.py
            log.warning(f"Invalid skin texture for player {player['name']} ({player['roster_id']}): {player['skin']}. Using default skin texture.")
            
        file.write(bytes([skin_texture_value]))

        # Skip empty space
        file.seek(file.tell() + 1)

        # Write Boot style and headgear
        # DEPECATED: the boot style is now written somehere else to allow more values (using exe patch). This is kept as a backup but it is not used anymore.
        boot_style = 4 * 16 + (0 if has_custom_boots(player) else stock_boot_style(player))
        file.write(bytes([boot_style]))

        # Write finger tape and socks up/down
        if player['finger_tape'] in tape_id:
            finger_tape = tape_id.get(player['finger_tape'])
        else:
            log.warning(f"Invalid finger tape")
            finger_tape = tape_id.get(player_default_values["finger_tape"])
                    
        if finger_tape == 1:
            finger_tape_and_socks = 16
        elif finger_tape == 2:
            finger_tape_and_socks = 8
        elif finger_tape == 3:
            finger_tape_and_socks = 24
        else:
            finger_tape_and_socks = 0
        
        finger_tape_and_socks += player["socks_up"] * 4
        file.write(bytes([finger_tape_and_socks]))

        # Write Face ID
        player_face = player['face']
        
        if isinstance(player_face, int):
            face_id = player_face
            
        elif player_face[-4:].lower() == ".big":
            face_id = face_id_for_custom_faces_by_roster_id.get(player['roster_id'])['face_id']
            custom_face_filepath = os.path.join(config.mod_data_directory, player_face)
            game_face_filepath = os.path.join(config.game_launcher_directory, face_id_for_custom_faces_by_roster_id[player['roster_id']]['filename'])
            copy_file(custom_face_filepath, game_face_filepath)
        
        else:
            face_id = player_default_values['face']
#            print(f"Invalid face for player {player['name']} ({player['roster_id']}): {player_face}")
            
        file.write(face_id.to_bytes(2, byteorder="little"))

        # Skip empty space
        file.seek(file.tell() + 1)

        # Wrist tape
        if player['wrist_tape'] in tape_id:
            wrist_tape = tape_id.get(player['wrist_tape'])
        else:
            log.warning(f"Invalid wrist tape")
            wrist_tape = tape_id.get(player_default_values["wrist_tape"])

        # Write skin tone. DEPRECATED: the skin is now written somehere else to allow more values (using exe patch). This is kept as a backup but it is not used anymore.
        if player["skin"] in skin_tone_id:
            skin_tone = skin_tone_id.get(player["skin"])
        else:
            skin_tone = skin_tone_id.get(player_default_values["skin"])
            log.warning(f"Invalid skin tone")
        
        wrist_tape_nibble = wrist_tape & 0x03
        skin_tone_nibble = skin_tone & 0x03
        wrist_tape_and_skin_tone_value = (wrist_tape_nibble << 5) | skin_tone_nibble
        file.write(bytes([wrist_tape_and_skin_tone_value]))

        # Write gloves and thigh Tape
        # Note: gloves are deprecated here (they are now written with the skin texture using exe patch). This is kept as a backup but it is not used anymore.
        if player['thigh_tape'] in tape_id:
            gloves_and_thigh_tape = tape_id.get(player['thigh_tape'])
        else:
            gloves_and_thigh_tape = tape_id.get(player_default_values['thigh_tape'])
            log.warning(f"Invalid thigh tape")
        gloves_and_thigh_tape += (1 if player['gloves'] else 0) * 8 # a custom glove image counts as gloves on
        file.write(bytes([gloves_and_thigh_tape]))

    try:
        with open(roster_filepath, "r+b") as file:
            roster_positions = find_roster_positions(file)
            results = {}

            for team in ['team_A', 'team_B']:
                for player in match_data[team]['players']:
                    player_id = player.get("roster_id")
                    player_name = player.get("name")

                    if player_id is None:
                        log.warning(f"Player missing 'roster_id' field ({player_name}). Skipping.")
                        continue
                    
                    missing_keys = [key for key in player_default_values if key not in player]
                    if missing_keys:
                        log.warning(f"Player {player_id} missing keys: {missing_keys}. Using default values.")
                        player = {**player_default_values, **player}

                    if player_id in roster_positions:
                        position = roster_positions[player_id]
                        write_player_data(file, position, player)
                    else:
                        log.error(f"The player id {player_id} does not exist in the roster file")
                        
                    for position in ['pos1', 'pos2', 'pos3']:
                        player_position = player[position]
                        if player_position and not positions_id.get(player_position, 0):
                            log.warning(f"Invalid position {position} for player {player_name} ({player_id}): {player_position}. Authorized values are: {', '.join(positions_id.keys())}")
        
    except Exception as e:
        log.error(f"Error while writing players data to roster: {e}")


