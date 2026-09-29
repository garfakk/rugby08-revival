"""
screens/post_match.py — Full-time screen
=============================================
Reads what R08_handler.read_match_result() parses out of the game's memory:
tries, conversions, penalties, drop goals, cards, tackles, scrums and
lineouts. The score is derived from the scoring events, because the game
never populates a team score field.

Substitutions are parsed but the parser returns nothing usable, so they are
deliberately not shown rather than shown wrong.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtGui import QPainter, QColor, QFont, QPixmap
from PyQt5.QtCore import Qt, QRectF

from app.screen_base import Screen
from ui import StyledButton
from ui.broadcast import (
    Card, HintBar, page_header, eyebrow_label, display_label, label_css, tracked_font,
)
from ui.theme import (
    BG_BASE, ACCENT, HOME_TINT, AWAY_TINT,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED, FONT_DISPLAY, BTN_HEIGHT,
)

STAT_ROWS = [
    ("TRIES", lambda s, st: s.get("tries", 0)),
    ("CONVERSIONS", lambda s, st: s.get("conversions", 0)),
    ("PENALTIES", lambda s, st: s.get("penalties", 0)),
    ("DROP GOALS", lambda s, st: s.get("drop_goals", 0)),
    ("TACKLES", lambda s, st: s.get("tackles", 0)),
    ("SCRUMS WON", lambda s, st: st.get("scrums_won_own", 0)),
    ("LINEOUTS WON", lambda s, st: st.get("lineouts_won_own", 0)),
    ("YELLOW CARDS", lambda s, st: s.get("yellow_cards", 0)),
    ("RED CARDS", lambda s, st: s.get("red_cards", 0)),
]


class StatComparison(QWidget):
    """Home value | label | away value, with a split bar showing the share."""

    def __init__(self, rows, parent=None):
        super().__init__(parent)
        self.rows = rows          # [(label, home_value, away_value)]
        self.setMinimumHeight(len(rows) * 42)

    def set_rows(self, rows):
        self.rows = rows
        self.setMinimumHeight(len(rows) * 42)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        mid = self.width() / 2
        y = 0
        for label, hv, av in self.rows:
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.DemiBold, track=2.0))
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(mid - 130, y, 260, 20), Qt.AlignCenter, label)

            p.setFont(tracked_font(FONT_DISPLAY, 16, QFont.Bold, track=0.4))
            p.setPen(QColor(FG_PRIMARY))
            p.drawText(QRectF(mid - 260, y, 110, 20), Qt.AlignRight | Qt.AlignVCenter, str(hv))
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(mid + 150, y, 110, 20), Qt.AlignLeft | Qt.AlignVCenter, str(av))

            total = max(hv + av, 1)
            bar_w = 220
            p.fillRect(QRectF(mid - 20 - bar_w * hv / total, y + 24, bar_w * hv / total, 5),
                       QColor(HOME_TINT))
            p.fillRect(QRectF(mid + 20, y + 24, bar_w * av / total, 5), QColor(AWAY_TINT))
            y += 42


class PostMatchScreen(Screen):
    def __init__(self, on_rematch, on_match_setup, on_main_menu):
        super().__init__(on_back=on_main_menu)
        self.on_rematch = on_rematch
        self.on_match_setup = on_match_setup
        self.on_main_menu = on_main_menu
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header_holder = QWidget()
        hh = QVBoxLayout(self.header_holder)
        hh.setContentsMargins(0, 0, 0, 0)
        self.header = page_header("Full time", breadcrumb="friendly", on_back=self.on_main_menu)
        hh.addWidget(self.header)
        root.addWidget(self.header_holder)

        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(80, 24, 80, 16)
        bl.setSpacing(16)

        # ── scoreline ────────────────────────────────────────────────────
        score_row = QHBoxLayout()
        score_row.setSpacing(24)

        self.home_crest = QLabel(); self.home_crest.setFixedSize(110, 110)
        self.home_crest.setAlignment(Qt.AlignCenter)
        self.home_crest.setStyleSheet("background: transparent;")
        self.away_crest = QLabel(); self.away_crest.setFixedSize(110, 110)
        self.away_crest.setAlignment(Qt.AlignCenter)
        self.away_crest.setStyleSheet("background: transparent;")

        self.home_name = display_label("—", 26, QFont.Bold, track=1.2)
        self.away_name = display_label("—", 26, QFont.Bold, track=1.2)
        self.home_score = display_label("0", 66, QFont.Bold, track=1.0)
        self.away_score = display_label("0", 66, QFont.Bold, track=1.0, color=FG_SECONDARY)

        score_row.addStretch(1)
        score_row.addWidget(self.home_crest, alignment=Qt.AlignVCenter)
        score_row.addWidget(self.home_name, alignment=Qt.AlignVCenter)
        score_row.addWidget(self.home_score, alignment=Qt.AlignVCenter)
        dash = display_label("—", 30, QFont.Bold, track=0, color=FG_MUTED)
        score_row.addWidget(dash, alignment=Qt.AlignVCenter)
        score_row.addWidget(self.away_score, alignment=Qt.AlignVCenter)
        score_row.addWidget(self.away_name, alignment=Qt.AlignVCenter)
        score_row.addWidget(self.away_crest, alignment=Qt.AlignVCenter)
        score_row.addStretch(1)
        bl.addLayout(score_row)

        # Full time / interrupted banner
        self.status_label = eyebrow_label("", color=FG_MUTED, size=20)
        self.status_label.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.status_label)

        # ── statistics ───────────────────────────────────────────────────
        stats_card = Card()
        sv = QVBoxLayout(stats_card)
        sv.setContentsMargins(24, 16, 24, 16)
        sv.addWidget(eyebrow_label("match statistics", color=ACCENT, size=13))
        self.stats = StatComparison([])
        sv.addWidget(self.stats)
        bl.addWidget(stats_card, stretch=1)

        # ── scorers ──────────────────────────────────────────────────────
        scorers = QHBoxLayout()
        scorers.setSpacing(20)
        self.home_scorers = self._scorer_card("scorers · home", HOME_TINT)
        self.away_scorers = self._scorer_card("scorers · away", AWAY_TINT)
        scorers.addWidget(self.home_scorers[0], stretch=1)
        scorers.addWidget(self.away_scorers[0], stretch=1)
        bl.addLayout(scorers, stretch=1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        for text, variant, slot in (("RESTART", "neutral", lambda: self.on_rematch()),
                                      ("MAIN MENU", "primary", lambda: self.on_main_menu())):
            btn = StyledButton(text, variant)
            btn.setMinimumHeight(BTN_HEIGHT)
            btn.setMinimumWidth(180)
            btn.clicked.connect(slot)
            self.focus.register(btn)
            actions.addWidget(btn)
        bl.addLayout(actions)

        root.addWidget(body, stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "select"), ("B", "main menu")])
        root.addWidget(self.hintbar)

    def _scorer_card(self, title, tint):
        card = Card(stripe=tint)
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 14, 22, 14)
        v.setSpacing(6)
        v.addWidget(eyebrow_label(title, color=tint, size=12))
        holder = QVBoxLayout()
        holder.setSpacing(4)
        v.addLayout(holder)
        v.addStretch(1)
        return card, holder

    # ── data ─────────────────────────────────────────────────────────────
    def set_result(self, match_data, result):
        """`match_data` is what was sent to the backend (team names, crests),
        `result` is what R08_handler.read_match_result() returned. A None
        result means the game exited without one — say so instead of showing
        a fabricated 0-0."""
        home = (match_data or {}).get("team_A", {})
        away = (match_data or {}).get("team_B", {})
        self.home_name.setText(home.get("name", "HOME").upper())
        self.away_name.setText(away.get("name", "AWAY").upper())
        self._set_crest(self.home_crest, home.get("logo"))
        self._set_crest(self.away_crest, away.get("logo"))

        self._set_status(result)

        if not result:
            self.home_score.setText("–")
            self.away_score.setText("–")
            self.stats.set_rows([("NO RESULT READ FROM THE GAME", 0, 0)])
            self._fill_scorers(self.home_scorers[1], [])
            self._fill_scorers(self.away_scorers[1], [])
            return

        hs = result.get("team_A", {}).get("score", {}) or {}
        as_ = result.get("team_B", {}).get("score", {}) or {}
        hst = result.get("team_A", {}).get("stats", {}) or {}
        ast = result.get("team_B", {}).get("stats", {}) or {}
        self.home_score.setText(str(hs.get("points", 0)))
        self.away_score.setText(str(as_.get("points", 0)))
        self.stats.set_rows([(label, fn(hs, hst), fn(as_, ast)) for label, fn in STAT_ROWS])

        self._fill_scorers(self.home_scorers[1], result.get("team_A", {}).get("players", []))
        self._fill_scorers(self.away_scorers[1], result.get("team_B", {}).get("players", []))

    def _set_status(self, result):
        """Banner under the scoreline: blank at full time, a warning when the
        match was left early (with the minute when the game's clock was readable)."""
        if result and result.get("finished") is False:
            minute = result.get("minute")
            text = f"MATCH INTERRUPTED AT {minute} MIN" if minute else "MATCH INTERRUPTED"
            self.status_label.setText(text)
            self.status_label.setStyleSheet(label_css(20, QFont.DemiBold, ACCENT, FONT_DISPLAY))
        else:
            self.status_label.setText("")

    def _set_crest(self, label, rel_path):
        from shared.config import config
        import os
        label.clear()
        if not rel_path:
            return
        path = os.path.join(config.mod_data_directory, rel_path)
        if os.path.exists(path):
            pix = QPixmap(path)
            if not pix.isNull():
                label.setPixmap(pix.scaled(100, 100, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _fill_scorers(self, holder, players):
        while holder.count():
            item = holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        scorers = []
        for p in players:
            events = []
            if p.get("tries"):
                events.append(f"TRY ×{p['tries']}" if p["tries"] > 1 else "TRY")
            if p.get("conversions_scored"):
                events.append(f"CON ×{p['conversions_scored']}")
            if p.get("penalties_scored"):
                events.append(f"PEN ×{p['penalties_scored']}")
            if p.get("drop_goals"):
                events.append(f"DROP ×{p['drop_goals']}")
            if events:
                scorers.append((p.get("name", "—"), " · ".join(events)))

        if not scorers:
            holder.addWidget(display_label("No scorers", 12, QFont.DemiBold,
                                            track=1.2, color=FG_MUTED))
            return
        for name, events in scorers[:8]:
            row = QHBoxLayout()
            row.addWidget(display_label(name, 15, QFont.Bold, track=0.4))
            row.addStretch(1)
            row.addWidget(display_label(events, 11, QFont.DemiBold, track=1.0,
                                        color=FG_SECONDARY))
            wrapper = QWidget()
            wrapper.setStyleSheet("background: transparent;")
            wrapper.setLayout(row)
            holder.addWidget(wrapper)
