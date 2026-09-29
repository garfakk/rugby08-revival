"""
ui/music.py — menu background music
========================================
A shuffled rock playlist that runs under the menus, handing off to a single
dedicated loop (see LOADING_TRACK_FILE) while a match loads, and shutting up
entirely once the game's own audio takes over. Two pieces:

* `MenuMusic` — the player. Reads assets/audio/menu/tracks.json (see
  CREDITS.md next to it: every track is Creative Commons (BY, some with SA/NC/ND), so the artist MUST
  stay credited — that is what the medal below is for, not decoration).
  Drop a file in that folder and add a manifest entry to extend the
  playlist; no code change needed.
* `TrackMedal` — the bottom-left "now playing" plate that slides in whenever
  a track starts and fades itself back out a few seconds later.

Alt skips to the next track; the skip is wired app-wide in
main.MainWindow.eventFilter, since menu focus lives in whatever tile or row
the user is on, not in a widget this module owns.
"""
import json
import os
import random

from PyQt5.QtWidgets import QWidget, QGraphicsOpacityEffect
from PyQt5.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen
from PyQt5.QtCore import (
    Qt, QObject, QUrl, QRectF, QPropertyAnimation, QSequentialAnimationGroup,
    QEasingCurve, QEvent, QPoint, pyqtSignal,
)
from PyQt5.QtMultimedia import QMediaPlayer, QMediaContent

from shared.config import config
from shared.game_profile import game_profile
from ui.theme import (
    BG_RAISED, BORDER, ACCENT, FG_PRIMARY, FG_SECONDARY, FG_MUTED,
    FONT_DISPLAY, FONT_BODY,
)
from ui.broadcast import tracked_font, draw_frame

# Dedicated loading-screen loop — kept separate from the shuffled menu
# playlist (tracks.json) entirely, so it never turns up at random in the
# menus and the menus never turn up during a load.
LOADING_TRACK_FILE = "rock_metal_energetic_instrumental.mp3"


from shared.log import get_logger

log = get_logger(__name__)


