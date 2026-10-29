"""screens/settings.py — Settings screen"""
import sys
import re
from pathlib import Path

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy, QStackedWidget,
    QLabel, QPushButton, QComboBox, QLineEdit,
)
from PyQt5.QtGui import QFont

sys.path.append(str(Path(__file__).parent.parent.parent))
from shared.user_prefs import user_prefs
from shared.game_profile import game_profile, SECTIONS, RESOLUTIONS, UNSAFE_RESOLUTIONS

import logging

from shared.log import ROOT as LOG_ROOT, setup_logging
from ui import (make_page_header, make_separator, make_label, StyledButton, ToggleRow,
                ChoiceRow, CycleRow, SliderRow)
from ui.editor_kit import TabStrip, TabPage
from ui.theme import BTN_HEIGHT_BACK


class SettingsScreen(QWidget):
    def __init__(self, back_callback, on_windowed_mode_changed=None, music=None):
        super().__init__()
        self.back_callback = back_callback
        self._on_windowed_mode_changed = on_windowed_mode_changed
        # The frontend's own menu-music player, so the "Music" slider below
        # (the game's own vol_music setting) can apply live to it too — one
        # volume for both rather than a separate frontend-only preference.
        self._music = music
        self._game_pages = []       # (TabPage, settings) — rebuilt by "reset"
        self._init_ui()
        self._profile_revision = game_profile.revision

    def showEvent(self, event):
        # Options changed in-game since the pages were built (game_profile.import_ingame)
        if self._profile_revision != game_profile.revision:
            self._profile_revision = game_profile.revision
            self._build_game_pages()
            self._enlarge_text()
        super().showEvent(event)

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

        # One tab for the mod itself, then one per group of game options
        titles = ["General"] + [title.title() for title, _settings in SECTIONS]
        self.tabs = TabStrip(titles)
        self.tabs.changed.connect(self._on_tab)
        cl.addWidget(self.tabs)

        self.stack = QStackedWidget()
        general = TabPage()
        self._build_general_page(general.layout_)
        self.stack.addWidget(general)
        for _title, settings in SECTIONS:
            page = TabPage()
            self._game_pages.append((page, settings))
            self.stack.addWidget(page)
        cl.addWidget(self.stack, stretch=1)
        self._build_game_pages()

        cl.addWidget(make_separator())
        cl.addSpacing(10)
        footer = QHBoxLayout()
        back = StyledButton("BACK", "neutral")
        back.setMinimumHeight(BTN_HEIGHT_BACK)
        back.clicked.connect(self.back_callback)
        footer.addWidget(back, stretch=1)
        self.reset_btn = StyledButton("RESET GAME SETTINGS", "neutral")
        self.reset_btn.setMinimumHeight(BTN_HEIGHT_BACK)
        self.reset_btn.clicked.connect(self._reset_game_settings)
        footer.addWidget(self.reset_btn, stretch=1)
        cl.addLayout(footer)
        self._on_tab(0)

        center = QHBoxLayout()
        center.addStretch(1)
        center.addWidget(content, 100)      # fills the width up to its maximum
        center.addStretch(1)
        root.addLayout(center, stretch=1)
        self._enlarge_text()

    def _on_tab(self, index):
        self.stack.setCurrentIndex(index)
        self.reset_btn.setVisible(index > 0)    # only the game's own options reset

    def _enlarge_text(self):
        """Make settings labels and values easier to read without changing
        shared row-widget typography everywhere else in the app."""
        text_widgets = []
        for widget_type in (QLabel, QPushButton, QComboBox, QLineEdit):
            text_widgets.extend(self.findChildren(widget_type))
        for widget in text_widgets:
            if widget.property("settingsFontScaled"):
                continue
            widget.setProperty("settingsFontScaled", True)
            font = QFont(widget.font())
            font.setPointSize(max(1, font.pointSize() + 2))
            widget.setFont(font)
            stylesheet = widget.styleSheet()
            if stylesheet:
                widget.setStyleSheet(re.sub(
                    r"(font-size\s*:\s*)(\d+(?:\.\d+)?)pt",
                    lambda match: f"{match.group(1)}{float(match.group(2)) + 2:g}pt",
                    stylesheet,
                ))

        # TabStrip paints its text instead of using child labels.
        if not self.tabs.property("settingsFontScaled"):
            self.tabs.setProperty("settingsFontScaled", True)
            tab_font = QFont(self.tabs._font)
            tab_font.setPointSize(tab_font.pointSize() + 2)
            self.tabs._font = tab_font
            self.tabs.setFixedHeight(48)
            self.tabs.update()

    # ── General: the mod itself ──
    def _build_general_page(self, cl):
        cl.addWidget(make_label("DISPLAY", role="muted"))

        # Windowed: the normal resizable window. Off (default): unified
        # fullscreen. Applied live — see main.MainWindow.apply_windowed_mode.
        def _set_windowed(on):
            user_prefs.game_windowed = bool(on)
            user_prefs.save()
            if self._on_windowed_mode_changed:
                self._on_windowed_mode_changed(user_prefs.game_windowed)

        cl.addWidget(ToggleRow("Windowed Mode", user_prefs.game_windowed, _set_windowed))

        def _set_preview_3d(on):
            user_prefs.preview_3d = bool(on)
            user_prefs.save()

        cl.addWidget(ToggleRow("3D Player Preview", user_prefs.preview_3d, _set_preview_3d))

        # Once a day at startup, ask GitHub for a new program or data release
        # (app/updater); Tools > Updates can always check by hand.
        def _set_check_updates(on):
            user_prefs.check_updates = bool(on)
            user_prefs.save()

        cl.addWidget(ToggleRow("Check For Updates", user_prefs.check_updates, _set_check_updates))

        # Screen ratio of the match picture, drawn as big as fits at that
        # ratio, black bars around it (screens.ingame). 4:3 = the game as
        # shipped (widescreen patch off); the others turn the widescreen patch
        # on, its 3D view at that ratio (Auto: the window's own, no bars).
        # Written to rugby08patches.ini at the next match start
        # (backend.mod_utils.configure_game_widescreen).
        ratio_choices = ["Auto", "4:3", "16:10", "16:9", "21:9"]

        def _set_ratio(label):
            user_prefs.widescreen = label != "4:3"
            user_prefs.widescreen_aspect = label.lower()
            user_prefs.save()

        aspect = user_prefs.widescreen_aspect.strip().lower()
        selected_ratio = ("4:3" if not user_prefs.widescreen or aspect == "4:3" else
                          next((c for c in ratio_choices if c.lower() == aspect), "Auto"))
        cl.addWidget(ChoiceRow("Screen Ratio", ratio_choices, selected_ratio, _set_ratio))

        # How Quick Match picks teams (app/team_browse.py): the classic
        # season > category > team, or one of the team-first alternatives.
        # Takes effect the next time Quick Match opens.
        from app.team_browse import STYLES, style_label
        labels = [label for _id, label in STYLES]

        def _set_picker(label):
            user_prefs.match_picker = next(i for i, l in STYLES if l == label)
            user_prefs.save()

        cl.addWidget(ChoiceRow("Quick Match Picker", labels, style_label(user_prefs.match_picker),
                               _set_picker))
        cl.addSpacing(16)

        # MATCH > Wind (Standard / Advanced): temporarily hidden, and
        # user_prefs.wind_mode forced to "standard" (see shared/user_prefs.py).
        # To bring it back:
        #   def _set_wind_mode(label):
        #       user_prefs.wind_mode = label.lower(); user_prefs.save()
        #   cl.addWidget(make_label("MATCH", role="muted"))
        #   cl.addWidget(CycleRow("Wind", ["Standard", "Advanced"],
        #                         user_prefs.wind_mode.capitalize(), _set_wind_mode))
        #   cl.addSpacing(16)

        cl.addWidget(make_label("DEBUG", role="muted"))

        level_names = ["OFF", "DEBUG", "INFO", "WARNING", "ERROR"]

        def _set_log_level(name):
            user_prefs.log_level = name
            user_prefs.save()
            setup_logging(name)     # applies immediately

        current = logging.getLevelName(logging.getLogger(LOG_ROOT).getEffectiveLevel())
        selected_level = user_prefs.log_level or current
        cl.addWidget(ChoiceRow("Log Level", level_names, selected_level, _set_log_level))


        cl.addStretch()

    # ── The game's own options, written into its profile at every launch ──
    def _build_game_pages(self):
        """One row per game option (see shared.game_profile.SECTIONS), plus the
        resolution. Saved as soon as a value changes."""
        def _set(key):
            def apply(value):
                game_profile.set(key, value)
                game_profile.save()
                if key == "vol_music" and self._music is not None:
                    self._music.set_volume(value)
            return apply

        for page, settings in self._game_pages:
            layout = page.layout_
            while layout.count():
                item = layout.takeAt(0)
                if item.widget():
                    item.widget().deleteLater()
            layout.addWidget(make_label("Applied to the game at every launch.", role="muted"))
            for s in settings:
                current = game_profile.get(s.key)
                if s.kind == "bool":
                    row = ToggleRow(s.label, bool(current), lambda v, k=s.key: _set(k)(int(v)))
                elif s.kind == "range":
                    row = SliderRow(s.label, s.minimum, s.maximum, current, _set(s.key), s.step)
                else:
                    labels = [label for label, _v in s.choices]
                    by_label = dict(s.choices)
                    initial = next((l for l, v in s.choices if v == current), labels[0])
                    choose = lambda label, k=s.key, m=by_label: _set(k)(m[label])
                    # two values: one click flips them; more: a dropdown list
                    row = (CycleRow if len(labels) <= 2 else ChoiceRow)(s.label, labels, initial, choose)
                layout.addWidget(row)
                if s.key == "gamma":
                    layout.addWidget(self._resolution_row())
            layout.addStretch()

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

        return ChoiceRow("Resolution", labels, f"{current[0]}x{current[1]}", apply)

    def _reset_game_settings(self):
        game_profile.reset()
        if self._music is not None:
            self._music.set_volume(game_profile.get("vol_music"))
        self._build_game_pages()
        self._enlarge_text()


SettingsMenu = SettingsScreen
