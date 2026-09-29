"""
ui/dropdown.py — shared clean dropdown/popup-list primitives
==================================================================
One popup design used everywhere a screen needs to offer a list of choices
anchored to a control: stadium selection (DropdownRow) and the squad
editor's player picker. Fixed size, always — a popup that grows and
shrinks with its content jumps around the screen and fights whatever's
under it; this scrolls instead.
"""
from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QScrollArea, QApplication, QSizePolicy,
)
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QPolygonF
from PyQt5.QtCore import Qt, QPoint, QRectF, QEvent, pyqtSignal

from ui.broadcast import tracked_font, eyebrow_label, draw_frame
from ui.theme import (
    DROPDOWN_BG, DROPDOWN_BORDER, DROPDOWN_FOCUS, DROPDOWN_ROW,
    DROPDOWN_DISABLED_BG, DROPDOWN_TEXT, DROPDOWN_SUBDUED_TEXT,
    DROPDOWN_DISABLED_TEXT, DROPDOWN_FOCUS_TEXT, DROPDOWN_TAG,
    DROPDOWN_SUBTITLE, DROPDOWN_FOCUS_RAIL, DROPDOWN_SUBDUED_RAIL,
    DROPDOWN_LABEL, DROPDOWN_VALUE, DROPDOWN_ARROW, DROPDOWN_TITLE,
    LIST_BG, LIST_ROW, LIST_SELECTED, LIST_HOVER, LIST_BORDER,
    LIST_TEXT, LIST_SUBDUED_TEXT,
    LIST_TAG, LIST_SUBTITLE,
    BORDER, FONT_DISPLAY,
    BG_RAISED, BG_HIGHLIGHT, ACCENT, FG_PRIMARY, FG_SECONDARY, FG_MUTED,
)


def _is_deleted(widget):
    """True once the underlying C++ object is gone (the anchor a popup was
    opened against can outlive the popup itself only briefly, but a rebuild
    elsewhere in the screen can still beat it to deletion). Duplicated from
    app/input.py's helper of the same name rather than imported — this
    module doesn't depend on app/, see the class docstring above."""
    try:
        from PyQt5 import sip
    except ImportError:          # pragma: no cover — very old PyQt5
        import sip
    return sip.isdeleted(widget)


def _discard(widget):
    """Take a widget out of the UI *now*. deleteLater() only queues the
    delete, so a widget merely removed from its layout keeps painting at its
    old geometry until the event loop gets round to it — which showed up as
    the previous team's kit fields sitting on top of the new one's."""
    widget.setParent(None)
    widget.deleteLater()


# Gap the layout leaves between rows — with BG_PANEL behind BG_RAISED rows
# (see PopupList/OptionRow) this reads as a real divider, but only if it's
# wide enough to survive a remote display's compression; 1px vanished.
ROW_SPACING = 2


