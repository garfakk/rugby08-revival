"""
app/input.py — Action layer + spatial focus navigation
========================================================
One action layer keyboard feeds today; a pygame-based gamepad source can
feed the same actions later without screens changing (see the approved
UI-redesign plan, "Input + focus system"). Screens implement input once
against Action, not against Qt key codes directly.
"""
from enum import Enum, auto

from PyQt5.QtCore import Qt


class Action(Enum):
    NAV_UP = auto()
    NAV_DOWN = auto()
    NAV_LEFT = auto()
    NAV_RIGHT = auto()
    CONFIRM = auto()
    BACK = auto()
    ALT = auto()
    AUX = auto()
    TAB_PREV = auto()
    TAB_NEXT = auto()
    ADVANCED = auto()


KEYMAP = {
    Qt.Key_Up: Action.NAV_UP,
    Qt.Key_Down: Action.NAV_DOWN,
    Qt.Key_Left: Action.NAV_LEFT,
    Qt.Key_Right: Action.NAV_RIGHT,
    Qt.Key_Return: Action.CONFIRM,
    Qt.Key_Enter: Action.CONFIRM,
    Qt.Key_Space: Action.CONFIRM,
    Qt.Key_Escape: Action.BACK,
    Qt.Key_Backspace: Action.BACK,
    Qt.Key_X: Action.ALT,
    Qt.Key_Y: Action.AUX,
    Qt.Key_Q: Action.TAB_PREV,
    Qt.Key_E: Action.TAB_NEXT,
    Qt.Key_PageUp: Action.TAB_PREV,
    Qt.Key_PageDown: Action.TAB_NEXT,
    Qt.Key_F: Action.ADVANCED,
}

HINT_GLYPH = {
    Action.CONFIRM: "A",
    Action.BACK: "B",
    Action.ALT: "X",
    Action.AUX: "Y",
    Action.TAB_PREV: "LB",
    Action.TAB_NEXT: "RB",
    Action.ADVANCED: "F",
}

_DIRECTION_VEC = {
    Action.NAV_UP: (0, -1),
    Action.NAV_DOWN: (0, 1),
    Action.NAV_LEFT: (-1, 0),
    Action.NAV_RIGHT: (1, 0),
}


def window_rect(widget):
    """`widget`'s rectangle in its top-level window's coordinates.

    `geometry()` is relative to the widget's own parent, so comparing it
    across widgets that live in different cards, grids or scroll areas
    compares unrelated coordinate systems — which is what sent Down from a
    team card's season picker to a button at the bottom of the screen."""
    from PyQt5.QtCore import QPoint, QRect
    top_left = widget.mapTo(widget.window(), QPoint(0, 0))
    return QRect(top_left, widget.size())


def nearest_in_direction(current, candidates, direction: Action):
    """Classic spatial-navigation heuristic: among `candidates`, pick the one
    most plausibly "in that direction" from `current` — primary-axis distance
    dominates, perpendicular offset is penalised, and a candidate that shares
    a row (or column) band with `current` is preferred so grids move straight
    rather than diagonally. Returns None if nothing qualifies."""
    if current is None or current not in candidates:
        if not candidates:
            return None
        return min(candidates, key=lambda w: (window_rect(w).y(), window_rect(w).x()))

    dx, dy = _DIRECTION_VEC.get(direction, (0, 0))
    if dx == 0 and dy == 0:
        return None

    cur = window_rect(current)
    cx, cy = cur.center().x(), cur.center().y()
    best, best_score = None, None
    for w in candidates:
        if w is current:
            continue
        r = window_rect(w)
        vx, vy = r.center().x() - cx, r.center().y() - cy
        primary = vx * dx + vy * dy
        if primary <= 0:
            continue  # not in the requested direction
        perpendicular = abs(vx * dy - vy * dx)
        if dx:   # horizontal move: overlap on the vertical axis = same row
            overlap = min(cur.bottom(), r.bottom()) - max(cur.top(), r.top())
        else:    # vertical move: overlap on the horizontal axis = same column
            overlap = min(cur.right(), r.right()) - max(cur.left(), r.left())
        score = primary + perpendicular * 2.2
        if overlap > 0:
            score -= min(perpendicular, overlap) * 2.0
        if best_score is None or score < best_score:
            best, best_score = w, score
    return best


def _is_deleted(widget):
    try:
        from PyQt5 import sip
    except ImportError:          # pragma: no cover — very old PyQt5
        import sip
    return sip.isdeleted(widget)


class FocusManager:
    """Per-screen registry of navigable widgets, driven by arrow keys instead
    of Tab — geometry-nearest rather than a hand-maintained order, so it
    survives layout changes and reflow without upkeep.

    A scope narrows navigation to one container's descendants while it is
    pushed — an open dialog must not let the arrows wander onto the screen
    behind it."""

    def __init__(self):
        self._widgets = []
        self._scopes = []

    def clear(self):
        self._widgets = []

    def register(self, widget):
        # TabFocus, not StrongFocus: this system moves focus itself (move(),
        # focus_first() below both call widget.setFocus() explicitly, which
        # works under any policy) — StrongFocus's extra ClickFocus bit was
        # Qt's own doing, silently refocusing whatever a mouse click landed
        # on before the widget's own mousePressEvent ever saw the click.
        # Keyboard/pad navigation is unaffected; a mouse click still does
        # whatever the widget's own click handler does, just without also
        # stealing focus onto it.
        widget.setFocusPolicy(Qt.TabFocus)
        self._widgets.append(widget)
        return widget

    def unregister(self, widget):
        self._widgets = [w for w in self._widgets if w is not widget]

    def unregister_tree(self, container):
        self._widgets = [w for w in self._widgets
                         if _is_deleted(w) or not (w is container or container.isAncestorOf(w))]
        self._prune()

    def push_scope(self, container):
        self._scopes.append(container)

    def pop_scope(self, container=None):
        if not self._scopes:
            return
        if container is None:
            self._scopes.pop()
        else:
            self._scopes = [s for s in self._scopes if s is not container]

    def _prune(self):
        self._widgets = [w for w in self._widgets if not _is_deleted(w)]
        self._scopes = [s for s in self._scopes if not _is_deleted(s)]

    def alive(self, within=None):
        """Registered widgets that can take focus right now, narrowed to the
        innermost pushed scope (or to `within`)."""
        self._prune()
        scope = within if within is not None else (self._scopes[-1] if self._scopes else None)
        return [w for w in self._widgets
                if w.isVisible() and w.isEnabled()
                and (scope is None or scope is w or scope.isAncestorOf(w))]

    def focus_first(self, within=None):
        """First registered widget — screens register in the order they want
        focus to start from, so this is registration order, not geometry."""
        alive = self.alive(within)
        if alive:
            alive[0].setFocus()

    def move(self, direction: Action):
        alive = self.alive()
        if not alive:
            return None
        from PyQt5.QtWidgets import QApplication
        current = QApplication.focusWidget()
        current = current if current in alive else None
        target = nearest_in_direction(current, alive, direction)
        if target is not None:
            target.setFocus()
        elif current is None:
            self.focus_first()
        return target
