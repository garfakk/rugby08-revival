"""
ui/team_sheet.py — the matchday team-sheet widgets
====================================================
Shared by the squad editor (one match's lineup) and the team editor (a
team's stored squad): shirts 1-15 laid out the way a matchday graphic shows
them, replacements 16-22 underneath, and the player picker with its
FITS / ALL switch.

Extra behaviour the team editor needs is opt-in, so the squad editor keeps
exactly the look and interaction it had: compact size, role badges, a fit /
problem tint, drag and drop between shirts, and a "carrying" state for
moving a player with the keyboard or pad.
"""
from PyQt5.QtWidgets import QWidget, QSizePolicy, QVBoxLayout, QLabel
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QDrag
from PyQt5.QtCore import Qt, QRectF, QTimer, QMimeData, QPoint, pyqtSignal

from ui.broadcast import SegmentedToggle, tracked_font, draw_frame
from ui.dropdown import PopupList
from ui.theme import (
    BG_BASE, BG_CARD, BG_RAISED, BG_HIGHLIGHT, BORDER, ACCENT, WARN,
    FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FG_MUTED, FONT_DISPLAY,
)

# ── Domain constants ─────────────────────────────────────────────────────
POSITION_FOR_NUMBER = {
    1: "prop", 2: "hooker", 3: "prop", 4: "second_row", 5: "second_row",
    6: "flanker", 7: "flanker", 8: "number_eight", 9: "scrum_half",
    10: "fly_half", 11: "winger", 12: "centre", 13: "centre", 14: "winger",
    15: "fullback",
}

# The matchday-graphic disposition: one entry per row, listing shirt numbers
# left-to-right exactly as they are laid out on a team sheet.
SHEET_ROWS = [
    [1, 2, 3],
    [4, 5],
    [6, 7, 8],
    [9, 10],
    [11, 12, 13, 14],
    [15],
]
# Match setup's squad editor swaps 7 and 8 (6, 8, 7): the team editor follows it.
MATCH_SHEET_ROWS = [([6, 8, 7] if row == [6, 7, 8] else row) for row in SHEET_ROWS]
STARTERS = [n for row in SHEET_ROWS for n in row]
SUBSTITUTES = list(range(16, 23))     # 7 replacements — 22 players total
SQUAD_SIZE = len(STARTERS) + len(SUBSTITUTES)

POSITION_NAMES = {
    "prop": "Prop", "loosehead_prop": "Loosehead prop", "tighthead_prop": "Tighthead prop",
    "hooker": "Hooker", "second_row": "Second row", "lock": "Lock",
    "flanker": "Flanker", "openside_flanker": "Openside flanker",
    "blindside_flanker": "Blindside flanker", "number_eight": "Number 8",
    "scrum_half": "Scrum-half", "fly_half": "Fly-half", "centre": "Centre",
    "inside_centre": "Inside centre", "outside_centre": "Outside centre",
    "winger": "Winger", "wing": "Wing", "fullback": "Full-back", "full_back": "Full-back",
}

POSITION_SHORT = {
    "loosehead_prop": "LHP", "tighthead_prop": "THP", "prop": "PR", "hooker": "HK",
    "second_row": "LK", "lock": "LK", "blindside_flanker": "BF", "openside_flanker": "OF",
    "flanker": "FL", "number_eight": "N8", "scrum_half": "SH", "fly_half": "FH",
    "centre": "CE", "inside_centre": "IC", "outside_centre": "OC", "winger": "WG",
    "wing": "WG", "fullback": "FB", "full_back": "FB",
}