class OptionRow(QWidget):
    """One selectable line in a popup list: label, optional right-aligned
    tag ("CURRENT", "#4", a stadium's country...), plus three independent
    visual states.

      selected  — this row is what the slot already holds
      highlighted — the list cursor is on it, whether it got there by mouse
                  or by d-pad. There is exactly ONE highlight per list and
                  the owning PopupList owns it; the row never sets it from
                  its own mouse events, it only reports being entered.
      subdued   — listed, but not a natural choice here (the squad picker
                  passes this for players out of position). Drawn as a rail
                  down the right edge so it costs the name no width and the
                  misfits form one scannable column.
    """

    entered = pyqtSignal()
    picked = pyqtSignal(object)

    ROW_H = 34

    def __init__(self, text, data, tag="", tag_color=None, disabled=False,
                 selected=False, subdued=False, parent=None, icon=None, subtitle="",
                 list_style=False):
        super().__init__(parent)
        self.setFixedHeight(self.ROW_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.text, self.data, self.tag = text, data, tag
        self.tag_color = tag_color
        self.disabled = disabled
        self.selected = selected
        self.subdued = subdued
        self.highlighted = False
        self.icon = icon            # optional QPixmap drawn at the left (thumbnails)
        self.subtitle = subtitle    # optional secondary text after the name
        self.list_style = list_style

    def set_highlighted(self, on):
        if on != self.highlighted:
            self.highlighted = on
            self.update()

    def set_selected(self, on):
        if on != self.selected:
            self.selected = on
            self.update()

    def enterEvent(self, event):
        # Report only — PopupList decides what the highlight becomes, so a
        # mouse and a d-pad drive the same single piece of state.
        if not self.disabled:
            self.entered.emit()

    # No leaveEvent: the highlight moves, it never clears. Sliding the mouse
    # off the list must not blank the cursor a pad user is about to move.

    def mousePressEvent(self, event):
        if not self.disabled:
            self.picked.emit(self.data)

    def paintEvent(self, event):
        p = QPainter(self)
        # Always an opaque fill — never leave the row see-through to
        # whatever else is stacked behind the popup. BG_RAISED (not
        # BG_CARD) so each row reads as a distinct block against the
        # popup's BG_PANEL backdrop, not just more of the same flat fill.
        # Disabled (= "this is what's already picked, here for reference,
        # not clickable") sinks back to BG_PANEL instead — before, it was
        # the exact same bright fill as every pickable row, told apart only
        # by slightly dimmer text, so the one row you can't pick looked
        # identical to the ones you can.
        row_bg = ((LIST_BG if self.list_style else DROPDOWN_DISABLED_BG) if self.disabled else
              (LIST_ROW if self.list_style else DROPDOWN_ROW))
        p.fillRect(self.rect(), QColor(row_bg))
        lit = self.highlighted or self.selected
        if lit:
            if self.list_style:
                fill = LIST_SELECTED if self.selected else LIST_HOVER
            else:
                fill = DROPDOWN_FOCUS
            p.fillRect(self.rect(), QColor(fill))
            p.fillRect(0, 0, 3, self.height(), QColor(LIST_BORDER if self.list_style else DROPDOWN_FOCUS_RAIL))
        if self.subdued:
            p.fillRect(self.width() - 2, 0, 2, self.height(), QColor(DROPDOWN_SUBDUED_RAIL))

        if self.disabled:
            text_col = DROPDOWN_DISABLED_TEXT
        elif lit:
            text_col = (LIST_SUBDUED_TEXT if self.list_style else DROPDOWN_SUBDUED_TEXT) if self.subdued else (LIST_TEXT if self.list_style else DROPDOWN_FOCUS_TEXT)
        else:
            text_col = (LIST_SUBDUED_TEXT if self.list_style else DROPDOWN_SUBDUED_TEXT) if self.subdued else (LIST_TEXT if self.list_style else DROPDOWN_TEXT)

        x0 = 14
        if self.icon is not None and not self.icon.isNull():
            ih = self.ROW_H - 8
            scaled = self.icon.scaled(ih * 2, ih, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(10, (self.ROW_H - scaled.height()) // 2, scaled)
            x0 = 10 + ih * 2 + 8 if scaled.width() > ih else 10 + ih + 8
        avail = self.width() - x0 - 12
        if self.tag:
            p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, track=1.0))
            tag_w = p.fontMetrics().horizontalAdvance(self.tag) + 4
            p.setPen(QColor(self.tag_color or (LIST_TAG if self.list_style else DROPDOWN_TAG)))
            p.drawText(self.rect().adjusted(0, 0, -14, 0), Qt.AlignRight | Qt.AlignVCenter, self.tag)
            avail -= tag_w + 8
        p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.DemiBold, track=0.4))
        p.setPen(QColor(text_col))
        elided = p.fontMetrics().elidedText(self.text, Qt.ElideRight, int(avail))
        p.drawText(self.rect().adjusted(x0, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter, elided)
        if self.subtitle:
            used = p.fontMetrics().horizontalAdvance(elided) + 10
            if used < avail:
                p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, track=0.6))
                p.setPen(QColor(LIST_SUBTITLE if self.list_style else DROPDOWN_SUBTITLE))
                sub = p.fontMetrics().elidedText(self.subtitle, Qt.ElideRight, int(avail - used))
                p.drawText(self.rect().adjusted(x0 + used, 0, 0, 0),
                           Qt.AlignLeft | Qt.AlignVCenter, sub)


