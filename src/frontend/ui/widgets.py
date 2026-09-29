"""
ui/widgets.py — Reusable UI Components
========================================
Every shared widget and factory lives here.
Screens import from this module — they never hardcode colours or fonts.

Public API
----------
  Factories (return a configured QWidget):
    make_page_header(title)        -> (header_widget, accent_bar_widget)
    make_separator()               -> QFrame (horizontal rule)
    make_label(text, role, align)  -> QLabel
    make_group(title)              -> QGroupBox

  Styled widget subclasses:
    StyledButton(text, variant)    -> QPushButton (primary/ghost/neutral/danger/small)
    HoverComboBox()                -> QComboBox with hover/data-change signals

  Helper:
    style_button(btn, variant)     -> apply variant stylesheet to existing QPushButton
"""

from PyQt5.QtWidgets import (
    QPushButton, QLabel, QFrame, QWidget,
    QVBoxLayout, QHBoxLayout, QGroupBox, QComboBox,
    QGraphicsDropShadowEffect, QSizePolicy, QSlider,
)
from PyQt5.QtGui import QFont, QColor
from PyQt5.QtCore import Qt, pyqtSignal, QEvent

from ui.theme import (
    BG_BASE, BG_PANEL, BG_CARD, BG_RAISED, BG_HIGHLIGHT,
    BORDER, BORDER_EM,
    ACCENT, ACCENT_LITE, ACCENT_DARK, ACCENT_DIM,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED,
    DANGER, DANGER_LITE,
    FONT_DISPLAY, FONT_BODY,
    HEADER_HEIGHT, HEADER_BAR_H,
    GRAD_HEADER, GRAD_ACCENT_BTN, GRAD_ACCENT_BTN_HOVER,
    F_HUGE, F_H1, F_H2, F_H3, F_BODY, F_SMALL, F_MONO,
)

# ── Button variant stylesheets ─────────────────────────────────────────────────

from shared.log import get_logger

log = get_logger(__name__)


def _make_btn_stylesheet(bg, bg_h, bg_p, fg, fg_h, border, border_h):
    return (
        f"QPushButton {{"
        f"  background: {bg}; color: {fg};"
        f"  border: 1px solid {border}; border-radius: 0px;"
        f"  padding: 10px 28px;"
        f"  font-family: '{FONT_DISPLAY}'; font-size: 10pt; font-weight: bold;"
        f"  letter-spacing: 2px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background: {bg_h}; border-color: {border_h}; color: {fg_h};"
        f"}}"
        f"QPushButton:pressed {{ background: {bg_p}; border: 1px solid {border_h}; }}"
        f"QPushButton:disabled {{"
        f"  background: {BG_PANEL}; color: {FG_MUTED}; border: 1px solid {BORDER};"
        f"}}"
    )

BUTTON_VARIANTS = {
    "primary": _make_btn_stylesheet(
        bg=GRAD_ACCENT_BTN, bg_h=GRAD_ACCENT_BTN_HOVER, bg_p=ACCENT_DARK,
        fg=BG_BASE, fg_h="#000000",
        border=ACCENT_DARK, border_h=ACCENT_LITE,
    ),
    "ghost": _make_btn_stylesheet(
        bg="transparent", bg_h=ACCENT_DIM, bg_p=BG_CARD,
        fg=ACCENT, fg_h=ACCENT_LITE,
        border=ACCENT_DARK, border_h=ACCENT,
    ),
    "neutral": _make_btn_stylesheet(
        bg=BG_CARD, bg_h=BG_RAISED, bg_p=BG_PANEL,
        fg=FG_SECONDARY, fg_h=FG_PRIMARY,
        border=BORDER, border_h=BORDER_EM,
    ),
    "danger": _make_btn_stylesheet(
        bg=DANGER, bg_h=DANGER_LITE, bg_p="#8a2820",
        fg=FG_PRIMARY, fg_h="#ffffff",
        border=DANGER, border_h=DANGER_LITE,
    ),
    "small": (
        f"QPushButton {{"
        f"  background-color: {BG_CARD}; color: {FG_SECONDARY};"
        f"  border: 1px solid {BORDER}; border-radius: 0px;"
        f"  padding: 4px 14px; font-size: 11pt;"
        f"}}"
        f"QPushButton:hover {{"
        f"  border-color: {ACCENT_DARK}; color: {ACCENT};"
        f"  background: {BG_RAISED};"
        f"}}"
        f"QPushButton:pressed {{ background-color: {BG_PANEL}; border: 1px solid {ACCENT_DARK}; }}"
    ),
}


