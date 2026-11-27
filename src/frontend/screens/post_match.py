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
    Card, HintBar, page_header, eyebrow_label, display_label, label_css, scroll_wrap,
)
from ui.stat_compare import StatComparison
from ui.theme import (
    BG_BASE, ACCENT, HOME_TINT, AWAY_TINT, FG_SECONDARY, FG_MUTED, FONT_DISPLAY, BTN_HEIGHT,
)

CREST = 80            # team crest box in the scoreline
NAME_W = 340          # team names longer than this are cut short
STAT_ROW_H = 30       # stat_compare paints a row's bar 24-29 px down
STATS_W = 540         # the statistics' painted width (numbers either side of the bars)

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
        bl.setSpacing(12)

        # ── scoreline ────────────────────────────────────────────────────
        self.scoreline = QWidget()
        self.scoreline.setStyleSheet("background: transparent;")
        score_row = QHBoxLayout(self.scoreline)
        score_row.setContentsMargins(0, 0, 0, 0)
        score_row.setSpacing(24)

        self.home_crest = QLabel(); self.home_crest.setFixedSize(CREST, CREST)
        self.home_crest.setAlignment(Qt.AlignCenter)
        self.home_crest.setStyleSheet("background: transparent;")
        self.away_crest = QLabel(); self.away_crest.setFixedSize(CREST, CREST)
        self.away_crest.setAlignment(Qt.AlignCenter)
        self.away_crest.setStyleSheet("background: transparent;")

        self.home_name = display_label("—", 26, QFont.Bold, track=1.2)
        self.away_name = display_label("—", 26, QFont.Bold, track=1.2)
        for name in (self.home_name, self.away_name):    # long names cut short (_set_name)
            name.setMaximumWidth(NAME_W)
        self.home_score = display_label("0", 60, QFont.Bold, track=1.0)
        self.away_score = display_label("0", 60, QFont.Bold, track=1.0, color=FG_SECONDARY)

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

        # ── statistics | scorers, side by side ───────────────────────────
        # (stacked, they are too tall for a 1080p laptop at 150 %, about
        # 1280x690 of layout)
        blocks = QHBoxLayout()
        blocks.setSpacing(16)

        self.stats_card = Card()
        sv = QVBoxLayout(self.stats_card)
        sv.setContentsMargins(24, 12, 24, 12)
        sv.setSpacing(6)
        sv.addWidget(eyebrow_label("match statistics", color=ACCENT, size=13))
        self.stats = StatComparison([], row_h=STAT_ROW_H, grow=True)
        self.stats.setMinimumWidth(STATS_W)
        sv.addWidget(self.stats, stretch=1)
        blocks.addWidget(self.stats_card, stretch=1)

        # one card, home and away side by side like the score above
        self.scorers_card = Card()
        cv = QVBoxLayout(self.scorers_card)
        cv.setContentsMargins(24, 12, 24, 12)
        cv.setSpacing(6)
        cv.addWidget(eyebrow_label("scorers", color=ACCENT, size=13))
        inner = QWidget()
        inner.setStyleSheet("background: transparent;")
        cols = QHBoxLayout(inner)
        cols.setContentsMargins(0, 0, 0, 0)
        cols.setSpacing(24)
        self.home_scorers = self._scorer_column(cols, HOME_TINT, "home")
        self.away_scorers = self._scorer_column(cols, AWAY_TINT, "away")
        self._scorers_inner = inner
        self._scorers_scroll = scroll_wrap(inner, horizontal=False)        # a long list scrolls
        cv.addWidget(self._scorers_scroll, stretch=1)
        # nobody scored: one line in the middle of the card, not two empty columns
        self.no_scorers = display_label("No scorers in this match", 13, QFont.DemiBold,
                                        track=1.2, color=FG_MUTED)
        self.no_scorers.setAlignment(Qt.AlignCenter)
        self.no_scorers.hide()
        cv.addWidget(self.no_scorers, stretch=1)
        blocks.addWidget(self.scorers_card, stretch=1)
        bl.addLayout(blocks, stretch=1)
        bl.addStretch(0)
        from ui.stat_compare import ROW_H
        m = sv.contentsMargins()
        self._card_chrome = m.top() + m.bottom() + sv.spacing() + 24       # margins + title
        self._stats_full = len(STAT_ROWS) * ROW_H + self._card_chrome
        self._fit_cards()

    def _show_scorers(self, any_scorer):
        """The two columns, or the one "no scorers" line when nobody scored."""
        self._scorers_scroll.setVisible(any_scorer)
        self.no_scorers.setVisible(not any_scorer)

    def _fit_cards(self):
        """Both cards as tall as the taller of the statistics at full size
        and the whole scorer list, no taller: on a big screen the spare
        height stays below them; on a short one the scorers scroll."""
        scorers = self._scorers_inner.sizeHint().height() + self._card_chrome
        cap = max(self._stats_full, scorers)
        for card in (self.stats_card, self.scorers_card):
            card.setMaximumHeight(cap)

    def _scorer_column(self, cols, tint, side):
        """One side's scorers: the team's name over a line in its colour,
        then name over scores per scorer."""
        col = QWidget()
        col.setStyleSheet("background: transparent;")
        outer = QVBoxLayout(col)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(8)
        team = eyebrow_label(side, color=tint, size=11)
        outer.addWidget(team)
        line = QWidget()
        line.setFixedHeight(3)
        line.setStyleSheet(f"background: {tint};")
        outer.addWidget(line)
        v = QVBoxLayout()
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        v.addStretch(1)
        outer.addLayout(v)
        v.team_label = team
        v.column = col
        cols.addWidget(col, stretch=1, alignment=Qt.AlignTop)
        return v

    # ── data ─────────────────────────────────────────────────────────────
    def set_result(self, match_data, result):
        """`match_data` is what was sent to the backend (team names, crests),
        `result` is what R08_handler.read_match_result() returned. A None
        result means the game exited without one — say so instead of showing
        a fabricated 0-0."""
        home = (match_data or {}).get("team_A", {})
        away = (match_data or {}).get("team_B", {})
        self._set_name(self.home_name, home.get("name", "HOME"))
        self._set_name(self.away_name, away.get("name", "AWAY"))
        for holder, info, default in ((self.home_scorers, home, "home"), (self.away_scorers, away, "away")):
            name = str(info.get("name") or default).upper()
            holder.team_label.setText(holder.team_label.fontMetrics().elidedText(name, Qt.ElideRight, 260))
        self._set_crest(self.home_crest, home.get("logo_frontend") or home.get("logo"))
        self._set_crest(self.away_crest, away.get("logo_frontend") or away.get("logo"))

        self._set_status(result)

        if not result:
            self.home_score.setText("–")
            self.away_score.setText("–")
            self.stats.set_rows([("NO RESULT READ FROM THE GAME", 0, 0)])
            self._fill_scorers(self.home_scorers, [])
            self._fill_scorers(self.away_scorers, [])
            self._show_scorers(False)
            self._fit_cards()
            return

        hs = result.get("team_A", {}).get("score", {}) or {}
        as_ = result.get("team_B", {}).get("score", {}) or {}
        hst = result.get("team_A", {}).get("stats", {}) or {}
        ast = result.get("team_B", {}).get("stats", {}) or {}
        self.home_score.setText(str(hs.get("points", 0)))
        self.away_score.setText(str(as_.get("points", 0)))
        self.stats.set_rows([(label, fn(hs, hst), fn(as_, ast)) for label, fn in STAT_ROWS])
        self.stats.reveal()

        home_n = self._fill_scorers(self.home_scorers, result.get("team_A", {}).get("players", []),
                                    _times(result, "team_A"))
        n = self._fill_scorers(self.away_scorers, result.get("team_B", {}).get("players", []),
                               _times(result, "team_B"))
        self._show_scorers(bool(n or home_n))
        self._fit_cards()

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

    @staticmethod
    def _set_name(label, name):
        """The team name, cut short with … when wider than NAME_W."""
        text = str(name).upper()
        label.setText(label.fontMetrics().elidedText(text, Qt.ElideRight, NAME_W))
        label.setToolTip(text if label.text() != text else "")

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
                label.setPixmap(pix.scaled(CREST - 8, CREST - 8, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def _fill_scorers(self, holder, players, times=None):
        times = times or {}
        while holder.count() > 1:                        # the trailing stretch stays
            item = holder.takeAt(0)
            if item.widget():
                item.widget().hide()
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
            holder.insertWidget(0, display_label("No scorers", 12, QFont.DemiBold,
                                                 track=1.2, color=FG_MUTED))
            return 0
        for i, (name, events) in enumerate(scorers):
            # name over its scores: the column is half a card wide
            entry = QWidget()
            entry.setStyleSheet("background: transparent; border: none;")
            ev = QVBoxLayout(entry)
            ev.setContentsMargins(0, 0, 0, 0)
            ev.setSpacing(0)
            ev.addWidget(display_label(name, 14, QFont.Bold, track=0.4))
            scores = QLabel(events.upper())
            scores.setWordWrap(True)
            scores.setStyleSheet(label_css(10, QFont.DemiBold, FG_SECONDARY, FONT_DISPLAY)
                                 + " background: transparent; border: none;")
            ev.addWidget(scores)
            holder.insertWidget(i, entry)
        return len(scorers)


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
        bl.setContentsMargins(60, 12, 60, 10)
        bl.setSpacing(10)
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
