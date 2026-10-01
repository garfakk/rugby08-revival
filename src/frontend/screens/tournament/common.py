"""screens/tournament/common.py — widgets the tournament screens share."""
from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtGui import QColor
from PyQt5.QtWidgets import (QAbstractItemView, QHeaderView, QTableWidget, QTableWidgetItem,
                             QVBoxLayout, QWidget)

from app.input import KEYMAP, Action
from ui.broadcast import eyebrow_label
from ui.theme import (ACCENT, BG_BASE, BG_PANEL, BORDER, FG_PRIMARY, FG_SECONDARY, T_LABEL)


class DataTable(QTableWidget):
    """Read-only grid. set_rows([[cell, ...]], colors={row: color},
    bold={row}). Cells may be (text, color) tuples. Enter / double-click
    emits activated_row; the row's `keys[i]` is what callers usually want."""
    activated_row = pyqtSignal(int)

    def __init__(self, columns, stretch_col=1, parent=None):
        super().__init__(0, len(columns), parent)
        self.keys = []
        self.setHorizontalHeaderLabels(columns)
        self.verticalHeader().hide()
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setAlternatingRowColors(True)
        self.setWordWrap(False)
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        for i in range(len(columns)):
            header.setSectionResizeMode(i, QHeaderView.Stretch if i == stretch_col
                                        else QHeaderView.ResizeToContents)
        self.setStyleSheet(
            f"QTableWidget {{ background: {BG_PANEL}; alternate-background-color: {BG_BASE};"
            f" color: {FG_PRIMARY}; border: 1px solid {BORDER}; font-size: {T_LABEL}pt; }}"
            f"QTableWidget::item {{ padding: 2px 6px; }}"
            f"QTableWidget::item:selected {{ background: {ACCENT}; color: white; }}"
            f"QHeaderView::section {{ background: {BG_BASE}; color: {FG_SECONDARY};"
            f" border: none; border-bottom: 1px solid {BORDER}; padding: 6px; }}")
        self.doubleClicked.connect(lambda idx: self.activated_row.emit(idx.row()))

    def set_rows(self, rows, keys=None, colors=None, bold=(), align_right_from=None):
        keep = self.current_key()
        self.keys = list(keys) if keys is not None else list(range(len(rows)))
        colors = colors or {}
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, cell in enumerate(row):
                text, color = cell if isinstance(cell, tuple) else (cell, None)
                item = QTableWidgetItem("" if text is None else str(text))
                tint = color or colors.get(r)
                if tint:
                    item.setForeground(QColor(tint))
                if r in bold:
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                if align_right_from is not None and c >= align_right_from:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.setItem(r, c, item)
        if keep is not None and keep in self.keys:
            self.selectRow(self.keys.index(keep))

    def current_key(self):
        r = self.currentRow()
        return self.keys[r] if 0 <= r < len(self.keys) else None

    def select_key(self, key):
        if key in self.keys:
            self.selectRow(self.keys.index(key))

    def fit_height(self, max_rows=None):
        """Size to the rows so stacked tables don't each scroll."""
        n = self.rowCount() if max_rows is None else min(self.rowCount(), max_rows)
        h = self.horizontalHeader().height() + sum(self.rowHeight(i) for i in range(n)) + 4
        self.setFixedHeight(max(h, 60))

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action in (Action.TAB_NEXT, Action.TAB_PREV, Action.BACK):
            event.ignore()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentRow() >= 0:
            self.activated_row.emit(self.currentRow())
        else:
            super().keyPressEvent(event)


def section(title, color=ACCENT):
    """Eyebrow heading + a vertical layout under it, in one widget."""
    w = QWidget()
    w.setStyleSheet("background: transparent;")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(6)
    v.addWidget(eyebrow_label(title, color=color, size=12))
    return w, v


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            # Detach now: deleteLater alone leaves the old widget painted
            # under the new one until the event loop gets round to it.
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())
