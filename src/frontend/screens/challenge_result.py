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
from screens.post_match import MatchReport
from ui import StyledButton
from ui.broadcast import Card, HintBar, page_header, eyebrow_label, display_label, label_css
from ui.checklist import CheckList
from ui.theme import (
    BG_BASE, ACCENT, GREEN, DANGER_LITE, FG_PRIMARY, FG_SECONDARY, FG_MUTED, FONT_DISPLAY, BTN_HEIGHT,
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
    """The quick match's full-time report (screens.post_match.MatchReport)
    with the challenge's verdict and objectives above the statistics."""

    def __init__(self, on_retry, on_challenges):
        super().__init__(on_back=on_challenges)
        self.on_retry = on_retry
        self.on_challenges = on_challenges
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Challenge result"))

        body = QWidget()
        body.setObjectName("challengeResultBody")
        body.setStyleSheet(f"QWidget#challengeResultBody {{ background: {BG_BASE}; }}")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setFocusPolicy(Qt.NoFocus)
        scroll.setWidget(body)
        bl = QVBoxLayout(body)
        bl.setContentsMargins(80, 24, 80, 16)
        bl.setSpacing(16)

        self.report = MatchReport()
        report_layout = self.report.layout()

        # the verdict and the objectives, between the scoreline and the stats
        verdict = QWidget()
        verdict.setStyleSheet("background: transparent;")
        vl = QVBoxLayout(verdict)
        vl.setContentsMargins(0, 0, 0, 0)
        vl.setSpacing(8)
        self.name = eyebrow_label("", color=FG_SECONDARY, size=14)
        self.name.setAlignment(Qt.AlignCenter)
        vl.addWidget(self.name)
        self.outcome = display_label("", 44, QFont.Bold, track=6.0)
        self.outcome.setAlignment(Qt.AlignCenter)
        vl.addWidget(self.outcome)
        self.text = QLabel("")
        self.text.setAlignment(Qt.AlignCenter)
        self.text.setWordWrap(True)
        self.text.setStyleSheet(label_css(16, QFont.Normal, FG_PRIMARY, FONT_DISPLAY))
        vl.addWidget(self.text)
        self.reward = eyebrow_label("", color=GREEN, size=14)
        self.reward.setAlignment(Qt.AlignCenter)
        vl.addWidget(self.reward)
        report_layout.insertWidget(2, verdict)

        self.objectives_card = Card(stripe=ACCENT)
        ol = QVBoxLayout(self.objectives_card)
        ol.setContentsMargins(24, 14, 24, 16)
        ol.setSpacing(10)
        ol.addWidget(eyebrow_label("objectives", color=ACCENT, size=13))
        self.objectives = CheckList(size=14)
        ol.addWidget(self.objectives)
        report_layout.insertWidget(3, self.objectives_card)
        bl.addWidget(self.report, stretch=1)

        actions = QHBoxLayout()
        actions.addStretch(1)
        self._buttons = {}
        for key, text, variant, slot in (
                ("retry", "RETRY", "neutral", lambda: self.on_retry()),
                ("challenges", "BACK TO CHALLENGES", "primary", lambda: self.on_challenges())):
            btn = StyledButton(text, variant)
            btn.setMinimumHeight(BTN_HEIGHT)
            btn.setMinimumWidth(180)
            btn.clicked.connect(slot)
            self.focus.register(btn)
            actions.addWidget(btn)
            self._buttons[key] = btn
        root.addWidget(scroll, stretch=1)
        # the actions stay in view, under the report
        foot = QWidget()
        foot.setObjectName("challengeResultFoot")
        foot.setStyleSheet(f"QWidget#challengeResultFoot {{ background: {BG_BASE}; }}")
        actions.setContentsMargins(80, 10, 80, 16)
        foot.setLayout(actions)
        root.addWidget(foot)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "select"), ("B", "back to challenges")])
        root.addWidget(self.hintbar)

    @property
    def stats(self):
        return self.report.stats

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

    def _show_objectives(self, challenge, result, verdict):
        """The objectives as tick boxes: the ones met ticked (none when the
        match was not completed)."""
        lines = challenge.get("objective_lines") or []
        shown = bool(lines and challenge.get("match_objectives"))   # as before the match
        self.objectives_card.setVisible(shown)
        if not shown:
            return
        ticked = [False] * len(lines)
        if verdict:
            ticked[0] = verdict in ("win", "missed")          # "Win the match"
            checks = challenge_objectives.judge_all(challenge, result)
            for i, (_, passed, _) in enumerate(checks[:len(lines) - 1]):
                ticked[i + 1] = bool(passed)
        self.objectives.set_items(lines, ticked)

    def set_result(self, match_data, result):
        challenge = (match_data or {}).get("challenge") or {}
        self.name.setText(challenge.get("name", "").upper())
        self.report.set_result(match_data, result)

        verdict = self.judge(challenge, result)
        style = {"win": ("CHALLENGE WON", GREEN), "draw": ("DRAW", FG_PRIMARY),
                 "loss": ("CHALLENGE LOST", DANGER_LITE),
                 "missed": ("OBJECTIVES MISSED", DANGER_LITE)}
        self._show_objectives(challenge, result, verdict)
        if verdict:
            word, color = style[verdict]
            body = challenge.get(f"{verdict}_text") or _DEFAULT_TEXT[verdict]
            rewards = [u.get("name") for u in challenge.get("unlockables") or [] if u.get("name")]
            self.reward.setText("UNLOCKED: " + ", ".join(rewards)
                                if verdict == "win" and rewards else "")
        else:
            word, color = "NOT COMPLETED", FG_MUTED
            body = ("The match was left before full time." if result
                    else "No result could be read from the game.")
            self.reward.setText("")
        self.reward.setVisible(bool(self.reward.text()))
        self.outcome.setText(word)
        self.outcome.setStyleSheet(label_css(44, QFont.Bold, color, FONT_DISPLAY))
        self.text.setText(body)
