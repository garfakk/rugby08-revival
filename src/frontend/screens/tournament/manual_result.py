"""
screens/tournament/manual_result.py — Expert mode: decide a match without
playing it. AUTO-GENERATE fills the form from the simulator; every line can
then be changed, or the whole result typed in. Functional, not pretty: one
event list per side (minute, kind, player; how long for an injury or a ban)
plus penalty tries; the score follows from the events. A level knockout
match also needs the winner.

Recorded untouched, a generated result keeps everything the simulator made
(missed kicks, tackles, replacements); once edited, it is a manual result.
"""
import random

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox,
                             QVBoxLayout, QWidget)

from app.tournament import injuries, manual, simulator
from app.tournament.model import MatchResult

_POINTS = {"try": 5, "conversion": 2, "penalty": 3, "drop": 3}


class _EventRow(QWidget):
    def __init__(self, players, on_change):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        self.minute = QSpinBox()
        self.minute.setRange(0, 120)
        self.minute.setSuffix(" min")
        self.kind = QComboBox()
        self.kind.addItems(manual.EVENT_KINDS)
        self.player = QComboBox()
        for shirt, (pid, name) in enumerate(players, 1):
            self.player.addItem(f"{shirt}. {name}", pid)
        # an injury's type, an injury's or a ban's length
        self.injury_type = QComboBox()
        self.injury_type.addItems([row[0] for row in injuries.INJURY_TABLE])
        self.matches = QSpinBox()
        self.matches.setRange(0, injuries.OUT_FOR_TOURNAMENT)
        self.matches.setValue(1)
        self.matches.setToolTip(f"Matches missed (0 = none, {injuries.OUT_FOR_TOURNAMENT} = "
                                "the rest of the tournament)")
        h.addWidget(self.minute)
        h.addWidget(self.kind)
        h.addWidget(self.player, stretch=1)
        h.addWidget(self.injury_type)
        h.addWidget(self.matches)
        self.kind.currentIndexChanged.connect(self._kind_changed)
        for w in (self.minute, self.matches):
            w.valueChanged.connect(on_change)
        for w in (self.kind, self.player, self.injury_type):
            w.currentIndexChanged.connect(on_change)
        self._kind_changed()

    def _kind_changed(self):
        kind = self.kind.currentText()
        self.injury_type.setVisible(kind == "injury")
        self.matches.setVisible(kind in manual.LENGTH_KINDS)
        self.matches.setSuffix(" matches out" if kind == "injury" else " match ban")

    def set_event(self, ev):
        self.minute.setValue(int(ev.get("minute", 0)))
        self.kind.setCurrentText(ev.get("kind", "try"))
        i = self.player.findData(ev.get("pid"))
        if i >= 0:
            self.player.setCurrentIndex(i)
        if ev.get("type"):
            self.injury_type.setCurrentText(ev["type"])
        if ev.get("matches") is not None:
            self.matches.setValue(int(ev["matches"]))

    def as_dict(self):
        kind = self.kind.currentText()
        out = {"minute": self.minute.value(), "kind": kind, "pid": self.player.currentData()}
        if kind in manual.LENGTH_KINDS:
            out["matches"] = self.matches.value()
        if kind == "injury":
            out["type"] = self.injury_type.currentText()
        return out


class _SidePanel(QWidget):
    def __init__(self, t, team_id, on_change):
        super().__init__()
        self.team_id = team_id
        self._on_change = on_change
        sel = t.teams[team_id].selection.get("players", [])
        self.players = [(pid, t.player_name(pid)) for pid in sel]
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.addWidget(QLabel(f"<b>{t.team_name(team_id)}</b>"))
        self.rows_box = QVBoxLayout()
        v.addLayout(self.rows_box)
        buttons = QHBoxLayout()
        add = QPushButton("+ ADD EVENT")
        add.clicked.connect(self.add_row)
        remove = QPushButton("REMOVE LAST")
        remove.clicked.connect(self.remove_row)
        buttons.addWidget(add)
        buttons.addWidget(remove)
        buttons.addStretch(1)
        v.addLayout(buttons)
        pen = QHBoxLayout()
        pen.addWidget(QLabel("Penalty tries (7 pts, no scorer)"))
        self.penalty_tries = QSpinBox()
        self.penalty_tries.setRange(0, 20)
        self.penalty_tries.valueChanged.connect(on_change)
        pen.addWidget(self.penalty_tries)
        pen.addStretch(1)
        v.addLayout(pen)
        self.rows = []

    def add_row(self):
        row = _EventRow(self.players, self._on_change)
        self.rows.append(row)
        self.rows_box.addWidget(row)
        self._on_change()

    def load(self, events, penalty_tries):
        while self.rows:
            row = self.rows.pop()
            row.setParent(None)
            row.deleteLater()
        for ev in events:
            self.add_row()
            self.rows[-1].set_event(ev)
        self.penalty_tries.setValue(penalty_tries)
        self._on_change()

    def remove_row(self):
        if self.rows:
            row = self.rows.pop()
            row.setParent(None)
            row.deleteLater()
            self._on_change()

    def entered(self):
        return [r.as_dict() for r in self.rows]

    def points(self):
        return (sum(_POINTS.get(e["kind"], 0) for e in self.entered())
                + 7 * self.penalty_tries.value())


