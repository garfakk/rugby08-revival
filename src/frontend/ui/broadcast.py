"""
ui/broadcast.py — Broadcast-sports widget kit
=================================================
The pad-native controls the redesign is built from: SelectorRow (replaces
QComboBox, whose native popup has no workable gamepad story — ui/dropdown.py's
PopupList is the one popup that does, driven by the owning screen), Card,
Chip, DeviceTile (controller assignment icon tile), SegmentedToggle and
HintBar. Custom-painted so the built
app matches the approved mockups (scratchpad/mockup/gen_mockups.py) exactly,
not just approximately.
"""
from PyQt5.QtWidgets import QWidget, QLabel, QFrame, QSizePolicy, QHBoxLayout, QVBoxLayout
from PyQt5.QtGui import QPainter, QColor, QFont, QFontMetrics, QPen
from PyQt5.QtCore import Qt, pyqtSignal, pyqtProperty, QRectF

from ui.theme import (
    BG_BASE, BG_PANEL, BG_CARD, BG_RAISED, BG_HIGHLIGHT, DROPDOWN_BG, DROPDOWN_BORDER,
    SQUAD_PICKER_ACTIVE_BG, SQUAD_PICKER_INACTIVE_BG,
    SQUAD_PICKER_ACTIVE_TEXT, SQUAD_PICKER_INACTIVE_TEXT,
    SQUAD_PICKER_BORDER, SQUAD_PICKER_DIVIDER,
    BORDER, BORDER_EM, ACCENT, WARN,
    HOME_TINT, AWAY_TINT, GREEN, BLOCKED,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED,
    FONT_DISPLAY, FONT_BODY,
)
from ui.icons import arrow, gamepad_icon, keyboard_icon, link_icon
from shared.user_prefs import user_prefs


def tracked_font(family, size, weight=QFont.Normal, track=1.0):
    f = QFont(family, size, weight)
    f.setStyleStrategy(QFont.PreferAntialias)
    f.setLetterSpacing(QFont.AbsoluteSpacing, track)
    return f


_CSS_WEIGHT = {QFont.Bold: 700, QFont.DemiBold: 600, QFont.Medium: 500, QFont.Normal: 400}


def label_css(size, weight=QFont.Bold, color=FG_PRIMARY, family=FONT_DISPLAY):
    """Font declarations a QLabel must carry in its OWN stylesheet: the
    app-wide QSS sets `font-size` on QWidget, and QSS beats setFont(), so a
    programmatic font alone is silently downgraded to 10pt."""
    return (f"color: {color}; background: transparent;"
            f" font-family: '{family}'; font-size: {size}pt;"
            f" font-weight: {_CSS_WEIGHT.get(weight, 400)};")


def display_label(text, size, weight=QFont.Bold, track=1.0, color=FG_PRIMARY,
                  family=FONT_DISPLAY, upper=True):
    """QLabel that actually renders at the size asked for, with letter
    spacing (which QSS can't express) coming from the QFont."""
    lbl = QLabel(text.upper() if upper else text)
    font = tracked_font(family, size, weight, track)
    lbl.setFont(font)
    lbl.setStyleSheet(label_css(size, weight, color, family))
    # Never let a label end up shorter than its own text: the layout is sized
    # in pixels while the font is in points, so a row that fits at one scaling
    # factor or font can clip the bottom of the glyphs at another.
    lbl.setMinimumHeight(QFontMetrics(font).height())
    return lbl


def page_header(title: str, breadcrumb: str = None, right: str = None, on_back=None) -> QWidget:
    header = QWidget()
    header.setFixedHeight(76)
    header.setObjectName("pageHeader")
    # Scoped by #pageHeader: an unscoped border/background rule set via
    # setStyleSheet() on a container cascades to unstyled QLabel children in
    # Qt (they pick up the parent's border) — scoping avoids that.
    header.setStyleSheet(f"QWidget#pageHeader {{ background: {BG_PANEL}; border-bottom: 3px solid {ACCENT}; }}")
    hl = QHBoxLayout(header)
    hl.setContentsMargins(28, 0, 28, 0)

    stripe = QFrame()
    stripe.setFixedWidth(6)
    stripe.setStyleSheet(f"background: {ACCENT};")
    hl.addWidget(stripe)
    hl.addSpacing(14)

    # A real, clickable button — the hint bar's "B  BACK" is only a legend
    # for the keyboard/pad action, not a control, so mouse-only navigation
    # had no way back off a screen that relies solely on it.
    if on_back is not None:
        from ui.widgets import StyledButton
        back_btn = StyledButton("‹ BACK", "ghost")
        back_btn.setFixedHeight(38)
        back_btn.clicked.connect(on_back)
        hl.addWidget(back_btn, alignment=Qt.AlignVCenter)
        hl.addSpacing(18)

    tcol = QVBoxLayout()
    tcol.setSpacing(0)
    tcol.addStretch(1)
    tcol.addWidget(display_label(title, 24, QFont.Bold, track=1.2))
    if breadcrumb:
        tcol.addWidget(display_label(breadcrumb, 10, QFont.DemiBold, track=1.6,
                                     color=FG_SECONDARY, family=FONT_BODY))
    tcol.addStretch(1)
    hl.addLayout(tcol)
    hl.addStretch(1)

    if right:
        hl.addWidget(display_label(right, 12, QFont.DemiBold, track=1.4, color=FG_SECONDARY),
                     alignment=Qt.AlignVCenter)
    return header


