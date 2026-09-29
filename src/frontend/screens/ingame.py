"""
ingame.py — In-game widget
==========================
Launches Rugby08.exe and keeps its window hidden behind the loading screen
until the match has loaded.
On Windows (config.reveal_mode; "auto" follows the mod window — fullscreen mod,
fullscreen game; windowed mod, game embedded and filling it):
  "fullscreen" - the game keeps its own window, off-screen and off the taskbar
                 while it boots, then covers the mod's monitor (borderless).
  "embed"      - the window is reparented into the Qt container (SetParent).
On Linux: snapshots windows matching `config.embed_window_title` before launch,
          finds the largest *new* visible window afterwards, and reparents it
          into the container with `xdotool windowreparent` (XReparentWindow).
Every step fails safe: if xdotool is missing, the window can't be found, or a
reparent fails, the game keeps running in its own window and the UI says so —
nothing crashes and no unrelated window is ever embedded.
Simulation mode returns to the main menu after a short non-blocking delay.
"""
import logging
import os
import sys
import time
import ctypes
import shutil
import platform
import random
import subprocess
from pathlib import Path

import psutil
from PyQt5.QtWidgets import (
    QApplication, QVBoxLayout, QHBoxLayout, QWidget, QLabel, QGraphicsOpacityEffect,
)
from PyQt5.QtCore import (QThread, pyqtSignal, QTimer, Qt, QRect, QPoint,
                          QPropertyAnimation, QEasingCurve, QVariantAnimation)
from PyQt5.QtGui import QWindow, QPixmap, QFont

sys.path.append(str(Path(__file__).parent.parent.parent))
from shared.config import config
from shared.user_prefs import user_prefs
from shared.log import get_logger
from ui.loading_ring import CircularLoadingRing
from ui.broadcast import display_label
from ui.theme import BG_BASE, FG_SECONDARY, FG_MUTED

log = get_logger(__name__)

IS_WINDOWS = platform.system() == "Windows"
IS_LINUX = platform.system() == "Linux"

if IS_WINDOWS:
    try:
        import win32gui
        import win32con
        import win32process
        import win32api
        WIN32_AVAILABLE = True
    except ImportError:
        WIN32_AVAILABLE = False
        log.warning("pywin32 not installed — window embedding disabled.")
else:
    WIN32_AVAILABLE = False

# Linux X11 embedding relies on xdotool (XReparentWindow under the hood)
HAS_XDOTOOL = bool(shutil.which("xdotool")) if IS_LINUX else False

EMBED_TIMEOUT_S = 30.0
EMBED_POLL_MS = 150   # fast poll: the window is grabbed almost as soon as it maps
EMBED_MIN_SIZE = 100   # px — ignore tiny helper/IME windows when picking the game window
# reveal_mode "fullscreen": where the game window waits while it boots — the
# same spot the d3d8 proxy boots it at (d3d8_offscreen_boot).
OFFSCREEN_POS = -10000
# Geometry re-asserts after the fullscreen reveal (the game can still Reset
# its device right after the match starts).
REVEAL_REASSERT_MS = (300, 800, 1600)
# "Match in progress" waits this long after the fullscreen reveal: the game
# window takes a moment to actually appear, and the text showed before it.
MATCH_MESSAGE_DELAY_MS = 900
# Linux: the d3d8 proxy (ShowAtMatchStart) keeps the game window hidden past
# our reveal and shows it itself once the match has loaded. When wine maps it
# again it re-syncs the X window to its own idea of the position — the
# absolute screen coordinates it read back after our reparent — so in a
# windowed mod window (container not at the screen origin) the game lands
# offset inside the container. Watch for that map and pin the window back.
HAS_XWININFO = bool(shutil.which("xwininfo")) if IS_LINUX else False
X11_MAP_WATCH_MS = 250
X11_MAP_WATCH_TIMEOUT_S = 150.0   # > the proxy's ShowTimeoutSec failsafe (120 s)
X11_MAP_SETTLE_S = 3.0            # keep pinning this long after it maps
LSFW_LOCK, LSFW_UNLOCK = 1, 2      # LockSetForegroundWindow

# After the game window is embedded it is kept hidden (behind the loading
# screen) while the game boots. The game is only shown once its loading is
# genuinely FINISHED, which takes two signals, not one:
#   * the boot counter (config.boot_counter_address) reaching
#     config.boot_counter_max — the game's own loading at 100 %;
#   * the screen id (config.reveal_screen_id) — the frontend is up.
# The screen id alone used to drive the reveal, and it lands well before the
# counter tops out, so the game appeared mid-load: the user saw the game's
# own loading finish instead of the mod's ring finishing. Whichever signal
# is unavailable (counter not configured, memory unreadable) drops out of
# the condition, so a machine with neither still behaves as before: the
# proxy's loading->frontend window resize, then a timeout, as fallbacks.
# 100 ms: the stadium flyover starts ~0.6 s after the counter tops out, so a
# slow poll plus the ring's finish would cut into it.
FRONTEND_WATCH_MS = 100
FRONTEND_TIMEOUT_S = 45.0   # reveal anyway if no signal is ever observed
# One signal can land long before the other (or, if boot_counter_max was
# measured on a different build/machine, never). Once the FIRST of the two
# arrives, the second gets this long to show up before the reveal goes
# ahead without it — a wrong counter_max then costs a few seconds, not the
# full FRONTEND_TIMEOUT_S.
REVEAL_GRACE_S = 8.0
# The counter is polled, so the exact top value can be missed if the game
# zeroes it the moment loading ends. A drop this far below a peak that had
# already got within COUNTER_NEAR of the max is read as that reset, i.e. as
# "loading finished", rather than as the counter going backwards.
COUNTER_NEAR = 0.98               # fraction of boot_counter_max that counts as
                                  # "as good as topped out"
COUNTER_RESET_DROP = 0.5          # fraction of the peak below which a reading
                                  # is a reset, not a stall
COUNTER_SETTLE_S = 1.0            # a counter parked within COUNTER_NEAR of the
                                  # max this long is done too (final value a
                                  # little under boot_counter_max)
COUNTER_STALL_MIN = 0.9           # ...or, parked this long at this fraction of the
COUNTER_STALL_S = 3.0             # max: the top value depends on the match (seen
                                  # 20224 = 97.5 % where 20736 is usual, so the
                                  # COUNTER_NEAR rule missed it and the reveal
                                  # waited for the 45 s timeout)
LOADED_SCREEN_ID = 0x0079         # team sheets: the match is loaded whatever the counter says
LOADING_ANIM_MS = 400

# ── Loading progress model ─────────────────────────────────────────────────────
# The bar spans two things the user cannot tell apart: the mod's own preparation
# work (file generation, reported step by step by backend.start_match) and the
# game's boot (tracked through the boot counter read from process memory —
# config.boot_counter_address / boot_counter_max — falling back to screen ids
# paced by config.expected_boot_seconds when that counter is unavailable).
PROGRESS_RESOLUTION = 1000        # QProgressBar range — sub-percent smoothness
PREP_END      = 0.45              # preparation work owns 0 .. 45 % (measured:
                                  # ~2 s of prep against ~7 s of boot, and the
                                  # boot half is the one with a real signal)
PROC_SEEN     = 0.48              # game process appeared — boot tracking starts
                                  # here, NOT at the embed: the window can take a
                                  # long time to appear and the boot counter is
                                  # already climbing meanwhile
EMBED_DONE    = 0.52              # game window found and reparented (floor only,
                                  # in case the boot counter is unreadable)
BOOT_END      = 0.97              # ceiling while booting; the reveal fills the rest
BOOT_WATCH_MS = 250               # boot-counter poll while waiting for the window
# BOOT_CURVE used to be 1.25 (">1 = starts steady, picks up speed towards
# the reveal"). In practice a >1 power curve on an already-fractional
# by_counter/by_time value stays BELOW the raw signal for the whole boot
# (x**1.25 < x for x in (0,1)) and only meets it at x=1 — so the bar
# visibly lagged for the whole boot stretch (read as "stuck around 50%",
# where the boot phase begins) and then had to close that accumulated
# gap the moment _reveal_game fires, on top of FINISH_MS's own rush —
# double deceleration followed by a double rush. 1.0 maps the tracked
# boot signal straight through, so the bar's pace actually reflects it.
BOOT_CURVE    = 1.0
SCREEN_ID_STEP = 0.05             # bump per newly observed in-game screen id
                                  # (only used when the boot counter is unreadable)
PROGRESS_EASE_MS   = 40
PROGRESS_EASE_RATE = 0.06         # fraction of the remaining gap eaten per tick

# A stage's whole span (report() jumps the target to its END before the
# stage's real work has even started) used to be closed almost entirely at
# PROGRESS_EASE_RATE: the bar would rush to the target in well under a
# second, then sit dead still — often for several real seconds — waiting
# for the next report() once a slow stage (graphics/roster building, which
# together are 72% of the weighted total) actually finishes. That dead
# stop read as "slows down around 50%". Raising CRAWL_GAP so most of a big
# span is walked at the slower CRAWL_RATE instead keeps the bar visibly,
# continuously creeping the whole time a stage is genuinely working —
# never stopped — and EASE_RATE still gives a satisfying burst forward for
# the first slice whenever a new stage actually starts.
                                  # (~0.45 s half-life: closes most of a jump in
                                  # under a second, still never teleports)
PROGRESS_CRAWL_GAP  = 0.35        # gap under which the bar switches to...
PROGRESS_CRAWL_RATE = 0.028       # ...this slower rate, so it keeps inching
                                  # instead of parking on the target and looking
                                  # frozen until the next real signal. This is a
                                  # gap-closing rate chasing a moving target, so
                                  # it can never fully catch up during a fast
                                  # boot — nudged up slightly from 0.02 to leave
                                  # less for the adaptive finish (see FINISH_MS)
                                  # to cover, without going high enough to look
                                  # twitchy on a boot that genuinely takes a while
# Human pacing: a perfectly smooth bar reads as fake, so the easing rate is
# multiplied by a factor that changes every PACE_HOLD_S — the bar dawdles, then
# surges, like real work. Never affects the target, only how fast the displayed
# value chases it, so progress stays monotonic and honest.
PACE_PROFILE   = ((0.35, 0.18), (0.65, 0.45), (1.00, 0.24), (1.90, 0.13))
PACE_HOLD_S    = (0.35, 1.30)     # min/max seconds one pace factor lasts

