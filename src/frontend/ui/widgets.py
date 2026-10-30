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
    BORDER, BORDER_EM, DIVIDER,
    ACCENT, ACCENT_LITE, ACCENT_DARK, ACCENT_DIM,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED,
    DANGER, DANGER_LITE,
    FONT_DISPLAY, FONT_BODY,
    HEADER_HEIGHT, HEADER_BAR_H,
    GRAD_HEADER, GRAD_ACCENT_BTN, GRAD_ACCENT_BTN_HOVER,
    F_HUGE, F_H1, F_H2, F_H3, F_BODY, F_SMALL, F_MONO,
    T_SETTING_LABEL, T_SETTING_VALUE,
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


# ── Setting rows (Settings screen) ────────────────────────────────────────────

class SettingRow(QWidget):
    """A Settings row: the label on the left, its control on the right, a
    hairline under it — a
    flat list, no boxes. The focused row lights up: a red bar on its left
    edge, a raised background, the label brighter. The row takes the
    keyboard focus, not the control: Left/Right change the value (adjust),
    Enter/Space activate it; every other key goes on to the screen."""

    HEIGHT = 54
    CONTROL_WIDTH = 320     # every row's control in one right-hand column

    def __init__(self, label: str, parent=None):
        super().__init__(parent)
        self.setObjectName("settingRow")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(self.HEIGHT)
        self.row = QHBoxLayout(self)
        self.row.setContentsMargins(34, 0, 12, 1)      # clear of the hairline
        self.row.setSpacing(8)

        self.label = QLabel(label)
        self.row.addWidget(self.label)
        self.row.addStretch()
        self._paint_focus(False)

    def _own(self, control):
        """Add the row's control: driven through the row, never focused itself;
        a click on it focuses the row."""
        control.setFocusPolicy(Qt.NoFocus)
        control.installEventFilter(self)
        control.setAttribute(Qt.WA_TranslucentBackground, True)
        self.row.addWidget(control)

    def eventFilter(self, obj, event):
        if event.type() == QEvent.MouseButtonPress:
            self.setFocus(Qt.MouseFocusReason)
        return False

    def mousePressEvent(self, event):
        self.setFocus(Qt.MouseFocusReason)
        super().mousePressEvent(event)

    def _paint_focus(self, focused):
        self.setStyleSheet(
            f"QWidget#settingRow {{ background-color: {BG_RAISED if focused else 'transparent'};"
            f" border: none; border-bottom: 1px solid {DIVIDER};"
            f" border-left: 3px solid {ACCENT if focused else 'transparent'}; }}"
        )
        self.label.setStyleSheet(
            f"color: {FG_PRIMARY if focused else FG_SECONDARY}; font-family: '{FONT_DISPLAY}';"
            f" font-size: {T_SETTING_LABEL}pt; background: transparent; border: none;"
        )
        self._focus_changed(focused)

    def _focus_changed(self, focused):
        """Restyle the control for the row's focus (subclasses)."""

    def focusInEvent(self, event):
        self._paint_focus(True)
        super().focusInEvent(event)

    def focusOutEvent(self, event):
        self._paint_focus(False)
        super().focusOutEvent(event)

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key_Left, Qt.Key_Right):
            self.adjust(-1 if k == Qt.Key_Left else 1)
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activate()
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def adjust(self, delta: int):
        """Left (-1) / Right (+1)."""

    def activate(self):
        """Enter / Space."""
        self.adjust(1)


def _value_style(color):
    return (f"color: {color}; font-family: '{FONT_DISPLAY}'; font-size: {T_SETTING_VALUE + 1}pt;"
            f" font-weight: bold; letter-spacing: 1px; background: transparent; border: none;")