def eyebrow_label(text: str, color: str = FG_SECONDARY, size: int = 12) -> QLabel:
    return display_label(text, size, QFont.DemiBold, track=2.2, color=color)


CARD_TRANSLUCENT_ALPHA = 222   # out of 255 — a light tint: clearly still a
                               # panel, the background behind it only
                               # barely bleeds through as texture


def draw_frame(p, rect, color, width=1):
    """Outline `rect` with four filled strips instead of a stroked pen. The
    app runs under a fractional QT_SCALE_FACTOR (see main.py), where a 1px
    pen on an integer edge lands between device pixels and can vanish
    entirely; a filled strip always covers at least one whole pixel."""
    r = QRectF(rect)
    c = QColor(color)
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    p.fillRect(QRectF(x, y, w, width), c)
    p.fillRect(QRectF(x, y + h - width, w, width), c)
    p.fillRect(QRectF(x, y + width, width, h - 2 * width), c)
    p.fillRect(QRectF(x + w - width, y + width, width, h - 2 * width), c)


class Card(QFrame):
    """A bordered panel with an optional left accent stripe — the base
    surface every screen is built from. `translucent=True` lets whatever
    is behind the card (the atmosphere layer) show faintly through the
    fill — the border stays fully opaque so the panel still reads as a
    distinct surface, not just a tinted region."""

    def __init__(self, stripe: str = None, parent=None, translucent: bool = False):
        super().__init__(parent)
        self._stripe = stripe
        self._bg_opacity = 1.0
        self._translucent = translucent
        self.setAutoFillBackground(False)
        # Qt auto-applies the app-wide stylesheet's blanket `QWidget {
        # background-color }` rule as a styled-background fill underneath
        # any custom paintEvent, for any class the stylesheet's selectors
        # match — which is every QWidget subclass, Card included — entirely
        # independent of what paintEvent below actually draws. Normally
        # invisible (this auto-fill is the same BG_BASE colour paintEvent
        # draws over it every time), it became a real bug once bg_opacity
        # could make paintEvent draw nothing: the auto-fill still landed,
        # as a flat, hard-edged box exactly the card's size, wherever
        # anything other than a flat BG_BASE now shows through (the
        # atmosphere layer). Scoping it to transparent makes this card's
        # own paintEvent the only thing that ever paints its background.
        self.setObjectName("card")
        self.setStyleSheet("QFrame#card { background: transparent; }")

    def set_stripe(self, color: str):
        self._stripe = color
        self.update()

    def _get_bg_opacity(self):
        return self._bg_opacity

    def _set_bg_opacity(self, value):
        self._bg_opacity = value
        self.update()

    # Animatable independently of a QGraphicsOpacityEffect, which would
    # also fade this card's children — the kickoff sequence needs the
    # panel itself (fill, border, stripe) to fade out while a child (the
    # 3D player stage) stays fully opaque.
    bg_opacity = pyqtProperty(float, _get_bg_opacity, _set_bg_opacity)

    def paintEvent(self, event):
        if self._bg_opacity <= 0.0:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing, False)
        p.setOpacity(self._bg_opacity)
        fill = QColor(BG_CARD)
        if self._translucent:
            fill.setAlpha(CARD_TRANSLUCENT_ALPHA)
        p.fillRect(self.rect(), fill)
        draw_frame(p, self.rect(), BORDER)
        if self._stripe:
            p.fillRect(QRectF(0, 0, 4, self.height()), QColor(self._stripe))