def style_button(btn: QPushButton, variant: str = "primary") -> None:
    btn.setStyleSheet(BUTTON_VARIANTS.get(variant, BUTTON_VARIANTS["primary"]))
    btn.setCursor(Qt.PointingHandCursor)


class StyledButton(QPushButton):
    def __init__(self, text: str, variant: str = "primary", parent=None):
        super().__init__(text, parent)
        style_button(self, variant)


# ── Label factories ───────────────────────────────────────────────────────────

_LABEL_ROLES = {
    "title":     (ACCENT,        F_HUGE,  "10px"),
    "heading":   (ACCENT_DARK,   F_H2,    "4px"),
    "subheading":(FG_PRIMARY,    F_H3,    "2px"),
    "body":      (FG_PRIMARY,    F_BODY,  "0"),
    "secondary": (FG_SECONDARY,  F_SMALL, "0"),
    "muted":     (FG_MUTED,      F_SMALL, "1px"),
    "accent":    (ACCENT,        F_MONO,  "1px"),
}

def make_label(text: str, role: str = "body",
               align: Qt.AlignmentFlag = Qt.AlignLeft) -> QLabel:
    colour, font, spacing = _LABEL_ROLES.get(role, _LABEL_ROLES["body"])
    lbl = QLabel(text)
    lbl.setFont(font)
    lbl.setAlignment(align)
    lbl.setStyleSheet(
        f"color: {colour}; letter-spacing: {spacing};"
        f" background: transparent;"
    )
    return lbl


# ── Page header ───────────────────────────────────────────────────────────────

def make_page_header(title: str) -> tuple[QWidget, QFrame]:
    header = QWidget()
    header.setFixedHeight(HEADER_HEIGHT)
    header.setStyleSheet(
        f"background: {GRAD_HEADER};"
        f" border-bottom: 1px solid {BORDER};"
    )
    hl = QVBoxLayout(header)
    hl.setContentsMargins(28, 0, 28, 0)

    lbl = QLabel(title)
    lbl.setFont(F_H2)
    lbl.setStyleSheet(
        f"color: {ACCENT}; letter-spacing: 4px; background: transparent;"
    )
    hl.addWidget(lbl, alignment=Qt.AlignVCenter)

    bar = QFrame()
    bar.setFixedHeight(HEADER_BAR_H)
    bar.setStyleSheet(f"background: {ACCENT_DARK}; border: none;")

    return header, bar


# ── Separator ─────────────────────────────────────────────────────────────────

def make_separator(vertical: bool = False) -> QFrame:
    sep = QFrame()
    sep.setFrameShape(QFrame.VLine if vertical else QFrame.HLine)
    sep.setStyleSheet(f"color: {BORDER};")
    return sep


# ── GroupBox ──────────────────────────────────────────────────────────────────

def make_group(title: str) -> QGroupBox:
    return QGroupBox(title.upper())


# ── HoverComboBox ─────────────────────────────────────────────────────────────

