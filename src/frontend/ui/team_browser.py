"""
ui/team_browser.py — the widgets of the alternative team pickers
(app/team_browse.py, Settings > Quick Match Picker).

  ChipBar         a wrapped row of chips, one selected: the season chips of
                  the browser styles, and the filter chips inside the browser
  SeasonTimeline  a team's seasons as dots on a line, gaps visible
  TeamBrowser     the popup: every team grouped by kind, a search typed on
                  the keyboard, optional filter chips (leagues, Six Nations)

ChipBar and SeasonTimeline have the interface of SelectorRow that the match
setup column uses (set_values / current / index_of / set_index / has_values
/ changed), and consume Left/Right while focused, like it.
"""
from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import QSizePolicy, QWidget

from app.team_browse import search_match
from ui.broadcast import tracked_font
from ui.dropdown import PopupList
from ui.theme import (ACCENT, BG_RAISED, BORDER, FG_MUTED, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY,
                      FONT_DISPLAY)


class _Selector(QWidget):
    """What ChipBar and SeasonTimeline share: the values, the index, the
    signal, Left/Right."""

    changed = pyqtSignal()

    def __init__(self, display=str, focusable=True, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus if focusable else Qt.NoFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._values, self._index, self._display = [], 0, display

    def set_values(self, values, index=0):
        self._values = list(values)
        self._index = max(0, min(index, len(self._values) - 1)) if self._values else 0
        self._relayout()
        self.update()

    def _relayout(self):
        pass

    def current(self):
        return self._values[self._index] if self._values else None

    def has_values(self):
        return bool(self._values)

    def index(self):
        return self._index

    def index_of(self, value):
        try:
            return self._values.index(value)
        except ValueError:
            return None

    def set_index(self, i, notify=False):
        if not self._values:
            return
        i = max(0, min(i, len(self._values) - 1))
        if i != self._index:
            self._index = i
            self.update()
            if notify:
                self.changed.emit()

    def step(self, d):
        self.set_index(self._index + d, notify=True)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            self.step(-1 if event.key() == Qt.Key_Left else 1)
            event.accept()
            return
        super().keyPressEvent(event)


class ChipBar(_Selector):
    """Chips in rows that wrap; the selected one filled."""

    CHIP_H, GAP, PAD = 30, 6, 12

    def __init__(self, display=str, focusable=True, parent=None):
        super().__init__(display, focusable, parent)
        self._rects = []
        self.setMouseTracking(True)

    def _font(self):
        return tracked_font(FONT_DISPLAY, 11, QFont.Bold, 0.8)

    def _layout(self, width):
        fm = QFontMetrics(self._font())
        x = y = 0
        rects = []
        for v in self._values:
            w = fm.horizontalAdvance(str(self._display(v)).upper()) + 2 * self.PAD
            if x and x + w > width:
                x, y = 0, y + self.CHIP_H + self.GAP
            rects.append(QRectF(x, y, w, self.CHIP_H))
            x += w + self.GAP
        return rects, (y + self.CHIP_H if rects else 0)

    def _relayout(self):
        self._rects, h = self._layout(max(self.width(), 200))
        self.setFixedHeight(max(h, self.CHIP_H))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        rects, h = self._layout(self.width())
        if h != self.height() and h:
            self.setFixedHeight(h)
        self._rects = rects

    def mousePressEvent(self, event):
        for i, r in enumerate(self._rects):
            if r.contains(event.pos()):
                self.set_index(i, notify=True)
                return

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(self._font())
        for i, (v, r) in enumerate(zip(self._values, self._rects)):
            on = i == self._index
            p.fillRect(r, QColor(ACCENT if on else BG_RAISED))
            if on and self.hasFocus():
                p.setPen(QPen(QColor(FG_PRIMARY), 1))
                p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
            p.setPen(QColor(FG_PRIMARY if on else FG_SECONDARY))
            p.drawText(r, Qt.AlignCenter, str(self._display(v)).upper())


class SeasonTimeline(_Selector):
    """The team's seasons as dots on a line over the span of the whole data:
    filled where it has a squad, hollow where it has none; the selected one
    large. Left/Right move between the seasons it has."""

    def __init__(self, years, display=str, focusable=True, parent=None):
        super().__init__(display, focusable, parent)
        self._years = [str(y) for y in years]      # every year of the data, oldest first
        self.setFixedHeight(64)

    def _x(self, year):
        i = self._years.index(year) if year in self._years else 0
        pad = 18
        span = max(1, len(self._years) - 1)
        return pad + (self.width() - 2 * pad) * i / span

    def mousePressEvent(self, event):
        have = [(abs(self._x(v) - event.x()), i) for i, v in enumerate(self._values)]
        if have:
            self.set_index(min(have)[1], notify=True)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        y = 20
        p.setPen(QPen(QColor(BORDER), 2))
        p.drawLine(int(self._x(self._years[0])) if self._years else 0, y,
                   int(self._x(self._years[-1])) if self._years else 0, y)
        have = set(self._values)
        selected = self.current()
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 0.4))
        for yr in self._years:
            x = self._x(yr)
            if yr in have:
                on = yr == selected
                p.setBrush(QColor(ACCENT if on else FG_SECONDARY))
                p.setPen(Qt.NoPen)
                r = 8 if on else 5
            else:
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(QColor(FG_MUTED), 1))
                r = 3.5
            p.drawEllipse(QRectF(x - r, y - r, 2 * r, 2 * r))
            if yr == selected or int(yr) % 4 == 3:
                p.setPen(QColor(ACCENT if yr == selected else FG_TERTIARY))
                p.drawText(QRectF(x - 24, y + 12, 48, 16), Qt.AlignCenter, f"'{yr[2:]}")
        if self.hasFocus():
            p.setBrush(Qt.NoBrush)
            p.setPen(QPen(QColor(ACCENT), 1))
            p.drawRect(0, 0, self.width() - 1, self.height() - 1)