class Chip(QWidget):
    def __init__(self, text: str, color: str, filled: bool = False, parent=None):
        super().__init__(parent)
        self._text = text.upper()
        self._color = color
        self._filled = filled
        self.setFixedHeight(22)
        f = tracked_font(FONT_BODY, 11, QFont.DemiBold, track=1.2)
        self._font = f
        from PyQt5.QtGui import QFontMetrics
        w = QFontMetrics(f).horizontalAdvance(self._text)
        self.setFixedWidth(w + 20)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(self._font)
        col = QColor(self._color)
        if self._filled:
            p.fillRect(self.rect(), col)
            p.setPen(QColor(BG_BASE))
        else:
            draw_frame(p, self.rect(), col)
            p.setPen(col)
        p.drawText(self.rect(), Qt.AlignCenter, self._text)


class SelectorRow(QWidget):
    """The core pad-native control: <  VALUE  > . Left/Right change the
    value in place while focused (consumed here, never bubbled — see
    app/input.py for why that's what lets arrow-key screen navigation and
    in-place value editing coexist). Optionally carries a link/split toggle
    (season & tournament pickers) or a read-only "mirror" state."""

    changed = pyqtSignal()
    link_toggled = pyqtSignal()

    def __init__(self, label: str, values=None, display=str, compact=False, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self._compact = compact
        if compact:
            # Deliberately small: a slim chip that takes as little room as it
            # can while staying readable and clickable.
            self.setFixedHeight(44)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        else:
            self.setMinimumHeight(64)
            self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._label = label
        self._values = list(values) if values else []
        self._display = display
        self._index = 0
        self._free_text = None       # overrides values[] display when set
        self._mirror = False         # read-only "· CENTRE" style row
        self._mirror_target = "centre"
        self._disabled = False
        self._link = None            # None = no icon, True/False = linked/split
        self._status = None          # (text, color)
        self._problem = ""           # validation message from the screen, if any
        self._popup = None           # the open dropdown popup, if any (see user_prefs.dropdown_menus)
        self._popup_open = False
        # A short list (team, kit) is faster to click through with < / >
        # than to open a popup for — set True to always use arrow-cycling
        # on this instance regardless of the global dropdown_menus setting.
        self._force_arrows = False
        self._fw_click_boundary = None   # set by _paint_compact once it knows where the text sits

    def set_force_arrows(self, on: bool = True):
        self._force_arrows = on
        self.update()

    def _use_popup(self):
        return user_prefs.dropdown_menus and not self._force_arrows

    # ── state ────────────────────────────────────────────────────────────
    def set_values(self, values, index=0):
        self._values = list(values)
        self._index = max(0, min(index, len(self._values) - 1)) if self._values else 0
        self._free_text = None
        self.update()

    def current(self):
        if self._free_text is not None:
            return None
        if not self._values:
            return None
        return self._values[self._index]

    def has_values(self):
        return bool(self._values)

    def index_of(self, value):
        try:
            return self._values.index(value)
        except ValueError:
            return None

    def set_index(self, i):
        if not self._values:
            return
        self._index = max(0, min(i, len(self._values) - 1))
        self.update()

    def set_free_text(self, text):
        self._free_text = text
        self.update()

    def set_mirror(self, mirror: bool, target: str = "centre"):
        self._mirror = mirror
        self._mirror_target = target
        self.update()

    def set_disabled_visual(self, disabled: bool):
        self._disabled = disabled
        self.setEnabled(not disabled)
        self.update()

    def set_link(self, linked):
        self._link = linked
        self.update()

    def set_status(self, text, color):
        self._status = (text, color) if text else None
        self.update()

    def set_problem(self, message=None):
        """A validation message from the screen; None clears it. Neither
        paint path (compact especially) has room to print the message
        itself, so it only tints the row (label + border, matching
        TextRow's WARN severity) and surfaces the text as a tooltip."""
        self._problem = message or ""
        self.setToolTip(self._problem)
        self.update()

    def _display_text(self):
        if self._free_text is not None:
            return self._free_text
        if not self._values:
            return ""
        return self._display(self._values[self._index])

    # ── interaction ──────────────────────────────────────────────────────
    def _step(self, d):
        if self._mirror or self._disabled or not self._values:
            return
        self._index = (self._index + d) % len(self._values)
        self.update()
        self.changed.emit()

    def _toggle_popup(self):
        # A second click/Enter on a row whose popup is already open closes
        # it — see DropdownRow._toggle_popup for why this has to be an
        # explicit check here rather than relying on the popup's own
        # outside-click auto-close (that doesn't fire for a click back on
        # the anchor, by design — see PopupList.eventFilter).
        if self._popup is not None and self._popup.isVisible():
            self._popup.close_popup()
            return
        self._open_popup()

    def _open_popup(self):
        """Swap the arrow-cycling interaction for a scrollable popup list —
        see user_prefs.dropdown_menus. Left/Right still step in place
        regardless of the setting (pad/keyboard users keep the fast path;
        see the module docstring on why SelectorRow owns Left/Right itself),
        this only changes what a click (or Enter/Space) does."""
        if self._mirror or self._disabled or not self._values or self._free_text is not None:
            return
        from ui.dropdown import PopupList   # deferred: ui.dropdown imports this module
        screen = self.window()
        # No title — see DropdownRow._open_popup; list_bg matches the
        # picked-row highlight so the open list reads as one lit block.
        # height=340 is only the CAP — size_to() below sizes the box to the
        # actual row count, so a short list doesn't open with a slab of
        # empty space under its last row.
        popup = PopupList(screen, width=max(240, self.width()), height=340, own_keys=True,
                           show_title=False, list_bg=DROPDOWN_BORDER)
        current = self.current()
        current_i = None
        # selected, not disabled — see DropdownRow._open_popup.
        for i, v in enumerate(self._values):
            popup.add_row(self._display(v).upper(), v, selected=(v == current))
            if v == current:
                current_i = i
        popup.size_to(len(self._values))
        popup.picked.connect(self._on_popup_picked)
        popup.closed.connect(self._on_popup_closed)
        popup.open_at(self, screen, gap=0, own_toggle=True)
        if current_i is not None:
            popup.set_highlight(current_i, scroll=True)
        self._popup = popup
        self._popup_open = True
        self.update()

    def _on_popup_closed(self):
        self._popup_open = False
        self.update()

    def _on_popup_picked(self, value):
        try:
            self._index = self._values.index(value)
        except ValueError:
            return
        self.update()
        self.changed.emit()

    def keyPressEvent(self, event):
        if self._mirror or self._disabled:
            return super().keyPressEvent(event)
        if self._use_popup() and event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self._toggle_popup(); event.accept(); return
        if event.key() == Qt.Key_Left:
            self._step(-1); event.accept(); return
        if event.key() == Qt.Key_Right:
            self._step(1); event.accept(); return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # No setFocus() — clicking steps/opens the popup without pulling
        # keyboard/pad focus onto the row; FocusManager still does that for
        # arrow-key/pad navigation.
        if self._link is not None:
            link_rect = QRectF(self.width() - 40, 0, 40, self.height())
            if link_rect.contains(event.pos()):
                self.link_toggled.emit()
                return
        if self._mirror or self._disabled:
            return
        if self._use_popup():
            self._toggle_popup()
            return
        # Left arrow steps back; the text and the right arrow (everything
        # else) both step forward — clicking the value itself is the
        # "advance" action, not a dead zone. force_arrows rows hug their
        # arrows to the text (see _paint_compact) rather than sitting at
        # the box edges, so the split has to follow where the text
        # actually starts, not a fixed thirds-of-width guess — otherwise,
        # on a wide row with short text, "the left arrow" and "the text"
        # both land in the same middle third and the left arrow silently
        # does nothing but step forward.
        boundary = self._fw_click_boundary if self._force_arrows and self._fw_click_boundary is not None \
            else self.width() / 3
        if event.x() < boundary:
            self._step(-1)
        else:
            self._step(1)

    def paintEvent(self, event):
        p = QPainter(self)
        if self._compact:
            self._paint_compact(p)
            return
        w, h = self.width(), self.height()
        link_w = 46 if self._link is not None else 0
        body_w = w - link_w
        focused = self.hasFocus()

        # BG_RAISED at rest, not BG_CARD — this row sits on a Card filled
        # with BG_CARD, so the two used to be indistinguishable except by
        # the (also too-faint) border.
        bg = DROPDOWN_BG if self._popup_open else (
            BG_HIGHLIGHT if (focused and not self._mirror) else (BG_PANEL if self._mirror else BG_RAISED))
        p.fillRect(QRectF(0, 0, body_w, h), QColor(bg))
        border = DROPDOWN_BORDER if self._popup_open else (WARN if self._problem else BORDER)
        p.setPen(QPen(QColor(border), 2))
        p.drawRect(QRectF(0, 0, body_w, h).adjusted(0, 0, -1, -1))
        if focused and not self._mirror:
            p.fillRect(QRectF(0, 0, 3, h), QColor(ACCENT))

        lab_col = WARN if self._problem else (FG_MUTED if self._disabled else FG_SECONDARY)
        p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.DemiBold, track=1.6))
        p.setPen(QColor(lab_col))
        p.drawText(QRectF(14, 6, body_w - 100, 18), Qt.AlignLeft | Qt.AlignVCenter, self._label.upper())

        if self._mirror:
            p.setFont(tracked_font(FONT_BODY, 10, QFont.DemiBold, track=1.0))
            p.setPen(QColor(FG_MUTED))
            p.drawText(QRectF(body_w - 90, 6, 80, 18), Qt.AlignRight | Qt.AlignVCenter,
                       f". {self._mirror_target.upper()}")

        val_col = BLOCKED if self._disabled else (ACCENT if focused and not self._mirror else
                   (FG_SECONDARY if self._mirror else FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 19, QFont.Bold, track=0.6))
        p.setPen(QColor(val_col))
        val_rect = QRectF(28, h * 0.30, body_w - 56, h * 0.62)
        elided = p.fontMetrics().elidedText(self._display_text().upper(), Qt.ElideRight,
                                            int(val_rect.width()))
        p.drawText(val_rect, Qt.AlignCenter, elided)

        if not self._disabled and not self._mirror:
            ac = ACCENT if focused else FG_MUTED
            if self._use_popup():
                arrow(p, body_w - 20, h * 0.62, "down", ac, size=6)
            else:
                arrow(p, 22, h * 0.62, "left", ac, size=7)
                arrow(p, body_w - 22, h * 0.62, "right", ac, size=7)

        if self._status:
            txt, col = self._status
            p.setFont(tracked_font(FONT_BODY, 10, QFont.DemiBold, track=1.0))
            fm = p.fontMetrics()
            tw = fm.horizontalAdvance(txt) + 16
            chip_rect = QRectF(body_w - tw - 12, 8, tw, 18)
            p.setPen(QPen(QColor(col), 1))
            p.drawRect(chip_rect.adjusted(0, 0, -1, -1))
            p.drawText(chip_rect, Qt.AlignCenter, txt)

        if self._link is not None:
            p.setPen(QPen(QColor(BORDER_EM), 1))
            p.drawLine(int(body_w + 10), 10, int(body_w + 10), h - 10)
            link_icon(p, body_w + link_w / 2 + 4, h / 2, self._link, s=1.0,
                      color=ACCENT if self._link else FG_MUTED)

    def _paint_compact(self, p):
        """Small corner badge — flanks the crest on the team cards instead of
        a full-width row (season top-left, competition top-right)."""
        w, h = self.width(), self.height()
        focused = self.hasFocus()
        if self._force_arrows:
            # Chip style, no box — matches TeamNamePicker: focus shows as
            # the text/arrows turning ACCENT below, not a fill or border.
            pass
        else:
            # BG_RAISED at rest, not BG_CARD — this row sits on a Card
            # filled with BG_CARD, so the two used to be indistinguishable
            # except by the (also too-faint) border.
            bg = DROPDOWN_BG if self._popup_open else (
                BG_HIGHLIGHT if (focused and not self._mirror) else (BG_PANEL if self._mirror else BG_RAISED))
            p.fillRect(QRectF(0, 0, w, h), QColor(bg))
            border = DROPDOWN_BORDER if self._popup_open else (WARN if self._problem else BORDER)
            p.setPen(QPen(QColor(border), 2))
            p.drawRect(QRectF(0, 0, w, h).adjusted(0, 0, -1, -1))
            if focused and not self._mirror:
                p.fillRect(QRectF(0, 0, w, 3), QColor(ACCENT))

        lab_col = WARN if self._problem else (FG_MUTED if self._disabled else FG_SECONDARY)
        p.setFont(tracked_font(FONT_DISPLAY, 8, QFont.DemiBold, track=1.0))
        p.setPen(QColor(lab_col))
        p.drawText(QRectF(2, 3, w - 4, 11), Qt.AlignCenter, self._label.upper())

        val_col = BLOCKED if self._disabled else (ACCENT if focused and not self._mirror else
                   (FG_SECONDARY if self._mirror else FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, track=0.2))
        p.setPen(QColor(val_col))
        fm = p.fontMetrics()
        pad = 17 if (not self._disabled and not self._mirror) else 6
        elided = fm.elidedText(self._display_text().upper(), Qt.ElideRight, int(w - 2 * pad))
        p.drawText(QRectF(0, h * 0.34, w, h * 0.56), Qt.AlignCenter, elided)

        if not self._disabled and not self._mirror:
            ac = ACCENT if focused else FG_MUTED
            if self._use_popup():
                arrow(p, w - 8, h * 0.62, "down", ac, size=4)
            else:
                # Hug the value text (TeamNamePicker's "< NAME >" look, just
                # smaller) instead of sitting at the box's own edges — at
                # this row's full card width, a short value like "HOME"
                # left a wide dead gap to arrows pinned 9px off each side.
                half_text = fm.horizontalAdvance(elided) / 2
                arrow(p, w / 2 - half_text - 12, h * 0.62, "left", ac, size=6)
                arrow(p, w / 2 + half_text + 12, h * 0.62, "right", ac, size=6)
                # mousePressEvent's click zones can't stay a fixed thirds
                # split once the arrows moved to hug the text instead of
                # sitting at the box edges — cache where the text starts so
                # a click has to land left of it (on the left arrow) to
                # count as "previous"; anything from the text on rightward
                # (including the right arrow) is "next".
                self._fw_click_boundary = w / 2 - half_text