class HoverComboBox(QComboBox):
    hovered            = pyqtSignal(str)
    currentDataChanged = pyqtSignal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setEditable(True)
        self.lineEdit().setReadOnly(True)
        self.lineEdit().installEventFilter(self)
        self.view().viewport().installEventFilter(self)
        self.currentIndexChanged.connect(
            lambda: self.currentDataChanged.emit(self.currentData())
        )
        self._prev_data = None

    def eventFilter(self, source, event):
        viewport = self.view().viewport()
        if event.type() == QEvent.MouseMove and source is viewport:
            idx = self.view().indexAt(event.pos())
            if idx.isValid():
                self.hovered.emit(str(self.itemData(idx.row())))
        elif event.type() == QEvent.MouseButtonPress and source is self.lineEdit():
            self.showPopup()
        return super().eventFilter(source, event)

    def showPopup(self):
        if self.currentData() not in (None, -1, 0):
            self._prev_data = self.currentData()
        super().showPopup()

    def enterEvent(self, event):
        self.hovered.emit(str(self.currentData()))
        super().enterEvent(event)

    def leaveEvent(self, event):
        self.hovered.emit("")
        super().leaveEvent(event)

    def setCurrentData(self, data) -> None:
        target = str(data)
        for i in range(self.count()):
            if str(self.itemData(i)) == target:
                self.setCurrentIndex(i)
                return
        log.warning(f"data '{data}' not found in {self.count()} items")

    def has_data(self, value) -> bool:
        return any(self.itemData(i) == value for i in range(self.count()))


# ── ToggleRow ─────────────────────────────────────────────────────────────────

class ToggleRow(QWidget):
    def __init__(self, label: str, initial: bool, on_toggle, parent=None):
        super().__init__(parent)
        self._on_toggle = on_toggle
        self._state = initial

        self.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid {BORDER};"
        )

        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {FG_SECONDARY}; font-family: '{FONT_DISPLAY}'; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        row.addWidget(lbl)
        row.addStretch()

        self._btn = QPushButton()
        self._btn.setFixedSize(76, 30)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.clicked.connect(self._toggle)
        row.addWidget(self._btn)
        self._refresh()

    def _toggle(self):
        self._state = not self._state
        self._on_toggle(self._state)
        self._refresh()

    def _refresh(self):
        self._btn.setText("ON" if self._state else "OFF")
        if self._state:
            self._btn.setStyleSheet(
                f"QPushButton {{ background: {ACCENT}; color: {BG_BASE}; border: none;"
                f"  font-family: '{FONT_DISPLAY}'; font-size: 9pt; font-weight: bold;"
                f"  letter-spacing: 2px; }}"
                f"QPushButton:hover {{ background: {ACCENT_LITE}; }}"
            )
        else:
            self._btn.setStyleSheet(
                f"QPushButton {{ background: {BG_RAISED}; color: {FG_MUTED};"
                f"  border: 1px solid {BORDER};"
                f"  font-family: '{FONT_DISPLAY}'; font-size: 9pt; font-weight: bold;"
                f"  letter-spacing: 2px; }}"
                f"QPushButton:hover {{ border-color: {DANGER}; color: {DANGER_LITE}; }}"
            )


class ChoiceRow(QWidget):
    """ToggleRow's look, for a choice among several values: a dropdown list.
    on_change is called with the selected label."""

    def __init__(self, label: str, values, initial, on_change, parent=None):
        super().__init__(parent)
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 6, 16, 6)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {FG_SECONDARY}; font-family: '{FONT_DISPLAY}'; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        row.addWidget(lbl)
        row.addStretch()

        self.combo = HoverComboBox()
        self.combo.setFixedSize(180, 36)
        self.combo.addItems([str(v) for v in values])
        if str(initial) in [str(v) for v in values]:
            self.combo.setCurrentText(str(initial))
        self.combo.currentTextChanged.connect(on_change)
        row.addWidget(self.combo)