# The squad data uses finer-grained tags than POSITION_FOR_NUMBER's generic
# ones (loosehead_prop vs prop), so a shirt accepts a set, not one string. The
# game treats loosehead and tighthead as one position: either wears 1 or 3.
_PROPS = {"prop", "loosehead_prop", "tighthead_prop"}
ACCEPTED_POSITIONS = {
    1: _PROPS,
    2: {"hooker"},
    3: _PROPS,
    4: {"second_row", "lock"},
    5: {"second_row", "lock"},
    6: {"flanker", "blindside_flanker", "openside_flanker"},
    7: {"flanker", "blindside_flanker", "openside_flanker"},
    8: {"number_eight"},
    9: {"scrum_half"},
    10: {"fly_half"},
    11: {"winger", "wing"},
    12: {"centre", "inside_centre"},
    13: {"centre", "outside_centre"},
    14: {"winger", "wing"},
    15: {"fullback", "full_back"},
}

ROLE_SHORT = {
    "captain": "C", "viceCaptain": "VC", "longGK": "LG", "shortGK": "SG",
    "longPunt": "LP", "shortPunt": "SP", "kickoff": "KO",
}

STATS_PANEL_ATTRIBUTES = [
    ("ATTACK", "attack"), ("DEFENCE", "defense"), ("SPEED", "speed"),
    ("ACCELERATION", "acceleration"), ("HANDLING", "handling"),
    ("PASSING", "passing"), ("KICKING", "kicking"), ("TACKLING", "tackling"),
    ("STRENGTH", "strength"), ("STAMINA", "stamina"),
]

SLOT_MIME = "application/x-r08-slot"


def fits_shirt(player: dict, number: int) -> bool:
    accepted = ACCEPTED_POSITIONS.get(number)
    if not accepted or not player:
        return True
    return bool(accepted & {player.get("position1", ""), player.get("position2", ""),
                             player.get("position3", "")})


def last_name(player: dict) -> str:
    if not player:
        return "—"
    return (player.get("last_name")
            or player.get("display_name")
            or player.get("name", "—")).upper()


def all_positions(player: dict) -> str:
    """All 3 position slots the player carries, deduplicated and named —
    not just the primary one."""
    if not player:
        return ""
    seen = []
    for key in ("position1", "position2", "position3"):
        pos = (player.get(key) or "").strip()
        if pos and pos not in seen:
            seen.append(pos)
    return " / ".join(POSITION_NAMES.get(p, p.replace("_", " ")).upper() for p in seen)


def initials(player: dict) -> str:
    if not player:
        return "?"
    first = (player.get("first_name") or "").strip()
    last = (player.get("last_name") or player.get("display_name") or "").strip()
    return ((first[:1] + last[:1]) or "?").upper()