class TeamNamePicker(QWidget):
    """Big <  NAME  > selector for the team itself, sitting directly under
    the crest — no label row, no border box, matches the mockup's team-card
    header treatment."""

    changed = pyqtSignal()

    def __init__(self, values=None, display=str, subtitle=str, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(78)
        self._values = list(values) if values else []
        self._display = display
        self._subtitle = subtitle
        self._index = 0

    def set_values(self, values, index=0):
        self._values = list(values)
        self._index = max(0, min(index, len(self._values) - 1)) if self._values else 0
        self.update()

    def current(self):
        return self._values[self._index] if self._values else None

    def index_of(self, value):
        try:
            return self._values.index(value)
        except ValueError:
            return None

    def _step(self, d):
        if not self._values:
            return
        self._index = (self._index + d) % len(self._values)
        self.update()
        self.changed.emit()

    def keyPressEvent(self, event):
        # Always arrow-cycle — a season's team list is short enough that a
        # popup (see SelectorRow, which still offers one where the global
        # dropdown_menus preference is on) is more clicks than it's worth.
        if event.key() == Qt.Key_Left:
            self._step(-1); event.accept(); return
        if event.key() == Qt.Key_Right:
            self._step(1); event.accept(); return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        # No setFocus() — see SelectorRow.mousePressEvent.
        third = self.width() / 3
        if event.x() < third:
            self._step(-1)
        elif event.x() > 2 * third:
            self._step(1)

    def paintEvent(self, event):
        p = QPainter(self)
        focused = self.hasFocus()
        w, h = self.width(), self.height()
        ac = ACCENT if focused else FG_MUTED
        arrow(p, 26, h * 0.34, "left", ac, size=10)
        arrow(p, w - 26, h * 0.34, "right", ac, size=10)

        name = self._display(self._values[self._index]) if self._values else "—"
        p.setFont(tracked_font(FONT_DISPLAY, 30, QFont.Bold, track=0.8))
        p.setPen(QColor(ACCENT if focused else FG_PRIMARY))
        p.drawText(QRectF(0, 6, w, 42), Qt.AlignCenter, name.upper())

        if self._values:
            sub = self._subtitle(self._values[self._index])
            if sub:
                p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.DemiBold, track=1.8))
                p.setPen(QColor(FG_SECONDARY))
                p.drawText(QRectF(0, 48, w, 20), Qt.AlignCenter, sub.upper())


