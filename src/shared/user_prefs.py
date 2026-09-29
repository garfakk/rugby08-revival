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
from pathlib import Path

from shared.app_paths import FROZEN, user_data_directory
from shared.config import config


from shared.log import get_logger

log = get_logger(__name__)


def _prefs_dir() -> str:
    """user_prefs.ini is per-user state, not a game asset, so it belongs next
    to config.ini (user_data_directory(): user_data/ under the install folder) —
    never in mod_data_directory,
    which is the swappable, reinstallable teams/players/stadiums data pack.
    Dev runs (not FROZEN) fall back to config.mod_directory/this repo, same
    as config.ini itself does in shared/config.py."""
    if FROZEN:
        path = user_data_directory()
        try:
            os.makedirs(path, exist_ok=True)
            return path
        except OSError as e:
            log.warning(f"could not create {path}: {e}")
    for candidate in (getattr(config, "mod_directory", None),):
        if candidate and os.path.isdir(candidate):
            return candidate
    return str(Path(__file__).resolve().parent.parent)


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
        # Temporarily forced off and no longer user-facing (the Settings
        # toggle was removed) — the embedded game window doesn't reposition
        # correctly once the reveal moved to match-start (see ingame.py's
        # X11 map-watch code); come back to this once that's fixed. Not
        # loaded from or saved to disk in the meantime, so a previously
        # saved True doesn't leak back in.
        self.game_windowed = False
        # Expert mode: reveals unfinished features (shown disabled, "coming
        # soon") that are hidden from normal users. No longer user-facing
        # (the Settings toggle was removed) — always off now, never loaded
        # from or saved to disk.
        self.expert_mode = False
        # Logging level chosen in Settings (DEBUG / INFO / WARNING / ERROR);
        # "" = not chosen, so R08_LOG_LEVEL / config.ini / INFO apply.
        self.log_level = ""
        # 3D player previews on/off. Off: kit stages show the flat kit picture.
        self.preview_3d = True
        self._load()

    def _load(self):
        if not os.path.isfile(_PREFS_FILE):
            return
        cp = configparser.ConfigParser()
        try:
            cp.read(_PREFS_FILE)
        except (OSError, configparser.Error):
            return
        if cp.has_section(_SECTION):
            self.log_level = cp.get(_SECTION, "log_level", fallback=self.log_level).strip().upper()
            self.preview_3d = cp.getboolean(_SECTION, "preview_3d", fallback=self.preview_3d)

    def save(self):
        cp = configparser.ConfigParser()
        cp[_SECTION] = {"game_windowed": str(self.game_windowed),
                        "log_level": self.log_level,
                        "preview_3d": str(self.preview_3d)}
        try:
            with open(_PREFS_FILE, "w") as fh:
                cp.write(fh)
        except OSError as e:
            log.warning(f"could not save {_PREFS_FILE}: {e}")


user_prefs = UserPrefs()
