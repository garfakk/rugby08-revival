"""
screens/tournament/prefs.py — A tournament's preferences as Settings rows:
MATCH (difficulty, half length) and SQUAD (injuries, fatigue, suspensions),
side by side, with a line under them explaining the focused one.

Used by the wizard (before the tournament starts) and the dashboard's
SETTINGS tab (changed during it: every option is read again at each match
and each simulated round, so a change applies from the next one).
"""
from PyQt5.QtCore import QEvent, pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app import difficulty
from app.challenges import HALF_LENGTHS
from ui import CycleRow, ToggleRow
from ui.broadcast import eyebrow_label
from ui.editor_kit import Note
from ui.theme import ACCENT, FG_TERTIARY

from .common import transparent

# key -> (label, kind, help); kind "cycle" takes its values from VALUES
PREFS = {
    "difficulty": ("Difficulty", "cycle", "How well the computer plays in your matches."),
    "halftime_length": ("Half Length", "cycle", "The length of each half of the matches you play."),
    "injuries": ("Injuries", "toggle", "Players get hurt in matches and miss the next ones."),
    "fatigue": ("Fatigue", "toggle", "Players tire from match to match: rotate your squad to keep it fresh."),
    "suspensions": ("Suspensions", "toggle", "Cards add up to bans that keep players out of later matches."),
}
GROUPS = [("match", ["difficulty", "halftime_length"]),
          ("squad", ["injuries", "fatigue", "suspensions"])]
VALUES = {
    "difficulty": [(level, level.capitalize()) for level in difficulty.LEVELS],
    "halftime_length": [(v, f"{v[:-1]} min" if v.endswith("m") else v) for v in HALF_LENGTHS],
}
DEFAULTS = {"difficulty": "elite", "halftime_length": "5m",
            "injuries": True, "fatigue": True, "suspensions": True}


class PrefsPanel(QWidget):
    """The rows (DEFAULTS until set_values); `changed(key, value)` on each
    change made on a row."""

    changed = pyqtSignal(str, object)

    def __init__(self, parent=None):
        super().__init__(parent)
        transparent(self, "tourPrefs")
        self._values = dict(DEFAULTS)
        self.rows = {}
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(10)
        self._cols = QHBoxLayout()
        self._cols.setSpacing(36)
        v.addLayout(self._cols)
        for title, keys in GROUPS:
            col = QVBoxLayout()
            col.setSpacing(0)
            heading = eyebrow_label(title, color=ACCENT, size=11)
            heading.setContentsMargins(17, 0, 0, 8)
            col.addWidget(heading)
            for key in keys:
                row = self._row(key)
                row.installEventFilter(self)
                col.addWidget(row)
                self.rows[key] = row
            col.addStretch(1)
            self._cols.addLayout(col, stretch=1)
        self.help = Note("", color=FG_TERTIARY)
        self.help.setContentsMargins(17, 0, 0, 0)
        self.help.setMinimumHeight(22)
        v.addWidget(self.help)
        self._quiet = False

    def set_values(self, options):
        """Show `options` (missing keys: DEFAULTS); no `changed`."""
        self._quiet = True
        try:
            for key, default in DEFAULTS.items():
                value = (options or {}).get(key, default)
                row = self.rows[key]
                if PREFS[key][1] == "toggle":
                    row.set_state(bool(value))
                else:
                    shown = dict(VALUES[key])
                    row.set_current(shown.get(value, VALUES[key][0][1]))
                self._values[key] = value
        finally:
            self._quiet = False

    def _row(self, key):
        label, kind, _help = PREFS[key]
        if kind == "toggle":
            return ToggleRow(label, bool(self._values[key]), lambda on, k=key: self._set(k, bool(on)))
        pairs = VALUES[key]
        shown = dict(pairs)
        back = {text: value for value, text in pairs}
        current = shown.get(self._values[key], pairs[0][1])
        return CycleRow(label, [text for _v, text in pairs], current,
                        lambda text, k=key: self._set(k, back[text]))

    def _set(self, key, value):
        self._values[key] = value
        if not self._quiet:
            self.changed.emit(key, value)

    def values(self):
        return dict(self._values)

    def focus_rows(self):
        """The rows in focus order (one column, then the next)."""
        return [self.rows[k] for _title, keys in GROUPS for k in keys if k in self.rows]

    def eventFilter(self, obj, event):
        if event.type() == QEvent.FocusIn:
            key = next((k for k, r in self.rows.items() if r is obj), None)
            if key:
                self.help.setText(PREFS[key][2])
        return False
