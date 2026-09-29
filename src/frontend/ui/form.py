"""
ui/form.py — editing controls for the data editors
=======================================================
The rest of the widget kit is for *choosing* things; these three are for
changing them.

Text editing is deliberately modal — CONFIRM (or a click) opens the field,
Enter commits, Escape reverts — rather than a QLineEdit that simply sits
there focused. FocusManager (app/input.py) navigates between the widgets a
screen registered with it, and reads QApplication.focusWidget() to know
where it is: a line edit holding Qt focus is not in that set, so every arrow
key would be swallowed as text or, worse, bounce focus back to the top of
the form. Handing focus to the editor only for the duration of an edit keeps
one model of "where am I" for pad, keyboard and mouse alike.
"""
from PyQt5.QtWidgets import QWidget, QLineEdit, QSizePolicy, QScrollArea, QVBoxLayout
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from PyQt5.QtCore import Qt, QRectF, pyqtSignal

from ui.broadcast import tracked_font, label_css, draw_frame
from ui.dropdown import OptionRow, _discard
from ui.theme import (
    BG_CARD, BG_RAISED, BG_HIGHLIGHT, BORDER, BORDER_EM, BLOCKED,
    LIST_BG, LIST_BORDER,
    ACCENT, WARN, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FG_MUTED, FONT_DISPLAY,
)


class TextRow(QWidget):
    """A labelled text value. Not editable until activated, then it is a real
    line edit until Enter or Escape."""

    changed = pyqtSignal(str)
    text_edited = pyqtSignal(str)     # every keystroke while editing — live filters
    edit_finished = pyqtSignal()

    def __init__(self, label, value="", placeholder="", parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(52)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._label = label
        self._value = str(value or "")
        self._placeholder = placeholder
        self._problem = ""

        self._edit = QLineEdit(self)
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: {BG_RAISED}; color: {FG_PRIMARY};"
            f" border: 1px solid {ACCENT}; padding: 2px 8px;"
            f" font-family: '{FONT_DISPLAY}'; font-size: 13pt; }}")
        self._edit.hide()
        self._edit.returnPressed.connect(self._commit)
        self._edit.textEdited.connect(self.text_edited.emit)
        self._edit.installEventFilter(self)

    def value(self):
        return self._value

    def set_value(self, value):
        self._value = str(value or "")
        self.update()

    def set_problem(self, message=""):
        """A validation message to show in place of the value's usual
        subtitle — set by the screen, not discovered here."""
        self._problem = message or ""
        self.update()

    def is_editing(self):
        return self._edit.isVisible()

    # ── edit lifecycle ───────────────────────────────────────────────────
    def begin_edit(self, start_text=None):
        """`start_text` replaces the value with what was just typed — typing
        on a focused row starts an edit with that character, the way a
        spreadsheet cell does."""
        self._edit.setGeometry(12, 22, self.width() - 24, 26)
        self._edit.show()
        self._edit.setFocus()
        if start_text is None:
            self._edit.setText(self._value)
            self._edit.selectAll()
        else:
            self._edit.setText(start_text)
            self._edit.end(False)
            self.text_edited.emit(start_text)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.is_editing():
            self._edit.setGeometry(12, 22, self.width() - 24, 26)

    def _commit(self):
        new = self._edit.text()
        self._end_edit()
        if new != self._value:
            self._value = new
            self.changed.emit(new)
        self.edit_finished.emit()

    def _cancel(self):
        self._end_edit()
        self.edit_finished.emit()

    def _end_edit(self):
        self._edit.hide()
        self.setFocus()
        self.update()

    def eventFilter(self, watched, event):
        if watched is self._edit and event.type() == event.KeyPress:
            if event.key() == Qt.Key_Escape:
                self._cancel()
                return True
        return False

    def focusOutEvent(self, event):
        # Clicking straight onto another control while editing commits, the
        # same as Enter — an abandoned edit that silently reverted would look
        # like the app dropped the typing.
        if self.is_editing() and not self._edit.hasFocus():
            self._commit()
        super().focusOutEvent(event)

    def mousePressEvent(self, event):
        self.setFocus()
        self.begin_edit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.begin_edit()
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        focused = self.hasFocus() or self.is_editing()
        p.fillRect(self.rect(), QColor(BG_HIGHLIGHT if focused else BG_CARD))
        draw_frame(p, self.rect(), ACCENT if focused else BORDER)
        if focused:
            p.fillRect(0, 0, 3, self.height(), QColor(ACCENT))

        # The label always names the field; a problem is a tag beside it, not
        # a replacement — otherwise the one row that needs fixing is the one
        # whose name you can no longer read.
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, track=1.6))
        label_w = self.width() - 24
        if self._problem:
            fm = p.fontMetrics()
            tag = fm.elidedText(self._problem, Qt.ElideRight, int(self.width() * 0.55))
            tag_w = fm.horizontalAdvance(tag)
            p.setPen(QColor(WARN))
            p.drawText(QRectF(self.width() - 12 - tag_w, 4, tag_w, 16),
                       Qt.AlignRight | Qt.AlignVCenter, tag)
            label_w -= tag_w + 12
        p.setPen(QColor(WARN if self._problem else FG_SECONDARY))
        label = p.fontMetrics().elidedText(self._label.upper(), Qt.ElideRight, int(label_w))
        p.drawText(QRectF(12, 4, label_w, 16), Qt.AlignLeft | Qt.AlignVCenter, label)

        if self.is_editing():
            return
        p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.DemiBold, track=0.4))
        if self._value:
            shown, colour = self._value, FG_PRIMARY
        else:
            # Unmistakably not a value: a dash, then the hint, in the
            # de-emphasised colour.
            shown = f"—  {self._placeholder}" if self._placeholder else "—"
            colour = FG_TERTIARY
        p.setPen(QColor(colour))
        elided = p.fontMetrics().elidedText(shown, Qt.ElideRight, self.width() - 26)
        p.drawText(QRectF(13, 22, self.width() - 26, 24), Qt.AlignLeft | Qt.AlignVCenter, elided)


