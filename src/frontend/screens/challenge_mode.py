"""
screens/challenge_mode.py — Challenge mode (game modes)
=========================================================
Lists the challenges authored in the Challenge Editor (mod_data/challenges),
one tile each: name and match-up. Picking one opens the match presentation
screen — briefing, kits on the 3D players, and whatever the challenge leaves
to the player. The match is built from the challenge's own MatchConfig and
launched the same way a rematch is, so the post-match screen and rematch
work unchanged.
"""
import copy

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QScrollArea, QFrame
from PyQt5.QtCore import Qt

from app import challenges as ch
from app.input import Action, KEYMAP
from app.match_data_builder import build_match_data
from app.screen_base import Screen
from screens.match_presentation import Choice, Presentation, SideSpec
from ui.broadcast import HintBar, MenuTile, page_header
from ui.editor_kit import Note
from ui.theme import BG_BASE, FG_MUTED


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
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Challenge Mode", breadcrumb="game modes",
                                   on_back=self.on_back_cb))

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet(f"QScrollArea {{ background: {BG_BASE}; border: none; }}")
        self.scroll.viewport().setStyleSheet(f"background: {BG_BASE};")
        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(80, 40, 80, 24)
        bl.setSpacing(10)
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(10)
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
        for cid, data in self._all.items():
            found = ch.problems(self.ds, data)
            subtitle = ("cannot be played: " + "; ".join(found)) if found \
                else ch.summary(self.ds, data)
            tile = MenuTile(data["name"].upper(), subtitle)
            tile.activated.connect(lambda c=cid: self._play(c))
            self.focus.register(tile)
            self.list_layout.addWidget(tile)
            self._tiles.append(tile)
        self.empty.setVisible(not self._all)

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        w = self.focusWidget()
        if action == Action.CONFIRM and isinstance(w, MenuTile):
            w.activate()
            event.accept()
            return
        super().keyPressEvent(event)
        w = self.focusWidget()
        if isinstance(w, MenuTile):
            self.scroll.ensureWidgetVisible(w, 0, 20)

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
                            kit_locked=not ch.is_choice(work, f"{name}_kit"))

        def kickoff():
            match_data = build_match_data(self.ds, ch.to_match_config(self.ds, work))
            if match_data:
                self.on_play(match_data)

        self.on_present(Presentation(
            title="Challenge Mode", breadcrumb="game modes · challenge",
            eyebrow="challenge", heading=work["name"], briefing=work["description"],
            details=self._details(work), home=side("home"), away=side("away"),
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
            if name:
                lines.append(f"Stadium: {name}")
        for key, label in (("difficulty", "Difficulty"), ("halftime_length", "Half length"),
                           ("environment", "Conditions")):
            if not ch.is_choice(data, key):
                lines.append(f"{label}: {data[key]}")
        return lines