class DeviceTile(QWidget):
    """One connected input device — keyboard or pad — shown as an icon tile.
    Edge colour is the current assignment; the focused tile shows red nudge
    chevrons and Left/Right reassigns it (home -> unassigned -> away)."""

    reassigned = pyqtSignal(str)   # new zone: "home" | "none" | "away"

    ZONES = ["home", "none", "away"]

    def __init__(self, kind: str, label: str, zone: str = "none", parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedSize(84, 118)
        self.kind = kind
        self.label = label
        self.zone = zone

    def set_zone(self, zone):
        self.zone = zone
        self.update()

    def keyPressEvent(self, event):
        i = self.ZONES.index(self.zone)
        if event.key() == Qt.Key_Left and i > 0:
            self.zone = self.ZONES[i - 1]; self.update(); self.reassigned.emit(self.zone); event.accept(); return
        if event.key() == Qt.Key_Right and i < len(self.ZONES) - 1:
            self.zone = self.ZONES[i + 1]; self.update(); self.reassigned.emit(self.zone); event.accept(); return
        super().keyPressEvent(event)

    # No mousePressEvent override — a click used to only grab focus here
    # (reassignment is Left/Right once focused); see SelectorRow for why
    # that no longer happens on click, keyboard/pad nav unaffected.

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        s = 76
        cx, cy = self.width() / 2, s / 2 + 4
        focused = self.hasFocus()
        zone_col = {"home": HOME_TINT, "away": AWAY_TINT, "none": BORDER_EM}[self.zone]
        edge = ACCENT if focused else zone_col
        rect = QRectF(cx - s / 2, cy - s / 2, s, s)
        p.setPen(QPen(QColor(edge), 3 if focused else 2))
        p.setBrush(QColor(BG_RAISED))
        p.drawRoundedRect(rect, 14, 14)

        icon_fn = gamepad_icon if self.kind == "pad" else keyboard_icon
        icon_fn(p, cx, cy - 3, 1.05, FG_PRIMARY if self.zone != "none" else FG_SECONDARY)

        if focused:
            arrow(p, cx - s / 2 - 15, cy, "left", AWAY_TINT, size=7)
            arrow(p, cx + s / 2 + 15, cy, "right", AWAY_TINT, size=7)

        p.setFont(tracked_font(FONT_BODY, 11, QFont.DemiBold, track=0.6))
        p.setPen(QColor(ACCENT if focused else FG_SECONDARY))
        p.drawText(QRectF(0, cy + s / 2 + 6, self.width(), 16), Qt.AlignCenter, self.label.upper())

        zone_txt = {"home": "HOME", "away": "AWAY", "none": "UNASSIGNED"}[self.zone]
        p.setFont(tracked_font(FONT_BODY, 9, QFont.DemiBold, track=1.0))
        p.setPen(QColor(zone_col if self.zone != "none" else FG_MUTED))
        p.drawText(QRectF(0, cy + s / 2 + 22, self.width(), 14), Qt.AlignCenter, zone_txt)


class MenuTile(QWidget):
    """A big menu entry: title, subtitle, focus stripe, optional SOON chip.
    Shared by the main menu and the tool hubs it leads to."""

    activated = pyqtSignal()

    def __init__(self, title, subtitle="", soon=False, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(88)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.title = title
        self.subtitle = subtitle
        self.soon = soon
        # Entrance: 0 = parked off to the right and fully transparent,
        # 1 = settled in place. Driven by the owning screen (see
        # MainMenuScreen.play_entrance); painted rather than laid out, so a
        # staggered slide-in costs the vertical layout nothing.
        self._entrance = 1.0
        if soon:
            self.setEnabled(False)

    ENTRANCE_SLIDE = 90  # px travelled during the slide-in

    def set_entrance(self, t):
        self._entrance = max(0.0, min(1.0, float(t)))
        self.update()

    def mousePressEvent(self, event):
        # No setFocus() — see SelectorRow.mousePressEvent.
        if self.isEnabled():
            self.activate()

    def activate(self):
        if self.isEnabled():
            self.activated.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        if self._entrance < 1.0:
            p.setOpacity(self._entrance)
            p.translate(self.ENTRANCE_SLIDE * (1.0 - self._entrance), 0)
        focused = self.hasFocus()
        p.fillRect(self.rect(), QColor(BG_HIGHLIGHT if focused else BG_CARD))
        stripe_w = 8 if focused else 4
        stripe_col = ACCENT if focused else (BLOCKED if self.soon else BORDER_EM)
        p.fillRect(QRectF(0, 0, stripe_w, self.height()), QColor(stripe_col))
        # Draw the frame last so the top edge remains visible when adjacent
        # menu tiles or the entrance animation touch the tile boundary.
        draw_frame(p, self.rect(), ACCENT if focused else BORDER)

        p.setFont(tracked_font(FONT_DISPLAY, 26, QFont.Bold, track=1.0))
        p.setPen(QColor(BLOCKED if self.soon else FG_PRIMARY))
        title_rect = QRectF(34, 12, self.width() - 140, 34)
        if not self.subtitle:
            title_rect.setY(0)
            title_rect.setHeight(self.height())
        p.drawText(title_rect, Qt.AlignLeft | Qt.AlignVCenter, self.title)

        if self.subtitle:
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.DemiBold, track=1.4))
            p.setPen(QColor(FG_MUTED if self.soon else FG_SECONDARY))
            p.drawText(QRectF(36, 50, self.width() - 140, 22), Qt.AlignLeft | Qt.AlignVCenter,
                       self.subtitle.upper())

        if self.soon:
            p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.DemiBold, track=1.4))
            p.setPen(QColor(BLOCKED))
            chip = QRectF(self.width() - 110, self.height() / 2 - 12, 100, 24)
            p.drawRect(chip.adjusted(0, 0, -1, -1))
            p.drawText(chip, Qt.AlignCenter, "COMING SOON")