class MenuMusic(QObject):
    """Shuffled, endlessly looping playlist. Every public method is safe to
    call when no tracks were found or the platform has no working media
    backend — the whole feature then silently does nothing rather than
    taking the menus down with it."""

    track_started = pyqtSignal(str, str)   # title, artist

    def __init__(self, parent=None):
        super().__init__(parent)
        self._tracks = self._load_manifest()
        self._order = list(range(len(self._tracks)))
        random.shuffle(self._order)
        self._pos = 0
        self._suspended = False   # a match owns the speakers right now
        self._loading = False     # looping the dedicated loading track, not the playlist
        self._failed = False

        self._player = QMediaPlayer(self)
        self._player.setVolume(self._target_volume())
        self._player.mediaStatusChanged.connect(self._on_status)
        self._player.error.connect(self._on_error)

    @staticmethod
    def _target_volume():
        """Same "Music" slider as the game's own audio settings
        (shared.game_profile, key "vol_music") — one volume for both."""
        return max(0, min(100, int(game_profile.get("vol_music"))))

    def _loading_track_path(self):
        directory = getattr(config, "menu_music_directory", None)
        if not directory:
            return None
        path = os.path.join(directory, LOADING_TRACK_FILE)
        return path if os.path.isfile(path) else None

    # ── manifest ─────────────────────────────────────────────────────────
    @staticmethod
    def _load_manifest():
        directory = getattr(config, "menu_music_directory", None)
        if not directory or not os.path.isdir(directory):
            return []
        manifest = os.path.join(directory, "tracks.json")
        try:
            with open(manifest, "r", encoding="utf-8") as fh:
                entries = json.load(fh).get("tracks", [])
        except (OSError, ValueError) as exc:
            log.warning(f"Menu music: cannot read {manifest}: {exc}")
            return []
        tracks = []
        for entry in entries:
            path = os.path.join(directory, entry.get("file", ""))
            if not os.path.isfile(path):
                log.warning(f"Menu music: missing file {path}, skipped")
                continue
            tracks.append({
                "path": path,
                "title": entry.get("title", os.path.basename(path)),
                "artist": entry.get("artist", ""),
            })
        return tracks

    @property
    def available(self):
        return bool(self._tracks) and not self._failed

    def current(self):
        if not self.available:
            return None
        return self._tracks[self._order[self._pos]]

    # ── transport ────────────────────────────────────────────────────────
    def start(self):
        """First play, or resume after a match. No-op while already
        playing, so screen changes can call it freely."""
        if not self.available or self._suspended:
            return
        if self._player.state() == QMediaPlayer.PlayingState:
            return
        if self._player.state() == QMediaPlayer.PausedState:
            self._player.setVolume(self._target_volume())
            self._player.play()
            return
        self._play_current()

    def suspend(self):
        """A match is starting: stop dead and refuse to restart until
        `release()`. Stops rather than pauses — the game owns audio for
        however long the match lasts, and a paused player holding the
        device open is what makes the game's own sound stutter on some
        ALSA/PulseAudio setups."""
        self._suspended = True
        self._loading = False
        self._player.stop()

    def play_loading(self):
        """A match is loading: swap to the dedicated loading track (see
        LOADING_TRACK_FILE), looping, instead of the shuffled playlist. Call
        `stop_loading()` once loading ends, before the game's own audio takes
        over."""
        self._suspended = True
        self._loading = True
        path = self._loading_track_path()
        if path is None:
            log.warning(f"Menu music: loading track {LOADING_TRACK_FILE} not found")
            self._player.stop()
            return
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(path)))
        self._player.setVolume(self._target_volume())
        self._player.play()

    def stop_loading(self):
        """Loading is over — cut the loop dead, same as `suspend()`."""
        self.suspend()

    def release(self):
        """Back in the menus — allowed to play again."""
        self._suspended = False
        self._loading = False

    def skip(self):
        """Alt: next track, restarting the shuffle order once it runs out."""
        if not self.available or self._suspended:
            return
        self._pos = (self._pos + 1) % len(self._order)
        if self._pos == 0:
            random.shuffle(self._order)
        self._play_current()

    def set_volume(self, value):
        self._player.setVolume(max(0, min(100, int(value))))

    def _play_current(self):
        track = self.current()
        if track is None:
            return
        self._player.setMedia(QMediaContent(QUrl.fromLocalFile(track["path"])))
        self._player.setVolume(self._target_volume())
        self._player.play()
        self.track_started.emit(track["title"], track["artist"])

    # ── player callbacks ─────────────────────────────────────────────────
    def _on_status(self, status):
        if status == QMediaPlayer.EndOfMedia:
            if self._loading:
                self._player.setPosition(0)
                self._player.play()
            elif not self._suspended:
                self.skip()
        elif status == QMediaPlayer.InvalidMedia:
            if self._loading:
                log.warning(f"Menu music: unplayable loading track {LOADING_TRACK_FILE}")
            else:
                log.warning(f"Menu music: unplayable file {self.current()}")
                self.skip()

    def _on_error(self, *_args):
        # A missing platform codec/backend reports here, once per media.
        # Give up on music entirely rather than error-looping the playlist.
        if self._player.error() in (QMediaPlayer.ResourceError,
                                    QMediaPlayer.ServiceMissingError):
            log.warning(f"Menu music disabled: {self._player.errorString()}")
            self._failed = True
            self._player.stop()