class ManualResultView(QWidget):
    def __init__(self, t, fixture):
        super().__init__()
        self.t, self.fixture = t, fixture
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        self.score = QLabel()
        self.score.setAlignment(Qt.AlignCenter)
        v.addWidget(self.score)
        tools = QHBoxLayout()
        gen = QPushButton("AUTO-GENERATE")
        gen.setToolTip("A simulated result for this match (again for another one)")
        gen.clicked.connect(self.auto_generate)
        clear = QPushButton("CLEAR")
        clear.clicked.connect(lambda: self._load(([], [], 0, 0)))
        self.origin = QLabel()
        tools.addWidget(gen)
        tools.addWidget(clear)
        tools.addWidget(self.origin, stretch=1)
        v.addLayout(tools)
        self._generated = None      # the simulated result while the form still shows it
        self._loading = False
        body = QWidget()
        bv = QVBoxLayout(body)
        self.home = _SidePanel(t, fixture.home, self._refresh)
        self.away = _SidePanel(t, fixture.away, self._refresh)
        bv.addWidget(self.home)
        bv.addWidget(self.away)
        bv.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(380)
        scroll.setWidget(body)
        v.addWidget(scroll)
        self.tie_box = QWidget()
        th = QHBoxLayout(self.tie_box)
        th.setContentsMargins(0, 0, 0, 0)
        th.addWidget(QLabel("Level knockout match — winner:"))
        self.winner = QComboBox()
        self.winner.addItem(t.team_name(fixture.home), fixture.home)
        self.winner.addItem(t.team_name(fixture.away), fixture.away)
        self.decided_by = QComboBox()
        self.decided_by.addItems(["tries", "kicks"])
        self.winner.currentIndexChanged.connect(self._refresh)
        self.decided_by.currentIndexChanged.connect(self._refresh)
        th.addWidget(self.winner)
        th.addWidget(self.decided_by)
        th.addStretch(1)
        v.addWidget(self.tie_box)
        self._refresh()

    def auto_generate(self):
        result = simulator.simulate(self.t, self.fixture, random.Random())
        self._load(manual.from_result(self.t, result, random.Random()), result)

    def _load(self, events, generated=None):
        home, away, home_pt, away_pt = events
        self._loading = True
        self.home.load(home, home_pt)
        self.away.load(away, away_pt)
        if generated and generated.winner:
            self.winner.setCurrentIndex(self.winner.findData(generated.winner))
            self.decided_by.setCurrentText(generated.decided_by or "tries")
        self._generated = generated
        self._refresh()
        self._loading = False

    def _refresh(self):
        if not self._loading:
            # any change of the generated lines makes it a manual result
            self._generated = None
        self.origin.setText("  simulated" if self._generated else "  entered by hand")
        h, a = self.home.points(), self.away.points()
        self.score.setText(f"<h2>{self.t.team_name(self.fixture.home)} {h} – {a} "
                           f"{self.t.team_name(self.fixture.away)}</h2>")
        self.tie_box.setVisible(bool(self.fixture.knockout) and h == a)

    def result(self) -> MatchResult:
        typed = manual.build_result(
            self.t, self.fixture, self.home.entered(), self.away.entered(),
            self.home.penalty_tries.value(), self.away.penalty_tries.value(),
            self.winner.currentData(), self.decided_by.currentText())
        if self._generated:
            # the simulator's own result, with the injury and ban lengths it showed
            self._generated.extra["manual"] = typed.extra["manual"]
            return self._generated
        return typed

