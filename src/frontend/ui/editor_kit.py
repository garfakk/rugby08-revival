"""
ui/editor_kit.py — building blocks for the data editors
=========================================================
The team and player editors are desk tools: mouse and keyboard first, with
the gamepad still able to reach everything. Everything here is Qt only (no
`app` imports) and paints itself so it matches the broadcast kit.

Principles the widgets enforce:
  * show the file as it is — a blank value reads as "—" with the game's
    default beside it, an off-list value is shown in warning colour and kept
    until the user changes it; displaying a record never edits it;
  * one row height and one label column per grid, so fields line up;
  * every field can carry an issue (error / warn / info) and a badge
    ("UI ONLY", "UNUSED BY GAME") without losing its label.
"""
import os
import re
import time

from PyQt5.QtWidgets import (
    QWidget, QLabel, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea,
    QSizePolicy, QLineEdit, QStackedWidget, QApplication, QFrame,
)
from PyQt5.QtGui import (
    QPainter, QColor, QPen, QFont, QFontMetrics, QPixmap, QImageReader, QBrush,
)
from PyQt5.QtCore import Qt, QRectF, QRect, QSize, QTimer, QPoint, pyqtSignal, QEvent

from ui.broadcast import Card, HintBar, draw_frame, tracked_font, display_label, eyebrow_label
from ui.dropdown import PopupList
from ui.widgets import StyledButton
from ui.theme import (
    BG_BASE, BG_PANEL, BG_CARD, BG_RAISED, BG_HIGHLIGHT, BORDER, BORDER_EM,
    ACCENT, ACCENT_DIM, WARN, INFO, GREEN, DANGER, DANGER_LITE, HOME_TINT,
    FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FG_MUTED, FONT_DISPLAY, FONT_BODY,
    T_DISPLAY, T_TITLE, T_SECTION, T_LABEL, T_VALUE, T_SMALL, EDITOR_ROW_H,
    BTN_HEIGHT_SM,
)

SEVERITY_COLOR = {"error": DANGER_LITE, "warn": WARN, "info": INFO}
SEVERITY_RANK = {"error": 0, "warn": 1, "info": 2}


def worst(severities):
    ranked = sorted((s for s in severities if s), key=lambda s: SEVERITY_RANK.get(s, 9))
    return ranked[0] if ranked else None


# ═════════════════════════════════════════════════════════════════════════
# Images
# ═════════════════════════════════════════════════════════════════════════
_PIXMAP_CACHE = {}
_PIXMAP_CACHE_ORDER = []
_CACHE_LIMIT = 400


def load_pixmap(path, max_side=None):
    """Cached, optionally downscaled pixmap for an image file; a null pixmap
    for anything missing or undecodable. Keyed on mtime so an image edited
    on disk while the app runs is picked up."""
    if not path or not os.path.isfile(path):
        return QPixmap()
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return QPixmap()
    key = (path, mtime, max_side)
    cached = _PIXMAP_CACHE.get(key)
    if cached is not None:
        return cached
    reader = QImageReader(path)
    if max_side:
        size = reader.size()
        if size.isValid() and max(size.width(), size.height()) > max_side:
            size.scale(max_side, max_side, Qt.KeepAspectRatio)
            reader.setScaledSize(size)
    image = reader.read()
    pix = QPixmap.fromImage(image) if not image.isNull() else QPixmap()
    _PIXMAP_CACHE[key] = pix
    _PIXMAP_CACHE_ORDER.append(key)
    if len(_PIXMAP_CACHE_ORDER) > _CACHE_LIMIT:
        _PIXMAP_CACHE.pop(_PIXMAP_CACHE_ORDER.pop(0), None)
    return pix


def image_size(path):
    if not path or not os.path.isfile(path):
        return None
    size = QImageReader(path).size()
    return (size.width(), size.height()) if size.isValid() else None


def expand_pattern(path, n):
    return path.replace("%", str(n), 1)


def asset_status(root, rel, spec):
    """(state, detail, count) for a team asset path.

    state: "empty" | "ok" | "missing" | "partial" | "size" | "archive" | "outside"
    """
    rel = (rel or "").strip()
    if not rel:
        return "empty", "not set", 0
    spec = spec or {}
    norm = os.path.normpath(rel)
    if os.path.isabs(rel) or norm.startswith(".."):
        return "outside", "outside the team folder", 0
    frames = spec.get("frames", 0)
    ext = os.path.splitext(rel)[1].lower()
    if "%" in rel and frames:
        present = sum(1 for i in range(1, frames + 1)
                      if os.path.isfile(os.path.join(root, expand_pattern(rel, i))))
        if present == frames:
            return "ok", f"{present}/{frames} files", present
        if present == 0:
            return "missing", f"0/{frames} files", 0
        return "partial", f"{present}/{frames} files", present
    full = os.path.join(root, rel)
    if not os.path.isfile(full):
        return "missing", "file not found", 0
    if ext in (".fsh", ".big"):
        return "archive", ext[1:].upper() + " archive", 1
    want = spec.get("size")
    if want:
        got = image_size(full)
        if got and tuple(got) != tuple(want):
            return "size", f"{got[0]}×{got[1]} (expected {want[0]}×{want[1]})", 1
    return "ok", "found", 1


STATUS_STYLE = {
    "empty": (FG_TERTIARY, "NOT SET"),
    "ok": (GREEN, "OK"),
    "missing": (DANGER_LITE, "MISSING"),
    "partial": (WARN, "PARTIAL"),
    "size": (WARN, "SIZE"),
    "archive": (INFO, "ARCHIVE"),
    "outside": (WARN, "OUTSIDE"),
}


def compact_button(text, variant="neutral", height=BTN_HEIGHT_SM):
    """A StyledButton with tight horizontal padding, for toolbars where the
    stock 28px padding would clip the label."""
    b = StyledButton(text, variant)
    b.setFixedHeight(height)
    b.setStyleSheet(b.styleSheet() + "QPushButton { padding: 4px 10px; letter-spacing: 1px; }")
    return b


# ═════════════════════════════════════════════════════════════════════════
# Small painted pieces
# ═════════════════════════════════════════════════════════════════════════
def paint_badge(p, x, y, text, color, h=16):
    """A small outlined tag; returns its width."""
    p.save()
    p.setFont(tracked_font(FONT_DISPLAY, T_SMALL - 1, QFont.DemiBold, track=0.8))
    w = p.fontMetrics().horizontalAdvance(text) + 10
    p.setPen(QPen(QColor(color), 1))
    p.setBrush(Qt.NoBrush)
    p.drawRect(QRectF(x, y, w, h))
    p.drawText(QRectF(x, y, w, h), Qt.AlignCenter, text)
    p.restore()
    return w


class Badge(QWidget):
    def __init__(self, text, color=FG_TERTIARY, filled=False, parent=None):
        super().__init__(parent)
        self._text, self._color, self._filled = text, color, filled
        f = tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, track=0.8)
        self._font = f
        # 20 px is the design height, but the text comes first (see
        # ui.broadcast.display_label).
        self.setFixedHeight(max(20, QFontMetrics(f).height()))
        self._fit()

    def _fit(self):
        self.setFixedWidth(QFontMetrics(self._font).horizontalAdvance(self._text) + 14)

    def set_text(self, text, color=None):
        self._text = text
        if color:
            self._color = color
        self._fit()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(self._font)
        col = QColor(self._color)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        if self._filled:
            p.fillRect(r, col)
            p.setPen(QColor(BG_BASE))
        else:
            p.setPen(QPen(col, 1))
            p.drawRect(r)
        p.drawText(self.rect(), Qt.AlignCenter, self._text)


