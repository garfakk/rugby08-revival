"""app/screen_base.py — common keyboard/focus wiring every screen shares."""
from PyQt5.QtWidgets import QWidget, QApplication, QAbstractButton
from PyQt5.QtCore import Qt

from app.input import Action, KEYMAP, FocusManager


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

    def on_show(self):
        # Park focus on the screen itself, not its first widget: a focused
        # widget is drawn red, so focusing one on arrival highlighted a button
        # nobody had picked. Keys still reach keyPressEvent from here, and the
        # first arrow press lands on the first widget (FocusManager.move).
        self.setFocus(Qt.OtherFocusReason)

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
        if action == Action.BACK and self.on_back_cb:
            self.on_back_cb()
            event.accept()
            return
        super().keyPressEvent(event)
