from concurrent.futures import process
import ctypes
import subprocess
import time
from screeninfo import get_monitors
import tkinter as tk
from PIL import Image, ImageTk
import threading
import os
import psutil
import sys
from pathlib import Path
sys.path.append(str(Path(__file__).parent.parent))

from shared.config import *
from backend.process_handler import *
from backend.overlay import *

from shared.log import get_logger

log = get_logger(__name__)


class R08_handler:
    def __init__(self):

        self.screen_controller_selection_reached = False
        self.match_started = False
        self.match_finished = False
        self.match_result = None
        self.R08_pid = None
        self.R08_handle = None

    def start_R08_executable(self, execute_when_ready = None):
        if config.simulation_mode:
            return
        
        previous_screen_id = None
        previous_boot_counter = None

        pids_before = find_game_pids() if config.platform == "linux" else set()

        # Start R08 executable
        self.R08_pid, self.R08_handle = start_process(config.game_launcher_executable_filepath, config.game_launcher_arguments, config.game_launcher_directory, config.game_launcher_environment)
        log.info(f"Launched process with PID: {self.R08_pid}")
        if config.platform == "windows" and self.R08_pid:   # TEMPORARY first-launch diagnostics
            try:
                from backend import launch_diag
                launch_diag.log_launcher_context()
                launch_diag.watch_game_modules(self.R08_pid, config.game_launcher_directory)
            except Exception as e:
                log.info(f"[diag] launch diagnostics failed: {e}")

        # Get process handle for Windows
        if config.platform == "windows":
            self.R08_handle = get_windows_process_handle(self.R08_pid)
        else:
            # Wine: the launched process may only be a launcher (see process_handler)
            self.R08_pid, self.R08_handle = resolve_linux_game_process(self.R08_handle, pids_before)
            
        # Display overlay
        if config.display_overlay_during_init:
            display_fullscreen_image(image_path)
            
        # Mute the game
        # WARNING not implemented
        if config.mute_game_during_init:
            pass

        # Wait for the R08 executable to start. Bounded: if it dies (crash,
        # missing dll, bad wine setup, ...) before ever exposing a readable
        # screen ID, `is_process_running` alone can't tell us apart from "still
        # booting" — without this, a dead process with no readable memory
        # left this spinning forever (seen live: python pinned at high CPU,
        # the game a zombie under it, no match ever read because we never
        # got past this loop to notice the death).
        boot_deadline = time.time() + config.R08_boot_timeout_seconds
        while self.get_current_screen_id(self.R08_handle) is None:
          if not is_process_running(self.R08_handle):
            log.error(f"Rugby08 exited (PID {self.R08_pid}) before its memory became readable; "
                      "no match will be tracked. Check the game/proxy logs next to the exe.")
            return
          if time.time() > boot_deadline:
            log.error(f"Rugby08 (PID {self.R08_pid}) did not become readable within "
                      f"{config.R08_boot_timeout_seconds:.0f}s; giving up.")
            return
          time.sleep(0.1)

        # While the R08 executable is running
        while is_process_running(self.R08_handle):

            # Read the current screen ID in memory
            current_screen_id = self.get_current_screen_id(self.R08_handle)

            # DEBUG: loading progress counter (Rugby08.exe + 0x6A6270), used by
            # the frontend loading bar — log it whenever it changes
            current_boot_counter = self.get_boot_counter(self.R08_handle)
            if current_boot_counter != previous_boot_counter:
                log.debug(f"Boot counter [0x{int(getattr(config, 'boot_counter_address', 0) or 0):08X}]: {current_boot_counter}")
                previous_boot_counter = current_boot_counter


            # If the screen has changed. A None reading (memory momentarily
            # unreadable — normal right as the process exits, on both
            # platforms) is not a screen: skip it rather than treat it as one,
            # so it neither crashes the ":04X" format below nor gets latched
            # into previous_screen_id (which would mask the real next change).
            if current_screen_id is not None and current_screen_id != previous_screen_id:
                log.info(f"Screen ID changed: 0x{current_screen_id:04X}")
                previous_screen_id = current_screen_id
                
                # If current screen is controller selection
                if current_screen_id ==  0x0321:
                    self.action_on_controller_selection_screen_reached()
                    
                # If the match has been finished
                elif current_screen_id == 0x0033:
                    self.action_on_match_finished()
                  
                # If current screen is game menu (no match is being played)
                elif current_screen_id == 0x0032:
                    self.action_on_game_menu_reached()

            # DEBUG
            #edit_game_memory(self.R08_pid)

            time.sleep(0.1)

        exit_code = get_process_exit_code(self.R08_handle)
        log.info(f'Process ended with code {exit_code}')
        try:
            from backend.mod_utils import log_game_session
            log_game_session(config.game_launcher_directory)
        except Exception as e:
            log.warning(f"Could not copy the game log: {e}")
        if self.match_result is None and self.screen_controller_selection_reached:
            # It went through match setup but exited (crash, force-quit, ...)
            # without ever showing the game menu again, so action_on_game_menu_reached
            # never ran and nothing got dumped from memory — by then the
            # process is gone and there is nothing left to read.
            log.warning("Rugby08 exited without returning to the game menu: no match result to read")

        # WARNING needed ?
        if config.platform == "windows":
            #CloseHandle(self.R08_handle)
            pass

    # Return the current R08 screen ID     
    def get_current_screen_id(self, R08_process_handle):
        memory_value = read_memory(R08_process_handle, config.memory_addresses['screen_id'], 2)

        if memory_value != None:
          return int.from_bytes(memory_value, byteorder='little')
        else:
          return None

    # Return the game's boot progress counter (dword at config.boot_counter_address)
    def get_boot_counter(self, R08_process_handle):
        address = int(getattr(config, "boot_counter_address", 0) or 0)

        if not address:
          return None

        memory_value = read_memory(R08_process_handle, address, 4)

        if memory_value != None:
          return int.from_bytes(memory_value, byteorder='little')
        else:
          return None


    # Action to be performed when the controller selection screen is reached
    def action_on_controller_selection_screen_reached(self):
        log.info("Controller selection screen reached")
        self.screen_controller_selection_reached = True
        # A (new) match is being set up: forget any full time from a previous one
        self.match_finished = False

    #    if execute_when_ready:
    #        time.sleep(0.5)
    #        execute_when_ready()
        
        if config.display_overlay_during_init:
            #tkRoot.destroy()
            pass

    # Action to be performed when the match is finished (based on in-game screen ID)
    def action_on_match_finished(self):
        if self.screen_controller_selection_reached:
            log.info("Match finished")
            self.match_finished = True
        else:
            log.warning("Full-time screen seen without any controller selection: ignored")

        #match_result_dump = dump_memory(process_handle, memory_addresses['match_result_start'], memory_addresses['match_result_end'])
        #self.read_match_result(match_result_dump)
        #print(f"Match result dumped. Length: {len(match_result_dump)}")

    # True only if the current match was played to full time: the game went
    # through controller selection (match set up) and then its full-time screen
    # (0x0033), in that order. Reaching the menu alone is not enough, since
    # quitting mid-match (or a crash back to the menu) lands there too.
    def is_match_finished(self):
        return bool(self.screen_controller_selection_reached and self.match_finished)

    # Minute of play from the 4-byte clock in the result block, or None when it
    # does not look like a match clock. The unit is not documented: it is read
    # as float32 seconds first, then as uint32 seconds, and accepted only if the
    # result is within a plausible match length (<= 2 h). Unverified against a
    # real interrupted match — check the "Match clock raw" DEBUG line.
    @staticmethod
    def decode_match_minute(raw):
        import struct
        if not raw or len(raw) < 4:
            return None
        raw = bytes(raw[:4])
        log.debug(f"Match clock raw: {raw.hex()}")
        candidates = []
        try:
            candidates.append(struct.unpack('<f', raw)[0])
        except struct.error:
            pass
        candidates.append(float(int.from_bytes(raw, 'little')))
        for seconds in candidates:
            if seconds == seconds and 0 < seconds <= 7200:
                return int(seconds // 60)
        return None

    # Action to be performed when the game menu is reached
    # Note: this should happen only when the match is finished
    def action_on_game_menu_reached(self):
        log.info("Game menu reached")

        # Ensure this is the end of the match (we previously reached the team controller selection)
        if self.screen_controller_selection_reached:
            finished = self.is_match_finished()
            if finished:
                log.info("End of the match reached")
            else:
                # Left the match before full time: the stats in memory are partial
                log.warning("Back at the menu but the match was not played to full time: reading the partial result")

            match_result_dump = dump_memory(self.R08_handle, config.memory_addresses['match_result_start'], config.memory_addresses['match_result_end'])
            self.match_result = self.read_match_result(match_result_dump)

            if self.match_result is not None:
                self.match_result['finished'] = finished
                self.match_result['minute'] = self.decode_match_minute(self.match_result['time'])
                if not finished:
                    log.info(f"Match interrupted at minute {self.match_result['minute']}")

            if match_result_dump != None:
              log.debug(f"Match result dumped. Length: {len(match_result_dump)}")

            log.info("Exit game")
            if config.platform == "windows":
                # No pkill on Windows: without this the game sits on its own
                # menu (fullscreen, on top of the mod) after full time.
                try:
                    psutil.Process(self.R08_pid).terminate()
                except psutil.Error as e:
                    log.warning(f"Could not terminate Rugby08 ({self.R08_pid}): {e}")
            else:
                # Warning: This is dirty temp code, to be fixed later
                subprocess.run("pkill Rugby08.exe", shell=True)
        else:
            pass


    # DEBUG
    def edit_game_memory(self, pid):
        # Address to modify
        address_to_modify = 0x009F9CB8
        data_to_write = b'\x21'

        try:
            modify_memory(pid, address_to_modify, data_to_write)
        
        except Exception as e:
            log.error(f"Error modifying memory: {e}")

    # Parse the memory dump and return the match result
    def read_match_result(self, memory_dump):
        if config.simulation_mode:
            return

        if memory_dump == None:
            log.warning("No memory dump")
            return
        
        def read_player(pos):
            player = {
                'id': int.from_bytes(memory_dump[pos:pos+2], byteorder='little'),
                'name': memory_dump[pos+4:pos+4+16].decode('utf-8').rstrip('\x00'),
                'penalties_scored': memory_dump[pos+0x3E],
                'penalties_attempted': memory_dump[pos+0x3F],
                'conversions_scored': memory_dump[pos+0x40],
                'conversions_attempted': memory_dump[pos+0x41],
                'drop_goals': memory_dump[pos+0x42],
                'yellow_cards': memory_dump[pos+0x44],
                'red_cards': memory_dump[pos+0x45],
                'tries': memory_dump[pos+0x48],
                'tackles': memory_dump[pos+0x4A],
                'injury': memory_dump[pos+0x50],
                }
            
            return player
        
        def read_scrums_and_lineouts(pos):
            scrum_and_lineouts = {
                'scrums_won_own': int.from_bytes(memory_dump[pos:pos+2], byteorder='little'),
                'scrums_won_opp': int.from_bytes(memory_dump[pos+2:pos+4], byteorder='little'),
                'lineouts_won_own': int.from_bytes(memory_dump[pos+4:pos+6], byteorder='little'),
                'lineouts_won_opp': int.from_bytes(memory_dump[pos+6:pos+8], byteorder='little'),
            }
            
            return scrum_and_lineouts
        
        def read_substitution(pos):
            substitution = {
                'player_in': 0,
                'player_out': memory_dump[pos:pos+2],
                'time': memory_dump[pos+4:pos+6],
            }
            
        with open(os.path.join(config.temp_directory, "dump.bin"), 'wb') as file:
            file.write(memory_dump)
            
        # Team A
        offsets = {
            'time': 0x1A00,
            'team_A': {
                'players': 0x110,
                'scrums_and_lineouts': 0xD64,
                'substitutions': 0xD0C,
            },
            'team_B': {
                'players': 0x110 + 0xC60,
                'scrums_and_lineouts': 0xD64 + 0xC60,
                'substitutions': 0xD0C + 0xC60,
            },
        }
            
        match_result = {
            'time': memory_dump[offsets['time']:offsets['time']+4],
            'half_time': memory_dump[offsets['time']+4],
            'team_A': {
                'score': None,
                'players': [],
                'substitutions': [],
                'stats': {},
            },
            'team_B': {
                 'score': None,
                'players': [],
                'substitutions': [],
                'stats': {},
            },
        }
        
        for team in ['team_A', 'team_B']:
            for index_player in range(22):
                player_result = read_player(offsets[team]['players'] + index_player * 0x64)
                match_result[team]['players'].append(player_result)
                
            for index_substitution in range(7):
                subsitution = read_substitution(offsets[team]['substitutions'] + index_substitution * 0x64)
                match_result[team]['substitutions'].append(subsitution)
        
            match_result[team]['stats'].update(read_scrums_and_lineouts(offsets[team]['scrums_and_lineouts']))

            # The game never populates a team score field, so derive it from
            # the per-player scoring events. (This block also used to end in a
            # stray comma, which made 'score' a 1-tuple rather than a dict.)
            score = {
                'points': 0,
                'tries': 0,
                'conversions': 0,
                'penalties': 0,
                'drop_goals': 0,
                'yellow_cards': 0,
                'red_cards': 0,
                'tackles': 0,
            }
            for player in match_result[team]['players']:
                score['tries'] += player['tries']
                score['conversions'] += player['conversions_scored']
                score['penalties'] += player['penalties_scored']
                score['drop_goals'] += player['drop_goals']
                score['yellow_cards'] += player['yellow_cards']
                score['red_cards'] += player['red_cards']
                score['tackles'] += player['tackles']
            score['points'] = (score['tries'] * 5 + score['conversions'] * 2
                               + score['penalties'] * 3 + score['drop_goals'] * 3)
            match_result[team]['score'] = score


        log.info("===== RESULT =====")
        log.info(f"Time: {match_result['time']} halftime:{match_result['half_time']}")
        for team in ['team_A', 'team_B']:
            log.info(f"== {team}:")
            log.info(f"stats: {match_result[team]['stats']}")
            #for stats in match_result[team]['stats']:
                #team_stats_str = ", ".join("{}: {}".format(k, v) for k, v in stats.items())
                #print(f"{team_stats_str}")
            for player in match_result[team]['players']:
                player_stats = {x: player[x] for x in player if x not in ['name']}
                player_stats_str = ", ".join("{}: {}".format(k, v) for k, v in player_stats.items())
                log.debug(f"{player['name']} \t {player_stats_str}")
            log.debug("Substitutions:")
            for sub in match_result[team]['substitutions']:
                log.debug(f"{sub}")

        return match_result

