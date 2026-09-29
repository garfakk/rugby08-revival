"""
ui/side_panel.py — slide-over side panes
=============================================
Shared open/close motion for the screens' side panes (match setup's
ADVANCED, the squad editor's ROLES / SET PLAYS). A pane is an ordinary
child widget positioned by hand over its screen — this only owns how it
gets on and off: it slides in horizontally from whichever vertical screen
edge it rests against, and leaves the same way.

The host keeps owning the resting geometry (it is the thing that knows how
wide its own pane is and where it sits), and passes it as a callable so a
window resize mid-animation still lands the pane in the right place.

Usage:

    self.panel = self._build_panel()
    self.panel.setParent(self)
    self.panel.hide()
    self._slide = SidePanelSlide(self.panel, self._panel_rect)

    def _panel_rect(self):
        return QRect(self.width() - WIDTH, 0, WIDTH, self.height())

    def resizeEvent(self, event):       # keep it glued while open
        super().resizeEvent(event)
        self._slide.sync_geometry()

    def toggle(self):
        self._open = not self._open
        self._slide.set_open(self._open)
"""
from PyQt5.QtCore import (
    QObject, QRect, QPropertyAnimation, QEasingCurve, pyqtSignal,
)

SLIDE_MS = 280
# Out of the edge on the way in (fast start, soft landing), back into it on
# the way out — the pane never decelerates into a position it is leaving.
CURVE_IN = QEasingCurve.OutCubic
CURVE_OUT = QEasingCurve.InCubic


class SidePanelSlide(QObject):
    """Drives one pane's horizontal slide. Safe to call repeatedly and
    mid-flight: an in-progress slide is reversed from wherever it is, not
    restarted from the edge."""

    opened = pyqtSignal()
    closed = pyqtSignal()

    def __init__(self, panel, resting, duration=SLIDE_MS, parent=None):
        super().__init__(parent or panel)
        self._panel = panel
        self._resting = resting          # callable -> QRect
        self._open = False
        self._anim = QPropertyAnimation(panel, b"geometry", self)
        self._anim.setDuration(duration)
        self._anim.finished.connect(self._on_finished)

    # ── geometry ─────────────────────────────────────────────────────────
    def _resting_rect(self):
        return QRect(self._resting())

    def _parked_rect(self):
        """The resting rect pushed out through the nearest vertical edge of
        the host. Which edge is decided by where the pane actually rests —
        a left-hand pane slides out of the left, a right-hand one out of the
        right — so this needs no per-pane configuration."""
        rect = self._resting_rect()
        host = self._panel.parentWidget()
        host_w = host.width() if host is not None else rect.right()
        parked = QRect(rect)
        if rect.center().x() * 2 >= host_w:
            parked.moveLeft(host_w)            # out through the right edge
        else:
            parked.moveLeft(-rect.width())     # out through the left edge
        return parked

    def sync_geometry(self):
        """Host resized: re-place the pane. While a slide is running the
        animation's endpoints are re-aimed instead, so the resize does not
        snap it or leave it heading for a stale rect."""
        if self._anim.state() == QPropertyAnimation.Running:
            self._anim.setStartValue(self._panel.geometry())
            self._anim.setEndValue(self._resting_rect() if self._open
                                   else self._parked_rect())
            return
        if self._open:
            self._panel.setGeometry(self._resting_rect())
        elif self._panel.isVisible():
            self._panel.setGeometry(self._parked_rect())

    # ── transport ────────────────────────────────────────────────────────
    @property
    def is_open(self):
        return self._open

    def open(self):
        self.set_open(True)

    def close(self):
        self.set_open(False)

    def set_open(self, open_, animate=True):
        if open_ == self._open and self._anim.state() != QPropertyAnimation.Running:
            # Already settled where it is asked to be — but a pane opened
            # before its host was ever shown still needs placing.
            if open_:
                self._panel.setGeometry(self._resting_rect())
                self._panel.show()
                self._panel.raise_()
            return
        self._open = open_
        self._anim.stop()

        if not animate:
            self._panel.setGeometry(self._resting_rect() if open_ else self._parked_rect())
            self._panel.setVisible(open_)
            if open_:
                self._panel.raise_()
            (self.opened if open_ else self.closed).emit()
            return

        if open_:
            # Start from where it already is if a close was interrupted,
            # otherwise from off the edge.
            start = (self._panel.geometry() if self._panel.isVisible()
                     else self._parked_rect())
            self._panel.setGeometry(start)
            self._panel.show()
            self._panel.raise_()
            self._anim.setStartValue(start)
            self._anim.setEndValue(self._resting_rect())
            self._anim.setEasingCurve(CURVE_IN)
        else:
            self._anim.setStartValue(self._panel.geometry())
            self._anim.setEndValue(self._parked_rect())
            self._anim.setEasingCurve(CURVE_OUT)
        self._anim.start()

    def _on_finished(self):
        if self._open:
            self._panel.setGeometry(self._resting_rect())
            self.opened.emit()
        else:
            self._panel.hide()
            self.closed.emit()