class CycleRow(QWidget):
    """ToggleRow's look, for a choice among several values: the button shows the
    current one and each click steps to the next."""

    def __init__(self, label: str, values, initial, on_change, parent=None):
        super().__init__(parent)
        self._values = list(values)
        self._on_change = on_change
        self._index = self._values.index(initial) if initial in self._values else 0

        self.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid {BORDER};"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {FG_SECONDARY}; font-family: '{FONT_DISPLAY}'; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        row.addWidget(lbl)
        row.addStretch()

        self._btn = QPushButton(str(self._values[self._index]))
        self._btn.setFixedSize(110, 30)
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setStyleSheet(
            f"QPushButton {{ background: {BG_RAISED}; color: {FG_SECONDARY};"
            f"  border: 1px solid {BORDER};"
            f"  font-family: '{FONT_DISPLAY}'; font-size: 9pt; font-weight: bold;"
            f"  letter-spacing: 2px; }}"
            f"QPushButton:hover {{ border-color: {ACCENT}; color: {ACCENT_LITE}; }}"
        )
        self._btn.clicked.connect(self._step)
        row.addWidget(self._btn)

    def _step(self):
        self._index = (self._index + 1) % len(self._values)
        value = self._values[self._index]
        self._btn.setText(str(value))
        self._on_change(value)


class SliderRow(QWidget):
    """ToggleRow's look, for an integer in [minimum, maximum]: a slider and its
    current value. on_change is called with the value as the slider moves."""

    def __init__(self, label: str, minimum: int, maximum: int, initial: int,
                 on_change, step: int = 1, parent=None):
        super().__init__(parent)
        self._on_change = on_change

        self.setStyleSheet(
            f"background-color: {BG_CARD}; border: 1px solid {BORDER};"
        )
        row = QHBoxLayout(self)
        row.setContentsMargins(16, 12, 16, 12)

        lbl = QLabel(label)
        lbl.setStyleSheet(
            f"color: {FG_SECONDARY}; font-family: '{FONT_DISPLAY}'; font-size: 10pt;"
            f" background: transparent; border: none;"
        )
        row.addWidget(lbl)
        row.addStretch()

        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setSingleStep(step)
        self._slider.setPageStep(step)
        self._slider.setFixedWidth(220)
        self._slider.setCursor(Qt.PointingHandCursor)
        self._slider.setStyleSheet(
            f"QSlider {{ background: transparent; border: none; }}"
            f"QSlider::groove:horizontal {{ height: 4px; background: {BG_RAISED};"
            f"  border: 1px solid {BORDER}; }}"
            f"QSlider::sub-page:horizontal {{ background: {ACCENT}; }}"
            f"QSlider::handle:horizontal {{ width: 12px; margin: -7px 0;"
            f"  background: {FG_SECONDARY}; border: none; }}"
            f"QSlider::handle:horizontal:hover {{ background: {ACCENT_LITE}; }}"
        )
        self._step = step
        self._slider.setValue(initial)
        self._slider.valueChanged.connect(self._changed)
        row.addWidget(self._slider)

        self._value = QLabel(str(initial))
        self._value.setFixedWidth(40)
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setStyleSheet(
            f"color: {FG_PRIMARY}; font-family: '{FONT_DISPLAY}'; font-size: 10pt;"
            f" font-weight: bold; background: transparent; border: none;"
        )
        row.addWidget(self._value)

    def _changed(self, value: int):
        if self._step > 1:
            snapped = self._slider.minimum() + round(
                (value - self._slider.minimum()) / self._step) * self._step
            snapped = min(snapped, self._slider.maximum())
            if snapped != value:
                self._slider.setValue(snapped)      # re-enters with the snapped value
                return
        self._value.setText(str(value))
        self._on_change(value)

    def set_value(self, value: int):
        self._slider.setValue(value)


# ── KitPreview ────────────────────────────────────────────────────────────────

