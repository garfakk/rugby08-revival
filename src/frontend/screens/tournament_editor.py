"""
screens/tournament_editor.py — Tournament editor (Tools, and the tournament
hub's CREATE YOUR OWN)
==========================================================================
Lets anyone build a competition of their own — a league, pools and a
knockout bracket, or a straight cup — without knowing how a template works.
The screen edits a *design* (app/tournament/custom.py), which is compiled to
a template on save; the wizard then offers it like any other competition.

Layout (EditorScreen): the user's tournaments on the left (+ NEW asks what
to start from), five tabs, and a live preview on the right: the
tournament's shape as a diagram, its numbers, what still stops it being
played, and PLAY IT.

  OVERVIEW        name, description, the squads' season, presentation
  FORMAT          league / groups + knockouts / cup, and how the knockouts go
  TEAMS           the pools (or the draw); add, remove, auto-fill, shuffle
  RULES           table points, ties on points, discipline, default settings
  VENUES & DATES  home grounds or neutral stadiums, the final, the calendar
"""
import copy
from datetime import date

from PyQt5.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen, QPainterPath
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from app import competition_branding
from app import variants as V
from app.challenges import HALF_LENGTHS
from app.season import season_label
from app.tournament import custom as C
from app.tournament import formats
from shared.log import get_logger
from ui.broadcast import tracked_font
from ui.dropdown import PopupList
from ui.editor_kit import (Badge, ChoiceField, FieldGrid, FormDialog, NumberField, Note,
                           SectionCard, SegmentField, TextField, compact_button)
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BG_CARD, BG_HIGHLIGHT, BG_RAISED, BORDER,
                      DANGER_LITE, FG_MUTED, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FONT_DISPLAY,
                      GREEN, T_LABEL, T_SMALL, WARN)

from .editor_base import EditorScreen
from .tournament.common import (ActivatableCard, PixmapLabel, competition_emblem, placeholder_crest,
                                team_crest)

log = get_logger(__name__)

TAB_OVERVIEW, TAB_FORMAT, TAB_TEAMS, TAB_RULES, TAB_VENUES = range(5)
# which tab shows each design key (issues land on it)
FIELD_TABS = {
    "name": TAB_OVERVIEW, "description": TAB_OVERVIEW, "season": TAB_OVERVIEW,
    "variant": TAB_OVERVIEW, "match_type": TAB_OVERVIEW, "branding": TAB_OVERVIEW,
    "trophy_lift": TAB_OVERVIEW,
    "format": TAB_FORMAT, "legs": TAB_FORMAT, "playoff_teams": TAB_FORMAT, "qualify": TAB_FORMAT,
    "best_extra": TAB_FORMAT, "seeding": TAB_FORMAT, "third_place": TAB_FORMAT,
    "knockout_draw": TAB_FORMAT, "group_count": TAB_FORMAT, "teams_from": TAB_FORMAT,
    "category": TAB_FORMAT,
    "groups": TAB_TEAMS,
    "points": TAB_RULES, "tiebreakers": TAB_RULES, "discipline": TAB_RULES, "options": TAB_RULES,
    "venue": TAB_VENUES, "venues": TAB_VENUES, "knockout_venue": TAB_VENUES,
    "final_stadium": TAB_VENUES, "start": TAB_VENUES, "every": TAB_VENUES,
}
MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August",
          "September", "October", "November", "December"]
YES_NO = {True: "yes", False: "no"}
ON_OFF = {True: "on", False: "off"}


def _remove_button(slot, tip="remove"):
    b = compact_button("✕")
    b.setFixedWidth(34)
    b.setToolTip(tip)
    b.setProperty("removesRow", True)       # Y on the row presses it (app.screen_base)
    b.clicked.connect(slot)
    return b


# ═════════════════════════════════════════════════════════════════════════
# Painted pieces
# ═════════════════════════════════════════════════════════════════════════
class FormatCard(ActivatableCard):
    """One format, drawn: a little table, pools feeding a bracket, or a
    bracket; its name and one line on how it plays."""

    def __init__(self, fmt, parent=None):
        super().__init__(parent)
        self.fmt = fmt
        self.setFixedHeight(208)
        self.setMinimumWidth(200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        w = self.width()
        art = QRectF(18, 16, w - 36, 74)
        col = QColor(ACCENT if self.selected else FG_TERTIARY)
        getattr(self, f"_art_{self.fmt}")(p, art, col)
        p.setPen(QColor(FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 14, QFont.Bold, 0.8))
        p.drawText(QRectF(18, 98, w - 36, 24), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(C.FORMAT_LABELS[self.fmt].upper(), Qt.ElideRight, int(w - 36)))
        p.setPen(QColor(FG_TERTIARY))
        p.setFont(tracked_font(FONT_DISPLAY, T_SMALL + 1, QFont.DemiBold, 0.3))
        p.drawText(QRectF(18, 124, w - 36, 78), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                   C.FORMAT_BLURBS[self.fmt])
        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(QRectF(w - 30, 12, 18, 18))
            p.setPen(QColor(BG_BASE))
            p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.Bold, 0))
            p.drawText(QRectF(w - 30, 12, 18, 18), Qt.AlignCenter, "✓")

    @staticmethod
    def _table(p, r, col, rows):
        h = r.height() / rows
        for i in range(rows):
            line = QRectF(r.x(), r.y() + i * h + 2, r.width(), h - 4)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(col) if i == 0 else QColor(BG_RAISED))
            p.drawRoundedRect(line, 2, 2)
            p.setBrush(QColor(BG_BASE if i == 0 else FG_MUTED))
            p.drawRect(QRectF(line.x() + 6, line.center().y() - 1.5, line.width() * 0.45, 3))

    @staticmethod
    def _bracket(p, r, col, first):
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
        y = prev[0]
        p.drawEllipse(QRectF(r.x() + (len(cols) - 1) * cw + cw * 0.55 + 4, y - 6, 12, 12))

    def _art_league(self, p, r, col):
        self._table(p, QRectF(r.x(), r.y(), r.width() * 0.8, r.height()), col, 6)

    def _art_groups(self, p, r, col):
        gw = r.width() * 0.22
        for i in range(2):
            self._table(p, QRectF(r.x(), r.y() + i * (r.height() / 2), gw, r.height() / 2 - 4), col, 3)
            self._table(p, QRectF(r.x() + gw + 6, r.y() + i * (r.height() / 2), gw, r.height() / 2 - 4),
                        col, 3)
        self._bracket(p, QRectF(r.x() + gw * 2 + 22, r.y(), r.width() - gw * 2 - 22, r.height()), col, 4)

    def _art_cup(self, p, r, col):
        self._bracket(p, QRectF(r.x(), r.y(), r.width() * 0.9, r.height()), col, 8)


