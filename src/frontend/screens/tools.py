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
from shared.config import config
from shared.user_prefs import user_prefs
from ui.broadcast import (
    Card, HintBar, MenuTile, page_header, eyebrow_label, display_label, scroll_wrap,
)
from ui.theme import BG_BASE, ACCENT, FG_SECONDARY, FG_MUTED


# Tools offered in expert mode only
EXPERT_TOOLS = ("TOURNAMENT EDITOR", "STADIUM EDITOR", "REFEREE EDITOR")


class ToolsScreen(Screen):
    def __init__(self, ds, on_back, on_team_editor, on_player_editor, on_import=None,
                 on_challenge_editor=None, on_edits=None, on_updates=None,
                 on_tournament_editor=None, on_stadium_editor=None, on_referee_editor=None):
        super().__init__(on_back=on_back)
        self.ds = ds
        self._build(on_team_editor, on_player_editor, on_import, on_challenge_editor, on_edits,
                    on_updates, on_tournament_editor, on_stadium_editor, on_referee_editor)

    def _build(self, on_team_editor, on_player_editor, on_import=None, on_challenge_editor=None,
               on_edits=None, on_updates=None, on_tournament_editor=None, on_stadium_editor=None,
               on_referee_editor=None):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Tools", right=self._data_summary(),
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
            ("MY EDITS", "", on_edits, on_edits is None),
            ("UPDATES", "", on_updates, on_updates is None),
        ]
        if on_tournament_editor is not None:
            items.insert(2, ("TOURNAMENT EDITOR", "", on_tournament_editor, False))
        if on_stadium_editor is not None:
            items.insert(3, ("STADIUM EDITOR", "", on_stadium_editor, False))
        if on_referee_editor is not None:
            items.insert(4, ("REFEREE EDITOR", "", on_referee_editor, False))
        if config.developper_mode:
            items.extend([
                ("IMPORT ROSTER", "", on_import, on_import is None),
                ("CHALLENGE EDITOR", "", on_challenge_editor, on_challenge_editor is None),
            ])
        self.edits_tile = None
        self.expert_tiles = []       # shown in expert mode only (on_show)
        for title, subtitle, slot, soon in items:
            tile = MenuTile(title, subtitle, soon=soon)
            if title == "MY EDITS":
                self.edits_tile = tile
            if title in EXPERT_TOOLS:
                self.expert_tiles.append(tile)
            if slot is not None:
                tile.activated.connect(slot)
            self.focus.register(tile)
            menu.addWidget(tile)
        menu.addStretch(2)
        menu_w = QWidget()
        menu_w.setLayout(menu)
        bl.addWidget(menu_w, stretch=3)

        self._apply_expert_mode()
        root.addWidget(scroll_wrap(body), stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "open"), ("B", "back")])
        root.addWidget(self.hintbar)

    def on_show(self):
        self._apply_expert_mode()
        super().on_show()
        self._update_edits_tile()

    def _apply_expert_mode(self):
        """Hidden tiles are skipped by keyboard/pad navigation."""
        for tile in self.expert_tiles:
            tile.setVisible(user_prefs.expert_mode)

    def _update_edits_tile(self):
        """MY EDITS says how many records are edited and how many wait for a choice."""
        edits = getattr(self.ds, "edits", None)
        if self.edits_tile is None or edits is None:
            return
        n, conflicts = edits.count(), len(edits.conflicts)
        text = f"{n} record{'s' if n != 1 else ''} edited" if n else ""
        if conflicts:
            text += f" · {conflicts} to settle"
        if n and not edits.enabled:
            text += " · turned off"
        self.edits_tile.subtitle = text
        self.edits_tile.update()

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
