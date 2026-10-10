"""
screens/tournament/manual_result.py — Expert mode: type a match result in
instead of playing or simulating it. Functional, not pretty: one event list
per side (minute, kind, player) plus penalty tries; the score follows from
the events. A level knockout match also needs the winner.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QComboBox, QHBoxLayout, QLabel, QPushButton, QScrollArea, QSpinBox,
                             QVBoxLayout, QWidget)

from app.tournament import manual
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
        h.addWidget(self.minute)
        h.addWidget(self.kind)
        h.addWidget(self.player, stretch=1)
        self.minute.valueChanged.connect(on_change)
        self.kind.currentIndexChanged.connect(on_change)
        self.player.currentIndexChanged.connect(on_change)

    def as_dict(self):
        return {"minute": self.minute.value(), "kind": self.kind.currentText(),
                "pid": self.player.currentData()}


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
        th.addWidget(self.winner)
        th.addWidget(self.decided_by)
        th.addStretch(1)
        v.addWidget(self.tie_box)
        self._refresh()

    def _refresh(self):
        h, a = self.home.points(), self.away.points()
        self.score.setText(f"<h2>{self.t.team_name(self.fixture.home)} {h} – {a} "
                           f"{self.t.team_name(self.fixture.away)}</h2>")
        self.tie_box.setVisible(bool(self.fixture.knockout) and h == a)

    def result(self) -> MatchResult:
        return manual.build_result(
            self.t, self.fixture, self.home.entered(), self.away.entered(),
            self.home.penalty_tries.value(), self.away.penalty_tries.value(),
            self.winner.currentData(), self.decided_by.currentText())