class StructureDiagram(QWidget):
    """The tournament's stages top to bottom (custom.structure): a table
    stage as a wide card, each knockout round under it, the final in gold."""

    ROW_H = 50
    GAP = 14

    def __init__(self, parent=None):
        super().__init__(parent)
        self.blocks = []
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_blocks(self, blocks):
        self.blocks = list(blocks)
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
            p.drawText(QRectF(0, 0, w, self.ROW_H), Qt.AlignCenter, "Add teams to see the tournament")
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
            games = f"{b['matches']} {'game' if b['matches'] == 1 else 'games'}".upper()
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.Bold, 0.6))
            gw = p.fontMetrics().horizontalAdvance(games) + 6
            p.setPen(QColor(FG_SECONDARY))
            p.drawText(QRectF(w - gw - 12, r.y() + 5, gw, 22), Qt.AlignRight | Qt.AlignVCenter, games)
            p.setPen(QColor(col if final else FG_PRIMARY))
            p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, 1.0))
            p.drawText(QRectF(r.x() + 16, r.y() + 5, w - gw - 40, 22), Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(b["title"].upper(), Qt.ElideRight, int(w - gw - 40)))
            p.setPen(QColor(FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.3))
            fm = p.fontMetrics()
            p.drawText(QRectF(r.x() + 16, r.y() + 26, w - 30, 20), Qt.AlignLeft | Qt.AlignVCenter,
                       fm.elidedText(b["detail"], Qt.ElideRight, int(w - 34)))
            if i < len(self.blocks) - 1:
                # the arrow down to the next stage
                cx = w / 2
                y0, y1 = y + self.ROW_H + 2, y + self.ROW_H + self.GAP - 2
                p.setPen(QPen(QColor(FG_MUTED), 2))
                p.drawLine(int(cx), int(y0), int(cx), int(y1 - 4))
                path = QPainterPath()
                path.moveTo(cx - 5, y1 - 6)
                path.lineTo(cx + 5, y1 - 6)
                path.lineTo(cx, y1)
                path.closeSubpath()
                p.fillPath(path, QColor(FG_MUTED))


class StatTile(QWidget):
    """A big number over a small caption."""

    def __init__(self, caption, parent=None):
        super().__init__(parent)
        self.caption, self.value = caption, "—"
        self.setFixedHeight(58)

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
        p.setFont(tracked_font(FONT_DISPLAY, 20, QFont.Bold, 0.5))
        p.drawText(QRectF(0, 4, r.width(), 30), Qt.AlignCenter, self.value)
        p.setPen(QColor(FG_TERTIARY))
        p.setFont(tracked_font(FONT_DISPLAY, 9, QFont.Bold, 1.4))
        p.drawText(QRectF(0, 34, r.width(), 18), Qt.AlignCenter, self.caption.upper())


