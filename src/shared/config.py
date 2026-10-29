import platform
import os
import configparser
import pprint
import sys
import shutil
import tempfile

from shared.app_paths import (FROZEN, app_directory, app_data_directory, check_writable_or_exit,
                              is_portable, mod_data_directory,
                              user_data_directory)
from shared.original_game_files import ORIGINAL_GAME_FILES, ORIGINAL_GAME_FOLDERS


from shared.log import get_logger

log = get_logger(__name__)


def _game_dir_candidates():
  """Best-effort guesses of where Rugby 08 is installed (Windows only)."""
  found = []
  try:
    import winreg
    uninstall = r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall"
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
      for view in (winreg.KEY_WOW64_32KEY, winreg.KEY_WOW64_64KEY):
        try:
          base = winreg.OpenKey(root, uninstall, 0, winreg.KEY_READ | view)
        except OSError:
          continue
        i = 0
        while True:
          try:
            name = winreg.EnumKey(base, i)
          except OSError:
            break
          i += 1
          try:
            with winreg.OpenKey(base, name) as k:
              display = winreg.QueryValueEx(k, "DisplayName")[0]
              if "rugby 08" in str(display).lower():
                loc = winreg.QueryValueEx(k, "InstallLocation")[0]
                if loc:
                  found.append(loc)
          except OSError:
            pass
  except ImportError:
    pass
  for env in ("ProgramFiles(x86)", "ProgramFiles", "ProgramW6432"):
    pf = os.environ.get(env)
    if pf:
      for vendor in ("EA SPORTS", "EA SPORT", "EA Games", "Electronic Arts"):
        for game in ("EA SPORTS(TM) Rugby 08", "Rugby 08", "EA SPORTS Rugby 08"):
          found.append(os.path.join(pf, vendor, game))
  # mod installed as <game>/R08_mod (the historical layout)
  found.append(os.path.dirname(app_directory().rstrip("\\/")))
  return found


def find_game_directory(exe_name="Rugby08.exe"):
  for cand in _game_dir_candidates():
    if cand and os.path.isfile(os.path.join(cand, exe_name)):
      return cand
  return None


def _needs_installer(config_filepath):
  """Installed (non-portable) exe with no valid config: setup is the installer's job."""
  import tkinter as tk
  from tkinter import messagebox
  root = tk.Tk()
  root.withdraw()
  messagebox.showerror("Rugby 08 Revival",
                       "Rugby 08 Revival is not set up (no valid configuration found in:\n"
                       f"{config_filepath}).\n\n"
                       "Run the Rugby 08 Revival installer (R08Revival_<version>_setup.exe): it makes a "
                       "copy of your Rugby 08 game for the mod to work on and writes the settings.")
  root.destroy()
  sys.exit(1)


def _first_run_setup(config_filepath):
  """Portable copy or source checkout: locate Rugby 08 and write config.ini.
  Returns True if written. (An installed copy is configured by the separate
  installer, see packaging/.)"""
  exe_name = "Rugby08.exe"
  game_dir = find_game_directory(exe_name)
  if not game_dir:
    import tkinter as tk
    from tkinter import filedialog, messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showinfo("Rugby 08 Revival",
                        "Rugby 08 could not be found automatically.\n"
                        "Select the folder that contains Rugby08.exe.")
    while not game_dir:
      chosen = filedialog.askdirectory(title="Select the Rugby 08 installation folder")
      if not chosen:
        root.destroy()
        return False
      if os.path.isfile(os.path.join(chosen, exe_name)):
        game_dir = chosen
      else:
        messagebox.showerror("Rugby 08 Revival", f"{exe_name} not found in:\n{chosen}")
    root.destroy()
  try:
    os.makedirs(os.path.dirname(config_filepath), exist_ok=True)
    with open(config_filepath, "w", encoding="utf-8") as f:
      f.write("# Written at first launch. Every option is documented in config.ini.example\n")
      f.write(f"# ({os.path.join(app_data_directory(), 'config.ini.example')}).\n\n")
      f.write("[Main]\n")
      f.write(f"R08_directory = {os.path.normpath(game_dir)}{os.sep}\n")
      f.write(f"R08_filename = {exe_name}\n\n")
      f.write("[Options]\n")
      if sys.platform != "win32":
        # The game is a Windows exe: start it through wine (WINEPREFIX etc. are
        # inherited from the environment).
        f.write(f"game_launcher_executable_filepath = {shutil.which('wine') or 'wine'}\n")
        f.write(f"game_launcher_arguments = {exe_name}\n")
  except OSError as e:
    log.error(f"cannot write {config_filepath}: {e}")
    return False
  return True