class _Switch(QWidget):
    """An on/off switch: a pill track, the knob at the side of the state."""

    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(46, 24)
        self.setCursor(Qt.PointingHandCursor)
        self.on = False

    def mousePressEvent(self, event):
        self.clicked.emit()

    def paintEvent(self, event):
        from PyQt5.QtGui import QPainter, QPen
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = self.rect().adjusted(1, 1, -1, -1)
        p.setPen(QPen(QColor(ACCENT if self.on else BORDER), 1))
        p.setBrush(QColor(ACCENT if self.on else BG_BASE))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 6
        x = r.right() - d - 2 if self.on else r.left() + 3
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(FG_PRIMARY if self.on else FG_MUTED))
        p.drawEllipse(x, r.top() + 3, d, d)


class ToggleRow(SettingRow):
    def __init__(self, label: str, initial: bool, on_toggle, parent=None):
        super().__init__(label, parent)
        self._on_toggle = on_toggle
        self._state = initial

        box = QWidget()
        box.setFixedWidth(self.CONTROL_WIDTH)
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(12)
        h.addStretch()
        self._text = QLabel()
        h.addWidget(self._text)
        self._switch = _Switch()
        self._switch.clicked.connect(self._toggle)
        h.addWidget(self._switch)
        self._own(box)
        self._refresh()

    def adjust(self, delta):
        self._toggle()

    def _toggle(self):
        self.setFocus(Qt.MouseFocusReason)
        self._state = not self._state
        self._on_toggle(self._state)
        self._refresh()

    def _refresh(self):
        self._text.setText("ON" if self._state else "OFF")
        self._text.setStyleSheet(_value_style(FG_PRIMARY if self._state else FG_MUTED))
        self._switch.on = self._state
        self._switch.update()


class _Stepper(QWidget):
    """‹ VALUE › — the value between two arrows that step it (Left/Right
    on the row do the same). The arrows light up while the row is focused."""

    ARROW_WIDTH = 28

    def __init__(self, center, on_step, parent=None):
        super().__init__(parent)
        self.setFixedWidth(SettingRow.CONTROL_WIDTH)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self._arrows = []
        for delta, glyph in ((-1, "‹"), (1, "›")):
            arrow = QLabel(glyph)
            arrow.setFixedWidth(self.ARROW_WIDTH)
            arrow.setAlignment(Qt.AlignCenter)
            arrow.setCursor(Qt.PointingHandCursor)
            arrow.mousePressEvent = lambda _e, d=delta: on_step(d)
            self._arrows.append(arrow)
        h.addWidget(self._arrows[0])
        h.addWidget(center, 1)
        h.addWidget(self._arrows[1])
        self.set_focused(False)

    def set_focused(self, focused):
        for arrow in self._arrows:
            arrow.setStyleSheet(
                f"color: {ACCENT if focused else FG_MUTED}; font-family: '{FONT_DISPLAY}';"
                f" font-size: {T_SETTING_LABEL + 6}pt; font-weight: bold; background: transparent;"
            )


class ChoiceRow(SettingRow):
    """A choice among several values: ‹ value ›, Left/Right step through
    them, Enter or a click on the value opens the whole list. on_change is
    called with the selected label."""

    def __init__(self, label: str, values, initial, on_change, parent=None):
        super().__init__(label, parent)
        self.combo = HoverComboBox()
        self.combo.setFixedHeight(36)
        self.combo.setCursor(Qt.PointingHandCursor)
        self.combo.lineEdit().setAlignment(Qt.AlignCenter)
        self.combo.lineEdit().setCursor(Qt.PointingHandCursor)
        self.combo.setStyleSheet(
            f"QComboBox {{ background: transparent; border: none; padding: 0; min-height: 0; }}"
            f"QComboBox::drop-down {{ width: 0; border: none; }}"
            f"QComboBox::down-arrow {{ image: none; border: none; width: 0; height: 0; }}"
        )
        # the read-only line edit shows the value: styled itself, the
        # combo's own rule doesn't reach its text colour
        self.combo.lineEdit().setStyleSheet(_value_style(FG_PRIMARY) + " padding: 0;")
        self.combo.lineEdit().setFont(QFont(FONT_DISPLAY, T_SETTING_VALUE + 1, QFont.Bold))
        self.combo.addItems([str(v) for v in values])
        if str(initial) in [str(v) for v in values]:
            self.combo.setCurrentText(str(initial))
        self.combo.currentTextChanged.connect(on_change)
        self._stepper = _Stepper(self.combo, self.adjust)
        self._own(self._stepper)
        self.combo.setFocusPolicy(Qt.NoFocus)
        self.combo.installEventFilter(self)
        self.combo.lineEdit().setFocusPolicy(Qt.NoFocus)
        self.combo.lineEdit().installEventFilter(self)

    def _focus_changed(self, focused):
        if hasattr(self, "_stepper"):
            self._stepper.set_focused(focused)

    def adjust(self, delta):
        i = self.combo.currentIndex() + delta
        if 0 <= i < self.combo.count():
            self.combo.setCurrentIndex(i)

    def activate(self):
        self.combo.showPopup()