class SegmentedToggle(QWidget):
    """A two-or-more segment switch showing every mode at once, each with its
    own count — so the list below it never has hidden state you have to press
    something to discover.

    Deliberately NOT focusable: the owning screen flips it with Left/Right
    (an axis a vertical list doesn't use), which keeps it off the focus chain
    and out of the way of browsing the list itself."""

    changed = pyqtSignal(int)

    def __init__(self, segments=None, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.NoFocus)
        self.setMouseTracking(True)
        self.setFixedHeight(28)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._segments = list(segments or [])   # [(label, count)]
        self._index = 0

    def set_segments(self, segments):
        self._segments = list(segments)
        self._index = min(self._index, max(0, len(self._segments) - 1))
        self.update()

    def index(self):
        return self._index

    def set_index(self, i, notify=True):
        if not self._segments:
            return
        i = max(0, min(i, len(self._segments) - 1))
        if i == self._index:
            return
        self._index = i
        self.update()
        if notify:
            self.changed.emit(i)

    def _segment_at(self, x):
        if not self._segments:
            return None
        return min(int(x / (self.width() / len(self._segments))), len(self._segments) - 1)

    def mousePressEvent(self, event):
        i = self._segment_at(event.x())
        if i is not None:
            self.set_index(i)

    def paintEvent(self, event):
        if not self._segments:
            return
        p = QPainter(self)
        w = self.width() / len(self._segments)
        for i, (label, count) in enumerate(self._segments):
            active = i == self._index
            r = QRectF(i * w, 0, w, self.height())
            p.fillRect(r, QColor(SQUAD_PICKER_ACTIVE_BG if active else SQUAD_PICKER_INACTIVE_BG))
            p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, track=1.4))
            text = f"{label.upper()}  {count}"
            p.setPen(QColor(SQUAD_PICKER_ACTIVE_TEXT if active else SQUAD_PICKER_INACTIVE_TEXT))
            p.drawText(r, Qt.AlignCenter, text)
        p.setPen(QPen(QColor(SQUAD_PICKER_BORDER), 1))
        p.drawRect(QRectF(0.5, 0.5, self.width() - 1, self.height() - 1))
        for i in range(1, len(self._segments)):
            x = i * w
            p.setPen(QPen(QColor(SQUAD_PICKER_DIVIDER), 1))
            p.drawLine(QRectF(x, 0, 0, self.height()).topLeft(),
                       QRectF(x, 0, 0, self.height()).bottomLeft())


