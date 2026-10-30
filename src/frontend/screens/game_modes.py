"""screens/game_modes.py — Game Modes hub: challenge mode and tournament."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout

from app.screen_base import Screen
from app.input import Action, KEYMAP
from ui.broadcast import HintBar, MenuTile, page_header
from ui.theme import BG_BASE


class GameModesScreen(Screen):
    def __init__(self, on_back, on_challenge, on_tournament):
        super().__init__(on_back=on_back)
        self._build(on_challenge, on_tournament)

    def _build(self, on_challenge, on_tournament):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Game modes", on_back=self.on_back_cb))

        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(80, 40, 80, 24)

        menu = QVBoxLayout()
        menu.setSpacing(10)
        menu.addStretch(1)
        for title, slot in (
            ("CHALLENGE MODE", on_challenge),
            ("TOURNAMENT", on_tournament),
        ):
            tile = MenuTile(title)
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
        self.hintbar.set_hints([("A", "select"), ("B", "back")])
        root.addWidget(self.hintbar)

    def keyPressEvent(self, event):
        if KEYMAP.get(event.key()) == Action.CONFIRM:
            w = self.focusWidget()
            if isinstance(w, MenuTile):
                w.activate()
                event.accept()
                return
        super().keyPressEvent(event)


GameModesMenu = GameModesScreen