# The bar's crawl during boot is an exponential-decay chase of a moving
# target (see _tick_progress): it structurally can never fully close the
# gap while the target keeps climbing, so whatever's left over lands on
# _reveal_game. A FIXED finish duration meant a boot that (for whatever
# reason — an expected_boot_seconds that runs long relative to the real
# machine, a counter that stayed unreadable) left a big gap got the exact
# same rushed close as one that left a small gap — "almost no time
# between 70 and 100 %". FINISH_MS is now a floor, not the whole
# duration: _reveal_game adds time proportional to how much is actually
# left to cover, so a big gap gets a proportionally longer, still-smooth
# close instead of a snap.
FINISH_MS      = 350              # floor — even a near-zero gap gets a small beat
FINISH_MS_PER_GAP = 1400          # extra ms per 100% of remaining gap at reveal
FINISH_MS_MAX  = 1400
FINISH_CURVE = 1.4                # >1 = the final fill accelerates into 100 % —
                                  # kept mild now that BOOT_CURVE=1.0 means the
                                  # bar should already be close when this fires;
                                  # it used to also be covering BOOT_CURVE's
                                  # accumulated lag, which is why it needed to
                                  # be sharp (2.1) and quick (420ms) before
FINISH_TICK_MS = 20
# The game starts playing audio the moment its loading ends, so the ring must
# already be full by then: once the boot counter's climb rate says it tops out
# within PREFILL_LEAD_S, the ring fills over PREFILL_MS and holds at 100 %
# (celebrating) until the game is actually ready, then the game shows at once.
PREFILL_LEAD_S = 0.8
PREFILL_MS     = 450
PREFILL_MIN_SAMPLE_S = 0.3        # counter climb observed this long before its
                                  # rate is trusted

# The reveal already forces the ring back to a visual 0 (see
# restart_loading_display) even though the real, tracked progress is
# already well ahead by then — but immediately snapping the display up to
# catch up reads as fake, a bar that "starts" already most of the way
# there. INTRO_* instead walks it up to INTRO_TARGET by hand, in small
# randomly-paced steps that look like the first real steps of actual work
# (clean_files, static files — genuinely quick, genuinely small), THEN
# hands off to the normal tracked display — which, being already ahead,
# jumps forward to meet the real value. That jump is the payoff: a
# deliberately unhurried, believable start followed by a satisfying
# acceleration, rather than one long uniform crawl.
INTRO_TARGET      = 0.15
# Steps are drawn from this weighted set rather than a flat range: real
# counters don't tick evenly, they sit still and then skip several points
# at once when a chunk of work lands. Weights keep most steps small with
# the occasional jump.
INTRO_STEPS       = ((1, 0.30), (2, 0.28), (3, 0.18), (4, 0.12), (5, 0.08), (7, 0.04))
INTRO_DELAY_MS    = (90, 380)
INTRO_HOLD_MS     = (500, 1100)   # dead stop on 0 before the first step

# ── Game launcher thread ───────────────────────────────────────────────────────

# Loading-bar trace (progress, boot counter, reveal decisions): DEBUG only.
bar_log = get_logger("ingame.loadingbar")


class GameLauncherThread(QThread):
    """Starts the Rugby08 backend handler in a worker thread."""
    error      = pyqtSignal(str)
    # carries the parsed match result (or None if the game gave us none)
    game_ended = pyqtSignal(object)
    # (fraction 0..1 of the preparation work done, fraction once the running
    #  step completes, label of the running step)
    prep_progress = pyqtSignal(float, float, str)

    def __init__(self, match_data):
        super().__init__()
        self.match_data = match_data

    def _debug_match_data(self):
        match_data = self.match_data

        log.debug("===== FRONTEND MATCH DEBUG =====")

        if not isinstance(match_data, dict):
            log.warning("No match data available from frontend.")
            return

        for team_key in ("team_A", "team_B"):
            team = match_data.get(team_key, {}) or {}
            log.debug(f"[{team_key}]")
            log.debug(f"Team: {team.get('name', 'Unknown')}")
            log.debug(f"Kit front: {team.get('kit_front', 'N/A')}")
            log.debug(f"Kit back: {team.get('kit_back', 'N/A')}")

            players = team.get("players", []) or []
            log.debug(f"Players selected: {len(players)}")
            for index, player in enumerate(players, start=1):
                if not isinstance(player, dict):
                    log.debug(f"  {index:02d}. {player}")
                    continue

                positions = [player.get("pos1"), player.get("pos2"), player.get("pos3")]
                positions = [pos for pos in positions if pos]
                positions_text = ", ".join(positions) if positions else "N/A"
                log.debug(f"  {index:02d}. {player.get('name', 'Unknown')} | positions: {positions_text}")

        log.debug("===============================")

    def run(self):
        try:
            self._debug_match_data()
            import backend.start_match
            result = backend.start_match.start_match(
                self.match_data, start_R08=True,
                progress_callback=self.prep_progress.emit,
            )
            self.game_ended.emit(result)
        except Exception as e:
            self.error.emit(str(e))


class _LinuxPollThread(QThread):
    """Runs one round of the X11 embed poll (psutil scan + xdotool calls) off
    the GUI thread — see GameWidget._own_wid for why this is safe: `poll_fn`
    (GameWidget._poll_linux_snapshot) only reads state and shells out, it
    never touches a widget or paints."""
    result = pyqtSignal(set, object)

    def __init__(self, poll_fn, parent=None):
        super().__init__(parent)
        self._poll_fn = poll_fn

    def run(self):
        new_pids, xid = self._poll_fn()
        self.result.emit(new_pids, xid)


# ── Game widget ────────────────────────────────────────────────────────────────

