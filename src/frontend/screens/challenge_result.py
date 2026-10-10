"""
screens/challenge_result.py — Challenge result screen
=========================================================
Shown instead of the plain full-time screen when the match was a challenge
(match_data["challenge"], set by challenge_mode.py). Judges the match on the
final score for the side the player controlled and frames it with the
challenge's own win / draw / loss text and rewards. The game's own .mis
objectives are not read back: the challenge's match objectives are judged by
the mod (app/challenge_objectives.py) and a win counts only when every one
of them is met.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QScrollArea
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt

from app import challenge_objectives
from app.screen_base import Screen
from screens.post_match import PostMatchScreen, StatComparison, STAT_ROWS
from ui import StyledButton
from ui.broadcast import Card, HintBar, page_header, eyebrow_label, display_label, label_css
from ui.theme import (
    BG_BASE, ACCENT, HOME_TINT, AWAY_TINT, GREEN, DANGER_LITE,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED, FONT_DISPLAY, BTN_HEIGHT,
)

# The result's team keys, by side
_KEY = {"home": "team_A", "away": "team_B"}
_DEFAULT_TEXT = {
    "win": "Challenge completed.",
    "draw": "A draw is not enough. Try again.",
    "loss": "Challenge failed. Try again.",
    "missed": "The match is won, but not every objective was met. Try again.",
}


class ChallengeResultScreen(Screen):
    def __init__(self, on_retry, on_challenges, on_main_menu):
        super().__init__(on_back=on_challenges)
        self.on_retry = on_retry
        self.on_challenges = on_challenges
        self.on_main_menu = on_main_menu
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header_holder = QWidget()
        hh = QVBoxLayout(self.header_holder)
        hh.setContentsMargins(0, 0, 0, 0)
        hh.addWidget(page_header("Challenge result", breadcrumb="challenge mode",
                                 on_back=self.on_challenges))
        root.addWidget(self.header_holder)

        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(80, 20, 80, 16)
        bl.setSpacing(12)

        self.name = eyebrow_label("", color=FG_SECONDARY, size=14)
        self.name.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.name)

        self.outcome = display_label("", 56, QFont.Bold, track=6.0)
        self.outcome.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.outcome)

        self.text = QLabel("")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setStyleSheet(label_css(16, QFont.Normal, FG_PRIMARY, FONT_DISPLAY))
        bl.addWidget(self.text)

        self.objectives = QLabel("")
        self.objectives.setAlignment(Qt.AlignCenter)
        self.objectives.setWordWrap(True)
        self.objectives.setTextFormat(Qt.RichText)
        self.objectives.setStyleSheet(label_css(14, QFont.DemiBold, FG_SECONDARY, FONT_DISPLAY))
        bl.addWidget(self.objectives)

        self.reward = eyebrow_label("", color=GREEN, size=14)
        self.reward.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.reward)

        # ── scoreline ────────────────────────────────────────────────────
        score_row = QHBoxLayout()
        score_row.setSpacing(24)
        self.home_crest, self.away_crest = QLabel(), QLabel()
        for crest in (self.home_crest, self.away_crest):
            crest.setFixedSize(90, 90)
            crest.setAlignment(Qt.AlignCenter)
            crest.setStyleSheet("background: transparent;")
        self.home_name = display_label("—", 22, QFont.Bold, track=1.2)
        self.away_name = display_label("—", 22, QFont.Bold, track=1.2)
        self.home_score = display_label("0", 54, QFont.Bold, track=1.0)
        self.away_score = display_label("0", 54, QFont.Bold, track=1.0)
        score_row.addStretch(1)
        for w in (self.home_crest, self.home_name, self.home_score):
            score_row.addWidget(w, alignment=Qt.AlignVCenter)
        score_row.addWidget(display_label("—", 28, QFont.Bold, track=0, color=FG_MUTED),
                            alignment=Qt.AlignVCenter)
        for w in (self.away_score, self.away_name, self.away_crest):
            score_row.addWidget(w, alignment=Qt.AlignVCenter)
        score_row.addStretch(1)
        bl.addLayout(score_row)

        self.status = eyebrow_label("", color=ACCENT, size=16)
        self.status.setAlignment(Qt.AlignCenter)
        bl.addWidget(self.status)

        # ── summary: statistics and scorers ──────────────────────────────
        summary = QHBoxLayout()
        summary.setSpacing(20)
        stats_card = Card()
        sv = QVBoxLayout(stats_card)
        sv.setContentsMargins(24, 14, 24, 14)
        sv.addWidget(eyebrow_label("summary", color=ACCENT, size=13))
        self.stats = StatComparison([])
        sv.addWidget(self.stats)
        sv.addStretch(1)
        summary.addWidget(stats_card, stretch=3)

        self.scorers_card = Card()
        scorer_layout = QVBoxLayout(self.scorers_card)
        scorer_layout.setContentsMargins(18, 14, 18, 14)
        scorer_layout.setSpacing(8)
        scorer_layout.addWidget(eyebrow_label("scorers", color=ACCENT, size=13))
        self.scorers_scroll = QScrollArea()
        self.scorers_scroll.setWidgetResizable(True)
        self.scorers_scroll.setFrameShape(QScrollArea.NoFrame)
        self.scorers_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scorers_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scorers_content = QWidget()
        self.scorers_content.setStyleSheet("background: transparent;")
        self.scorers_layout = QVBoxLayout(self.scorers_content)
        self.scorers_layout.setContentsMargins(0, 0, 0, 0)
        self.scorers_layout.setSpacing(6)
        self.scorers_scroll.setWidget(self.scorers_content)
        scorer_layout.addWidget(self.scorers_scroll)
        summary.addWidget(self.scorers_card, stretch=2)
        bl.addLayout(summary, stretch=1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._buttons = {}
        for key, text, variant, slot in (
                ("retry", "RETRY", "neutral", lambda: self.on_retry()),
                ("challenges", "CHALLENGES", "primary", lambda: self.on_challenges()),
                ("menu", "MAIN MENU", "neutral", lambda: self.on_main_menu())):
            btn = StyledButton(text, variant)
            btn.setMinimumHeight(BTN_HEIGHT)
            btn.setMinimumWidth(180)
            btn.clicked.connect(slot)
            self.focus.register(btn)
            actions.addWidget(btn)
            self._buttons[key] = btn
        bl.addLayout(actions)
        root.addWidget(body, stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "select"), ("B", "challenges")])
        root.addWidget(self.hintbar)

    _set_crest = PostMatchScreen._set_crest

    def _show_scorers(self, result):
        while self.scorers_layout.count():
            item = self.scorers_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for key, name, tint in (("team_A", self.home_name.text(), HOME_TINT),
                                ("team_B", self.away_name.text(), AWAY_TINT)):
            self.scorers_layout.addWidget(eyebrow_label(name, color=tint, size=11))
            players = ((result or {}).get(key) or {}).get("players", [])
            scorers = []
            for player in players:
                events = []
                for field, label in (("tries", "TRY"),
                                     ("conversions_scored", "CON"),
                                     ("penalties_scored", "PEN"),
                                     ("drop_goals", "DROP")):
                    count = player.get(field) or 0
                    if count:
                        events.append(f"{label} ×{count}" if count > 1 else label)
                if events:
                    scorers.append((player.get("name", "—"), " · ".join(events)))

            if not scorers:
                self.scorers_layout.addWidget(display_label(
                    "No scorers", 12, QFont.DemiBold, color=FG_MUTED))
                continue
            for player_name, events in scorers:
                row = QHBoxLayout()
                row.addWidget(display_label(player_name, 14, QFont.Bold, track=0.3))
                row.addStretch(1)
                row.addWidget(display_label(events, 11, QFont.DemiBold, color=FG_SECONDARY))
                wrapper = QWidget()
                wrapper.setStyleSheet("background: transparent;")
                wrapper.setLayout(row)
                self.scorers_layout.addWidget(wrapper)
        self.scorers_layout.addStretch(1)

    def on_show(self):
        super().on_show()
        self._buttons["challenges"].setFocus()

    # ── data ─────────────────────────────────────────────────────────────
    @staticmethod
    def judge(challenge, result):
        """"win" / "draw" / "loss", or None when the match was left early or
        no result could be read."""
        if not result or result.get("finished") is False:
            return None
        points = {side: ((result.get(key) or {}).get("score") or {}).get("points", 0)
                  for side, key in _KEY.items()}
        mine = challenge.get("user_side", "home")
        other = "away" if mine == "home" else "home"
        if points[mine] > points[other]:
            checks = challenge_objectives.judge_all(challenge, result)
            return "win" if all(passed for _, passed, _ in checks) else "missed"
        return "loss" if points[mine] < points[other] else "draw"

    def _show_objectives(self, challenge, result):
        """The objectives ticked or crossed, or just listed when the match
        was not completed."""
        lines = challenge.get("objective_lines") or []
        if not challenge.get("match_objectives"):
            self.objectives.setText("")
            return
        rows = []
        if result and result.get("finished") is not False:
            checks = challenge_objectives.judge_all(challenge, result)
            for line, (_, passed, _) in zip(lines[1:], checks):
                mark, color = ("✓", GREEN) if passed else ("✗", DANGER_LITE)
                rows.append(f'<span style="color:{color}">{mark}</span> {line}')
        else:
            rows = [f"· {line}" for line in lines[1:]]
        self.objectives.setText("<br>".join(rows))

    def set_result(self, match_data, result):
        challenge = (match_data or {}).get("challenge") or {}
        home = (match_data or {}).get("team_A", {})
        away = (match_data or {}).get("team_B", {})
        self.name.setText(challenge.get("name", "").upper())
        self.home_name.setText(home.get("name", "HOME").upper())
        self.away_name.setText(away.get("name", "AWAY").upper())
        self._set_crest(self.home_crest, home.get("logo_frontend") or home.get("logo"))
        self._set_crest(self.away_crest, away.get("logo_frontend") or away.get("logo"))

        verdict = self.judge(challenge, result)
        style = {"win": ("CHALLENGE WON", GREEN), "draw": ("DRAW", FG_PRIMARY),
                 "loss": ("CHALLENGE LOST", DANGER_LITE),
                 "missed": ("OBJECTIVES MISSED", DANGER_LITE)}
        self._show_objectives(challenge, result)
        if verdict:
            word, color = style[verdict]
            body = challenge.get(f"{verdict}_text") or _DEFAULT_TEXT[verdict]
            rewards = [u.get("name") for u in challenge.get("unlockables") or [] if u.get("name")]
            self.reward.setText("UNLOCKED: " + ", ".join(rewards)
                                if verdict == "win" and rewards else "")
            self.status.setText("")
        else:
            word, color = "NOT COMPLETED", FG_MUTED
            body = ("The match was left before full time." if result
                    else "No result could be read from the game.")
            self.reward.setText("")
            minute = (result or {}).get("minute")
            self.status.setText(f"MATCH INTERRUPTED AT {minute} MIN"
                                if result and minute else "")
        self.outcome.setText(word)
        self.outcome.setStyleSheet(label_css(56, QFont.Bold, color, FONT_DISPLAY))
        self.text.setText(body)

        self._show_scorers(result)
        if not result:
            self.home_score.setText("–")
            self.away_score.setText("–")
            self.stats.set_rows([])
            return
        hs = (result.get("team_A") or {}).get("score") or {}
        as_ = (result.get("team_B") or {}).get("score") or {}
        hst = (result.get("team_A") or {}).get("stats") or {}
        ast = (result.get("team_B") or {}).get("stats") or {}
        self.home_score.setText(str(hs.get("points", 0)))
        self.away_score.setText(str(as_.get("points", 0)))
        self.stats.set_rows([(label, fn(hs, hst), fn(as_, ast))
                             for label, fn in STAT_ROWS[:5]])
