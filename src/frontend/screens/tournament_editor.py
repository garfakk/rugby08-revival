"""
screens/tournament_editor.py — Tournament editor (Tools, and the tournament
hub's CREATE YOUR OWN)
==========================================================================
Builds a competition of your own — a league, pools and a knockout bracket,
or a straight cup — without knowing how a template works. The screen edits
a *design* (app/tournament/custom.py), compiled to a template on save; New
tournament then offers it like any other competition.

Layout (EditorScreen): your tournaments on the left (+ NEW shows the ready-
made shapes to start from), five tabs in the middle, and a live preview on
the right: the shape as a diagram, its numbers, what still stops it being
played, and PLAY.

  SETUP     name, season, the format and how its knockouts go
  TEAMS     the pools (or the draw): add several at once, auto-fill, move, shuffle
  RULES     table points, ties on points, discipline, starting settings
  SCHEDULE  home grounds or neutral stadiums, the final, the calendar
  LOOK      description, presentation, competition look and squads, trophy
"""
import copy
from datetime import date, timedelta

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import (QGridLayout, QHBoxLayout, QLineEdit, QScrollArea, QSizePolicy,
                             QVBoxLayout, QWidget)

from app import competition_branding
from app.challenges import HALF_LENGTHS
from app.season import season_label
from app.tournament import custom as C
from shared.log import get_logger
from ui.broadcast import tracked_font
from ui.dropdown import PopupList
from ui.editor_kit import (Badge, ChoiceField, ConfirmDialog, FieldGrid, FormDialog, NumberField, Note,
                           SectionCard, SegmentField, TextField, compact_button)
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BG_CARD, BG_HIGHLIGHT, BG_RAISED, BORDER,
                      DANGER_LITE, FG_MUTED, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FONT_DISPLAY,
                      GREEN, T_LABEL, T_SMALL, WARN)

from .editor_base import EditorScreen
from .tournament.common import (ActivatableCard, PixmapLabel, competition_emblem, placeholder_crest,
                                team_crest)

log = get_logger(__name__)

TAB_SETUP, TAB_TEAMS, TAB_RULES, TAB_SCHEDULE, TAB_LOOK = range(5)
# which tab shows each design key (issues land on it)
FIELD_TABS = {
    "name": TAB_SETUP, "season": TAB_SETUP, "format": TAB_SETUP, "legs": TAB_SETUP,
    "playoff_teams": TAB_SETUP, "qualify": TAB_SETUP, "best_extra": TAB_SETUP,
    "seeding": TAB_SETUP, "third_place": TAB_SETUP, "knockout_draw": TAB_SETUP,
    "group_count": TAB_SETUP, "teams_from": TAB_SETUP, "category": TAB_SETUP,
    "groups": TAB_TEAMS,
    "points": TAB_RULES, "tiebreakers": TAB_RULES, "discipline": TAB_RULES, "options": TAB_RULES,
    "venue": TAB_SCHEDULE, "venues": TAB_SCHEDULE, "knockout_venue": TAB_SCHEDULE,
    "final_stadium": TAB_SCHEDULE, "start": TAB_SCHEDULE, "every": TAB_SCHEDULE,
    "description": TAB_LOOK, "variant": TAB_LOOK, "match_type": TAB_LOOK, "branding": TAB_LOOK,
    "trophy_lift": TAB_LOOK,
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
YES_NO = {True: "yes", False: "no"}
ON_OFF = {True: "on", False: "off"}


def _icon_button(text, slot, tip, removes=False):
    b = compact_button(text)
    b.setFixedWidth(34)
    b.setToolTip(tip)
    if removes:
        b.setProperty("removesRow", True)       # Y on the row presses it (app.screen_base)
    b.clicked.connect(slot)
    return b


# ═════════════════════════════════════════════════════════════════════════
# Painted pieces
# ═════════════════════════════════════════════════════════════════════════
def _art_table(p, r, col, rows):
    h = r.height() / rows
    for i in range(rows):
        line = QRectF(r.x(), r.y() + i * h + 2, r.width(), h - 4)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(col) if i == 0 else QColor(BG_RAISED))
        p.drawRoundedRect(line, 2, 2)
        p.setBrush(QColor(BG_BASE if i == 0 else FG_MUTED))
        p.drawRect(QRectF(line.x() + 6, line.center().y() - 1.5, line.width() * 0.45, 3))


def _art_bracket(p, r, col, first):
    """`first` ties in the first column, halving to a final."""
    pen = QPen(QColor(col), 2)
    cols = []
    n = first
    while n >= 1:
        cols.append(n)
        n //= 2
    cw = r.width() / len(cols)
    prev = []
    for ci, n in enumerate(cols):
        ys = [r.y() + (i + 0.5) * r.height() / n for i in range(n)]
        x0, x1 = r.x() + ci * cw, r.x() + ci * cw + cw * 0.55
        p.setPen(pen)
        for y in ys:
            p.drawLine(int(x0), int(y), int(x1), int(y))
        if prev:
            px = r.x() + (ci - 1) * cw + cw * 0.55
            for i, y in enumerate(ys):
                a, b = prev[2 * i], prev[2 * i + 1]
                p.drawLine(int(px), int(a), int(x0 - 4), int(a))
                p.drawLine(int(px), int(b), int(x0 - 4), int(b))
                p.drawLine(int(x0 - 4), int(a), int(x0 - 4), int(b))
                p.drawLine(int(x0 - 4), int(y), int(x0), int(y))
        prev = ys
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(AWAY_TINT))
    p.drawEllipse(QRectF(r.x() + (len(cols) - 1) * cw + cw * 0.55 + 4, prev[0] - 6, 12, 12))


def paint_art(p, fmt, r, col):
    """A format drawn small: a table, pools feeding a bracket, or a bracket."""
    if fmt == "league":
        _art_table(p, QRectF(r.x(), r.y(), r.width() * 0.8, r.height()), col, 6)
    elif fmt == "groups":
        gw = r.width() * 0.22
        for i in range(2):
            _art_table(p, QRectF(r.x(), r.y() + i * (r.height() / 2), gw, r.height() / 2 - 4), col, 3)
            _art_table(p, QRectF(r.x() + gw + 6, r.y() + i * (r.height() / 2), gw, r.height() / 2 - 4),
                       col, 3)
        _art_bracket(p, QRectF(r.x() + gw * 2 + 22, r.y(), r.width() - gw * 2 - 22, r.height()), col, 4)
    else:
        _art_bracket(p, QRectF(r.x(), r.y(), r.width() * 0.9, r.height()), col, 8)


class FormatCard(ActivatableCard):
    """One format, drawn, with its name under it."""

    def __init__(self, fmt, parent=None):
        super().__init__(parent)
        self.fmt = fmt
        self.setFixedHeight(128)
        self.setMinimumWidth(120)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        w = self.width()
        col = QColor(ACCENT if self.selected else FG_TERTIARY)
        paint_art(p, self.fmt, QRectF(16, 14, w - 32, 54), col)
        p.setPen(QColor(FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, 0.8))
        p.drawText(QRectF(16, 76, w - 32, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(C.FORMAT_SHORT[self.fmt].upper(), Qt.ElideRight, int(w - 32)))
        p.setPen(QColor(FG_TERTIARY))
        p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.3))
        p.drawText(QRectF(16, 98, w - 32, 20), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(C.FORMAT_BLURBS[self.fmt], Qt.ElideRight, int(w - 32)))
        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(QRectF(w - 30, 10, 18, 18))
            p.setPen(QColor(BG_BASE))
            p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.Bold, 0))
            p.drawText(QRectF(w - 30, 10, 18, 18), Qt.AlignCenter, "✓")


class StarterCard(ActivatableCard):
    """A ready-made shape to start from: its art, name and one line."""

    def __init__(self, key, title, fmt, detail, parent=None):
        super().__init__(parent)
        self.key, self.title, self.fmt, self.detail = key, title, fmt, detail
        self.setFixedHeight(168)
        self.setMinimumWidth(190)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        w = self.width()
        hot = self.hasFocus() or self.underMouse()
        art = QRectF(18, 16, w - 36, 54)
        if self.key == "blank":
            p.setPen(QPen(QColor(ACCENT if hot else FG_TERTIARY), 3))
            cx, cy = art.center().x(), art.center().y()
            p.drawLine(int(cx - 14), int(cy), int(cx + 14), int(cy))
            p.drawLine(int(cx), int(cy - 14), int(cx), int(cy + 14))
        else:
            paint_art(p, self.fmt, art, QColor(ACCENT if hot else FG_TERTIARY))
        p.setPen(QColor(FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 14, QFont.Bold, 0.8))
        p.drawText(QRectF(18, 80, w - 36, 24), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(self.title.upper(), Qt.ElideRight, int(w - 36)))
        p.setPen(QColor(FG_TERTIARY))
        p.setFont(tracked_font(FONT_DISPLAY, T_SMALL + 1, QFont.DemiBold, 0.3))
        p.drawText(QRectF(18, 106, w - 36, 56), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self.detail)