class GameWidget(QWidget):
    def __init__(self, end_callback, team_selection_callback=None,
                 result_callback=None, on_loading_end=None):
        super().__init__()
        self.end_callback = end_callback
        # Called with the parsed match result so the shell can show the
        # full-time screen; falls back to end_callback when unset.
        self.result_callback = result_callback
        self.team_selection_callback = team_selection_callback
        # Called once per launch, the moment loading is done and the game is
        # about to be revealed — lets the shell stop its loading-track loop
        # instead of this widget knowing anything about menu music.
        self._on_loading_end = on_loading_end
        self._worker: GameLauncherThread | None = None
        self._r08_pid: int | None = None
        self._reveal_fullscreen: bool | None = None   # decided per match, see _decide_reveal_mode
        self.match_data: dict | None = None

        # Embedding state
        self._hwnd = None
        self._x11_wid: int | None = None
        # Linux only: the mod window was fullscreen when the match started, so the
        # game is embedded in a host covering the WHOLE window instead of the
        # screen stack, whose width is capped (main.MAX_CONTENT_WIDTH) and
        # letterboxed on wide monitors — see _embed_host.
        self._linux_fullscreen = False
        self._fs_host: QWidget | None = None
        self._embedded_qwindow: QWindow | None = None
        self._embedded_container: QWidget | None = None
        self._embed_timer: QTimer | None = None
        self._embed_deadline = 0.0
        self._game_active = False
        self._pre_launch_pids: set[int] = set()
        # Cached once per launch (start_executable, GUI thread): winId() is
        # unsafe to call from the poll worker thread, and it never changes
        # for the lifetime of a match.
        self._own_wid: int | None = None
        # psutil + xdotool (Linux embed polling) are subprocess/syscall-heavy
        # enough (tens of ms per tick) to visibly steal frames from the ~30 fps
        # loading-ring animation if run on the GUI thread every EMBED_POLL_MS.
        # Offloaded to this worker; see _poll_linux / _on_linux_poll_result.
        self._linux_poll_thread: "_LinuxPollThread | None" = None
        # reveal_mode "fullscreen": focus handling while the game is hidden
        self._foreground_locked = False
        self._last_refocus = 0.0

        # Frontend-reveal watch state
        self._frontend_timer: QTimer | None = None
        self._x11_map_timer: QTimer | None = None
        self._x11_map_deadline = 0.0
        self._x11_mapped_at = 0.0
        self._frontend_deadline = 0.0
        self._loading_w = 0
        self._revealed = False
        self._finishing = False
        self._finish_timer: QTimer | None = None
        self._boot_timer: QTimer | None = None
        self._screen_id_seen = False
        # Reveal conditions (see the FRONTEND_* block): both are sticky —
        # the screen id moves on past reveal_screen_id, and the counter can
        # be zeroed by the game the moment loading ends, so each is latched
        # the first time it is observed rather than re-tested at reveal.
        self._screen_id_reached = False
        self._counter_done = False
        self._counter_peak = 0
        self._counter_last = None
        self._counter_changed_at = 0.0
        self._counter_first = None       # (time, value) of the first non-zero reading
        self._reveal_wait_deadline = 0.0
        # Reveal hand-off: the game is shown once it is ready AND the ring is full
        self._game_ready = False
        self._bar_full = False
        self._prefilling = False
        # Pace jitter state (see PACE_PROFILE)
        self._pace = 1.0
        self._pace_until = 0.0
        self._bar_log_t0 = 0.0
        self._bar_log_last_tick = 0.0

        # Loading-screen animation
        self._anim_timer: QTimer | None = None
        self._anim_dots = 0

        # Loading progress state
        self._progress_target = 0.0
        self._progress_shown = 0.0
        self._progress_timer: QTimer | None = None
        # False when the game is not embedded: the bar then only covers the
        # preparation work, since the game boots in a window we don't watch.
        self._track_boot = True
        self._boot_started = 0.0
        self._screen_ids_seen: set[int] = set()

        self._init_ui()

    def _init_ui(self):
        self.setContentsMargins(0, 0, 0, 0)
        self.setStyleSheet("background-color: #000000; border: none;")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Loading screen shown while the game boots (the embedded game window
        # stays hidden behind it until the reveal). Progression bar: later.
        self._loading_panel = QWidget(self)
        self._loading_panel.setObjectName("loadingPanel")
        self._loading_panel.setStyleSheet(
            f"QWidget#loadingPanel {{ background-color: {BG_BASE}; border: none; }}")
        loading_layout = QVBoxLayout(self._loading_panel)
        loading_layout.setContentsMargins(0, 0, 0, 0)
        loading_layout.setSpacing(24)
        loading_layout.addStretch()

        # Épuré: one element carries the whole screen — a ring with the
        # percentage inside it. No pitch, no ball, no crowd (that motif
        # stays on the main menu). Crests either side give matchup context.
        ring_row = QHBoxLayout()
        ring_row.setContentsMargins(0, 0, 0, 0)
        ring_row.setSpacing(48)
        ring_row.addStretch(1)

        self._home_crest, home_col = self._build_crest_column(self._loading_panel)
        ring_row.addLayout(home_col)
        ring_row.setAlignment(home_col, Qt.AlignVCenter)

        self._progress = CircularLoadingRing(self._loading_panel)
        self._progress.setRange(0, PROGRESS_RESOLUTION)
        self._progress.setValue(0)
        self._progress.setFixedSize(280, 280)
        ring_row.addWidget(self._progress, alignment=Qt.AlignVCenter)

        self._away_crest, away_col = self._build_crest_column(self._loading_panel)
        ring_row.addLayout(away_col)
        ring_row.setAlignment(away_col, Qt.AlignVCenter)

        ring_row.addStretch(1)
        loading_layout.addLayout(ring_row)

        self._status = display_label("LOADING", 15, QFont.DemiBold,
                                     track=2.0, color=FG_SECONDARY, upper=False)
        self._status.setAlignment(Qt.AlignCenter)
        self._status.setParent(self._loading_panel)
        loading_layout.addSpacing(8)
        loading_layout.addWidget(self._status)

        loading_layout.addStretch()
        layout.addWidget(self._loading_panel, stretch=1)

        self.container = QWidget(self)
        self.container.setStyleSheet("border: none;")
        self.container.hide()
        layout.addWidget(self.container, stretch=1)

    def _build_crest_column(self, parent):
        crest = QLabel(parent)
        crest.setFixedSize(124, 124)
        crest.setAlignment(Qt.AlignHCenter | Qt.AlignBottom)
        crest.setStyleSheet("background: transparent;")
        name = display_label("", 17, QFont.DemiBold, track=2.0, color=FG_MUTED)
        name.setAlignment(Qt.AlignCenter)
        name.setParent(parent)
        col = QVBoxLayout()
        col.setSpacing(6)
        # A few px of headroom, not centered on 0: pushes the crest+name
        # block down a bit within its (now vertically-centered-on-the-ring)
        # cell rather than sitting dead center.
        col.setContentsMargins(0, 18, 0, 0)
        col.addWidget(crest, alignment=Qt.AlignCenter)
        # AlignTop: without it the label's cell absorbs any leftover height
        # in the column and QLabel centers its text inside that whole cell —
        # the name text then floats far below the crest instead of sitting
        # right under it.
        col.addWidget(name, alignment=Qt.AlignHCenter | Qt.AlignTop)
        crest._name_label = name
        return crest, col

    def _apply_matchup_crests(self, match_data):
        """Populate the crests flanking the loading ring, if the match data
        carries them. Fails safe to a blank, captionless column."""
        for label, side in ((self._home_crest, "team_A"), (self._away_crest, "team_B")):
            team = (match_data or {}).get(side, {}) or {}
            label._name_label.setText(str(team.get("name", "")).upper())
            label.clear()
            logo_rel = team.get("logo")
            if logo_rel:
                path = os.path.join(config.mod_data_directory, logo_rel)
                if os.path.isfile(path):
                    pix = QPixmap(path)
                    if not pix.isNull():
                        # Trim the logo's transparent margin: it is part of the
                        # visual gap between crest and name. The crest sits on
                        # the bottom of its box, right above the name.
                        try:
                            from PIL import Image
                            box = Image.open(path).convert("RGBA").getchannel("A").getbbox()
                            if box:
                                pix = pix.copy(box[0], box[1], box[2] - box[0], box[3] - box[1])
                        except Exception:
                            pass
                        label.setPixmap(pix.scaled(118, 118, Qt.KeepAspectRatio,
                                                    Qt.SmoothTransformation))

    # ── Kick-off transition (see MatchSetupScreen._begin_zoom_in) ─────────────
    # The loading screen is shown while match setup's players are still
    # dollying in over it: the crests are flown in by an overlay and land on
    # their labels, and everything else fades in.

    def _fade_widgets(self):
        """Widgets faded with a QGraphicsOpacityEffect (the ring fades through
        its own set_fade instead — see prepare_intro_transition)."""
        return (self._status,
                self._home_crest._name_label, self._away_crest._name_label)

    def prepare_intro_transition(self):
        """Make the loading elements (and crests) invisible, ready to fade in."""
        self._progress.set_fade(0.0)
        self._intro_effects = []
        for w in self._fade_widgets():
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(0.0)
            w.setGraphicsEffect(eff)
            self._intro_effects.append(eff)
        # A fully transparent effect is skipped by Qt (nothing is rendered),
        # so holding the real crests hidden while the flyers travel is free.
        self._crest_effects = []
        for w in (self._home_crest, self._away_crest):
            eff = QGraphicsOpacityEffect(w)
            eff.setOpacity(0.0)
            w.setGraphicsEffect(eff)
            self._crest_effects.append(eff)

    def crest_display_rect(self, side, ancestor):
        """(QRect, QPixmap) — where a crest's logo is drawn, in `ancestor`'s
        coordinates. The rect is empty when the crest has no logo."""
        label = self._home_crest if side == "home" else self._away_crest
        pix = label.pixmap()
        box = QRect(label.mapTo(ancestor, QPoint(0, 0)), label.size())
        if pix is None or pix.isNull():
            return QRect(), None
        w, h = int(pix.width() / pix.devicePixelRatio()), int(pix.height() / pix.devicePixelRatio())
        # AlignHCenter | AlignBottom, as set in _build_crest_column
        return QRect(box.x() + (box.width() - w) // 2, box.bottom() + 1 - h, w, h), pix

    def play_intro_fade(self, duration_ms=1000):
        """Fade the loading elements in (not the crests: see show_crests).

        One animation drives every element, so a frame costs one timer tick
        and one pass over the widgets instead of an independent animation per
        widget."""
        anim = QVariantAnimation(self)
        anim.setDuration(duration_ms)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.InOutQuad)

        def apply(v):
            self._progress.set_fade(v)
            for eff in self._intro_effects:
                eff.setOpacity(v)
        anim.valueChanged.connect(apply)
        self._intro_anim = anim
        anim.start()

        def done():
            self._progress.set_fade(1.0)
            for w in self._fade_widgets():
                w.setGraphicsEffect(None)
        QTimer.singleShot(duration_ms + 50, done)

    def show_crests(self):
        """The flown-in crests have landed: show the real ones in their place."""
        for w in (self._home_crest, self._away_crest):
            w.setGraphicsEffect(None)

    # ── Public API ─────────────────────────────────────────────────────────────

    def restart_loading_display(self):
        """Called right when this screen becomes visible, independent of
        start_executable() (which may have run moments earlier while this
        screen was still hidden behind match setup's kickoff animation) —
        snaps the ring's drawn arc to 0 so the reveal always reads as a
        fresh climb, even though the underlying progress is already ahead.
        See _run_intro_climb for how it gets from there to that real value
        without either looking frozen or looking fake.

        _progress_shown is reset alongside the drawn arc (never
        _progress_target — that's the real, monotonically-tracked backend
        progress, and must keep whatever it already reached) so the eased
        chase this feeds into (_tick_progress) starts from the same 0 the
        intro climb just showed, instead of resuming from a stale, higher
        value and painting a visible drop once the two hand off."""
        self._progress.reset_display()
        self._progress_shown = 0.0
        self._run_intro_climb()

    def _run_intro_climb(self):
        self._intro_value = 0.0
        self._progress.setValue(0)
        if self._progress_timer:
            self._progress_timer.stop()   # only the intro drives the ring for now

        # restart_loading_display() can be called again before a previous
        # climb's chain of singleShots has finished (e.g. the kickoff
        # transition re-triggers it once the ring actually fades into view,
        # on top of the one fired when the screen was first switched to) —
        # a generation token lets the stale chain notice it's been
        # superseded and quietly stop, instead of the two climbs
        # interleaving writes to _intro_value.
        self._intro_gen = getattr(self, "_intro_gen", 0) + 1
        gen = self._intro_gen

        def pick_step():
            roll, acc = random.random(), 0.0
            for points, weight in INTRO_STEPS:
                acc += weight
                if roll <= acc:
                    return points / 100.0
            return INTRO_STEPS[0][0] / 100.0

        def step():
            if gen != self._intro_gen:
                return   # superseded by a later restart_loading_display()
            self._intro_value = min(INTRO_TARGET, self._intro_value + pick_step())
            self._progress.setValue(int(self._intro_value * PROGRESS_RESOLUTION))
            if self._intro_value >= INTRO_TARGET:
                # Hand off to the real tracked value — already well ahead
                # after everything that ran hidden behind the kickoff
                # animation, so this is where the climb visibly surges.
                # Floor it at what the intro just displayed: _progress_shown
                # was frozen (timer stopped) for the whole climb, so if real
                # progress happened to still be behind INTRO_TARGET, the
                # first tick after resuming would otherwise paint a value
                # BELOW what's on screen right now — a visible regression.
                self._progress_shown = max(self._progress_shown, self._intro_value)
                if self._progress_timer:
                    self._progress_timer.start(PROGRESS_EASE_MS)
                return
            QTimer.singleShot(random.randint(*INTRO_DELAY_MS), step)

        # Sit visibly on 0 first: something that starts counting the
        # instant it appears reads as scripted, a beat of nothing reads as
        # work actually getting under way.
        QTimer.singleShot(random.randint(*INTRO_HOLD_MS), step)

    def start_executable(self, match_data=None):
        self.match_data = match_data
        self._apply_matchup_crests(match_data)
        self._reset_embed_state()
        self._decide_reveal_mode()
        self._linux_fullscreen = bool(IS_LINUX and self.window().isFullScreen())
        self._game_active = True

        if config.simulation_mode:
            self._stop_progress(hide=True)
            self._show_message("Simulation mode — returning in 2 s…")
            QTimer.singleShot(2000, self._on_game_ended)
            return

        # Snapshot windows that already match the embed title BEFORE launching,
        # so we only ever embed a window that appears afterwards (the game).
        self._pre_launch_wids = self._list_candidate_wids() if (IS_LINUX and HAS_XDOTOOL) else set()
        # Snapshot game-named PIDs before launch too, so the window is matched to
        # the game's *own* process (robust) rather than by window title.
        self._pre_launch_pids = self._running_game_pids()

        self._start_progress()

        # Monitor the game is revealed on (reveal_mode "fullscreen"). Read here,
        # in the GUI thread, before the backend writes the proxy ini from it.
        config.reveal_monitor_rect = self._target_monitor_rect()
        # Linux: the game is embedded and stretched to fill its host (the whole
        # mod window when fullscreen, else this screen). It only RENDERS at the
        # size its d3d8 proxy is told (FrontendWidth/Height) — enlarging its
        # window afterwards leaves the picture in a corner — so hand the backend
        # that size, in the game's own (physical) pixels.
        config.embed_frontend_size = bool(IS_LINUX and getattr(config, "embed_game", True))
        if config.embed_frontend_size:
            # (Not `self`: a page of the stack that has not been shown yet still has
            # its construction-time size; the stack widget itself is laid out.)
            target = self.window() if self._linux_fullscreen else (self.parentWidget() or self)
            ratio = target.devicePixelRatioF()
            config.reveal_monitor_rect = (0, 0, int(target.width() * ratio),
                                          int(target.height() * ratio))
        self._lock_foreground()

        self._worker = GameLauncherThread(self.match_data)
        self._worker.error.connect(self._on_launch_error)
        self._worker.game_ended.connect(self._on_game_ended)
        self._worker.prep_progress.connect(self._on_prep_progress)
        self._worker.start()

        # Not embedding: the bar can still show the preparation work, but the
        # game's boot happens in its own window and is not tracked.
        if not getattr(config, "embed_game", True):
            self._track_boot = False
            self._show_message("Game is launching in its own window.")
            return

        if IS_LINUX and not HAS_XDOTOOL:
            self._track_boot = False
            self._show_message(
                "Game is launching in its own window.\n"
                "(install 'xdotool' to embed it here)"
            )
            return

        self._start_loading_anim()

        self._own_wid = int(self.window().winId())
        self._embed_deadline = time.time() + EMBED_TIMEOUT_S
        self._embed_timer = QTimer(self)
        self._embed_timer.timeout.connect(self._poll_for_window)
        self._embed_timer.start(EMBED_POLL_MS)

    # ── Loading screen ─────────────────────────────────────────────────────────

    def _show_match_message(self):
        # Skip if the match ended or the screen was reset during the delay.
        if self._revealed:
            self._show_message("Match in progress")

    def _show_message(self, text: str):
        """Static status text on the loading panel (stops the LOADING animation)."""
        self._stop_loading_anim()
        self._status.setText(text)

    def _start_loading_anim(self):
        self._stop_loading_anim()
        self._anim_dots = 0
        self._status.setText("LOADING")
        self._anim_timer = QTimer(self)
        self._anim_timer.timeout.connect(self._tick_loading_anim)
        self._anim_timer.start(LOADING_ANIM_MS)

    def _stop_loading_anim(self):
        if self._anim_timer:
            self._anim_timer.stop()
            self._anim_timer = None

    def _tick_loading_anim(self):
        self._anim_dots = (self._anim_dots + 1) % 4
        self._status.setText("LOADING" + "." * self._anim_dots)

    # ── Loading progress ───────────────────────────────────────────────────────

    def _bar_log(self, event: str, **fields):
        """Loading-bar trace, at DEBUG on the "ingame.loadingbar" logger."""
        if not bar_log.isEnabledFor(logging.DEBUG):
            return
        now = time.time()
        elapsed = now - (self._bar_log_t0 or now)
        parts = [f"+{elapsed:6.2f}s",
                 f"shown={self._progress_shown:.3f}",
                 f"target={self._progress_target:.3f}",
                 f"{event}"]
        parts += [f"{k}={v}" for k, v in fields.items()]
        bar_log.debug(" ".join(parts))

    def _start_progress(self):
        """Reset the bar and start easing it towards its target."""
        self._progress_target = 0.0
        self._progress_shown = 0.0
        self._track_boot = True
        self._boot_started = 0.0
        self._screen_ids_seen = set()
        self._bar_log_t0 = time.time()
        self._bar_log_last_tick = 0.0
        self._bar_log("start")
        self._progress.setValue(0)
        self._progress.show()
        if self._progress_timer is None:
            self._progress_timer = QTimer(self)
            # CoarseTimer's batching/slack is noticeable at a 40 ms interval;
            # see CircularLoadingRing's own timer for the same fix.
            self._progress_timer.setTimerType(Qt.PreciseTimer)
            self._progress_timer.timeout.connect(self._tick_progress)
        self._progress_timer.start(PROGRESS_EASE_MS)

    def _stop_progress(self, hide=False):
        if self._progress_timer:
            self._progress_timer.stop()
        if hide:
            self._progress.hide()

    def _set_progress(self, target: float, shown_floor: float | None = None):
        """Move the bar's target forward (never backwards). `shown_floor` snaps
        the displayed value up immediately instead of easing towards it."""
        self._progress_target = max(self._progress_target, min(1.0, float(target)))
        if shown_floor is not None:
            self._progress_shown = max(self._progress_shown, min(1.0, float(shown_floor)))
            self._paint_progress()

    def _tick_progress(self):
        """Ease the displayed value towards the target so the bar keeps moving
        during long steps that report nothing (BIG repacking, game boot)."""
        gap = self._progress_target - self._progress_shown
        if gap > 0.0005:
            # Big gap (a real signal landed): close it quickly. Small gap (the
            # bar has caught up and nothing new is reported): crawl.
            rate = PROGRESS_EASE_RATE if gap > PROGRESS_CRAWL_GAP else PROGRESS_CRAWL_RATE
            self._progress_shown += gap * rate * self._pace_factor()
        elif gap > 0:
            self._progress_shown = self._progress_target
        else:
            return
        self._paint_progress()
        # sample the eased value once a second
        now = time.time()
        if now - self._bar_log_last_tick >= 1.0:
            self._bar_log_last_tick = now
            self._bar_log("ease")

    def _pace_factor(self):
        """Current speed multiplier, re-rolled every PACE_HOLD_S seconds."""
        now = time.time()
        if now >= self._pace_until:
            roll = random.random()
            acc = 0.0
            for factor, weight in PACE_PROFILE:
                acc += weight
                if roll <= acc:
                    self._pace = factor
                    break
            else:
                self._pace = 1.0
            self._pace_until = now + random.uniform(*PACE_HOLD_S)
        return self._pace

    def _paint_progress(self):
        self._progress.setValue(int(self._progress_shown * PROGRESS_RESOLUTION))

    def _on_prep_progress(self, start: float, end: float, label: str):
        """A preparation step in backend.start_match is about to run, covering
        the [start, end] slice of the preparation work. The bar snaps to the
        work actually done and then eases towards the end of the running step —
        decelerating, never quite arriving — so a long step (BIG repacking)
        keeps the bar moving instead of freezing until the next report."""
        start = max(0.0, min(1.0, start))
        end = max(start, min(1.0, end))
        scale = 1.0 if not self._track_boot else PREP_END
        # Target only, no shown_floor: steps that cost nothing report back to
        # back, and snapping the displayed value to each one made the bar
        # teleport (0.23 -> 0.75 in one frame). Easing glides there instead.
        self._set_progress(end * scale)
        if not self._track_boot and start >= 1.0:
            self._stop_progress()
            return
        self._bar_log("prep", step=repr(label), span=f"{start:.3f}->{end:.3f}")

    def _start_boot_watch(self):
        """Track the game's boot from the moment its process exists — the window
        can take a long time to appear (Wine start-up) and the boot counter is
        already climbing during that wait, which is where the bar used to sit
        frozen. Stops once _start_frontend_watch takes over the polling."""
        if self._boot_timer or self._revealed or self._finishing:
            return
        if not self._track_boot:
            return
        self._boot_timer = QTimer(self)
        self._boot_timer.timeout.connect(self._note_boot_progress)
        self._boot_timer.start(BOOT_WATCH_MS)
        self._bar_log("boot_watch_start", pid=self._r08_pid)
        self._start_loading_anim()
        self._note_boot_progress()

    def _stop_boot_watch(self):
        if self._boot_timer:
            self._boot_timer.stop()
            self._boot_timer = None

    def _note_boot_progress(self):
        """Advance the bar over the game's own boot, capped below 100 % until
        the reveal. Primary signal: the game's boot counter (0 ..
        config.boot_counter_max) read from process memory. Elapsed time (paced
        by config.expected_boot_seconds) runs alongside as a floor so the bar
        keeps moving if the counter stalls, and takes over entirely — together
        with a bump per newly seen screen id — when the counter is not
        configured or unreadable."""
        if not self._boot_started:
            self._boot_started = time.time()
        span = BOOT_END - PROC_SEEN

        expected = float(getattr(config, "expected_boot_seconds", 25) or 25)
        elapsed = time.time() - self._boot_started
        by_time = min(1.0, elapsed / expected) if expected > 0 else 1.0

        counter_max = int(getattr(config, "boot_counter_max", 0) or 0)
        if counter_max > 0:
            counter = self._read_boot_counter()
            if counter is not None:
                by_counter = max(0.0, min(1.0, counter / counter_max))
                self._set_progress(PROC_SEEN + span * max(by_counter, by_time) ** BOOT_CURVE)
              
                if time.time() - self._bar_log_last_tick >= 1.0:
                    self._bar_log_last_tick = time.time()
                    self._bar_log("boot", counter=counter,
                                  by_counter=f"{by_counter:.3f}",
                                  by_time=f"{by_time:.3f}")
                return
          
            if time.time() - self._bar_log_last_tick >= 1.0:
                self._bar_log_last_tick = time.time()
                self._bar_log("boot_counter_unreadable", pid=self._r08_pid)

        screen_id = self._read_game_screen_id()
        if screen_id is not None:
            self._screen_ids_seen.add(screen_id)
        by_screens = min(1.0, len(self._screen_ids_seen) * SCREEN_ID_STEP)

        self._set_progress(PROC_SEEN + span * max(by_time, by_screens) ** BOOT_CURVE)
      
        if time.time() - self._bar_log_last_tick >= 1.0:
            self._bar_log_last_tick = time.time()
            self._bar_log("boot_fallback", screen_id=screen_id,
                          by_time=f"{by_time:.3f}", by_screens=f"{by_screens:.3f}")

    # ── Embedding: shared ──────────────────────────────────────────────────────

    def _reset_embed_state(self):
        if self._embed_timer:
            self._embed_timer.stop()
            self._embed_timer = None
        if self._linux_poll_thread:
            # Let it finish on its own (it's mid-syscall) but stop it from
            # acting on a stale result or clobbering the next match's poll
            # thread when it finishes late.
            try:
                self._linux_poll_thread.result.disconnect(self._on_linux_poll_result)
                self._linux_poll_thread.finished.disconnect(self._clear_linux_poll_thread)
            except TypeError:
                pass
            self._linux_poll_thread = None
        if self._frontend_timer:
            self._frontend_timer.stop()
            self._frontend_timer = None
        self._stop_x11_map_watch()
        if self._finish_timer:
            self._finish_timer.stop()
            self._finish_timer = None
        self._stop_boot_watch()
        self._loading_w = 0
        self._revealed = False
        self._finishing = False
        self._screen_id_seen = False
        self._screen_id_reached = False
        self._counter_done = False
        self._counter_peak = 0
        self._counter_last = None
        self._counter_changed_at = 0.0
        self._counter_first = None
        self._reveal_wait_deadline = 0.0
        self._game_ready = False
        self._bar_full = False
        self._prefilling = False
        # Boot tracking is per launch. Left over from the previous match,
        # _boot_started makes the elapsed-time floor read as a boot that has
        # already taken minutes (by_time pinned at 1.0), which slams the bar
        # to BOOT_END the instant the second match starts; _screen_ids_seen
        # does the same to the fallback signal.
        self._boot_started = 0.0
        self._screen_ids_seen.clear()
        # Restored because start_executable turns it off for the non-embedded
        # paths — one launch without embedding must not silently disable boot
        # tracking for every launch after it.
        self._track_boot = True
        # The previous match's process is gone by every route into here, and a
        # stale pid both blocks re-detection (the `not self._r08_pid` guard in
        # the window polls) and makes every memory read of the new process
        # fail — _read_game_uint would be reading a dead pid.
        self._r08_pid = None
        self._hwnd = None
        self._release_foreground_lock()
        self._last_refocus = 0.0
        self._x11_wid = None
        self._embedded_qwindow = None
        if self._embedded_container:
            self._embedded_container.setParent(None)
            self._embedded_container.deleteLater()
            self._embedded_container = None
        self._pre_launch_wids = set()
        # Drop any native window we created for embedding so the next launch
        # starts from a clean container.
        self.container.hide()
        if self._fs_host is not None:
            self._fs_host.hide()
        self._loading_panel.show()
        self._stop_progress()
        self._progress_target = 0.0
        self._progress_shown = 0.0
        self._progress.setValue(0)
        # Clears the ring's celebration latch as well as its drawn arc — see
        # CircularLoadingRing.reset_display.
        self._progress.reset_display()
        self._progress.show()
        self._start_loading_anim()

    def _poll_for_window(self):
        if time.time() > self._embed_deadline:
            self._embed_timer.stop()
            self._embed_timer = None
            # The proxy may have booted the window off-screen for us to embed;
            # since embedding failed, put it back where the user can see it.
            self._move_window_onscreen()
            self._stop_progress(hide=True)
            self._show_message("Game is running in its own window.")
            return

        if IS_WINDOWS and WIN32_AVAILABLE:
            self._poll_windows()
        elif IS_LINUX and HAS_XDOTOOL:
            self._poll_linux()

    def _move_window_onscreen(self):
        """The d3d8 proxy boots the game window off-screen (d3d8_offscreen_boot)
        so it never flashes before embedding. If embedding fails, bring the
        window back into view — best-effort, never raises."""
        if self._fullscreen_reveal():
            # Never leave the game stranded off-screen: show it as it would
            # have been shown after loading.
            self._reveal_fullscreen_win32()
            return
        if not (getattr(config, "use_d3d8_proxy", False)
                and getattr(config, "d3d8_offscreen_boot", True)):
            return
        if IS_LINUX and HAS_XDOTOOL:
            xid = self._x11_wid or self._find_x11_window()
            if xid:
                self._xdotool("windowmove", str(xid), "100", "100")
                self._xdotool("windowmap", str(xid))
                self._xdotool("windowactivate", str(xid))
        elif IS_WINDOWS and WIN32_AVAILABLE:
            hwnd = self._hwnd or self._find_game_hwnd_by_pid(self._new_game_pids())
            if hwnd:
                try:
                    win32gui.SetWindowPos(
                        hwnd, win32con.HWND_TOP, 100, 100, 0, 0,
                        win32con.SWP_NOSIZE | win32con.SWP_SHOWWINDOW,
                    )
                except Exception as e:
                    log.warning(f"Could not move game window on-screen: {e}")

    # ── Embedding: Linux (X11) ─────────────────────────────────────────────────

    def _poll_linux(self):
        # The actual work (psutil scan + several xdotool subprocess spawns)
        # runs on _LinuxPollThread — done inline on the GUI thread it easily
        # took 50-150 ms per EMBED_POLL_MS tick, stealing frames from the
        # ~30 fps loading-ring animation and reading as stutter. One poll in
        # flight at a time; a tick that lands while the last one is still
        # running is simply skipped, so this never queues up work.
        if self._linux_poll_thread is not None:
            return
        self._linux_poll_thread = _LinuxPollThread(self._poll_linux_snapshot, self)
        self._linux_poll_thread.result.connect(self._on_linux_poll_result)
        self._linux_poll_thread.finished.connect(self._clear_linux_poll_thread)
        self._linux_poll_thread.start()

    def _poll_linux_snapshot(self):
        """Off the GUI thread: read-only (see _LinuxPollThread) — returns
        (new_pids, xid_or_None) without acting on either."""
        new_pids = self._new_game_pids()
        xid = self._find_x11_window()
        return new_pids, xid

    def _clear_linux_poll_thread(self):
        self._linux_poll_thread = None

    def _on_linux_poll_result(self, new_pids, xid):
        # The deadline/embed_timer may have fired (or the match ended) while
        # this result was in flight.
        if self._embed_timer is None:
            return
        # Best-effort: if exactly one new game process appeared, remember its PID
        # for clean termination. (Under Wine the process name may not match, in
        # which case this stays unset and X11 window matching is used as before.)
        if len(new_pids) == 1:
            self._r08_pid = next(iter(new_pids))
        if new_pids:
            self._set_progress(PROC_SEEN)
            self._bar_log("proc_seen", pids=sorted(new_pids))
            self._start_boot_watch()

        if xid:
            self._embed_timer.stop()
            self._embed_timer = None
            self._embed_x11(xid)

    @staticmethod
    def _xdotool(*args, timeout=2):
        """Run xdotool; return stdout (stripped) or None on any failure."""
        try:
            result = subprocess.run(
                ["xdotool", *args],
                capture_output=True, text=True, timeout=timeout,
            )
            if result.returncode != 0:
                return None
            return result.stdout.strip()
        except Exception:
            return None

    def _list_candidate_wids(self) -> set[int]:
        """All window ids matching the configured title.

        If no title is configured, match any named window.  Used both for the
        pre-launch snapshot and for finding the game window after launch.
        NOT --onlyvisible: the game boots fully off-screen (d3d8_offscreen_boot)
        and wine keeps fully off-screen windows unmapped, so the game window is
        never "visible" before we embed it. Tiny helper/IME windows that slip
        in are filtered out by EMBED_MIN_SIZE.
        """
        title = (config.embed_window_title or "").strip() or "."
        out = self._xdotool("search", "--name", title, timeout=3)
        if not out:
            return set()
        wids = set()
        for line in out.split("\n"):
            line = line.strip()
            if line.isdigit():
                wids.add(int(line))
        return wids

    def _window_area(self, xid: int):
        """Return (width, height) of a window, or None if it can't be read."""
        out = self._xdotool("getwindowgeometry", "--shell", str(xid))
        if not out:
            return None
        geo = {}
        for line in out.split("\n"):
            if "=" in line:
                key, _, val = line.partition("=")
                geo[key.strip()] = val.strip()
        try:
            return int(geo["WIDTH"]), int(geo["HEIGHT"])
        except (KeyError, ValueError):
            return None

    def _find_x11_window(self):
        """Pick the largest newly-appeared visible window matching the title."""
        new_wids = self._list_candidate_wids() - self._pre_launch_wids
        own_wid = self._own_wid

        best = None
        best_area = 0
        for xid in new_wids:
            if xid == own_wid:
                continue
            size = self._window_area(xid)
            if not size:
                continue
            w, h = size
            if w < EMBED_MIN_SIZE or h < EMBED_MIN_SIZE:
                continue
            if w * h > best_area:
                best, best_area = xid, w * h
        return best

    def _embed_x11(self, xid):
        # Realize a native X11 window for the container to reparent into, but
        # keep the container HIDDEN so the reparented game window stays invisible
        # while the game boots windowed (loading/title videos). The splash stays
        # up until _reveal_game() fires at the frontend transition.
        try:
            container_xid = int(self._embed_host().winId())
        except Exception as e:
            log.warning(f"X11 embed failed (no container window): {e}")
            self._stop_progress(hide=True)
            self._show_message("Game is running in its own window.")
            return

        # Strip window-manager state, unmap, THEN reparent: reparenting a
        # mapped window lets the WM briefly draw/animate it on the desktop.
        # Unmapped, the move into the (hidden) container is invisible.
        self._xdotool("windowstate", "--remove", "FULLSCREEN", str(xid))
        self._xdotool("windowunmap", "--sync", str(xid))
        result = self._xdotool("windowreparent", str(xid), str(container_xid))
        if result is None:
            # Reparent failed — leave the game in its own window, don't crash.
            log.warning("X11 embed failed: windowreparent unsuccessful")
            self._xdotool("windowmap", str(xid))   # undo the unmap
            self._move_window_onscreen()
            self._stop_progress(hide=True)
            self._show_message("Game is running in its own window.")
            return

        # Move the window to the container origin NOW: it booted at
        # -10000,-10000 (offscreen boot) and wine keeps windows it believes are
        # fully off-screen unmapped — at 0,0 inside the container wine considers
        # it on-screen again and lets it map. The container itself is still
        # hidden, so nothing shows until _reveal_game().
        self._xdotool("windowmove", str(xid), "0", "0")
        # Some window managers unmap a window when it is reparented — remap it.
        self._xdotool("windowmap", str(xid))

        # Wine virtual-desktop mode: the game window we just reparented was a
        # child of the "Wine desktop" X window, which is now left floating on
        # top. Minimise it so it doesn't cover the embedded game.
        self._hide_wine_desktop(xid)

        self._x11_wid = xid
        # Do NOT resize the window yet: leaving it at its loading size keeps the
        # proxy's loading->frontend resize observable.
        self._start_frontend_watch()

    def _hide_wine_desktop(self, embedded_xid):
        """Minimise the leftover Wine virtual-desktop window(s) so they don't
        cover the embedded game. No-op when not running a virtual desktop."""
        title = (getattr(config, "wine_virtual_desktop_title", "") or "").strip()
        if not title:
            return
        out = self._xdotool("search", "--name", title)
        if not out:
            return
        own = int(self.window().winId())
        for line in out.split("\n"):
            line = line.strip()
            if not line.isdigit():
                continue
            xid = int(line)
            if xid == embedded_xid or xid == own:
                continue
            self._xdotool("windowminimize", str(xid))
            log.debug(f"Minimised Wine virtual desktop window {xid}")

    def _embed_host(self):
        """The widget the game window is reparented into. Normally `container`,
        which fills the screen stack. In a fullscreen mod window on Linux it is
        a native child of the top-level window covering all of it: the screen
        stack stops at MAX_CONTENT_WIDTH and is centred, so on a wide monitor
        the game would fill only a column of the screen instead of all of it.
        Windows never takes this path (`_linux_fullscreen` needs IS_LINUX)."""
        if not self._linux_fullscreen:
            return self.container
        if self._fs_host is None:
            host = QWidget(self.window())
            host.setAttribute(Qt.WA_NativeWindow, True)
            host.setStyleSheet("background: #000000; border: none;")
            host.hide()
            self._fs_host = host
        return self._fs_host

    def _resize_embedded_x11(self):
        if not (IS_LINUX and self._x11_wid):
            return
        host = self._embed_host()
        if host is not self.container:
            host.setGeometry(self.window().rect())
        # xdotool sizes in device pixels; Qt's are logical once high-DPI scaling
        # is on (same conversion as _resize_embedded_win32).
        ratio = host.devicePixelRatioF()
        w = max(1, int(host.width() * ratio))
        h = max(1, int(host.height() * ratio))
        self._xdotool("windowmove", str(self._x11_wid), "0", "0")
        self._xdotool("windowsize", str(self._x11_wid), str(w), str(h))

    # ── Embedding: Windows ─────────────────────────────────────────────────────

    @staticmethod
    def _game_process_name() -> str:
        """Image name of the game process. Windows: the configured exe, as ever.
        Linux/Wine: always Rugby08.exe — R08_filename may be Rugby08Launcher.exe,
        a launcher that exits after starting the real game, and its pid (dead
        soon, and holding none of the game's memory) is the wrong one to track."""
        if IS_LINUX:
            return "Rugby08.exe"
        return getattr(config, "string_for_pid_search", "Rugby08.exe")

    def _running_game_pids(self) -> set:
        """PIDs of processes whose image name matches the game exe."""
        name = self._game_process_name()
        pids = set()
        for proc in psutil.process_iter(["pid", "name"]):
            try:
                if proc.info["name"] == name:
                    pids.add(proc.info["pid"])
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
        return pids

    def _new_game_pids(self) -> set:
        """Game PIDs that appeared after launch (excludes any pre-existing)."""
        return self._running_game_pids() - self._pre_launch_pids

    def _poll_windows(self):
        # Match the window to the game's *own* process (the exe we launched),
        # not by window title — so an unrelated window sharing the title can't
        # be grabbed. Wait until the game process exists, then pick its largest
        # visible top-level window.
        pids = self._new_game_pids()
        if not pids:
            return
        self._set_progress(PROC_SEEN)
        self._bar_log("proc_seen", pids=sorted(pids))
        if len(pids) == 1 and not self._r08_pid:
            self._r08_pid = next(iter(pids))
        self._start_boot_watch()
        hwnd = self._find_game_hwnd_by_pid(pids)
        if hwnd:
            self._embed_timer.stop()
            self._embed_timer = None
            self._hwnd = hwnd
            if self._fullscreen_reveal():
                self._adopt_win32()
            else:
                self._embed_win32()

    def _find_game_hwnd_by_pid(self, pids: set):
        own = int(self.window().winId())
        best = {"hwnd": None, "area": 0, "pid": None}
        # With a known class, match on it alone: the real window can be
        # minimised or off-screen, and the caps-probe window the game shows
        # first (same size, visible, gone ~0.3 s later) must never be taken.
        wanted_class = (getattr(config, "game_window_class", "") or "").strip()

        def _cb(hwnd, _):
            try:
                if hwnd == own:
                    return
                _, pid = win32process.GetWindowThreadProcessId(hwnd)
                if pid not in pids:
                    return
                l, t, r, b = win32gui.GetWindowRect(hwnd)
                w, h = r - l, b - t
                if wanted_class:
                    if win32gui.GetClassName(hwnd) != wanted_class:
                        return
                    w, h = max(w, 1), max(h, 1)
                else:
                    if not (win32gui.IsWindowVisible(hwnd) and win32gui.IsWindowEnabled(hwnd)):
                        return
                    if w < EMBED_MIN_SIZE or h < EMBED_MIN_SIZE:
                        return
                if w * h > best["area"]:
                    best.update(hwnd=hwnd, area=w * h, pid=pid)
            except Exception:
                return

        try:
            win32gui.EnumWindows(_cb, None)
        except Exception as e:
            log.warning(f"Win32 window enumeration failed: {e}")

        if best["hwnd"] is not None:
            self._r08_pid = best["pid"]   # remember for clean termination
        return best["hwnd"]

    def _embed_win32(self):
        try:
            # Reparent into the container but keep it hidden (splash stays up)
            # until the frontend transition; see _embed_x11 for the rationale.
            # WS_CHILD must be set when giving a window a parent — without it
            # focus/activation and z-order misbehave as a "popup with a parent".
            win32gui.SetWindowLong(
                self._hwnd, win32con.GWL_STYLE,
                win32con.WS_CHILD | win32con.WS_VISIBLE | win32con.WS_CLIPSIBLINGS,
            )
            win32gui.SetParent(self._hwnd, int(self.container.winId()))
            win32gui.SetWindowPos(
                self._hwnd, 0, 0, 0, 0, 0,
                win32con.SWP_NOMOVE | win32con.SWP_NOSIZE | win32con.SWP_NOZORDER
                | win32con.SWP_FRAMECHANGED,
            )
            # Do NOT resize yet — keep the proxy's frontend resize observable.
            self._start_frontend_watch()
        except Exception as e:
            log.warning(f"Win32 embed failed: {e}")
            self._move_window_onscreen()
            self._stop_progress(hide=True)
            self._show_message("Game is running.")

    def _resize_embedded_win32(self):
        if self._hwnd and WIN32_AVAILABLE:
            r = self.container.geometry()
            # Qt geometry is in logical pixels once high-DPI scaling is on
            # (see main.py); MoveWindow wants the physical ones.
            ratio = self.container.devicePixelRatioF()
            win32gui.MoveWindow(self._hwnd, 0, 0,
                                int(r.width() * ratio), int(r.height() * ratio), True)

    # ── Fullscreen reveal: Windows (reveal_mode "fullscreen") ──────────────────

    def _decide_reveal_mode(self):
        """Fix, for the match about to start, whether the game is revealed
        fullscreen (its own borderless window over the monitor) or embedded in
        the mod window: config.reveal_mode "auto" follows the mod window —
        fullscreen mod, fullscreen game; windowed mod, game embedded and filling
        it. Also published as config.reveal_fullscreen for the backend (proxy
        ini). Windows only: Linux always embeds, into a container that fills the
        mod window (fullscreen when the mod is)."""
        mode = str(getattr(config, "reveal_mode", "auto")).strip().lower()
        if not (IS_WINDOWS and WIN32_AVAILABLE):
            fullscreen = False
        elif mode == "fullscreen":
            fullscreen = True
        elif mode == "embed":
            fullscreen = False
        else:
            fullscreen = self.window().isFullScreen()
        self._reveal_fullscreen = fullscreen
        config.reveal_fullscreen = fullscreen

    def _fullscreen_reveal(self) -> bool:
        if self._reveal_fullscreen is None:
            self._decide_reveal_mode()
        return self._reveal_fullscreen

    def _target_monitor_rect(self):
        """(left, top, right, bottom) of the monitor the mod window is on, in
        physical pixels (this process is per-monitor DPI aware, so that is what
        its own SetWindowPos calls use), or None. Also records that monitor's
        scaling factor in config.reveal_monitor_scale: a DPI-UNAWARE game sees
        the screen divided by it, and the proxy (running inside the game)
        compares window sizes in those coordinates — see
        backend.mod_utils.configure_d3d8_proxy."""
        if not (IS_WINDOWS and WIN32_AVAILABLE):
            return None
        try:
            monitor = win32api.MonitorFromWindow(int(self.window().winId()),
                                                 win32con.MONITOR_DEFAULTTONEAREST)
            rect = tuple(win32api.GetMonitorInfo(monitor)["Monitor"])
        except Exception as e:
            log.warning(f"Could not read the target monitor: {e}")
            return None
        scale = 1.0
        try:
            dpi_x, dpi_y = ctypes.c_uint(), ctypes.c_uint()
            # MDT_EFFECTIVE_DPI = 0; 96 dpi = 100 %
            if ctypes.windll.shcore.GetDpiForMonitor(
                    int(monitor), 0, ctypes.byref(dpi_x), ctypes.byref(dpi_y)) == 0:
                scale = (dpi_x.value or 96) / 96.0
        except Exception as e:
            log.warning(f"Could not read the monitor scaling (assuming 100%): {e}")
        config.reveal_monitor_scale = scale
        return rect

    def _live_game_hwnd(self):
        """The adopted game window; re-found by pid if its handle died."""
        if self._hwnd and win32gui.IsWindow(self._hwnd):
            return self._hwnd
        pids = {self._r08_pid} if self._r08_pid else self._new_game_pids()
        hwnd = self._find_game_hwnd_by_pid(pids) if pids else None
        if hwnd != self._hwnd:
            log.debug(f"Game window handle changed: {self._hwnd} -> {hwnd}")
        self._hwnd = hwnd
        return hwnd

    def _set_taskbar_button(self, visible: bool):
        """Show/hide the game's taskbar button (WS_EX_APPWINDOW vs
        WS_EX_TOOLWINDOW). The taskbar only picks up an ex-style change when
        the window is shown again, hence the hide + show-without-activating."""
        ex = win32gui.GetWindowLong(self._hwnd, win32con.GWL_EXSTYLE)
        if visible:
            new = (ex | win32con.WS_EX_APPWINDOW) & ~win32con.WS_EX_TOOLWINDOW
        else:
            new = (ex | win32con.WS_EX_TOOLWINDOW) & ~win32con.WS_EX_APPWINDOW
        if new == ex:
            return
        win32gui.ShowWindow(self._hwnd, win32con.SW_HIDE)
        win32gui.SetWindowLong(self._hwnd, win32con.GWL_EXSTYLE, new)
        win32gui.ShowWindow(self._hwnd, win32con.SW_SHOWNOACTIVATE)

    def _hide_game_win32(self):
        """Keep the game window where nobody sees it: off the taskbar and
        off-screen (the proxy already boots it there with d3d8_offscreen_boot;
        this also covers d3d8_offscreen_boot = False)."""
        self._set_taskbar_button(False)
        if not win32gui.IsIconic(self._hwnd):
            win32gui.SetWindowPos(
                self._hwnd, 0, OFFSCREEN_POS, OFFSCREEN_POS, 0, 0,
                win32con.SWP_NOSIZE | win32con.SWP_NOZORDER | win32con.SWP_NOACTIVATE,
            )

    def _adopt_win32(self):
        """Take charge of the game's own window without reparenting it: hidden
        while it boots, focus handed back to the mod (the game grabs it when it
        starts), then _start_frontend_watch waits for the match to load."""
        try:
            self._hide_game_win32()
        except Exception as e:
            log.warning(f"Could not hide the game window: {e}")
            self._stop_progress(hide=True)
            self._show_message("Game is running.")
            self._reveal_fullscreen_win32()
            return
        self._force_foreground(int(self.window().winId()))
        self._start_frontend_watch()

    def _reveal_fullscreen_win32(self, activate=True):
        """Cover the target monitor with the game window (borderless: the
        proxy already strips the frame), put it back on the taskbar and, on the
        first call, bring it to the front. Also used for the re-asserts."""
        hwnd = self._live_game_hwnd()
        rect = getattr(config, "reveal_monitor_rect", None) or self._target_monitor_rect()
        if not hwnd or not rect:
            return
        left, top, right, bottom = rect
        try:
            self._set_taskbar_button(True)
            if win32gui.IsIconic(hwnd):
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            if win32gui.GetWindowRect(hwnd) != (left, top, right, bottom):
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOP, left, top, right - left, bottom - top,
                    win32con.SWP_SHOWWINDOW | win32con.SWP_FRAMECHANGED
                    | win32con.SWP_NOOWNERZORDER,
                )
                # A monitor-sized resize goes through the proxy's fullscreen
                # veto, which snaps the window back to its ini PosX/PosY
                # (off-screen) — move it in again, without resizing.
                win32gui.SetWindowPos(
                    hwnd, win32con.HWND_TOP, left, top, 0, 0,
                    win32con.SWP_NOSIZE | win32con.SWP_NOOWNERZORDER,
                )
            if activate:
                self._release_foreground_lock()
                self._force_foreground(hwnd)
        except Exception as e:
            log.warning(f"Could not reveal the game window fullscreen: {e}")

    def _lock_foreground(self):
        """Called at kick-off while the mod still owns the foreground: stop the
        game (started by us, so allowed to) from grabbing focus for its
        hidden windows. Pressing Alt or clicking always lifts it."""
        if self._fullscreen_reveal():
            self._foreground_locked = bool(ctypes.windll.user32.LockSetForegroundWindow(LSFW_LOCK))

    def _release_foreground_lock(self):
        if getattr(self, "_foreground_locked", False):
            ctypes.windll.user32.LockSetForegroundWindow(LSFW_UNLOCK)
            self._foreground_locked = False

    def _keep_mod_in_front(self):
        """Before the reveal, focus left on the hidden game (or on nothing)
        goes back to the mod — keystrokes would otherwise reach a game the
        user cannot see. Focus on any other app is left alone."""
        fg = win32gui.GetForegroundWindow()
        if fg:
            _, pid = win32process.GetWindowThreadProcessId(fg)
            if pid != self._r08_pid:
                return
        now = time.time()
        if now - self._last_refocus >= 0.5:
            self._last_refocus = now
            self._force_foreground(int(self.window().winId()))

    @staticmethod
    def _force_foreground(hwnd):
        """SetForegroundWindow, which Windows refuses unless the caller owns
        the foreground — e.g. once the game has grabbed it at start-up. On
        refusal, retry attached to the foreground thread's input queue."""
        try:
            win32gui.SetForegroundWindow(hwnd)
            return
        except Exception:
            pass
        me = win32api.GetCurrentThreadId()
        fg = win32gui.GetForegroundWindow()
        fg_thread = win32process.GetWindowThreadProcessId(fg)[0] if fg else 0
        attached = False
        try:
            if fg_thread and fg_thread != me:
                attached = bool(win32process.AttachThreadInput(me, fg_thread, True))
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        except Exception as e:
            log.warning(f"Could not bring window {hwnd} to the front: {e}")
        finally:
            if attached:
                win32process.AttachThreadInput(me, fg_thread, False)

    # ── Frontend reveal (hide the boot/loading window) ──────────────────────────

    def _embedded_window_size(self):
        """(width, height) of the embedded game window, or None."""
        if IS_LINUX and self._x11_wid:
            return self._window_area(self._x11_wid)
        if IS_WINDOWS and self._hwnd and WIN32_AVAILABLE:
            try:
                l, t, r, b = win32gui.GetClientRect(self._hwnd)
                return (r - l, b - t)
            except Exception:
                return None
        return None

    def _start_frontend_watch(self):
        """Poll until the game is ready to be shown: primarily the screen id
        (from process memory) reaching config.reveal_screen_id; fallback the
        proxy's loading->frontend window resize; last resort a timeout."""
        # Boot tracking already runs (since the process appeared); this timer
        # takes it over, so stop the standalone one.
        self._stop_boot_watch()
        # DEBUG: skip the loading screen entirely — show the game window now so
        # its own boot/title videos are visible instead of hidden behind the
        # ring. No frontend-reveal watch needed.
        if getattr(user_prefs, "debug_show_game_window", False):
            self._stop_progress()
            self._show_game()
            return
        # Floor only, and only if the boot signals have not got past it already.
        self._set_progress(EMBED_DONE)
        self._bar_log("embed_done", pid=self._r08_pid)
        self._start_loading_anim()
        size = self._embedded_window_size()
        self._loading_w = size[0] if size else 0
        self._frontend_deadline = time.time() + FRONTEND_TIMEOUT_S
        self._frontend_timer = QTimer(self)
        self._frontend_timer.timeout.connect(self._check_frontend_reached)
        self._frontend_timer.start(FRONTEND_WATCH_MS)

    def _read_game_uint(self, address, size):
        """Unsigned little-endian value of `size` bytes read at `address` in the
        game's process, or None if it can't be read (no pid yet, permissions,
        dead process...)."""
        pid = self._r08_pid
        if not pid or not address:
            return None
        if IS_LINUX:
            try:
                with open(f"/proc/{pid}/mem", "rb", buffering=0) as mem:
                    mem.seek(address)
                    raw = mem.read(size)
                if len(raw) != size:
                    return None
                return int.from_bytes(raw, "little")
            except Exception:
                return None
        if IS_WINDOWS:
            try:
                import ctypes
                PROCESS_VM_READ = 0x0010
                PROCESS_QUERY_INFORMATION = 0x0400
                kernel32 = ctypes.windll.kernel32
                handle = kernel32.OpenProcess(
                    PROCESS_VM_READ | PROCESS_QUERY_INFORMATION, False, pid)
                if not handle:
                    return None
                try:
                    buf = ctypes.create_string_buffer(size)
                    n = ctypes.c_size_t()
                    ok = kernel32.ReadProcessMemory(
                        handle, ctypes.c_void_p(address), buf, size, ctypes.byref(n))
                    if ok and n.value == size:
                        return int.from_bytes(buf.raw, "little")
                finally:
                    kernel32.CloseHandle(handle)
            except Exception:
                return None
        return None

    def _read_game_screen_id(self):
        """Current in-game screen id read from the game's process memory, or
        None if it can't be read."""
        addresses = getattr(config, "memory_addresses", {}) or {}
        return self._read_game_uint(addresses.get("screen_id"), 2)

    def _read_boot_counter(self):
        """Value of the game's boot-progress counter (Rugby08.exe + offset, see
        config.boot_counter_address), or None if it can't be read / is not
        configured."""
        address = int(getattr(config, "boot_counter_address", 0) or 0)
        if not address:
            return None
        return self._read_game_uint(address, 4)

    def _note_counter_done(self):
        """Latch `_counter_done` once the game's boot counter says loading is
        finished: it reached config.boot_counter_max, or it came within
        COUNTER_NEAR of it and then dropped away (the game zeroing it at the
        end of loading — polling can miss the exact top value). Returns True
        while the counter is a usable signal at all, so the caller can tell
        "not finished yet" apart from "no counter to wait for"."""
        counter_max = int(getattr(config, "boot_counter_max", 0) or 0)
        if counter_max <= 0:
            return False
        if self._counter_done:
            return True
        counter = self._read_boot_counter()
        if counter is None:
            # Unreadable (permissions, process gone): not a signal we can
            # wait on. If it was readable earlier, keep waiting on what we
            # already latched rather than flipping the condition mid-boot.
            return self._counter_peak > 0
        self._counter_peak = max(self._counter_peak, counter)
        now = time.time()
        if counter > 0 and self._counter_first is None:
            self._counter_first = (now, counter)
        if counter != self._counter_last:
            self._counter_last, self._counter_changed_at = counter, now
        if counter >= counter_max:
            self._counter_done = True
        elif (self._counter_peak >= counter_max * COUNTER_NEAR
                and counter < self._counter_peak * COUNTER_RESET_DROP):
            self._counter_done = True
        elif (counter >= counter_max * COUNTER_NEAR
                and now - self._counter_changed_at >= COUNTER_SETTLE_S):
            self._counter_done = True
        elif (counter >= counter_max * COUNTER_STALL_MIN
                and now - self._counter_changed_at >= COUNTER_STALL_S):
            self._counter_done = True
        if self._counter_done:
            self._bar_log("counter_done", counter=counter,
                          peak=self._counter_peak, max=counter_max)
        return True

    def _check_frontend_reached(self):
        if self._revealed or self._finishing:
            return

        # Fullscreen mode: if the game replaced its window, keep the new one
        # hidden too.
        if self._fullscreen_reveal():
            adopted = self._hwnd
            if self._live_game_hwnd() not in (None, adopted):
                try:
                    self._hide_game_win32()
                except Exception as e:
                    log.warning(f"Could not hide the game window: {e}")
            self._keep_mod_in_front()

        self._note_boot_progress()

        # Signal 1: the game's screen id says it is past the boot screens.
        reveal_id = int(getattr(config, "reveal_screen_id", 0x79) or 0)
        if reveal_id and not self._screen_id_reached:
            screen_id = self._read_game_screen_id()
            if screen_id is not None:
                self._screen_id_seen = True
                if screen_id == reveal_id:
                    self._screen_id_reached = True
                    self._bar_log("screen_id_reached",
                                  counter=self._read_boot_counter())

        # Signal 2: the boot counter reaching its max — the game's own
        # loading at 100 %, which is the moment to actually show it.
        counter_usable = self._note_counter_done()
        if (counter_usable and not self._counter_done and self._screen_id_reached
                and self._read_game_screen_id() == LOADED_SCREEN_ID):
            self._counter_done = True
            self._bar_log("counter_done", counter=self._read_boot_counter(),
                          peak=self._counter_peak, why="game reached its team sheets")
        screen_usable = bool(reveal_id) and (self._screen_id_seen
                                             or self._screen_id_reached)

        if counter_usable or screen_usable:
            wanted = [self._counter_done or not counter_usable,
                      self._screen_id_reached or not screen_usable]
            if all(wanted):
                self._reveal_game()
                return
            if (counter_usable and not self._prefilling
                    and (self._screen_id_reached or not screen_usable)):
                eta = self._seconds_to_counter_done()
                if eta is not None and eta <= PREFILL_LEAD_S:
                    self._start_prefill(eta)
            # Counter done, screen id still missing: give it REVEAL_GRACE_S
            # and then go without it (see the constant). Not the other way
            # round: reveal_screen_id comes up BEFORE the match loads, so a
            # grace started there would show the game's loading card on a
            # slow load — the counter is the authority, FRONTEND_TIMEOUT_S
            # the last resort.
            if self._counter_done:
                if not self._reveal_wait_deadline:
                    self._reveal_wait_deadline = time.time() + REVEAL_GRACE_S
                    self._bar_log("reveal_wait",
                                  counter_done=self._counter_done,
                                  screen_id_reached=self._screen_id_reached)
                elif time.time() > self._reveal_wait_deadline:
                    self._bar_log("reveal_wait_expired")
                    self._reveal_game()
                    return

        # Fallback (screen id never readable): the proxy's loading->frontend
        # window resize.
        if not self._screen_id_seen:
            frontend_w = int(getattr(config, "d3d8_frontend_width", 0) or 0)
            size = self._embedded_window_size()
            width = size[0] if size else 0
            reached = False
            if width > 0:
                if frontend_w > 0:
                    reached = width >= frontend_w
                elif self._loading_w > 0:
                    reached = width != self._loading_w
            if reached:
                self._reveal_game()
                return

        if time.time() > self._frontend_deadline:
            self._reveal_game()

    def _seconds_to_counter_done(self):
        """Estimated seconds until the boot counter tops out, from its average
        climb rate since the first non-zero reading; None while unknown."""
        counter_max = int(getattr(config, "boot_counter_max", 0) or 0)
        if counter_max <= 0 or self._counter_first is None or self._counter_last is None:
            return None
        t0, c0 = self._counter_first
        elapsed = time.time() - t0
        climbed = self._counter_last - c0
        if elapsed < PREFILL_MIN_SAMPLE_S or climbed <= 0:
            return None
        return max(0.0, (counter_max - self._counter_last) / (climbed / elapsed))

    def _start_prefill(self, eta):
        """Fill the ring now so it is already at 100 % when the game finishes
        loading (see PREFILL_LEAD_S); the reveal watch keeps running."""
        self._prefilling = True
        self._stop_progress()
        self._bar_log("prefill", eta=f"{eta:.2f}")
        self._start_fill(PREFILL_MS)

    def _reveal_game(self):
        """The game is ready. It is shown as soon as the ring is at 100 %: at
        once if the prefill already got there, else when the running prefill
        or a finish fill (FINISH_MS) reaches it."""
        if self._revealed or self._finishing:
            return
        self._finishing = True
        self._game_ready = True
        if self._on_loading_end:
            self._on_loading_end()
        self._bar_log("reveal", counter=self._read_boot_counter())
        self._stop_boot_watch()
        if self._frontend_timer:
            self._frontend_timer.stop()
            self._frontend_timer = None
        self._stop_progress()
        if self._bar_full:
            self._show_game()
            return
        if self._prefilling:
            return

        gap = 1.0 - self._progress_shown
        finish_ms = min(FINISH_MS_MAX, FINISH_MS + gap * FINISH_MS_PER_GAP)
        if self._fullscreen_reveal():
            # The stadium flyover starts ~0.6 s after loading ends and runs
            # on its own clock: the floor only, so little of it is missed.
            finish_ms = FINISH_MS
        self._bar_log("finish_start", gap=f"{gap:.3f}", finish_ms=f"{finish_ms:.0f}")
        self._start_fill(finish_ms)

    def _start_fill(self, finish_ms):
        """Walk the ring from where it is up to 100 % over `finish_ms`, then
        celebrate; the game is shown there if it is already ready."""
        start = self._progress_shown
        started = time.time()
        self._finish_timer = QTimer(self)
        # 20 ms interval: CoarseTimer's slack is proportionally largest here.
        self._finish_timer.setTimerType(Qt.PreciseTimer)

        def tick():
            elapsed_ms = (time.time() - started) * 1000.0
            t = min(1.0, elapsed_ms / finish_ms) if finish_ms > 0 else 1.0
            # Accelerate into 100 %: the last stretch snaps shut.
            self._progress_shown = start + (1.0 - start) * (t ** FINISH_CURVE)
            self._progress_target = max(self._progress_target, self._progress_shown)
            self._paint_progress()
            if t >= 1.0:
                if self._finish_timer:
                    self._finish_timer.stop()
                    self._finish_timer = None
                self._bar_full = True
                self._bar_log("bar_full", game_ready=self._game_ready)
                # Ball goes through the posts while the game finishes loading.
                self._progress.celebrate()
                if self._game_ready:
                    self._show_game()

        self._finish_timer.timeout.connect(tick)
        self._finish_timer.start(FINISH_TICK_MS)

    def _show_game(self):
        if self._revealed:
            return
        self._revealed = True
        self._finishing = False
        self._bar_log("show_game")
        if self._fullscreen_reveal():
            # The game covers the monitor in its own window; the mod stays
            # behind it on the finished loading screen.
            self._reveal_fullscreen_win32()
            QTimer.singleShot(MATCH_MESSAGE_DELAY_MS, self._show_match_message)
            for delay_ms in REVEAL_REASSERT_MS:
                QTimer.singleShot(delay_ms, self._reassert_fullscreen)
            return
        self._loading_panel.hide()
        host = self._embed_host()
        if host is self.container:
            self.container.show()
        else:
            host.setGeometry(self.window().rect())
            host.show()
            host.raise_()
        QApplication.processEvents()

        # Now stretch the game window to fill the container. The game's own
        # frontend transition (Reset) can land shortly after the reveal, so
        # re-assert the geometry a few times — the proxy stops resizing after
        # its first frontend sizing, but the timing of that first one varies.
        self._apply_embedded_geometry()
        for delay_ms in (300, 800, 1600):
            QTimer.singleShot(delay_ms, self._apply_embedded_geometry)
        if IS_LINUX and self._x11_wid:
            self._start_x11_map_watch()

    def _x11_window_state(self, xid):
        """(viewable, x, y, width, height) of an X window, position relative
        to its parent, or None if it can't be read."""
        try:
            out = subprocess.run(["xwininfo", "-id", str(xid)], capture_output=True,
                                 text=True, timeout=2).stdout
        except Exception:
            return None
        info = {}
        for line in out.split("\n"):
            key, sep, val = line.partition(":")
            if sep:
                info[key.strip()] = val.strip()
        try:
            return (info["Map State"] == "IsViewable",
                    int(info["Relative upper-left X"]), int(info["Relative upper-left Y"]),
                    int(info["Width"]), int(info["Height"]))
        except (KeyError, ValueError):
            return None

    def _start_x11_map_watch(self):
        self._stop_x11_map_watch()
        self._x11_map_deadline = time.time() + X11_MAP_WATCH_TIMEOUT_S
        self._x11_mapped_at = 0.0
        self._x11_map_timer = QTimer(self)
        self._x11_map_timer.timeout.connect(self._x11_map_tick)
        # Without xwininfo the map can't be seen: just re-pin, less often.
        self._x11_map_timer.start(X11_MAP_WATCH_MS if HAS_XWININFO else 1000)

    def _stop_x11_map_watch(self):
        if self._x11_map_timer:
            self._x11_map_timer.stop()
            self._x11_map_timer = None

    def _x11_map_tick(self):
        """Pin the embedded game window to its host once the proxy shows it
        (see X11_MAP_WATCH_MS), then for X11_MAP_SETTLE_S more."""
        now = time.time()
        if not (self._revealed and self._x11_wid) or now >= self._x11_map_deadline:
            self._stop_x11_map_watch()
            return
        if not HAS_XWININFO:
            self._apply_embedded_geometry()
            return
        state = self._x11_window_state(self._x11_wid)
        if not state or not state[0]:
            return                      # still hidden by the proxy
        viewable, x, y, w, h = state
        if not self._x11_mapped_at:
            self._x11_mapped_at = now
            self._x11_map_deadline = now + X11_MAP_SETTLE_S
            log.debug(f"Embedded game window mapped at {x},{y} {w}x{h}")
        host = self._embed_host()
        ratio = host.devicePixelRatioF()
        want_w = max(1, int(host.width() * ratio))
        want_h = max(1, int(host.height() * ratio))
        if (x, y, w, h) != (0, 0, want_w, want_h):
            log.debug(f"Re-pinning embedded game window: {x},{y} {w}x{h} "
                      f"-> 0,0 {want_w}x{want_h}")
            self._resize_embedded_x11()

    def _apply_embedded_geometry(self):
        """Fit the embedded game window to the container (windowed host resize,
        reveal, and post-reveal re-asserts all funnel through here)."""
        if not self._revealed or self._fullscreen_reveal():
            return
        if IS_LINUX and self._x11_wid:
            self._resize_embedded_x11()
        elif IS_WINDOWS and self._hwnd:
            self._resize_embedded_win32()

    def _reassert_fullscreen(self):
        if self._revealed and self._fullscreen_reveal():
            self._reveal_fullscreen_win32(activate=False)

    # ── Qt events ──────────────────────────────────────────────────────────────

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Only follow the container size once revealed — resizing the embedded
        # window earlier would mask the loading->frontend size jump we watch for.
        if not self._revealed:
            return
        # Defer one event-loop turn so the layout has settled and
        # container.width()/height() reflect the new wrapper size.
        QTimer.singleShot(0, self._apply_embedded_geometry)

    def on_hide(self):
        """Called by ScreenManager whenever navigation moves away from this
        screen (see app/shell.py) — the loading screen (or the embedded
        game, if it got that far) is about to stop being visible. A match
        still in progress at that point (the user backed out before it
        ended on its own) would otherwise leave Rugby08.exe running behind
        whatever screen replaces this one — same cleanup as the explicit
        BACK TO TEAM SELECTION button, just reachable from anywhere
        navigation can leave this screen, not only that one path."""
        if self._game_active:
            self._game_active = False
            self._terminate_game_process()
            self._reset_embed_state()

    def closeEvent(self, event):
        self._terminate_game_process()
        if self._worker and self._worker.isRunning():
            self._worker.wait(5000)
        event.accept()

    # ── Slots ──────────────────────────────────────────────────────────────────

    def _on_launch_error(self, msg: str):
        if self._embed_timer:
            self._embed_timer.stop()
            self._embed_timer = None
        self._game_active = False
        self._release_foreground_lock()
        self._stop_progress(hide=True)
        self._show_message(f"Launch error:\n{msg}")
        # No back button on the loading screen any more: don't strand the user here.
        QTimer.singleShot(5000, self._go_back_to_team_selection)

    def _on_game_ended(self, result=None):
        if not self._game_active:
            return
        self._game_active = False
        self._reset_embed_state()
        if self._fullscreen_reveal():
            # The fullscreen game window just went away: bring the mod (and
            # the full-time screen) back to the front.
            self._force_foreground(int(self.window().winId()))
        if self.result_callback:
            self.result_callback(result)
        else:
            self.end_callback()

    def _go_back_to_team_selection(self):
        # Same teardown on_hide() now does for any navigation away from this
        # screen — kept as an explicit call here (rather than relying on the
        # ScreenManager to invoke on_hide() a moment later) so the process
        # is already dead and the panel already reset by the time
        # team_selection_callback's own screen switch actually happens, not
        # a frame after.
        self.on_hide()
        if self.team_selection_callback:
            self.team_selection_callback()

    def _terminate_game_process(self):
        pid = self._r08_pid
        if not pid:
            name = self._game_process_name()
            for proc in psutil.process_iter(["pid", "name"]):
                try:
                    if proc.info["name"] == name:
                        pid = proc.info["pid"]
                        break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        if pid:
            try:
                psutil.Process(pid).terminate()
                log.info(f"Rugby08 process {pid} terminated.")
            except psutil.NoSuchProcess:
                pass
            except Exception as e:
                log.error(f"Failed to terminate Rugby08 ({pid}): {e}")


if __name__ == "__main__":
    from ui import APP_STYLESHEET
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLESHEET)
    win = GameWidget(lambda: print("Game ended"))
    win.resize(800, 600)
    win.show()
    sys.exit(app.exec_())