class Config:
  def __init__(self):

    self.data_directory = ''   # [Main] data_directory: source runs only (default: <repo>/data)
    # Same layout from source as in the released build (see shared/app_paths.py):
    # config.ini is in user_data/, written at first launch when missing.
    check_writable_or_exit()
    config_filepath = os.path.join(user_data_directory(), 'config.ini')
    if not self._config_is_valid(config_filepath):
      if is_portable():
        _first_run_setup(config_filepath)
      else:
        _needs_installer(config_filepath)

    # Load the values in the [Main] section (this will set the paths first)
    if not self._load_config_file(config_filepath, 'Main'):
      log.error(f"Failed to load configuration from {config_filepath}")
      exit(1)

    # The values are the ones used by default unless overridden by the section [Options] from the config file    

    # Game launcher paths and related options
    self.game_launcher_directory = os.path.join(self.R08_directory)
    self.game_launcher_executable_filepath = os.path.join(self.R08_directory, self.R08_filename)
    self.game_launcher_arguments = []
    self.game_launcher_environment = []
    self.game_launcher_environment_file = ""

    self.R08_data_gob_filepath = os.path.join(self.R08_directory, "Data", "data.gob")

    # Mod directories (see shared/app_paths.py): assets/ and the docs are in
    # app_data/ (src/ from source), the data pack in mod_data/ (data/ from source).
    self.mod_src_directory = app_data_directory()
    self.mod_data_directory = self.data_directory or mod_data_directory()

    # Warning bug here. If mod_src_directory or mod_data_directory are overridden in config.ini,
    # then the following paths will be incorrect.

    # Mod assets
    self.directory_teams = os.path.join(self.mod_data_directory, "teams")
    self.directory_players = os.path.join(self.mod_data_directory, "players")
    self.directory_stadiums = os.path.join(self.mod_data_directory, "stadiums")
    self.directory_competitions = os.path.join(self.mod_data_directory, "competitions")
    self.directory_challenges = os.path.join(self.mod_data_directory, "challenges")
    # Tournament saves are the user's progress, not data: user_data/.
    self.directory_tournament_saves = os.path.join(user_data_directory(), "tournaments")
    # The user's own edits of teams and players, laid over the data pack
    # (frontend/app/user_edits.py): a new data pack never overwrites them.
    self.directory_user_edits = os.path.join(user_data_directory(), "edits")
    self.data_version, self.data_schema = self._read_data_version()
    self._check_data_installed()
    self.static_files_directory = os.path.join(self.mod_src_directory, "assets", "static_files")
    self.templates_directory = os.path.join(self.mod_src_directory, "assets", "templates")
    # Menu background music (Creative Commons tracks + tracks.json manifest) —
    # see assets/audio/menu/CREDITS.md and frontend/ui/music.py.
    self.menu_music_directory = os.path.join(self.mod_src_directory, "assets", "audio", "menu")

    # Temporary working files (intermediate FSH files inserted into BIG archives,
    # extracted BIG files, memory dumps, etc.). These must NOT live in the game
    # directory. Overridable via [Options] in config.ini.
    self.temp_directory = os.path.join(tempfile.gettempdir(), "R08-mod")

    # Debug options
    self.debug_level = 0
    # Logging (see shared/log.py): DEBUG / INFO / WARNING / ERROR / OFF. R08_LOG_LEVEL
    # and the entry points' --log-level override it. "" = shared.log's default
    # (default INFO). log_file adds a rotating log file next to the
    # console output.
    self.log_level = ""
    self.log_file = ""
    self.simulation_mode = False

    # Platform information
    self.platform = platform.uname()[0].lower()

    # Static files to be omitted when starting mod
    self.exclude_static_files = []

    # Process handling options
    self.read_process_memory = True
    self.write_process_memory = True
    self.string_for_pid_search = self.R08_filename
    self.no_R08_process_stdout = True
    # How long to wait for the just-launched exe to become memory-readable
    # (screen_id != None) before giving up on it — see R08_handler.start_R08_executable.
    self.R08_boot_timeout_seconds = 90

    # Memory addresses
    self.memory_addresses = {
      # MatchSetup: both team records (players' match counters, substitution
      # log, set-piece counters), the scores, clock and period
      # (backend/match_memory.py)
      'match_setup': 0x009B6830,
      'screen_id': 0x009F9CB8,
      # *(world_ptr) = the match object; +world_clock_offset = time played,
      # float REAL seconds (scales with the half length; FUN_0062ed50 adds the
      # frame time). Non-zero once play has started.
      'world_ptr': 0x00A31988,
      'world_clock_offset': 0x58,
      # The match clock as displayed (float seconds on the 80-min scale: real
      # time x 40 / half length in minutes, FUN_00632f10), stopped by the game
      # at each period end, and the current period (byte: 0-1 halves, 2-4
      # extra time). Match-setup block 0x9B6830 +0x18f0 / +0x18f4. Zeroed when
      # the game's menu comes back, so it must be read during the match.
      'match_clock': 0x009B8120,
      'match_period': 0x009B8124,
    }
    # Seconds between two reads of the live scoring counters during a match
    # (timestamps the scores for challenge objectives).
    self.score_poll_interval = 0.5
    # Keep the options changed in-game (pause menu: camera, audio, HUD...):
    # the game's in-memory profile is read every profile_poll_interval seconds
    # during the match and what changed is saved as the user's game settings
    # (shared.game_profile.import_ingame).
    self.import_ingame_settings = True
    self.profile_poll_interval = 1.0

    # Front end options
    self.loading_image_filepath = "img.jpg"
    self.display_overlay_during_init = False
    # Title used to locate/embed the game window. Empty or unmatched falls back
    # to "largest newly-appeared window" in the embed code.
    self.embed_window_title = "Rugby"
    # Embed the game window into the Qt container (unified look). If False, the
    # game runs in its own window.
    self.embed_game = True
    # When Wine runs in virtual-desktop mode, reparenting the game window out of
    # the desktop leaves the desktop X window floating on top. Minimise any
    # window whose title contains this string after embedding. Empty = disabled.
    self.wine_virtual_desktop_title = "Wine desktop"
    # Host Qt window: True = a normal resizable window with its title bar,
    # False = fullscreen. Only the FIRST run reads this: Settings > Windowed
    # Mode writes the user's choice to user_prefs.ini, which wins from then on
    # (see shared.user_prefs.UserPrefs).
    self.game_windowed = False

    # Power-user UI: shows match-setup fields for .mis values the mod's own
    # forms don't normally expose (wind, weather extras, presentation
    # toggles, hand-authored mission state/objectives) — see
    # frontend/screens/match_setup.py's ADVANCED pane and
    # frontend/screens/mission_editor.py. Off by default: these are
    # experimental/rarely-needed fields, most of them gated by a reR08
    # rugby08patches.dll patch (default-on, but only if that DLL is in use).
    self.advanced_user = False

    # Reveal unfinished and data-editing tools in the Tools menu.
    self.developper_mode = False

    # Where the team and player editors save: "user" keeps every change as
    # the user's own edit in user_data/edits/ (the data pack is never
    # written, a new release can't overwrite the edits); "mod" writes the
    # data pack files themselves (the maintainer preparing a release).
    self.save_edits_to = "user"

    # d3d8.dll proxy: forces the game windowed and blocks the monitor resolution
    # switch, which is what makes the game window embeddable.
    self.use_d3d8_proxy = True
    self.d3d8proxy_dll_filepath = self._bundled_dll("d3d8.dll")
    # Gameplay patches DLL, chain-loaded by the d3d8 proxy (replaces the
    # Rugby08Launcher injection when launching Rugby08.exe directly).
    self.use_rugby08patches = True
    self.rugby08patches_dll_filepath = self._bundled_dll("rugby08patches.dll")
    # rugby08patches.dll "widescreen" patch: the 3D view uses the game window's
    # aspect ratio instead of the stock 4:3 stretched to the screen. The 2D HUD
    # keeps its 4:3 layout. widescreen_aspect: "auto" (follow the window) or a
    # fixed ratio such as 1.7777778 (16:9) or 16:9. widescreen is only the
    # default: Settings > Screen Ratio saves the user's choice to user_prefs.ini,
    # which wins from then on (see shared.user_prefs.UserPrefs).
    self.widescreen = False
    self.widescreen_aspect = "auto"

    # d3d8 proxy runtime config (written to rugby08_windowed.ini next to the exe)
    self.d3d8_mode = "all"            # "all" or "frontend-fullscreen"
    self.d3d8_allow_resize = False
    self.d3d8_borderless = True
    self.d3d8_keep_active = True
    self.d3d8_block_mode_switch = True
    self.d3d8_loading_width = 640     # loading/title-video window size (0 = keep backbuffer)
    self.d3d8_loading_height = 480
    self.d3d8_frontend_width = 1280   # frontend size; the loading->frontend jump reveals the embed
    self.d3d8_frontend_height = 720   # (reveal_mode "fullscreen" uses the target monitor size instead)
    self.d3d8_log = False
    # Boot the game window off-screen (PosX/PosY=-10000) when embedding, so it
    # never flashes on the desktop before being reparented into the container.
    # If embedding fails, the frontend moves it back on-screen.
    self.d3d8_offscreen_boot = True
    # How the game window is shown once the match has loaded (Windows only;
    # Linux always embeds through xdotool, into a container that fills the mod
    # window — fullscreen when the mod is):
    #   "auto"       - the game keeps its own top-level window, kept off-screen
    #                  and off the taskbar while it boots, then revealed
    #                  borderless over the monitor the mod window is on
    #                  (fullscreen mod) or over the mod's game area, owned by
    #                  the mod window (windowed mod). Decided when the match starts.
    #   "fullscreen" - as "auto", always over the monitor.
    #   "embed"      - reparented into the mod window as a WS_CHILD, filling it.
    #                  Crashes the game: DirectInput refuses a child window.
    # Set by the frontend at kick-off: True when this match's reveal is fullscreen.
    self.reveal_fullscreen = False
    # Set by the frontend at kick-off: True when the game keeps its own window
    # (Windows, reveal_mode not "embed"); reveal_monitor_rect is then its rect.
    self.reveal_own_window = False
    # Linux: set by the frontend at kick-off when the game is embedded — the game
    # must then render at reveal_monitor_rect's size (the embedding host's).
    self.embed_frontend_size = False
    self.reveal_mode = "auto"
    # Window class of the game's real top-level window. Before it, the game
    # creates a short-lived "EAGL PC Caps Retrieval" window (device caps probe,
    # destroyed ~0.3 s later): adopting that one leaves a dead handle.
    self.game_window_class = "EAGL PC"
    # Keep the game hidden behind the loading screen until its match has
    # finished loading: the game's screen id (read from process memory) must
    # be this value AND the boot counter must have reached boot_counter_max.
    # Measured (Win10, 2026-09-19): 0x0000 -> 0x0002 -> 0x0321 at 3.4 s; still on
    # 0x0321 the counter climbs 0 -> 20736 (6.4 s) behind the game's loading
    # card, then the stadium flyover starts ~0.6 s later. Everything after it
    # (flyover, walk-out, anthems/haka, team sheets = 0x0079) is shown.
    # 0 disables the screen-id check (window-resize heuristic / timeout).
    self.reveal_screen_id = 0x0321
    # Loading progress counter: a dword in the game's memory that climbs from 0
    # to boot_counter_max while the match loads. Absolute address =
    # Rugby08.exe image base (0x400000) + 0x6A6270. Drives the loading bar.
    self.boot_counter_address = 0x00AA6270
    # Value the counter reaches when the match has finished loading (same value
    # measured with different stadiums / times of day). 0 = counter not used;
    # the bar falls back to expected_boot_seconds pacing.
    self.boot_counter_max = 20736
    # Rough time the game takes to boot from launch to the reveal screen. Only
    # used to pace the loading progress bar when the boot counter is unavailable;
    # the real reveal always snaps the bar to 100%.
    self.expected_boot_seconds = 25

    # Wine only: remove the prefix-global virtual desktop (winecfg "Emulate a
    # virtual desktop"). The proxy forces windowed mode and blocks display-mode
    # switches, so the virtual desktop is useless and its (blue) window would
    # otherwise pop up over everything during boot. NOTE: a per-app
    # AppDefaults Desktop="" override does NOT work (wine hangs unable to
    # create its desktop window) — only removing the global value works.
    self.wine_disable_virtual_desktop = True

    # Miscellaneous
    self.mute_game_during_init = True
  

    self.original_game_files = ORIGINAL_GAME_FILES
    self.original_game_folders = ORIGINAL_GAME_FOLDERS
        
    # Deprecated options (will be removed in future)
    self.change_screen_resolution = True
    self.ignore_error_on_start_executable = False
    
    # External tools (defaults)
    self.tools = {
      'impbig': "config/tools/ImpBIG.exe",
    }

    # Attempt to load overrides from section [Options] in config file
    self._options_set = set()     # the attributes config.ini itself set
    self._load_config_file(config_filepath, 'Options')

    # Build launcher environment from OS env + config overrides + optional .env file
    self.game_launcher_environment = self._build_game_launcher_environment(config_filepath)

    # Make sure the temporary working directory exists
    try:
      os.makedirs(self.temp_directory, exist_ok=True)
    except Exception as e:
      log.warning(f"Failed to create temp directory '{self.temp_directory}': {e}")

    log.debug("Config loaded")

  def _bundled_dll(self, name):
    """assets/static_files/<name> shipped with the mod (override the path in
    config.ini [Options] to use another build)."""
    return os.path.join(self.static_files_directory, name)

  def _read_data_version(self):
    """data/VERSION (written by the data pack): key=value lines data_version, schema."""
    info = {}
    try:
      with open(os.path.join(self.mod_data_directory, "VERSION"), encoding="utf-8") as f:
        for line in f:
          if "=" in line:
            k, v = line.split("=", 1)
            info[k.strip()] = v.strip()
    except OSError:
      pass
    try:
      schema = int(info.get("schema", 0))
    except ValueError:
      schema = 0
    return info.get("data_version", "unknown"), schema

  def _check_data_installed(self):
    """Tell the user (instead of crashing) when the data pack is missing or built
    for another program version."""
    from shared.version import DATA_SCHEMA
    problem = None
    if not os.path.isdir(self.directory_teams):
      problem = (f"No mod data found in:\n{self.mod_data_directory}\n\n"
                 "Install the Rugby 08 Revival data pack.")
    elif self.data_schema and self.data_schema != DATA_SCHEMA:
      problem = (f"The data in {self.mod_data_directory} was built for another "
                 f"program version (data schema {self.data_schema}, program expects "
                 f"{DATA_SCHEMA}).\nInstall the matching data pack.")
    if problem:
      import tkinter as tk
      from tkinter import messagebox
      root = tk.Tk()
      root.withdraw()
      messagebox.showerror("Rugby 08 Revival", problem)
      root.destroy()
      sys.exit(1)

  @staticmethod
  def _config_is_valid(config_filepath):
    """config.ini exists and points at a real Rugby 08 install."""
    cp = configparser.ConfigParser()
    try:
      if not cp.read(config_filepath):
        return False
      main = cp['Main']
      return os.path.isfile(os.path.join(main['R08_directory'], main['R08_filename']))
    except (KeyError, configparser.Error, OSError):
      return False

  def _parse_env_assignments(self, values):
    env = {}
    for entry in self._parse_list(values):
      if '=' not in entry:
        continue
      key, val = entry.split('=', 1)
      key = key.strip()
      val = val.strip()
      if key:
        env[key] = val
    return env

  def _load_env_file(self, filepath):
    env = {}

    if not filepath:
      return env

    if not os.path.isfile(filepath):
      log.warning(f"Environment file not found: {filepath}")
      return env

    try:
      with open(filepath, 'r', encoding='utf-8') as f:
        for raw_line in f:
          line = raw_line.strip()

          if not line or line.startswith('#'):
            continue

          if line.startswith('export '):
            line = line[7:].strip()

          if '=' not in line:
            continue

          key, val = line.split('=', 1)
          key = key.strip()
          val = val.strip()

          if not key:
            continue

          if (val.startswith('"') and val.endswith('"')) or (val.startswith("'") and val.endswith("'")):
            val = val[1:-1]
          elif ' #' in val:
            # support inline comments for unquoted values
            val = val.split(' #', 1)[0].rstrip()

          env[key] = val

    except Exception as e:
      log.warning(f"Failed to load environment file '{filepath}': {e}")

    return env

  def _build_game_launcher_environment(self, config_filepath):
    env = os.environ.copy()

    # Backward compatibility: game_launcher_environment as KEY=VALUE list
    env.update(self._parse_env_assignments(self.game_launcher_environment))

    env_file = str(self.game_launcher_environment_file).strip()
    if env_file:
      if not os.path.isabs(env_file):
        env_file = os.path.join(os.path.dirname(config_filepath), env_file)
      env.update(self._load_env_file(env_file))

    return env

  def _parse_bool(self, value):
    if isinstance(value, bool):
      return value
    v = str(value).strip().lower()
    return v in ("1", "true", "yes", "on")

  def _parse_list(self, value):
    if isinstance(value, (list, tuple)):
      return list(value)
    # accept comma or pipe separated
    parts = [p.strip() for p in str(value).split(',') if p.strip()]
    if len(parts) == 1:
      parts = [p.strip() for p in str(value).split('|') if p.strip()]
    return parts

  def _load_config_file(self, config_filepath, section_name):
    config = configparser.ConfigParser()
    
    if not os.path.isfile(config_filepath):
      return False
        
    try:
      config.read(config_filepath)
    except Exception:
      return False

    # Handle [Main] section for specific attributes
    if config.has_section('Main') and section_name == 'Main':
      main = config['Main']
      if 'R08_directory' in main:
        self.R08_directory = main['R08_directory']
      else:
        log.error("'game_launcher_directory' not found in [Main] section of config.ini")
        return
      
      if 'R08_filename' in main:
        self.R08_filename = main['R08_filename']
      else:
        log.error("'game_launcher_executable_filename' not found in [Main] section of config.ini")
        return
      
      self.data_directory = '' if FROZEN else main.get('data_directory', '').strip()
      # Ignored (kept for old config.ini files): every folder derives from app_directory().
      self.mod_directory = app_directory()

    # Handle [Options] section for overrides
    if config.has_section('Options') and section_name == 'Options':
      for key, val in config.items('Options'):
        attr = key.strip()
        if not hasattr(self, attr):
          # try underscore variant (in case user used dots or hyphens)
          attr = attr.replace('-', '_').replace('.', '_')
        if not hasattr(self, attr):
          continue

        current = getattr(self, attr)
        # Determine type and convert
        try:
          if isinstance(current, bool):
            newval = self._parse_bool(val)
          elif isinstance(current, int):
            # base 0 so hex values (screen ids: 0x79) work as well as decimal
            newval = int(str(val).strip(), 0)
          elif isinstance(current, (list, tuple)):
            newval = self._parse_list(val)
          elif isinstance(current, dict):
            # do not overwrite complex dicts from simple ini values
            continue
          else:
            newval = val

          setattr(self, attr, newval)
          self._options_set.add(attr)

        except Exception:
          # if conversion fails, skip and keep default
          continue

    return True
  
  def is_set(self, attr):
    """True when config.ini's [Options] gave `attr` a value (not the default)."""
    return attr in self._options_set

  def _serialize_value(self, value):
    # Recursively convert values to simple serializable types for printing
    if isinstance(value, dict):
      return {k: self._serialize_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
      return [self._serialize_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
      return value
    try:
      return str(value)
    except Exception:
      return repr(value)

  def to_dict(self):
    result = {}
    for k, v in self.__dict__.items():
      if k.startswith('_'):
        continue
      result[k] = self._serialize_value(v)
    return result

  def print_all(self, stream=None):
    """Pretty-print all configuration values.

    If `stream` is provided, it is passed to `pprint.pprint` as the `stream` argument.
    """
    data = self.to_dict()
    if stream is None:
      pprint.pprint(data)
    else:
      pprint.pprint(data, stream=stream)


config = Config()

if __name__ == "__main__":
  config.print_all()
  print(config.debug_level)