class Avatar(QWidget):
    """A crest/portrait if there is one, otherwise initials in a ring."""

    def __init__(self, size=64, tint=ACCENT, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pix = QPixmap()
        self._initials = "?"
        self._tint = tint
        self._square = False

    def set_pixmap(self, pix, square=True):
        self._pix = pix if pix is not None else QPixmap()
        self._square = square
        self.update()

    def set_initials(self, text, tint=None):
        self._initials = (text or "?")[:3].upper()
        if tint:
            self._tint = tint
        self._pix = QPixmap()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        r = QRectF(self.rect()).adjusted(2, 2, -2, -2)
        if not self._pix.isNull():
            scaled = self._pix.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap((self.width() - scaled.width()) // 2,
                         (self.height() - scaled.height()) // 2, scaled)
            return
        p.setBrush(QColor(BG_RAISED))
        p.setPen(QPen(QColor(self._tint), 2))
        p.drawEllipse(r)
        p.setPen(QColor(FG_SECONDARY))
        p.setFont(tracked_font(FONT_DISPLAY, max(10, int(self.height() * 0.3)), QFont.Bold, 0.5))
        p.drawText(r, Qt.AlignCenter, self._initials)


class Thumb(QWidget):
    """A fixed-size image well: the picture, or a word saying why not."""

    clicked = pyqtSignal()

    def __init__(self, w=48, h=48, parent=None):
        super().__init__(parent)
        self.setFixedSize(w, h)
        self._pix = QPixmap()
        self._text = ""
        self._border = BORDER

    def set_image(self, path, text_if_missing="—"):
        self._pix = load_pixmap(path, max_side=max(self.width(), self.height()) * 2)
        self._text = "" if not self._pix.isNull() else text_if_missing
        self.update()

    def set_text(self, text):
        self._pix = QPixmap()
        self._text = text
        self.update()

    def set_pixmap(self, pix, text_if_missing="—"):
        self._pix = pix if pix is not None else QPixmap()
        self._text = "" if not self._pix.isNull() else text_if_missing
        self.update()

    def set_border(self, color):
        self._border = color
        self.update()

    def mousePressEvent(self, event):
        self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(BG_BASE))
        # chequer-ish backdrop so transparent PNG areas read as transparent
        p.fillRect(QRect(0, 0, self.width() // 2, self.height() // 2), QColor("#0c0f16"))
        p.fillRect(QRect(self.width() // 2, self.height() // 2, self.width(), self.height()),
                   QColor("#0c0f16"))
        if not self._pix.isNull():
            scaled = self._pix.scaled(self.size() - QSize(4, 4), Qt.KeepAspectRatio,
                                      Qt.SmoothTransformation)
            p.drawPixmap((self.width() - scaled.width()) // 2,
                         (self.height() - scaled.height()) // 2, scaled)
        elif self._text:
            p.setPen(QColor(FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.6))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap, self._text)
        draw_frame(p, self.rect(), self._border)


# ═════════════════════════════════════════════════════════════════════════
# Fields
# ═════════════════════════════════════════════════════════════════════════
class FieldBase(QWidget):
    """Label on the left, value box on the right, one row height. Subclasses
    paint the value into `value_rect()`."""

    edited = pyqtSignal(object)

    def __init__(self, label, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(EDITOR_ROW_H)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.label = label
        self.label_width = 140
        self.key = None               # field key the screen addresses it by
        self._issue = None            # (severity, message)
        self._badge = ""
        self._hint = ""
        self._flash_until = 0.0
        self._label_font = tracked_font(FONT_DISPLAY, T_LABEL, QFont.DemiBold, track=0.6)
        self._value_font = tracked_font(FONT_DISPLAY, T_VALUE, QFont.DemiBold, track=0.3)

    # ── decoration ───────────────────────────────────────────────────────
    def set_issue(self, severity=None, message=""):
        self._issue = (severity, message) if severity else None
        self.setToolTip(message or self._tooltip_base())
        self.update()

    def issue(self):
        return self._issue

    def set_badge(self, text):
        self._badge = text or ""
        self.update()

    def set_hint(self, text):
        """Shown in place of a blank value — what the game uses instead."""
        self._hint = text or ""
        self.update()

    def _tooltip_base(self):
        return ""

    def flash(self):
        self._flash_until = time.monotonic() + 0.9
        self.update()
        QTimer.singleShot(950, self.update)

    def label_text_width(self):
        return QFontMetrics(self._label_font).horizontalAdvance(self.label) + (
            QFontMetrics(tracked_font(FONT_DISPLAY, T_SMALL - 1, QFont.DemiBold, 0.8))
            .horizontalAdvance(self._badge) + 18 if self._badge else 0)

    def value_rect(self):
        return QRectF(self.label_width, 3, self.width() - self.label_width, self.height() - 6)

    def is_editing(self):
        return False

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        focused = self.hasFocus() or self.is_editing()
        flashing = time.monotonic() < self._flash_until
        sev = self._issue[0] if self._issue else None

        # label
        p.setFont(self._label_font)
        p.setPen(QColor(ACCENT if focused else FG_SECONDARY))
        lw = self.label_width - 12
        text = self.label
        if self._badge:
            bw = QFontMetrics(tracked_font(FONT_DISPLAY, T_SMALL - 1, QFont.DemiBold, 0.8)) \
                .horizontalAdvance(self._badge) + 10
            lw -= bw + 6
        label = p.fontMetrics().elidedText(text, Qt.ElideRight, int(max(20, lw)))
        p.drawText(QRectF(0, 0, lw, self.height()), Qt.AlignLeft | Qt.AlignVCenter, label)
        if self._badge:
            tx = p.fontMetrics().horizontalAdvance(label) + 6
            paint_badge(p, tx, (self.height() - 16) / 2, self._badge, FG_TERTIARY)

        # value box
        box = self.value_rect()
        fill = BG_HIGHLIGHT if focused else BG_RAISED
        if flashing:
            fill = ACCENT_DIM
        p.fillRect(box, QColor(fill))
        border = SEVERITY_COLOR.get(sev) if sev else (ACCENT if focused else BORDER)
        draw_frame(p, box, border)
        if focused:
            p.fillRect(QRectF(box.x(), box.y(), 3, box.height()), QColor(ACCENT))
        if sev:
            p.setBrush(QColor(SEVERITY_COLOR[sev]))
            p.setPen(Qt.NoPen)
            p.setRenderHint(QPainter.Antialiasing, True)
            p.drawEllipse(QRectF(box.right() - 12, box.y() + 4, 6, 6))
            p.setRenderHint(QPainter.Antialiasing, False)
            p.setBrush(Qt.NoBrush)
        self.paint_value(p, box.adjusted(10, 0, -12, 0), focused)

    def paint_value(self, p, rect, focused):
        pass

    def draw_blank(self, p, rect, blank="—"):
        p.setFont(self._value_font)
        p.setPen(QColor(FG_TERTIARY))
        text = f"{blank}   {self._hint}" if self._hint else blank
        text = p.fontMetrics().elidedText(text, Qt.ElideRight, int(rect.width()))
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, text)


class TextField(FieldBase):
    """Free text. Enter / click / F2 opens the editor; Enter or leaving the
    field commits, Escape cancels. `max_bytes` shows a live byte counter."""

    def __init__(self, label, max_bytes=None, placeholder="", validator=None, parent=None):
        super().__init__(label, parent)
        self._value = ""
        self.max_bytes = max_bytes
        self.placeholder = placeholder
        self.validator = validator
        self._edit = QLineEdit(self)
        self._edit.setFrame(False)
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: {BG_HIGHLIGHT}; color: {FG_PRIMARY}; border: none;"
            f" font-family: '{FONT_DISPLAY}'; font-size: {T_VALUE}pt; font-weight: 600;"
            f" selection-background-color: {ACCENT}; selection-color: {BG_BASE}; }}")
        self._edit.hide()
        self._edit.returnPressed.connect(self.commit)
        self._edit.textEdited.connect(lambda _: self.update())
        self._edit.installEventFilter(self)

    def value(self):
        return self._value

    def set_value(self, value):
        self._value = "" if value is None else str(value)
        if not self.is_editing():
            self.update()

    def is_editing(self):
        return self._edit.isVisible()

    def begin_edit(self, text=None):
        r = self.value_rect().adjusted(10, 5, -60 if self.max_bytes else -12, -5)
        self._edit.setGeometry(r.toRect())
        self._edit.setText(self._value if text is None else text)
        self._edit.show()
        self._edit.setFocus()
        if text is None:
            self._edit.selectAll()
        self.update()

    def commit(self):
        if not self.is_editing():
            return
        new = self._edit.text()
        self._edit.hide()
        self.setFocus()
        self.update()
        if self.validator:
            new = self.validator(new)
        if new != self._value:
            self._value = new
            self.edited.emit(new)

    def cancel(self):
        self._edit.hide()
        self.setFocus()
        self.update()

    def eventFilter(self, watched, event):
        if watched is self._edit:
            if event.type() == QEvent.KeyPress:
                if event.key() == Qt.Key_Escape:
                    self.cancel()
                    return True
                if event.key() in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab):
                    self.commit()
                    return False
            elif event.type() == QEvent.FocusOut and self.is_editing():
                QTimer.singleShot(0, self._commit_if_left)
        return False

    def _commit_if_left(self):
        if self.is_editing() and not self._edit.hasFocus():
            self.commit()

    def mousePressEvent(self, event):
        self.setFocus()
        if self.value_rect().contains(event.pos()):
            self.begin_edit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_F2):
            self.begin_edit()
            event.accept()
            return
        if event.key() == Qt.Key_Delete and self._value:
            self._value = ""
            self.edited.emit("")
            self.update()
            event.accept()
            return
        super().keyPressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.is_editing():
            self._edit.setGeometry(self.value_rect().adjusted(
                10, 5, -60 if self.max_bytes else -12, -5).toRect())

    def paint_value(self, p, rect, focused):
        text = self._edit.text() if self.is_editing() else self._value
        if self.max_bytes:
            n = len(text.encode("utf-8"))
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.4))
            p.setPen(QColor(WARN if n > self.max_bytes else FG_TERTIARY))
            p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, f"{n}/{self.max_bytes}")
            rect = rect.adjusted(0, 0, -44, 0)
        if self.is_editing():
            return
        if not self._value:
            self.draw_blank(p, rect, "—" if not self.placeholder else f"— {self.placeholder}")
            return
        p.setFont(self._value_font)
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self._value, Qt.ElideRight, int(rect.width())))


class SuggestField(TextField):
    """A TextField with a "▾" pick-from-list affordance: click it (or the
    chevron on its own) to open a PopupList of `suggestions` and fill the
    field with whichever one is picked — same effect as typing it by hand.

    Unlike ChoiceField, `suggestions` is NOT a closed set: this stays a
    plain free-typed TextField underneath, for values the game accepts as
    any string but where only a known subset has actually been observed
    (a .mis restart-position script name, an objective PARAMETER name...).
    Typing something not in the list is exactly as valid as picking one —
    there's no NOT-IN-LIST warning the way ChoiceField shows one, because
    off-list here isn't wrong, just unconfirmed."""

    def __init__(self, label, suggestions=(), max_bytes=None, placeholder="", parent=None):
        super().__init__(label, max_bytes=max_bytes, placeholder=placeholder, parent=parent)
        self.suggestions = [s for s in suggestions if s]   # blank is "no suggestion", not a real one
        self._popup = None

    def set_suggestions(self, suggestions):
        self.suggestions = [s for s in suggestions if s]
        self.update()

    def _chevron_rect(self):
        r = self.value_rect().adjusted(10, 0, -12, 0)
        return QRectF(r.right() - 22, r.y(), 22, r.height())

    def open_suggestions(self):
        if not self.suggestions:
            return
        from ui.dropdown import PopupList
        screen = self.window()
        popup = PopupList(screen, width=max(240, self.width()), height=320, own_keys=True)
        popup.set_title(self.label)
        current = self._edit.text() if self.is_editing() else self._value
        for s in self.suggestions:
            popup.add_row(s, s, selected=(s == current))
        popup.size_to(len(self.suggestions))
        popup.picked.connect(self._on_suggestion_picked)
        popup.open_at(self, screen, own_toggle=True)
        self._popup = popup

    def _on_suggestion_picked(self, value):
        if self.is_editing():
            self.cancel()
        if value != self._value:
            self._value = value
            self.edited.emit(value)
        self.update()

    def mousePressEvent(self, event):
        if self.suggestions and self._chevron_rect().contains(event.pos()):
            self.setFocus()
            if self._popup is not None and self._popup.isVisible():
                self._popup.close_popup()
            else:
                self.open_suggestions()
            return
        super().mousePressEvent(event)

    def paint_value(self, p, rect, focused):
        if self.suggestions:
            chev = self._chevron_rect()
            super().paint_value(p, rect.adjusted(0, 0, -22, 0), focused)
            if not self.is_editing():
                p.setFont(self._value_font)
                p.setPen(QColor(ACCENT if focused else FG_TERTIARY))
                p.drawText(chev, Qt.AlignCenter, "▾")
        else:
            super().paint_value(p, rect, focused)


