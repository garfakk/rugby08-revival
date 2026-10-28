"""screens/about.py — About screen"""
import sys
from pathlib import Path

from PyQt5.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QWidget, QScrollArea, QSizePolicy, QTextBrowser,
)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor, QPalette

sys.path.append(str(Path(__file__).parent.parent.parent))
from shared.config import config
from shared.version import APP_VERSION
from app.input import Action, KEYMAP
from app.screen_base import Screen
from ui import make_page_header, make_separator, make_label, StyledButton
from ui.broadcast import HintBar
from ui.theme import AWAY_TINT, BTN_HEIGHT_BACK

SCROLL_STEP = 120       # px per Up/Down


CREDITS_PATH = Path(config.mod_src_directory) / "CREDITS.MD"


class AboutScreen(Screen):
    """Up/Down scroll the credits; A or B goes back."""

    def __init__(self, back_callback):
        super().__init__(on_back=back_callback)
        self.back_callback = back_callback
        self._init_ui()

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action in (Action.NAV_UP, Action.NAV_DOWN):
            bar = self.scroll.verticalScrollBar()
            bar.setValue(bar.value() + (SCROLL_STEP if action == Action.NAV_DOWN else -SCROLL_STEP))
        elif action == Action.CONFIRM:
            self.back_callback()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def _init_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        header, bar = make_page_header("ABOUT")
        root.addWidget(header)
        root.addWidget(bar)

        scroll = self.scroll = QScrollArea()
        scroll.setFocusPolicy(Qt.NoFocus)       # the screen takes the keys
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)

        inner = QWidget()
        inner_layout = QVBoxLayout(inner)
        inner_layout.setContentsMargins(0, 0, 0, 0)

        content = QWidget()
        content.setMaximumWidth(900)
        content.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        cl = QVBoxLayout(content)
        cl.setContentsMargins(20, 40, 20, 30)
        cl.setSpacing(18)

        cl.addWidget(make_label("RUGBY 08 - Revival", role="title", align=Qt.AlignLeft))
        cl.addWidget(make_separator())
        try:
            credits = CREDITS_PATH.read_text(encoding="utf-8").strip()
        except OSError:
            credits = f"Credits file not found: {CREDITS_PATH}"
        credits_view = QTextBrowser()
        credits_view.setMarkdown(f"{credits}")
        credits_html = credits_view.document().toHtml().replace("#0000ff", AWAY_TINT)
        credits_view.setHtml(credits_html)
        credits_view.setOpenExternalLinks(True)
        credits_view.setReadOnly(True)
        credits_view.setFocusPolicy(Qt.NoFocus)  # Up/Down scroll the page (keyPressEvent)
        credits_view.setFrameShape(QTextBrowser.NoFrame)
        credits_view.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        credits_view.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        credits_view.document().setDefaultStyleSheet(
            f"a {{ color: {AWAY_TINT}; }}"
        )
        credits_palette = credits_view.palette()
        credits_palette.setColor(QPalette.Link, QColor(AWAY_TINT))
        credits_palette.setColor(QPalette.LinkVisited, QColor(AWAY_TINT))
        credits_view.setPalette(credits_palette)
        credits_view.setStyleSheet(
            "QTextBrowser { background: transparent; color: #eef3ef; "
            "font-family: 'Barlow'; font-size: 12pt; border: none; }"
        )
        credits_view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        cl.addWidget(credits_view, stretch=1)
        cl.addWidget(make_label(f"Version  {APP_VERSION}", role="muted"))
        cl.addWidget(make_separator())
        cl.addSpacing(8)

        back = StyledButton("BACK", "neutral")
        back.setMinimumHeight(BTN_HEIGHT_BACK)
        back.clicked.connect(self.back_callback)
        cl.addWidget(back)

        center = QHBoxLayout()
        center.addStretch()
        center.addWidget(content, stretch=1)
        center.addStretch()
        inner_layout.addLayout(center, stretch=1)

        scroll.setWidget(inner)
        root.addWidget(scroll, stretch=1)
        hints = HintBar()
        hints.set_hints([("↕", "scroll"), ("B", "back")])
        root.addWidget(hints)


AboutMenu = AboutScreen