class _DragSource:
    """Mixin: optional drag-and-drop of a shirt onto another shirt."""

    dropped = None   # overridden by pyqtSignal in subclasses

    def _init_dnd(self):
        self._dnd = False
        self._press_pos = None
        self._dragged = False
        self._drop_hover = False

    def enable_dnd(self, on=True):
        self._dnd = on
        self.setAcceptDrops(on)

    def _dnd_press(self, event):
        self._press_pos = event.pos()
        self._dragged = False

    def _dnd_move(self, event):
        if not self._dnd or self._press_pos is None or not (event.buttons() & Qt.LeftButton):
            return False
        if (event.pos() - self._press_pos).manhattanLength() < 8 or self.player is None:
            return False
        self._dragged = True
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(SLOT_MIME, str(self.number).encode())
        drag.setMimeData(mime)
        pix = self.grab()
        drag.setPixmap(pix.scaled(pix.width() // 2 or 1, pix.height() // 2 or 1,
                                  Qt.KeepAspectRatio, Qt.SmoothTransformation))
        drag.setHotSpot(QPoint(pix.width() // 4, pix.height() // 4))
        drag.exec_(Qt.MoveAction)
        self._press_pos = None
        return True

    def dragEnterEvent(self, event):
        if self._dnd and event.mimeData().hasFormat(SLOT_MIME):
            event.acceptProposedAction()
            self._drop_hover = True
            self.update()

    def dragLeaveEvent(self, event):
        self._drop_hover = False
        self.update()

    def dropEvent(self, event):
        self._drop_hover = False
        self.update()
        if not event.mimeData().hasFormat(SLOT_MIME):
            return
        src = int(bytes(event.mimeData().data(SLOT_MIME)).decode())
        if src != self.number:
            self.dropped.emit(src, self.number)
        event.acceptProposedAction()


class SlotAvatar(_DragSource, QWidget):
    """One shirt on the team sheet: a portrait ring with the number and name
    under it, mirroring the matchday graphic."""

    activated = pyqtSignal(int)
    hovered = pyqtSignal(int)
    dropped = pyqtSignal(int, int)          # (from shirt, to shirt)
    double_clicked = pyqtSignal(int)
    unhovered = pyqtSignal(int)

    def __init__(self, number: int, tint: str, parent=None, size="normal"):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.number = number
        self.tint = tint
        self.player = None
        self.is_captain = False
        self.badges = []
        self.issue_color = None
        self.carrying = False
        self.empty_label = ""
        self.compact = size == "compact"
        self._init_dnd()
        self.setFixedSize(*((98, 68) if self.compact else (128, 100)))

    def set_player(self, player, is_captain=False):
        self.player = player
        self.is_captain = is_captain
        self.update()

    def set_badges(self, badges):
        self.badges = list(badges)
        self.update()

    def set_issue(self, color):
        self.issue_color = color
        self.update()

    def set_carrying(self, on):
        self.carrying = on
        self.update()

    def mousePressEvent(self, event):
        self.setFocus()
        if self._dnd:
            self._dnd_press(event)
        else:
            self.activated.emit(self.number)

    def mouseMoveEvent(self, event):
        self._dnd_move(event)

    def mouseReleaseEvent(self, event):
        if self._dnd and not self._dragged and self._press_pos is not None:
            self.activated.emit(self.number)
        self._press_pos = None

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.number)

    def enterEvent(self, event):
        self.hovered.emit(self.number)

    def leaveEvent(self, event):
        self.unhovered.emit(self.number)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        focused = self.hasFocus()
        d = 40 if self.compact else 64
        cx, cy = self.width() / 2, d / 2 + 3
        ring = ACCENT if (focused or self._drop_hover) else (self.issue_color or self.tint)

        p.setBrush(QColor(BG_HIGHLIGHT if self._drop_hover else BG_RAISED))
        pen = QPen(QColor(ring), 3 if (focused or self.issue_color) else 2)
        if self.carrying:
            pen.setStyle(Qt.DashLine)
            pen.setColor(QColor(ACCENT))
            pen.setWidth(3)
        p.setPen(pen)
        p.drawEllipse(QRectF(cx - d / 2, cy - d / 2, d, d))

        p.setFont(tracked_font(FONT_DISPLAY, 13 if self.compact else 19, QFont.Bold, track=0.5))
        p.setPen(QColor(FG_SECONDARY if self.player else FG_MUTED))
        p.drawText(QRectF(cx - d / 2, cy - d / 2, d, d), Qt.AlignCenter,
                   initials(self.player) if self.player else (self.empty_label or "?"))

        badges = list(self.badges) or (["C"] if self.is_captain else [])
        if badges:
            p.setFont(tracked_font(FONT_DISPLAY, 9 if self.compact else 11, QFont.Bold, track=0))
            shown = badges[:2] + ([f"+{len(badges) - 2}"] if len(badges) > 2 else [])
            bx = cx + d / 2 - 14
            for text in shown:
                w = max(18, p.fontMetrics().horizontalAdvance(text) + 8)
                br = QRectF(bx, cy - d / 2 - 3, w, 17)
                p.setBrush(QColor(ACCENT))
                p.setPen(Qt.NoPen)
                p.drawRoundedRect(br, 8, 8)
                p.setPen(QColor(BG_BASE))
                p.drawText(br, Qt.AlignCenter, text)
                bx += w - 2

        num_font = tracked_font(FONT_DISPLAY, 11 if self.compact else 12, QFont.Bold, track=0.6)
        p.setFont(num_font)
        num_txt = str(self.number)
        num_w = p.fontMetrics().horizontalAdvance(num_txt) + 6
        name = p.fontMetrics().elidedText(last_name(self.player) if self.player else "—",
                                          Qt.ElideRight, int(self.width() - num_w - 6))
        name_w = p.fontMetrics().horizontalAdvance(name)
        x0 = (self.width() - (num_w + name_w)) / 2
        y = d + (4 if self.compact else 8)

        p.setPen(QColor(ACCENT if focused else self.tint))
        p.drawText(QRectF(x0, y, num_w, 20), Qt.AlignLeft | Qt.AlignVCenter, num_txt)
        p.setPen(QColor(self.issue_color or (FG_PRIMARY if self.player else FG_MUTED)))
        p.drawText(QRectF(x0 + num_w, y, name_w, 20), Qt.AlignLeft | Qt.AlignVCenter, name)


class SubChip(_DragSource, QWidget):
    """A replacement, listed the way the graphic lists them: number + name."""

    activated = pyqtSignal(int)
    hovered = pyqtSignal(int)
    dropped = pyqtSignal(int, int)
    double_clicked = pyqtSignal(int)
    unhovered = pyqtSignal(int)
    remove_requested = pyqtSignal(int)     # the × of a removable chip

    def __init__(self, number: int, tint: str, parent=None, size="normal", show_number=True):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setFixedHeight(30 if size == "compact" else 38)
        self.setMinimumWidth(66 if size == "compact" else 150)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.setMouseTracking(True)
        self.number = number
        self.tint = tint
        self.player = None
        self.badges = []
        self.issue_color = None
        self.carrying = False
        self.show_number = show_number
        self.empty_label = ""       # shown on an empty chip (an "add" item)
        self.removable = False      # draws a × that emits remove_requested
        self._init_dnd()

    def set_player(self, player):
        self.player = player
        self.update()

    def set_badges(self, badges):
        self.badges = list(badges)
        self.update()

    def set_issue(self, color):
        self.issue_color = color
        self.update()

    def set_carrying(self, on):
        self.carrying = on
        self.update()

    def _cross_rect(self):
        return QRectF(self.width() - 24, 0, 24, self.height())

    def _on_cross(self, event):
        return self.removable and self.player is not None and self._cross_rect().contains(event.pos())

    def mousePressEvent(self, event):
        if self._on_cross(event):
            self.remove_requested.emit(self.number)
            return
        self.setFocus()
        if self._dnd:
            self._dnd_press(event)
        else:
            self.activated.emit(self.number)

    def mouseMoveEvent(self, event):
        self._dnd_move(event)

    def mouseReleaseEvent(self, event):
        if self._dnd and not self._dragged and self._press_pos is not None:
            self.activated.emit(self.number)
        self._press_pos = None

    def mouseDoubleClickEvent(self, event):
        self.double_clicked.emit(self.number)

    def enterEvent(self, event):
        self.hovered.emit(self.number)

    def leaveEvent(self, event):
        self.unhovered.emit(self.number)

    def paintEvent(self, event):
        p = QPainter(self)
        focused = self.hasFocus()
        p.fillRect(self.rect(), QColor(BG_HIGHLIGHT if (focused or self._drop_hover) else BG_CARD))
        if self.carrying:
            p.setPen(QPen(QColor(ACCENT), 2, Qt.DashLine))
            p.drawRect(self.rect().adjusted(1, 1, -1, -1))
        else:
            # filled strips, not a pen: a 1px stroke can vanish under the
            # app's fractional QT_SCALE_FACTOR (see draw_frame)
            draw_frame(p, self.rect(), ACCENT if (focused or self._drop_hover)
                       else (self.issue_color or BORDER))

        left = 38 if self.show_number else 10
        if self.show_number:
            p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, track=0.6))
            p.setPen(QColor(ACCENT if focused else self.tint))
            p.drawText(QRectF(10, 0, 26, self.height()), Qt.AlignLeft | Qt.AlignVCenter, str(self.number))
        right = 8
        if self.removable and self.player is not None:
            p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, track=0))
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(self._cross_rect(), Qt.AlignCenter, "×")
            right = 26
        if self.badges:
            p.setFont(tracked_font(FONT_DISPLAY, 9, QFont.Bold, track=0))
            text = self.badges[0] + (f"+{len(self.badges) - 1}" if len(self.badges) > 1 else "")
            w = p.fontMetrics().horizontalAdvance(text) + 10
            br = QRectF(self.width() - w - right + 2, (self.height() - 16) / 2, w, 16)
            p.setBrush(QColor(ACCENT))
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(br, 8, 8)
            p.setPen(QColor(BG_BASE))
            p.drawText(br, Qt.AlignCenter, text)
            right += w + 4
        p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, track=0.6))
        p.setPen(QColor(self.issue_color or (FG_PRIMARY if self.player else FG_MUTED)))
        if self.player is None and self.empty_label:
            p.setPen(QColor(ACCENT if focused else FG_SECONDARY))
            p.drawText(QRectF(left, 0, self.width() - left - right, self.height()),
                       Qt.AlignLeft | Qt.AlignVCenter, self.empty_label)
            return
        name = p.fontMetrics().elidedText(last_name(self.player), Qt.ElideRight,
                                          int(self.width() - left - right))
        p.drawText(QRectF(left, 0, self.width() - left - right, self.height()),
                   Qt.AlignLeft | Qt.AlignVCenter, name)


