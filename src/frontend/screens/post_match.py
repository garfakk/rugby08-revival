"""
screens/post_match.py — Full-time screen
=============================================
Reads what R08_handler.read_match_result() parses out of the game's memory:
tries, conversions, penalties, drop goals, cards, tackles, scrums and
lineouts. The score is derived from the scoring events, because the game
never populates a team score field.

Substitutions are parsed but the parser returns nothing usable, so they are
deliberately not shown rather than shown wrong.

MatchReport shows the scoreline, the statistics (the bars growing out row by
row) and the scorers; PostMatchScreen is the quick match's full time.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PyQt5.QtGui import QFont, QPixmap
from PyQt5.QtCore import Qt

from app.screen_base import Screen
from ui import StyledButton
from ui.broadcast import (
    Card, HintBar, page_header, eyebrow_label, display_label, label_css,
)
from ui.stat_compare import StatComparison
from ui.theme import (
    BG_BASE, ACCENT, HOME_TINT, AWAY_TINT, FG_SECONDARY, FG_MUTED, FONT_DISPLAY, BTN_HEIGHT,
)

STAT_ROWS = [
    ("TRIES", lambda s, st: s.get("tries", 0)),
    ("CONVERSIONS", lambda s, st: s.get("conversions", 0)),
    ("PENALTIES", lambda s, st: s.get("penalties", 0)),
    ("DROP GOALS", lambda s, st: s.get("drop_goals", 0)),
    ("TACKLES", lambda s, st: s.get("tackles", 0)),
    ("SCRUMS WON", lambda s, st: st.get("scrums_won", 0)),
    ("LINEOUTS WON", lambda s, st: st.get("lineouts_won", 0)),
    ("YELLOW CARDS", lambda s, st: s.get("yellow_cards", 0)),
    ("RED CARDS", lambda s, st: s.get("red_cards", 0)),
]


def _times(result, team):
    """{(roster id, score type): [minute, ...]} of the scores the game's clock
    timed (none when the clock was unreadable)."""
    out = {}
    for ev in (result or {}).get("events") or []:
        if ev.get("team") == team:
            out.setdefault((ev.get("id"), ev.get("type")), []).append(int(float(ev.get("clock") or 0) // 60) + 1)
    return {k: sorted(v) for k, v in out.items()}


class MatchReport(QWidget):
    """The result of a game as the game reported it: the scoreline (unless
    `scoreline=False`), an interrupted-match banner, the statistics and each
    side's scorers. The full-time screen, the challenge result and the
    tournament's full-time recap all show it."""

    def __init__(self, scoreline=True, parent=None):
        super().__init__(parent)
        self.setObjectName("matchReport")
        self.setStyleSheet("QWidget#matchReport { background: transparent; }")
        bl = QVBoxLayout(self)
        bl.setContentsMargins(0, 0, 0, 0)
        bl.setSpacing(16)

        # ── scoreline ────────────────────────────────────────────────────
        self.scoreline = QWidget()
        self.scoreline.setStyleSheet("background: transparent;")
        score_row = QHBoxLayout(self.scoreline)
        score_row.setContentsMargins(0, 0, 0, 0)
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
        bl.addWidget(self.scoreline)
        self.scoreline.setVisible(scoreline)

        # Full time / interrupted banner
        self.status_label = eyebrow_label("", color=FG_MUTED, size=20)
        self.status_label.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.status_label)

        # ── statistics ───────────────────────────────────────────────────
        self.stats_card = Card()
        sv = QVBoxLayout(self.stats_card)
        sv.setContentsMargins(24, 16, 24, 16)
        sv.addWidget(eyebrow_label("match statistics", color=ACCENT, size=13))
        self.stats = StatComparison([])
        sv.addWidget(self.stats)
        bl.addWidget(self.stats_card, stretch=1)

        # ── scorers ──────────────────────────────────────────────────────
        scorers = QHBoxLayout()
        scorers.setSpacing(20)
        self.home_scorers = self._scorer_card("scorers · home", HOME_TINT)
        self.away_scorers = self._scorer_card("scorers · away", AWAY_TINT)
        scorers.addWidget(self.home_scorers[0], stretch=1)
        scorers.addWidget(self.away_scorers[0], stretch=1)
        bl.addLayout(scorers, stretch=1)

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
        self._set_crest(self.home_crest, home.get("logo_frontend") or home.get("logo"))
        self._set_crest(self.away_crest, away.get("logo_frontend") or away.get("logo"))

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
        self.stats.reveal()

        self._fill_scorers(self.home_scorers[1], result.get("team_A", {}).get("players", []),
                           _times(result, "team_A"))
        self._fill_scorers(self.away_scorers[1], result.get("team_B", {}).get("players", []),
                           _times(result, "team_B"))

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
        self.status_label.setVisible(bool(self.status_label.text()))

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

    def _fill_scorers(self, holder, players, times=None):
        times = times or {}
        while holder.count():
            item = holder.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        scorers = []
        for p in players:
            events = []
            for field, label, kind in (("tries", "TRY", "try"), ("conversions_scored", "CON", "conversion"),
                                       ("penalties_scored", "PEN", "penalty"), ("drop_goals", "DROP", "drop_goal")):
                n = p.get(field)
                if not n:
                    continue
                mins = times.get((p.get("id"), kind), [])
                if len(mins) == n:
                    events.append(f"{label} " + " ".join(f"{m}'" for m in mins))
                else:
                    events.append(f"{label} ×{n}" if n > 1 else label)
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


class PostMatchScreen(Screen):
    """Full time of a quick match: the match report and MAIN MENU."""

    def __init__(self, on_main_menu):
        super().__init__(on_back=on_main_menu)
        self.on_main_menu = on_main_menu
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Full time"))

        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(80, 24, 80, 16)
        bl.setSpacing(16)
        self.report = MatchReport()
        bl.addWidget(self.report, stretch=1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self.menu_btn = StyledButton("MAIN MENU", "primary")
        self.menu_btn.setMinimumHeight(BTN_HEIGHT)
        self.menu_btn.setMinimumWidth(180)
        self.menu_btn.clicked.connect(lambda: self.on_main_menu())
        self.focus.register(self.menu_btn)
        actions.addWidget(self.menu_btn)
        bl.addLayout(actions)
        root.addWidget(body, stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "main menu")])
        root.addWidget(self.hintbar)

    @property
    def stats(self):
        return self.report.stats

    @property
    def stats_card(self):
        return self.report.stats_card

    def on_show(self):
        super().on_show()
        self.menu_btn.setFocus()

    def set_result(self, match_data, result):
        self.report.set_result(match_data, result)
