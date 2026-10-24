"""app/shell.py — ScreenManager: QStackedWidget + a real back-history stack.

A screen that defines on_hide() gets it called whenever navigation moves
away from it — via show_screen() to something else, or go_back() — the
same way on_show() already fires when navigation arrives. Symmetric to
on_show() and, unlike it, optional: most screens have nothing to release
on the way out (they just query the store fresh next time), so only the ones
that own something living beyond the widget itself (GameWidget's launched
Rugby08.exe process, notably) need to define it."""
from PyQt5.QtWidgets import QApplication, QStackedWidget

# Rounds of posted events run before a screen is painted: a screen sizing parts of itself from its own
# size (resizeEvent -> setFixedSize -> one more relayout, scroll bars appearing) settles in a few rounds.
SETTLE_PASSES = 4


def present(stack, screen, call_on_show=True):
    """Make `screen` the current page of `stack` with its layout already settled at its real size, so its
    first frame is its final one: painting is held while it becomes visible, on_show() fills it, and the
    relayouts that triggers (proportional crests, kit stages, text that changes widths) run synchronously."""
    screen.setUpdatesEnabled(False)
    try:
        stack.setCurrentWidget(screen)
        if call_on_show and hasattr(screen, "on_show"):
            screen.on_show()
        for _ in range(SETTLE_PASSES):
            QApplication.sendPostedEvents()      # relayouts, resizes, queued calls (scroll bars)
    finally:
        screen.setUpdatesEnabled(True)


class ScreenManager(QStackedWidget):
    def __init__(self):
        super().__init__()
        self._history = []

    def show_screen(self, screen, push_history=True):
        current = self.currentWidget()
        if current is not None and current is not screen:
            if push_history:
                self._history.append(current)
            if hasattr(current, "on_hide"):
                current.on_hide()
        if self.indexOf(screen) < 0:
            self.addWidget(screen)
        self._present(screen)

    def go_back(self, default=None):
        current = self.currentWidget()
        if self._history:
            prev = self._history.pop()
            if current is not None and current is not prev and hasattr(current, "on_hide"):
                current.on_hide()
            self._present(prev)
        elif default is not None:
            self.show_screen(default, push_history=False)

    def _present(self, screen):
        present(self, screen)

    def reset_history(self):
        self._history = []
