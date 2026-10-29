"""app/screen_base.py — common keyboard/focus wiring every screen shares."""
from PyQt5.QtWidgets import QWidget, QApplication, QAbstractButton, QScrollArea
from PyQt5.QtCore import Qt, QObject, QEvent

from app.input import Action, KEYMAP, FocusManager, nearest_in_direction, reveal


class _PassKeysOn(QObject):
    """On a scroll area: the keys of a widget inside it that the widget left
    unused go on to the screen instead of scrolling the area, so the arrows
    (and a pad) move the focus out of a card list rather than scrolling it.
    The area still scrolls when it has the focus itself."""

    def eventFilter(self, area, event):
        if event.type() == QEvent.KeyPress and event.key() in KEYMAP:
            focus = QApplication.focusWidget()
            if focus is not None and focus is not area and area.isAncestorOf(focus):
                event.ignore()          # skips the area, carries on to its parent
                return True
        return False


_PASS_KEYS_ON = _PassKeysOn()


def pass_keys_through_scroll_areas(root):
    """Install _PassKeysOn on every scroll area under `root` (once each)."""
    for area in root.findChildren(QScrollArea):
        if not area.property("passesKeysOn"):
            area.setProperty("passesKeysOn", True)
            area.installEventFilter(_PASS_KEYS_ON)


class Screen(QWidget):
    """Base class for every top-level screen. Handles arrow-key navigation
    (via FocusManager) and Enter/Space/Escape uniformly, so each screen only
    has to register its focusable widgets and handle ALT/AUX/ADVANCED if it
    uses them."""

    def __init__(self, on_back=None, parent=None):
        super().__init__(parent)
        self.focus = FocusManager()
        self.on_back_cb = on_back
        self.setFocusPolicy(Qt.StrongFocus)

    def showEvent(self, event):
        # Scroll areas filled after construction (lists rebuilt on show) too
        pass_keys_through_scroll_areas(self)
        super().showEvent(event)

    def on_show(self):
        # Park focus on the screen itself, not its first widget: a focused
        # widget is drawn red, so focusing one on arrival highlighted a button
        # nobody had picked. Keys still reach keyPressEvent from here, and the
        # first arrow press lands on the first widget (FocusManager.move).
        self.setFocus(Qt.OtherFocusReason)

    def remove_focused_row(self):
        """Y: press the remove button (property removesRow) of the row holding
        the focus — it sits past the row's fields, which keep Left/Right for
        their values, so the arrows can't reach it."""
        w = QApplication.focusWidget()
        while w is not None and w is not self:
            for button in w.findChildren(QAbstractButton, options=Qt.FindDirectChildrenOnly):
                if button.property("removesRow") and button.isVisible() and button.isEnabled():
                    # the focus goes to what is above the row, chosen before it goes
                    others = [o for o in self.focus.alive() if not (o is w or w.isAncestorOf(o))]
                    target = nearest_in_direction(QApplication.focusWidget(), others + [QApplication.focusWidget()],
                                                  Action.NAV_UP)
                    button.click()
                    if target is not None:
                        target.setFocus()
                        reveal(target)
                    return True
            w = w.parentWidget()
        return False

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action in (Action.NAV_UP, Action.NAV_DOWN, Action.NAV_LEFT, Action.NAV_RIGHT):
            self.focus.move(action)
            event.accept()
            return
        if action == Action.CONFIRM:
            w = QApplication.focusWidget()
            if isinstance(w, QAbstractButton):
                w.click()
                event.accept()
                return
        if action == Action.AUX and self.remove_focused_row():
            event.accept()
            return
        if action == Action.BACK and self.on_back_cb:
            self.on_back_cb()
            event.accept()
            return
        super().keyPressEvent(event)