class StructureDiagram(QWidget):
    """The tournament's stages top to bottom (custom.structure): a table
    stage as a wide card, each knockout round under it, the final in gold."""

    ROW_H = 46
    GAP = 12

    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocks = []
        self.empty_text = ""
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_blocks(self, blocks, empty_text=""):
        self.blocks = list(blocks)
        self.empty_text = empty_text
        n = max(1, len(self.blocks))
        self.setFixedHeight(n * self.ROW_H + (n - 1) * self.GAP + 4)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w = self.width()
        if not self.blocks:
            p.setPen(QColor(FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, T_LABEL, QFont.DemiBold, 0.4))
            p.drawText(QRectF(0, 0, w, self.ROW_H), Qt.AlignCenter, self.empty_text)
            return
        for i, b in enumerate(self.blocks):
            y = i * (self.ROW_H + self.GAP)
            final = b["kind"] == "final"
            col = QColor(AWAY_TINT if final else (ACCENT if b["kind"] == "table" else FG_SECONDARY))
            r = QRectF(1, y + 1, w - 2, self.ROW_H - 2)
            p.setPen(QPen(col, 1.5))
            p.setBrush(QColor(BG_HIGHLIGHT if final else BG_CARD))
            p.drawRoundedRect(r, 6, 6)
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(r.x(), r.y(), 5, r.height()), 2, 2)
            games = ("" if b["matches"] is None else
                     f"{b['matches']} {'game' if b['matches'] == 1 else 'games'}".upper())
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.Bold, 0.6))
            gw = p.fontMetrics().horizontalAdvance(games) + 6
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(w - gw - 12, r.y() + 4, gw, 22), Qt.AlignRight | Qt.AlignVCenter, games)
            p.setPen(QColor(col if final else FG_PRIMARY))
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, 1.0))
            p.drawText(QRectF(r.x() + 16, r.y() + 4, w - gw - 40, 22), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(b["title"].upper(), Qt.ElideRight, int(w - gw - 40)))
            p.setPen(QColor(FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.3))
            p.drawText(QRectF(r.x() + 16, r.y() + 24, w - 30, 18), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(b["detail"], Qt.ElideRight, int(w - 34)))
            if i < len(self.blocks) - 1:
                cx = w / 2
                y0, y1 = y + self.ROW_H + 2, y + self.ROW_H + self.GAP - 1
                p.setPen(QPen(QColor(FG_MUTED), 2))
                p.drawLine(int(cx), int(y0), int(cx), int(y1 - 4))
                path = QPainterPath()
                path.moveTo(cx - 4, y1 - 5)
                path.lineTo(cx + 4, y1 - 5)
                path.lineTo(cx, y1)
                path.closeSubpath()
                p.fillPath(path, QColor(FG_MUTED))


class StatTile(QWidget):
    """A big number over a small caption."""

    def __init__(self, caption, parent=None):
        super().__init__(parent)
        self.caption, self.value = caption, "—"
        self.setFixedHeight(54)

    def set_value(self, value):
        self.value = str(value)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        p.setPen(QPen(QColor(BORDER), 1))
        p.setBrush(QColor(BG_CARD))
        p.drawRoundedRect(r, 5, 5)
        p.setPen(QColor(FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 18, QFont.Bold, 0.5))
        p.drawText(QRectF(0, 3, r.width(), 28), Qt.AlignCenter, self.value)
        p.setPen(QColor(FG_TERTIARY))
        p.setFont(tracked_font(FONT_DISPLAY, 9, QFont.Bold, 1.4))
        p.drawText(QRectF(0, 31, r.width(), 18), Qt.AlignCenter, self.caption.upper())