class KitPreviewBox(QLabel):
    def __init__(self, size: int = None, parent=None):
        super().__init__(parent)
        self._source_pixmap = None
        self.setMinimumSize(120, 120)
        self.setMaximumSize(400, 400)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAlignment(Qt.AlignCenter)
        self.setStyleSheet(
            f"border: 1px solid {BORDER}; background: {BG_CARD}; color: {FG_MUTED};"
            f" font-size: 9pt;"
        )

    def set_pixmap(self, pixmap):
        self._source_pixmap = pixmap
        self._update_scaled()

    def set_placeholder(self, text: str = "NO PREVIEW"):
        self._source_pixmap = None
        self.clear()
        self.setText(text)

    def _update_scaled(self):
        if self._source_pixmap and not self._source_pixmap.isNull():
            scaled = self._source_pixmap.scaled(
                self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation,
            )
            super().setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_scaled()


# ── Layout panel helpers ──────────────────────────────────────────────────────

def style_panel(widget: QWidget, bg: str = None, border_left: bool = False) -> None:
    colour = bg or BG_BASE
    border = f" border-left: 1px solid {BORDER};" if border_left else ""
    widget.setStyleSheet(f"background-color: {colour};{border}")


def make_app_title_header(game_name: str, subtitle: str, version: str) -> QWidget:
    container = QWidget()
    container_layout = QVBoxLayout(container)
    container_layout.setContentsMargins(0, 0, 0, 0)
    container_layout.setSpacing(0)

    header = QWidget()
    header.setMinimumHeight(120)
    header.setMaximumHeight(160)
    header.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    header.setStyleSheet(
        f"background: {GRAD_HEADER};"
        f" border-bottom: 1px solid {BORDER};"
    )
    hl = QVBoxLayout(header)
    hl.setContentsMargins(0, 20, 0, 16)
    hl.setSpacing(6)

    title_lbl = QLabel(game_name)
    title_lbl.setAlignment(Qt.AlignCenter)
    title_lbl.setStyleSheet(
        f"color: {ACCENT}; font-family: '{FONT_DISPLAY}'; font-size: 34pt;"
        f" font-weight: bold; letter-spacing: 12px; background: transparent;"
    )
    hl.addWidget(title_lbl)

    sub_lbl = QLabel(subtitle)
    sub_lbl.setAlignment(Qt.AlignCenter)
    sub_lbl.setStyleSheet(
        f"color: {FG_MUTED}; font-family: '{FONT_DISPLAY}'; font-size: 9pt;"
        f" letter-spacing: 6px; background: transparent;"
    )
    hl.addWidget(sub_lbl)

    accent_bar = QFrame()
    accent_bar.setFixedHeight(3)
    accent_bar.setStyleSheet(
        f"background: qlineargradient(x1:0, y1:0, x2:1, y2:0,"
        f" stop:0 transparent, stop:0.2 {ACCENT_DARK},"
        f" stop:0.5 {ACCENT}, stop:0.8 {ACCENT_DARK},"
        f" stop:1 transparent);"
        f" border: none;"
    )

    container_layout.addWidget(header)
    container_layout.addWidget(accent_bar)
    return container


def make_footer(left_text: str, right_text: str) -> QWidget:
    footer = QWidget()
    footer.setFixedHeight(32)
    footer.setStyleSheet(
        f"background: {GRAD_HEADER};"
        f" border-top: 1px solid {BORDER};"
    )
    fl = QHBoxLayout(footer)
    fl.setContentsMargins(20, 0, 20, 0)

    left_lbl = QLabel(left_text)
    left_lbl.setStyleSheet(
        f"color: {FG_MUTED}; font-size: 8pt; font-family: '{FONT_DISPLAY}';"
        f" background: transparent; letter-spacing: 1px;"
    )
    fl.addWidget(left_lbl)
    fl.addStretch()

    right_lbl = QLabel(right_text)
    right_lbl.setStyleSheet(
        f"color: {ACCENT_DARK}; font-size: 8pt; font-family: '{FONT_DISPLAY}';"
        f" background: transparent;"
    )
    fl.addWidget(right_lbl)
    return footer