class StatRow(QWidget):
    """One 0-99 rating: label, value, and a bar that doubles as the control.
    Left/Right step by 1, with Shift for 10; clicking the bar sets it
    outright, which is what makes re-rating a whole squad bearable."""

    changed = pyqtSignal(int)

    LO, HI = 0, 99

    def __init__(self, label, value=0, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._label = label
        self._value = self._clamp(value)
        self._problem = ""

    @staticmethod
    def _to_int(value):
        try:
            return int(str(value).strip() or 0)
        except (TypeError, ValueError):
            return 0

    def _clamp(self, value):
        return max(self.LO, min(self.HI, self._to_int(value)))

    def value(self):
        return self._value

    def set_value(self, value, notify=False):
        value = self._clamp(value)
        if value == self._value:
            return
        self._value = value
        self.update()
        if notify:
            self.changed.emit(value)

    def set_problem(self, message=""):
        """A validation message from the screen; None/"" clears it. The
        label column is too narrow to print it the way TextRow does, so it
        only tints (label + bar, matching TextRow's WARN severity) and
        surfaces the text as a tooltip."""
        self._problem = message or ""
        self.setToolTip(self._problem)
        self.update()

    def _bar_rect(self):
        return QRectF(126, self.height() / 2 - 3, self.width() - 126 - 46, 6)

    def _set_from_x(self, x):
        bar = self._bar_rect()
        if bar.width() > 0:
            ratio = max(0.0, min(1.0, (x - bar.x()) / bar.width()))
            self.set_value(round(self.LO + ratio * (self.HI - self.LO)), notify=True)

    def mousePressEvent(self, event):
        # Only the bar is a slider. A click on the label or the number just
        # focuses the row — it used to set the rating from the click's x,
        # which made "click the label" mean "set to 0".
        self.setFocus()
        self._dragging = self._bar_rect().adjusted(-4, -10, 4, 10).contains(event.pos())
        if self._dragging:
            self._set_from_x(event.x())

    def mouseMoveEvent(self, event):
        if event.buttons() & Qt.LeftButton and getattr(self, "_dragging", False):
            self._set_from_x(event.x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def keyPressEvent(self, event):
        step = 10 if event.modifiers() & Qt.ShiftModifier else 1
        if event.key() == Qt.Key_Left:
            self.set_value(self._value - step, notify=True)
            event.accept()
            return
        if event.key() == Qt.Key_Right:
            self.set_value(self._value + step, notify=True)
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        focused = self.hasFocus()
        if focused:
            p.fillRect(self.rect(), QColor(BG_HIGHLIGHT))
            p.fillRect(0, 0, 3, self.height(), QColor(ACCENT))

        tint = WARN if self._problem else (ACCENT if focused else FG_SECONDARY)
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, track=1.2))
        p.setPen(QColor(tint))
        p.drawText(QRectF(12, 0, 110, self.height()), Qt.AlignLeft | Qt.AlignVCenter,
                   self._label.upper())

        bar = self._bar_rect()
        p.fillRect(bar, QColor(BG_RAISED))
        filled = QRectF(bar.x(), bar.y(), bar.width() * self._value / self.HI, bar.height())
        p.fillRect(filled, QColor(tint))

        p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, track=0))
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(self.width() - 42, 0, 32, self.height()),
                   Qt.AlignRight | Qt.AlignVCenter, str(self._value))


