"""screens/settings.py — Settings screen

One tab per topic, whichever file a setting is saved to (user_prefs.ini for
the mod's own, game_profile.ini for the game's, see shared.game_profile):
Display, Audio, Gameplay, Camera, HUD, Advanced. A row tagged IN-GAME changes
only the game itself, not these menus; a dot marks a row that differs from its
default. Every value is saved as soon as it changes.

Keys go through app.input's actions, so a pad drives it the same way:
Up/Down pick a row, Left/Right change it, Enter opens a list, Q/E (LB/RB)
switch tabs, Y resets the tab, Esc (B) goes back.
"""
import sys
import logging
from pathlib import Path

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy, QStackedWidget, QLabel,
)
from PyQt5.QtCore import Qt, QEvent, QTimer

sys.path.append(str(Path(__file__).parent.parent.parent))
from shared.user_prefs import user_prefs, SCREEN_RATIOS
from shared.game_profile import game_profile, SECTIONS, RESOLUTIONS, UNSAFE_RESOLUTIONS

from shared.log import ROOT as LOG_ROOT, setup_logging
from app.display import native_resolution, native_screen_ratio
from app.input import Action, KEYMAP, HINT_GLYPH
from ui import make_page_header, make_separator, StyledButton, ToggleRow, ChoiceRow, CycleRow, SliderRow
from ui.widgets import make_in_game_tag, make_changed_mark
from ui.broadcast import HintBar
from ui.editor_kit import TabStrip, TabPage, ConfirmDialog
from ui.theme import BTN_HEIGHT_BACK, FG_MUTED, T_SETTING_VALUE, T_SETTING_TAB

TABS = ("Display", "Audio", "Gameplay", "Camera", "HUD", "Advanced")
# The game's own option group (shared.game_profile.SECTIONS) on each tab
GAME_SECTION = {"Display": "VIDEO", "Audio": "AUDIO", "Gameplay": "GAMEPLAY",
                "Camera": "CAMERA", "HUD": "HUD"}
# Game options that change these menus too, so not tagged IN-GAME: the menu
# music plays at the game's own Music volume.
ALSO_IN_MENUS = {"vol_music"}
RATIO_CHOICES = ["Auto", *SCREEN_RATIOS]
LOG_LEVELS = ["OFF", "DEBUG", "INFO", "WARNING", "ERROR"]


def _note(text):
    label = QLabel(text)
    label.setStyleSheet(f"color: {FG_MUTED}; font-size: {T_SETTING_VALUE}pt; background: transparent;")
    return label


