"""app/shell.py — ScreenManager: QStackedWidget + a real back-history stack.

A screen that defines on_hide() gets it called whenever navigation moves
away from it — via show_screen() to something else, or go_back() — the
same way on_show() already fires when navigation arrives. Symmetric to
on_show() and, unlike it, optional: most screens have nothing to release
on the way out (they just query the store fresh next time), so only the ones
that own something living beyond the widget itself (GameWidget's launched
Rugby08.exe process, notably) need to define it."""
from PyQt5.QtWidgets import QStackedWidget


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
        self.setCurrentWidget(screen)
        if hasattr(screen, "on_show"):
            screen.on_show()

    def go_back(self, default=None):
        current = self.currentWidget()
        if self._history:
            prev = self._history.pop()
            if current is not None and current is not prev and hasattr(current, "on_hide"):
                current.on_hide()
            self.setCurrentWidget(prev)
            if hasattr(prev, "on_show"):
                prev.on_show()
        elif default is not None:
            self.show_screen(default, push_history=False)

    def reset_history(self):
        self._history = []
