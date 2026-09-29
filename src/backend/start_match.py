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
from PyQt5.QtCore import *
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

# Custom modules
from backend.game_specific_variables import *
from shared.config import *
from backend.R08_handler import *
import backend.game_files_processor as game_files_processor
import backend.mod_utils as mod_utils
from backend import audio_patch
from shared.game_profile import game_profile

from shared.log import get_logger, setup_logging

log = get_logger(__name__)


# This is the main function of this file, which starts a match with the data provided in match_data
# It is the only function you should use
def start_match(match_data, copy_static_files = True, create_mission_file = True, edit_graphics_files = True, edit_teams_name = True, edit_roster_file = True, start_R08 = True, clean_files = False, progress_callback = None):
    """
    The content of the input argument match_data must match the structure described in 'match_data.yaml', converted to a python dict.
    For example:
    match_data = {
        'difficulty': 'elite',
        'half_time_length': '2m',
        ...
        ...
        
        'referee': {
            'face': 'some_path/face.big'
            'kit_front': 'some_path/face.big'
            'kit_back': 'some_path/kit_back.fsh'
        },
      
        'team_A': {
            'name': "Team name",
            'kit_front': 'some_path/face.big',
            'kit_back': 'some_path/kit_back.fsh',
            'logo': 'some_path/logo.png',
            ...
            ...
            'roles': {'captain': 8,  'vice-captain': 5, 'kick_off': 10, 'long_GK': 15, 'long_punt': 15, 'short_GK': 10, 'short_punt': 10},
            'set_plays': ["classic", "pivot", "pocket", "dummy_switch"],
      
            'players': [
                {'name': "Player 1", 'pos1': "loosehead_prop", 'pos2': "", 'pos3': "", 'face': "some_path/face.big", ...},
                {'name': "Player 2", 'pos1': "hooker", 'pos2': "", 'pos3': "", 'face': "some_path/face.big" ...},
                ...
                ...
            ],
        },
        'team_B': {
            ...
            ...
        }
    }

    progress_callback, when given, is called as
    progress_callback(start_fraction, end_fraction, label) before each
    preparation step (file generation, proxy deployment), with the fractions in
    [0.0, 1.0] bracketing that step's share of the work: start = already done,
    end = done once the step completes. Knowing the span lets the caller keep a
    progress bar moving *inside* a long step instead of freezing. It is called
    once more with (1.0, 1.0) right before the game executable is started.
    Exceptions raised by it are swallowed.
    """

    # Relative cost of each preparation step, used to build the reported
    # fraction: the graphics and roster steps (BIG/FSH repacking, player faces)
    # dominate, the rest is quick file copying.
    step_weights = {
        'clean':    3,
        'static':   8,
        'mission':  4,
        'graphics': 40,
        'teams':    5,
        'roster':   32,
        'proxy':    8,
    }
    total_weight = sum(step_weights.values())
    done_weight = 0

    def report(step, label):
        """Announce the step about to run (with the span it covers), then
        account for its cost."""
        nonlocal done_weight
        log.info(label)
        end_weight = done_weight + step_weights[step]
        if progress_callback:
            try:
                progress_callback(done_weight / total_weight,
                                  end_weight / total_weight, label)
            except Exception as e:
                log.warning(f"Progress callback failed: {e}")
        done_weight = end_weight

    # This removes all the non-original R08 files
    report('clean', "Cleaning game files")
    game_files_processor.clean_generated_files()
    if clean_files:
        game_files_processor.clean_non_original_files()
        log.info("Non-original game files removed")


    # This copies the statics (already modified files that does not need to be edited again) files into the game directory
    report('static', "Copying static files")
    if copy_static_files:
        game_files_processor.copy_static_files()
    else:
        log.debug("Statics files not copied")

    # aems.big is not shipped: the game's own copy gets its loop music
    # silenced in place (one directory read when already done).
    audio_patch.ensure_patched()
    
    # The game's settings: profile template copied to the game folder and edited
    # with the user's choices from Settings. Runs after the static files so it
    # always wins over a user_profile.pro shipped there.
    game_profile.deploy()

    # This creates the mission file that will be launched at game startup
    report('mission', "Creating mission file")
    if create_mission_file:
        game_files_processor.create_mission_file(match_data)
    else:
        log.debug("Mission file not created")
    
    # This copies all the graphic files into the game directory (except player faces)
    report('graphics', "Building graphics files")
    if edit_graphics_files :
        game_files_processor.edit_graphics_files(match_data)
    else:
        log.debug("Graphics files not created")
    
    # This writes teams data into the roster
    report('teams', "Writing team names")
    if edit_teams_name:
        game_files_processor.edit_teams_name(match_data)
    else:
        log.debug("Teams name not edited")
    
    # This writes the players data in the roster and copies custom player faces into the game directory
    report('roster', "Writing roster and player faces")
    if edit_roster_file:
        game_files_processor.edit_roster_file(match_data)
    else:
        log.debug("Roster file not edited")

    # Deploy the d3d8 proxy (windowed mode + embeddable window + patches)
    report('proxy', "Deploying windowing patches")
    if config.use_d3d8_proxy:
        mod_utils.configure_d3d8_proxy()
    else:
        log.debug("No windowing helper used (d3d8 proxy off)")
            
    if progress_callback:
        try:
            progress_callback(1.0, 1.0, "Starting Rugby 08")
        except Exception as e:
            log.warning(f"Progress callback failed: {e}")

    # Start the R08 executable
    if start_R08:
      r08 = R08_handler()
      #game_ready = pyqtSignal()
      #r08.start_R08_executable(game_ready.emit)
      r08.start_R08_executable(None)
      # Parsed by R08_handler once the game returns to its menu; None if the
      # game exited without one (or in simulation mode).
      return r08.match_result
    else:
        log.debug("R08 executable not started")
    return None
    

