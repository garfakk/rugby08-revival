"""
screens/challenge_mode.py — Challenge mode (game modes)
=========================================================
Lists the challenges authored in the Challenge Editor (mod_data/challenges),
one card each: the crests around the score and minute it starts on, the
name, match-up and the start of the briefing. Picking one opens the match
presentation screen — briefing, kits on the 3D players, difficulty and half
length (always the player's pick) and whatever else the challenge leaves to
the player. The match is built from the challenge's own MatchConfig and
launched the same way a rematch is, so the post-match screen and rematch
work unchanged.
"""
import copy

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QFrame, QScrollArea, QVBoxLayout, QWidget

from app import challenges as ch
from app.input import Action, KEYMAP
from app.match_data_builder import build_match_data
from app.screen_base import Screen
from screens.match_presentation import Choice, Presentation, SideSpec
from screens.tournament.common import ActivatableCard, team_crest
from ui.atmosphere import AtmosphereWidget
from ui.broadcast import HintBar, eyebrow_label, page_header, tracked_font
from ui.editor_kit import Note
from ui.theme import (ACCENT, AWAY_TINT, BORDER, FG_MUTED, FG_PRIMARY, FG_SECONDARY,
                      FG_TERTIARY, FONT_BODY, FONT_DISPLAY, HOME_TINT, WARN)

CREST = 64
SCORE_W = 112
LEFT_W = 24 + CREST + SCORE_W + CREST + 24     # the match-up block


def _elide_lines(fm: QFontMetrics, text: str, width: int, lines: int) -> list:
    """`text` word-wrapped to at most `lines` lines of `width`, the last one
    elided when it doesn't all fit."""
    words = " ".join(text.split()).split(" ")
    out, line = [], ""
    for i, word in enumerate(words):
        trial = f"{line} {word}".strip()
        if fm.horizontalAdvance(trial) <= width or not line:
            line = trial
            continue
        out.append(line)
        line = word
        if len(out) == lines - 1:
            rest = " ".join([line] + words[i + 1:])
            out.append(fm.elidedText(rest, Qt.ElideRight, width))
            return out
    if line:
        out.append(line)
    return out


