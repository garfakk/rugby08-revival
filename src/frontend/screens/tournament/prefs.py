"""
screens/tournament/prefs.py — A tournament's preferences as Settings rows:
MATCH (difficulty, half length), SQUAD (injuries, fatigue, suspensions, the CPU teams' squads) and
RULES (50/22, 22m), side by side.

Used by the wizard (before the tournament starts) and the dashboard's
SETTINGS tab (MATCH only, changed during it: every option is read again at
each match, so a change applies from the next one; SQUAD and RULES are fixed
once the tournament has started).
"""
from PyQt5.QtCore import QSize, pyqtSignal
from PyQt5.QtWidgets import QGridLayout, QLayout, QVBoxLayout, QWidget

from app import difficulty
from backend import crowd
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
    "cpu_squads": ("CPU Squads", "cycle"),
    "law_5022": ("50/22", "toggle"),
    "law_22m": ("22m", "toggle"),
    "law_penalty_touch": ("80' Penalty Touch", "toggle"),
    "crowd_size": ("Crowd", "cycle"),
    "crowd_colours": ("Team Colours", "toggle"),
    "crowd_mood": ("Atmosphere", "cycle"),
    "referee": ("Referee", "cycle"),
}
GROUPS = [("match", ["difficulty", "halftime_length"]),
          ("squad", ["injuries", "fatigue", "suspensions", "cpu_squads"]),
          ("rules", ["law_5022", "law_22m", "law_penalty_touch"])]
if crowd.OPTIONS_ENABLED:
    GROUPS.append(("crowd", ["crowd_size", "crowd_colours", "crowd_mood"]))
GROUPS.append(("referee", ["referee"]))
# shown in expert mode only
EXPERT_GROUPS = {"crowd", "referee"}
VALUES = {
    "difficulty": [(level, level.capitalize()) for level in difficulty.LEVELS],
    "halftime_length": [(v, f"{v[:-1]} min" if v.endswith("m") else v) for v in HALF_LENGTHS],
    # the teams the user doesn't manage: their own 22, or the best available
    "cpu_squads": [("default", "Default"), ("best", "Best")],
    "crowd_size": [("full", "Full"), ("busy", "Busy"), ("half", "Half"), ("sparse", "Sparse")],
    "crowd_mood": [("normal", "Normal"), ("quiet", "Quiet")],
}
DEFAULTS = {"difficulty": "elite", "halftime_length": "5m",
            "injuries": True, "fatigue": True, "suspensions": True, "cpu_squads": "default",
            "law_5022": True, "law_22m": True, "law_penalty_touch": True,
            "crowd_size": "full", "crowd_colours": False, "crowd_mood": "normal",
            "referee": "", "referee_kits": []}
KIT_ROW = "referee_kit:"   # + kit: one toggle row per referee kit ("referee_kits")


def referee_values():
    """The referee choices (app/referees.py): the game's own, one drawn for
    each match, or the same one every match."""
    from app import referees
    return ([(referees.STOCK, "Game's own"), (referees.RANDOM, "Random")]
            + [(rid, r["name"] or rid) for rid, r in referees.load().items()])


def referee_kit_keys():
    """The rows of the referee kits a competition's referees may wear (none
    ticked: each referee's own)."""
    from app import referees
    return [KIT_ROW + kit for kit in referees.kits()]