class NumberField(FieldBase):
    """An integer stored as a string. Digits type the value directly (it
    commits after a pause, on Enter, or when enough digits are in);
    Left/Right step ±1, Shift ±5, PgUp/PgDn ±10; Delete clears to blank."""

    def __init__(self, label, lo=0, hi=99, allow_blank=True, parent=None):
        super().__init__(label, parent)
        self.lo, self.hi = lo, hi
        self.allow_blank = allow_blank
        self._value = ""           # the stored string, possibly off-range/non-numeric
        self._buffer = ""
        self._buffer_timer = QTimer(self)
        self._buffer_timer.setSingleShot(True)
        self._buffer_timer.timeout.connect(self._commit_buffer)

    def value(self):
        return self._value

    def set_value(self, value):
        self._value = "" if value is None else str(value).strip()
        self._buffer = ""
        self.update()

    def as_int(self):
        try:
            return int(self._value)
        except (TypeError, ValueError):
            return None

    def is_editing(self):
        return bool(self._buffer)

    def _emit(self, new):
        if new != self._value:
            self._value = new
            self.edited.emit(new)
        self.update()

    def step(self, delta):
        current = self.as_int()
        if current is None:
            current = max(self.lo, min(self.hi, 50 if self.hi >= 50 >= self.lo else self.lo))
            new = current
        else:
            new = max(self.lo, min(self.hi, current + delta))
        self._emit(str(new))

    def _commit_buffer(self):
        if not self._buffer:
            return
        value = int(self._buffer)
        self._buffer = ""
        self._emit(str(max(self.lo, min(self.hi, value))))

    def keyPressEvent(self, event):
        k, mods = event.key(), event.modifiers()
        text = event.text()
        if text and text.isdigit() and not (mods & Qt.ControlModifier):
            self._buffer += text
            if len(self._buffer) >= len(str(self.hi)):
                self._commit_buffer()
            else:
                self._buffer_timer.start(900)
                self.update()
            event.accept()
            return
        if self._buffer:
            if k in (Qt.Key_Return, Qt.Key_Enter):
                self._buffer_timer.stop()
                self._commit_buffer()
            elif k == Qt.Key_Backspace:
                self._buffer = self._buffer[:-1]
                self._buffer_timer.start(900)
                self.update()
            elif k == Qt.Key_Escape:
                self._buffer = ""
                self.update()
            else:
                self._commit_buffer()
                super().keyPressEvent(event)
                return
            event.accept()
            return
        if k in (Qt.Key_Left, Qt.Key_Right):
            step = 5 if mods & Qt.ShiftModifier else 1
            self.step(-step if k == Qt.Key_Left else step)
        elif k in (Qt.Key_PageUp, Qt.Key_PageDown):
            self.step(10 if k == Qt.Key_PageUp else -10)
        elif k == Qt.Key_Delete and self.allow_blank:
            self._emit("")
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def wheelEvent(self, event):
        if self.hasFocus():
            self.step(1 if event.angleDelta().y() > 0 else -1)
            event.accept()
        else:
            event.ignore()

    def mousePressEvent(self, event):
        # Missing entirely until now: every other FieldBase subclass
        # (TextField, ChoiceField...) grabs focus on click, but this one
        # never did — and a field registered with FocusManager runs under
        # Qt.TabFocus (see FocusManager.register), which does NOT focus a
        # widget on a plain mouse click the way the default policy would.
        # Net effect: clicking a NumberField looked like it did something
        # (the box highlights on focus-in from elsewhere) but typing right
        # after a click went nowhere, because the click itself never
        # actually moved keyboard focus onto the field.
        self.setFocus()

    def focusOutEvent(self, event):
        self._buffer_timer.stop()
        self._commit_buffer()
        super().focusOutEvent(event)

    def paint_value(self, p, rect, focused):
        p.setFont(self._value_font)
        if self._buffer:
            p.setPen(QColor(ACCENT))
            p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, self._buffer + "▏")
            return
        if not self._value:
            self.draw_blank(p, rect)
            return
        n = self.as_int()
        bad = n is None or not (self.lo <= n <= self.hi)
        p.setPen(QColor(WARN if bad else FG_PRIMARY))
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter, self._value)
        if focused:
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.4))
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, "type · ←→")


class RatingField(NumberField):
    """0-99 rating: label, bar, number, and the change against a reference
    (the previous season) as a delta and a ghost tick on the bar. Only the
    bar reacts to the mouse — clicking the label or number just focuses."""

    def __init__(self, label, parent=None):
        super().__init__(label, lo=0, hi=99, allow_blank=False, parent=parent)
        self.setFixedHeight(34)
        self.reference = None
        self._dragging = False

    def set_reference(self, value):
        try:
            self.reference = int(value)
        except (TypeError, ValueError):
            self.reference = None
        self.update()

    def value_rect(self):
        return QRectF(self.label_width, 2, self.width() - self.label_width, self.height() - 4)

    def _bar_rect(self):
        box = self.value_rect()
        return QRectF(box.x() + 10, box.center().y() - 3, box.width() - 10 - 84, 6)

    def _set_from_x(self, x):
        bar = self._bar_rect()
        if bar.width() > 0:
            ratio = max(0.0, min(1.0, (x - bar.x()) / bar.width()))
            self._emit(str(round(ratio * 99)))

    def mousePressEvent(self, event):
        self.setFocus()
        self._dragging = self._bar_rect().adjusted(-4, -12, 4, 12).contains(event.pos())
        if self._dragging:
            self._set_from_x(event.x())

    def mouseMoveEvent(self, event):
        if self._dragging and event.buttons() & Qt.LeftButton:
            self._set_from_x(event.x())

    def mouseReleaseEvent(self, event):
        self._dragging = False

    def paint_value(self, p, rect, focused):
        bar = self._bar_rect()
        n = self.as_int()
        p.fillRect(bar, QColor(BG_BASE))
        if n is not None:
            col = ACCENT if focused else (FG_SECONDARY if 0 <= n <= 99 else WARN)
            if self._issue:
                col = SEVERITY_COLOR[self._issue[0]]
            p.fillRect(QRectF(bar.x(), bar.y(), bar.width() * max(0, min(n, 99)) / 99,
                              bar.height()), QColor(col))
        if self.reference is not None:
            gx = bar.x() + bar.width() * max(0, min(self.reference, 99)) / 99
            p.fillRect(QRectF(gx - 1, bar.y() - 3, 2, bar.height() + 6), QColor(FG_TERTIARY))
        right = QRectF(bar.right() + 8, rect.y(), rect.right() - bar.right() - 8, rect.height())
        p.setFont(tracked_font(FONT_DISPLAY, T_VALUE, QFont.Bold, 0))
        if self._buffer:
            p.setPen(QColor(ACCENT))
            p.drawText(right, Qt.AlignLeft | Qt.AlignVCenter, self._buffer + "▏")
            return
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(right.x(), right.y(), 30, right.height()),
                   Qt.AlignRight | Qt.AlignVCenter, self._value or "—")
        if self.reference is not None and n is not None and n != self.reference:
            d = n - self.reference
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.Bold, 0))
            p.setPen(QColor(GREEN if d > 0 else DANGER_LITE))
            p.drawText(QRectF(right.x() + 34, right.y(), 40, right.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, f"{'+' if d > 0 else '−'}{abs(d)}")


class ChoiceField(FieldBase):
    """One value from a list. Left/Right step, Enter/click opens a searchable
    popup. A blank stored value shows `blank_label`; a value that isn't in the
    list shows in warning colour with NOT IN LIST and stays until changed."""

    def __init__(self, label, options=(), display=None, allow_blank=True,
                 blank_label="—", parent=None):
        super().__init__(label, parent)
        self.options = list(options)
        self.display = display or (lambda v: str(v).replace("_", " "))
        self.allow_blank = allow_blank
        self.blank_label = blank_label
        self.tag_for = None          # optional fn(value) -> (tag, color) for popup rows
        self.subtitle_for = None     # optional fn(value) -> str for popup rows
        self.popup_title = label
        self.off_list_badge = True     # False when `display` already explains it
        self._value = ""
        self._popup = None

    def value(self):
        return self._value

    def set_options(self, options):
        self.options = list(options)
        self.update()

    def set_value(self, value):
        self._value = "" if value is None else value
        self.update()

    def _cycle(self):
        return ([""] if self.allow_blank else []) + list(self.options)

    def _emit(self, value):
        if value != self._value:
            self._value = value
            self.edited.emit(value)
        self.update()

    def step(self, delta):
        cycle = self._cycle()
        if not cycle:
            return
        if self._value in cycle:
            i = (cycle.index(self._value) + delta) % len(cycle)
        else:
            # blank-but-not-allowed or off-list: land on the first real choice
            i = 0 if not self.allow_blank else (1 if len(cycle) > 1 else 0)
        self._emit(cycle[i])

    def toggle_popup(self):
        # A second click/Enter while the popup is already open closes it —
        # see DropdownRow._toggle_popup (ui/dropdown.py) for the full
        # reasoning; PopupList's own outside-click auto-close deliberately
        # doesn't fire for a click back on the field that opened it, so
        # this has to be the thing that decides "close" vs "open".
        if self._popup is not None and self._popup.isVisible():
            self._popup.close_popup()
            return
        self.open_popup()

    def open_popup(self):
        screen = self.window()
        # height=380 is only the CAP — size_to() below sizes the box to the
        # actual option count, so a short list doesn't open into a mostly
        # empty box.
        popup = PopupList(screen, width=max(260, int(self.width() - self.label_width)),
                          height=380, own_keys=True)
        popup.set_title(self.popup_title)
        if self.allow_blank:
            popup.add_row(self.blank_label, "", selected=(self._value == ""))
        for opt in self.options:
            tag, tag_col = self.tag_for(opt) if self.tag_for else ("", None)
            popup.add_row(self.display(opt), opt, tag=tag, tag_color=tag_col,
                          selected=(opt == self._value),
                          subtitle=self.subtitle_for(opt) if self.subtitle_for else "")
        popup.size_to(len(self.options) + (1 if self.allow_blank else 0))
        popup.picked.connect(self._emit)
        popup.closed.connect(lambda: self.setFocus())
        anchor = self
        popup.open_at(anchor, screen, own_toggle=True)
        cycle = self._cycle()
        if self._value in cycle:
            QTimer.singleShot(0, lambda: popup.set_highlight(cycle.index(self._value)))
        self._popup = popup

    def mousePressEvent(self, event):
        self.setFocus()
        if self.value_rect().contains(event.pos()):
            self.toggle_popup()

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key_Left, Qt.Key_Right):
            self.step(-1 if k == Qt.Key_Left else 1)
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.toggle_popup()
        elif k == Qt.Key_Delete and self.allow_blank:
            self._emit("")
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def paint_value(self, p, rect, focused):
        p.setFont(self._value_font)
        # chevron
        p.setPen(QColor(ACCENT if focused else FG_TERTIARY))
        p.drawText(rect, Qt.AlignRight | Qt.AlignVCenter, "▾")
        rect = rect.adjusted(0, 0, -16, 0)
        if self._value == "" or self._value is None:
            self.draw_blank(p, rect, self.blank_label)
            return
        off_list = self._value not in self.options
        text = self.display(self._value)
        if off_list and self.off_list_badge:
            tag_w = paint_badge(p, rect.right() - 86, rect.center().y() - 8, "NOT IN LIST", WARN)
            rect = rect.adjusted(0, 0, -tag_w - 8, 0)
            p.setFont(self._value_font)
        p.setPen(QColor(WARN if off_list else FG_PRIMARY))
        p.drawText(rect, Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(text, Qt.ElideRight, int(rect.width())))