class TeamBrowser:
    """The popup list of teams. Rows are grouped (a disabled header per
    group); typing filters by name, Backspace edits it; with `filters` the
    chips above the list narrow it (Left/Right). `entries`: [(tid, name,
    group, subtitle, icon)]."""

    def __init__(self, screen, width=600, height=660):
        self.screen = screen
        self._popup = PopupList(screen, width=width, height=height, own_keys=True)
        self._popup.key_hook = self._key
        self._popup.picked.connect(self._picked)
        self._popup.closed.connect(self._closed)
        self.chips = ChipBar(display=lambda f: f[0], focusable=False)
        self.chips.changed.connect(self._rebuild)
        self._popup.set_toolbar_widget(self.chips)
        self._entries, self._query, self._current = [], "", None
        self._filters, self._title = [], ""
        self._on_pick = None
        self._groups_order = []

    # ── state ──
    def is_open(self):
        return self._popup.isVisible()

    def close(self):
        self._popup.close_popup()

    def open_for(self, title, entries, current, anchor, on_pick, filters=None):
        self._entries, self._current, self._on_pick = list(entries), current, on_pick
        self._query, self._title = "", title
        self._filters = list(filters or [])
        self.chips.setVisible(bool(self._filters))
        self.chips.set_values(self._filters, 0)
        self._popup.size_to(min(len(self._entries) + 8, 14))
        self._rebuild()
        self._popup.open_at(anchor, self.screen)

    # ── rows ──
    def _visible(self):
        keep = self.chips.current()[1] if self._filters and self.chips.current() else (lambda t: True)
        return [e for e in self._entries if keep(e[0]) and (not self._query or search_match(self._query, e[1]))]

    def _rebuild(self, *_):
        self._popup.clear_rows()
        shown = self._visible()
        self._popup.set_title(f"{self._title}  ·  ⌕ {self._query}_" if self._query else
                              f"{self._title}  ·  type to search")
        if not shown:
            self._popup.add_row("NO TEAM MATCHES", None, disabled=True)
            return
        group = None
        index = 0
        for tid, name, grp, subtitle, icon in shown:
            if grp != group:
                group = grp
                self._popup.add_row(grp.upper(), None, disabled=True, subdued=True)
            if tid == self._current:
                index = len(self._popup._rows)
            self._popup.add_row(name, tid, subtitle=subtitle, icon=icon, selected=tid == self._current)
        self._popup.set_highlight(index)

    def _key(self, event):
        k = event.key()
        if k == Qt.Key_Left or k == Qt.Key_Right:
            if self._filters:
                self.chips.step(-1 if k == Qt.Key_Left else 1)
                return True
            return False
        if k == Qt.Key_Backspace and self._query:
            self._query = self._query[:-1]
            self._rebuild()
            return True
        if event.text() and event.text().isprintable() and (k != Qt.Key_Space or self._query):
            self._query += event.text()
            self._rebuild()
            return True
        return False

    def _picked(self, tid):
        if tid is not None and self._on_pick:
            self._on_pick(tid)

    def _closed(self):
        pass