class PopupList(QWidget):
    """The popup itself: a title, an optional toolbar slot and a scrollable
    row list, at a size that is fixed for as long as it is open — content
    that doesn't fit scrolls. `size_to()` sets that height from a row count
    before opening; callers whose content changes while open (a filter, a
    view switch) must size to the largest view, so the box never moves under
    the cursor.

    Owns THE highlight: one index into its rows, moved either by the mouse
    entering a row or by whatever the owning screen routes in from the
    action layer (move_highlight / page_highlight / activate_highlight).
    Both paths land in set_highlight, so there is a single definition of
    "the row the list is on", and `hovered` is emitted from there — which is
    what lets a preview panel follow a d-pad exactly as it follows a mouse.

    The keys themselves are mapped by the screen, not here: ui/ has no
    dependency on app/, and only the screen knows what else is on screen."""

    picked = pyqtSignal(object)
    hovered = pyqtSignal(object)
    closed = pyqtSignal()

    # Popups that are open right now, innermost last. Only the top one may
    # take keys, so a popup opened from inside another never fights it.
    _open_stack = []

    def __init__(self, parent=None, width=280, height=340, own_keys=False,
                 show_title=True, list_bg=None):
        super().__init__(parent)
        # own_keys: the popup routes the keyboard itself (arrows, paging,
        # Enter, Esc, type-ahead) instead of relying on the owning screen.
        # Popups opened by a self-contained control (SelectorRow, DropdownRow)
        # need this — no screen knows they are open, so keys used to land on
        # the form behind them.
        self._own_keys = own_keys
        self._typeahead = ""
        self._typeahead_t = 0.0
        self.setObjectName("popupList")
        # list_bg lets a caller (DropdownRow/SelectorRow) tint the whole
        # popup — chrome, gutters and all — the same colour a row lights up
        # with when picked, so the open list reads as one clearly-lit block
        # instead of a dark box with a dark row inside it. Other PopupList
        # callers (squad editor menus etc.) keep the plain BG_PANEL look.
        bg = list_bg or DROPDOWN_BG
        # A plain QWidget subclass ignores a stylesheet background unless it
        # is told to paint one, and the rows/scroll area below fill only
        # their own rects — without this the title and toolbar band stayed
        # transparent and whatever the popup was covering showed through it.
        self.setAttribute(Qt.WA_StyledBackground, True)
        # No border here — the list below (self.scroll) already draws its
        # own clear border; a second one 4-10px outside it just doubled up
        # into a cluttered two-line edge instead of one clean frame.
        self.setStyleSheet(f"QWidget#popupList {{ background: {bg}; border: none; }}")
        self.setFixedWidth(width)
        # 92 for title/toolbar/margins, +10 for the list's own border wrap
        # (list_wrap's 10px bottom margin, added below — no top margin left
        # to account for once there's no title).
        self._max_list_h = height - (106 if show_title else 78)
        self.setFixedHeight(height)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 10 if show_title else 0, 0, 0)
        v.setSpacing(6)

        self.title_lbl = None
        if show_title:
            self.title_lbl = eyebrow_label("", color=DROPDOWN_TITLE, size=12)
            self.title_lbl.setContentsMargins(14, 0, 14, 0)
            v.addWidget(self.title_lbl)

        self._toolbar_v = QVBoxLayout()
        self._toolbar_v.setContentsMargins(10, 0, 10, 0)
        v.addLayout(self._toolbar_v)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        # Opaque throughout — the viewport is a separate child widget and
        # doesn't inherit an instance stylesheet set on the QScrollArea, so
        # it needs its own fill or it shows through to whatever is stacked
        # behind the popup. Always BG_PANEL here, even when list_bg is set —
        # list_bg only tints the popup's own background (the halo just
        # outside this box, showing through list_wrap's margin below), not
        # the inside of the list: painting every row-to-row gap in that
        # colour turned each one into its own thin coloured line, everywhere,
        # not just as the current-item highlight.
        # BORDER boxes the row list on its own — the popup itself is
        # borderless (see above), so this is the one edge the whole thing has.
        self.scroll.setStyleSheet(f"background: {DROPDOWN_BG}; border: 2px solid {DROPDOWN_BORDER};")
        self.scroll.viewport().setStyleSheet(f"background: {DROPDOWN_BG};")
        self._holder = QWidget()
        self._holder.setStyleSheet(f"background: {DROPDOWN_BG};")
        self._holder_v = QVBoxLayout(self._holder)
        self._holder_v.setContentsMargins(0, 0, 0, 0)
        self._holder_v.setSpacing(ROW_SPACING)
        self._holder_v.addStretch(1)
        self.scroll.setWidget(self._holder)
        list_wrap = QVBoxLayout()
        # No top margin — that halo strip sat right above the list's own
        # border with nothing between it and the toolbar/top edge, reading
        # as a stray red sliver rather than a frame.
        list_wrap.setContentsMargins(10, 0, 10, 10)
        list_wrap.addWidget(self.scroll)
        v.addLayout(list_wrap, stretch=1)

        self._rows = []
        self._hi = -1
        self._anchor = None

        self.hide()

    def set_title(self, text):
        if self.title_lbl is not None:
            self.title_lbl.setText(text.upper())

    def size_to(self, row_count):
        """Height for `row_count` rows, capped at the height passed to the
        constructor. Call before open_at, with the biggest row count the
        popup can show while it stays open."""
        rows_h = max(1, row_count) * (OptionRow.ROW_H + ROW_SPACING)
        self.scroll.setFixedHeight(min(self._max_list_h, rows_h))
        self.setFixedHeight(self.layout().totalSizeHint().height())

    def set_toolbar_widget(self, widget):
        while self._toolbar_v.count():
            item = self._toolbar_v.takeAt(0)
            if item.widget():
                _discard(item.widget())
        if widget is not None:
            self._toolbar_v.addWidget(widget)

    def clear_rows(self):
        while self._holder_v.count() > 1:   # keep the trailing stretch
            item = self._holder_v.takeAt(0)
            if item.widget():
                _discard(item.widget())
        self._rows = []
        self._hi = -1

    def add_row(self, text, data, tag="", tag_color=None, disabled=False,
                selected=False, subdued=False, icon=None, subtitle=""):
        row = OptionRow(text, data, tag=tag, tag_color=tag_color, disabled=disabled,
                        selected=selected, subdued=subdued, icon=icon, subtitle=subtitle)
        index = len(self._rows)
        # scroll=False: the mouse is already on the row, and scrolling the
        # list under a moving cursor makes it chase itself.
        row.entered.connect(lambda i=index: self.set_highlight(i, scroll=False))
        row.picked.connect(self._on_row_picked)
        self._holder_v.insertWidget(self._holder_v.count() - 1, row)
        self._rows.append(row)
        return row

    # ── the highlight ────────────────────────────────────────────────────
    def highlighted_index(self):
        return self._hi

    def highlighted_data(self):
        return self._rows[self._hi].data if 0 <= self._hi < len(self._rows) else None

    def set_highlight(self, i, scroll=True):
        if not (0 <= i < len(self._rows)) or self._rows[i].disabled:
            return False
        if 0 <= self._hi < len(self._rows):
            self._rows[self._hi].set_highlighted(False)
        self._hi = i
        row = self._rows[i]
        row.set_highlighted(True)
        if scroll:
            self.scroll.ensureWidgetVisible(row, 0, OptionRow.ROW_H)
        self.hovered.emit(row.data)
        return True

    def move_highlight(self, delta):
        """Clamped, never wrapping — a list that jumps from bottom to top
        loses a pad user completely. Skips disabled rows."""
        if not self._rows:
            return False
        step = 1 if delta > 0 else -1
        i = self._hi if self._hi >= 0 else (-1 if step > 0 else len(self._rows))
        remaining = abs(delta)
        landed = self._hi
        while remaining:
            i += step
            if not (0 <= i < len(self._rows)):
                break
            if self._rows[i].disabled:
                continue
            landed = i
            remaining -= 1
        return self.set_highlight(landed) if landed != self._hi else False

    def rows_per_page(self):
        return max(1, self.scroll.viewport().height() // (OptionRow.ROW_H + ROW_SPACING))

    def page_highlight(self, sign):
        return self.move_highlight(sign * self.rows_per_page())

    def activate_highlight(self):
        data = self.highlighted_data()
        if data is None:
            return False
        self._on_row_picked(data)
        return True

    def _on_row_picked(self, data):
        # Emit BEFORE closing: `closed` is how an owner tears down the state
        # describing what this popup was opened for, and that state is
        # exactly what a `picked` handler needs to apply the pick.
        self.picked.emit(data)
        self.close_popup()

    def open_at(self, anchor: QWidget, screen: QWidget, gap: int = 4, own_toggle: bool = False):
        """own_toggle=True: a click back on `anchor` while this popup is open
        does NOT auto-close it here — the anchor is expected to do that
        itself (see DropdownRow._toggle_popup et al.), which is what lets a
        second click on the same button close its own popup instead of the
        click landing here first, closing it, and then still reaching the
        anchor's own always-open handler and reopening a new one. Off by
        default: every caller that doesn't opt in keeps today's plain
        "any outside click closes it" behaviour unchanged."""
        self._anchor = anchor if own_toggle else None
        pos = anchor.mapTo(screen, QPoint(0, anchor.height() + gap))
        x = max(8, min(pos.x(), screen.width() - self.width() - 8))
        y = max(8, min(pos.y(), screen.height() - self.height() - 8))
        if self.parentWidget() is not screen:
            self.setParent(screen)
        self.move(x, y)
        self.show()
        self.raise_()
        if self not in PopupList._open_stack:
            PopupList._open_stack.append(self)
        QApplication.instance().installEventFilter(self)

    def close_popup(self):
        self.hide()

    def hideEvent(self, event):
        QApplication.instance().removeEventFilter(self)
        if self in PopupList._open_stack:
            PopupList._open_stack.remove(self)
        super().hideEvent(event)
        self.closed.emit()

    @classmethod
    def any_open(cls):
        return any(p.isVisible() for p in cls._open_stack)

    def eventFilter(self, watched, event):
        if event.type() == QEvent.MouseButtonPress:
            if self.rect().contains(self.mapFromGlobal(event.globalPos())):
                return False
            # A click back on the button that opened this popup is NOT
            # "outside" in the close-it sense — it's the toggle. Leaving it
            # alone here and letting that click reach the anchor's own
            # mousePressEvent is what lets the anchor close it on a second
            # click; auto-closing it here too raced the anchor's own
            # handler (this ran first, closed it, then the click still
            # landed on the anchor and reopened a fresh one — so a second
            # click looked like it did nothing).
            anchor = self._anchor
            if (anchor is not None and not _is_deleted(anchor)
                    and anchor.rect().contains(anchor.mapFromGlobal(event.globalPos()))):
                return False
            self.close_popup()
        elif (event.type() == QEvent.KeyPress and self._own_keys and self.isVisible()
              and PopupList._open_stack and PopupList._open_stack[-1] is self):
            return self._handle_key(event)
        return False

    def _handle_key(self, event):
        import time
        k = event.key()
        toolbar = self._toolbar_v.itemAt(0).widget() if self._toolbar_v.count() else None
        if k == Qt.Key_Up:
            self.move_highlight(-1)
        elif k == Qt.Key_Down:
            self.move_highlight(1)
        elif k == Qt.Key_PageUp:
            self.page_highlight(-1)
        elif k == Qt.Key_PageDown:
            self.page_highlight(1)
        elif k == Qt.Key_Home:
            self.set_highlight(next((i for i, r in enumerate(self._rows) if not r.disabled), 0))
        elif k == Qt.Key_End:
            self.set_highlight(max((i for i, r in enumerate(self._rows) if not r.disabled),
                                   default=0))
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activate_highlight()
        elif k in (Qt.Key_Escape, Qt.Key_Backspace):
            self.close_popup()
        elif k in (Qt.Key_Left, Qt.Key_Right):
            if toolbar is not None and hasattr(toolbar, "set_index") and hasattr(toolbar, "index"):
                toolbar.set_index(toolbar.index() + (-1 if k == Qt.Key_Left else 1))
        elif event.text() and event.text().isprintable():
            # Type-ahead: jump to the first row starting with what was typed
            # in quick succession ("sec" → Second row).
            now = time.monotonic()
            if now - self._typeahead_t > 0.9:
                self._typeahead = ""
            self._typeahead_t = now
            self._typeahead += event.text().lower()
            needle = self._typeahead
            match = next((i for i, r in enumerate(self._rows)
                          if not r.disabled and r.text.lower().startswith(needle)), None)
            if match is None:
                match = next((i for i, r in enumerate(self._rows)
                              if not r.disabled and needle in r.text.lower()), None)
            if match is not None:
                self.set_highlight(match)
        else:
            return False
        return True


class DropdownRow(QWidget):
    """A field that looks like the other pickers but opens a scrollable
    PopupList instead of cycling with arrows — for lists too long to click
    through one at a time (stadiums)."""

    changed = pyqtSignal()

    def __init__(self, label, values=None, display=str, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(64)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._label = label
        self._values = list(values) if values else []
        self._display = display
        self._index = 0
        self._popup = None
        self._popup_open = False

    def set_values(self, values, index=0):
        self._values = list(values)
        self._index = max(0, min(index, len(self._values) - 1)) if self._values else 0
        self.update()

    def current(self):
        return self._values[self._index] if self._values else None

    def set_index(self, i):
        if self._values:
            self._index = max(0, min(i, len(self._values) - 1))
            self.update()

    def mousePressEvent(self, event):
        # No setFocus() — a mouse click opens the popup without also
        # pulling keyboard/pad focus onto the field itself (that's still
        # how arrow-key/pad navigation lands on it, via FocusManager).
        self._toggle_popup()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._toggle_popup()
            event.accept()
            return
        super().keyPressEvent(event)

    def _toggle_popup(self):
        # Already open (from an earlier click on this very field) —
        # closing it is the natural thing a second click on the same
        # button does; opening a second one on top would just be a bigger
        # version of the same list. See PopupList.eventFilter for why the
        # popup's own outside-click auto-close can't be relied on alone to
        # produce this: it doesn't fire for a click back on the anchor.
        if self._popup is not None and self._popup.isVisible():
            self._popup.close_popup()
            return
        self._open_popup()

    def _open_popup(self):
        if not self._values:
            return
        screen = self.window()
        # No title — the label above the field already says what this is;
        # list_bg ties the list's own colour to the picked-row highlight so
        # the whole open list reads as one lit block.
        # height=360 is only the CAP passed to the constructor — size_to()
        # below is what actually sizes the box to the real row count, so a
        # short list (a handful of stadiums) doesn't open as a mostly-empty
        # 360px box with a couple of rows floating at the top of it.
        popup = PopupList(screen, width=max(260, self.width()), height=360, own_keys=True,
                   show_title=False)
        current = self.current()
        current_i = None
        # selected, not disabled — the current value is still a normal,
        # pickable row in the list, just marked; it used to be greyed out
        # and unclickable, which read as "removed from the list" rather
        # than "this is where you are".
        for i, v in enumerate(self._values):
            popup.add_row(self._display(v).upper(), v, selected=(v == current))
            if v == current:
                current_i = i
        popup.size_to(len(self._values))
        popup.picked.connect(self._on_picked)
        popup.closed.connect(self._on_popup_closed)
        popup.open_at(self, screen, gap=0, own_toggle=True)
        if current_i is not None:
            # After open_at, not before — the scroll area has no usable
            # geometry to scroll within until the popup is actually shown.
            popup.set_highlight(current_i, scroll=True)
        self._popup = popup
        self._popup_open = True
        self.update()

    def _on_popup_closed(self):
        self._popup_open = False
        self.update()

    def _on_picked(self, value):
        try:
            self._index = self._values.index(value)
        except ValueError:
            return
        self.update()
        self.changed.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        w, h = self.width(), self.height()
        focused = self.hasFocus()

        # BG_RAISED at rest (not BG_CARD) — this control sits on a Card
        # that's filled with BG_CARD itself, so a BG_CARD fill here was
        # completely invisible except for its near-black border.
        # Same green palette as SelectorRow — only the open state goes blue.
        p.fillRect(self.rect(), QColor(DROPDOWN_BG if self._popup_open else
                                       (BG_HIGHLIGHT if focused else BG_RAISED)))
        draw_frame(p, self.rect(), DROPDOWN_BORDER if self._popup_open else BORDER, 2)
        if focused:
            p.fillRect(0, 0, 3, h, QColor(ACCENT))

        p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.DemiBold, track=1.6))
        p.setPen(QColor(FG_SECONDARY))
        p.drawText(QRectF(14, 6, w - 100, 18), Qt.AlignLeft | Qt.AlignVCenter, self._label.upper())

        val_col = ACCENT if focused else FG_PRIMARY
        # Same font and centred box as SelectorRow's value.
        p.setFont(tracked_font(FONT_DISPLAY, 19, QFont.Bold, track=0.6))
        p.setPen(QColor(val_col))
        text = self._display(self.current()).upper() if self._values else "—"
        val_rect = QRectF(28, h * 0.30, w - 56, h * 0.62)
        elided = p.fontMetrics().elidedText(text, Qt.ElideRight, int(val_rect.width()))
        p.drawText(val_rect, Qt.AlignCenter, elided)

        # chevron — a dropdown opens a list, it doesn't cycle, so no arrows
        chev_col = ACCENT if focused else FG_MUTED
        cx, cy = w - 22, h * 0.6
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(chev_col))
        p.drawPolygon(QPolygonF([QPoint(int(cx - 6), int(cy - 3)),
                                 QPoint(int(cx + 6), int(cy - 3)),
                                 QPoint(int(cx), int(cy + 5))]))