class PrefsPanel(QWidget):
    """The rows (DEFAULTS until set_values); `changed(key, value)` on each
    change made on a row."""

    changed = pyqtSignal(str, object)

    def __init__(self, parent=None, groups=None):
        """`groups`: the GROUPS titles shown (all by default)."""
        super().__init__(parent)
        transparent(self, "tourPrefs")
        self._values = dict(DEFAULTS)
        self._pairs = dict(VALUES, referee=referee_values())
        self.rows = {}
        # The groups side by side when they fit, else wrapped onto more rows
        # (a small window): see _reflow.
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setHorizontalSpacing(36)
        self._grid.setVerticalSpacing(18)
        self._grid.setSizeConstraint(QLayout.SetNoConstraint)
        self._columns = []
        self._order = []
        from shared.user_prefs import user_prefs
        for title, keys in GROUPS:
            if title == "referee":
                keys = keys + referee_kit_keys()
            if groups is not None and title not in groups:
                continue
            if title in EXPERT_GROUPS and not user_prefs.expert_mode:
                continue
            column = transparent(QWidget(), f"tourPrefs_{title}")
            col = QVBoxLayout(column)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            heading = eyebrow_label(title, color=ACCENT, size=11)
            heading.setContentsMargins(17, 0, 0, 8)
            col.addWidget(heading)
            for key in keys:
                row = self._row(key)
                col.addWidget(row)
                self.rows[key] = row
                self._order.append(key)
            col.addStretch(1)
            self._columns.append(column)
        self._per_row = 0
        self._reflow(len(self._columns))
        self._quiet = False

    def _fit(self, width):
        """How many groups fit side by side in `width`."""
        mins = [c.minimumSizeHint().width() for c in self._columns]
        spacing = self._grid.horizontalSpacing()
        for n in range(len(mins), 1, -1):
            if max(mins) * n + spacing * (n - 1) <= width:
                return n
        return 1

    def _reflow(self, per_row):
        if per_row == self._per_row:
            return
        self._per_row = per_row
        for c in self._columns:
            self._grid.removeWidget(c)
        for i in range(self._grid.columnCount()):
            self._grid.setColumnStretch(i, 0)
        for i, c in enumerate(self._columns):
            self._grid.addWidget(c, i // per_row, i % per_row)
        for i in range(per_row):
            self._grid.setColumnStretch(i, 1)
        self.updateGeometry()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._reflow(self._fit(self.width()))

    def minimumSizeHint(self):
        # one group wide (narrower windows wrap the groups instead of cutting
        # them), as tall as the groups are in their current rows
        widest = max((c.minimumSizeHint().width() for c in self._columns), default=0)
        return QSize(widest, self._grid.minimumSize().height())

    def sizeHint(self):
        return QSize(max(self.minimumSizeHint().width(), self._grid.sizeHint().width()),
                     self._grid.sizeHint().height())

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
                    shown = dict(self._pairs[key])
                    row.set_current(shown.get(value, self._pairs[key][0][1]))
                self._values[key] = value
            self._values["referee_kits"] = list(self._values.get("referee_kits") or [])
            for key, row in self.rows.items():
                if key.startswith(KIT_ROW):
                    row.set_state(key[len(KIT_ROW):] in self._values["referee_kits"])
        finally:
            self._quiet = False

    def _row(self, key):
        if key.startswith(KIT_ROW):
            from app import referees
            kit = key[len(KIT_ROW):]
            return ToggleRow(f"{referees.kit_label(kit).capitalize()} kit",
                             kit in (self._values.get("referee_kits") or []),
                             lambda on, k=kit: self._set_kit(k, bool(on)))
        label, kind = PREFS[key]
        if kind == "toggle":
            return ToggleRow(label, bool(self._values[key]), lambda on, k=key: self._set(k, bool(on)))
        pairs = self._pairs[key]
        shown = dict(pairs)
        back = {text: value for value, text in pairs}
        current = shown.get(self._values[key], pairs[0][1])
        return CycleRow(label, [text for _v, text in pairs], current,
                        lambda text, k=key: self._set(k, back[text]))

    def _set(self, key, value):
        self._values[key] = value
        if not self._quiet:
            self.changed.emit(key, value)

    def _set_kit(self, kit, on):
        """Tick / untick referee kit `kit` (option "referee_kits")."""
        kits = [k for k in self._values.get("referee_kits") or [] if k != kit]
        if on:
            kits.append(kit)
        self._set("referee_kits", kits)

    def values(self):
        return dict(self._values, referee_kits=list(self._values.get("referee_kits") or []))

    def focus_rows(self):
        """The rows in focus order (one column, then the next)."""
        return [self.rows[k] for k in self._order]