class SegmentField(FieldBase):
    """A handful of mutually exclusive values shown side by side — every
    option visible at once, one click or one Left/Right to change."""

    def __init__(self, label, options, display=None, allow_blank=False, blank_label="—",
                 swatches=None, parent=None):
        super().__init__(label, parent)
        self.options = list(options)
        self.display = display or (lambda v: str(v).replace("_", " "))
        self.allow_blank = allow_blank
        self.blank_label = blank_label
        self.swatches = swatches or {}
        self._value = ""

    def value(self):
        return self._value

    def set_value(self, value):
        self._value = "" if value is None else value
        self.update()

    def _segments(self):
        segs = list(self.options)
        if self.allow_blank or self._value == "":
            segs = [""] + segs
        if self._value not in segs:
            segs.append(self._value)
        return segs

    def _rects(self):
        box = self.value_rect().adjusted(4, 4, -4, -4)
        segs = self._segments()
        w = box.width() / max(1, len(segs))
        return [(s, QRectF(box.x() + i * w, box.y(), w - 2, box.height())) for i, s in enumerate(segs)]

    def _emit(self, value):
        if value != self._value:
            self._value = value
            self.edited.emit(value)
        self.update()

    def step(self, delta):
        segs = [s for s in self._segments() if s != "" or self.allow_blank]
        segs = [s for s in segs if s in self.options or s == "" and self.allow_blank]
        if not segs:
            return
        if self._value in segs:
            i = max(0, min(len(segs) - 1, segs.index(self._value) + delta))
        else:
            i = 0
        self._emit(segs[i])

    def mousePressEvent(self, event):
        self.setFocus()
        for seg, r in self._rects():
            if r.contains(event.pos()) and (seg in self.options or (seg == "" and self.allow_blank)):
                self._emit(seg)
                return

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key_Left, Qt.Key_Right):
            self.step(-1 if k == Qt.Key_Left else 1)
            event.accept()
            return
        super().keyPressEvent(event)

    def paint_value(self, p, rect, focused):
        p.setFont(tracked_font(FONT_DISPLAY, T_LABEL, QFont.DemiBold, 0.4))
        for seg, r in self._rects():
            on = seg == self._value
            off_list = seg not in self.options and seg != ""
            if on:
                p.fillRect(r, QColor(ACCENT if focused else BORDER_EM))
            text = self.blank_label if seg == "" else self.display(seg)
            sw = self.swatches.get(seg)
            tx = r
            if sw:
                p.fillRect(QRectF(r.x() + 6, r.center().y() - 5, 10, 10), QColor(sw))
                tx = r.adjusted(14, 0, 0, 0)
            if on:
                p.setPen(QColor(BG_BASE if focused else FG_PRIMARY))
            else:
                p.setPen(QColor(WARN if off_list else FG_TERTIARY))
            p.drawText(tx, Qt.AlignCenter,
                       p.fontMetrics().elidedText(text, Qt.ElideRight, int(tx.width() - 4)))


class AssetField(FieldBase):
    """A path relative to a folder: thumbnail, status (OK / MISSING / SIZE),
    and a browse popup over the files that actually exist. Enter or click
    opens the browser; F2 or a click on the path types it by hand."""

    browse_requested = pyqtSignal()

    def __init__(self, label, spec=None, parent=None):
        super().__init__(label, parent)
        self.setFixedHeight(48)
        self.spec = spec or {}
        self.root = ""
        self._value = ""
        self._status = ("empty", "not set", 0)
        self._thumb = QPixmap()
        self._edit = QLineEdit(self)
        self._edit.setFrame(False)
        self._edit.setStyleSheet(
            f"QLineEdit {{ background: {BG_HIGHLIGHT}; color: {FG_PRIMARY}; border: none;"
            f" font-family: '{FONT_DISPLAY}'; font-size: {T_VALUE}pt; }}")
        self._edit.hide()
        self._edit.returnPressed.connect(self._commit_text)
        self._edit.installEventFilter(self)

    def value_rect(self):
        return QRectF(self.label_width, 3, self.width() - self.label_width, self.height() - 6)

    def value(self):
        return self._value

    def set_root(self, root):
        self.root = root or ""
        self._refresh()

    def set_value(self, value):
        self._value = value or ""
        self._refresh()

    def status(self):
        return self._status

    def _refresh(self):
        self._status = asset_status(self.root, self._value, self.spec)
        path = self._value.replace("%", "1", 1) if "%" in self._value else self._value
        full = os.path.join(self.root, path) if self._value else ""
        ext = os.path.splitext(full)[1].lower()
        self._thumb = load_pixmap(full, 96) if ext in (".png", ".jpg", ".jpeg", ".bmp") else QPixmap()
        self.setToolTip(f"{self.spec.get('note', '')}\n{os.path.join(self.root, self._value)}"
                        if self._value else self.spec.get("note", ""))
        self.update()

    def is_editing(self):
        return self._edit.isVisible()

    def begin_text_edit(self):
        box = self.value_rect()
        self._edit.setGeometry(QRect(int(box.x() + 56), int(box.y() + 8),
                                     int(box.width() - 56 - 120), int(box.height() - 16)))
        self._edit.setText(self._value)
        self._edit.show()
        self._edit.setFocus()
        self._edit.selectAll()

    def _commit_text(self):
        new = self._edit.text().strip().replace("\\", "/")
        self._edit.hide()
        self.setFocus()
        if new != self._value:
            self._value = new
            self._refresh()
            self.edited.emit(new)

    def set_picked(self, rel):
        if rel != self._value:
            self._value = rel
            self._refresh()
            self.edited.emit(rel)

    def eventFilter(self, watched, event):
        if watched is self._edit and event.type() == QEvent.KeyPress and event.key() == Qt.Key_Escape:
            self._edit.hide()
            self.setFocus()
            return True
        if watched is self._edit and event.type() == QEvent.FocusOut and self.is_editing():
            QTimer.singleShot(0, lambda: self._commit_text() if self.is_editing()
                              and not self._edit.hasFocus() else None)
        return False

    def mousePressEvent(self, event):
        self.setFocus()
        box = self.value_rect()
        browse = QRectF(box.right() - 70, box.y(), 70, box.height())
        if browse.contains(event.pos()) or QRectF(box.x(), box.y(), 56, box.height()).contains(event.pos()):
            self.browse_requested.emit()
        elif box.contains(event.pos()):
            self.begin_text_edit()

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.browse_requested.emit()
        elif k == Qt.Key_F2:
            self.begin_text_edit()
        elif k == Qt.Key_Delete and self._value:
            self.set_picked("")
        else:
            super().keyPressEvent(event)
            return
        event.accept()

    def paint_value(self, p, rect, focused):
        box = self.value_rect()
        tr = QRectF(box.x() + 8, box.y() + 5, 40, box.height() - 10)
        p.fillRect(tr, QColor(BG_BASE))
        if not self._thumb.isNull():
            scaled = self._thumb.scaled(tr.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
            p.drawPixmap(int(tr.center().x() - scaled.width() / 2),
                         int(tr.center().y() - scaled.height() / 2), scaled)
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRect(tr)

        state, detail, _ = self._status
        colour, word = STATUS_STYLE.get(state, (FG_TERTIARY, state.upper()))
        text_rect = QRectF(tr.right() + 10, box.y(), box.width() - (tr.right() - box.x()) - 90,
                           box.height())
        if not self.is_editing():
            p.setFont(self._value_font)
            if self._value:
                p.setPen(QColor(FG_PRIMARY))
                p.drawText(text_rect.adjusted(0, 3, 0, -box.height() / 2 + 2),
                           Qt.AlignLeft | Qt.AlignBottom,
                           p.fontMetrics().elidedText(self._value, Qt.ElideMiddle,
                                                      int(text_rect.width())))
                p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.4))
                p.setPen(QColor(colour if state != "ok" else FG_TERTIARY))
                p.drawText(text_rect.adjusted(0, box.height() / 2, 0, -3),
                           Qt.AlignLeft | Qt.AlignTop, f"{word} · {detail}" if state != "ok" else detail)
            else:
                self.draw_blank(p, text_rect, "— not set")
        # browse button
        br = QRectF(box.right() - 76, box.y() + 7, 66, box.height() - 14)
        p.setPen(QPen(QColor(ACCENT if focused else BORDER_EM), 1))
        p.drawRect(br)
        p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.Bold, 1.0))
        p.setPen(QColor(ACCENT if focused else FG_SECONDARY))
        p.drawText(br, Qt.AlignCenter, "BROWSE")