# Start the match if this script is run directly (not loaded as a module)
if __name__ == "__main__":

    def ask_confirmation(prompt):
        while True:
            response = input(f"{prompt} (y/n): ").strip().lower()
            if response in ["y", "yes"]:
                return True
            elif response in ["n", "no"]:
                return False
            else:
                print("Please enter 'y' or 'n'.")



    parser = argparse.ArgumentParser(description="Configure and start a match")
    parser.add_argument("match_config_file_positional", nargs="?", type=str, metavar="FILE", help="YAML match configuration file (positional, equivalent to --match-config-file)")
    parser.add_argument("--match-config-file", dest="config_file", type=str, metavar="FILE", help="YAML match configuration file", required=False)
    parser.add_argument("--show-config", dest="show_config", action="store_true", help="Print the loaded configuration and exit")
    parser.add_argument("--no-static-files", dest="copy_static_files", action="store_false", help="Don't copy the static files")
    parser.add_argument("--no-mission-file", dest="create_mission_file", action="store_false", help="Don't create the mission file")
    parser.add_argument("--no-graphics-files", dest="edit_graphics_files", action="store_false", help="Don't edit the graphics files")        
    parser.add_argument("--no-teams-name", dest="edit_teams_name", action="store_false", help="Don't edit the teams name")
    parser.add_argument("--no-roster-file", dest="edit_roster_file", action="store_false", help="Don't edit the roster file")
    parser.add_argument("--no-exec", dest="start_r08", action="store_false", help="Don't start the R08 executable")   
    parser.add_argument("--read-dump", dest="read_dump_file", type=str, metavar="FILE", help="Read a memory dump file and exit")
    parser.add_argument("--clean-files", dest="clean_files", action="store_true", help="Remove all but original files from R08 folder. USE WITH CAUTION!")
    parser.add_argument("--log-level", dest="log_level", default=None, metavar="LEVEL", help="DEBUG, INFO, WARNING or ERROR (default: log_level in config.ini, else INFO; OFF in the released exe)")
    parser.add_argument("--no-warning", dest="disable_warnings", action="store_true", help="Disable warnings for dangerous actions")
    args = parser.parse_args()
    setup_logging(args.log_level)

    # If a positional config file is provided, override --match-config-file
    if args.match_config_file_positional:
        args.config_file = args.match_config_file_positional
    
    match_data = None
    
    # Print configuration
    if args.show_config:
        config.print_all()

    # Read memory dump file
    elif args.read_dump_file:
        with open(os.path.join(config.temp_directory, "dump.bin"), 'rb') as file:
          memory_dump = file.read()
          r08 = R08_handler()
          r08.read_match_result(memory_dump)

    # Load config and start match
    else:

        # Ask confimation for cleaning files
        if args.clean_files and not args.disable_warnings:
            if not ask_confirmation(f"Warning: all the non-original files will be deleted from {config.game_launcher_directory}.\nPlease confirm"):
                log.info("Action cancelled by user. Aborting.")
                exit(0)

        try:
            with open(args.config_file, "r") as file:
                match_data = yaml.safe_load(file)
                
        except Exception as e:
            log.error(f"cannot read the match file {args.config_file}: {e}. Aborting.")
        
        if match_data != None:
            log.info(f"Successfully loaded match data from file: {args.config_file}")
            start_match(match_data, args.copy_static_files, args.create_mission_file, args.edit_graphics_files, args.edit_teams_name, args.edit_roster_file, args.start_r08, args.clean_files)
        
        
    