class StatsPanel(QWidget):
    """Attribute read-out for whichever player is under the cursor."""

    def __init__(self, parent=None, attributes=None, min_height=330):
        super().__init__(parent)
        self.player = None
        self.attributes = attributes or STATS_PANEL_ATTRIBUTES
        self.setMinimumHeight(min_height)

    def set_player(self, player):
        self.player = player
        self.update()

    def paintEvent(self, event):
        if not self.player:
            return
        p = QPainter(self)
        w = self.width()
        row_h = max(26, min(34, self.height() / len(self.attributes)))
        y = 0
        for label, key in self.attributes:
            try:
                val = int(self.player.get(key, 0))
            except (TypeError, ValueError):
                val = 0
            p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, track=1.0))
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(0, y, w - 40, 15), Qt.AlignLeft | Qt.AlignVCenter, label)
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, track=0))
            p.setPen(QColor(FG_PRIMARY))
            p.drawText(QRectF(w - 36, y, 36, 15), Qt.AlignRight | Qt.AlignVCenter, str(val))
            bar = QRectF(0, y + 18, w, 5)
            p.fillRect(bar, QColor(BG_RAISED))
            p.fillRect(QRectF(bar.x(), bar.y(), bar.width() * min(val, 99) / 99, bar.height()),
                       QColor(ACCENT))
            y += row_h