class ToggleGrid(QWidget):
    """A grid of on/off chips (special skills). One focus stop: arrows move
    the cursor inside the grid, Space/Enter toggles; Up/Down at the top or
    bottom row leave the grid."""

    toggled = pyqtSignal(str, bool)

    def __init__(self, items, columns=3, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.items = list(items)          # [(key, label)]
        self.columns = columns
        self.on = set()
        self.cursor = 0
        self.key = None
        self.rows = (len(self.items) + columns - 1) // columns
        self.setFixedHeight(self.rows * 38)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_values(self, on_keys):
        self.on = set(on_keys)
        self.update()

    def _rect(self, i):
        w = self.width() / self.columns
        return QRectF((i % self.columns) * w, (i // self.columns) * 38, w - 6, 32)

    def _toggle(self, i):
        key = self.items[i][0]
        state = key not in self.on
        (self.on.add if state else self.on.discard)(key)
        self.update()
        self.toggled.emit(key, state)

    def mousePressEvent(self, event):
        self.setFocus()
        for i in range(len(self.items)):
            if self._rect(i).contains(event.pos()):
                self.cursor = i
                self._toggle(i)
                return

    def keyPressEvent(self, event):
        k = event.key()
        n = len(self.items)
        if k in (Qt.Key_Space, Qt.Key_Return, Qt.Key_Enter):
            self._toggle(self.cursor)
        elif k == Qt.Key_Left and self.cursor % self.columns:
            self.cursor -= 1
        elif k == Qt.Key_Right and self.cursor % self.columns < self.columns - 1 and self.cursor + 1 < n:
            self.cursor += 1
        elif k == Qt.Key_Up and self.cursor >= self.columns:
            self.cursor -= self.columns
        elif k == Qt.Key_Down and self.cursor + self.columns < n:
            self.cursor += self.columns
        else:
            super().keyPressEvent(event)
            return
        self.update()
        event.accept()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        focused = self.hasFocus()
        for i, (key, label) in enumerate(self.items):
            r = self._rect(i)
            on = key in self.on
            p.setPen(QPen(QColor(ACCENT if (focused and i == self.cursor) else
                                 (ACCENT if on else BORDER)), 2 if focused and i == self.cursor else 1))
            p.setBrush(QColor(ACCENT if on else BG_RAISED))
            p.drawRoundedRect(r, 4, 4)
            p.setPen(QColor(BG_BASE if on else FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, T_LABEL, QFont.Bold if on else QFont.DemiBold, 0.4))
            p.drawText(r.adjusted(10, 0, -6, 0), Qt.AlignLeft | Qt.AlignVCenter,
                       ("✓  " if on else "") + label)


class LayerStackField(QWidget):
    """The ordered skin layer stack: the base skin, the overlay images painted
    over it bottom to top, and the gloves image that always ends up on top.

    One focus stop, like ToggleGrid — the rows are data, not widgets, so a
    rebuild never leaves dead widgets in the focus manager. Up/Down pick a
    row (and leave the stack at either end), Shift+Up/Down move the selected
    layer, Delete removes it, Enter on the last row adds one.
    """

    edited = pyqtSignal(object)          # the new list of layer values
    add_requested = pyqtSignal()
    row_activated = pyqtSignal(int)      # a layer row was opened (replace it)

    ROW_H = 30
    BASE, ADD, GLOVES = -1, -2, -3

    def __init__(self, parent=None, show_base=True):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.key = None
        self.layers = []          # [{"value", "label", "thumb", "tag", "tag_color"}]
        #: a pinned first row below the layers — the stock/custom skin swatch
        #: for the one combined stack; a dedicated per-kind stack (see
        #: screens/player_tabs.py::AppearanceTab.LAYER_SECTIONS) has nothing
        #: to pin there, so it's created with show_base=False instead.
        self.show_base = show_base
        self.base = {"label": "stock skin", "thumb": "", "swatch": None}
        self.top = None           # gloves row, same shape as a layer
        self.cursor = 0           # index into self._rows()
        self._hover = -1
        self._fit()

    # ── contents ─────────────────────────────────────────────────────────
    def set_base(self, label, thumb="", swatch=None):
        self.base = {"label": label, "thumb": thumb, "swatch": swatch}
        self.update()

    def set_top(self, row):
        self.top = row
        self._fit()

    def set_layers(self, rows):
        self.layers = list(rows)
        self.cursor = max(0, min(self.cursor, len(self._rows()) - 1))
        self._fit()

    def values(self):
        return [r["value"] for r in self.layers]

    def _rows(self):
        """Row kinds top to bottom: gloves (if any), layers reversed (the
        top-most layer first, the way the stack is painted), base (unless
        show_base is False), add."""
        rows = []
        if self.top:
            rows.append((self.GLOVES, self.top))
        for i in range(len(self.layers) - 1, -1, -1):
            rows.append((i, self.layers[i]))
        if self.show_base:
            rows.append((self.BASE, self.base))
        rows.append((self.ADD, None))
        return rows

    def _fit(self):
        self.setFixedHeight(len(self._rows()) * self.ROW_H + 4)
        self.update()

    def selected_layer(self):
        kind, _ = self._rows()[self.cursor] if self._rows() else (self.ADD, None)
        return kind if kind >= 0 else None

    # ── edits ────────────────────────────────────────────────────────────
    def move(self, delta):
        i = self.selected_layer()
        if i is None:
            return False
        j = i + delta
        if not 0 <= j < len(self.layers):
            return False
        values = self.values()
        values[i], values[j] = values[j], values[i]
        self.layers[i], self.layers[j] = self.layers[j], self.layers[i]
        # follow the layer: rows are painted top-first, so moving up in the
        # stack means moving up the list index.
        self.cursor -= delta
        self.update()
        self.edited.emit(values)
        return True

    def remove(self):
        i = self.selected_layer()
        if i is None:
            return False
        values = self.values()
        del values[i]
        del self.layers[i]
        self.cursor = max(0, min(self.cursor, len(self._rows()) - 1))
        self._fit()
        self.edited.emit(values)
        return True

    def select_value(self, value):
        for pos, (kind, row) in enumerate(self._rows()):
            if kind >= 0 and row.get("value") == value:
                self.cursor = pos
                self.update()
                return

    # ── mouse ────────────────────────────────────────────────────────────
    def _row_rect(self, pos):
        return QRectF(0, 2 + pos * self.ROW_H, self.width(), self.ROW_H - 2)

    def _buttons(self, rect):
        """(up, down, remove) hotspots on the right of a layer row. 24px
        square with a 4px gap — 20px/2px was a tight, easy-to-mis-click
        cluster for a mouse (three 22px-pitch targets touching)."""
        y, h = rect.y() + 4, rect.height() - 8
        x = rect.right() - 28
        out = []
        for _ in range(3):
            out.append(QRectF(x, y, 24, h))
            x -= 28
        return list(reversed(out))          # up, down, remove

    def mouseMoveEvent(self, event):
        hit = int((event.pos().y() - 2) // self.ROW_H)
        if hit != self._hover:
            self._hover = hit
            self.update()

    def leaveEvent(self, event):
        self._hover = -1
        self.update()

    def mousePressEvent(self, event):
        self.setFocus()
        rows = self._rows()
        pos = int((event.pos().y() - 2) // self.ROW_H)
        if not 0 <= pos < len(rows):
            return
        self.cursor = pos
        self.update()
        kind, _ = rows[pos]
        if kind == self.ADD:
            self.add_requested.emit()
            return
        if kind >= 0:
            up, down, rm = self._buttons(self._row_rect(pos))
            if up.contains(event.pos()):
                self.move(1)            # up the stack = later in the list
            elif down.contains(event.pos()):
                self.move(-1)
            elif rm.contains(event.pos()):
                self.remove()

    def mouseDoubleClickEvent(self, event):
        kind = self.selected_layer()
        if kind is not None:
            self.row_activated.emit(kind)

    # ── keys ─────────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        k, mods = event.key(), event.modifiers()
        rows = self._rows()
        shift = bool(mods & Qt.ShiftModifier)
        if k in (Qt.Key_Up, Qt.Key_Down) and shift:
            if self.move(1 if k == Qt.Key_Up else -1):
                event.accept()
                return
        elif k == Qt.Key_Up and self.cursor > 0:
            self.cursor -= 1
        elif k == Qt.Key_Down and self.cursor < len(rows) - 1:
            self.cursor += 1
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and self.remove():
            event.accept()
            return
        elif k in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            kind, _ = rows[self.cursor]
            if kind == self.ADD:
                self.add_requested.emit()
            elif kind >= 0:
                self.row_activated.emit(kind)
        else:
            super().keyPressEvent(event)
            return
        self.update()
        event.accept()

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        focused = self.hasFocus()
        small = tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.4)
        value_font = tracked_font(FONT_DISPLAY, T_LABEL, QFont.DemiBold, 0.3)
        for pos, (kind, row) in enumerate(self._rows()):
            r = self._row_rect(pos)
            on = pos == self.cursor
            hovered = pos == self._hover
            p.fillRect(r, QColor(BG_HIGHLIGHT if (on and focused) else
                                 (BG_RAISED if (on or hovered) else BG_CARD)))
            draw_frame(p, r, ACCENT if (on and focused) else BORDER)
            if kind == self.ADD:
                p.setFont(small)
                p.setPen(QColor(ACCENT if (on and focused) else FG_SECONDARY))
                p.drawText(r.adjusted(10, 0, 0, 0), Qt.AlignLeft | Qt.AlignVCenter,
                           "+  ADD LAYER")
                continue

            # position label
            p.setFont(small)
            p.setPen(QColor(FG_TERTIARY))
            if kind == self.BASE:
                tag = "BASE"
            elif kind == self.GLOVES:
                tag = "TOP"
            else:
                tag = str(kind + 1)
            p.drawText(QRectF(r.x() + 6, r.y(), 30, r.height()), Qt.AlignLeft | Qt.AlignVCenter, tag)

            # thumbnail / swatch
            tr = QRectF(r.x() + 38, r.y() + 4, 44, r.height() - 8)
            p.fillRect(tr, QColor(BG_BASE))
            swatch = row.get("swatch")
            pix = load_pixmap(row.get("thumb", ""), 96)
            if not pix.isNull():
                scaled = pix.scaled(tr.size().toSize(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap(int(tr.center().x() - scaled.width() / 2),
                             int(tr.center().y() - scaled.height() / 2), scaled)
            elif swatch:
                p.fillRect(tr.adjusted(1, 1, -1, -1), QColor(swatch))
            p.setPen(QPen(QColor(BORDER), 1))
            p.drawRect(tr)

            # name and chip
            text_rect = QRectF(tr.right() + 10, r.y(), r.width() - (tr.right() - r.x()) - 100,
                               r.height())
            p.setFont(value_font)
            p.setPen(QColor(FG_PRIMARY if kind != self.BASE else FG_SECONDARY))
            p.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(row.get("label", ""), Qt.ElideMiddle,
                                                  int(text_rect.width())))
            if row.get("tag"):
                paint_badge(p, r.right() - 88, r.center().y() - 8, row["tag"],
                            row.get("tag_color") or FG_TERTIARY)
            elif kind >= 0 and (on or hovered):
                up, down, rm = self._buttons(r)
                p.setFont(small)
                for rect, glyph, colour in ((up, "▲", FG_SECONDARY), (down, "▼", FG_SECONDARY),
                                            (rm, "✕", DANGER_LITE)):
                    p.setPen(QPen(QColor(BORDER), 1))
                    p.drawRect(rect)
                    p.setPen(QColor(colour))
                    p.drawText(rect, Qt.AlignCenter, glyph)


class FrameStrip(QWidget):
    """Thumbnails for a %-pattern (ball frames, banners, back numbers)."""

    def __init__(self, count, thumb=(64, 32), max_show=None, parent=None):
        super().__init__(parent)
        self.count = count
        self.tw, self.th = thumb
        self.max_show = max_show or count
        self.root, self.pattern = "", ""
        self._pix = []
        self.setFixedHeight(self.th + 22)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_pattern(self, root, pattern):
        self.root, self.pattern = root or "", pattern or ""
        self._pix = []
        if self.pattern:
            for i in range(1, self.count + 1):
                rel = expand_pattern(self.pattern, i) if "%" in self.pattern else self.pattern
                full = os.path.join(self.root, rel)
                if i <= self.max_show:
                    self._pix.append((i, load_pixmap(full, max(self.tw, self.th) * 2),
                                      os.path.isfile(full)))
                else:
                    self._pix.append((i, None, os.path.isfile(full)))
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        if not self.pattern:
            p.setPen(QColor(FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.4))
            p.drawText(self.rect(), Qt.AlignLeft | Qt.AlignVCenter, "no pattern set")
            return
        present = sum(1 for _, _, ok in self._pix if ok)
        x = 0
        gap = 6
        shown = [e for e in self._pix if e[1] is not None]
        label_w = 96
        avail = self.width() - label_w
        per = self.tw + gap
        fit = max(1, int(avail // per))
        for i, pix, ok in shown[:fit]:
            r = QRectF(x, 0, self.tw, self.th)
            p.fillRect(r, QColor(BG_BASE))
            if pix is not None and not pix.isNull():
                scaled = pix.scaled(self.tw - 2, self.th - 2, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                p.drawPixmap(int(r.center().x() - scaled.width() / 2),
                             int(r.center().y() - scaled.height() / 2), scaled)
            p.setPen(QPen(QColor(BORDER if ok else DANGER_LITE), 1))
            p.drawRect(r)
            if not ok:
                p.drawLine(r.topLeft(), r.bottomRight())
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL - 1, QFont.DemiBold, 0.2))
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(QRectF(x, self.th + 2, self.tw, 16), Qt.AlignCenter, str(i))
            x += per
        p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.4))
        p.setPen(QColor(GREEN if present == self.count else WARN))
        lr = QRectF(self.width() - label_w, 0, label_w, self.th)
        p.drawText(lr, Qt.AlignRight | Qt.AlignVCenter, f"{present}/{self.count}\npresent")


def browse_assets(screen, anchor, root, spec, current, on_pick, title="choose file"):
    """Popup over the files under `root` that fit `spec`. Numbered series
    (ball_1.png, ball_2.png…) collapse to their %-pattern when the spec
    expects frames, so picking one picks the whole series."""
    exts = tuple(spec.get("ext", (".png",))) if spec else (".png",)
    frames = spec.get("frames", 0) if spec else 0
    entries = []
    seen_patterns = set()
    if root and os.path.isdir(root):
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames.sort()
            for fname in sorted(filenames):
                if not fname.lower().endswith(exts) or ".deleted-" in fname:
                    continue
                rel = os.path.relpath(os.path.join(dirpath, fname), root).replace(os.sep, "/")
                m = re.search(r"_(\d+)(\.\w+)$", rel)
                if frames and m:
                    pattern = rel[:m.start(1)] + "%" + m.group(2)
                    if pattern in seen_patterns:
                        continue
                    seen_patterns.add(pattern)
                    entries.append((pattern, rel))
                else:
                    entries.append((rel, rel))
    popup = PopupList(screen, width=520, height=460, own_keys=True)
    popup.set_title(title)
    popup.add_row("— none (clear)", "", selected=(current == ""))
    for value, sample in entries:
        full = os.path.join(root, sample)
        small = (spec or {}).get("size")
        icon = load_pixmap(full, 64) if small and max(small) <= 512 else None
        tag = ""
        if "%" in value:
            n = sum(1 for i in range(1, frames + 1) if os.path.isfile(os.path.join(root, expand_pattern(value, i))))
            tag = f"{n}/{frames}"
        popup.add_row(value, value, tag=tag, selected=(value == current), icon=icon)
    if not entries:
        popup.add_row("no matching files in this folder", None, disabled=True)
    popup.size_to(len(entries) + 1)
    popup.picked.connect(lambda v: on_pick(v) if v is not None else None)
    popup.closed.connect(lambda: anchor.setFocus() if anchor is not None else None)
    popup.open_at(anchor, screen)
    return popup


# ═════════════════════════════════════════════════════════════════════════
# Layout
# ═════════════════════════════════════════════════════════════════════════
class FieldGrid(QWidget):
    """Fields in N columns, one row height, labels aligned per column."""

    def __init__(self, columns=2, parent=None, h_spacing=24, v_spacing=6):
        super().__init__(parent)
        self.setObjectName("fieldGrid")
        self.setStyleSheet("QWidget#fieldGrid { background: transparent; }")
        self.columns = columns
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(h_spacing)
        self.grid.setVerticalSpacing(v_spacing)
        self._row = 0
        self._col = 0
        self._fields = []   # (field, col)

    def add(self, field, span=1):
        if self._col + span > self.columns:
            self._row += 1
            self._col = 0
        self.grid.addWidget(field, self._row, self._col, 1, span)
        if isinstance(field, FieldBase):
            self._fields.append((field, self._col))
        self._col += span
        if self._col >= self.columns:
            self._row += 1
            self._col = 0
        self.align_labels()
        return field

    def add_widget(self, widget, span=None):
        span = span or self.columns
        if self._col:
            self._row += 1
            self._col = 0
        self.grid.addWidget(widget, self._row, 0, 1, span)
        self._row += 1
        return widget

    def newline(self):
        if self._col:
            self._row += 1
            self._col = 0

    def align_labels(self, cap=170):
        by_col = {}
        for f, col in self._fields:
            by_col.setdefault(col, []).append(f)
        for col, fields in by_col.items():
            width = min(cap, max(f.label_text_width() for f in fields) + 16)
            for f in fields:
                f.label_width = max(80, width)
                f.update()

    def fields(self):
        return [f for f, _ in self._fields]


class SectionCard(Card):
    """A card with a title row and an optional right-hand widget."""

    def __init__(self, title, right=None, stripe=None, parent=None):
        super().__init__(stripe=stripe, parent=parent)
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(18, 12, 18, 14)
        self.v.setSpacing(8)
        head = QHBoxLayout()
        head.setSpacing(8)
        self.title_lbl = eyebrow_label(title, color=ACCENT, size=T_SECTION)
        head.addWidget(self.title_lbl)
        head.addStretch(1)
        self.head = head
        if right is not None:
            head.addWidget(right)
        self.v.addLayout(head)

    def set_title(self, title):
        self.title_lbl.setText(title.upper())

    def add(self, widget, stretch=0):
        self.v.addWidget(widget, stretch)
        return widget

    def add_layout(self, layout, stretch=0):
        self.v.addLayout(layout, stretch)
        return layout


class Note(QLabel):
    """Wrapped explanatory text in the readable de-emphasised colour."""

    def __init__(self, text="", color=FG_TERTIARY, size=T_SMALL, parent=None):
        super().__init__(text, parent)
        self.setWordWrap(True)
        self.setStyleSheet(f"color: {color}; background: transparent;"
                           f" font-family: '{FONT_BODY}'; font-size: {size}pt;")
        # The stylesheet decides what is PAINTED, the widget's own font decides
        # what Qt measures for the layout. Left at the default they disagree
        # and the last line of the note gets clipped.
        font = QFont(FONT_BODY)
        font.setPointSize(size)
        self.setFont(font)
        # One line's worth is the floor even when the row around it is tight.
        self.setMinimumHeight(QFontMetrics(font).height())


class TabStrip(QWidget):
    """Focusable tab bar. Click a tab, or Left/Right while it has focus."""

    changed = pyqtSignal(int)

    def __init__(self, titles, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(42)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.titles = list(titles)
        self.counts = [None] * len(self.titles)   # (n, severity)
        self._index = 0
        self._font = tracked_font(FONT_DISPLAY, 13, QFont.Bold, track=1.4)

    def index(self):
        return self._index

    def set_index(self, i, notify=True):
        i = max(0, min(len(self.titles) - 1, i))
        if i == self._index:
            return
        self._index = i
        self.update()
        if notify:
            self.changed.emit(i)

    def set_count(self, i, n, severity=None):
        self.counts[i] = (n, severity) if n else None
        self.update()

    def _rects(self):
        fm = QFontMetrics(self._font)
        x = 0
        out = []
        for i, t in enumerate(self.titles):
            text = t.upper()
            # Qt versions/platforms disagree on whether the advance includes the
            # letter spacing: take the widest measure, and add the spacing back,
            # so a title is never wider than its tab.
            w = (max(fm.horizontalAdvance(text), fm.boundingRect(text).width())
                 + round(len(text) * self._font.letterSpacing()) + 44)
            if self.counts[i]:
                w += 26
            out.append(QRectF(x, 0, w, self.height()))
            x += w
        return out

    def mousePressEvent(self, event):
        self.setFocus()
        for i, r in enumerate(self._rects()):
            if r.contains(event.pos()):
                self.set_index(i)

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Left, Qt.Key_Right):
            self.set_index(self._index + (-1 if event.key() == Qt.Key_Left else 1))
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        focused = self.hasFocus()
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), QColor(BORDER))
        for i, r in enumerate(self._rects()):
            on = i == self._index
            p.setFont(self._font)
            p.setPen(QColor(FG_PRIMARY if on else FG_TERTIARY))
            tr = r.adjusted(22, 0, -22 - (26 if self.counts[i] else 0), 0)
            p.drawText(tr, Qt.AlignLeft | Qt.AlignVCenter | Qt.TextDontClip, self.titles[i].upper())
            if on:
                p.fillRect(QRectF(r.x() + 12, self.height() - 3, r.width() - 24, 3),
                           QColor(ACCENT))
                if focused:
                    p.setPen(QPen(QColor(ACCENT), 1))
                    p.setBrush(Qt.NoBrush)
                    p.drawRect(r.adjusted(4, 4, -4, -6))
            if self.counts[i]:
                n, sev = self.counts[i]
                col = QColor(SEVERITY_COLOR.get(sev, FG_TERTIARY))
                c = QRectF(tr.right() + 6, r.center().y() - 9, 20, 18)
                p.setPen(Qt.NoPen)
                p.setBrush(col)
                p.drawRoundedRect(c, 9, 9)
                p.setPen(QColor(BG_BASE))
                p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.Bold, 0))
                p.drawText(c, Qt.AlignCenter, str(n) if n < 100 else "99")