# ═════════════════════════════════════════════════════════════════════════
# Rows
# ═════════════════════════════════════════════════════════════════════════
class TeamRow(QWidget):
    """Crest, (seed number,) name, and the row's buttons."""

    def __init__(self, crest, name, seed=None, on_up=None, on_down=None, on_remove=None,
                 warn="", parent=None):
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
        h.addWidget(label, stretch=1)
        for text, slot in (("▲", on_up), ("▼", on_down)):
            if slot is not None:
                b = compact_button(text)
                b.setFixedWidth(34)
                b.clicked.connect(slot)
                h.addWidget(b)
                self.buttons.append(b)
        if on_remove is not None:
            b = _remove_button(on_remove, "take the team out")
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
            rm = _remove_button(lambda _=False, i=i: self._remove(i))
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
        searchable = len(free) > 12
        if searchable:
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
    TAB_TITLES = ["Overview", "Format", "Teams", "Rules", "Venues & dates"]
    RECORD_NOUN = "tournament"
    LIST_PLACEHOLDER = "filter tournaments"
    PREVIEW_PANE = True
    GROUP_LABEL = "Format"
    SORTS = [("name", "name"), ("issues", "most issues")]

    def __init__(self, ds, on_back, on_play=None):
        """`on_play(template_id)`: start a tournament of it (the wizard)."""
        self._designs = {}
        self._drafts = {}            # id -> design never saved (just created)
        self._teams_sig = None
        self._groups_holder_items = []
        self.on_play = on_play
        super().__init__(ds, on_back)
        self._build_list_extras()
        self._build_overview()
        self._build_format()
        self._build_teams()
        self._build_rules()
        self._build_venues()
        self._build_preview()
        self.shell.footer.target.setText("")

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
        self.new_btn.setText("+ NEW")
        self.dup_btn.setText("COPY")
        self.del_btn = compact_button("DELETE")
        self.del_btn.clicked.connect(self.delete_record)
        bar = self.shell.list_layout.itemAt(0).layout()
        bar.addWidget(self.del_btn)
        self.focus.register(self.del_btn)
        self.empty_note = Note("No tournament yet. + NEW TOURNAMENT starts one: from scratch or "
                               "from a ready-made shape (a World Cup, a club league...).",
                               color=FG_TERTIARY)
        self.shell.list_layout.insertWidget(1, self.empty_note)

    def list_rows(self):
        self._designs = C.load_all()
        self._designs.update(self._drafts)
        rows = []
        for tid, d in self._designs.items():
            errors = 0
            try:
                found = C.problems(self.ds, d)
                errors = sum(1 for p in found if p[2] == "error")
            except Exception:
                log.exception("checking %s", tid)
            teams = len(C.all_teams(d))
            rows.append({"id": tid, "text": d["name"] or "(no name)",
                         "tag": "DRAFT" if tid in self._drafts else
                         (f"{errors} TO FIX" if errors else f"{teams} TEAMS"),
                         "color": WARN if errors or tid in self._drafts else FG_TERTIARY,
                         "search": d["name"] + " " + C.FORMAT_LABELS[d["format"]],
                         "group": C.FORMAT_LABELS[d["format"]], "errors": errors, "issues": errors})
        if hasattr(self, "empty_note"):
            self.empty_note.setVisible(not rows)
            self.del_btn.setEnabled(self.record_id is not None)
        return rows

    def load_record(self, record_id):
        if record_id in self._drafts:
            return copy.deepcopy(self._drafts[record_id])
        designs = C.load_all()
        d = designs.get(record_id)
        return dict(d, id=record_id) if d else None

    def write_record(self):
        tid = C.save(self.session.working, self.record_id)
        self._drafts.pop(tid, None)
        return f"Saved — {self.session.working['name']} is in New tournament"

    def after_save(self):
        self.del_btn.setEnabled(True)

    # ── new / copy / delete ──────────────────────────────────────────────
    def new_record(self):
        self.guard_dirty(self._ask_starter)

    def _ask_starter(self):
        popup = PopupList(self.window(), width=460, height=460, own_keys=True)
        popup.set_title("start from")
        for key, title, subtitle in C.STARTERS:
            popup.add_row(title, key, subtitle=subtitle)
        popup.size_to(len(C.STARTERS))
        popup.picked.connect(lambda key: self._create(key) if key else None)
        popup.closed.connect(self.new_btn.setFocus)
        popup.open_at(self.new_btn, self.window())

    def _default_season(self):
        seasons = sorted({s for ss in self.ds.teams.values() for s in ss}, reverse=True)
        count = {s: sum(1 for ts in self.ds.teams.values() if s in ts) for s in seasons}
        return max(seasons, key=lambda s: (count[s], s)) if seasons else ""

    def _create(self, key):
        design = C.starter(self.ds, key, self._default_season())
        if not design["name"]:
            design["name"] = "My tournament"
        taken = set(C.load_all()) | set(self._drafts)
        tid = C.unique_id(design["name"], taken)
        design["id"] = tid
        self._drafts[tid] = design
        self.reload_list()
        self.open_record(tid)
        self._starter_key = key
        self.shell.tabs.set_index(TAB_TEAMS if key != "blank" else TAB_FORMAT)
        self.shell.footer.set_status("New tournament — choose its teams, then SAVE", FG_SECONDARY)
        self.refresh_all()
        self._refresh_chrome_dirty_draft()

    def _refresh_chrome_dirty_draft(self):
        if self.record_id in self._drafts:
            self.shell.footer.save_btn.setEnabled(True)
            self.shell.header.set_dirty(max(1, self.session.change_count()))

    def duplicate_record(self):
        if self.session is None:
            return
        src = copy.deepcopy(self.session.working)

        def go():
            src["name"] = (src["name"] or "Tournament") + " (copy)"
            tid = C.unique_id(src["name"], set(C.load_all()) | set(self._drafts))
            src["id"] = tid
            self._drafts[tid] = src
            self.reload_list()
            self.open_record(tid)
            self._refresh_chrome_dirty_draft()
        self.guard_dirty(go)

    def delete_record(self):
        if self.record_id is None:
            return
        name = self.d["name"] or "this tournament"

        def go():
            tid = self.record_id
            self._drafts.pop(tid, None)
            C.delete(tid)
            self.record_id = None
            self.session = None
            self._teams_sig = None
            self.reload_list()
            first = None
            if self.list.count():
                self.list.set_highlight(0)
                first = self.list.highlighted_data()
            if first is not None:
                self.open_record(first)
            else:
                self.refresh_all()
            self.shell.footer.set_status(f"Deleted {name}", FG_SECONDARY)
        self.confirm("Delete this tournament?",
                     f"{name} will be removed. Tournaments already started with it are kept.",
                     "DELETE", go)

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

    # ── OVERVIEW ─────────────────────────────────────────────────────────
    def _build_overview(self):
        page = self._page(TAB_OVERVIEW)
        card = SectionCard("Tournament")
        grid = FieldGrid(columns=1)
        self.f_name = self._field("name", TextField("name", max_bytes=60), TAB_OVERVIEW, grid)
        self.f_name.edited.connect(lambda v: self._set("name", v.strip(), "name"))
        self.f_desc = self._field("description", TextField("description", max_bytes=200,
                                  placeholder="written for you from the format"), TAB_OVERVIEW, grid)
        self.f_desc.edited.connect(lambda v: self._set("description", v.strip(), "description"))
        card.add(grid)
        page.addWidget(card)

        card = SectionCard("Squads")
        grid = FieldGrid(columns=1)
        self.f_season = self._field("season", ChoiceField("season", allow_blank=False,
                                    display=self._season_text), TAB_OVERVIEW, grid)
        self.f_season.popup_title = "the squads of"
        self.f_season.edited.connect(lambda v: self._set("season", v, "season"))
        self.f_variant = self._field("variant", ChoiceField(
            "competition squads", allow_blank=True, blank_label="none: the teams' usual squads",
            display=lambda v: v.replace("_", " ").title()), TAB_OVERVIEW, grid)
        self.f_variant.searchable = True
        self.f_variant.edited.connect(lambda v: self._set("variant", v or "", "competition squads"))
        card.add(grid)
        card.add(Note("Every team plays with its squad of that season (its nearest one when it "
                      "has none). Competition squads: a team that has a squad or kit made for "
                      "that competition (a World Cup squad...) uses it.", color=FG_TERTIARY))
        page.addWidget(card)

        card = SectionCard("In the game")
        grid = FieldGrid(columns=1)
        self.f_match_type = self._field("match_type", ChoiceField(
            "presentation", list(C.MATCH_TYPES), allow_blank=False,
            display=lambda v: C.MATCH_TYPES.get(v, v)), TAB_OVERVIEW, grid)
        self.f_match_type.edited.connect(lambda v: self._set("match_type", v, "presentation"))
        self.f_branding = self._field("branding", ChoiceField(
            "competition look", allow_blank=True, blank_label="none: the home team's",
            display=lambda c: competition_branding.label(self.ds, c)), TAB_OVERVIEW, grid)
        self.f_branding.searchable = True
        self.f_branding.edited.connect(lambda v: self._set("branding", v or "", "competition look"))
        self.f_trophy = self._field("trophy_lift", SegmentField(
            "trophy lift", [True, False], display=lambda v: YES_NO[v]), TAB_OVERVIEW, grid)
        self.f_trophy.edited.connect(lambda v: self._set("trophy_lift", bool(v), "trophy lift"))
        card.add(grid)
        card.add(Note("Presentation: the game's own menus and commentary for that competition. "
                      "Competition look: its ball, logos, pitch logo and stadium boards.",
                      color=FG_TERTIARY))
        page.addWidget(card)
        page.addStretch(1)

    # ── FORMAT ───────────────────────────────────────────────────────────
    def _build_format(self):
        page = self._page(TAB_FORMAT)
        row = QHBoxLayout()
        row.setSpacing(12)
        self.format_cards = {}
        for fmt in C.FORMATS:
            card = FormatCard(fmt)
            card.activated.connect(lambda fmt=fmt: self._pick_format(fmt))
            row.addWidget(card)
            if fmt == "league":
                self.register_field("format", card, TAB_FORMAT)     # registers it for focus too
            else:
                self.focus.register(card)
            self.format_cards[fmt] = card
        page.addLayout(row)

        # the table stage
        self.table_card = SectionCard("League")
        grid = FieldGrid(columns=2)
        self.f_legs = self._field("legs", SegmentField(
            "games", [1, 2], display=lambda v: {1: "once", 2: "home & away"}[v]), TAB_FORMAT, grid)
        self.f_legs.edited.connect(lambda v: self._set("legs", int(v), "games"))
        self.f_groups_n = self._field("group_count", NumberField("pools", lo=2, hi=16, allow_blank=False),
                                      TAB_FORMAT, grid)
        self.f_groups_n.edited.connect(self._on_group_count)
        self.table_card.add(grid)
        grid = self.league_grid = FieldGrid(columns=2)
        self.f_teams_from = self._field("teams_from", SegmentField(
            "teams", ["pick", "category"],
            display=lambda v: {"pick": "I choose them", "category": "a whole category"}[v]),
            TAB_FORMAT, grid)
        self.f_teams_from.edited.connect(lambda v: self._set("teams_from", v, "teams"))
        self.f_category = self._field("category", ChoiceField("category", allow_blank=True,
                                      blank_label="— choose —"), TAB_FORMAT, grid)
        self.f_category.edited.connect(lambda v: self._set("category", v or "", "category"))
        self.table_card.add(grid)
        self.table_note = Note("", color=FG_TERTIARY)
        self.table_card.add(self.table_note)
        page.addWidget(self.table_card)

        # the knockouts
        self.ko_card = SectionCard("Knockouts")
        grid = self.playoff_grid = FieldGrid(columns=1)
        self.f_playoffs = self._field("playoff_teams", SegmentField(
            "play-offs", C.LEAGUE_PLAYOFFS,
            display=lambda v: {0: "none", 2: "final", 4: "top 4", 6: "top 6", 8: "top 8"}[v]),
            TAB_FORMAT, grid)
        self.f_playoffs.edited.connect(lambda v: self._set("playoff_teams", int(v), "play-offs"))
        self.ko_card.add(grid)
        grid = self.qualify_grid = FieldGrid(columns=2)
        self.f_qualify = self._field("qualify", NumberField("through per pool", lo=1, hi=8,
                                     allow_blank=False), TAB_FORMAT, grid)
        self.f_qualify.edited.connect(lambda v: v and self._set("qualify", int(v), "going through"))
        self.f_extra = self._field("best_extra", NumberField("+ best of rest", lo=0, hi=15,
                                   allow_blank=False), TAB_FORMAT, grid)
        self.f_extra.edited.connect(lambda v: self._set("best_extra", int(v or 0), "best of the rest"))
        self.ko_card.add(grid)
        grid = FieldGrid(columns=2)
        self.f_seeding = self._field("seeding", ChoiceField(
            "pairing", list(C.SEEDINGS), allow_blank=False, display=lambda v: C.SEEDINGS[v]),
            TAB_FORMAT, grid)
        self.f_seeding.edited.connect(lambda v: self._set("seeding", v, "pairing"))
        self.f_ko_draw = self._field("knockout_draw", ChoiceField(
            "a drawn game", list(C.KNOCKOUT_DRAWS), allow_blank=False,
            display=lambda v: C.KNOCKOUT_DRAWS[v]), TAB_FORMAT, grid)
        self.f_third = self._field("third_place", SegmentField(
            "bronze final", [True, False], display=lambda v: YES_NO[v]), TAB_FORMAT, grid)
        self.f_third.edited.connect(lambda v: self._set("third_place", bool(v), "bronze final"))
        self.f_ko_draw.edited.connect(lambda v: self._set("knockout_draw", v, "drawn knockout games"))
        self.ko_card.add(grid)
        self.ko_note = Note("", color=FG_TERTIARY)
        self.ko_card.add(self.ko_note)
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
        self.shuffle_btn = compact_button("SHUFFLE THE DRAW")
        self.shuffle_btn.clicked.connect(self._shuffle)
        self.clear_btn = compact_button("CLEAR ALL")
        self.clear_btn.clicked.connect(self._clear_teams)
        for b in (self.fill_btn, self.shuffle_btn, self.clear_btn):
            bar.addWidget(b)
            self.focus.register(b)
        bar.addStretch(1)
        self.teams_count = Note("", color=FG_SECONDARY, size=T_LABEL + 1)
        bar.addWidget(self.teams_count)
        page.addLayout(bar)
        self.teams_note = Note("", color=FG_TERTIARY)
        page.addWidget(self.teams_note)
        holder = QWidget()
        holder.setObjectName("groupsHolder")
        holder.setStyleSheet("QWidget#groupsHolder { background: transparent; }")
        self.groups_grid = QGridLayout(holder)
        self.groups_grid.setContentsMargins(0, 0, 0, 0)
        self.groups_grid.setHorizontalSpacing(12)
        self.groups_grid.setVerticalSpacing(12)
        self.register_field("groups", holder, TAB_TEAMS)
        self.focus.unregister(holder)
        page.addWidget(holder)
        page.addStretch(1)

    def _team_name(self, tid):
        from app.tournament.engine import pick_season
        seasons = self.ds.teams.get(tid) or {}
        if not seasons:
            return f"missing team {tid}"
        return seasons[pick_season(seasons, self.d["season"] or "0")].get("name", tid)

    def _crest(self, tid, size=28):
        from app.tournament.engine import pick_season
        seasons = self.ds.teams.get(tid)
        if not seasons:
            return placeholder_crest(size)
        return team_crest(self.ds, tid, pick_season(seasons, self.d["season"] or "0"), size)

    def _rebuild_groups(self):
        d = self.d
        sig = (d["format"], d["season"], d["teams_from"],
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
        cols = 2 if fmt == "groups" else 1
        for i, g in enumerate(d["groups"]):
            card = SectionCard(C.group_name(d, i), right=Badge(f"{len(g['teams'])} teams", FG_TERTIARY))
            if fmt == "groups":
                name = TextField("pool name", max_bytes=30, placeholder=f"Pool {C.group_id(i)}")
                name.set_value(g["name"])
                name.edited.connect(lambda v, i=i: self._rename_group(i, v))
                card.add(name)
                self.focus.register(name)
            for j, tid in enumerate(g["teams"]):
                cup = fmt == "cup"
                row = TeamRow(self._crest(tid), self._team_name(tid),
                              seed=j + 1 if cup else None,
                              on_up=(lambda _=False, i=i, j=j: self._move_team(i, j, -1)) if cup and j else None,
                              on_down=(lambda _=False, i=i, j=j: self._move_team(i, j, 1))
                              if cup and j < len(g["teams"]) - 1 else None,
                              on_remove=lambda _=False, i=i, j=j: self._remove_team(i, j),
                              warn="no full squad" if tid in short else "")
                for b in row.buttons:
                    self.focus.register(b)
                card.add(row)
            add = compact_button("+ ADD TEAM")
            add.clicked.connect(lambda _=False, i=i, b=add: self._ask_team(i, b))
            card.add(add)
            self.focus.register(add)
            self.groups_grid.addWidget(card, i // cols, i % cols)
            self._groups_holder_items.append(card)

    def _short_squads(self):
        from app.tournament.engine import pick_season, usable_squad
        out = set()
        for tid in C.all_teams(self.d):
            seasons = self.ds.teams.get(tid)
            if seasons and len(usable_squad(self.ds, tid, pick_season(seasons, self.d["season"] or "0"))) < 22:
                out.add(tid)
        return out

    def _ask_team(self, group_index, anchor):
        taken = set(C.all_teams(self.d))
        playable = set(C.teams_from_source(self.ds, "all", self.d["season"]))
        teams = sorted((t for t in self.ds.teams if t not in taken),
                       key=lambda t: (t not in playable, self._team_name(t).lower()))
        popup = PopupList(self.window(), width=440, height=480, own_keys=True)
        popup.set_title("add a team")
        box = popup.add_search_box("Type a team or a category…")

        def kind(t):
            from app.tournament.engine import pick_season
            seasons = self.ds.teams.get(t) or {}
            info = seasons.get(pick_season(seasons, self.d["season"] or "0")) or {}
            return str(info.get("category") or info.get("type") or "")

        def fill(text):
            popup.clear_rows()
            q = text.casefold().strip()
            for t in teams:
                name, cat = self._team_name(t), kind(t)
                if q and q not in name.casefold() and q not in cat.casefold():
                    continue
                popup.add_row(name, t, icon=self._crest(t, 24), subtitle=cat,
                              tag="" if t in playable else "NO SQUAD",
                              tag_color=WARN, subdued=t not in playable)
            popup._sync_rows()
            popup.set_highlight(0)
        box.textChanged.connect(fill)
        fill("")
        popup.size_to(10)
        popup.picked.connect(lambda t: self._add_team(group_index, t) if t else None)
        popup.closed.connect(anchor.setFocus)
        popup.open_at(anchor, self.window())

    def _add_team(self, i, tid):
        def mutate(w):
            if tid not in [t for g in w["groups"] for t in g["teams"]]:
                w["groups"][i]["teams"].append(tid)
        self.edit(f"add {self._team_name(tid)}", mutate)

    def _remove_team(self, i, j):
        name = self._team_name(self.d["groups"][i]["teams"][j])
        self.edit(f"remove {name}", lambda w: w["groups"][i]["teams"].pop(j))

    def _move_team(self, i, j, delta):
        def mutate(w):
            ts = w["groups"][i]["teams"]
            ts[j], ts[j + delta] = ts[j + delta], ts[j]
        self.edit("draw order", mutate)

    def _rename_group(self, i, v):
        def mutate(w):
            w["groups"][i]["name"] = v.strip()
        self.edit("pool name", mutate, coalesce_key=f"group_name_{i}")

    def _shuffle(self):
        self._replace("shuffle the draw", C.shuffle_draw(self.d))

    def _clear_teams(self):
        if not C.all_teams(self.d):
            return

        def go():
            def mutate(w):
                for g in w["groups"]:
                    g["teams"] = []
            self.edit("clear the teams", mutate)
        self.confirm("Take every team out?", "The pools stay, empty. UNDO (Ctrl+Z) brings them back.",
                     "CLEAR ALL", go)

    def _ask_fill(self):
        if self.session is None:
            return
        d = self.d
        cats = C.categories(self.ds)
        sources = list(C.TEAM_SOURCES) + [f"cat:{c}" for c in cats if c.lower() != "international"]
        source = ChoiceField("teams from", sources, allow_blank=False,
                             display=lambda s: C.TEAM_SOURCES.get(s) or s[4:])
        default_source, default_size = C.starter_fill_target(getattr(self, "_starter_key", ""))
        sizes = [len(g["teams"]) for g in d["groups"]]
        if d["format"] == "groups":
            label, size = "teams per pool", max(sizes + [default_size if d["format"] == "groups" else 4])
        elif d["format"] == "cup":
            label, size = "teams in the cup", max(len(C.all_teams(d)), 8)
        else:
            label, size = "teams in the league", max(len(C.all_teams(d)), default_size)
        count = NumberField(label, lo=2, hi=64, allow_blank=False)
        count.set_value(size)
        source.set_value(default_source)

        def done(role):
            self._dialog = None
            if role != "ok":
                return
            n = count.as_int() or size
            filled = C.auto_fill(self.ds, self.d, source.value(), n)
            added = len(C.all_teams(filled)) - len(C.all_teams(self.d))
            self._replace("auto-fill", filled)
            self.shell.footer.set_status(
                f"Added {added} team{'s' if added != 1 else ''}" if added else
                "No team left to add from there", GREEN if added else WARN)
        self.show_dialog(FormDialog(
            self, "Auto-fill",
            "Tops every pool up with teams picked at random (only teams with a full squad for "
            "the season). The teams already in stay.",
            {"source": source, "count": count},
            [("CANCEL", "neutral", "cancel"), ("FILL", "primary", "ok")], done))

    # ── RULES ────────────────────────────────────────────────────────────
    def _build_rules(self):
        page = self._page(TAB_RULES)
        card = SectionCard("Table points")
        top = FieldGrid(columns=1)
        presets = list(C.POINTS_PRESETS) + ["custom"]
        self.f_points = self._field("points", ChoiceField(
            "points system", presets, allow_blank=False,
            display=lambda k: C.POINTS_PRESETS[k]["label"] if k in C.POINTS_PRESETS else "Custom"),
            TAB_RULES, top)
        self.f_points.edited.connect(self._on_points_preset)
        card.add(top)
        grid = FieldGrid(columns=2)
        self.f_pts = {}
        for key, label, hi in (("win", "win", 10), ("draw", "draw", 10), ("loss", "loss", 10),
                               ("losing_bonus", "losing bonus ≤", 20),
                               ("grand_slam", "slam bonus", 10)):
            f = NumberField(label, lo=0, hi=hi, allow_blank=False)
            f.edited.connect(lambda v, k=key: self._set_point(k, int(v or 0)))
            grid.add(f)
            self.register_field(f"points.{key}", f, TAB_RULES)
            self.f_pts[key] = f
        self.f_try_bonus = ChoiceField("try bonus", list(C.TRY_BONUS), allow_blank=False,
                                       display=lambda v: C.TRY_BONUS[v])
        self.f_try_bonus.edited.connect(lambda v: self._set_point("try_bonus", v))
        grid.add(self.f_try_bonus)
        self.register_field("points.try_bonus", self.f_try_bonus, TAB_RULES)
        card.add(grid)
        self.points_example = Note("", color=FG_SECONDARY)
        card.add(self.points_example)
        page.addWidget(card)

        card = SectionCard("Level on points")
        card.add(Note("Teams level on points are split by these, in this order:", color=FG_TERTIARY))
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
            display=lambda k: C.DISCIPLINE_PRESETS[k]["label"]), TAB_RULES, grid)
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
        card.add(Note("What New tournament starts with; they can be changed there.", color=FG_TERTIARY))
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
        parts = [f"a win with {'4 tries' if p['try_bonus'] == '4tries' else '3 more tries'}: {win}"
                 if tb else f"a win: {p['win']}",
                 f"a draw: {p['draw']}"]
        if p["losing_bonus"]:
            parts.append(f"a loss by {p['losing_bonus']} or less: {p['loss'] + 1}")
        parts.append(f"a heavy loss: {p['loss']}")
        if p["grand_slam"]:
            parts.append(f"winning every game: +{p['grand_slam']}")
        return "Points: " + " · ".join(parts)

    # ── VENUES & DATES ───────────────────────────────────────────────────
    def _stadium_name(self, sid):
        info = self.ds.stadiums.get(str(sid)) or {}
        name = info.get("name") or f"stadium {sid}"
        country = info.get("country")
        return f"{name} ({str(country).title()})" if country else name

    def _build_venues(self):
        page = self._page(TAB_VENUES)
        card = SectionCard("Where")
        grid = FieldGrid(columns=1)
        self.f_venue = self._field("venue", SegmentField(
            "table games", ["home", "neutral"],
            display=lambda v: {"home": "home team's ground", "neutral": "neutral stadiums"}[v]),
            TAB_VENUES, grid)
        self.f_venue.edited.connect(lambda v: self._set("venue", v, "venue"))
        self.f_ko_venue = self._field("knockout_venue", SegmentField(
            "knockout games", ["home", "neutral"],
            display=lambda v: {"home": "better seed hosts", "neutral": "neutral stadiums"}[v]),
            TAB_VENUES, grid)
        self.f_ko_venue.edited.connect(lambda v: self._set("knockout_venue", v, "knockout venue"))
        stadiums = sorted(self.ds.stadiums, key=lambda s: self._stadium_name(s).lower())
        self.f_final = self._field("final_stadium", ChoiceField(
            "the final", stadiums, allow_blank=True, blank_label="like the other knockout games",
            display=self._stadium_name), TAB_VENUES, grid)
        self.f_final.searchable = True
        self.f_final.edited.connect(lambda v: self._set("final_stadium", v or "", "final venue"))
        card.add(grid)
        card.add(Note("Neutral stadiums are used in turn, in the order below; none chosen = every "
                      "stadium in turn.", color=FG_TERTIARY))
        self.venue_list = OrderedList("+ ADD A STADIUM", self._stadium_name, "add a stadium",
                                      self.focus)
        self.venue_list.changed.connect(lambda vals: self._set("venues", vals, "stadiums", coalesce=False))
        card.add(self.venue_list)
        self.register_field("venues", self.venue_list.add_btn, TAB_VENUES)
        page.addWidget(card)

        card = SectionCard("When")
        grid = FieldGrid(columns=3)
        self.f_month = ChoiceField("starts in", list(range(1, 13)), allow_blank=False,
                                   display=lambda m: MONTHS[int(m) - 1])
        self.f_month.edited.connect(lambda m: self._set_start(month=int(m)))
        self.f_day = NumberField("on the", lo=1, hi=31, allow_blank=False)
        self.f_day.edited.connect(lambda v: v and self._set_start(day=int(v)))
        self.f_every = self._field("every", NumberField("days apart", lo=1, hi=60,
                                   allow_blank=False), TAB_VENUES)
        self.f_every.edited.connect(lambda v: v and self._set("every", int(v), "days between rounds"))
        for f in (self.f_month, self.f_day, self.f_every):
            grid.add(f)
        self.register_field("start", self.f_month, TAB_VENUES)
        self.register_field("start.day", self.f_day, TAB_VENUES)
        card.add(grid)
        self.dates_note = Note("", color=FG_SECONDARY)
        card.add(self.dates_note)
        card.add(Note("Weekly rounds land on Saturdays. The season sets the year: a 2024 season "
                      "runs from July 2023 to June 2024, which decides the weather.", color=FG_TERTIARY))
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
        from datetime import timedelta
        end = start + timedelta(days=(days - 1) * d["every"] + (7 if any(
            b["kind"] != "table" for b in C.structure(d)) else 0))
        return (f"{days} rounds of games, from {start.strftime('%d %B %Y').lstrip('0')} "
                f"to about {end.strftime('%B %Y')}.")

    # ── preview pane ─────────────────────────────────────────────────────
    def _build_preview(self):
        lay = self.shell.preview_layout
        lay.setSpacing(12)
        head = QHBoxLayout()
        head.setSpacing(12)
        self.pv_emblem = PixmapLabel(64, placeholder_crest(64))
        head.addWidget(self.pv_emblem)
        col = QVBoxLayout()
        col.setSpacing(2)
        self.pv_name = Note("", color=FG_PRIMARY, size=15)
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
        from PyQt5.QtWidgets import QScrollArea
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
        self.play_btn = compact_button("PLAY IT  ›", "primary")
        self.play_btn.setMinimumHeight(44)
        self.play_btn.clicked.connect(self._play)
        lay.addWidget(self.play_btn)
        self.focus.register(self.play_btn)
        self.play_hint = Note("", color=FG_TERTIARY)
        lay.addWidget(self.play_hint)

    def _refresh_preview(self, d, issues):
        tpl = C.compile_template(d, self.record_id or "preview")
        self.pv_emblem.set_pixmap(competition_emblem(self.ds, tpl, 64))
        self.pv_name.setText(d["name"] or "No name yet")
        if d["teams_from"] == "category":
            sub = f"every {d['category'] or '…'} club, each season"
        else:
            sub = self._season_text(d["season"])
        self.pv_sub.setText(f"{C.FORMAT_LABELS[d['format']]} · {sub}")
        cat = d["teams_from"] == "category"
        self.pv_teams.set_value("—" if cat else len(C.all_teams(d)))
        self.pv_games.set_value("—" if cat else C.match_count(d))
        self.pv_rounds.set_value("—" if cat else C.matchdays(d))
        self.pv_diagram.set_blocks([] if not C.all_teams(d) and not cat else C.structure(d))
        errors = [m for _k, m, s in issues if s == "error"]
        warns = [m for _k, m, s in issues if s == "warn"]
        if errors:
            self.pv_status.setText(f"✕  {errors[0]}" + (f"  (+{len(errors) - 1} more)" if len(errors) > 1 else ""))
            self.pv_status.setStyleSheet(f"color: {DANGER_LITE}; background: transparent;")
        elif warns:
            self.pv_status.setText(f"!  Playable · {warns[0]}")
            self.pv_status.setStyleSheet(f"color: {WARN}; background: transparent;")
        else:
            self.pv_status.setText("✓  Ready to play")
            self.pv_status.setStyleSheet(f"color: {GREEN}; background: transparent;")
        self.play_btn.setEnabled(not errors and self.on_play is not None)
        dirty = self.session is not None and (self.session.is_dirty() or self.record_id in self._drafts)
        self.play_hint.setText("Saves it first, then opens New tournament on it." if dirty and not errors
                               else ("Fix what is listed above to play it." if errors else
                                     "Opens New tournament on it: pick your team and kick off."))

    def _play(self):
        if self.session is None or self.on_play is None:
            return
        if (self.session.is_dirty() or self.record_id in self._drafts) and not self.save():
            return
        self.on_play(self.record_id)

    # ── refresh ──────────────────────────────────────────────────────────
    def on_record_opened(self):
        self._teams_sig = None

    def refresh_view(self):
        d = self.d
        fmt = d["format"]
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
        self.f_season.setEnabled(not cat_mode)

        # format
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
        if fmt == "league":
            self.table_note.setText("Every club of the category that season plays: one edition per "
                                    "season of the data, like the club leagues." if cat_mode else
                                    "Everyone plays everyone; the table decides, or the play-offs do.")
        else:
            sizes = [len(g["teams"]) for g in d["groups"]]
            self.table_note.setText(f"Pools of {', '.join(map(str, sizes))} teams — set the teams in "
                                    f"TEAMS." if any(sizes) else "Put the teams in the pools in TEAMS.")
        self.playoff_grid.setVisible(fmt == "league")
        self.f_playoffs.set_value(d["playoff_teams"])
        self.qualify_grid.setVisible(fmt == "groups")
        self.f_qualify.set_value(d["qualify"])
        self.f_extra.set_value(d["best_extra"])
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
        q = C.qualifiers(d)
        if fmt == "groups":
            self.ko_note.setText(f"{q} teams reach the knockouts. "
                                 + ("Pool winners meet another pool's runner-up." if d["seeding"] == "cross"
                                    else "Seeds by record: the best meets the worst."))
        elif fmt == "cup":
            self.ko_note.setText("The draw is set in TEAMS: seed 1 at the top. "
                                 + ("Pairs play as listed (1 v 2, 3 v 4...)." if d["seeding"] == "listed"
                                    else "Seeded: 1 v the last seed, 2 and 1 only in the final."))
        else:
            self.ko_note.setText({0: "The top of the table wins it.",
                                  2: "First v second in a final.",
                                  4: "Semi-finals 1 v 4 and 2 v 3, then the final.",
                                  6: "3 v 6 and 4 v 5 first; 1 and 2 wait in the semi-finals.",
                                  8: "Quarter-finals 1 v 8, 2 v 7, 3 v 6, 4 v 5."}[d["playoff_teams"]])

        # teams
        self._rebuild_groups()
        n = len(C.all_teams(d))
        self.teams_count.setText("" if cat_mode else f"{n} team{'s' if n != 1 else ''}")
        for b in (self.fill_btn, self.shuffle_btn, self.clear_btn):
            b.setVisible(not cat_mode)
        self.shuffle_btn.setEnabled(n > 1)
        self.teams_note.setText(
            f"Every club of the category {d['category'] or '(choose it in FORMAT)'} plays, "
            "season by season: nothing to pick here." if cat_mode else
            {"cup": "The order is the draw. Seed 1 at the top: ▲ ▼ move a team.",
             "groups": "Add teams to each pool, or AUTO-FILL them; SHUFFLE THE DRAW deals them again.",
             "league": "Add the teams, or AUTO-FILL them."}[fmt])

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

        # venues & dates
        self.f_venue.set_value(d["venue"])
        self.f_ko_venue.set_value(d["knockout_venue"])
        self.f_ko_venue.setVisible(has_ko)
        self.f_final.set_value(d["final_stadium"])
        self.f_final.setVisible(has_ko)
        self.venue_list.set_values(d["venues"], sorted(self.ds.stadiums,
                                                       key=lambda s: self._stadium_name(s).lower()))
        m, dd = (int(x) for x in d["start"].split("-"))
        self.f_month.set_value(m)
        self.f_day.set_value(dd)
        self.f_every.set_value(d["every"])
        self.dates_note.setText(self._dates_text(d))

    def collect_issues(self):
        try:
            issues = C.problems(self.ds, self.d)
        except Exception as e:
            log.exception("checking the tournament")
            issues = [("format", f"Could not check it: {e}", "error")]
        self._refresh_preview(self.d, issues)
        return issues

    def tab_for_issue(self, key):
        return FIELD_TABS.get(key.split(".")[0], TAB_OVERVIEW)

    def header_state(self):
        d = self.d
        tpl = C.compile_template(d, self.record_id or "preview")
        draft = self.record_id in self._drafts
        return {"title": d["name"] or "New tournament",
                "eyebrow": "my tournament · not saved yet" if draft else "my tournament",
                "subtitle": "", "chips": [],
                "pixmap": competition_emblem(self.ds, tpl, 64)}

    def _refresh_chrome(self):
        super()._refresh_chrome()
        if self.session is not None:
            self._refresh_chrome_dirty_draft()
        self.del_btn.setEnabled(self.record_id is not None)

    def on_show(self):
        self._teams_sig = None
        super().on_show()

    def tab_hints(self, focused):
        return [("↕←→", "move"), ("A", "change"), ("Y", "remove")]
