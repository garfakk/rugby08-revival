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


def fit_rect(left, top, width, height, ratio):
    """The largest width / height = `ratio` rectangle centred in the given one
    (left, top, width, height); the rectangle itself when ratio is None (the
    picture fills it: Screen Ratio "Auto")."""
    if not ratio or width <= 0 or height <= 0:
        return left, top, width, height
    if width / height > ratio:
        w, h = max(1, round(height * ratio)), height
    else:
        w, h = width, max(1, round(width / ratio))
    return left + (width - w) // 2, top + (height - h) // 2, w, h


# Settings > Screen Ratio presets (besides "Auto"), as width / height.
SCREEN_RATIOS = {"4:3": 4 / 3, "16:10": 16 / 10, "16:9": 16 / 9, "21:9": 21 / 9}


def nearest_screen_ratio(width, height):
    """The SCREEN_RATIOS label closest to a width x height screen (4:3 when
    the size is unknown): 1920x1080 -> "16:9", 2560x1080 / 3440x1440 ->
    "21:9", 5120x1440 (32:9) -> "21:9", the widest preset."""
    if width <= 0 or height <= 0:
        return "4:3"
    ratio = width / height
    return min(SCREEN_RATIOS, key=lambda label: abs(SCREEN_RATIOS[label] - ratio))


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
        # match simulation (auto-generated or typed-in results of your own
        # matches). Each such feature carries an "EXPERT" tag (theme.EXPERT).
        # Not in Settings: opt in with `expert_mode = true` in the prefs file.
        self.expert_mode = False
        # Logging level chosen in Settings (DEBUG / INFO / WARNING / ERROR);
        # "" = not chosen, so R08_LOG_LEVEL / config.ini / INFO apply.
        self.log_level = ""
        # 3D player previews on/off. Off: kit stages show the flat kit picture.
        self.preview_3d = True
        # 3D match view in the game window's aspect ratio (rugby08patches.dll
        # widescreen patch) instead of a stretched 4:3. Settings > Screen Ratio;
        # config.ini's widescreen is only the default until it is toggled.
        self.widescreen = config.widescreen
        # Aspect ratio of that 3D view: "auto" (follow the window) or "W:H".
        # Settings > Screen Ratio; config.ini's widescreen_aspect is the default.
        self.widescreen_aspect = str(config.widescreen_aspect)
        # Whether a screen ratio was ever chosen (Settings, user_prefs.ini or
        # config.ini). Not yet: the first launch picks the screen's own
        # (main.MainWindow._pick_screen_ratio).
        self.screen_ratio_set = (config.is_set("widescreen")
                                 or config.is_set("widescreen_aspect"))
        # Coin toss before each quick/tournament match (World Rugby Law 6.3):
        # decides kick-off and ends, so match setup locks those two rows.
        # Settings > Coin Toss; off by default.
        self.coin_toss = False
        # "standard" = the game's stock random wind (rolled by the backend);
        # "advanced" = the reR08 wind patch, set per match (match setup,
        # challenge file, tournament fixture). Settings > Wind.
        self.wind_mode = "advanced"
        # The user's team/player edits (user_data/edits) laid over the data
        # pack. Off: the pack alone is used, the edits are kept. Tools › My edits.
        self.use_edits = True
        # Tournament mode's transitions and recaps (matchday results, new
        # stage, champions...). Not in Settings: opt out with
        # `animations = false` in the prefs file.
        self.animations = True
        # Look on GitHub for a new program or data release at startup, at
        # most once a day (app/updater). Settings > Check For Updates.
        self.check_updates = True
        # How Quick Match picks a team (app/team_browse.py STYLES): "classic"
        # (season, category, team), "team_first", "browser", "timeline",
        # "era", "leagues". Settings > Quick Match Picker.
        self.match_picker = "classic"
        # The difficulty a match starts on (app/difficulty.py LEVELS): quick
        # match, a new tournament, a challenge. Settings > Preferred Difficulty.
        self.difficulty = "elite"
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
            self.widescreen = cp.getboolean(_SECTION, "widescreen", fallback=self.widescreen)
            self.widescreen_aspect = cp.get(_SECTION, "widescreen_aspect",
                                            fallback=self.widescreen_aspect).strip() or "auto"
            if cp.has_option(_SECTION, "widescreen") or cp.has_option(_SECTION, "widescreen_aspect"):
                self.screen_ratio_set = True
            self.coin_toss = cp.getboolean(_SECTION, "coin_toss", fallback=self.coin_toss)
            self.expert_mode = cp.getboolean(_SECTION, "expert_mode", fallback=self.expert_mode)
            self.use_edits = cp.getboolean(_SECTION, "use_edits", fallback=self.use_edits)
            self.animations = cp.getboolean(_SECTION, "animations", fallback=self.animations)
            self.check_updates = cp.getboolean(_SECTION, "check_updates", fallback=self.check_updates)
            self.match_picker = cp.get(_SECTION, "match_picker", fallback=self.match_picker).strip().lower() \
                or "classic"
            self.difficulty = cp.get(_SECTION, "difficulty", fallback=self.difficulty).strip().lower() \
                or "elite"
            mode = cp.get(_SECTION, "wind_mode", fallback=self.wind_mode).strip().lower()
            mode = "standard" if mode == "default" else mode      # older name
            if mode in ("standard", "advanced"):
                self.wind_mode = mode

    def screen_ratio_label(self):
        """The Settings > Screen Ratio choice: "Auto" or a SCREEN_RATIOS label."""
        aspect = str(self.widescreen_aspect).strip().lower()
        if not self.widescreen or aspect == "4:3":
            return "4:3"
        return next((label for label in SCREEN_RATIOS if label == aspect), "Auto")

    def set_screen_ratio(self, label):
        """Settings > Screen Ratio: 4:3 = the game as shipped (widescreen patch
        off); "Auto" or any other ratio turns the patch on. Saved."""
        self.widescreen = label != "4:3"
        self.widescreen_aspect = label.lower()
        self.screen_ratio_set = True
        self.save()

    def picture_ratio(self):
        """Width / height the match picture keeps inside the window, as big
        as fits, black bars around it; None: it fills the window (the
        widescreen 3D view following the window's own ratio, "auto")."""
        if not self.widescreen:
            return 4 / 3
        text = str(self.widescreen_aspect).strip().lower()
        try:
            if ":" in text:
                w, h = (float(part) for part in text.split(":", 1))
                return w / h if w > 0 and h > 0 else None
            return float(text) or None
        except ValueError:
            return None                     # "auto"

    def save(self):
        cp = configparser.ConfigParser()
        cp[_SECTION] = {"game_windowed": str(self.game_windowed),
                        "log_level": self.log_level,
                        "preview_3d": str(self.preview_3d),
                        "widescreen": str(self.widescreen),
                        "widescreen_aspect": self.widescreen_aspect,
                        "coin_toss": str(self.coin_toss),
                        "expert_mode": str(self.expert_mode),
                        "use_edits": str(self.use_edits),
                        "animations": str(self.animations),
                        "check_updates": str(self.check_updates),
                        "match_picker": self.match_picker,
                        "difficulty": self.difficulty,
                        "wind_mode": self.wind_mode}
        if not self.screen_ratio_set:
            # left out until chosen, so the first launch still detects it
            del cp[_SECTION]["widescreen"], cp[_SECTION]["widescreen_aspect"]
        try:
            with open(_PREFS_FILE, "w") as fh:
                cp.write(fh)
        except OSError as e:
            log.warning(f"could not save {_PREFS_FILE}: {e}")


user_prefs = UserPrefs()