class TabPage(QScrollArea):
    """One tab's content. Scrolls only if the window is too small for it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWidgetResizable(True)
        self.setFrameShape(QScrollArea.NoFrame)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setStyleSheet(f"QScrollArea {{ background: transparent; border: none; }}")
        self.body = QWidget()
        self.body.setObjectName("tabBody")
        self.body.setStyleSheet(f"QWidget#tabBody {{ background: {BG_BASE}; }}")
        self.viewport().setStyleSheet(f"background: {BG_BASE};")
        self.layout_ = QVBoxLayout(self.body)
        self.layout_.setContentsMargins(0, 14, 6, 6)
        self.layout_.setSpacing(12)
        self.setWidget(self.body)


# ═════════════════════════════════════════════════════════════════════════
# Shell: header, footer, list pane, tabs
# ═════════════════════════════════════════════════════════════════════════
class SeasonPicker(QWidget):
    """Season selector plus a menu of season actions."""

    season_picked = pyqtSignal(str)
    action = pyqtSignal(str)          # "add" | "duplicate" | "delete"

    def __init__(self, parent=None, display=None):
        super().__init__(parent)
        self.setObjectName("seasonPicker")
        self.setStyleSheet("QWidget#seasonPicker { background: transparent; }")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.choice = ChoiceField("Season", allow_blank=False,
                                  display=display or (lambda v: str(v)))
        self.choice.popup_title = "season"
        self.choice.label_width = 64
        self.choice.setFixedWidth(230)
        self.choice.edited.connect(lambda v: self.season_picked.emit(v))
        h.addWidget(self.choice)
        self.menu_btn = compact_button("SEASON ▾", height=EDITOR_ROW_H)
        self.menu_btn.clicked.connect(self.open_menu)
        h.addWidget(self.menu_btn)

    def set_seasons(self, seasons, current):
        self.choice.set_options(seasons)
        self.choice.set_value(current or "")

    def open_menu(self):
        popup = open_season_menu(self.menu_btn, self.window(), lambda a: self.action.emit(a))
        popup.closed.connect(lambda: self.menu_btn.setFocus())


def open_season_menu(anchor, screen, on_pick):
    """The Add / Duplicate / Delete season menu, anchored to any widget —
    shared by `SeasonPicker` and the player editor's seasons pane."""
    popup = PopupList(screen, width=280, height=200, own_keys=True)
    popup.set_title("season actions")
    popup.add_row("Add season…", "add", subtitle="blank or copied")
    popup.add_row("Duplicate this season…", "duplicate", subtitle="to another year")
    popup.add_row("Delete this season…", "delete", tag="", tag_color=DANGER_LITE)
    popup.size_to(3)
    popup.picked.connect(on_pick)
    popup.open_at(anchor, screen)
    return popup