class ChallengeCard(ActivatableCard):
    """One challenge: both crests around the score it starts on and the
    minute, the side the player takes marked; name, match-up and the start
    of the briefing beside it. A challenge that can't be played shows why."""

    def __init__(self, ds, number, data, problems, parent=None):
        super().__init__(parent, stripe=WARN if problems else None)
        self.setFixedHeight(156)
        self.data = data
        self.number = number
        self.problems = problems
        self._crests = {}
        self._names = {}
        for side in ("home", "away"):
            slot = data[side]
            info = ds.team_season(slot["team_id"], slot["season"], slot.get("variant", ""))
            self._names[side] = (info.get("name") or slot["team_id"] or "?").upper()
            self._crests[side] = team_crest(ds, slot["team_id"], slot["season"], CREST,
                                            variant=slot.get("variant", ""))
        sid = data["stadium_id"] or next(iter(ds.stadiums), "")
        self._stadium = (ds.stadiums.get(sid, {}).get("name") or "").upper()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self.paint_background(p)
        d, w, h = self.data, self.width(), self.height()
        hot = self.hasFocus() or self.underMouse()

        # ── match-up block: crest, score + minute, crest ──
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.6))
        p.setPen(QColor(ACCENT if hot else FG_TERTIARY))
        p.drawText(QRectF(24, 12, LEFT_W - 48, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   f"CHALLENGE {self.number:02d}")
        top = 40
        for side, x in (("home", 24), ("away", 24 + CREST + SCORE_W)):
            p.drawPixmap(x, top, self._crests[side])
            if d["user_side"] == side:
                tint = HOME_TINT if side == "home" else AWAY_TINT
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(tint))
                p.drawRoundedRect(QRectF(x + 8, top + CREST + 8, CREST - 16, 3), 1.5, 1.5)
                p.setPen(QColor(tint))
                p.setFont(tracked_font(FONT_DISPLAY, 9, QFont.Bold, 1.6))
                p.drawText(QRectF(x - 10, top + CREST + 13, CREST + 20, 16), Qt.AlignCenter, "YOU")
        home_pts, away_pts = ch.start_score(d)
        minute = ch.start_minute(d)
        box = QRectF(24 + CREST, top, SCORE_W, CREST)
        p.setPen(QColor(FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 28, QFont.Bold, 0.5))
        p.drawText(box.adjusted(0, -6, 0, -18), Qt.AlignCenter, f"{home_pts}–{away_pts}")
        label = f"{minute}' · {'2ND' if minute >= 40 else '1ST'} HALF" if minute is not None else "KICK-OFF"
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.4))
        tw = QFontMetrics(p.font()).horizontalAdvance(label) + 14
        pill = QRectF(box.center().x() - tw / 2, box.bottom() - 16, tw, 18)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT if minute is not None else BORDER))
        p.drawRoundedRect(pill, 9, 9)
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(pill, Qt.AlignCenter, label)

        # divider
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawLine(LEFT_W, 18, LEFT_W, h - 18)

        # ── text block ──
        x = LEFT_W + 24
        tw = w - x - 56
        p.setFont(tracked_font(FONT_DISPLAY, 21, QFont.Bold, 0.8))
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(x, 12, tw, 32), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(d["name"].upper(), Qt.ElideRight, int(tw)))
        meta = f"YOU PLAY {self._names[d['user_side']]}"
        if self._stadium:
            meta += f"   ·   {self._stadium}"
        p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.DemiBold, 1.2))
        p.setPen(QColor(FG_TERTIARY))
        p.drawText(QRectF(x, 44, tw, 18), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(meta, Qt.ElideRight, int(tw)))

        body = QFont(FONT_BODY, 10)
        p.setFont(body)
        fm = QFontMetrics(body)
        if self.problems:
            p.setPen(QColor(WARN))
            text = "Cannot be played: " + "; ".join(self.problems)
        else:
            p.setPen(QColor(FG_SECONDARY))
            text = d.get("description") or ""
        y = 72
        for line in _elide_lines(fm, text, int(tw), 3):
            p.drawText(QRectF(x, y, tw, fm.height()), Qt.AlignLeft | Qt.AlignVCenter, line)
            y += fm.height() + 2

        # play chevron
        if not self.problems:
            p.setFont(tracked_font(FONT_DISPLAY, 30, QFont.Bold, 0))
            p.setPen(QColor(ACCENT if hot else FG_MUTED))
            p.drawText(QRectF(w - 48, 0, 32, h), Qt.AlignCenter, "›")


