"""
main.py — Application entry point
===================================
App shell: ScreenManager owns navigation with a real back-history stack;
DataStore loads teams/players/stadiums/tournaments once, at startup.
"""
import os
import sys
import argparse
from pathlib import Path

# The project root, so `shared` imports below work however this is launched.
ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# PyOpenGL guesses its backend from env vars (e.g. XDG_SESSION_TYPE); pin it on
# Windows so the released exe is deterministic.
if sys.platform == "win32":
    os.environ.setdefault("PYOPENGL_PLATFORM", "nt")

# Released (windowed) exe has no console: sys.stdout/stderr are None, which
# breaks any code that flushes or writes to them. Send them to a log file
# next to the exe instead (useful for bug reports). The file is only created
# on the first write. The previous run's log is kept as R08Revival.prev.log, so
# the log of a first launch survives the second one.
class _LazyLogFile:
    def __init__(self, path):
        self._path = path
        self._fh = None

    def _open(self):
        if self._fh is None:
            try:
                os.makedirs(os.path.dirname(self._path), exist_ok=True)
                self._fh = open(self._path, "w", encoding="utf-8", buffering=1)
            except OSError:
                self._fh = open(os.devnull, "w")
        return self._fh

    def write(self, text):
        return self._open().write(text) if text else 0

    def flush(self):
        if self._fh is not None:
            self._fh.flush()

    def isatty(self):
        return False


if getattr(sys, "frozen", False) and (sys.stdout is None or sys.stderr is None):
    from shared.app_paths import user_data_directory
    os.makedirs(user_data_directory(), exist_ok=True)
    _log_path = os.path.join(user_data_directory(), "R08Revival.log")
    try:
        os.replace(_log_path, _log_path[:-4] + ".prev.log")   # keep the previous run's log
    except OSError:
        pass
    _log = _LazyLogFile(_log_path)
    sys.stdout = sys.stdout or _log
    sys.stderr = sys.stderr or _log

# Logging goes to stderr (R08Revival.log in the released exe). Set up here with the
# environment's level so import-time messages are not lost; main() applies
# --log-level and the config file's level once those are known.
from shared.log import get_logger, setup_logging

setup_logging()
log = get_logger(__name__)

from PyQt5.QtWidgets import QApplication, QMainWindow, QWidget, QHBoxLayout, QSizePolicy
from PyQt5.QtCore import Qt, QEvent, QTimer
from PyQt5.QtGui import QIcon, QSurfaceFormat

# Scale the WHOLE UI with the display, not just the text. Every size in this UI
# is a pixel count (fixed row/header heights, paddings) while the fonts are in
# points, which grow with the screen's DPI: on a 150 % display a 24 pt title
# needs 65 px inside a header fixed at 76 px that also has to hold an 11 pt
# breadcrumb (30 px), so the bottom of the text was cut off. With this, Qt
# reports 96 dpi and a device pixel ratio instead, so points and pixels keep
# the proportions the layout was designed with at any scaling factor.
# Set at import time: these must be set BEFORE the QApplication is built, and
# main() is not the only entry point that builds one (see devR08/tools).
#: Logical space the screens are laid out for. Below this they start to
#: overlap (the match-setup middle column is the tightest), so the UI scale is
#: reduced rather than letting that happen — see _fit_ui_scale().
DESIGN_SIZE = (1280, 720)


