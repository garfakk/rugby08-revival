"""
shared/user_prefs.py — persisted UI preferences
====================================================
config.py only ever reads config.ini (rewriting it with configparser would
destroy its extensive hand-written comments), so preferences the UI itself
changes — the 3D player preview toggle, for now — live in a separate
user_prefs.ini next to it instead.
"""
import configparser
import os

from shared.app_paths import user_data_directory
from shared.config import config


from shared.log import get_logger

log = get_logger(__name__)


def _prefs_dir() -> str:
    """user_prefs.ini is per-user state, not a game asset, so it belongs next
    to config.ini (user_data_directory(): user_data/ under the install folder,
    or under the repo root from source) — never in mod_data_directory,
    which is the swappable, reinstallable teams/players/stadiums data pack."""
    path = user_data_directory()
    try:
        os.makedirs(path, exist_ok=True)
    except OSError as e:
        log.warning(f"could not create {path}: {e}")
    return path


PREFS_DIR = _prefs_dir()
_PREFS_FILE = os.path.join(PREFS_DIR, "user_prefs.ini")
_SECTION = "prefs"


class UserPrefs:
    def __init__(self):
        # 3D preview is the plan's confirmed default ("replacing the kit
        # image"). No longer user-facing (the Settings toggle was removed) —
        # always this value now, never loaded from or saved to disk.
        self.player_3d_preview = True
        # SelectorRow/TeamNamePicker open a scrollable popup list on click
        # instead of stepping one value at a time with the arrows. No longer
        # user-facing (the Settings toggle was removed) — always this value
        # now, never loaded from or saved to disk.
        self.dropdown_menus = True
        # DEBUG: reveal the embedded game window immediately instead of hiding
        # it behind the loading screen while it boots. No longer user-facing
        # (the Settings toggle was removed) — always off now, never loaded
        # from or saved to disk.
        self.debug_show_game_window = False
        # Windowed (embedded in this app) vs unified fullscreen (this app
        # goes fullscreen, game stays embedded inside it) — drives BOTH the
        # frontend window (see main.MainWindow.apply_windowed_mode) and the
        # d3d8 proxy's own Mode= (see backend.mod_utils.configure_d3d8_proxy).
        # Settings > Windowed Mode; off by default.
        self.game_windowed = False
        # Expert mode: reveals unfinished features (shown disabled, "coming
        # soon") that are hidden from normal users, and the tournament's
        # manual result entry. Not in Settings: opt in with `expert_mode =
        # true` in the prefs file.
        self.expert_mode = False
        # Logging level chosen in Settings (DEBUG / INFO / WARNING / ERROR);
        # "" = not chosen, so R08_LOG_LEVEL / config.ini / INFO apply.
        self.log_level = ""
        # 3D player previews on/off. Off: kit stages show the flat kit picture.
        self.preview_3d = True
        # Coin toss before each quick/tournament match (World Rugby Law 6.3):
        # decides kick-off and ends, so match setup locks those two rows.
        # Off, and not in Settings: expert opt-in via `coin_toss = true` in
        # the prefs file.
        self.coin_toss = False
        # "standard" = the game's stock random wind (rolled by the backend);
        # "advanced" = the reR08 wind patch, set per match (match setup,
        # challenge file, tournament fixture).
        # Temporarily forced to "standard" (Settings row hidden, never loaded
        # from disk); the stored choice is kept in _stored_wind_mode and still
        # saved. To bring it back: default "advanced", load into wind_mode,
        # restore the Settings row.
        self.wind_mode = "standard"
        self._stored_wind_mode = "advanced"
        self._load()

    def _load(self):
        if not os.path.isfile(_PREFS_FILE):
            return
        cp = configparser.ConfigParser(strict=False)    # duplicate keys: last wins, not a silent reset
        try:
            cp.read(_PREFS_FILE)
        except (OSError, configparser.Error):
            return
        if cp.has_section(_SECTION):
            self.game_windowed = cp.getboolean(_SECTION, "game_windowed", fallback=self.game_windowed)
            self.log_level = cp.get(_SECTION, "log_level", fallback=self.log_level).strip().upper()
            self.preview_3d = cp.getboolean(_SECTION, "preview_3d", fallback=self.preview_3d)
            self.coin_toss = cp.getboolean(_SECTION, "coin_toss", fallback=self.coin_toss)
            self.expert_mode = cp.getboolean(_SECTION, "expert_mode", fallback=self.expert_mode)
            mode = cp.get(_SECTION, "wind_mode", fallback=self.wind_mode).strip().lower()
            mode = "standard" if mode == "default" else mode      # older name
            if mode in ("standard", "advanced"):
                self._stored_wind_mode = mode

    def save(self):
        cp = configparser.ConfigParser()
        cp[_SECTION] = {"game_windowed": str(self.game_windowed),
                        "log_level": self.log_level,
                        "preview_3d": str(self.preview_3d),
                        "coin_toss": str(self.coin_toss),
                        "expert_mode": str(self.expert_mode),
                        "wind_mode": self._stored_wind_mode}
        try:
            with open(_PREFS_FILE, "w") as fh:
                cp.write(fh)
        except OSError as e:
            log.warning(f"could not save {_PREFS_FILE}: {e}")


user_prefs = UserPrefs()