class ChallengeModeScreen(Screen):
    def __init__(self, ds, on_back, on_play, on_present, parent=None):
        super().__init__(on_back=on_back, parent=parent)
        self.ds = ds
        self.on_play = on_play          # fn(match_data)
        self.on_present = on_present    # fn(Presentation)
        self._all = {}
        self._tiles = []
        self._build()

    def _build(self):
        self._backdrop = AtmosphereWidget(self)
        self._backdrop.lower()
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Challenge Mode", breadcrumb="game modes",
                                   on_back=self.on_back_cb))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        body = QWidget()
        body.setObjectName("challengeBody")
        body.setStyleSheet("QWidget#challengeBody { background: transparent; }")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(80, 32, 80, 24)
        bl.setSpacing(6)
        self.count_label = eyebrow_label("challenges", color=ACCENT, size=13)
        bl.addWidget(self.count_label)
        bl.addWidget(Note("Step into a match already under way: the score, the clock and the "
                          "squads are set. Pick your difficulty and half length, then finish the job.",
                          color=FG_SECONDARY))
        bl.addSpacing(14)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(12)
        bl.addLayout(self.list_layout)
        self.empty = Note("No challenges yet. Create one in Tools → Challenge Editor.",
                          color=FG_MUTED)
        bl.addWidget(self.empty)
        bl.addStretch(1)
        self.scroll.setWidget(body)
        root.addWidget(self.scroll, stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "select"), ("B", "back")])
        root.addWidget(self.hintbar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._backdrop.setGeometry(self.rect())
        self._backdrop.lower()

    def on_show(self):
        super().on_show()
        self.reload()

    def reload(self):
        """Re-read the folder (the editor may have changed it)."""
        for tile in self._tiles:
            self.focus.unregister(tile)
            tile.setParent(None)
            tile.deleteLater()
        self._tiles = []
        self._all = ch.load_all()
        for number, (cid, data) in enumerate(self._all.items(), start=1):
            tile = ChallengeCard(self.ds, number, data, ch.problems(self.ds, data))
            tile.activated.connect(lambda c=cid: self._play(c))
            tile.focused.connect(lambda t=tile: self.scroll.ensureWidgetVisible(t, 0, 20))
            self.focus.register(tile)
            self.list_layout.addWidget(tile)
            self._tiles.append(tile)
        n = len(self._all)
        self.count_label.setText(f"{n} challenge{'s' if n != 1 else ''}".upper())
        self.count_label.setVisible(bool(n))
        self.empty.setVisible(not n)

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        w = self.focusWidget()
        if action == Action.CONFIRM and isinstance(w, ChallengeCard):
            w.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def _play(self, cid):
        data = self._all.get(cid)
        if not data or ch.problems(self.ds, data):
            return
        work = copy.deepcopy(data)     # the player's picks never reach the file

        choices = []
        for key, label in ch.CHOOSABLE.items():
            if key in ("home_kit", "away_kit") or not ch.is_choice(work, key):
                continue
            values, display = ch.choice_options(self.ds, work, key)
            choices.append(Choice(label, values, ch.get_choice(work, key), display,
                                  apply=lambda v, k=key: ch.set_choice(work, k, v)))

        def side(name):
            slot = work[name]
            return SideSpec(slot["team_id"], slot["season"], slot["kit"],
                            kit_locked=not ch.is_choice(work, f"{name}_kit"),
                            variant=slot.get("variant", ""),
                            kit_variant=slot.get("kit_variant", ""),
                            kit_override=ch.custom_kit(work, name))

        def kickoff():
            match_data = build_match_data(self.ds, ch.to_match_config(self.ds, work))
            if match_data:
                # What the full-time screen needs to frame the result; rides
                # along in match_data so a rematch keeps it.
                match_data["challenge"] = {
                    k: copy.deepcopy(work[k]) for k in
                    ("name", "user_side", "win_text", "draw_text", "loss_text", "unlockables",
                     "match_objectives", "score_events", "mission_mode_time")}
                match_data["challenge"]["objective_lines"] = ch.objective_lines(self.ds, work)
                self.on_play(match_data)

        self.on_present(Presentation(
            title="Challenge Mode", breadcrumb="game modes · challenge",
            eyebrow="challenge", heading=work["name"], briefing=work["description"],
            details=self._details(work),
            objectives=ch.objective_lines(self.ds, work) if work.get("match_objectives") else [],
            home=side("home"), away=side("away"),
            choices=choices,
            on_kit=lambda s, key: work[s].__setitem__("kit", key),
            on_kickoff=kickoff,
            controlled=lambda: {work["user_side"]}))

    def _details(self, data):
        """The settings the challenge fixes, one line each."""
        lines = []
        if not ch.is_choice(data, "stadium_id"):
            sid = data["stadium_id"] or next(iter(self.ds.stadiums), "")
            name = self.ds.stadiums.get(sid, {}).get("name", "")
            # The description usually opens with the venue already.
            if name and name.lower() not in (data.get("description") or "").lower():
                lines.append(f"Stadium: {name}")
        for key, label in (("difficulty", "Difficulty"), ("halftime_length", "Half length"),
                           ("environment", "Conditions")):
            if not ch.is_choice(data, key):
                lines.append(f"{label}: {data[key]}")
        return lines