class SettingsScreen(QWidget):
    def __init__(self, back_callback, on_windowed_mode_changed=None, music=None):
        super().__init__()
        self.back_callback = back_callback
        self._on_windowed_mode_changed = on_windowed_mode_changed
        # The frontend's own menu-music player, so the "Music" slider below
        # (the game's own vol_music setting) can apply live to it too — one
        # volume for both rather than a separate frontend-only preference.
        self._music = music
        self._pages = []            # TabPage per tab
        self._rows = []             # per tab: [(row, changed() -> bool)]
        self._init_ui()
        self._profile_revision = game_profile.revision

    def showEvent(self, event):
        # Options changed in-game since the pages were built (game_profile.import_ingame)
        if self._profile_revision != game_profile.revision:
            self._profile_revision = game_profile.revision
            self._build_pages()
        super().showEvent(event)
        QTimer.singleShot(0, self._focus_first_row)

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header, bar = make_page_header("SETTINGS")
        root.addWidget(header)
        root.addWidget(bar)

        content = QWidget()
        content.setMaximumWidth(900)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 20, 20, 24)
        cl.setSpacing(0)

        self.tabs = TabStrip(TABS, font_size=T_SETTING_TAB)
        self.tabs.changed.connect(self._on_tab)
        self.tabs.installEventFilter(self)
        cl.addWidget(self.tabs)

        legend = QHBoxLayout()
        legend.setContentsMargins(2, 12, 0, 0)
        legend.setSpacing(8)
        legend.addWidget(make_in_game_tag())
        legend.addWidget(_note("changes only the game itself, not these menus"))
        legend.addSpacing(18)
        legend.addWidget(make_changed_mark())
        legend.addWidget(_note("changed from its default"))
        legend.addStretch()
        cl.addLayout(legend)

        self.stack = QStackedWidget()
        for _tab in TABS:
            page = TabPage()
            self._pages.append(page)
            self._rows.append([])
            self.stack.addWidget(page)
        cl.addWidget(self.stack, stretch=1)
        self._build_pages()

        cl.addWidget(make_separator())
        cl.addSpacing(10)
        footer = QHBoxLayout()
        footer.setSpacing(12)
        self.back_btn = StyledButton("BACK", "neutral")
        self.back_btn.clicked.connect(self.back_callback)
        self.reset_btn = StyledButton("", "neutral")
        self.reset_btn.clicked.connect(self._ask_reset)
        for button in (self.back_btn, self.reset_btn):
            button.setMinimumHeight(BTN_HEIGHT_BACK)
            button.installEventFilter(self)
            footer.addWidget(button, stretch=1)
        cl.addLayout(footer)

        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(content, 100)      # fills the width up to its maximum
        center.addStretch(1)
        root.addLayout(center, stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([
            ("↕", "select"), ("←→", "change"),
            (HINT_GLYPH[Action.TAB_PREV], "previous tab"), (HINT_GLYPH[Action.TAB_NEXT], "next tab"),
            (HINT_GLYPH[Action.AUX], "reset tab"), ("B", "back"),
        ])
        root.addWidget(self.hintbar)
        self._on_tab(0)

    def _on_tab(self, index):
        self.stack.setCurrentIndex(index)
        self.reset_btn.setText(f"RESET {TABS[index].upper()}")

    # ── pages ──
    def _build_pages(self):
        for index in range(len(TABS)):
            self._fill_page(index)

    def _fill_page(self, index):
        layout = self._pages[index].layout_
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        tab = TABS[index]
        if tab == "Display":
            rows = self._display_rows()
        elif tab == "Advanced":
            rows = self._advanced_rows()
        else:
            # Gameplay > Wind (Standard / Advanced): temporarily hidden, and
            # user_prefs.wind_mode forced to "standard" (see shared/user_prefs.py).
            # To bring it back, add to the Gameplay rows:
            #   CycleRow("Wind", ["Standard", "Advanced"], user_prefs.wind_mode.capitalize(),
            #            lambda label: (setattr(user_prefs, "wind_mode", label.lower()),
            #                           user_prefs.save()))
            rows = self._game_rows(GAME_SECTION[tab])
        for row, _changed in rows:
            row.installEventFilter(self)
            layout.addWidget(row)
        layout.addStretch()
        self._rows[index] = rows
        self._refresh_marks()

    def _refresh_marks(self):
        for rows in self._rows:
            for row, changed in rows:
                row.set_changed(changed())

    def _saved(self, apply):
        """`apply`, then the changed-from-default dots brought up to date."""
        def wrapped(value):
            apply(value)
            self._refresh_marks()
        return wrapped

    def _display_rows(self):
        # Windowed: the normal resizable window. Off (default): unified
        # fullscreen. Applied live — see main.MainWindow.apply_windowed_mode.
        rows = [(ToggleRow("Windowed Mode", user_prefs.game_windowed, self._saved(self._set_windowed)),
                 lambda: user_prefs.game_windowed)]
        rows.append((self._resolution_row(),
                     lambda: game_profile.get_resolution() != native_resolution()))
        # Screen ratio of the match picture, drawn as big as fits at that
        # ratio, black bars around it (screens.ingame). 4:3 = the game as
        # shipped (widescreen patch off); the others turn the widescreen patch
        # on, its 3D view at that ratio (Auto: the window's own, no bars).
        # Written to rugby08patches.ini at the next match start
        # (backend.mod_utils.configure_game_widescreen). Default: the screen's
        # own, closest preset (main.MainWindow._pick_screen_ratio).
        rows.append((ChoiceRow("Screen Ratio", RATIO_CHOICES, user_prefs.screen_ratio_label(),
                               self._saved(user_prefs.set_screen_ratio), in_game=True),
                     lambda: user_prefs.screen_ratio_label() != native_screen_ratio()))
        return rows + self._game_rows("VIDEO")

    def _set_windowed(self, on):
        user_prefs.game_windowed = bool(on)
        user_prefs.save()
        if self._on_windowed_mode_changed:
            self._on_windowed_mode_changed(user_prefs.game_windowed)

    def _resolution_row(self):
        current = game_profile.get_resolution()
        sizes = list(RESOLUTIONS)
        if current not in sizes and current not in UNSAFE_RESOLUTIONS:
            sizes.append(current)
        if current in UNSAFE_RESOLUTIONS:
            current = sizes[0]
        labels = [f"{w}x{h}" for w, h in sizes]

        def apply(label):
            w, h = label.split("x")
            game_profile.set_resolution(int(w), int(h))
            game_profile.save()

        return ChoiceRow("Resolution", labels, f"{current[0]}x{current[1]}", self._saved(apply),
                         in_game=True)

    def _game_rows(self, section):
        """One row per game option of that SECTIONS group, written into the
        game's profile at every launch."""
        def _set(key):
            def apply(value):
                game_profile.set(key, value)
                game_profile.save()
                if key == "vol_music" and self._music is not None:
                    self._music.set_volume(value)
            return self._saved(apply)

        rows = []
        for s in dict(SECTIONS)[section]:
            current = game_profile.get(s.key)
            in_game = s.key not in ALSO_IN_MENUS
            if s.kind == "bool":
                row = ToggleRow(s.label, bool(current), lambda v, a=_set(s.key): a(int(v)),
                                in_game=in_game)
            elif s.kind == "range":
                row = SliderRow(s.label, s.minimum, s.maximum, current, _set(s.key), s.step,
                                in_game=in_game)
            else:
                labels = [label for label, _v in s.choices]
                by_label = dict(s.choices)
                initial = next((l for l, v in s.choices if v == current), labels[0])
                choose = lambda label, a=_set(s.key), m=by_label: a(m[label])
                # two values: one click flips them; more: a dropdown list
                row = (CycleRow if len(labels) <= 2 else ChoiceRow)(
                    s.label, labels, initial, choose, in_game=in_game)
            rows.append((row, lambda k=s.key: game_profile.get(k) != game_profile.default(k)))
        return rows

    def _advanced_rows(self):
        def _set_preview_3d(on):
            user_prefs.preview_3d = bool(on)
            user_prefs.save()

        def _set_log_level(name):
            user_prefs.log_level = name
            user_prefs.save()
            setup_logging(name)     # applies immediately

        current = logging.getLevelName(logging.getLogger(LOG_ROOT).getEffectiveLevel())
        return [
            (ToggleRow("3D Player Preview", user_prefs.preview_3d, self._saved(_set_preview_3d)),
             lambda: not user_prefs.preview_3d),
            (ChoiceRow("Log Level", LOG_LEVELS, user_prefs.log_level or current,
                       self._saved(_set_log_level)),
             lambda: bool(user_prefs.log_level)),
        ]

    # ── reset ──
    def _ask_reset(self):
        index = self.tabs.index()
        tab = TABS[index]
        text = "Every setting on this tab goes back to its default."
        if tab == "Display":
            text += " Resolution and Screen Ratio go back to this screen's own."
        ConfirmDialog(self, f"Reset {tab}?", text,
                      [("CANCEL", "neutral", "cancel"), ("RESET", "primary", "reset")],
                      lambda role: self._on_reset_choice(role, index))

    def _on_reset_choice(self, role, index):
        if role == "reset":
            self.reset_tab(index)
        self.reset_btn.setFocus()

    def reset_tab(self, index):
        """Every setting of tab `index` back to its default."""
        tab = TABS[index]
        if tab == "Advanced":
            user_prefs.preview_3d = True
            user_prefs.log_level = ""
            user_prefs.save()
            setup_logging()
        else:
            game_profile.reset([s.key for s in dict(SECTIONS)[GAME_SECTION[tab]]])
            if tab == "Audio" and self._music is not None:
                self._music.set_volume(game_profile.get("vol_music"))
            if tab == "Display":
                game_profile.set_resolution(*native_resolution())
                game_profile.save()
                user_prefs.set_screen_ratio(native_screen_ratio())
                if user_prefs.game_windowed:
                    self._set_windowed(False)
        self._fill_page(index)

    # ── keyboard / pad ──
    def _focus_first_row(self):
        rows = self._rows[self.tabs.index()]
        if self.isVisible() and rows:
            rows[0][0].setFocus(Qt.TabFocusReason)

    def _move_focus(self, current, delta):
        """Up / Down: tab strip, then the tab's rows, then the footer."""
        index = self.tabs.index()
        rows = [row for row, _changed in self._rows[index]]
        footer = (self.back_btn, self.reset_btn)
        if current in footer:
            target = rows[-1] if delta < 0 and rows else None
        else:
            order = [self.tabs] + rows
            i = order.index(current) + delta if current in order else 0
            target = order[i] if 0 <= i < len(order) else (footer[0] if i >= len(order) else None)
        if target is not None:
            target.setFocus(Qt.TabFocusReason)
            if target in rows:
                self._pages[index].ensureWidgetVisible(target)

    def eventFilter(self, obj, event):
        """Keys on the tab strip, the rows and the footer buttons: whatever
        the row itself doesn't use (see ui.widgets.SettingRow)."""
        if event.type() != QEvent.KeyPress:
            return False
        action = KEYMAP.get(event.key())
        if action in (Action.TAB_PREV, Action.TAB_NEXT):
            on_row = obj not in (self.tabs, self.back_btn, self.reset_btn)
            self.tabs.step(-1 if action == Action.TAB_PREV else 1)
            if on_row:
                self._focus_first_row()
        elif action == Action.BACK:
            self.back_callback()
        elif action == Action.AUX:
            self._ask_reset()
        elif action in (Action.NAV_UP, Action.NAV_DOWN):
            self._move_focus(obj, -1 if action == Action.NAV_UP else 1)
        elif obj in (self.back_btn, self.reset_btn) and action in (Action.NAV_LEFT, Action.NAV_RIGHT):
            (self.reset_btn if obj is self.back_btn else self.back_btn).setFocus(Qt.TabFocusReason)
        elif obj in (self.back_btn, self.reset_btn) and action == Action.CONFIRM:
            obj.click()
        else:
            return False
        return True


SettingsMenu = SettingsScreen