class EditorHeader(QWidget):
    back_clicked = pyqtSignal()
    issues_clicked = pyqtSignal()

    def __init__(self, parent=None, compact=False):
        super().__init__(parent)
        self.setObjectName("editorHeader")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#editorHeader {{ background: {BG_PANEL};"
                           f" border-bottom: 2px solid {ACCENT}; }}")
        self.setFixedHeight(60 if compact else 96)
        h = QHBoxLayout(self)
        h.setContentsMargins(24, 10, 24, 10)
        h.setSpacing(16)

        self.back_btn = StyledButton("‹ BACK", "ghost")
        self.back_btn.setFixedHeight(38)
        self.back_btn.clicked.connect(self.back_clicked.emit)
        h.addWidget(self.back_btn, alignment=Qt.AlignVCenter)

        # A screen with no per-record header content (EditorScreen.
        # COMPACT_HEADER) skips the avatar/eyebrow/subtitle/chips block
        # rather than rendering it empty — the 96px bar was sized for that
        # block, so at 60px it would just clip. eyebrow/subtitle/chips still
        # exist as attributes, just never placed in a layout, so
        # `_refresh_chrome`'s unconditional eyebrow.setText/set_chips calls
        # have somewhere harmless to land instead of raising.
        self.avatar = Avatar(64)
        self.eyebrow = display_label("", T_SMALL, QFont.DemiBold, track=1.8, color=FG_TERTIARY)
        self.subtitle = display_label("", T_SMALL, QFont.DemiBold, track=0.6,
                                      color=FG_TERTIARY, upper=False)
        self.chips = QHBoxLayout()
        self.chips.setSpacing(6)

        if compact:
            self.avatar.hide()
            self.title = display_label("—", T_TITLE, QFont.Bold, track=0.6, upper=False)
            h.addWidget(self.title, stretch=1, alignment=Qt.AlignVCenter)
        else:
            h.addWidget(self.avatar, alignment=Qt.AlignVCenter)
            col = QVBoxLayout()
            col.setSpacing(0)
            col.addWidget(self.eyebrow)
            self.title = display_label("—", T_DISPLAY, QFont.Bold, track=0.6, upper=False)
            self.title.setMinimumHeight(max(40, QFontMetrics(self.title.font()).height()))
            col.addWidget(self.title)
            chips_row = QHBoxLayout()
            chips_row.setSpacing(6)
            chips_row.addWidget(self.subtitle)
            chips_row.addLayout(self.chips)
            chips_row.addStretch(1)
            col.addLayout(chips_row)
            h.addLayout(col, stretch=1)

        self.season_slot = QHBoxLayout()
        h.addLayout(self.season_slot)

        self.dirty_lbl = display_label("", T_LABEL, QFont.Bold, track=1.0, color=ACCENT)
        self.dirty_lbl.setAlignment(Qt.AlignRight)
        self.issues_btn = StyledButton("NO ISSUES", "neutral")
        self.issues_btn.setFixedHeight(32)
        self.issues_btn.clicked.connect(self.issues_clicked.emit)
        if compact:
            # Stacked (below) needs ~50px for the two lines plus the gap
            # between them — taller than this whole bar. Side by side fits
            # the fixed-height issues button with room to spare.
            right = QHBoxLayout()
            right.setSpacing(10)
            right.addWidget(self.dirty_lbl, alignment=Qt.AlignVCenter)
            right.addWidget(self.issues_btn, alignment=Qt.AlignVCenter)
        else:
            right = QVBoxLayout()
            right.setSpacing(4)
            right.addWidget(self.dirty_lbl)
            right.addWidget(self.issues_btn)
        h.addLayout(right)

    def set_chips(self, chips):
        """chips: [(text, color)]"""
        while self.chips.count():
            widget = self.chips.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        for text, color in chips:
            self.chips.addWidget(Badge(text, color))

    def set_dirty(self, n):
        self.dirty_lbl.setText(f"● {n} UNSAVED" if n else "")

    def set_issues(self, issues):
        counts = {}
        for _, _, sev in issues:
            counts[sev] = counts.get(sev, 0) + 1
        if not issues:
            self.issues_btn.setText("✓ NO ISSUES")
            colour = GREEN
        else:
            parts = []
            for sev, word in (("error", "ERROR"), ("warn", "WARNING"), ("info", "NOTE")):
                if counts.get(sev):
                    n = counts[sev]
                    parts.append(f"{n} {word}{'S' if n > 1 else ''}")
            self.issues_btn.setText("  ·  ".join(parts))
            colour = SEVERITY_COLOR[worst(counts)]
        self.issues_btn.setStyleSheet(
            self.issues_btn.styleSheet() + f"QPushButton {{ color: {colour}; }}")


class EditorFooter(QWidget):
    revert_clicked = pyqtSignal()
    save_clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("editorFooter")
        self.setAttribute(Qt.WA_StyledBackground, True)
        self.setStyleSheet(f"QWidget#editorFooter {{ background: {BG_PANEL};"
                           f" border-top: 1px solid {BORDER}; }}")
        self.setFixedHeight(56)
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 20, 0)
        h.setSpacing(12)
        self.hints = HintBar(framed=False)
        self.hints.setMinimumWidth(420)
        h.addWidget(self.hints, stretch=3)
        self.status = display_label("", T_LABEL, QFont.DemiBold, track=0.6,
                                    color=FG_SECONDARY, upper=False)
        h.addWidget(self.status, stretch=2)
        self.target = display_label("", T_SMALL, QFont.DemiBold, track=0.4,
                                    color=FG_TERTIARY, upper=False)
        h.addWidget(self.target)
        self.revert_btn = compact_button("REVERT")
        self.revert_btn.setMinimumWidth(96)
        self.revert_btn.clicked.connect(self.revert_clicked.emit)
        h.addWidget(self.revert_btn)
        self.save_btn = StyledButton("SAVE", "primary")
        self.save_btn.setFixedHeight(BTN_HEIGHT_SM)
        self.save_btn.setMinimumWidth(120)
        self.save_btn.clicked.connect(self.save_clicked.emit)
        h.addWidget(self.save_btn)
        self._fade = QTimer(self)
        self._fade.setSingleShot(True)
        self._fade.timeout.connect(self._fade_status)

    def set_status(self, text, color=FG_SECONDARY):
        self.status.setText(text)
        self.status.setStyleSheet(
            f"color: {color}; background: transparent; font-family: '{FONT_DISPLAY}';"
            f" font-size: {T_LABEL}pt; font-weight: 600;")
        self._fade.start(5000)

    def _fade_status(self):
        self.status.setStyleSheet(
            f"color: {FG_TERTIARY}; background: transparent; font-family: '{FONT_DISPLAY}';"
            f" font-size: {T_LABEL}pt; font-weight: 600;")


