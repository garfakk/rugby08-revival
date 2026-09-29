"""screens/game_modes.py — Game Modes screen"""
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget, QSizePolicy

from ui import make_page_header, make_separator, StyledButton
from ui.theme import BTN_HEIGHT, BTN_HEIGHT_BACK


class GameModesScreen(QWidget):
    def __init__(self, back_callback):
        super().__init__()
        self.back_callback = back_callback
        self._init_ui()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header, bar = make_page_header("GAME MODES")
        root.addWidget(header)
        root.addWidget(bar)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)

        menu_col = QWidget()
        menu_col.setMaximumWidth(480)
        menu_col.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        ml = QVBoxLayout(menu_col)
        ml.setContentsMargins(20, 0, 20, 0)
        ml.setSpacing(12)

        ml.addStretch(2)

        for text, variant, slot in [
            ("NEW TOURNAMENT",  "primary", None),
            ("LOAD TOURNAMENT", "ghost",   None),
        ]:
            btn = StyledButton(text, variant)
            btn.setMinimumHeight(BTN_HEIGHT)
            if slot:
                btn.clicked.connect(slot)
            ml.addWidget(btn)

        ml.addStretch(1)
        ml.addWidget(make_separator())
        ml.addSpacing(6)

        back = StyledButton("BACK", "neutral")
        back.setMinimumHeight(BTN_HEIGHT_BACK)
        back.clicked.connect(self.back_callback)
        ml.addWidget(back)

        ml.addStretch(2)

        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(menu_col)
        center.addStretch()
        body_layout.addLayout(center, stretch=1)

        root.addWidget(body, stretch=1)


GameModesMenu = GameModesScreen