class SearchList(QWidget):
    """A filterable list panel: type to narrow, arrow through what's left.

    Two distinct states, unlike PopupList's one. The HIGHLIGHT is a cursor:
    the mouse moves it by hovering, arrows move it, and it commits to
    nothing. The SELECTION is what the screen is actually working on, and
    only a click or CONFIRM changes it. A popup can conflate the two because
    it closes on the way out; a panel that loads a record cannot — sweeping
    the pointer across it would otherwise open thirty players in a row and
    throw away edits on the way past."""

    highlighted = pyqtSignal(object)     # cursor moved — no commitment
    activated = pyqtSignal(object)       # clicked or confirmed — a real pick

    def __init__(self, placeholder="search", parent=None, show_filter=True):
        super().__init__(parent)
        # The list itself is the focus stop, not its filter box: CONFIRM here
        # means "open the row I'm on". The filter is opened deliberately
        # (a click, or the screen's filter key) so that A never lands you in
        # a text field when you meant to pick something.
        self.setFocusPolicy(Qt.StrongFocus)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)

        # A short, fixed vocabulary (e.g. a player's seasons) never needs
        # narrowing down — the filter box would just be dead chrome above it.
        self.search = TextRow("filter", placeholder=placeholder) if show_filter else None
        if self.search is not None:
            # Narrow as you type, not on Enter — a filter you can't see
            # working until you commit it reads as broken.
            self.search.text_edited.connect(self._on_filter_changed)
            self.search.changed.connect(self._on_filter_changed)
            self.search.edit_finished.connect(self._on_filter_finished)
            v.addWidget(self.search)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setStyleSheet(f"background: {LIST_BG}; border: 1px solid {LIST_BORDER};")
        self.scroll.viewport().setStyleSheet(f"background: {LIST_BG};")
        self._holder = QWidget()
        self._holder.setStyleSheet(f"background: {LIST_BG};")
        self._holder_v = QVBoxLayout(self._holder)
        self._holder_v.setContentsMargins(0, 0, 0, 0)
        self._holder_v.setSpacing(1)
        self._holder_v.addStretch(1)
        self.scroll.setWidget(self._holder)
        v.addWidget(self.scroll, stretch=1)

        self._items = []        # [(data, text, tag, tag_color, subdued)]
        self._all_rows = []     # one OptionRow per item, built once per set_items
        self._rows = []         # the rows the filter currently lets through
        self._hi = -1
        self._selected = None
        self._filter = ""
        self._search_keys = []  # extra text matched by the filter, per item

    # ── content ──────────────────────────────────────────────────────────
    def set_items(self, items, keep_data=None, search_text=None):
        """`items`: [(data, text, tag, tag_color, subdued)]. `keep_data`
        re-highlights that entry after the rebuild when it survived the
        filter — so editing a name doesn't throw you back to the top.
        `search_text`: optional per-item strings the filter also matches
        (an id, a team, a position) beyond the visible text."""
        self._items = list(items)
        self._search_keys = [
            (it[1] + " " + (search_text[i] if search_text else "")).lower()
            for i, it in enumerate(self._items)]
        self._rebuild(keep_data if keep_data is not None else self.highlighted_data())

    def _on_filter_changed(self, text):
        self._filter = text.strip().lower()
        self._apply_filter(self.highlighted_data())

    def _on_filter_finished(self):
        # Hand the keyboard back to the rows, so Enter-then-Down browses what
        # the filter left.
        self.setFocus()

    def _rebuild(self, keep_data=None):
        while self._holder_v.count() > 1:
            item = self._holder_v.takeAt(0)
            if item.widget():
                _discard(item.widget())
        self._all_rows = []
        for data, text, tag, tag_color, subdued in self._items:
            row = OptionRow(text, data, tag=tag, tag_color=tag_color, subdued=subdued,
                            selected=(data == self._selected), list_style=True)
            row.entered.connect(lambda r=row: self._on_row_entered(r))
            row.picked.connect(self._on_row_picked)
            self._holder_v.insertWidget(self._holder_v.count() - 1, row)
            self._all_rows.append(row)
        self._apply_filter(keep_data)

    def _apply_filter(self, keep_data=None):
        """Hide rather than rebuild: filtering 351 players on every keystroke
        must not re-create 351 widgets each time."""
        needle = self._filter
        if 0 <= self._hi < len(self._rows):
            self._rows[self._hi].set_highlighted(False)
        self._rows = []
        self._hi = -1
        for row, key in zip(self._all_rows, self._search_keys):
            show = not needle or needle in key
            row.setVisible(show)
            if show:
                self._rows.append(row)
        if self._rows:
            target = next((i for i, r in enumerate(self._rows) if r.data == keep_data), 0)
            self.set_highlight(target)

    def _on_row_entered(self, row):
        if row in self._rows:
            self.set_highlight(self._rows.index(row), scroll=False)

    # ── highlight ────────────────────────────────────────────────────────
    def highlighted_data(self):
        return self._rows[self._hi].data if 0 <= self._hi < len(self._rows) else None

    def set_highlight(self, i, scroll=True):
        if not (0 <= i < len(self._rows)):
            return False
        if 0 <= self._hi < len(self._rows):
            self._rows[self._hi].set_highlighted(False)
        self._hi = i
        row = self._rows[i]
        row.set_highlighted(True)
        if scroll:
            self.scroll.ensureWidgetVisible(row, 0, OptionRow.ROW_H)
        self.highlighted.emit(row.data)
        return True

    def move_highlight(self, delta):
        if not self._rows:
            return False
        return self.set_highlight(max(0, min(self._hi + delta, len(self._rows) - 1)))

    def page_highlight(self, sign):
        rows = max(1, self.scroll.viewport().height() // (OptionRow.ROW_H + 1))
        return self.move_highlight(sign * rows)

    def select_data(self, data):
        target = next((i for i, r in enumerate(self._rows) if r.data == data), None)
        return self.set_highlight(target) if target is not None else False

    # ── selection ────────────────────────────────────────────────────────
    def selected_data(self):
        return self._selected

    def set_selected(self, data, scroll=False):
        """Mark `data` as the row the screen is working on. Independent of
        the cursor, so the pointer can wander without changing it."""
        self._selected = data
        for row in self._all_rows:
            row.set_selected(row.data == data)
        if scroll:
            self.select_data(data)

    def _on_row_picked(self, data):
        self.set_selected(data)
        self.activated.emit(data)

    def activate(self):
        data = self.highlighted_data()
        if data is not None:
            self.set_selected(data)
            self.activated.emit(data)
        return data is not None

    def count(self):
        return len(self._rows)

    def begin_filter(self, start_text=None):
        if self.search is not None:
            self.search.setFocus()
            self.search.begin_edit(start_text)

    def filter_text(self):
        return self._filter

    def clear_filter(self):
        if self.search is not None:
            self.search.set_value("")
        self._on_filter_changed("")

    def keyPressEvent(self, event):
        """The list owns its own browsing keys, so any screen gets the same
        behaviour without re-implementing it. Left/Right are deliberately
        NOT consumed: they leave the list for whatever is beside it."""
        k = event.key()
        if k == Qt.Key_Up:
            self.move_highlight(-1)
        elif k == Qt.Key_Down:
            self.move_highlight(1)
        elif k == Qt.Key_PageUp:
            self.page_highlight(-1)
        elif k == Qt.Key_PageDown:
            self.page_highlight(1)
        elif k == Qt.Key_Home:
            self.set_highlight(0)
        elif k == Qt.Key_End:
            self.set_highlight(len(self._rows) - 1)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            self.activate()
        elif k == Qt.Key_Slash or (k == Qt.Key_F and event.modifiers() & Qt.ControlModifier):
            self.begin_filter()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def paintEvent(self, event):
        """A focus ring, because the list is a focus stop but paints nothing
        of its own — its rows carry the cursor, and without this there is no
        way to tell the list has the keyboard."""
        if not self.hasFocus():
            return
        p = QPainter(self)
        draw_frame(p, self.rect(), ACCENT)