class CycleRow(SettingRow):
    """A choice among a few values: ‹ value ›, each step (or a click on the
    value) moves to the next one, round."""

    def __init__(self, label: str, values, initial, on_change, parent=None):
        super().__init__(label, parent)
        self._values = list(values)
        self._on_change = on_change
        self._index = self._values.index(initial) if initial in self._values else 0

        self._value = QLabel(str(self._values[self._index]))
        self._value.setAlignment(Qt.AlignCenter)
        self._value.setCursor(Qt.PointingHandCursor)
        self._value.setStyleSheet(_value_style(FG_PRIMARY))
        self._value.mousePressEvent = lambda _e: self.adjust(1)
        self._stepper = _Stepper(self._value, self.adjust)
        self._own(self._stepper)

    def _focus_changed(self, focused):
        if hasattr(self, "_stepper"):
            self._stepper.set_focused(focused)

    def adjust(self, delta):
        self.setFocus(Qt.MouseFocusReason)
        self._index = (self._index + delta) % len(self._values)
        value = self._values[self._index]
        self._value.setText(str(value))
        self._on_change(value)


class SliderRow(SettingRow):
    """An integer in [minimum, maximum]: a slider and its current value.
    on_change is called with the value as the slider moves."""

    def __init__(self, label: str, minimum: int, maximum: int, initial: int,
                 on_change, step: int = 1, parent=None):
        super().__init__(label, parent)
        self._on_change = on_change

        box = QWidget()
        box.setFixedWidth(self.CONTROL_WIDTH)
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(14)
        self._slider = QSlider(Qt.Horizontal)
        self._slider.setRange(minimum, maximum)
        self._slider.setSingleStep(step)
        self._slider.setPageStep(step)
        self._slider.setCursor(Qt.PointingHandCursor)
        self._slider.setFocusPolicy(Qt.NoFocus)
        self._slider.installEventFilter(self)
        self._step = step
        self._slider.setValue(initial)
        self._slider.valueChanged.connect(self._changed)
        h.addWidget(self._slider, 1)

        self._value = QLabel(str(initial))
        self._value.setFixedWidth(36)
        self._value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._value.setStyleSheet(_value_style(FG_PRIMARY))
        h.addWidget(self._value)
        self._own(box)
        self._focus_changed(False)

    def _focus_changed(self, focused):
        if not hasattr(self, "_slider"):
            return
        self._slider.setStyleSheet(
            f"QSlider {{ background: transparent; border: none; }}"
            f"QSlider::groove:horizontal {{ height: 4px; background: {BG_BASE}; border-radius: 2px; }}"
            f"QSlider::sub-page:horizontal {{ background: {ACCENT if focused else ACCENT_DARK};"
            f"  border-radius: 2px; }}"
            f"QSlider::handle:horizontal {{ width: 14px; height: 14px; margin: -5px 0;"
            f"  border-radius: 7px; background: {FG_PRIMARY if focused else FG_SECONDARY}; }}"
        )

    def adjust(self, delta):
        self._slider.setValue(self._slider.value() + delta * self._step)

    def activate(self):
        pass

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
