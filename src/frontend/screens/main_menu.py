"""screens/main_menu.py — Main Menu screen (broadcast redesign)."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt5.QtGui import QFont
from PyQt5.QtCore import (
    Qt, QVariantAnimation, QEasingCurve, QSequentialAnimationGroup,
    QParallelAnimationGroup,
)

from shared.config import config
from shared.version import APP_VERSION
from app.screen_base import Screen
from ui.broadcast import display_label, HintBar, MenuTile
from ui.theme import BG_BASE, ACCENT, FG_MUTED


class MainMenuScreen(Screen):
    def __init__(self, mw):
        super().__init__(on_back=None)
        self.mw = mw
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(120, 0, 120, 0)

        hero = QVBoxLayout()
        hero.addStretch(1)
        hero.addWidget(display_label("RUGBY 08", 52, QFont.Bold, track=3.0))
        hero.addSpacing(6)
        hero.addWidget(display_label("REVIVAL", 17, QFont.DemiBold, track=6.0, color=ACCENT))
        hero.addSpacing(4)
        hero.addWidget(display_label(f"v{APP_VERSION} · data {config.data_version}", 11, QFont.Normal, track=2.0,
                                     color=FG_MUTED, upper=False))
        hero.addStretch(2)
        hero_w = QWidget()
        hero_w.setLayout(hero)
        hero_w.setFixedWidth(420)
        bl.addWidget(hero_w)

        bl.addStretch(1)

        menu_col = QVBoxLayout()
        menu_col.setSpacing(10)
        menu_col.addStretch(1)

        items = [
            ("QUICK MATCH", "", self.mw.show_match_setup, False),
            ("GAME MODES", "", self.mw.show_game_modes, True),
            ("TOOLS", "", self.mw.show_tools, False),
            ("SETTINGS", "", self.mw.show_settings, False),
            ("ABOUT", "", self.mw.show_about, False),
            ("EXIT", "", self.mw.close, False),
        ]
        self._tiles = []
        for title_txt, sub_txt, slot, soon in items:
            tile = MenuTile(title_txt, sub_txt, soon=soon)
            tile.activated.connect(slot)
            self.focus.register(tile)
            menu_col.addWidget(tile)
            self._tiles.append(tile)
        menu_col.addStretch(2)
        menu_w = QWidget()
        menu_w.setLayout(menu_col)
        menu_w.setFixedWidth(560)
        bl.addWidget(menu_w)

        root.addWidget(body, stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "select"), ("B", "exit")])
        root.addWidget(self.hintbar)

    # ── entrance ─────────────────────────────────────────────────────────
    ENTRANCE_MS = 520      # per-tile slide+fade
    ENTRANCE_STAGGER = 95  # gap between consecutive tiles starting

    def play_entrance(self):
        """Slide + fade the menu tiles in one after another, top to bottom.
        Called when the startup intro lifts (see MainWindow._show_intro); the
        tiles sit fully painted otherwise, so any other route to this screen
        is unaffected."""
        group = QParallelAnimationGroup(self)
        for i, tile in enumerate(self._tiles):
            tile.set_entrance(0.0)
            anim = QVariantAnimation(self)
            anim.setDuration(self.ENTRANCE_MS)
            anim.setStartValue(0.0)
            anim.setEndValue(1.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            anim.valueChanged.connect(tile.set_entrance)
            seq = QSequentialAnimationGroup(self)
            seq.addPause(i * self.ENTRANCE_STAGGER)
            seq.addAnimation(anim)
            group.addAnimation(seq)
        # Kept on self: a QAbstractAnimation whose only reference is local
        # is garbage-collected mid-flight, leaving the tiles parked at
        # whatever opacity they had reached.
        self._entrance_group = group
        group.start()

    def keyPressEvent(self, event):
        w = self.focusWidget()
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space) and isinstance(w, MenuTile):
            w.activate()
            event.accept()
            return
        super().keyPressEvent(event)


MainMenu = MainMenuScreen