class TrackMedal(QWidget):
    """Bottom-left "now playing" plate. Deliberately a leaf widget with no
    children and no repaint timer of its own: a QGraphicsOpacityEffect over
    a widget that repaints itself collides with Qt's effect renderer (see
    the same note in ui/intro.py)."""

    MARGIN = 26          # from the bottom-left corner of the anchor (else the window)
    HEIGHT = 58
    IN_MS = 380
    HOLD_MS = 4200
    OUT_MS = 700

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self._title = ""
        self._artist = ""
        self._eyebrow_font = tracked_font(FONT_BODY, 9, QFont.DemiBold, track=2.0)
        self._title_font = tracked_font(FONT_DISPLAY, 17, QFont.Bold, track=1.0)
        self._artist_font = tracked_font(FONT_BODY, 10, QFont.DemiBold, track=1.2)

        self._fx = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(self._fx)
        self._fx.setOpacity(0.0)
        self._group = None
        self._anchor = None
        self.hide()

    def set_anchor(self, widget):
        """Align to `widget`'s left edge instead of the window's: on a wide
        window the app's content is centred and capped in width, and the plate
        belongs to that column, not to the far edge of the screen. It follows
        the anchor whenever the anchor moves or resizes."""
        self._anchor = widget
        widget.installEventFilter(self)
        self.reposition()

    def eventFilter(self, watched, event):
        if watched is self._anchor and event.type() in (QEvent.Resize, QEvent.Move):
            self.reposition()
        return super().eventFilter(watched, event)

    # ── content ──────────────────────────────────────────────────────────
    def show_track(self, title, artist):
        self._title = (title or "").upper()
        self._artist = (artist or "").upper()
        self._resize_to_text()
        self.reposition()
        self.show()
        self.raise_()
        self._play()

    def _resize_to_text(self):
        title_w = QFontMetrics(self._title_font).horizontalAdvance(self._title)
        artist_w = QFontMetrics(self._artist_font).horizontalAdvance(self._artist)
        eyebrow_w = QFontMetrics(self._eyebrow_font).horizontalAdvance("NOW PLAYING")
        width = 30 + max(title_w, artist_w, eyebrow_w) + 26
        self.setFixedSize(max(220, min(width, 520)), self.HEIGHT)

    def reposition(self):
        """Parked against the anchor's (default: the parent's) bottom-left
        corner, above the hint bar.
        Called by the owner on every window resize and screen change — this
        widget floats over the screen stack rather than sitting in any layout.

        The hint bar belongs to whichever screen is showing, so its height is
        looked up rather than assumed; without it the plate sat on top of the
        bar's own "SELECT / EXIT" hints."""
        parent = self.parentWidget()
        if parent is None:
            return
        from ui.broadcast import HintBar
        bars = [b.height() for b in parent.window().findChildren(HintBar) if b.isVisible()]
        left = 0
        if self._anchor is not None:
            left = self._anchor.mapTo(parent, QPoint(0, 0)).x()
        self.move(left + self.MARGIN,
                  parent.height() - self.height() - self.MARGIN - (max(bars) if bars else 0))

    # ── animation ────────────────────────────────────────────────────────
    def _fade(self, start, end, ms, curve=QEasingCurve.InOutQuad):
        anim = QPropertyAnimation(self._fx, b"opacity", self)
        anim.setDuration(ms)
        anim.setStartValue(start)
        anim.setEndValue(end)
        anim.setEasingCurve(curve)
        return anim

    def _play(self):
        if self._group is not None:
            self._group.stop()
        seq = QSequentialAnimationGroup(self)
        seq.addAnimation(self._fade(self._fx.opacity(), 1.0, self.IN_MS,
                                    QEasingCurve.OutCubic))
        seq.addPause(self.HOLD_MS)
        seq.addAnimation(self._fade(1.0, 0.0, self.OUT_MS))
        seq.finished.connect(self.hide)
        self._group = seq
        seq.start()

    def dismiss(self):
        """Hide immediately — used when a match takes the screen."""
        if self._group is not None:
            self._group.stop()
            self._group = None
        self._fx.setOpacity(0.0)
        self.hide()

    # ── paint ────────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        rect = self.rect()
        p.fillRect(rect, QColor(BG_RAISED))
        draw_frame(p, rect, BORDER)
        p.fillRect(QRectF(0, 0, 4, self.height()), QColor(ACCENT))

        p.setFont(self._eyebrow_font)
        p.setPen(QColor(ACCENT))
        p.drawText(QRectF(18, 8, self.width() - 26, 13),
                   Qt.AlignLeft | Qt.AlignVCenter, "NOW PLAYING")

        p.setFont(self._title_font)
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(17, 20, self.width() - 26, 21),
                   Qt.AlignLeft | Qt.AlignVCenter, self._title)

        if self._artist:
            p.setFont(self._artist_font)
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(18, 40, self.width() - 26, 14),
                       Qt.AlignLeft | Qt.AlignVCenter, self._artist)

        # The licences these tracks ship under (CC BY / BY-SA) require
        # attribution wherever they are played — the artist line above is
        # that attribution, hence no option to hide it.
        p.setFont(self._eyebrow_font)
        p.setPen(QColor(FG_MUTED))
        # p.drawText(QRectF(0, 0, self.width() - 10, self.height()),
                #    Qt.AlignRight | Qt.AlignVCenter, "ALT ›")
