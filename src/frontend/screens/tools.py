"""
screens/tools.py — Tools hub
=================================
Entry point for the editors that write the mod's own data files, kept apart
from the match flow: everything under here changes what is on disk, and one
of them is reached by accident far too easily from a menu that otherwise
only starts games.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from app.screen_base import Screen
from app.input import Action, KEYMAP
from ui.broadcast import (
    Card, HintBar, MenuTile, page_header, eyebrow_label, display_label,
)
from ui.theme import BG_BASE, ACCENT, FG_SECONDARY, FG_MUTED


class ToolsScreen(Screen):
    def __init__(self, ds, on_back, on_team_editor, on_player_editor, on_import=None):
        super().__init__(on_back=on_back)
        self.ds = ds
        self._build(on_team_editor, on_player_editor, on_import)

    def _build(self, on_team_editor, on_player_editor, on_import=None):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Tools", breadcrumb="mod data",
                                    right=self._data_summary(),
                                    on_back=self.on_back_cb))

        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(80, 40, 80, 24)
        bl.setSpacing(28)

        menu = QVBoxLayout()
        menu.setSpacing(10)
        menu.addStretch(1)
        items = [
            ("TEAM EDITOR", "", on_team_editor, False),
            ("PLAYER EDITOR", "", on_player_editor, False),
            ("IMPORT ROSTER", "", on_import, on_import is None),
            ("TOURNAMENTS", "", None, True),
        ]
        for title, subtitle, slot, soon in items:
            tile = MenuTile(title, subtitle, soon=soon)
            if slot is not None:
                tile.activated.connect(slot)
            self.focus.register(tile)
            menu.addWidget(tile)
        menu.addStretch(2)
        menu_w = QWidget()
        menu_w.setLayout(menu)
        bl.addWidget(menu_w, stretch=3)

        root.addWidget(body, stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "open"), ("B", "back")])
        root.addWidget(self.hintbar)

    def _data_summary(self):
        return (f"{len(self.ds.teams)} teams · {len(self.ds.players)} players")


    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action == Action.CONFIRM:
            w = self.focusWidget()
            if isinstance(w, MenuTile):
                w.activate()
                event.accept()
                return
        super().keyPressEvent(event)
