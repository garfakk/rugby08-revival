"""
app/edit_session.py — working copy, undo/redo and dirty tracking
==================================================================
One record (a team's seasons, or a player) is edited through one session.
Widgets never mutate data directly: every edit is `apply(label, fn)`, which
is what makes undo, the "● N unsaved" count and the refresh all come from a
single place.

Snapshots rather than a command pattern: the records are small JSON, and a
snapshot can never drift out of sync with the operation that produced it.
"""
import copy
import time

from PyQt5.QtCore import QObject, pyqtSignal

UNDO_LIMIT = 200
COALESCE_SECONDS = 0.9


def _flatten(value, prefix="", out=None):
    """Leaf paths → values. Dicts also contribute their key order, so moving
    a kit (whose position matters to the game) counts as a change."""
    if out is None:
        out = {}
    if isinstance(value, dict):
        out[prefix + "__order__"] = tuple(value.keys())
        for k, v in value.items():
            _flatten(v, f"{prefix}{k}.", out)
    elif isinstance(value, list):
        out[prefix + "__len__"] = len(value)
        for i, v in enumerate(value):
            _flatten(v, f"{prefix}{i}.", out)
    else:
        out[prefix.rstrip(".")] = value
    return out


class _Entry:
    __slots__ = ("label", "before", "after", "key", "t", "hint")

    def __init__(self, label, before, after, key, hint):
        self.label, self.before, self.after = label, before, after
        self.key, self.t, self.hint = key, time.monotonic(), hint


class EditSession(QObject):
    # (label, view_hint) — view_hint tells the screen where the change lives
    # (e.g. {"season": "2026", "tab": 1, "field": "attack"}) so undoing an edit
    # made on another tab first brings it into view.
    changed = pyqtSignal(str, object)

    def __init__(self, record, parent=None):
        super().__init__(parent)
        self.baseline = copy.deepcopy(record)
        self.working = copy.deepcopy(record)
        self._undo = []
        self._redo = []
        self._baseline_flat = _flatten(self.baseline)

    # ── edits ────────────────────────────────────────────────────────────
    def apply(self, label, mutate, coalesce_key=None, view_hint=None):
        """Run `mutate(working)`. Returns True if anything changed. Repeated
        edits to the same `coalesce_key` in quick succession (stepping a
        rating, typing a number) merge into one undo step."""
        before = copy.deepcopy(self.working)
        mutate(self.working)
        if self.working == before:
            return False
        top = self._undo[-1] if self._undo else None
        if (coalesce_key is not None and top is not None and top.key == coalesce_key
                and time.monotonic() - top.t < COALESCE_SECONDS):
            top.after = copy.deepcopy(self.working)
            top.t = time.monotonic()
        else:
            self._undo.append(_Entry(label, before, copy.deepcopy(self.working),
                                     coalesce_key, view_hint))
            del self._undo[:-UNDO_LIMIT]
        self._redo.clear()
        self.changed.emit(label, view_hint)
        return True

    def replace(self, label, new_record, view_hint=None):
        return self.apply(label, lambda w: (w.clear(), w.update(copy.deepcopy(new_record)))
                          if isinstance(w, dict) else None, view_hint=view_hint)

    def can_undo(self):
        return bool(self._undo)

    def can_redo(self):
        return bool(self._redo)

    def undo_label(self):
        return self._undo[-1].label if self._undo else ""

    def redo_label(self):
        return self._redo[-1].label if self._redo else ""

    def undo(self):
        if not self._undo:
            return None
        entry = self._undo.pop()
        self._redo.append(entry)
        self._set_working(entry.before)
        self.changed.emit(f"undo {entry.label}", entry.hint)
        return entry

    def redo(self):
        if not self._redo:
            return None
        entry = self._redo.pop()
        self._undo.append(entry)
        self._set_working(entry.after)
        self.changed.emit(f"redo {entry.label}", entry.hint)
        return entry

    def _set_working(self, snapshot):
        # Mutate in place: widgets and helpers may hold a reference to
        # `working` (or to a dict inside it) for the whole session.
        fresh = copy.deepcopy(snapshot)
        if isinstance(self.working, dict) and isinstance(fresh, dict):
            self.working.clear()
            self.working.update(fresh)
        else:
            self.working = fresh

    # ── dirty / save ─────────────────────────────────────────────────────
    def changed_paths(self):
        now = _flatten(self.working)
        keys = set(now) | set(self._baseline_flat)
        return sorted(k for k in keys if now.get(k, _MISSING) != self._baseline_flat.get(k, _MISSING))

    def change_count(self):
        """How many values differ from the file — not how many edits were
        made, so undoing back to the original clears it."""
        paths = self.changed_paths()
        # A structural change (order/length) plus the leaves it moved would
        # otherwise count every shifted element; report one per container.
        structural = {p.rsplit("__", 2)[0] for p in paths if p.endswith(("__order__", "__len__"))}
        leaves = [p for p in paths if not p.endswith(("__order__", "__len__"))
                  and not any(p.startswith(s) for s in structural)]
        return len(structural) + len(leaves)

    def is_dirty(self):
        return self.working != self.baseline

    def mark_saved(self):
        self.baseline = copy.deepcopy(self.working)
        self._baseline_flat = _flatten(self.baseline)

    def revert(self):
        self._set_working(self.baseline)
        self._undo.clear()
        self._redo.clear()
        self.changed.emit("revert", None)


_MISSING = object()