# ═════════════════════════════════════════════════════════════════════════
# Starting shapes
# ═════════════════════════════════════════════════════════════════════════
class StartPanel(QWidget):
    """The ready-made shapes as cards: shown when there is no tournament yet
    and by + NEW. `picked(key)`."""

    picked = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, focus, parent=None):
        super().__init__(parent)
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 14, 0, 0)
        v.setSpacing(12)
        head = QHBoxLayout()
        from ui.broadcast import eyebrow_label
        head.addWidget(eyebrow_label("New tournament", color=ACCENT, size=13))
        head.addStretch(1)
        self.cancel_btn = compact_button("CANCEL")
        self.cancel_btn.clicked.connect(self.cancelled)
        head.addWidget(self.cancel_btn)
        v.addLayout(head)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")
        holder = QWidget()
        holder.setObjectName("starterHolder")
        holder.setStyleSheet("QWidget#starterHolder { background: transparent; }")
        grid = QGridLayout(holder)
        grid.setContentsMargins(0, 0, 6, 0)
        grid.setSpacing(12)
        self.cards = []
        for i, (key, title, fmt, detail) in enumerate(C.STARTERS):
            card = StarterCard(key, title, fmt, detail)
            card.activated.connect(lambda key=key: self.picked.emit(key))
            grid.addWidget(card, i // 3, i % 3)
            focus.register(card)
            self.cards.append(card)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        grid.setRowStretch(len(C.STARTERS) // 3 + 1, 1)
        scroll.setWidget(holder)
        v.addWidget(scroll, stretch=1)
        focus.register(self.cancel_btn)


# ═════════════════════════════════════════════════════════════════════════
# Rows
# ═════════════════════════════════════════════════════════════════════════
class ReflowGrid(QWidget):
    """Cards in as many columns as fit (each at least `col_width`)."""

    def __init__(self, col_width=270, max_cols=3, parent=None):
        super().__init__(parent)
        self.setObjectName("reflowGrid")
        self.setStyleSheet("QWidget#reflowGrid { background: transparent; }")
        self.col_width, self.max_cols = col_width, max_cols
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setHorizontalSpacing(12)
        self.grid.setVerticalSpacing(12)
        self.cards = []
        self._cols = 0

    def set_cards(self, cards, single=False):
        self.cards = list(cards)
        self.single = single
        self._cols = 0
        self._layout()

    def _layout(self):
        cols = 1 if getattr(self, "single", False) else max(
            1, min(self.max_cols, len(self.cards) or 1, (self.width() + 12) // (self.col_width + 12)))
        if cols == self._cols:
            return
        self._cols = cols
        for c in self.cards:
            self.grid.removeWidget(c)
        for i, c in enumerate(self.cards):
            self.grid.addWidget(c, i // cols, i % cols, Qt.AlignTop)
            c.show()
        for k in range(self.max_cols):
            self.grid.setColumnStretch(k, 1 if k < cols else 0)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()


class TeamRow(QWidget):
    """Crest, (seed number,) name, and the row's buttons."""

    def __init__(self, crest, name, seed=None, buttons=(), warn="", parent=None):
        super().__init__(parent)
        self.buttons = []
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        if seed is not None:
            n = Badge(str(seed), FG_TERTIARY)
            n.setFixedWidth(30)
            h.addWidget(n)
        h.addWidget(PixmapLabel(28, crest))
        label = Note(name + (f"  ·  {warn}" if warn else ""), color=WARN if warn else FG_PRIMARY,
                     size=T_LABEL + 1)
        label.setWordWrap(False)
        label.setMinimumWidth(40)
        label.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # long names clip, never widen
        h.addWidget(label, stretch=1)
        for b in buttons:
            h.addWidget(b)
            self.buttons.append(b)


class OrderedList(QWidget):
    """Rows the user can put in order (▲ ▼), remove (✕) and add to (+): the
    tie-breakers, the neutral stadiums. Emits `changed(list)`."""

    changed = pyqtSignal(list)

    def __init__(self, add_text, labels, popup_title, focus, ordered=True, parent=None):
        super().__init__(parent)
        self.labels = labels              # callable value -> text
        self.options = []                 # what + can add
        self.values = []
        self.ordered = ordered
        self._focus = focus
        self._add_text, self._popup_title = add_text, popup_title
        self.v = QVBoxLayout(self)
        self.v.setContentsMargins(0, 0, 0, 0)
        self.v.setSpacing(6)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(4)
        self.v.addLayout(self.rows)
        self.add_btn = compact_button(add_text)
        self.add_btn.clicked.connect(self._open_add)
        bar = QHBoxLayout()
        bar.addWidget(self.add_btn)
        bar.addStretch(1)
        self.v.addLayout(bar)
        # (the owner registers add_btn: it is the list's field for issues)

    def set_values(self, values, options):
        if list(values) == self.values and list(options) == self.options:
            return
        self.values, self.options = list(values), list(options)
        for i in reversed(range(self.rows.count())):
            w = self.rows.takeAt(i).widget()
            if w is not None:
                self._focus.unregister_tree(w)
                w.setParent(None)
                w.deleteLater()
        for i, value in enumerate(self.values):
            row = QWidget()
            h = QHBoxLayout(row)
            h.setContentsMargins(0, 0, 0, 0)
            h.setSpacing(8)
            if self.ordered:
                n = Badge(str(i + 1), FG_TERTIARY)
                n.setFixedWidth(30)
                h.addWidget(n)
            h.addWidget(Note(self.labels(value), color=FG_PRIMARY, size=T_LABEL + 1), stretch=1)
            buttons = []
            if self.ordered:
                for text, delta in (("▲", -1), ("▼", 1)):
                    b = compact_button(text)
                    b.setFixedWidth(34)
                    b.setEnabled(0 <= i + delta < len(self.values))
                    b.clicked.connect(lambda _=False, i=i, d=delta: self._move(i, d))
                    h.addWidget(b)
                    buttons.append(b)
            rm = _icon_button("✕", lambda _=False, i=i: self._remove(i), "remove", removes=True)
            h.addWidget(rm)
            buttons.append(rm)
            for b in buttons:
                self._focus.register(b)
            self.rows.addWidget(row)
        self.add_btn.setEnabled(any(o not in self.values for o in self.options))

    def _move(self, i, d):
        vals = list(self.values)
        vals[i], vals[i + d] = vals[i + d], vals[i]
        self.changed.emit(vals)

    def _remove(self, i):
        vals = list(self.values)
        del vals[i]
        self.changed.emit(vals)

    def _open_add(self):
        free = [o for o in self.options if o not in self.values]
        if not free:
            return
        popup = PopupList(self.window(), width=380, height=420, own_keys=True)
        popup.set_title(self._popup_title)
        if len(free) > 12:
            box = popup.add_search_box()

            def refill(text):
                popup.clear_rows()
                for o in free:
                    if text.casefold() in self.labels(o).casefold():
                        popup.add_row(self.labels(o), o)
                popup._sync_rows()
                popup.set_highlight(0)
            box.textChanged.connect(refill)
        for o in free:
            popup.add_row(self.labels(o), o)
        popup.size_to(min(12, len(free)))
        popup.picked.connect(lambda o: self.changed.emit(self.values + [o]) if o is not None else None)
        popup.closed.connect(self.add_btn.setFocus)
        popup.open_at(self.add_btn, self.window())


# ═════════════════════════════════════════════════════════════════════════
# The screen
# ═════════════════════════════════════════════════════════════════════════
class TournamentEditorScreen(EditorScreen):
    TAB_TITLES = ["Setup", "Teams", "Rules", "Schedule", "Look"]
    RECORD_NOUN = "tournament"
    LIST_PLACEHOLDER = "filter"
    PREVIEW_PANE = True
    GROUP_LABEL = "Format"
    SORTS = [("name", "name"), ("issues", "most issues")]

    def __init__(self, ds, on_back, on_play=None):
        """`on_play(template_id)`: start a tournament of it (the wizard)."""
        self._designs = {}
        self._drafts = {}            # id -> design never saved (just created)
        self._teams_sig = None
        self._groups_holder_items = []
        self._starting = False
        self._stock, self._edits = {}, {}
        self.on_play = on_play
        super().__init__(ds, on_back)
        self._build_list_extras()
        self._build_setup()
        self._build_teams()
        self._build_rules()
        self._build_schedule()
        self._build_look()
        self._build_preview()
        self._build_start()
        self.shell.footer.target.setText("")
        self.shell.tabs.set_metrics(13, 30)

    # ── shorthands ───────────────────────────────────────────────────────
    @property
    def d(self):
        return self.session.working if self.session else C.new_design()

    def _page(self, tab):
        return self.shell.page(tab).layout_

    def _set(self, key, value, label=None, coalesce=True):
        def mutate(w):
            w[key] = value
            w.update(C.normalize(w))
        self.edit(label or f"{key.replace('_', ' ')}", mutate, coalesce_key=key if coalesce else None)

    def _replace(self, label, new_design):
        """The whole design replaced by `new_design` (a format change, a draw)."""
        def mutate(w):
            keep = w.get("id")
            w.clear()
            w.update(new_design)
            if keep:
                w["id"] = keep
        self.edit(label, mutate)

    def _field(self, key, widget, tab, grid=None):
        self.register_field(key, widget, tab)
        if grid is not None:
            grid.add(widget)
        return widget

    def _season_text(self, s):
        return f"{season_label(s)} squads" if s else "—"

    # ── list pane ────────────────────────────────────────────────────────
    def _build_list_extras(self):
        shell = self.shell
        shell.list_pane.setFixedWidth(250)
        shell.preview_pane.setFixedWidth(320)
        self.filters_toggle.hide()
        self.new_btn.setText("+ NEW")
        self.dup_btn.setText("COPY")
        self.del_btn = compact_button("DELETE")
        self.del_btn.clicked.connect(self.delete_record)
        bar = shell.list_layout.itemAt(0).layout()
        bar.addWidget(self.del_btn)
        self.focus.register(self.del_btn)

    def _load_stock(self):
        """The data's competitions, as the data has them (no edit), and the edits."""
        from app.tournament import formats
        self._stock = {tid: tpl for tid, tpl in formats.load_templates(edits=False).items()
                       if not tpl.get("custom")}
        self._edits = C.load_edits()

    def is_base(self, tid=None):
        tid = self.record_id if tid is None else tid
        return tid in getattr(self, "_stock", {})

    def list_rows(self):
        self._load_stock()
        self._designs = C.load_all()
        self._designs.update(self._drafts)
        rows = []
        for tid, tpl in self._stock.items():
            name = (self.session.working["name"] if self.session is not None and tid == self.record_id
                    else (self._edits.get(tid) or {}).get("name") or tpl.get("name") or tid)
            rows.append({"id": tid, "text": name, "tag": "EDITED" if tid in self._edits else "",
                         "color": ACCENT, "search": f"{name} {tpl.get('name', '')}",
                         "group": "Competitions", "errors": 0, "issues": 0, "stock": True})
        if self.session is not None and self.record_id in self._designs:
            self._designs[self.record_id] = self.session.working     # as it is now, saved or not
        for tid, d in self._designs.items():
            errors = 0
            try:
                errors = sum(1 for p in C.problems(self.ds, d) if p[2] == "error")
            except Exception:
                log.exception("checking %s", tid)
            rows.append({"id": tid, "text": d["name"] or "(no name)",
                         "tag": "DRAFT" if tid in self._drafts else (f"{errors} TO FIX" if errors else ""),
                         "color": WARN, "search": d["name"] + " " + C.FORMAT_LABELS[d["format"]],
                         "group": C.FORMAT_LABELS[d["format"]], "errors": errors, "issues": errors})
        if hasattr(self, "del_btn"):
            self.del_btn.setEnabled(self.record_id is not None)
        return rows

    def list_ids(self):
        return [it[0] for it in self.list_items()[0]]

    def list_items(self):
        """Yours first, then the data's competitions."""
        items, search = super().list_items()
        stock = {tid for tid in getattr(self, "_stock", {})}
        order = sorted(range(len(items)), key=lambda i: items[i][0] in stock)
        return [items[i] for i in order], [search[i] for i in order]

    def load_record(self, record_id):
        if self.is_base(record_id):
            raw = self._stock[record_id]
            edit = C.load_edits().get(record_id) or {}
            d = C.design_of_template(record_id, C.apply_edit(raw, edit))
            d["team_swaps"] = dict(edit.get("team_swaps") or {})
            return d
        if record_id in self._drafts:
            return copy.deepcopy(self._drafts[record_id])
        d = C.load_all().get(record_id)
        return dict(d, id=record_id) if d else None

    def write_record(self):
        if self.is_base():
            raw = self._stock[self.record_id]
            C.save_edit(self.record_id, C.edit_from_design(self.record_id, raw, self.session.working))
            return "Saved"
        tid = C.save(self.session.working, self.record_id)
        self._drafts.pop(tid, None)
        return "Saved"

    def after_save(self):
        self.del_btn.setEnabled(True)

    # ── start panel: new / copy / delete ─────────────────────────────────
    def _build_start(self):
        self.start_panel = StartPanel(self.focus)
        self.start_panel.picked.connect(self._create)
        self.start_panel.cancelled.connect(lambda: self._set_starting(False))
        self.shell.right_layout.insertWidget(0, self.start_panel)
        self.start_panel.hide()

    def _set_starting(self, on):
        self._starting = on
        self._refresh_chrome()
        if on:
            self.start_panel.cards[0].setFocus()
        else:
            self.list.setFocus()

    def _sync_start(self):
        show = self._starting or self.session is None
        sh = self.shell
        self.start_panel.setVisible(show)
        self.start_panel.cancel_btn.setVisible(self.session is not None)
        for w in (sh.tabs, sh.stack, sh.preview_pane, sh.preview_sep):
            w.setVisible(not show)

    def guard_dirty(self, then):
        """A draft counts as unsaved even before its first edit; discarding
        it drops it."""
        if self.session is None or self.record_id not in self._drafts:
            super().guard_dirty(then)
            return
        name = self.d["name"] or "This tournament"

        def choice(role):
            self._dialog = None
            if role == "save":
                if self.save():
                    then()
            elif role == "discard":
                self._drafts.pop(self.record_id, None)
                self.session = None
                self.record_id = None
                self._teams_sig = None
                self.reload_list()
                then()
            else:
                self.focus_list_or_content()
        self.show_dialog(ConfirmDialog(
            self, "Not saved", name,
            [("CANCEL", "neutral", "cancel"), ("DISCARD", "danger", "discard"),
             ("SAVE", "primary", "save")], choice))

    def new_record(self):
        self.guard_dirty(lambda: self._set_starting(True))

    def _default_season(self):
        seasons = sorted({s for ss in self.ds.teams.values() for s in ss}, reverse=True)
        count = {s: sum(1 for ts in self.ds.teams.values() if s in ts) for s in seasons}
        # the latest season most teams have a squad of
        full = [s for s in seasons if count[s] >= 0.9 * max(count.values())]
        return full[0] if full else ""

    def _create(self, key):
        design = C.starter(self.ds, key, self._default_season())
        if not design["name"]:
            design["name"] = "My tournament"
        if key != "blank":
            source, size = C.starter_fill_target(key)
            design = C.auto_fill(self.ds, design, source, size, best=True)
        taken = set(C.load_all()) | set(self._drafts)
        tid = C.unique_id(design["name"], taken)
        design["id"] = tid
        self._drafts[tid] = design
        self._starting = False
        self.reload_list()
        self.open_record(tid)
        self.shell.tabs.set_index(TAB_SETUP)
        self._sync_start()
        self.f_name.setFocus()

    def duplicate_record(self):
        if self.session is None or self.is_base():
            return
        src = copy.deepcopy(self.session.working)

        def go():
            src["name"] = (src["name"] or "Tournament") + " (copy)"
            tid = C.unique_id(src["name"], set(C.load_all()) | set(self._drafts))
            src["id"] = tid
            self._drafts[tid] = src
            self.reload_list()
            self.open_record(tid)
        self.guard_dirty(go)

    def delete_record(self):
        if self.record_id is None:
            return
        name = self.d["name"] or "this tournament"
        if self.is_base():
            tid = self.record_id

            def reset():
                C.delete_edit(tid)
                self.session = None
                self.record_id = None
                self.reload_list()
                self.open_record(tid)
                self.shell.footer.set_status("Back to the original", FG_SECONDARY)
            self.confirm("Back to the original?", name, "RESET", reset)
            return

        def go():
            tid = self.record_id
            self._drafts.pop(tid, None)
            C.delete(tid)
            self.record_id = None
            self.session = None
            self._teams_sig = None
            self.reload_list()
            mine = [t for t in self.list_ids() if not self.is_base(t)]
            if mine:
                self.open_record(mine[0])
            else:
                self.refresh_all()
            self.shell.footer.set_status(f"Deleted {name}", FG_SECONDARY)
        self.confirm("Delete this tournament?", name, "DELETE", go)

    def save(self):
        if self.session is not None and self.record_id in self._drafts and not self.session.is_dirty():
            # a fresh draft, untouched: its starting point is saved as it is
            try:
                message = self.write_record()
            except Exception as e:
                self.shell.footer.set_status(f"Save failed: {e}", DANGER_LITE)
                return False
            self.after_save()
            self.reload_list()
            self.refresh_all()
            self.shell.footer.set_status(message, GREEN)
            return True
        return super().save()

    # ── SETUP ────────────────────────────────────────────────────────────
    def _build_setup(self):
        page = self._page(TAB_SETUP)
        card = SectionCard("Tournament")
        grid = FieldGrid(columns=1)
        self.f_name = self._field("name", TextField("name", max_bytes=60), TAB_SETUP, grid)
        self.f_name.edited.connect(lambda v: self._set("name", v.strip(), "name"))
        self.f_season = self._field("season", ChoiceField("season", allow_blank=False,
                                    display=self._season_text), TAB_SETUP, grid)
        self.f_season.popup_title = "the squads of"
        self.f_season.edited.connect(lambda v: self._set("season", v, "season"))
        card.add(grid)
        page.addWidget(card)

        self.format_row = QWidget()
        self.format_row.setObjectName("formatRow")
        self.format_row.setStyleSheet("QWidget#formatRow { background: transparent; }")
        row = QHBoxLayout(self.format_row)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(10)
        self.format_cards = {}
        for fmt in C.FORMATS:
            fcard = FormatCard(fmt)
            fcard.activated.connect(lambda fmt=fmt: self._pick_format(fmt))
            row.addWidget(fcard)
            self.register_field("format", fcard, TAB_SETUP) if fmt == "league" else self.focus.register(fcard)
            self.format_cards[fmt] = fcard
        page.addWidget(self.format_row)

        # the table stage
        self.table_card = SectionCard("League")
        grid = FieldGrid(columns=1)
        self.f_legs = self._field("legs", SegmentField(
            "games", [1, 2], display=lambda v: {1: "1 leg", 2: "2 legs"}[v]), TAB_SETUP, grid)
        self.f_legs.edited.connect(lambda v: self._set("legs", int(v), "legs"))
        self.f_groups_n = self._field("group_count", NumberField("pools", lo=2, hi=16, allow_blank=False),
                                      TAB_SETUP, grid)
        self.f_groups_n.edited.connect(self._on_group_count)
        self.table_card.add(grid)
        grid = self.league_grid = FieldGrid(columns=1)
        self.f_teams_from = self._field("teams_from", SegmentField(
            "teams", ["pick", "category"],
            display=lambda v: {"pick": "I pick them", "category": "a category"}[v]), TAB_SETUP, grid)
        self.f_teams_from.edited.connect(lambda v: self._set("teams_from", v, "teams"))
        self.f_category = self._field("category", ChoiceField("category", allow_blank=True,
                                      blank_label="choose…"), TAB_SETUP, grid)
        self.f_category.edited.connect(lambda v: self._set("category", v or "", "category"))
        self.table_card.add(grid)
        page.addWidget(self.table_card)

        # the knockouts
        self.ko_card = SectionCard("Knockouts")
        grid = self.playoff_grid = FieldGrid(columns=1)
        self.f_playoffs = self._field("playoff_teams", SegmentField(
            "play-offs", C.LEAGUE_PLAYOFFS,
            display=lambda v: {0: "none", 2: "final", 4: "top 4", 6: "top 6", 8: "top 8"}[v]),
            TAB_SETUP, grid)
        self.f_playoffs.edited.connect(lambda v: self._set("playoff_teams", int(v), "play-offs"))
        self.ko_card.add(grid)
        grid = self.qualify_grid = FieldGrid(columns=1)
        self.f_qualify = self._field("qualify", NumberField("top per pool", lo=1, hi=8,
                                     allow_blank=False), TAB_SETUP, grid)
        self.f_qualify.edited.connect(lambda v: v and self._set("qualify", int(v), "going through"))
        self.f_extra = self._field("best_extra", NumberField("+ best", lo=0, hi=15,
                                   allow_blank=False), TAB_SETUP, grid)
        self.f_extra.edited.connect(lambda v: self._set("best_extra", int(v or 0), "best of the rest"))
        self.ko_card.add(grid)
        grid = FieldGrid(columns=1)
        self.f_seeding = self._field("seeding", ChoiceField(
            "pairing", list(C.SEEDINGS), allow_blank=False, display=lambda v: C.SEEDINGS[v]),
            TAB_SETUP, grid)
        self.f_seeding.edited.connect(lambda v: self._set("seeding", v, "pairing"))
        self.f_ko_draw = self._field("knockout_draw", ChoiceField(
            "a draw", list(C.KNOCKOUT_DRAWS), allow_blank=False,
            display=lambda v: C.KNOCKOUT_DRAWS[v]), TAB_SETUP, grid)
        self.f_ko_draw.edited.connect(lambda v: self._set("knockout_draw", v, "drawn knockout games"))
        self.f_third = self._field("third_place", SegmentField(
            "bronze final", [True, False], display=lambda v: YES_NO[v]), TAB_SETUP, grid)
        self.f_third.edited.connect(lambda v: self._set("third_place", bool(v), "bronze final"))
        self.ko_card.add(grid)
        page.addWidget(self.ko_card)
        page.addStretch(1)

    def _pick_format(self, fmt):
        if self.session is None or self.d["format"] == fmt:
            return
        self._replace(f"format: {C.FORMAT_LABELS[fmt]}", C.change_format(self.d, fmt))

    def _on_group_count(self, v):
        if self.session is None or not str(v).strip():
            return
        n = int(v)
        if n != len(self.d["groups"]):
            self._replace(f"{n} pools", C.set_group_count(self.d, n))

    # ── TEAMS ────────────────────────────────────────────────────────────
    def _build_teams(self):
        page = self._page(TAB_TEAMS)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        self.fill_btn = compact_button("AUTO-FILL…", "primary")
        self.fill_btn.clicked.connect(self._ask_fill)
        self.shuffle_btn = compact_button("SHUFFLE")
        self.shuffle_btn.clicked.connect(self._shuffle)
        self.clear_btn = compact_button("CLEAR")
        self.clear_btn.clicked.connect(self._clear_teams)
        for b in (self.fill_btn, self.shuffle_btn, self.clear_btn):
            bar.addWidget(b)
            self.focus.register(b)
        bar.addStretch(1)
        self.teams_count = Note("", color=FG_SECONDARY, size=T_LABEL + 1)
        self.teams_count.setWordWrap(False)
        bar.addWidget(self.teams_count)
        page.addLayout(bar)
        self.teams_note = Note("", color=FG_TERTIARY)
        page.addWidget(self.teams_note)
        self.groups_grid = holder = ReflowGrid()
        self.register_field("groups", holder, TAB_TEAMS)
        self.focus.unregister(holder)
        page.addWidget(holder)
        page.addStretch(1)

    def _season_of(self, tid):
        from app.tournament.engine import pick_season
        seasons = self.ds.teams.get(tid) or {}
        return pick_season(seasons, self.d["season"] or "0") if seasons else ""

    def _team_name(self, tid):
        seasons = self.ds.teams.get(tid) or {}
        if not seasons:
            return f"missing team {tid}"
        return seasons[self._season_of(tid)].get("name", tid)

    def _crest(self, tid, size=28):
        if not self.ds.teams.get(tid):
            return placeholder_crest(size)
        return team_crest(self.ds, tid, self._season_of(tid), size)

    def _rebuild_groups(self):
        d = self.d
        base = self.is_base()
        sig = (base, d["format"], d["season"], d["teams_from"],
               tuple((g["name"], tuple(g["teams"])) for g in d["groups"]))
        if sig == self._teams_sig:
            return
        self._teams_sig = sig
        for w in self._groups_holder_items:
            self.focus.unregister_tree(w)
            w.setParent(None)
            w.deleteLater()
        self._groups_holder_items = []
        if d["teams_from"] == "category":
            return
        fmt = d["format"]
        short = self._short_squads()
        n_groups = len(d["groups"])
        cards = []
        for i, g in enumerate(d["groups"]):
            right = QWidget()
            rh = QHBoxLayout(right)
            rh.setContentsMargins(0, 0, 0, 0)
            rh.setSpacing(6)
            rh.addWidget(Badge(f"{len(g['teams'])}", FG_TERTIARY))
            card = SectionCard(C.group_name(d, i), right=right)
            if base:
                pass
            elif fmt == "groups":
                rename = _icon_button("✎", lambda _=False, i=i: self._ask_group_name(i), "rename the pool")
                rh.addWidget(rename)
                self.focus.register(rename)
            for j, tid in enumerate(g["teams"]):
                buttons = []
                if base:
                    buttons.append(_icon_button("⇄", lambda _=False, tid=tid: self._ask_swap(tid),
                                                "swap for another team"))
                elif fmt == "cup":
                    for text, delta in (("▲", -1), ("▼", 1)):
                        b = _icon_button(text, lambda _=False, i=i, j=j, dl=delta: self._move_team(i, j, dl),
                                         "seed up" if delta < 0 else "seed down")
                        b.setEnabled(0 <= j + delta < len(g["teams"]))
                        buttons.append(b)
                if fmt == "groups" and n_groups > 1 and not base:
                    buttons.append(_icon_button("⇄", lambda _=False, i=i, j=j, b=None: self._ask_move(i, j),
                                                "move to another pool"))
                if not base:
                    buttons.append(_icon_button("✕", lambda _=False, i=i, j=j: self._remove_team(i, j),
                                                "take the team out", removes=True))
                warn = ("not in the data" if tid not in self.ds.teams else
                        "no full squad" if tid in short else "")
                row = TeamRow(self._crest(tid), self._team_name(tid) if tid in self.ds.teams else tid,
                              seed=j + 1 if fmt == "cup" else None, buttons=buttons, warn=warn)
                for b in row.buttons:
                    self.focus.register(b)
                card.add(row)
            if not base:
                add = compact_button("+ ADD TEAMS")
                add.clicked.connect(lambda _=False, i=i, b=add: self._ask_teams(i, b))
                card.add(add)
                self.focus.register(add)
            cards.append(card)
            self._groups_holder_items.append(card)
        self.groups_grid.set_cards(cards, single=fmt != "groups")

    def _short_squads(self):
        from app.tournament.engine import usable_squad
        return {t for t in C.all_teams(self.d)
                if self.ds.teams.get(t) and len(usable_squad(self.ds, t, self._season_of(t))) < 22}

    def _ask_teams(self, group_index, anchor):
        """Several teams at once: click to tick, ALL ticks what the search
        shows, DONE (or Esc) adds them."""
        taken = set(C.all_teams(self.d))
        teams = sorted((t for t in C.teams_from_source(self.ds, "all", self.d["season"]) if t not in taken),
                       key=lambda t: self._team_name(t).lower())
        if not teams:
            self.shell.footer.set_status("Every team with a squad is already in", WARN)
            return

        def kind(t):
            info = self.ds.teams[t].get(self._season_of(t)) or {}
            return str(info.get("category") or info.get("type") or "")

        cats = {t: kind(t) for t in teams}
        popup = PopupList(self.window(), width=470, height=580, own_keys=True)
        ticked = []                       # in the order ticked
        specs = {}
        bar = QWidget()
        bh = QHBoxLayout(bar)
        bh.setContentsMargins(0, 0, 0, 0)
        bh.setSpacing(6)
        box = QLineEdit()
        box.setPlaceholderText("Name or category…")
        box.setStyleSheet(
            f"QLineEdit {{ background: {BG_RAISED}; color: {FG_PRIMARY}; border: 1px solid {BORDER};"
            f" padding: 4px 8px; font-family: '{FONT_DISPLAY}'; font-size: 12pt; }}"
            f"QLineEdit:focus {{ border: 1px solid {ACCENT}; }}")
        all_btn = compact_button("ALL")
        done_btn = compact_button("ADD", "primary")
        bh.addWidget(box, stretch=1)
        bh.addWidget(all_btn)
        bh.addWidget(done_btn)
        popup.set_toolbar_widget(bar)
        popup.search_box = box

        def shown():
            q = box.text().casefold().strip()
            return [t for t in teams if not q or q in self._team_name(t).casefold()
                    or q in cats[t].casefold()]

        def mark(tid):
            s = specs.get(tid)
            if s is not None:
                s.selected = tid in ticked
                s.tag = "✓" if s.selected else ""
                popup.scroll.refresh_spec(s)

        def retitle():
            popup.set_title(f"add teams · {len(ticked)} ticked" if ticked else "add teams")
            done_btn.setText(f"ADD {len(ticked)}" if ticked else "ADD")
            done_btn.setEnabled(bool(ticked))
            all_btn.setText("ALL")

        def fill(_text=""):
            popup.clear_rows()
            specs.clear()
            for t in shown():
                specs[t] = popup.add_row(self._team_name(t), t, icon=self._crest(t, 24), subtitle=cats[t],
                                         selected=t in ticked, tag="✓" if t in ticked else "")
            popup._sync_rows()
            popup.set_highlight(0)

        def toggle(tid):
            if tid in ticked:
                ticked.remove(tid)
            else:
                ticked.append(tid)
            mark(tid)
            retitle()

        def tick_all():
            rows = shown()
            if all(t in ticked for t in rows):
                for t in rows:
                    ticked.remove(t)
            else:
                ticked.extend(t for t in rows if t not in ticked)
            for t in rows:
                mark(t)
            retitle()

        popup.keep_open = lambda tid: True
        popup.picked.connect(lambda tid: toggle(tid) if tid else None)
        box.textChanged.connect(fill)
        all_btn.clicked.connect(tick_all)
        done_btn.clicked.connect(popup.close_popup)
        popup.closed.connect(anchor.setFocus)
        popup.closed.connect(lambda: self._add_teams(group_index, ticked) if ticked else None)
        retitle()
        fill()
        popup.size_to(12)
        popup.open_at(anchor, self.window())
        box.setFocus()

    def _ask_swap(self, tid):
        """A data competition's team swapped for another: it takes its place,
        its games and its pool."""
        taken = set(C.all_teams(self.d))
        teams = sorted((t for t in C.teams_from_source(self.ds, "all", self.d["season"]) if t not in taken),
                       key=lambda t: self._team_name(t).lower())
        popup = PopupList(self.window(), width=440, height=520, own_keys=True)
        popup.set_title(f"in place of {self._team_name(tid)}")
        box = popup.add_search_box("Name or category…")

        def kind(t):
            info = self.ds.teams[t].get(self._season_of(t)) or {}
            return str(info.get("category") or info.get("type") or "")

        def fill(text=""):
            popup.clear_rows()
            q = text.casefold().strip()
            for t in teams:
                if not q or q in self._team_name(t).casefold() or q in kind(t).casefold():
                    popup.add_row(self._team_name(t), t, icon=self._crest(t, 24), subtitle=kind(t))
            popup._sync_rows()
            popup.set_highlight(0)
        box.textChanged.connect(fill)
        fill()
        popup.size_to(10)

        def go(new):
            if new:
                self._replace(f"{self._team_name(new)} in place of {self._team_name(tid)}",
                              C.swap_team(self.d, tid, new))
        popup.picked.connect(go)
        popup.open_at(self.focusWidget() or self, self.window())

    def _add_teams(self, i, tids):
        tids = list(tids)

        def mutate(w):
            have = {t for g in w["groups"] for t in g["teams"]}
            w["groups"][i]["teams"] += [t for t in tids if t not in have]
        n = len(tids)
        self.edit(f"add {n} team{'s' if n != 1 else ''}", mutate)

    def _remove_team(self, i, j):
        name = self._team_name(self.d["groups"][i]["teams"][j])
        self.edit(f"remove {name}", lambda w: w["groups"][i]["teams"].pop(j))

    def _move_team(self, i, j, delta):
        def mutate(w):
            ts = w["groups"][i]["teams"]
            ts[j], ts[j + delta] = ts[j + delta], ts[j]
        self.edit("draw order", mutate)

    def _ask_move(self, i, j):
        d = self.d
        tid = d["groups"][i]["teams"][j]
        popup = PopupList(self.window(), width=300, height=360, own_keys=True)
        popup.set_title(f"move {self._team_name(tid)} to")
        for k, g in enumerate(d["groups"]):
            if k != i:
                popup.add_row(C.group_name(d, k), k, tag=f"{len(g['teams'])}")
        popup.size_to(len(d["groups"]) - 1)

        def go(k):
            if k is None:
                return

            def mutate(w):
                w["groups"][k]["teams"].append(w["groups"][i]["teams"].pop(j))
            self.edit(f"move {self._team_name(tid)}", mutate)
        popup.picked.connect(go)
        popup.open_at(self.focusWidget() or self, self.window())

    def _ask_group_name(self, i):
        self.ask_text("Pool name", "name", self.d["groups"][i]["name"] or C.group_name(self.d, i),
                      lambda v: self._rename_group(i, v))

    def _rename_group(self, i, v):
        def mutate(w):
            w["groups"][i]["name"] = v.strip()
        self.edit("pool name", mutate)

    def _shuffle(self):
        self._replace("shuffle the draw", C.shuffle_draw(self.d))

    def _clear_teams(self):
        if not C.all_teams(self.d):
            return

        def mutate(w):
            for g in w["groups"]:
                g["teams"] = []
        self.edit("clear the teams", mutate)
        self.shell.footer.set_status("Teams cleared · Ctrl+Z undoes", FG_SECONDARY)

    def _ask_fill(self):
        if self.session is None:
            return
        d = self.d
        cats = C.categories(self.ds)
        sources = list(C.TEAM_SOURCES) + [f"cat:{c}" for c in cats if c.lower() != "international"]
        source = ChoiceField("teams from", sources, allow_blank=False,
                             display=lambda s: C.TEAM_SOURCES.get(s) or s[4:])
        source.searchable = True
        how = SegmentField("pick", ["best", "random"], display=lambda v: v)
        sizes = [len(g["teams"]) for g in d["groups"]]
        if d["format"] == "groups":
            label, size = "teams per pool", max(sizes + [4])
        elif d["format"] == "cup":
            label, size = "teams", max(len(C.all_teams(d)), 8)
        else:
            label, size = "teams", max(len(C.all_teams(d)), 8)
        count = NumberField(label, lo=2, hi=64, allow_blank=False)
        count.set_value(size)
        source.set_value("clubs" if C.all_teams(d) and not set(C.teams_from_source(
            self.ds, "internationals", d["season"])) & set(C.all_teams(d)) else "internationals")
        how.set_value("best")

        def done(role):
            self._dialog = None
            if role != "ok":
                return
            n = count.as_int() or size
            filled = C.auto_fill(self.ds, self.d, source.value(), n, best=how.value() == "best")
            added = len(C.all_teams(filled)) - len(C.all_teams(self.d))
            self._replace("auto-fill", filled)
            self.shell.footer.set_status(
                f"Added {added} team{'s' if added != 1 else ''}" if added else
                "No team left to add from there", GREEN if added else WARN)
        self.show_dialog(FormDialog(
            self, "Auto-fill", "", {"source": source, "count": count, "how": how},
            [("CANCEL", "neutral", "cancel"), ("FILL", "primary", "ok")], done, width=520))

    # ── RULES ────────────────────────────────────────────────────────────
    def _build_rules(self):
        page = self._page(TAB_RULES)
        card = SectionCard("Table points")
        top = FieldGrid(columns=1)
        presets = list(C.POINTS_PRESETS) + ["custom"]
        self.f_points = self._field("points", ChoiceField(
            "system", presets, allow_blank=False,
            display=lambda k: C.POINTS_PRESETS[k]["label"] if k in C.POINTS_PRESETS else "Custom"),
            TAB_RULES, top)
        self.f_points.edited.connect(self._on_points_preset)
        self.f_try_bonus = ChoiceField("try bonus", list(C.TRY_BONUS), allow_blank=False,
                                       display=lambda v: C.TRY_BONUS[v])
        self.f_try_bonus.edited.connect(lambda v: self._set_point("try_bonus", v))
        top.add(self.f_try_bonus)
        self.register_field("points.try_bonus", self.f_try_bonus, TAB_RULES)
        card.add(top)
        grid = FieldGrid(columns=2)
        self.f_pts = {}
        for key, label, hi in (("win", "win", 10), ("draw", "draw", 10), ("loss", "loss", 10),
                               ("losing_bonus", "close loss ≤", 20),
                               ("grand_slam", "slam", 10)):
            f = NumberField(label, lo=0, hi=hi, allow_blank=False)
            f.edited.connect(lambda v, k=key: self._set_point(k, int(v or 0)))
            grid.add(f)
            self.register_field(f"points.{key}", f, TAB_RULES)
            self.f_pts[key] = f
        card.add(grid)
        self.points_example = Note("", color=FG_SECONDARY)
        card.add(self.points_example)
        page.addWidget(card)

        card = SectionCard("Level on points")
        self.tb_list = OrderedList("+ ADD A TIE-BREAKER", lambda k: C.TIEBREAKERS.get(k, k),
                                   "add a tie-breaker", self.focus)
        self.tb_list.changed.connect(lambda vals: self._set("tiebreakers", vals, "tie-breakers",
                                                            coalesce=False))
        card.add(self.tb_list)
        self.register_field("tiebreakers", self.tb_list.add_btn, TAB_RULES)
        page.addWidget(card)

        card = SectionCard("Discipline")
        grid = FieldGrid(columns=1)
        self.f_discipline = self._field("discipline", ChoiceField(
            "bans", list(C.DISCIPLINE_PRESETS), allow_blank=False,
            display=lambda k: C.DISCIPLINE_PRESETS[k]["label"] if k in C.DISCIPLINE_PRESETS
            else "As the competition has it"), TAB_RULES, grid)
        self.f_discipline.edited.connect(lambda v: self._set("discipline", v, "discipline"))
        card.add(grid)
        page.addWidget(card)

        card = SectionCard("Starting settings")
        grid = FieldGrid(columns=2)
        self.f_half = ChoiceField("half length", HALF_LENGTHS, allow_blank=False,
                                  display=lambda v: f"{v[:-1]} min" if str(v).endswith("m") else v)
        self.f_half.edited.connect(lambda v: self._set_option("halftime_length", v))
        grid.add(self.f_half)
        self.register_field("options.halftime_length", self.f_half, TAB_RULES)
        self.f_opts = {}
        for key in ("injuries", "fatigue", "suspensions"):
            f = SegmentField(key, [True, False], display=lambda v: ON_OFF[v])
            f.edited.connect(lambda v, k=key: self._set_option(k, bool(v)))
            grid.add(f)
            self.register_field(f"options.{key}", f, TAB_RULES)
            self.f_opts[key] = f
        card.add(grid)
        page.addWidget(card)
        page.addStretch(1)

    def _on_points_preset(self, key):
        if key == "custom":
            self._set_point("preset", "custom")
            return

        def mutate(w):
            w["points"] = dict({k: v for k, v in C.POINTS_PRESETS[key].items() if k != "label"},
                               preset=key)
        self.edit("points system", mutate)

    def _set_point(self, key, value):
        def mutate(w):
            pts = dict(w["points"])
            pts[key] = value
            if key != "preset":
                pts["preset"] = "custom"
            w["points"] = pts
            w.update(C.normalize(w))
        self.edit(f"points: {key.replace('_', ' ')}", mutate, coalesce_key=f"points.{key}")

    def _set_option(self, key, value):
        def mutate(w):
            w["options"] = dict(w["options"], **{key: value})
        self.edit(key.replace("_", " "), mutate, coalesce_key=f"options.{key}")

    def _points_example(self, p):
        tb = p["try_bonus"] != "none"
        win = p["win"] + (1 if tb else 0)
        parts = [f"win {p['win']}" + (f" (+1 with {'4 tries' if p['try_bonus'] == '4tries' else '3 more tries'}"
                                        f" = {win})" if tb else ""),
                 f"draw {p['draw']}", f"loss {p['loss']}"]
        if p["losing_bonus"]:
            parts[-1] += f" (+1 within {p['losing_bonus']})"
        if p["grand_slam"]:
            parts.append(f"all wins +{p['grand_slam']}")
        return " · ".join(parts)

    # ── SCHEDULE ─────────────────────────────────────────────────────────
    def _stadium_name(self, sid):
        info = self.ds.stadiums.get(str(sid)) or {}
        name = info.get("name") or f"stadium {sid}"
        country = info.get("country")
        return f"{name} ({str(country).title()})" if country else name

    def _build_schedule(self):
        page = self._page(TAB_SCHEDULE)
        card = SectionCard("Where")
        grid = FieldGrid(columns=1)
        self.f_venue = self._field("venue", SegmentField(
            "table games", ["home", "neutral"],
            display=lambda v: {"home": "home ground", "neutral": "neutral"}[v]), TAB_SCHEDULE, grid)
        self.f_venue.edited.connect(lambda v: self._set("venue", v, "venue"))
        self.f_ko_venue = self._field("knockout_venue", SegmentField(
            "knockouts", ["home", "neutral"],
            display=lambda v: {"home": "better seed hosts", "neutral": "neutral"}[v]),
            TAB_SCHEDULE, grid)
        self.f_ko_venue.edited.connect(lambda v: self._set("knockout_venue", v, "knockout venue"))
        stadiums = sorted(self.ds.stadiums, key=lambda s: self._stadium_name(s).lower())
        self.f_final = self._field("final_stadium", ChoiceField(
            "the final", stadiums, allow_blank=True, blank_label="like the other knockouts",
            display=self._stadium_name), TAB_SCHEDULE, grid)
        self.f_final.searchable = True
        self.f_final.edited.connect(lambda v: self._set("final_stadium", v or "", "final venue"))
        card.add(grid)
        page.addWidget(card)

        self.venue_card = SectionCard("Neutral stadiums")
        self.venue_list = OrderedList("+ ADD A STADIUM", self._stadium_name, "add a stadium",
                                      self.focus)
        self.venue_list.changed.connect(lambda vals: self._set("venues", vals, "stadiums", coalesce=False))
        self.venue_card.add(self.venue_list)
        self.venue_note = Note("None chosen: every stadium in turn.", color=FG_TERTIARY)
        self.venue_card.add(self.venue_note)
        self.register_field("venues", self.venue_list.add_btn, TAB_SCHEDULE)
        page.addWidget(self.venue_card)

        card = SectionCard("When")
        grid = FieldGrid(columns=1)
        self.f_month = ChoiceField("starts in", list(range(1, 13)), allow_blank=False,
                                   display=lambda m: MONTHS[int(m) - 1])
        self.f_month.edited.connect(lambda m: self._set_start(month=int(m)))
        self.f_day = NumberField("day", lo=1, hi=31, allow_blank=False)
        self.f_day.edited.connect(lambda v: v and self._set_start(day=int(v)))
        self.f_every = self._field("every", NumberField("days between rounds", lo=1, hi=60,
                                   allow_blank=False), TAB_SCHEDULE)
        self.f_every.edited.connect(lambda v: v and self._set("every", int(v), "days between rounds"))
        for f in (self.f_month, self.f_day, self.f_every):
            grid.add(f)
        self.register_field("start", self.f_month, TAB_SCHEDULE)
        self.register_field("start.day", self.f_day, TAB_SCHEDULE)
        card.add(grid)
        self.dates_note = Note("", color=FG_SECONDARY)
        card.add(self.dates_note)
        page.addWidget(card)
        page.addStretch(1)

    def _set_start(self, month=None, day=None):
        m, dd = (int(x) for x in self.d["start"].split("-"))
        m = month or m
        dd = min(day or dd, [31, 29, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][m - 1])
        self._set("start", f"{m:02d}-{dd:02d}", "start date")

    def _dates_text(self, d):
        try:
            year = int(d["season"]) if d["season"] else date.today().year
            m, dd = (int(x) for x in d["start"].split("-"))
            start = date(year - 1 if m >= 7 else year, m, dd)
        except (ValueError, TypeError):
            return ""
        days = C.matchdays(d)
        if not days:
            return ""
        end = start + timedelta(days=(days - 1) * d["every"] + (7 if any(
            b["kind"] != "table" for b in C.structure(d)) else 0))
        return (f"{days} rounds, {start.strftime('%d %B %Y').lstrip('0')} "
                f"to about {end.strftime('%B %Y')}")

    # ── LOOK ─────────────────────────────────────────────────────────────
    def _build_look(self):
        page = self._page(TAB_LOOK)
        card = SectionCard("In the game")
        grid = FieldGrid(columns=1)
        self.f_desc = self._field("description", TextField("description", max_bytes=200,
                                  placeholder="written from the format"), TAB_LOOK, grid)
        self.f_desc.edited.connect(lambda v: self._set("description", v.strip(), "description"))
        self.f_match_type = self._field("match_type", ChoiceField(
            "presentation", list(C.MATCH_TYPES), allow_blank=False,
            display=lambda v: C.MATCH_TYPES.get(v, v)), TAB_LOOK, grid)
        self.f_match_type.edited.connect(lambda v: self._set("match_type", v, "presentation"))
        self.f_branding = self._field("branding", ChoiceField(
            "look", allow_blank=True, blank_label="none: the home team's",
            display=lambda c: competition_branding.label(self.ds, c)), TAB_LOOK, grid)
        self.f_branding.popup_title = "competition look"
        self.f_branding.searchable = True
        self.f_branding.edited.connect(lambda v: self._set("branding", v or "", "competition look"))
        self.f_variant = self._field("variant", ChoiceField(
            "squads", allow_blank=True, blank_label="none: the usual squads",
            display=lambda v: v.replace("_", " ").title()), TAB_LOOK, grid)
        self.f_variant.popup_title = "competition squads"
        self.f_variant.searchable = True
        self.f_variant.edited.connect(lambda v: self._set("variant", v or "", "competition squads"))
        self.f_trophy = self._field("trophy_lift", SegmentField(
            "trophy lift", [True, False], display=lambda v: YES_NO[v]), TAB_LOOK, grid)
        self.f_trophy.edited.connect(lambda v: self._set("trophy_lift", bool(v), "trophy lift"))
        card.add(grid)
        page.addWidget(card)
        page.addStretch(1)

    # ── preview pane ─────────────────────────────────────────────────────
    def _build_preview(self):
        lay = self.shell.preview_layout
        lay.setSpacing(10)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.pv_emblem = PixmapLabel(56, placeholder_crest(56))
        head.addWidget(self.pv_emblem)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.pv_name = Note("", color=FG_PRIMARY, size=14)
        self.pv_sub = Note("", color=FG_TERTIARY)
        col.addWidget(self.pv_name)
        col.addWidget(self.pv_sub)
        head.addLayout(col, stretch=1)
        lay.addLayout(head)
        stats = QHBoxLayout()
        stats.setSpacing(8)
        self.pv_teams, self.pv_games, self.pv_rounds = StatTile("teams"), StatTile("games"), StatTile("rounds")
        for t in (self.pv_teams, self.pv_games, self.pv_rounds):
            stats.addWidget(t)
        lay.addLayout(stats)
        self.pv_diagram = StructureDiagram()
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        holder = QWidget()
        holder.setObjectName("diagramHolder")
        holder.setStyleSheet("QWidget#diagramHolder { background: transparent; }")
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 6, 0)
        hv.addWidget(self.pv_diagram)
        hv.addStretch(1)
        scroll.setWidget(holder)
        scroll.viewport().setStyleSheet("background: transparent;")
        lay.addWidget(scroll, stretch=1)
        self.pv_status = Note("", color=GREEN, size=T_LABEL + 1)
        lay.addWidget(self.pv_status)
        self.play_btn = compact_button("PLAY  ›", "primary")
        self.play_btn.setMinimumHeight(44)
        self.play_btn.clicked.connect(self._play)
        lay.addWidget(self.play_btn)
        self.focus.register(self.play_btn)

    def _refresh_preview(self, d, issues):
        base = self.is_base()
        tpl = self._base_template() if base else C.compile_template(d, self.record_id or "preview")
        self.pv_emblem.set_pixmap(competition_emblem(self.ds, tpl, 56))
        self.pv_name.setText(d["name"] or "No name yet")
        if d["teams_from"] == "category":
            sub = f"every {d['category'] or '…'} club, each season"
        else:
            sub = self._season_text(d["season"])
        self.pv_sub.setText(f"{C.FORMAT_LABELS[d['format']]} · {sub}")
        cat = d["teams_from"] == "category"
        empty = not C.all_teams(d) and not cat
        if base:
            blocks = C.template_structure(tpl)
            self.pv_teams.set_value("—" if cat else len(C.all_teams(d)))
            self.pv_games.set_value("—" if cat else sum(b["matches"] or 0 for b in blocks))
            self.pv_rounds.set_value("—" if cat else len({f.get("date") for s in tpl.get("stages") or []
                                                          for f in s.get("fixtures") or []} - {None})
                                     + sum(1 for b in blocks if b["kind"] != "table") or "—")
            self.pv_diagram.set_blocks(blocks)
        else:
            self.pv_teams.set_value("—" if cat else len(C.all_teams(d)))
            self.pv_games.set_value("—" if cat else C.match_count(d))
            self.pv_rounds.set_value("—" if cat else C.matchdays(d))
            self.pv_diagram.set_blocks([] if empty else C.structure(d), "Add teams to see it" if empty else "")
        errors = [m for _k, m, s in issues if s == "error"]
        warns = [m for _k, m, s in issues if s == "warn"]
        if errors:
            self.pv_status.setText(f"✕  {errors[0]}" + (f"  (+{len(errors) - 1} more)" if len(errors) > 1 else ""))
            self.pv_status.setStyleSheet(f"color: {DANGER_LITE}; background: transparent;")
        elif warns:
            self.pv_status.setText(f"!  {warns[0]}")
            self.pv_status.setStyleSheet(f"color: {WARN}; background: transparent;")
        else:
            self.pv_status.setText("✓  Ready")
            self.pv_status.setStyleSheet(f"color: {GREEN}; background: transparent;")
        self.play_btn.setEnabled(not errors and self.on_play is not None)

    def _play(self):
        if self.session is None or self.on_play is None:
            return
        if (self.session.is_dirty() or self.record_id in self._drafts) and not self.save():
            return
        self.on_play(self.record_id)

    # ── refresh ──────────────────────────────────────────────────────────
    def on_record_opened(self):
        self._teams_sig = None
        self._starting = False

    def refresh_view(self):
        d = self.d
        fmt = d["format"]
        self._sync_start()
        self.f_name.set_value(d["name"])
        self.f_desc.set_value(d["description"])
        seasons = sorted({s for ss in self.ds.teams.values() for s in ss}, reverse=True)
        self.f_season.set_options(seasons)
        self.f_season.set_value(d["season"])
        self.f_variant.set_options(C.known_variants(self.ds))
        self.f_variant.set_value(d["variant"])
        self.f_match_type.set_value(d["match_type"])
        self.f_branding.set_options(competition_branding.all_choices(self.ds))
        self.f_branding.set_value(d["branding"])
        self.f_trophy.set_value(d["trophy_lift"])
        cat_mode = d["teams_from"] == "category"
        base = self.is_base()
        self.f_season.setEnabled(not cat_mode and not base)
        if base:
            self.f_season.set_options([d["season"]] if d["season"] else [])
        self.format_row.setVisible(not base)
        self.shell.tabs.set_hidden([TAB_SCHEDULE] if base else [])
        discipline = list(C.DISCIPLINE_PRESETS) + ([C.ORIGINAL] if base else [])
        self.f_discipline.set_options(discipline)

        # setup
        for f, card in self.format_cards.items():
            card.selected = f == fmt
            card.update()
        self.table_card.setVisible(fmt != "cup")
        self.table_card.set_title({"league": "League", "groups": "Pool stage"}.get(fmt, ""))
        self.f_legs.set_value(d["legs"])
        self.f_groups_n.setVisible(fmt == "groups")
        self.f_groups_n.set_value(len(d["groups"]))
        self.league_grid.setVisible(fmt == "league")
        self.f_teams_from.set_value(d["teams_from"])
        self.f_category.setVisible(cat_mode)
        self.f_category.set_options(C.categories(self.ds))
        self.f_category.set_value(d["category"])
        self.playoff_grid.setVisible(fmt == "league")
        self.f_playoffs.set_value(d["playoff_teams"])
        self.qualify_grid.setVisible(fmt == "groups")
        self.f_qualify.set_value(d["qualify"])
        self.f_extra.set_value(d["best_extra"])
        self.f_extra.label = "+ best " + {1: "runners-up", 2: "thirds", 3: "fourths"}.get(d["qualify"], "of the rest")
        self.qualify_grid.align_labels()
        seedings = {"groups": ["cross", "ranked"], "cup": ["ranked", "listed"]}.get(fmt, [])
        self.f_seeding.set_options(seedings)
        self.f_seeding.set_value(d["seeding"] if d["seeding"] in seedings else (seedings or [""])[0])
        self.f_seeding.setVisible(bool(seedings))
        has_ko = C.qualifiers(d) >= 2 or fmt == "cup"
        self.f_third.set_value(d["third_place"])
        self.f_third.setVisible(has_ko)
        self.f_ko_draw.set_value(d["knockout_draw"])
        self.f_ko_draw.setVisible(has_ko)
        self.ko_card.set_title("The cup" if fmt == "cup" else ("Play-offs" if fmt == "league" else "Knockouts"))
        self.ko_card.setVisible((has_ko or fmt == "league") and not base)
        self.table_card.setVisible(fmt != "cup" and not base)

        # teams
        self._rebuild_groups()
        n = len(C.all_teams(d))
        self.teams_count.setText("" if cat_mode else f"{n} team{'s' if n != 1 else ''}")
        for b in (self.fill_btn, self.shuffle_btn, self.clear_btn):
            b.setVisible(not cat_mode and not base)
        self.shuffle_btn.setEnabled(n > 1)
        self.clear_btn.setEnabled(n > 0)
        self.teams_note.setVisible(cat_mode)
        self.teams_note.setText(f"Every {d['category'] or '…'} club plays, one edition per season."
                                if cat_mode else "")
        if base and not cat_mode:
            self.teams_note.setVisible(True)
            self.teams_note.setText("⇄ swaps a team: it takes the other's games.")

        # rules
        p = d["points"]
        self.f_points.set_value(p["preset"])
        for key, f in self.f_pts.items():
            f.set_value(p[key])
        self.f_try_bonus.set_value(p["try_bonus"])
        self.points_example.setText(self._points_example(p))
        self.tb_list.set_values(d["tiebreakers"], list(C.TIEBREAKERS))
        self.f_discipline.set_value(d["discipline"])
        self.f_half.set_value(d["options"]["halftime_length"])
        for key, f in self.f_opts.items():
            f.set_value(bool(d["options"].get(key, True)))

        # schedule
        self.f_venue.set_value(d["venue"])
        self.f_ko_venue.set_value(d["knockout_venue"])
        self.f_ko_venue.setVisible(has_ko)
        self.f_final.set_value(d["final_stadium"])
        self.f_final.setVisible(has_ko)
        neutral = d["venue"] == "neutral" or (has_ko and d["knockout_venue"] == "neutral")
        self.venue_card.setVisible(neutral)
        self.venue_list.set_values(d["venues"], sorted(self.ds.stadiums,
                                                       key=lambda s: self._stadium_name(s).lower()))
        m, dd = (int(x) for x in d["start"].split("-"))
        self.f_month.set_value(m)
        self.f_day.set_value(dd)
        self.f_every.set_value(d["every"])
        self.dates_note.setText(self._dates_text(d))

    def _base_template(self):
        """The data competition as the open edit makes it."""
        raw = self._stock[self.record_id]
        return C.apply_edit(raw, C.edit_from_design(self.record_id, raw, self.d))

    def _base_issues(self):
        from app.tournament import formats
        from app.tournament.engine import default_participants
        d = self.d
        out = []
        if not d["name"].strip():
            out.append(("name", "Give the tournament a name", "error"))
        tpl = self._base_template()
        if not tpl.get("category"):
            parts = default_participants(tpl, d["season"])
            missing = [x for gs in parts.values() for ts in gs.values() for x in ts if x not in self.ds.teams]
            if missing:
                # as New tournament does: left out, never replaced
                parts = {s: {g: [x for x in ts if x in self.ds.teams] for g, ts in gs.items()}
                         for s, gs in parts.items()}
                out.append(("groups", f"{len(missing)} team{'s' if len(missing) > 1 else ''} not in the "
                                      "data: left out (⇄ puts another in)", "warn"))
            for msg in formats.problems(self.ds, tpl, d["season"], parts):
                if "usable players" not in msg and "not in the data" not in msg:
                    out.append(("groups", msg, "error"))
        teams = C.all_teams(d)
        if len(teams) != len(set(teams)):
            out.append(("groups", "A team is in twice", "error"))
        return out

    def collect_issues(self):
        if self.is_base():
            try:
                issues = self._base_issues()
            except Exception as e:
                log.exception("checking the competition")
                issues = [("groups", f"Could not check it: {e}", "error")]
            self._refresh_preview(self.d, issues)
            self._sync_list(issues)
            return issues
        try:
            issues = C.problems(self.ds, self.d)
        except Exception as e:
            log.exception("checking the tournament")
            issues = [("format", f"Could not check it: {e}", "error")]
        self._refresh_preview(self.d, issues)
        self._sync_list(issues)
        return issues

    def _sync_list(self, issues):
        sig = (self.record_id, self.d["name"], self.d["format"], sum(1 for i in issues if i[2] == "error"))
        if sig != getattr(self, "_list_sig", None):
            self._list_sig = sig
            self.reload_list()

    def tab_for_issue(self, key):
        return FIELD_TABS.get(key.split(".")[0], TAB_SETUP)

    def header_state(self):
        d = self.d
        if self.is_base():
            tpl = self._base_template()
            return {"title": d["name"] or "—",
                    "eyebrow": "competition · edited" if self.record_id in self._edits else "competition",
                    "subtitle": "", "chips": [], "pixmap": competition_emblem(self.ds, tpl, 64)}
        tpl = C.compile_template(d, self.record_id or "preview")
        draft = self.record_id in self._drafts
        return {"title": d["name"] or "New tournament",
                "eyebrow": "not saved yet" if draft else "tournament",
                "subtitle": "", "chips": [],
                "pixmap": competition_emblem(self.ds, tpl, 64)}

    def _refresh_chrome(self):
        super()._refresh_chrome()
        h = self.shell.header
        has = self.session is not None and not self._starting
        if not has:
            h.title.setText("New tournament" if self._starting else "Tournament editor")
            h.eyebrow.setText("")
            h.set_chips([])
            h.set_dirty(0)
        if has and self.record_id in self._drafts:
            # a draft is unsaved even before the first edit
            self.shell.footer.save_btn.setEnabled(True)
            h.set_dirty(max(1, self.session.change_count()))
        h.avatar.setVisible(has)
        h.issues_btn.setVisible(has)
        base = has and self.is_base()
        self.del_btn.setText("RESET" if base else "DELETE")
        self.del_btn.setEnabled(has and (not base or self.record_id in self._edits))
        self.dup_btn.setEnabled(has and not base)
        self._sync_start()

    def on_show(self):
        self._teams_sig = None
        self.refresh_from_store()
        if self.record_id is None:
            mine = [tid for tid in self.list_ids() if not self.is_base(tid)]
            if mine:
                self.open_record(mine[0])
        self.list.setFocus()
        self._update_hints()
        self._sync_start()
        if self._starting or self.session is None:
            self.start_panel.cards[0].setFocus()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        compact = self.width() < 1150
        self.shell.list_pane.setFixedWidth(230 if compact else 250)
        self.shell.preview_pane.setFixedWidth(250 if compact else 320)
        self.shell.tabs.set_metrics(11 if compact else 13, 8 if compact else 30)

    def pane(self):
        return "list" if self.session is None else super().pane()

    def keyPressEvent(self, event):
        from app.input import KEYMAP, Action
        from PyQt5.QtWidgets import QApplication, QLineEdit
        if (self._starting and self._dialog is None and not PopupList.any_open()
                and not isinstance(QApplication.focusWidget(), QLineEdit)
                and KEYMAP.get(event.key()) == Action.BACK):
            self._set_starting(False)
            event.accept()
            return
        super().keyPressEvent(event)

    def _update_hints(self):
        if self._dialog is None and not PopupList.any_open() and (self._starting or self.session is None):
            self.shell.footer.hints.set_hints([("↕←→", "move"), ("A", "choose")] +
                                              ([("B", "cancel")] if self.session is not None else [("B", "back")]))
            return
        super()._update_hints()

    def tab_hints(self, focused):
        return [("↕←→", "move"), ("A", "change"), ("Y", "remove")]
