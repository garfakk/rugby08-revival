"""
screens/tournament/prefs.py — A tournament's preferences as Settings rows:
MATCH (difficulty, half length) and SQUAD (injuries, fatigue, suspensions),
side by side.

Used by the wizard (before the tournament starts) and the dashboard's
SETTINGS tab (MATCH only, changed during it: every option is read again at
each match, so a change applies from the next one; SQUAD is fixed once the
tournament has started).
"""
from PyQt5.QtCore import pyqtSignal
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app import difficulty
from app.challenges import HALF_LENGTHS
from ui import CycleRow, ToggleRow
from ui.broadcast import eyebrow_label
from ui.theme import ACCENT

from .common import transparent

# key -> (label, kind); kind "cycle" takes its values from VALUES
PREFS = {
    "difficulty": ("Difficulty", "cycle"),
    "halftime_length": ("Half Length", "cycle"),
    "injuries": ("Injuries", "toggle"),
    "fatigue": ("Fatigue", "toggle"),
    "suspensions": ("Suspensions", "toggle"),
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

    def __init__(self, parent=None, groups=None):
        """`groups`: the GROUPS titles shown (all by default)."""
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
            if groups is not None and title not in groups:
                continue
            col = QVBoxLayout()
            col.setSpacing(0)
            heading = eyebrow_label(title, color=ACCENT, size=11)
            heading.setContentsMargins(17, 0, 0, 8)
            col.addWidget(heading)
            for key in keys:
                row = self._row(key)
                col.addWidget(row)
                self.rows[key] = row
            col.addStretch(1)
            self._cols.addLayout(col, stretch=1)
        self._quiet = False

    def set_values(self, options):
        """Show `options` (missing keys: DEFAULTS); no `changed`."""
        self._quiet = True
        try:
            for key, default in DEFAULTS.items():
                value = (options or {}).get(key, default)
                self._values[key] = value
                row = self.rows.get(key)
                if row is None:
                    continue
                if PREFS[key][1] == "toggle":
                    row.set_state(bool(value))
                else:
                    shown = dict(VALUES[key])
                    row.set_current(shown.get(value, VALUES[key][0][1]))
                self._values[key] = value
        finally:
            self._quiet = False

    def _row(self, key):
        label, kind = PREFS[key]
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