def _fit_ui_scale(design=DESIGN_SIZE):
    """Windows: the UI is laid out in logical pixels — the desktop divided by
    the display's scaling — and a 1080p screen at 150 % leaves only 1280x680 of
    them, less than the screens need. QT_SCALE_FACTOR multiplies the display's
    own scaling, so setting it to the missing fraction buys the layout its
    design space back (slightly smaller text, nothing overlapping).
    Best-effort; never raises."""
    if sys.platform != "win32" or os.environ.get("QT_SCALE_FACTOR"):
        return
    try:
        import ctypes
        import math
        from ctypes import wintypes
        user32 = ctypes.windll.user32

        def metrics():
            rect = wintypes.RECT()
            user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0)  # SPI_GETWORKAREA
            return (user32.GetSystemMetrics(0), user32.GetSystemMetrics(1),   # SM_CX/CYSCREEN
                    rect.right - rect.left, rect.bottom - rect.top)

        # Unaware (this runs before Qt touches DPI): Windows hands back the
        # scaled-down numbers. Under a per-monitor-aware thread context: the
        # real ones. The two together give the display's scaling.
        virtual_w, _, _, _ = metrics()
        previous = user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))   # PMv2
        try:
            screen_w, screen_h, work_w, work_h = metrics()
        finally:
            if previous:
                user32.SetThreadDpiAwarenessContext(previous)
        display_scale = screen_w / float(virtual_w or screen_w)

        # Biggest UI scale that still leaves the layout its design space.
        fit = min(display_scale, work_w / design[0], work_h / design[1])
        # Then snap DOWN to a scale that divides the screen into whole logical
        # pixels. A fractional one leaves the last fraction of a pixel
        # unpainted, showing a hairline of desktop down the right and bottom
        # edges of a fullscreen window.
        step = screen_w // math.gcd(int(screen_w), int(screen_h))
        if step:
            logical_w = math.ceil(screen_w / fit / step) * step
            if logical_w > 0 and (screen_h * logical_w) % screen_w == 0:
                fit = screen_w / logical_w
        factor = fit / display_scale
        if abs(factor - 1.0) > 0.005:
            os.environ["QT_SCALE_FACTOR"] = f"{factor:.6f}"
            log.info(f"UI scale {fit:.4f}x instead of the display's {display_scale:.2f}x: "
                  f"{int(screen_w)}x{int(screen_h)} screen, {int(work_w)}x{int(work_h)} work "
                  f"area, screens need {design[0]}x{design[1]} logical pixels")
    except Exception as e:
        log.warning(f"could not work out the UI scale: {e}")


_fit_ui_scale()
QApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)
# Qt 5 rounds the scale factor to a whole number by default, which turns a
# 150 % display into 200 % — everything a third too big, and the window then
# too small to hold it. PassThrough uses the display's real factor.
try:
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
except AttributeError:      # Qt < 5.14
    pass

from ui import APP_STYLESHEET
from ui.theme import register_fonts
from app.shell import ScreenManager
from app.state import DataStore
from screens.main_menu import MainMenuScreen
from screens.match_setup import MatchSetupContainer
from screens.settings import SettingsScreen
from screens.about import AboutScreen
from screens.game_modes import GameModesScreen
from screens.ingame import GameWidget
from screens.post_match import PostMatchScreen
from screens.tools import ToolsScreen
from screens.team_editor import TeamEditorScreen
from screens.player_editor import PlayerEditorScreen
from screens.roster_import import RosterImportScreen
from shared.config import config
from shared.user_prefs import user_prefs
from shared.game_profile import game_profile, resolution_choices
from ui.theme import BG_BASE
from ui.music import MenuMusic, TrackMedal

# Every screen is designed and hand-tuned around roughly a 16:9 desktop
# width — on an ultrawide/superwide monitor (or "unified fullscreen" on one),
# letting it stretch edge to edge would spread cards and text across empty
# space rather than making anything more readable. Centered and letterboxed
# past this width instead; below it, unaffected (no screen's content
# actually reaches it in normal windowed use).
MAX_CONTENT_WIDTH = 1920