class HintBar(QWidget):
    """Persistent bottom bar showing the focused widget's action hints — the
    thing that makes a pad UI legible, and doubles as keyboard discoverability."""

    def __init__(self, parent=None, framed=True):
        super().__init__(parent)
        self.setFixedHeight(44)
        self._hints = []   # list[(glyph, label)]
        self._framed = framed   # False inside a container that draws its own chrome

    def set_hints(self, hints):
        self._hints = hints
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(BG_PANEL))
        if self._framed:
            p.fillRect(QRectF(0, 0, self.width(), 2), QColor(ACCENT))
        x = 24
        glyph_col = {"A": GREEN, "B": AWAY_TINT, "X": HOME_TINT, "Y": ACCENT,
                     "Q": ACCENT, "E": ACCENT}
        for glyph, label in self._hints:
            col = QColor(glyph_col.get(glyph, FG_SECONDARY))
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, track=0.0))
            fm = p.fontMetrics()
            gw = max(20, fm.horizontalAdvance(glyph) + 10)
            gr = QRectF(x, 12, gw, 20)
            p.setPen(QPen(col, 1.5))
            p.drawRoundedRect(gr, 10, 10)
            p.drawText(gr, Qt.AlignCenter, glyph)
            x += gw + 8
            p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.DemiBold, track=1.0))
            p.setPen(QColor(FG_SECONDARY))
            lw = p.fontMetrics().horizontalAdvance(label.upper())
            p.drawText(QRectF(x, 12, lw + 4, 20), Qt.AlignVCenter | Qt.AlignLeft, label.upper())
            x += lw + 30
