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

from shared.game_profile import game_profile, PROFILE_ADDRESS, PROFILE_SIZE
from backend import match_memory as mm
from backend.lineup_tracker import LineupTracker
from shared.log import get_logger

log = get_logger(__name__)

# Displayed clock (seconds) at which each period ends: halves, then extra time
# (two halves and the sudden-death period). The game stops the clock there
# (FUN_00421aa0..FUN_00421ae0). Period 5 = the drop-goal shootout after it.
PERIOD_ENDS = (2400, 4800, 5400, 6000, 6600)
SHOOTOUT_PERIOD = 5

# On the pitch (reR08 patches_dll/cards.cpp): world+0x68 / +0x6C = home / away
# team; team+0xD0+i*4 = the Player in position i (1..15); Player+0x10 = its
# record, Player+0x70 bit0 = off the pitch.
WORLD_TEAMS = 0x68
TEAM_POSITIONS = 0xD0
PLAYER_RECORD_PTR = 0x10
PLAYER_FLAGS = 0x70
POSITIONS = range(1, 16)


class R08_handler:
    def __init__(self):

        self.screen_controller_selection_reached = False
        self.match_started = False
        self.match_finished = False
        self.match_result = None
        # Scores seen while the match is played, timestamped with the match
        # clock: [{"team": "team_A", "slot": 0-21, "id": roster id,
        #          "type": "try", "clock": seconds}, ...]
        self.score_timeline = []
        self._score_snapshot = None
        self._last_score_poll = 0.0
        # Last match clock read during play (displayed seconds), its period and
        # the real time played (seconds)
        self.match_clock = None
        self.match_period = None
        self.match_real_time = None
        # What the game zeroes when its menu comes back, from the last read
        # during the match: {team: match_memory.read_score()}
        self.live_score = None
        # (team, roster slot) of the Man of the Match: the game names one at
        # every final whistle, never on a quit
        self.man_of_the_match = None
        self.lineup = LineupTracker()
        # Last read of the game's in-memory profile (in-game option changes)
        self.profile_snapshot = None
        self._last_profile_poll = 0.0
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

            if self.screen_controller_selection_reached and not self.match_finished \
                    and current_screen_id != 0x0032 \
                    and time.time() - self._last_score_poll >= config.score_poll_interval:
                self._last_score_poll = time.time()
                self.poll_match()

            # The options can be changed during the match, then the game is
            # killed (or crashes) with them only in memory: keep the latest.
            if self.screen_controller_selection_reached \
                    and time.time() - self._last_profile_poll >= config.profile_poll_interval:
                self._last_profile_poll = time.time()
                self.poll_profile()

            # DEBUG
            #edit_game_memory(self.R08_pid)

            time.sleep(0.1)

        exit_code = get_process_exit_code(self.R08_handle)
        log.info(f'Process ended with code {exit_code}')
        if self.profile_snapshot is not None:
            try:
                game_profile.import_ingame(self.profile_snapshot)
            except Exception as e:
                log.warning(f"Could not import the in-game settings: {e}")
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
            if exit_code is not None and (exit_code & 0xFFFFFFFF) == 0xC0000005:
                # The patches DLL's crash handler logs the faulting address in
                # rugby08_patches.log ("[crash] EXCEPTION"). When it is missing
                # there, Windows' own record names the faulting module.
                log.warning("Rugby08 crashed with an access violation (0xC0000005). If "
                            "rugby08_patches.log has no '[crash] EXCEPTION' record, see Windows "
                            "Event Viewer > Windows Logs > Application, 'Application Error' "
                            "(event 1000) for Rugby08.exe: faulting module name and offset.")

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

    # Read the game's in-memory profile (its options). Only kept once the
    # match is set up: the boot has long loaded user_profile.pro by then.
    def poll_profile(self):
        if not config.import_ingame_settings:
            return
        data = read_memory(self.R08_handle, PROFILE_ADDRESS, PROFILE_SIZE)
        if data is not None and len(data) == PROFILE_SIZE:
            self.profile_snapshot = bytes(data)

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
        self.score_timeline = []
        self._score_snapshot = None
        self.match_clock = None
        self.match_period = None
        self.match_real_time = None
        self.live_score = None
        self.man_of_the_match = None
        self.lineup = LineupTracker()

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
            self.poll_match()       # a score in the last moments before the whistle
            self.match_finished = True
        else:
            log.warning("Full-time screen seen without any controller selection: ignored")


    # True only if the current match was played to full time: the game went
    # through controller selection (match set up) and named a Man of the Match,
    # which it does at the final whistle and never on a quit (0x43E6D0, only
    # reached from the referee's end-of-period handler 0x43BAFA). A match
    # decided by the drop-goal shootout ends elsewhere, without one: there the
    # full-time screen (0x0033) in the shootout period is all there is.
    def is_match_finished(self):
        if not self.screen_controller_selection_reached:
            return False
        if self.man_of_the_match is not None:
            return True
        return bool(self.match_finished and self.match_period == SHOOTOUT_PERIOD)

    # (displayed clock in seconds, period, real seconds played) while a match
    # is played, else None. The displayed clock is the one on screen (80-minute
    # scale whatever the half length) and the one .mis start times and
    # challenge minutes use; the match object's own clock counts real seconds.
    def read_match_clock(self):
        import struct
        world = self.read_world()
        if not world:
            return None
        raw = read_memory(self.R08_handle, world + config.memory_addresses['world_clock_offset'], 4)
        if not raw or len(raw) < 4:
            return None
        real = struct.unpack('<f', raw)[0]
        if not real > 0:
            return None
        raw = read_memory(self.R08_handle, config.memory_addresses['match_clock'], 5)
        if not raw or len(raw) < 5:
            return None
        clock, period = struct.unpack('<f', raw[:4])[0], raw[4]
        if not (0 <= clock <= PERIOD_ENDS[-1]) or period > SHOOTOUT_PERIOD:
            return None
        return clock, period, real

    # Read the match clock into match_clock / match_period / match_real_time
    # and return the displayed clock (None before play). It only runs forward
    # during a match: a lower reading is the game resetting it on the way out
    # of the match, and is ignored.
    def update_match_clock(self):
        reading = self.read_match_clock()
        if reading is not None and (self.match_clock is None or reading[0] >= self.match_clock):
            self.match_clock, self.match_period, self.match_real_time = reading
        return self.match_clock if reading is not None else None

    def read_world(self):
        raw = read_memory(self.R08_handle, config.memory_addresses['world_ptr'], 4)
        return int.from_bytes(raw, 'little') if raw and len(raw) == 4 else None

    def read_setup(self):
        start = config.memory_addresses['match_setup']
        return dump_memory(self.R08_handle, start, start + mm.SETUP_SIZE)

    # Who is in each position: ({team: {pos: {"id", "off"}}}, {team: {id:
    # {"red", "injury"}}}), or None. About 35 small reads.
    def read_lineups(self, block):
        world = self.read_world()
        raw = read_memory(self.R08_handle, world + WORLD_TEAMS, 8) if world else None
        if not raw or len(raw) < 8:
            return None
        setup = config.memory_addresses['match_setup']
        lineups = {}
        for i, team in enumerate(mm.TEAM_RECORDS):
            team_ptr = int.from_bytes(raw[4 * i:4 * i + 4], 'little')
            slots = read_memory(self.R08_handle, team_ptr + TEAM_POSITIONS, 4 * 16) if team_ptr else None
            if not slots or len(slots) < 64:
                return None
            positions = {}
            for pos in POSITIONS:
                player = int.from_bytes(slots[4 * pos:4 * pos + 4], 'little')
                data = read_memory(self.R08_handle, player + PLAYER_RECORD_PTR,
                                   PLAYER_FLAGS - PLAYER_RECORD_PTR + 1) if player else None
                if not data or len(data) < PLAYER_FLAGS - PLAYER_RECORD_PTR + 1:
                    continue
                where = mm.record_slot(setup, int.from_bytes(data[:4], 'little'))
                if where is None:
                    continue
                pid = mm.read_player(block, *where)['id']
                positions[pos] = {'id': pid, 'off': bool(data[PLAYER_FLAGS - PLAYER_RECORD_PTR] & 1)}
            lineups[team] = positions
        records = {}
        for team in mm.TEAM_RECORDS:
            records[team] = {}
            for slot in range(mm.ROSTER_SLOTS):
                player = mm.read_player(block, team, slot)
                if player['id']:
                    records[team][player['id']] = {'red': player['red_cards'],
                                                   'injury': player['injury']}
        return lineups, records

    # One read of the match while it is played (every score_poll_interval):
    # clock, scores (every counter that went up since the previous read is a
    # score at the current clock; the first read is the baseline, so the score
    # a mission starts on is not counted as scored in play), the team scores
    # the game will zero, the Man of the Match and who plays where.
    def poll_match(self):
        clock = self.update_match_clock()
        if clock is None:
            return
        block = self.read_setup()
        if not block or len(block) < mm.SETUP_SIZE:
            return
        self.live_score = {team: mm.read_score(block, team) for team in mm.TEAM_RECORDS}
        self.man_of_the_match = mm.man_of_the_match(block) or self.man_of_the_match
        self._track_scores(block, clock)
        lineups = self.read_lineups(block)
        if lineups is not None:
            self.lineup.update(clock, self.match_period, self.match_real_time, *lineups)

    def _track_scores(self, block, clock):
        snapshot = mm.scoring_snapshot(block)
        previous, self._score_snapshot = self._score_snapshot, snapshot
        if previous is None:
            log.debug(f"Score tracking from {clock / 60:.1f} min")
            return
        for key, (pid, counts) in snapshot.items():
            before = previous.get(key, (pid, {}))[1]
            for kind, n in counts.items():
                for _ in range(max(0, n - before.get(kind, 0))):
                    self.score_timeline.append({'team': key[0], 'slot': key[1], 'id': pid,
                                                'type': kind, 'clock': round(clock, 1)})
                    log.info(f"Score: {key[0]} #{key[1] + 1} {kind} at {clock / 60:.1f} min")

    # Action to be performed when the game menu is reached
    # Note: this should happen only when the match is finished
    def action_on_game_menu_reached(self):
        log.info("Game menu reached")

        # Ensure this is the end of the match (we previously reached the team controller selection)
        if self.screen_controller_selection_reached:
            block = self.read_setup()
            if block and len(block) >= mm.SETUP_SIZE:
                self.man_of_the_match = mm.man_of_the_match(block) or self.man_of_the_match
            finished = self.is_match_finished()
            if finished:
                log.info("End of the match reached")
            else:
                # Left the match before full time: the stats in memory are partial
                log.warning("Back at the menu but the match was not played to full time: reading the partial result")

            self.match_result = self.read_match_result(block)
            if self.match_result is not None:
                self.match_result['finished'] = finished
                if not finished:
                    log.info(f"Match interrupted at minute {self.match_result['minute']}")

            self.poll_profile()     # options changed since the last poll

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

    # The match result from the block read at the menu (players' and teams'
    # counters survive there) and what was read during the match (scores,
    # clock, Man of the Match, lineups). None without a readable block.
    def read_match_result(self, block):
        if config.simulation_mode:
            return
        if not block or len(block) < mm.SETUP_SIZE:
            log.warning("No memory dump")
            return

        with open(os.path.join(config.temp_directory, "dump.bin"), 'wb') as file:
            file.write(block)

        result = {team: mm.read_team(block, team, (self.live_score or {}).get(team))
                  for team in mm.TEAM_RECORDS}
        for team in mm.TEAM_RECORDS:
            played = self.lineup.summary(team)
            for player in result[team]['players']:
                time_played = played.get(player['id'], {})
                player['seconds_on_field'] = time_played.get('seconds', 0.0)
                player['real_seconds_on_field'] = time_played.get('real_seconds', 0.0)
                player['positions'] = time_played.get('positions', {})
                player['real_positions'] = time_played.get('real_positions', {})
            result[team]['starting_lineup'] = {pos: p['id'] for pos, p in
                                               sorted(((self.lineup.starting or {}).get(team) or {}).items())}
        motm = None
        if self.man_of_the_match is not None:
            team, slot = self.man_of_the_match
            player = mm.read_player(block, team, slot)
            motm = {'team': team, 'id': player['id'], 'name': player['name']}
        result.update({
            # None = the clock was never readable, so nothing was timed
            'events': list(self.score_timeline) if self._score_snapshot is not None else None,
            'lineup_events': list(self.lineup.events) if self.lineup.lineups is not None else None,
            'man_of_the_match': motm,
            'clock': self.match_clock,
            'period': self.match_period,
            'real_time': self.match_real_time,
            'minute': int(self.match_clock // 60) if self.match_clock is not None else None,
        })

        log.info("===== RESULT =====")
        for team in mm.TEAM_RECORDS:
            log.info(f"== {team}: {result[team]['score']}")
            log.info(f"stats: {result[team]['stats']}")
            for player in result[team]['players']:
                player_stats = {x: player[x] for x in player if x not in ('name',)}
                log.debug(f"{player['name']} \t {player_stats}")
            log.debug(f"Substitutions: {result[team]['substitutions']}")
        log.info(f"Man of the Match: {motm}")
        for event in result['lineup_events'] or []:
            log.info(f"Lineup: {event}")
        return result