class MainWindow(QMainWindow):
    """Top-level window. Owns the ScreenManager and all navigation. Screens
    receive callbacks — they never import MainWindow directly."""

    fullscreen: bool = False

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Rugby 08 Revival")
        from shared.app_paths import assets_directory
        self.setWindowIcon(QIcon(os.path.join(assets_directory(), "app_icon.png")))
        self.setMinimumSize(1000, 640)

        self.data = DataStore()

        self.screens = ScreenManager()
        self.screens.setMaximumWidth(MAX_CONTENT_WIDTH)
        self.screens.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        letterbox = QWidget()
        letterbox.setAttribute(Qt.WA_StyledBackground, True)
        letterbox.setStyleSheet(f"background: {BG_BASE};")
        lb = QHBoxLayout(letterbox)
        lb.setContentsMargins(0, 0, 0, 0)
        # Stretch factor deliberately huge: addStretch()'s spacers carry an
        # explicit factor of 1, which suppresses Qt's usual auto-boost for
        # Expanding widgets sitting next to zero-stretch items -- without an
        # explicit factor here `screens` would just sit at its sizeHint and
        # the spacers would eat all the extra width. A big factor makes it
        # claim space first, capped by setMaximumWidth above; only the
        # overflow past that cap goes to the two side spacers.
        lb.addStretch(1)
        lb.addWidget(self.screens, 1000)
        lb.addStretch(1)
        self.setCentralWidget(letterbox)
        self._intro = None
        self._build_music()
        self._build_screens()
        self.show_main()
        self.apply_windowed_mode(user_prefs.game_windowed)
        self._show_intro()

    # ── menu music ─────────────────────────────────────────────────────────
    def _build_music(self):
        """Rock playlist under the menus, silenced for the duration of a
        match. See ui/music.py; the tracks and their CC attribution live in
        assets/audio/menu/."""
        self.music = MenuMusic(self)
        self.track_medal = TrackMedal(self.centralWidget())
        self.track_medal.set_anchor(self.screens)     # the content column, not the screen edge
        self.music.track_started.connect(self.track_medal.show_track)
        # Nothing plays until the intro splash lifts — the intro is its own
        # quiet piece, and the first track landing with the menu is the
        # point at which the medal is actually visible.
        self._menus_ready = False
        self._alt_held = False   # see eventFilter: Alt-alone vs Alt+key
        # Screen changes drive the music rather than each navigation method
        # doing it by hand: every route into and out of the match screen —
        # kick off, back, rematch, post-match — then behaves the same.
        self.screens.currentChanged.connect(self._on_screen_changed)
        # Alt is a modifier, so it never reaches a focused widget's
        # keyPressEvent as a plain key on its own; an application-wide
        # filter is the only place it can be caught reliably.
        QApplication.instance().installEventFilter(self)

    def _on_screen_changed(self, _index):
        # Screens differ in whether they carry a hint bar, and the medal parks
        # above it — so it has to be placed again on every change, not only on
        # resize.
        self.track_medal.reposition()
        if self.screens.currentWidget() is self.screen_ingame:
            self.track_medal.dismiss()
        else:
            self.music.release()
            if self._menus_ready:
                self.music.start()

    def eventFilter(self, obj, event):
        """Alt (pressed and released on its own) skips to the next track.
        Watched on press AND release so an Alt+something shortcut is not
        mistaken for a skip when the modifier is let go; nothing is ever
        swallowed (always returns to the base filter), so Alt keeps working
        as a modifier everywhere else."""
        etype = event.type()
        if etype == QEvent.KeyPress:
            if event.key() == Qt.Key_Alt:
                if not event.isAutoRepeat():
                    self._alt_held = True
            elif self._alt_held:
                self._alt_held = False
        elif etype == QEvent.KeyRelease and event.key() == Qt.Key_Alt:
            skip = self._alt_held and not event.isAutoRepeat()
            self._alt_held = False
            if skip and self.screens.currentWidget() is not self.screen_ingame:
                self.music.skip()
        return super().eventFilter(obj, event)

    def _show_intro(self):
        # Parented to the central widget, not self: QMainWindow's own
        # internal layout manages/stacks its central widget specially, and
        # a raw child of the QMainWindow itself gets silently re-stacked
        # behind it (raise_() doesn't stick) — a plain QWidget's child has
        # no such interference.
        from ui.intro import IntroSplash
        host = self.centralWidget()
        self._intro = IntroSplash(host)
        self._intro.setGeometry(host.rect())
        self._intro.finished.connect(self._on_intro_finished)
        self._intro.show()
        self._intro.raise_()
        # First GL context + shader compile now, while only the splash is up,
        # rather than when the match-setup 3D previews first appear.
        QTimer.singleShot(0, self._warm_up_gl)
        # Park the menu tiles before the splash covers them, so the reveal
        # never flashes a fully-drawn menu for a frame first.
        for tile in self.screen_main._tiles:
            tile.set_entrance(0.0)

    @staticmethod
    def _warm_up_gl():
        from ui.player_view import warm_up_gl
        if warm_up_gl() is False and os.environ.get("R08_GL_FALLBACK_TRIED") != "1":
            # No usable OpenGL 3.3 core context (see warm_up_gl()'s docstring —
            # typically a VM/RDP session with no GPU passthrough). Retry the
            # whole process once with Qt's bundled software rasterizer, which
            # does support it, just on the CPU. QT_OPENGL must be set before
            # QApplication exists, so this has to be a fresh process, not a
            # live switch; the env var guards against retrying forever if the
            # software renderer turns out to be unusable too (e.g. missing
            # from a stripped install) — that second run just shows the "3D
            # preview unavailable" placeholder instead of retrying again.
            log.warning("Retrying once with the software OpenGL renderer (QT_OPENGL=software)")
            os.environ["QT_OPENGL"] = "software"
            os.environ["R08_GL_FALLBACK_TRIED"] = "1"
            os.execv(sys.executable, [sys.executable] + sys.argv[1:])

    def _on_intro_finished(self):
        self._intro = None
        if not game_profile.has_resolution():
            self._pick_resolution()
        self._open_menus()

    def _pick_resolution(self):
        """First launch only: silently choose this screen's resolution (or the
        closest offered one). The user can change it later in Settings."""
        screen = QApplication.primaryScreen()
        ratio = screen.devicePixelRatio()
        _sizes, recommended = resolution_choices(round(screen.size().width() * ratio),
                                                 round(screen.size().height() * ratio))
        w, h = recommended
        game_profile.set_resolution(w, h)
        game_profile.save()
        log.info(f"first launch: game resolution set to {w}x{h}")

    def _open_menus(self):
        # Idle-time preparation of the match-setup 3D previews (see
        # MatchSetupScreen.prewarm) — after the splash, before anyone gets there.
        QTimer.singleShot(1200, self.screen_match_setup.prewarm)
        self._menus_ready = True
        self.screen_main.play_entrance()
        self.music.start()

    def changeEvent(self, event):
        """Re-assert the fullscreen geometry when the window is activated again
        (e.g. coming back from the match): Qt can put its stale frame margins
        back at any re-show, leaving a strip of desktop around the window."""
        super().changeEvent(event)
        if (event.type() in (QEvent.ActivationChange, QEvent.WindowStateChange)
                and getattr(self, "fullscreen", False) and self.isVisible()):
            app = QApplication.instance()
            screen = app.screenAt(self.frameGeometry().center()) or app.primaryScreen()
            QTimer.singleShot(0, lambda s=screen: self._force_native_fullscreen(s))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._intro is not None:
            self._intro.setGeometry(self.centralWidget().rect())
        self.track_medal.reposition()

    def closeEvent(self, event):
        # screen_ingame.closeEvent never fires on its own here: it's a
        # child widget inside the screen stack, not a top-level window, and
        # Qt only delivers closeEvent to the widget that was actually
        # closed. Without this, quitting the app while a match is loading
        # or in progress left Rugby08.exe running as an orphan process —
        # the same cleanup on_hide() gives every other way to navigate away
        # from that screen, just reached from window-close instead of
        # screen navigation.
        self.screen_ingame.on_hide()
        super().closeEvent(event)

    def apply_windowed_mode(self, windowed: bool):
        """Live: the normal resizable window, or unified fullscreen (this
        app fullscreen, the embedded game filling it) — see
        shared.user_prefs.UserPrefs.game_windowed. Called once at startup
        and again immediately by Settings when the toggle changes; no app
        restart needed. The embedded game's own windowed/fullscreen split
        (d3d8 proxy Mode=) is a separate concern, only settled at the next
        match launch — see backend.mod_utils.configure_d3d8_proxy."""
        self.fullscreen = not windowed
        # NO setWindowFlag(FramelessWindowHint) here. Changing a window flag on
        # a live window makes Qt destroy and recreate the native window, and the
        # recreated one came back never repainted (the app showed an empty
        # window with only the odd child redrawing itself) and 10 px short of
        # the screen. showFullScreen() drops the decorations by itself.
        app = QApplication.instance()
        if self.fullscreen:
            # Pick the screen the window is on, not always the primary one.
            screen = app.screenAt(self.frameGeometry().center()) or app.primaryScreen()
            self.setGeometry(screen.geometry())
            self.showFullScreen()
            # Safety net: Qt can apply frame margins of its own to the native
            # window, leaving a strip of desktop around it. No-op when the
            # window already covers the screen exactly.
            for delay_ms in (0, 150, 600):
                QTimer.singleShot(delay_ms, lambda s=screen: self._force_native_fullscreen(s))
        else:
            # showNormal() FIRST: resizing/moving while the window is still
            # fullscreen makes Qt keep the fullscreen (caption-less) native
            # style, so the window came back without a title bar.
            self.showNormal()
            screen = app.primaryScreen().availableGeometry()
            # Never open bigger than the desktop can show: 1440x900 is the
            # intended size, but on a smaller (or scaled) display the work
            # area itself is smaller, and the screens need DESIGN_SIZE.
            self.resize(min(1440, screen.width()), min(900, screen.height()))
            # The title bar and borders sit OUTSIDE that size, so a window
            # sized to the work area hangs off it — and with the frame off the
            # top edge the title bar is not there to grab.
            frame = self.frameGeometry()
            self.resize(min(self.width(), screen.width() - (frame.width() - self.width())),
                        min(self.height(), screen.height() - (frame.height() - self.height())))
            frame = self.frameGeometry()
            frame.moveCenter(screen.center())
            frame.moveLeft(max(screen.left(), frame.left()))
            frame.moveTop(max(screen.top(), frame.top()))
            self.move(frame.topLeft())
        self.show()
        self.raise_()
        self.activateWindow()

    def _force_native_fullscreen(self, screen=None):
        """Windows only: put the native window exactly on its monitor.

        The monitor rectangle is read natively, in physical pixels: Qt's own
        geometry is in logical ones once high-DPI scaling is on, and feeding
        those to SetWindowPos resized the window to a fraction of the screen
        while it was in the fullscreen (caption-less) state — which is how the
        window ended up borderless and unmovable. Best-effort, never raises."""
        if sys.platform != "win32" or not self.fullscreen:
            return
        try:
            import win32api
            import win32con
            import win32gui
            hwnd = int(self.winId())
            monitor = win32api.MonitorFromWindow(hwnd, win32con.MONITOR_DEFAULTTONEAREST)
            left, top, right, bottom = win32api.GetMonitorInfo(monitor)["Monitor"]
            if win32gui.GetWindowRect(hwnd) == (left, top, right, bottom):
                return
            win32gui.SetWindowPos(hwnd, win32con.HWND_TOP, left, top,
                                  right - left, bottom - top,
                                  win32con.SWP_NOZORDER | win32con.SWP_FRAMECHANGED)
        except Exception as e:
            log.warning(f"could not force fullscreen geometry: {e}")

    # ── Screen construction ────────────────────────────────────────────────
    def _build_screens(self):
        self.screen_main = MainMenuScreen(self)
        self.screen_match_setup = MatchSetupContainer(
            self.data, self.show_main, self.begin_match_launch, self.reveal_match)
        self.screen_settings = SettingsScreen(self.show_main, on_windowed_mode_changed=self.apply_windowed_mode,
                                              music=self.music)
        self.screen_about = AboutScreen(self.show_main)
        self.screen_game_modes = GameModesScreen(self.show_main)
        self.screen_ingame = GameWidget(self.show_main, self.show_match_setup,
                                         result_callback=self.show_post_match,
                                         on_loading_end=self.music.stop_loading)
        self.screen_post_match = PostMatchScreen(
            on_rematch=self.rematch,
            on_match_setup=self.show_match_setup,
            on_main_menu=self.show_main,
        )
        self.screen_tools = ToolsScreen(
            self.data, self.show_main, self.show_team_editor, self.show_player_editor,
            on_import=self.show_roster_import)
        editor_back = lambda: self.screens.go_back(default=self.screen_tools)
        self.screen_team_editor = TeamEditorScreen(self.data, editor_back,
                                                   open_player=self.open_player)
        self.screen_player_editor = PlayerEditorScreen(self.data, editor_back,
                                                       open_team=self.open_team)
        self.screen_team_editor.on_import = self.show_roster_import
        self.screen_player_editor.on_import = self.show_roster_import
        self.screen_roster_import = RosterImportScreen(
            self.data, editor_back, on_open_team=self.show_team_editor,
            on_open_player=self.show_player_editor)

        for screen in (
            self.screen_main,
            self.screen_match_setup,
            self.screen_settings,
            self.screen_about,
            self.screen_game_modes,
            self.screen_ingame,
            self.screen_post_match,
            self.screen_tools,
            self.screen_team_editor,
            self.screen_player_editor,
            self.screen_roster_import,
        ):
            self.screens.addWidget(screen)

    # ── Navigation ─────────────────────────────────────────────────────────
    def show_main(self):
        self.screens.show_screen(self.screen_main, push_history=False)
        self.screens.reset_history()

    def show_match_setup(self):
        self.screens.show_screen(self.screen_match_setup)

    def show_game_modes(self):
        self.screens.show_screen(self.screen_game_modes)

    def show_tools(self):
        self.screens.show_screen(self.screen_tools)

    def show_team_editor(self):
        self.screens.show_screen(self.screen_team_editor)

    def show_player_editor(self):
        self.screens.show_screen(self.screen_player_editor)

    def show_roster_import(self):
        self.screens.show_screen(self.screen_roster_import)

    def open_player(self, pid, season=None):
        """Team editor → player editor; BACK returns to the team."""
        self.screens.show_screen(self.screen_player_editor)
        self.screen_player_editor.show_player(pid, season)

    def open_team(self, tid, season=None, shirt=None):
        """Player editor → team editor on that squad; BACK returns to the player."""
        self.screens.show_screen(self.screen_team_editor)
        self.screen_team_editor.show_team(tid, season, shirt)

    def show_settings(self):
        self.screens.show_screen(self.screen_settings)

    def show_about(self):
        self.screens.show_screen(self.screen_about)

    def begin_match_launch(self, match_data):
        """Starts the actual backend work (file prep, launching the game)
        without switching the visible screen — the match-setup screen calls
        this the instant Kick off is pressed, before its own vanish/walk-off
        animation, so real progress is already ahead by the time the loading
        screen is revealed."""
        config.match_data = match_data
        self._last_match_data = match_data
        # Swap the shuffled playlist for the dedicated loading loop (see
        # ui/music.py:play_loading) — it plays until GameWidget's
        # on_loading_end fires (self.music.stop_loading, wired at
        # construction) right as the game is revealed.
        self.music.play_loading()
        self.track_medal.dismiss()
        log.info("Starting match: %s vs %s",
                 (match_data.get("team_A") or {}).get("name"), (match_data.get("team_B") or {}).get("name"))
        log.debug("Match data: %s", match_data)
        self.screen_ingame.start_executable(match_data)

    def reveal_match(self):
        self.screens.show_screen(self.screen_ingame)
        self.screen_ingame.restart_loading_display()

    def start_match(self, match_data):
        """Begin + reveal together, no animation — used where there is no
        match-setup screen to vanish first (e.g. a rematch)."""
        self.begin_match_launch(match_data)
        self.reveal_match()

    def show_post_match(self, result):
        self.screen_post_match.set_result(getattr(self, "_last_match_data", None), result)
        self.screens.show_screen(self.screen_post_match, push_history=False)
        self.screens.reset_history()

    def rematch(self):
        match_data = getattr(self, "_last_match_data", None)
        if match_data:
            self.start_match(match_data)