class EditorShell(QWidget):
    """Header / (list pane, full height | [identity pane] / mid pane | tabs
    | preview pane) / footer. The list pane runs the full height of the
    body, same as a plain two-pane screen — the identity strip sits only
    above the season/tabs/preview column to its right, not over the list.
    Screens fill the list pane and the tab pages; the shell owns nothing
    about the data."""

    LIST_WIDTH = 300
    MID_WIDTH = 170
    PREVIEW_WIDTH = 360

    def __init__(self, tab_titles, parent=None, mid_pane=False, compact_header=False,
                identity_pane=False, preview_pane=False):
        super().__init__(parent)
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = EditorHeader(compact=compact_header)
        root.addWidget(self.header)

        body = QWidget()
        body.setObjectName("editorBody")
        body.setStyleSheet(f"QWidget#editorBody {{ background: {BG_BASE}; }}")
        bh = QHBoxLayout(body)
        bh.setContentsMargins(20, 12, 20, 8)
        bh.setSpacing(20)

        self.list_pane = QWidget()
        self.list_pane.setObjectName("listPane")
        self.list_pane.setStyleSheet("QWidget#listPane { background: transparent; }")
        self.list_pane.setFixedWidth(self.LIST_WIDTH)
        self.list_layout = QVBoxLayout(self.list_pane)
        self.list_layout.setContentsMargins(0, 0, 0, 0)
        self.list_layout.setSpacing(8)
        bh.addWidget(self.list_pane)

        list_sep = QFrame()
        list_sep.setFrameShape(QFrame.VLine)
        list_sep.setFixedWidth(1)
        list_sep.setStyleSheet(f"background: {BORDER}; border: none;")
        bh.addWidget(list_sep)

        right_col = QVBoxLayout()
        right_col.setSpacing(12)

        # Optional strip above the season/tabs/preview row (not over the
        # list pane) — a screen asks for it (EditorScreen.IDENTITY_PANE) for
        # record-level content that doesn't belong to any one season or tab
        # (the player editor's name/birthdate/commentary). Absent for a
        # screen that doesn't fill it (team editor, today).
        self.identity_pane = None
        self.identity_layout = None
        if identity_pane:
            self.identity_pane = QWidget()
            self.identity_pane.setObjectName("identityPane")
            self.identity_pane.setStyleSheet("QWidget#identityPane { background: transparent; }")
            self.identity_layout = QVBoxLayout(self.identity_pane)
            self.identity_layout.setContentsMargins(0, 0, 0, 0)
            right_col.addWidget(self.identity_pane)
            hsep = QFrame()
            hsep.setFrameShape(QFrame.HLine)
            hsep.setFixedHeight(1)
            hsep.setStyleSheet(f"background: {BORDER}; border: none;")
            right_col.addWidget(hsep)

        bl = QHBoxLayout()
        bl.setSpacing(20)

        # Optional second pane between the list and the tabs — a screen asks
        # for it (EditorScreen.MID_PANE) rather than it always existing, so a
        # screen that doesn't fill it (team editor, today) gets the plain
        # two-pane layout back with no dead gap where an empty pane would sit.
        # Its separator is ACCENT rather than a plain border: it's the one
        # currently used (the season list sits in this pane) — a visible
        # thread from the selected season to the tab content beside it.
        self.mid_pane = None
        self.mid_layout = None
        if mid_pane:
            self.mid_pane = QWidget()
            self.mid_pane.setObjectName("midPane")
            self.mid_pane.setStyleSheet("QWidget#midPane { background: transparent; }")
            self.mid_pane.setFixedWidth(self.MID_WIDTH)
            self.mid_layout = QVBoxLayout(self.mid_pane)
            self.mid_layout.setContentsMargins(0, 0, 0, 0)
            self.mid_layout.setSpacing(14)
            bl.addWidget(self.mid_pane)

            sep = QFrame()
            sep.setFrameShape(QFrame.VLine)
            sep.setFixedWidth(2)
            sep.setStyleSheet(f"background: {ACCENT}; border: none;")
            bl.addWidget(sep)

        self.right_layout = right = QVBoxLayout()
        right.setSpacing(0)
        self.tabs = TabStrip(tab_titles)
        right.addWidget(self.tabs)
        self.stack = QStackedWidget()
        self.pages = []
        for _ in tab_titles:
            page = TabPage()
            self.stack.addWidget(page)
            self.pages.append(page)
        right.addWidget(self.stack, stretch=1)
        bl.addLayout(right, stretch=1)

        # Optional fixed-width pane at the far right, always visible
        # regardless of which tab is active — the player editor's 3D
        # preview, which isn't a property of any one tab.
        self.preview_pane = None
        self.preview_layout = None
        if preview_pane:
            sep2 = QFrame()
            sep2.setFrameShape(QFrame.VLine)
            sep2.setFixedWidth(1)
            sep2.setStyleSheet(f"background: {BORDER}; border: none;")
            bl.addWidget(sep2)

            self.preview_pane = QWidget()
            self.preview_pane.setObjectName("previewPane")
            self.preview_pane.setStyleSheet("QWidget#previewPane { background: transparent; }")
            self.preview_pane.setFixedWidth(self.PREVIEW_WIDTH)
            self.preview_layout = QVBoxLayout(self.preview_pane)
            self.preview_layout.setContentsMargins(0, 0, 0, 0)
            self.preview_layout.setSpacing(10)
            bl.addWidget(self.preview_pane)

        right_col.addLayout(bl, stretch=1)
        bh.addLayout(right_col, stretch=1)
        root.addWidget(body, stretch=1)

        self.footer = EditorFooter()
        root.addWidget(self.footer)
        self.tabs.changed.connect(self.stack.setCurrentIndex)

    def page(self, i):
        return self.pages[i]


# ═════════════════════════════════════════════════════════════════════════
# Overlays: issues, confirm / form dialogs
# ═════════════════════════════════════════════════════════════════════════
def open_issues_popover(screen, anchor, issues, on_pick):
    """issues: [(key, message, severity)] — picking one reveals its field."""
    popup = PopupList(screen, width=560, height=440, own_keys=True)
    popup.set_title(f"{len(issues)} issue{'s' if len(issues) != 1 else ''}")
    order = sorted(issues, key=lambda i: SEVERITY_RANK.get(i[2], 9))
    for key, msg, sev in order:
        popup.add_row(msg, key, tag=sev.upper(), tag_color=SEVERITY_COLOR.get(sev))
    if not issues:
        popup.add_row("nothing to fix — the game will read this record as written", None,
                      disabled=True)
    popup.size_to(max(1, len(issues)))
    popup.picked.connect(lambda k: on_pick(k) if k is not None else None)
    popup.open_at(anchor, screen)
    return popup


class ConfirmDialog(QWidget):
    """A modal card over a dimmed screen. No nested event loop: the choice
    arrives through `on_choice(role)`. Keys never reach the screen behind."""

    def __init__(self, screen, title, text, buttons, on_choice, cancel_role="cancel",
                 content=None, width=520):
        super().__init__(screen)
        self._on_choice = on_choice
        self._cancel_role = cancel_role
        self._done = False
        self.setGeometry(screen.rect())
        self.card = Card(stripe=ACCENT)
        self.card.setParent(self)
        self.card.setFixedWidth(width)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(26, 20, 26, 20)
        v.setSpacing(12)
        v.addWidget(display_label(title, T_TITLE, QFont.Bold, track=0.8, upper=False))
        if text:
            v.addWidget(Note(text, color=FG_SECONDARY, size=T_LABEL))
        self.content = content
        if content is not None:
            v.addWidget(content)
        row = QHBoxLayout()
        row.addStretch(1)
        self.buttons = []
        for label, variant, role in buttons:
            b = StyledButton(label, variant)
            b.setFixedHeight(BTN_HEIGHT_SM)
            b.setFocusPolicy(Qt.StrongFocus)
            b.clicked.connect(lambda _=False, r=role: self.choose(r))
            row.addWidget(b)
            self.buttons.append((b, role))
        v.addLayout(row)
        self.card.adjustSize()
        self._place()
        self.show()
        self.raise_()
        first = self._focusables()
        (first[0] if first else self.buttons[-1][0]).setFocus()
        screen.installEventFilter(self)

    def _focusables(self):
        out = []
        if self.content is not None:
            for w in self.content.findChildren(QWidget):
                if isinstance(w, FieldBase) and w.isVisible() and w.isEnabled():
                    out.append(w)
        return out

    def _place(self):
        self.setGeometry(self.parentWidget().rect())
        self.card.adjustSize()
        self.card.move((self.width() - self.card.width()) // 2,
                       max(40, (self.height() - self.card.height()) // 2))

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self._place()
        return False

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 170))

    def mousePressEvent(self, event):
        event.accept()

    def choose(self, role):
        if self._done:
            return
        self._done = True
        self.parentWidget().removeEventFilter(self)
        self.hide()
        self.deleteLater()
        self._on_choice(role)

    def keyPressEvent(self, event):
        k = event.key()
        focus = QApplication.focusWidget()
        order = self._focusables() + [b for b, _ in self.buttons]
        if k == Qt.Key_Escape or (k == Qt.Key_Backspace and not isinstance(focus, QLineEdit)):
            self.choose(self._cancel_role)
        elif k in (Qt.Key_Return, Qt.Key_Enter):
            for b, role in self.buttons:
                if focus is b:
                    self.choose(role)
                    break
            else:
                # Enter on a field that didn't take it: the primary action
                primary = [r for b, r in self.buttons if r not in (self._cancel_role,)]
                if primary and not self._focusables():
                    self.choose(primary[-1])
        elif k in (Qt.Key_Up, Qt.Key_Down, Qt.Key_Tab, Qt.Key_Backtab) or (
                k in (Qt.Key_Left, Qt.Key_Right) and isinstance(focus, StyledButton)):
            if focus in order:
                i = order.index(focus)
                step = -1 if k in (Qt.Key_Up, Qt.Key_Left, Qt.Key_Backtab) else 1
                order[(i + step) % len(order)].setFocus()
            elif order:
                order[0].setFocus()
        event.accept()


class FormDialog(ConfirmDialog):
    """A dialog whose content is a FieldGrid; `fields` maps name → field."""

    def __init__(self, screen, title, text, fields, buttons, on_choice,
                 cancel_role="cancel", width=560, footer=None):
        grid = FieldGrid(columns=1)
        self.fields = fields
        for f in fields.values():
            grid.add(f)
        content = QWidget()
        content.setObjectName("formContent")
        content.setStyleSheet("QWidget#formContent { background: transparent; }")
        cv = QVBoxLayout(content)
        cv.setContentsMargins(0, 0, 0, 0)
        cv.setSpacing(8)
        cv.addWidget(grid)
        self.footer_note = Note("", color=FG_TERTIARY)
        cv.addWidget(self.footer_note)
        if footer:
            self.footer_note.setText(footer)
        super().__init__(screen, title, text, buttons, on_choice, cancel_role, content, width)

    def values(self):
        return {k: f.value() for k, f in self.fields.items()}