FITS, ALL, SEARCH = 0, 1, 2     # the picker's view modes (SEARCH only when given a pool)


class _PickerToolbar(QWidget):
    """The segments plus, in SEARCH view, the query typed so far. Exposes
    index()/set_index() so the popup's ←→ keys drive the segments."""

    def __init__(self, segments, parent=None):
        super().__init__(parent)
        self.segments = segments
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(4)
        v.addWidget(segments)
        self.query = QLabel("")
        self.query.setFont(tracked_font(FONT_DISPLAY, 11, QFont.DemiBold, 0.4))
        self.query.setStyleSheet(f"color: {FG_SECONDARY}; background: {BG_RAISED};"
                                 f" border: 1px solid {BORDER}; padding: 3px 8px;")
        self.query.hide()
        v.addWidget(self.query)

    def index(self):
        return self.segments.index()

    def set_index(self, i, notify=True):
        self.segments.set_index(i, notify)


class PlayerPickerPopup(QWidget):
    """Anchored dropdown opened by activating a shirt on the sheet —
    selection happens here, not in the side panel.

    One piece of state, shown rather than hidden: a segmented FITS / ALL
    switch carrying the count of each, defaulting to the players who fit
    this shirt. Given a `search` pool, a third SEARCH view lists it instead
    (the whole player database), narrowed by what is typed. Nothing else is filtered — a player already wearing another
    shirt is listed and tagged with it (picking them MOVES them, vacating
    that shirt), and in ALL view a player out of position keeps his rail and
    dimmed name rather than being hidden behind a toggle.

    This widget is only a renderer plus a mode: which players exist, whether
    each fits and what order they come in is decided by the screen."""

    picked = pyqtSignal(object)
    hovered = pyqtSignal(object)
    closed = pyqtSignal()

    def __init__(self, parent=None, width=340, height=420, own_keys=False):
        super().__init__(parent)
        # own_keys: the popup drives its own keys (arrows browse, ←→ FITS/ALL,
        # Enter picks, Esc closes) instead of the screen routing them.
        self._popup = PopupList(parent, width=width, height=height, own_keys=own_keys)
        self._popup.picked.connect(self.picked.emit)
        self._popup.hovered.connect(self.hovered.emit)
        self._popup.closed.connect(self.closed.emit)

        self.segments = SegmentedToggle([("SUGGESTED", 0), ("ALL", 0)])
        self.segments.changed.connect(self._on_segment_changed)
        self.toolbar = _PickerToolbar(self.segments)
        self._popup.set_toolbar_widget(self.toolbar)
        self._popup.key_hook = self._search_key

        self._entries = []          # [(pid, name, fits)] in rank order
        self._search = None         # [(pid, name, fits)]: the SEARCH view's pool
        self._query = ""
        self._current_pid = None
        self._taken_by = {}
        self._tags = {}
        self._subtitles = {}
        self._mode = FITS
        self._seg_modes = [FITS, ALL]   # segment index -> view

    def isVisible(self):
        return self._popup.isVisible()

    def hide(self):
        self._popup.hide()

    def open_for(self, title, entries, current_pid, taken_by, anchor, screen,
                 tags=None, subtitles=None, search=None, mode=FITS):
        """`entries`: [(pid, name, fits)] for the WHOLE squad, already in the
        order they should appear. `taken_by`: {pid: shirt_number} for every
        OTHER filled slot. `tags`: optional {pid: (text, color)} overrides.
        `search`: optional [(pid, name, fits)] the SEARCH view filters.
        `mode`: the view it opens on."""
        self._entries = list(entries)
        self._search = list(search) if search is not None else None
        self._query = ""
        self._current_pid, self._taken_by = current_pid, taken_by
        self._tags = tags or {}
        self._subtitles = subtitles or {}
        self._mode = mode if (mode != SEARCH or self._search is not None) else FITS
        fit_count = sum(1 for pid, _, fits in self._entries
                        if fits or pid == current_pid)
        # no entries and opened on SEARCH: the SEARCH segment alone
        if self._search is not None and not self._entries and self._mode == SEARCH:
            self._seg_modes = [SEARCH]
        else:
            self._seg_modes = [FITS, ALL] + ([SEARCH] if self._search is not None else [])
        counts = {FITS: fit_count, ALL: len(self._entries), SEARCH: len(self._search or ())}
        names = {FITS: "SUGGESTED", ALL: "ALL", SEARCH: "SEARCH"}
        self.segments.set_segments([(names[m], counts[m]) for m in self._seg_modes])
        self.segments.set_index(self._seg_modes.index(self._mode), notify=False)
        self._show_query()
        self._popup.set_title(title)
        # Sized for the largest view, so flipping the segment scrolls the
        # list rather than resizing the popup under the cursor.
        self._popup.size_to(max(len(self._entries), len(self._search or ())))
        self._rebuild()
        self._popup.open_at(anchor, screen)
        # ensureWidgetVisible needs a laid-out scroll area, and open_at shows
        # without spinning the event loop, so defer the first scroll.
        QTimer.singleShot(0, lambda: self._popup.set_highlight(self._popup.highlighted_index()))

    # ── view mode ────────────────────────────────────────────────────────
    def cycle_mode(self, delta):
        self.segments.set_index(self.segments.index() + delta)

    def _on_segment_changed(self, index):
        self._mode = self._seg_modes[index]
        self._show_query()
        self._rebuild()

    def _show_query(self):
        on = self._mode == SEARCH
        self.toolbar.query.setVisible(on)
        if on:
            self.toolbar.query.setText(f"SEARCH: {self._query}_" if self._query
                                       else "TYPE A NAME TO SEARCH")

    def _search_key(self, event):
        """SEARCH view: typing edits the query (instead of jumping to a row),
        Backspace deletes from it. Returns True when the key was used."""
        if self._mode != SEARCH:
            return False
        if event.key() == Qt.Key_Backspace:
            if not self._query:
                return False
            self._query = self._query[:-1]
        elif event.text() and event.text().isprintable() and (event.key() != Qt.Key_Space
                                                               or self._query):
            self._query += event.text()
        else:
            return False
        self._show_query()
        self._rebuild()
        return True

    def _visible_entries(self):
        if self._mode == SEARCH:
            needle = self._query.strip().lower()
            return [e for e in self._search or ()
                    if not needle or needle in e[1].lower() or needle == str(e[0])]
        if self._mode == ALL:
            return self._entries
        # The incumbent stays listed even when he doesn't fit the shirt —
        # a default view that omitted the man currently wearing it would be
        # lying about the slot.
        return [e for e in self._entries if e[2] or e[0] == self._current_pid]

    def _rebuild(self):
        """Keeps the highlight on the same player across a mode switch when
        he survives it, so flipping FITS/ALL never loses your place."""
        keep_pid = self._popup.highlighted_data()
        self._popup.clear_rows()

        rows = self._visible_entries()
        if not rows:
            self._popup.add_row("NO PLAYER MATCHES" if self._mode == SEARCH
                                else "NO PLAYER FITS THIS SHIRT", None, disabled=True)
            return

        for pid, name, fits in rows:
            if pid in self._tags:
                tag, tag_col = self._tags[pid]
            elif pid == self._current_pid:
                tag, tag_col = "CURRENT", ACCENT
            elif pid in self._taken_by:
                tag, tag_col = f"#{self._taken_by[pid]}", WARN
            else:
                tag, tag_col = "", None
            self._popup.add_row(name, pid, tag=tag, tag_color=tag_col,
                                selected=(pid == self._current_pid),
                                subdued=not fits, subtitle=self._subtitles.get(pid, ""))

        index = next((i for i, (pid, _, _) in enumerate(rows) if pid == keep_pid), 0)
        self._popup.set_highlight(index)

    # ── passthroughs the screen drives from the action layer ─────────────
    def move_highlight(self, delta):
        return self._popup.move_highlight(delta)

    def page_highlight(self, sign):
        return self._popup.page_highlight(sign)

    def activate(self):
        return self._popup.activate_highlight()

    def highlighted_pid(self):
        return self._popup.highlighted_data()


def route_picker_key(picker, key):
    """Qt key → picker action, shared by every screen that opens one. Returns
    True when the key was used."""
    if key == Qt.Key_Up:
        picker.move_highlight(-1)
    elif key == Qt.Key_Down:
        picker.move_highlight(1)
    elif key == Qt.Key_Left:
        picker.cycle_mode(-1)
    elif key == Qt.Key_Right:
        picker.cycle_mode(1)
    elif key in (Qt.Key_PageUp, Qt.Key_Q):
        picker.page_highlight(-1)
    elif key in (Qt.Key_PageDown, Qt.Key_E):
        picker.page_highlight(1)
    elif key in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
        picker.activate()
    elif key in (Qt.Key_Escape, Qt.Key_Backspace):
        picker.hide()
    else:
        return False
    return True