# ── Entry point ───────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Rugby 08 Revival")
    parser.add_argument("--show-config", action="store_true",
                        help="Print the loaded config and exit")
    parser.add_argument("--log-level", default=None, metavar="LEVEL",
                        help="DEBUG, INFO, WARNING or ERROR (default: log_level in config.ini, else INFO; OFF in the released exe)")
    parser.add_argument("--selftest", action="store_true",
                        help="Build the whole UI, then quit after a moment (release smoke test)")
    args, _ = parser.parse_known_args()
    # --log-level and R08_LOG_LEVEL win; else the level chosen in Settings
    setup_logging(args.log_level or (None if os.environ.get("R08_LOG_LEVEL")
                                     else user_prefs.log_level or None))

    if args.show_config:
        config.print_all()
        sys.exit(0)

    # GLX/EGL pick the process-wide pixel format off the *first* GL context
    # created, so a per-widget alpha request (PlayerView's transparent 3D
    # stage) can get silently downgraded to opaque unless alpha is already
    # in the default format before anything creates a context.
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QApplication(sys.argv)
    register_fonts()
    app.setStyleSheet(APP_STYLESHEET)

    window = MainWindow()  # __init__ already applies the current windowed-mode setting

    if args.selftest:
        from PyQt5.QtCore import QTimer
        QTimer.singleShot(3000, app.quit)
        code = app.exec_()
        print("SELFTEST OK")
        sys.exit(code)

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
