"""
screens/tournament/squad.py — A human team's default lineup for the
tournament: the 22 every match starts from (a match's own changes are made
in match setup's squad editor and last for that match only).

Built from the same pieces as match setup's squad editor and the team
editor's squad tab (ui/team_sheet.py): the starting XV laid out as a team
sheet with the replacements underneath, a player picker opened on a shirt,
a side panel describing the player under the cursor, and slide-over panels
for roles / set plays and for lineups.

  Team sheet   every shirt shows its player's rating in that slot (injuries
               and fatigue included); orange = out of position, red =
               unavailable (covered automatically before the next match).
  Squad        the whole squad with its tournament numbers.
  Lineups      before each match: play your lineup, or auto pick the best 22;
               lineups saved under a name; the lineup of any match played.

Shirts: arrows / mouse move between them, A opens the picker, drag one onto
another to swap them. In the squad list A takes a player to the team sheet
(his shirt, or the picker on the shirt that suits him). X auto picks the
best 22 now (your lineup only), Y opens Lineups, START roles & plays.
Every change is saved at once.
"""
import re

from PyQt5.QtCore import QPoint, QRect, Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import (QApplication, QGridLayout, QHBoxLayout, QStackedWidget, QVBoxLayout,
                             QWidget)

from app.game_data import SET_PLAYS
from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.tournament import lineups, report, selection
from app.tournament.effects import MatchContext, base_ratings, effective_stats, is_available
from app.tournament.strength import POSITION_WEIGHTS, SLOT_POSITIONS, group_of, position_fit, slot_rating
from ui import StyledButton
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, label_css, page_header
from ui.editor_kit import (ChoiceField, ConfirmDialog, FieldGrid, FormDialog, Note, TabStrip, TextField,
                           compact_button)
from ui.side_panel import SidePanelSlide
from ui.team_sheet import MATCH_SHEET_ROWS, POSITION_NAMES, FITS, PlayerPickerPopup, SlotAvatar, StatsPanel, SubChip
from ui.theme import (ACCENT, BG_BASE, BG_PANEL, BG_RAISED, BORDER, BTN_HEIGHT, DANGER_LITE, FG_PRIMARY,
                      FG_SECONDARY, FG_TERTIARY, GREEN, T_LABEL, WARN)

from .common import DataTable, PixmapLabel, Section, YOU_TINT, clear_layout, tournament_crest, transparent

POSITION_ABBR = {
    "loosehead_prop": "LP", "hooker": "HK", "tighthead_prop": "TP", "second_row": "LK",
    "blindside_flanker": "BF", "openside_flanker": "OF", "number_eight": "N8",
    "scrum_half": "SH", "fly_half": "FH", "centre": "CE", "winger": "WG", "fullback": "FB",
}

ROLE_LABELS = {
    "captain": "Captain", "viceCaptain": "Vice-captain",
    "longGK": "Long goal kick", "shortGK": "Short goal kick",
    "longPunt": "Long punt", "shortPunt": "Short punt", "kickoff": "Kick-off",
}
# the rating a role's dropdown is ranked by (none: in shirt order)
ROLE_RATING = {
    "longGK": "goal_kicking", "shortGK": "goal_kicking",
    "longPunt": "kicking_power", "shortPunt": "kicking", "kickoff": "kicking_power",
}
SET_PLAY_DIRECTIONS = (("up", "▲ Up"), ("left", "◀ Left"), ("right", "▶ Right"), ("down", "▼ Down"))

STAT_LABELS = {
    "scrummaging": "SCRUMMAGING", "strength": "STRENGTH", "rucking": "RUCKING",
    "tackling": "TACKLING", "stamina": "STAMINA", "defense": "DEFENCE", "attack": "ATTACK",
    "handling": "HANDLING", "hooking": "HOOKING", "lineout": "LINEOUT", "speed": "SPEED",
    "crashball": "CRASH BALL", "passing": "PASSING", "agility": "AGILITY",
    "kicking": "KICKING", "creativity": "CREATIVITY", "acceleration": "ACCELERATION",
    "goal_kicking": "GOAL KICKING", "kicking_power": "KICK POWER", "gap_defense": "GAP DEFENCE",
}
STAT_ROWS = 6               # the position's most important ratings
SIDE_W = 400                # the side panel, fixed so names never shift the sheet
PANEL_W = 460               # the slide-over panels
TALL_WINDOW = 960           # below this the sheet uses the compact shirts
SHORT_WINDOW = 800          # below this too: 15 joins the back row, slimmer bench (1366x768, 720p)
STARTERS = 15
SQUAD = 22
SHEET, SQUAD_VIEW = 0, 1


def _pos(p):
    return (p or "").replace("_", " ")


def _abbr(p):
    return POSITION_ABBR.get(p, _pos(p))


def _pos_name(p):
    return POSITION_NAMES.get(p, _pos(p).capitalize())


def rating_color(v):
    return GREEN if v >= 80 else (FG_PRIMARY if v >= 65 else (WARN if v >= 50 else DANGER_LITE))


def _note_color(note, color):
    """Recolour a Note (its colour lives in its own stylesheet)."""
    note.setStyleSheet(re.sub(r"(?<![-\w])color: [^;]+;", f"color: {color};", note.styleSheet(), count=1))


def _sheet_player(p):
    """A tournament player as the team-sheet widgets read one (a flat dict
    with first / last / display name)."""
    d = dict(p.base)
    name = p.name or d.get("display_name") or ""
    d.setdefault("display_name", name)
    if not d.get("last_name"):
        d["last_name"] = name.split(".", 1)[-1].split(" ")[-1] if name else ""
    return d


def _rule():
    rule = QWidget()
    rule.setFixedHeight(1)
    rule.setStyleSheet(f"background: {BORDER};")
    return rule


class StatTiles(QWidget):
    """A row of big numbers with a caption each: APPS 3 · TRIES 2 ..."""

    def __init__(self, captions, parent=None):
        super().__init__(parent)
        self.setObjectName("statTiles")
        self.setStyleSheet("QWidget#statTiles { background: transparent; }")
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(6)
        self.values = []
        for caption in captions:
            tile = QWidget()
            tile.setObjectName("statTile")
            tile.setStyleSheet(f"QWidget#statTile {{ background: {BG_RAISED}; }}")
            v = QVBoxLayout(tile)
            v.setContentsMargins(6, 4, 6, 4)
            v.setSpacing(0)
            value = display_label("0", 18, QFont.Bold, track=0.2)
            value.setAlignment(Qt.AlignHCenter)
            v.addWidget(value)
            cap = eyebrow_label(caption, color=FG_TERTIARY, size=8)
            cap.setAlignment(Qt.AlignHCenter)
            v.addWidget(cap)
            h.addWidget(tile, stretch=1)
            self.values.append(value)

    def set_values(self, values):
        for label, value in zip(self.values, values):
            label.setText(str(value))
            label.setStyleSheet(label_css(18, QFont.Bold, FG_PRIMARY if value else FG_TERTIARY))


class TournamentSquadScreen(Screen):
    def __init__(self, on_back, embedded=False, on_hints=None):
        """`embedded`: shown inside the dashboard's Squad tab — no page
        header or hint bar of its own; `on_hints()` tells the host its
        hints (hint_items) changed."""
        super().__init__(on_back=on_back)
        self.embedded = embedded
        self.on_hints = on_hints
        self.session = None
        self.team_id = None
        self.ds = None
        self._slot = 0              # 0-based slot the side panel describes
        self._picker_slot = None    # slot the open picker belongs to
        self._panel = None          # "roles" / "lineups" while one is open
        self._compact = None
        self._stat_rows = STAT_ROWS
        self._preview = None        # auto mode: the 22 auto pick would choose now
        self._build()

    @property
    def t(self):
        return self.session.t

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header_holder = QVBoxLayout()
        root.addLayout(self.header_holder)

        body = QWidget()
        body.setObjectName("squadBody")
        body.setStyleSheet(f"QWidget#squadBody {{ background: {BG_BASE}; }}")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(*((0, 0, 0, 0) if self.embedded else (60, 20, 60, 16)))
        bl.setSpacing(24)
        left = QVBoxLayout()
        left.setSpacing(8)
        self.left_v = left
        self.view_tabs = TabStrip(["Team sheet", "Squad"], font_size=12)
        self.view_tabs.changed.connect(self._set_view)
        self.focus.register(self.view_tabs)
        left.addWidget(self.view_tabs)
        self.views = QStackedWidget()
        self.views.addWidget(self._build_sheet())
        self.views.addWidget(self._build_squad_view())
        left.addWidget(self.views, stretch=1)
        bl.addLayout(left, stretch=1)
        bl.addWidget(self._build_side_panel())
        root.addWidget(body, stretch=1)

        self.hintbar = HintBar()
        root.addWidget(self.hintbar)
        self.hintbar.setVisible(not self.embedded)

        self.panels = {}
        for name, build in (("roles", self._build_roles_panel), ("lineups", self._build_lineups_panel)):
            panel = build()
            panel.setParent(self)
            panel.hide()
            self.panels[name] = (panel, SidePanelSlide(panel, self._panel_rect))

        self.picker = PlayerPickerPopup(self, width=400, height=480, own_keys=True)
        self.picker.picked.connect(self._on_pick)
        self.picker.hovered.connect(self._preview_from_picker)
        self.picker.closed.connect(self._on_picker_closed)

    def _build_sheet(self):
        card = Card(stripe=YOU_TINT)
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 14, 24, 14)
        v.setSpacing(4)
        self.sheet_v = v
        head = QHBoxLayout()
        self.lineup_title = eyebrow_label("default lineup", color=YOU_TINT, size=13)
        head.addWidget(self.lineup_title)
        head.addStretch(1)
        self.xv_rating = eyebrow_label("", color=FG_SECONDARY, size=12)
        head.addWidget(self.xv_rating)
        v.addLayout(head)

        self.shirts = {}            # shirt number -> SlotAvatar / SubChip
        self.sheet_rows = []        # the XV's row layouts, in MATCH_SHEET_ROWS order
        for row in MATCH_SHEET_ROWS:
            hl = QHBoxLayout()
            self.sheet_rows.append(hl)
            hl.setSpacing(18)
            hl.addStretch(1)
            for number in row:
                hl.addWidget(self._wire(SlotAvatar(number, YOU_TINT)))
            hl.addStretch(1)
            v.addLayout(hl)

        v.addWidget(_rule())
        bench_head = QHBoxLayout()
        bench_head.addWidget(eyebrow_label("replacements", color=FG_SECONDARY, size=12))
        bench_head.addStretch(1)
        self.bench_rating = eyebrow_label("", color=FG_TERTIARY, size=11)
        bench_head.addWidget(self.bench_rating)
        v.addLayout(bench_head)
        bench = QGridLayout()
        self.bench_grid = bench
        bench.setHorizontalSpacing(8)
        bench.setVerticalSpacing(6)
        for i, number in enumerate(range(STARTERS + 1, SQUAD + 1)):
            bench.addWidget(self._wire(SubChip(number, YOU_TINT)), i // 4, i % 4)
        v.addLayout(bench)
        v.addStretch(1)
        return card

    def _build_squad_view(self):
        card = Card(stripe=YOU_TINT)
        v = QVBoxLayout(card)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(8)
        self.table = DataTable(["#", "Player", "Pos", "Rating", "Status", "Apps", "Min", "Tries", "Pts",
                                "Tkl", "MotM"], stretch_col=1,
                               widths={0: 44, 2: 84, 3: 70, 4: 130, 5: 56, 6: 60, 7: 60, 8: 56, 9: 56, 10: 62},
                               header_align={c: Qt.AlignHCenter for c in (0, 3, 5, 6, 7, 8, 9, 10)})
        self.table.currentCellChanged.connect(lambda r, *_: self._on_table_row(r))
        self.table.activated_row.connect(self._on_table_activated)
        self.focus.register(self.table)
        v.addWidget(self.table, stretch=1)
        return card

    def _wire(self, shirt):
        shirt.enable_dnd(True)
        shirt.activated.connect(self._on_shirt_activated)
        shirt.hovered.connect(self._on_shirt_hovered)
        shirt.unhovered.connect(lambda _n: self._show_slot(self._slot))
        shirt.dropped.connect(self._on_drop)
        self.focus.register(shirt)
        self.shirts[shirt.number] = shirt
        return shirt

    def _build_side_panel(self):
        card = Card()
        card.setFixedWidth(SIDE_W)
        self.side_card = card
        v = QVBoxLayout(card)
        self.side_v = v
        v.setContentsMargins(22, 16, 22, 16)
        v.setSpacing(8)
        inner = SIDE_W - 44

        # the team: crest, name, next match; a picker when two humans play
        team = QHBoxLayout()
        team.setSpacing(12)
        self.crest = PixmapLabel(44)
        team.addWidget(self.crest)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.team_name = display_label("", 18, QFont.Bold, track=1.0, color=YOU_TINT)
        self.team_name.setMinimumWidth(1)
        tv.addWidget(self.team_name)
        self.next_label = Note("", color=FG_TERTIARY)
        tv.addWidget(self.next_label)
        team.addLayout(tv, stretch=1)
        v.addLayout(team)
        self.team = ChoiceField("team", allow_blank=False)
        self.team.edited.connect(lambda tid: self._switch(tid))
        self.focus.register(self.team)
        v.addWidget(self.team)
        v.addWidget(_rule())
        v.addSpacing(2)

        # the player under the cursor
        self.slot_lbl = eyebrow_label("number 1", color=ACCENT, size=12)
        v.addWidget(self.slot_lbl)
        who = QHBoxLayout()
        who.setSpacing(10)
        names = QVBoxLayout()
        names.setSpacing(0)
        self.first_lbl = display_label("", 13, QFont.DemiBold, track=0.6, color=FG_SECONDARY, upper=False)
        self.first_lbl.setMinimumWidth(1)
        names.addWidget(self.first_lbl)
        self.name_lbl = display_label("—", 24, QFont.Bold, track=0.6)
        self.name_lbl.setMinimumWidth(1)
        names.addWidget(self.name_lbl)
        who.addLayout(names, stretch=1)
        self.rating_lbl = display_label("", 34, QFont.Bold, track=0.4)
        self.rating_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        who.addWidget(self.rating_lbl)
        v.addLayout(who)
        self.pos_lbl = display_label("", 11, QFont.DemiBold, track=1.4, color=FG_SECONDARY)
        self.pos_lbl.setWordWrap(True)
        self.pos_lbl.setFixedWidth(inner)
        v.addWidget(self.pos_lbl)
        self.status_lbl = Note("", color=FG_SECONDARY, size=T_LABEL)
        v.addWidget(self.status_lbl)
        self.tiles = StatTiles(["apps", "tries", "points", "tackles"])
        v.addWidget(self.tiles)
        v.addSpacing(2)
        self.stats = StatsPanel(attributes=[("", "")] * STAT_ROWS, min_height=STAT_ROWS * 26)
        v.addWidget(self.stats)
        v.addStretch(1)

        self.notes = Note("", color=FG_SECONDARY, size=T_LABEL)
        v.addWidget(self.notes)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.lineups_btn = StyledButton("LINEUPS", "neutral")
        self.lineups_btn.setMinimumHeight(BTN_HEIGHT)
        self.lineups_btn.clicked.connect(lambda: self.toggle_panel("lineups"))
        self.focus.register(self.lineups_btn)
        buttons.addWidget(self.lineups_btn, stretch=1)
        self.roles_btn = StyledButton("ROLES && PLAYS", "neutral")
        self.roles_btn.setMinimumHeight(BTN_HEIGHT)
        self.roles_btn.clicked.connect(lambda: self.toggle_panel("roles"))
        self.focus.register(self.roles_btn)
        buttons.addWidget(self.roles_btn, stretch=1)
        v.addLayout(buttons)
        self.auto_btn = StyledButton("AUTO PICK THE BEST 22", "ghost")
        self.auto_btn.setMinimumHeight(BTN_HEIGHT)
        self.auto_btn.clicked.connect(self._auto)
        self.focus.register(self.auto_btn)
        v.addWidget(self.auto_btn)
        self.done_btn = StyledButton("DONE", "primary")
        self.done_btn.setMinimumHeight(BTN_HEIGHT)
        self.done_btn.clicked.connect(lambda: self.on_back_cb())
        self.done_btn.setVisible(not self.embedded)
        if not self.embedded:
            self.focus.register(self.done_btn)
        v.addWidget(self.done_btn)
        return card

    def _panel_card(self, title, name):
        panel = Card()
        panel.setObjectName("squadPanel")
        panel.setStyleSheet(f"QWidget#squadPanel {{ background: {BG_PANEL};"
                            f" border-left: 3px solid {ACCENT}; }}")
        panel.setFixedWidth(PANEL_W)
        v = QVBoxLayout(panel)
        v.setContentsMargins(26, 20, 26, 20)
        v.setSpacing(10)
        head = QHBoxLayout()
        head.addWidget(display_label(title, 18, QFont.Bold, track=1.0))
        head.addStretch(1)
        close_btn = compact_button("CLOSE", "ghost")
        close_btn.clicked.connect(lambda: self.toggle_panel(name))
        self.focus.register(close_btn)
        head.addWidget(close_btn)
        v.addLayout(head)
        return panel, v

    def _build_roles_panel(self):
        panel, v = self._panel_card("Roles & plays", "roles")
        self.tactics_tabs = TabStrip(["Roles", "Set plays"])
        self.focus.register(self.tactics_tabs)
        v.addWidget(self.tactics_tabs)
        stack = transparent(QStackedWidget(), "squadTacticsStack")

        roles_page = transparent(QWidget(), "squadRolesPage")
        rv = QVBoxLayout(roles_page)
        rv.setContentsMargins(0, 8, 0, 0)
        grid = FieldGrid(columns=1, v_spacing=4)
        self.role_fields = {}
        for key, label in ROLE_LABELS.items():
            f = ChoiceField(label, allow_blank=False)
            f.popup_title = label
            f.off_list_badge = False
            f.edited.connect(lambda pid, k=key: self._set_role(k, pid))
            grid.add(f)
            self.focus.register(f)
            self.role_fields[key] = f
        rv.addWidget(grid)
        rv.addWidget(Note("Only a starter can hold a role."))
        rv.addStretch(1)
        stack.addWidget(roles_page)

        plays_page = transparent(QWidget(), "squadPlaysPage")
        pv = QVBoxLayout(plays_page)
        pv.setContentsMargins(0, 8, 0, 0)
        pg = FieldGrid(columns=1, v_spacing=4)
        self.play_fields = {}
        for key, label in SET_PLAY_DIRECTIONS:
            f = ChoiceField(label, SET_PLAYS, allow_blank=False)
            f.popup_title = f"set play · {key}"
            f.edited.connect(lambda play, k=key: self._set_play(k, play))
            pg.add(f)
            self.focus.register(f)
            self.play_fields[key] = f
        pv.addWidget(pg)
        pv.addWidget(Note("Called with the d-pad direction shown."))
        pv.addStretch(1)
        stack.addWidget(plays_page)
        self.tactics_tabs.changed.connect(stack.setCurrentIndex)
        v.addWidget(stack, stretch=1)
        return panel

    def _build_lineups_panel(self):
        panel, v = self._panel_card("Lineups", "lineups")
        self.mode_field = ChoiceField("each match", ["default", "auto"], allow_blank=False,
                                      display=lambda m: {"default": "Play my lineup",
                                                         "auto": "Auto pick the best 22"}.get(m, m))
        self.mode_field.popup_title = "each match"
        self.mode_field.edited.connect(self._set_mode)
        self.focus.register(self.mode_field)
        v.addWidget(self.mode_field)
        self.mode_note = Note("", color=FG_TERTIARY)
        self.mode_note.setWordWrap(True)
        v.addWidget(self.mode_note)
        self.save_btn = StyledButton("SAVE AS A NEW LINEUP…", "neutral")
        self.save_btn.setMinimumHeight(BTN_HEIGHT)
        self.save_btn.clicked.connect(self._save_as)
        self.focus.register(self.save_btn)
        v.addWidget(self.save_btn)
        self.lineup_rows = QVBoxLayout()
        self.lineup_rows.setSpacing(6)
        v.addLayout(self.lineup_rows)
        v.addStretch(1)
        self._lineup_widgets = []
        self._row_buttons = []      # per lineup row: its focusable buttons
        return panel

    def _panel_rect(self):
        return QRect(self.width() - PANEL_W, 0, PANEL_W, self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        for _panel, slide in self.panels.values():
            slide.sync_geometry()
        if self.picker.isVisible():
            self.picker.hide()      # its anchor geometry is stale
        self._fit_shirts()

    def _fit_shirts(self):
        """Full-size shirts when the window is tall enough, the team editor's
        compact ones otherwise; in a short window (1366x768, 720p) the sheet
        and the side panel tighten further so the page never scrolls."""
        h = self.window().height()
        compact, dense = h < TALL_WINDOW, h < SHORT_WINDOW
        if (compact, dense) == self._compact:
            return
        self._compact = (compact, dense)
        for shirt in self.shirts.values():
            if isinstance(shirt, SlotAvatar):
                shirt.set_compact(compact)
            else:
                shirt.setFixedHeight(30 if dense else 38)
        self.sheet_v.setSpacing(0 if compact else 4)
        self.sheet_v.setContentsMargins(*((20, 2, 20, 2) if dense else (20, 8, 20, 8) if compact
                                          else (24, 14, 24, 14)))
        self.left_v.setSpacing(0 if dense else 8)
        self.view_tabs.setFixedHeight(30 if dense else 40)
        self.bench_grid.setVerticalSpacing(3 if dense else 6)
        self._place_fullback(dense)
        self.tiles.setVisible(not dense)
        self.side_v.setContentsMargins(*((22, 10, 22, 10) if dense else (22, 16, 22, 16)))
        self.side_v.setSpacing(5 if dense else 8)
        self._stat_rows = 4 if compact else STAT_ROWS
        self.stats.setMinimumHeight(self._stat_rows * 26)
        self._show_slot(self._slot)

    def _place_fullback(self, in_back_row):
        """Short window: 15 stands in the back row, between the centres
        (11 12 15 13 14), which saves the sheet a whole row of shirts."""
        shirt = self.shirts[15]
        own, back = self.sheet_rows[-1], self.sheet_rows[-2]
        target, index = (back, 3) if in_back_row else (own, 1)
        if target.indexOf(shirt) >= 0:
            return
        (own if in_back_row else back).removeWidget(shirt)
        target.insertWidget(index, shirt)

    # ── entry ────────────────────────────────────────────────────────────
    def set_team(self, session, team_id):
        self.session = session
        self.ds = session.ds
        humans = [e.team_id for e in session.t.human_teams()]
        self.team.display = self.t.team_name
        self.team.set_options(humans)
        self.team.setVisible(len(humans) > 1)
        self._switch(team_id or (humans[0] if humans else None))

    def _switch(self, team_id):
        self.team_id = team_id
        self.team.set_value(team_id)
        clear_layout(self.header_holder)
        if not self.embedded:
            self.header_holder.addWidget(page_header(f"Squad · {self.t.team_name(team_id)}",
                                                     on_back=self.on_back_cb))
        self.crest.set_pixmap(tournament_crest(self.ds, self.t, team_id, 44))
        self.team_name.setText(self.t.team_name(team_id).upper())
        self._slot = 0
        self.refresh()

    def on_show(self):
        super().on_show()
        self._fit_shirts()
        self._update_hints()

    def enter(self):
        """Focus moves in from the host (the dashboard's tab bar)."""
        if self.views.currentIndex() == SQUAD_VIEW:
            self.view_tabs.setFocus()
        else:
            shirt = self.shirts.get(self._slot + 1) or self.shirts[1]
            shirt.setFocus()
            self._show_slot(shirt.number - 1)
        self._update_hints()

    # ── data ─────────────────────────────────────────────────────────────
    def _entry(self):
        return self.t.teams[self.team_id]

    def _auto_mode(self):
        return lineups.is_auto(self._entry())

    def _next_fixture(self):
        return next((f for f in sorted(self.t.fixtures, key=lambda f: f.day)
                     if not f.played and f.involves(self.team_id)), None)

    def _sel(self):
        """The lineup on show: the default, or (auto mode) what auto pick
        would choose for the next match."""
        if self._auto_mode():
            if self._preview is None:
                self._preview = selection.auto_select(self.t, self.team_id, self._next_fixture())
            return self._preview
        return lineups.default(self._entry())

    def _players(self):
        return list(self._sel().get("players", []))

    def _positions(self):
        pos = list(self._sel().get("positions") or [])
        return pos + SLOT_POSITIONS[len(pos):]

    def _slot_pos(self, slot):
        positions = self._positions()
        return positions[slot] if slot < len(positions) else SLOT_POSITIONS[0]

    def _rating_at(self, p, pos, slot=None):
        ctx = MatchContext(team_id=self.team_id, position=pos, slot=(slot + 1) if slot is not None else 0)
        eff = slot_rating(effective_stats(self.t, p, ctx), pos, p.positions)
        base = slot_rating(base_ratings(p), pos, p.positions)
        return eff, base

    def _rating(self, p, slot):
        return self._rating_at(p, self._slot_pos(slot), slot)

    def _fits(self, p, slot):
        return position_fit(p.positions, self._slot_pos(slot)) >= 0.9

    def _issue_color(self, p, slot):
        if not is_available(self.t, p):
            return DANGER_LITE
        return None if self._fits(p, slot) else WARN

    def _lineup_name(self):
        entry = self._entry()
        if self._auto_mode():
            return "auto pick"
        i = lineups.matching(entry, self._sel())
        return lineups.saved(entry)[i]["name"] if i is not None else ""

    def _edited_index(self):
        """The saved lineup the team sheet came from and has been changed
        since (it can be updated or reverted), or None."""
        entry = self._entry()
        if self._auto_mode():
            return None
        src = lineups.source(entry)
        if src is None or lineups.matching(entry, self._sel()) == src:
            return None
        return src

    # ── refresh ──────────────────────────────────────────────────────────
    def refresh(self):
        if not self.session or not self.team_id:
            return
        self._preview = None
        t = self.t
        sel = self._sel()
        players = self._players()
        roles = sel.get("roles", {})
        nxt = self._next_fixture()
        self.next_label.setText(f"Next: {report.fixture_caption(t, nxt)}" if nxt else "No match left to play")
        if self._auto_mode():
            title = "auto pick · the best 22 for the next match"
        else:
            name = self._lineup_name()
            edited = self._edited_index()
            if not name and edited is not None:
                name = f"{lineups.saved(self._entry())[edited]['name']} (edited)"
            title = "your lineup" + (f" · {name}" if name else "")
        self.lineup_title.setText(title.upper())
        # auto mode already re-picks before every match: nothing to do now
        self.auto_btn.setVisible(not self._auto_mode())

        badges = {}
        for key, badge in (("captain", "C"), ("longGK", "K")):
            if roles.get(key):
                badges.setdefault(roles[key], []).append(badge)
        xv, bench = [], []
        for number, shirt in self.shirts.items():
            slot = number - 1
            pid = players[slot] if slot < len(players) else None
            p = t.players.get(pid)
            if p is None:
                shirt.set_player(None)
                shirt.set_value(None)
                shirt.set_issue(None)
                shirt.set_badges([])
                continue
            eff, _base = self._rating(p, slot)
            shirt.set_player(_sheet_player(p))
            shirt.set_value(f"{eff:.0f}", rating_color(eff))
            shirt.set_issue(self._issue_color(p, slot))
            shirt.set_badges(badges.get(pid, []))
            (xv if slot < STARTERS else bench).append(eff)
        self.xv_rating.setText(f"xv {sum(xv) / len(xv):.0f}".upper() if xv else "")
        self.bench_rating.setText(f"bench {sum(bench) / len(bench):.0f}".upper() if bench else "")

        self._refresh_notes(nxt)
        self._refresh_roles()
        self._refresh_lineups()
        if self.views.currentIndex() == SQUAD_VIEW:
            self._refresh_table()
        self._show_slot(self._slot)
        self._update_hints()

    def _refresh_notes(self, nxt):
        """What the user should know, nothing else: auto mode, who covers
        an unavailable player in the next match, real problems."""
        t, sel = self.t, self._sel()
        lines, color = [], FG_SECONDARY
        if self._auto_mode():
            lines.append("Auto pick: the best 22 is chosen before every match. "
                         "Change a shirt to take over.")
        else:
            _pids, changes = selection.cover(t, self.team_id, sel, nxt)
            for out, cover in changes:
                lines.append(f"Next match: {t.player_name(cover)} covers for {t.player_name(out)}")
            errors, warnings = selection.validate(t, self.team_id, sel, availability=False)
            if errors:
                color = DANGER_LITE
            lines += errors + warnings
        self.notes.setText("\n".join(lines))
        _note_color(self.notes, color)
        self.notes.setVisible(bool(lines))

    def _refresh_roles(self):
        t = self.t
        sel = self._sel()
        roles = sel.get("roles", {})
        starters = [pid for pid in self._players()[:STARTERS] if pid in t.players]
        shirt_of = {pid: i + 1 for i, pid in enumerate(starters)}

        def display(pid):
            p = t.players.get(pid)
            return f"{p.name}  #{shirt_of.get(pid, '?')}" if p else "—"

        for key, f in self.role_fields.items():
            stat = ROLE_RATING.get(key)
            if stat:
                score = {pid: effective_stats(t, t.players[pid])[stat] for pid in starters}
                f.set_options(sorted(starters, key=lambda pid: -score[pid]))
                f.tag_for = lambda pid, s=score: (str(s.get(pid, "")), FG_TERTIARY)
            else:
                f.set_options(starters)
                f.tag_for = None
            f.display = display
            f.set_value(roles.get(key, ""))
        plays = sel.get("set_plays") or self._entry().set_plays or {}
        for key, f in self.play_fields.items():
            f.set_value(plays.get(key, "") or "")

    def _refresh_lineups(self):
        """The Lineups panel: the mode, the saved lineups, the played ones."""
        entry = self._entry()
        auto = self._auto_mode()
        self.mode_field.set_value("auto" if auto else "default")
        self.mode_note.setText(
            "The best fit 22 is picked before every match. Changing a shirt switches "
            "to your own lineup." if auto else
            "Every match starts from the team sheet as you set it; anyone injured or "
            "suspended is covered for that match only.")
        focused = QApplication.focusWidget()
        for w in self._lineup_widgets:
            if focused is not None and (w is focused or w.isAncestorOf(focused)):
                # a row's button had the focus: park it before the row goes
                # (else it stays on the dying button, and keys go nowhere)
                self.mode_field.setFocus()
            self.focus.unregister_tree(w)
            self.lineup_rows.removeWidget(w)
            w.hide()
            w.deleteLater()
        self._lineup_widgets = []
        current = None if self._auto_mode() else lineups.matching(entry, self._sel())

        def add(widget):
            self.lineup_rows.addWidget(widget)
            self._lineup_widgets.append(widget)

        saved = lineups.saved(entry)
        add(eyebrow_label("your saved lineups", color=FG_SECONDARY, size=11))
        if not saved:
            add(Note("None yet: SAVE AS A NEW LINEUP… keeps the team sheet under a name, "
                     "to come back to it later."))
        self._row_buttons = []
        edited = self._edited_index()
        for i, item in enumerate(saved):
            actions = [("USE", lambda _=False, it=item, i=i: self._load(it, row=i)),
                       ("RENAME", lambda _=False, i=i: self._rename(i)),
                       ("DELETE", lambda _=False, i=i: self._delete(i))]
            if i == edited:
                # the sheet is this lineup with changes: keep them, or not
                actions = [("UPDATE", lambda _=False, i=i: self._update(i)),
                           ("REVERT", lambda _=False, it=item, i=i: self._load(it, row=i))] + actions[1:]
            add(self._lineup_row(item["name"], self._xv_of(item), i == current, actions,
                                 edited=i == edited))
        played = lineups.played(self.t, self.team_id)
        if played:
            add(eyebrow_label("lineups of your matches", color=FG_SECONDARY, size=11))
        for j, (f, sel) in enumerate(played[:8]):
            add(self._lineup_row(self._played_caption(f), self._xv_of(sel), False, [
                ("USE", lambda _=False, s=sel, r=len(saved) + j: self._load(s, row=r)),
            ]))

    def _xv_of(self, sel):
        t = self.t
        positions = list(sel.get("positions") or []) + SLOT_POSITIONS[len(sel.get("positions") or []):]
        vals = [self._rating_at(t.players[pid], positions[i], i)[0]
                for i, pid in enumerate(sel.get("players", [])[:STARTERS]) if pid in t.players]
        return round(sum(vals) / len(vals)) if vals else None

    def _played_caption(self, f):
        t = self.t
        home = f.home == self.team_id
        other = t.team_name(f.away if home else f.home)
        mine, theirs = ((f.result.home.points, f.result.away.points) if home
                        else (f.result.away.points, f.result.home.points))
        winner = f.result.winner_id()
        mark = "W" if winner == self.team_id else ("D" if winner is None else "L")
        return f"{report.round_short(t, f.day)}  v {other}  {mark} {mine}-{theirs}"

    def _lineup_row(self, title, xv, current, actions, edited=False):
        """Name and XV rating on top (the whole name: nothing squeezes it),
        the actions under it. The lineup on the team sheet says IN USE
        instead of offering USE."""
        row = QWidget()
        row.setObjectName("lineupRow")
        edge = ACCENT if current else (WARN if edited else BG_RAISED)
        row.setStyleSheet(f"QWidget#lineupRow {{ background: {BG_RAISED};"
                          f" border-left: 3px solid {edge}; }}")
        v = QVBoxLayout(row)
        v.setContentsMargins(12, 6, 8, 6)
        v.setSpacing(4)
        top = QHBoxLayout()
        top.setSpacing(6)
        name = display_label(title, 12, QFont.Bold, track=0.4, upper=False,
                             color=ACCENT if current else FG_PRIMARY)
        name.setMinimumWidth(1)
        top.addWidget(name, stretch=1)
        if edited:
            top.addWidget(eyebrow_label("edited", color=WARN, size=10))
        if xv is not None:
            top.addWidget(display_label(f"XV {xv}", 11, QFont.DemiBold, track=0.6, color=FG_TERTIARY))
        v.addLayout(top)
        h = QHBoxLayout()
        h.setSpacing(6)
        buttons = []
        for label, fn in actions:
            if label == "USE" and current:
                h.addWidget(eyebrow_label("in use", color=ACCENT, size=10))
                continue
            b = compact_button(label, "ghost" if label == "DELETE" else "neutral", height=30)
            b.clicked.connect(fn)
            self.focus.register(b)
            h.addWidget(b)
            buttons.append(b)
        h.addStretch(1)
        v.addLayout(h)
        self._row_buttons.append(buttons)
        return row

    def _refresh_table(self):
        t = self.t
        entry = self._entry()
        players = self._players()
        table = t.stats.get("players", {})
        rows, keys = [], []

        def row(pid, shirt):
            # the 22 rated in their shirt (the number the sheet shows), the
            # rest at their own position: each section header says which
            p = t.players[pid]
            eff, _b = self._rating(p, shirt - 1) if shirt else self._rating_at(p, p.position)
            s = table.get(pid, {})
            available = is_available(t, p)
            status = report.player_status(t, p)
            dim = FG_PRIMARY if shirt else FG_SECONDARY
            return [
                {"text": shirt or "", "color": YOU_TINT, "align": Qt.AlignHCenter, "bold": True},
                {"text": p.name, "color": DANGER_LITE if not available else dim, "bold": bool(shirt and shirt <= 15)},
                {"text": " ".join(_abbr(x) for x in p.positions[:2]), "color": FG_TERTIARY},
                {"text": f"{eff:.0f}", "color": rating_color(eff), "bold": True, "align": Qt.AlignHCenter},
                {"text": status, "color": DANGER_LITE if not available else
                 (WARN if status != "fit" else FG_TERTIARY)},
            ] + [{"text": s.get(k, 0) or "–", "align": Qt.AlignHCenter,
                  "color": FG_PRIMARY if s.get(k) else FG_TERTIARY}
                 for k in ("apps", "minutes", "tries", "points", "tackles", "motm")]

        rows.append(Section("matchday 22", right="rating: in his shirt"))
        keys.append(None)
        for i, pid in enumerate(players):
            if pid in t.players:
                rows.append(row(pid, i + 1))
                keys.append(pid)
        rest = [pid for pid in entry.squad if pid in t.players and pid not in players]
        rest.sort(key=lambda pid: -self._rating_at(t.players[pid], t.players[pid].position)[0])
        if rest:
            rows.append(Section("rest of the squad", right="rating: at his own position", gap=True))
            keys.append(None)
        for pid in rest:
            rows.append(row(pid, None))
            keys.append(pid)
        self.table.set_rows(rows, keys=keys)

    # ── the side panel ───────────────────────────────────────────────────
    def _show_slot(self, slot, player=None):
        """The side panel describes `slot` and its player — or `player`, a
        candidate the picker is pointing at, measured for that slot."""
        if not self.session or not self.team_id:
            return
        if player is None:
            self._slot = slot
        pos = self._slot_pos(slot)
        players = self._players()
        current = self.t.players.get(players[slot]) if slot < len(players) else None
        self._describe(player or current, pos, slot, f"number {slot + 1} · "
                       + (_pos_name(pos) if slot < STARTERS else f"replacement · {_abbr(pos)}"))

    def _describe(self, p, pos, slot, caption):
        t = self.t
        self.slot_lbl.setText(caption.upper())
        if p is None:
            for lbl in (self.first_lbl, self.pos_lbl, self.status_lbl, self.rating_lbl):
                lbl.setText("")
            self.name_lbl.setText("EMPTY")
            self.tiles.set_values([0, 0, 0, 0])
            self.stats.set_player(None)
            return
        d = _sheet_player(p)
        self.first_lbl.setText((d.get("first_name") or "").strip())
        self.name_lbl.setText((d.get("last_name") or p.name).upper())
        self.pos_lbl.setText(" / ".join(_pos_name(x).upper() for x in p.positions))

        eff, base = self._rating_at(p, pos, slot)
        available = is_available(t, p)
        fits = position_fit(p.positions, pos) >= 0.9
        notes = [report.player_status(t, p)]
        if not fits:
            notes.append(f"out of position (a {_pos(p.position)})")
        if round(base) != round(eff):
            notes.append(f"normally {base:.0f}")
        self.status_lbl.setText(" · ".join(notes))
        _note_color(self.status_lbl, DANGER_LITE if not available else (WARN if not fits else FG_SECONDARY))
        self.rating_lbl.setText(f"{eff:.0f}")
        self.rating_lbl.setStyleSheet(label_css(34, QFont.Bold, rating_color(eff)))
        s = t.stats.get("players", {}).get(p.pid, {})
        self.tiles.set_values([s.get(k, 0) for k in ("apps", "tries", "points", "tackles")])

        weights = POSITION_WEIGHTS.get(group_of(pos) or "centre", {})
        keys = sorted(weights, key=lambda k: -weights[k])[:self._stat_rows]
        ctx = MatchContext(team_id=self.team_id, position=pos, slot=(slot + 1) if slot is not None else 0)
        self.stats.attributes = [(STAT_LABELS.get(k, k.upper()), k) for k in keys]
        self.stats.set_player(effective_stats(t, p, ctx))

    def _on_table_row(self, row):
        keys = self.table.keys
        pid = keys[row] if 0 <= row < len(keys) else None
        p = self.t.players.get(pid) if pid else None
        if p is None:
            return
        players = self._players()
        if pid in players:
            self._show_slot(players.index(pid))
        else:
            self._describe(p, p.position, None, f"squad · {_pos_name(p.position)}")

    def _on_table_activated(self, row):
        """A (Enter, double-click) on a player: back to the team sheet — on
        his shirt when he is in the 22, else with the picker open on the
        shirt that suits him best, him highlighted, so one more A puts him
        in."""
        pid = self.table.keys[row] if 0 <= row < len(self.table.keys) else None
        p = self.t.players.get(pid) if pid else None
        if p is None:
            return
        players = self._players()
        self.view_tabs.set_index(SHEET)
        if pid in players:
            shirt = self.shirts[players.index(pid) + 1]
            shirt.setFocus()
            self._show_slot(shirt.number - 1)
            return
        slot = self._slot_for(p)
        self.shirts[slot + 1].setFocus()
        self._show_slot(slot)
        self._open_picker(slot + 1, highlight=pid)

    def _slot_for(self, p):
        """The shirt a player from outside the 22 would most sensibly take:
        among the shirts he fits, the one whose wearer rates lowest there
        (a starter's shirt before a replacement's on a tie); with none he
        fits, the one he fits best."""
        players = self._players()
        best, best_key = 0, None
        for slot in range(min(SQUAD, len(players))):
            fit = position_fit(p.positions, self._slot_pos(slot))
            wearer = self.t.players.get(players[slot])
            there = self._rating(wearer, slot)[0] if wearer is not None else 0
            key = (fit >= 0.9, fit if fit < 0.9 else 0, -there, slot < STARTERS)
            if best_key is None or key > best_key:
                best, best_key = slot, key
        return best

    def _set_view(self, i):
        self.views.setCurrentIndex(i)
        if i == SQUAD_VIEW:
            self._refresh_table()
            # the side panel follows the list: its first player to start
            row = self.table.currentRow()
            if not (0 <= row < len(self.table.keys)) or self.table.keys[row] is None:
                row = next((r for r, k in enumerate(self.table.keys) if k), -1)
                if row >= 0:
                    self.table.setCurrentCell(row, 1)
            self._on_table_row(row)
        else:
            self._show_slot(self._slot)
        self._update_hints()

    # ── shirts ───────────────────────────────────────────────────────────
    def _on_shirt_hovered(self, number):
        if self.picker.isVisible():
            return
        keep = self._slot
        self._show_slot(number - 1)
        self._slot = keep

    def _on_shirt_activated(self, number):
        self._show_slot(number - 1)
        self._open_picker(number)

    def _on_drop(self, src, dst):
        self._swap(src - 1, dst - 1)
        self._slot = dst - 1
        self.shirts[dst].setFocus()

    def _swap(self, a, b):
        players = self._players()
        if max(a, b) >= len(players) or a == b:
            return
        players[a], players[b] = players[b], players[a]
        self._commit(players)

    def _open_picker(self, number, highlight=None):
        slot = number - 1
        t = self.t
        players = self._players()
        current = players[slot] if slot < len(players) else None
        taken = {pid: i + 1 for i, pid in enumerate(players) if pid != current}
        scored = []
        for pid in self._entry().squad:
            p = t.players.get(pid)
            if p is not None:
                scored.append((pid, p, self._rating(p, slot)[0]))
        # the current one first, then available before unavailable, by rating here
        scored.sort(key=lambda x: (x[0] != current, not is_available(t, x[1]), -x[2]))
        entries, tags, subtitles = [], {}, {}
        for pid, p, eff in scored:
            available = is_available(t, p)
            entries.append((pid, p.name, available and self._fits(p, slot)))
            if not available:
                tags[pid] = (report.player_status(t, p).upper(), DANGER_LITE)
            elif pid in taken:
                tags[pid] = (f"#{taken[pid]}", WARN if taken[pid] <= STARTERS else FG_TERTIARY)
            subtitles[pid] = f"{eff:.0f}   {' '.join(_abbr(x) for x in p.positions)}"
        title = f"NUMBER {number} · {_pos_name(self._slot_pos(slot)).upper()}"
        self._picker_slot = slot
        self.picker.open_for(title, entries, current, taken, self.shirts[number], self,
                             tags=tags, subtitles=subtitles, mode=FITS, highlight=highlight)
        self._keep_picker_off_panel()
        if highlight is not None:
            self._preview_from_picker(highlight)
        self._update_hints()

    def _keep_picker_off_panel(self):
        """The side panel previews the player under the picker's highlight:
        a picker opened on a shirt near it (a replacement on the right) is
        moved left so it never covers that preview."""
        pop = getattr(self.picker, "_popup", None)
        if pop is None or not pop.isVisible() or pop.parentWidget() is not self:
            return
        panel_left = self.side_card.mapTo(self, QPoint(0, 0)).x()
        if pop.geometry().right() > panel_left - 8:
            pop.move(max(8, panel_left - pop.width() - 8), pop.y())

    def _preview_from_picker(self, pid):
        if self._picker_slot is None:
            return
        p = self.t.players.get(pid)
        if p is not None:
            self._show_slot(self._picker_slot, player=p)
        self._update_hints()

    def _on_pick(self, pid):
        slot = self._picker_slot
        if slot is None or pid is None:
            return
        players = self._players()
        if slot >= len(players) or players[slot] == pid:
            return
        if pid in players:
            j = players.index(pid)
            players[j], players[slot] = players[slot], players[j]
        else:
            players[slot] = pid
        self._commit(players)

    def _on_picker_closed(self):
        slot = self._picker_slot
        self._picker_slot = None
        if slot is not None:
            self._show_slot(slot)
            shirt = self.shirts.get(slot + 1)
            if shirt is not None:
                shirt.setFocus()
        self._update_hints()

    # ── edits ────────────────────────────────────────────────────────────
    def _commit(self, players, roles=None, set_plays=None):
        """Any change makes the lineup on the sheet the default (and so
        switches auto pick off)."""
        sel = self._sel()
        self.session.set_selection(self.team_id, players, self._positions(),
                                   roles or sel.get("roles"),
                                   set_plays if set_plays is not None else sel.get("set_plays"))
        self.refresh()

    def _set_role(self, key, pid):
        roles = dict(self._sel().get("roles", {}))
        if roles.get(key) == pid:
            return
        roles[key] = pid
        self._commit(self._players(), roles)

    def _set_play(self, key, play):
        plays = dict(self._sel().get("set_plays") or self._entry().set_plays or {})
        if plays.get(key) == play:
            return
        plays[key] = play
        self._commit(self._players(), set_plays=plays)

    def _auto(self):
        """The best 22 now, as your lineup. A lineup of your own that is not
        saved anywhere would be lost: asked first."""
        if self._auto_mode():
            return
        entry = self._entry()
        if lineups.matching(entry, self._sel()) is not None:
            self._do_auto()
            return
        ConfirmDialog(self.window(), "Auto pick the best 22?",
                      "Your lineup on the team sheet is replaced. It isn't saved: "
                      "LINEUPS > SAVE AS A NEW LINEUP… keeps it.",
                      [("CANCEL", "neutral", "cancel"), ("AUTO PICK", "primary", "ok")],
                      lambda role: self._do_auto() if role == "ok" else self.auto_btn.setFocus())

    def _do_auto(self):
        self.session.auto_select(self.team_id)
        self.refresh()

    def _set_mode(self, mode):
        if mode == "auto":
            self.session.set_auto_lineup(self.team_id, True)
        else:
            # take what is on show (the auto pick preview) as the lineup:
            # an edit of no saved lineup
            lineups.set_source(self._entry(), None)
            sel = self._sel()
            self.session.set_selection(self.team_id, sel.get("players", []), sel.get("positions"),
                                       sel.get("roles"), sel.get("set_plays"))
        self.refresh()

    def _load(self, sel, row=None):
        self.session.load_lineup(self.team_id, sel, source=sel.get("name"))
        self.refresh()
        # stay on the row just used (its USE became IN USE: its next button)
        buttons = self._row_buttons[row] if row is not None and row < len(self._row_buttons) else []
        # deferred: the rebuilt rows are only shown on the next turn, and a
        # hidden widget can't take the focus
        QTimer.singleShot(0, (buttons[0] if buttons else self.save_btn).setFocus)

    def _ask_name(self, title, default, on_ok):
        field = TextField("name")
        field.set_value(default)

        def done(role):
            name = field.value().strip()
            if role == "ok" and name:
                on_ok(name)
            QTimer.singleShot(0, self.save_btn.setFocus)

        FormDialog(self.window(), title, "", {"name": field},
                   [("CANCEL", "neutral", "cancel"), ("SAVE", "primary", "ok")], done, width=460)
        QTimer.singleShot(0, field.begin_edit)

    def _save_as(self):
        entry = self._entry()
        if self._auto_mode():
            self._set_mode("default")      # a saved lineup is a lineup of your own
        default = self._lineup_name() or f"Lineup {len(lineups.saved(entry)) + 1}"
        self._ask_name("Save lineup", default,
                       lambda name: (self.session.save_lineup(self.team_id, name), self.refresh()))

    def _update(self, index):
        """Write the sheet's changes into the saved lineup they came from."""
        self.session.update_lineup(self.team_id, index)
        self.refresh()
        buttons = self._row_buttons[index] if index < len(self._row_buttons) else []
        QTimer.singleShot(0, (buttons[0] if buttons else self.save_btn).setFocus)

    def _rename(self, index):
        item = lineups.saved(self._entry())[index]
        self._ask_name("Rename lineup", item["name"],
                       lambda name: (self.session.rename_lineup(self.team_id, index, name), self.refresh()))

    def _delete(self, index):
        item = lineups.saved(self._entry())[index]

        def done(role):
            if role == "ok":
                self.session.delete_lineup(self.team_id, index)
                self.refresh()
            QTimer.singleShot(0, self.save_btn.setFocus)
        ConfirmDialog(self.window(), "Delete lineup?", f"“{item['name']}” is deleted. "
                      "The team sheet stays as it is.",
                      [("CANCEL", "neutral", "cancel"), ("DELETE", "danger", "ok")], done)

    # ── panels ───────────────────────────────────────────────────────────
    def toggle_panel(self, name):
        if self._panel and self._panel != name:
            self.toggle_panel(self._panel)
        panel, slide = self.panels[name]
        opening = self._panel != name
        self._panel = name if opening else None
        slide.set_open(opening)
        if opening:
            panel.raise_()
            self.focus.push_scope(panel)
            (self.tactics_tabs if name == "roles" else self.mode_field).setFocus()
        else:
            self.focus.pop_scope(panel)
            (self.roles_btn if name == "roles" else self.lineups_btn).setFocus()
        self._update_hints()

    # ── hints / keys ─────────────────────────────────────────────────────
    def _picker_verb(self):
        pid = self.picker.highlighted_pid()
        players = self._players()
        slot = self._picker_slot
        if pid is None or slot is None:
            return "—"
        if slot < len(players) and players[slot] == pid:
            return "keep"
        if pid in players:
            return f"swap with {players.index(pid) + 1}"
        return "pick"

    def hint_items(self):
        if self.picker.isVisible():
            return [("↕", "browse"), ("←→", "suggested / all"), ("A", self._picker_verb()),
                    ("B", "cancel")]
        if self._panel:
            return [("A", "select"), ("B", "close panel")]
        hints = [("A", "pick player" if self.views.currentIndex() == SHEET else "to the team sheet")]
        if not self._auto_mode():
            hints.append(("X", "auto pick"))
        hints += [("Y", "lineups"), ("START", "roles & plays")]
        if self.views.currentIndex() == SQUAD_VIEW:
            return hints + [("B", "team sheet")]
        return hints + [("B", "back" if self.embedded else "done")]

    def _update_hints(self):
        self.hintbar.set_hints(self.hint_items())
        if self.on_hints:
            self.on_hints()

    def has_focus_inside(self):
        w = QApplication.focusWidget()
        return w is not None and (w is self or self.isAncestorOf(w))

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action == Action.ALT and not self._panel:
            self._auto()
            event.accept()
            return
        if action == Action.AUX:
            self.toggle_panel("lineups")
            event.accept()
            return
        if action == Action.ADVANCED:
            self.toggle_panel("roles")
            event.accept()
            return
        if action == Action.BACK and self._panel:
            self.toggle_panel(self._panel)
            event.accept()
            return
        if action == Action.BACK and self.views.currentIndex() == SQUAD_VIEW:
            # the list is a step inside the team sheet: B goes back there
            # first (on the shirt last looked at), the next B to the host
            self.view_tabs.set_index(SHEET)
            shirt = self.shirts.get(self._slot + 1) or self.shirts[1]
            shirt.setFocus()
            self._show_slot(shirt.number - 1)
            self._update_hints()
            event.accept()
            return
        if action == Action.CONFIRM:
            w = QApplication.focusWidget()
            if isinstance(w, (SlotAvatar, SubChip)):
                self._on_shirt_activated(w.number)
                event.accept()
                return
        if action in (Action.NAV_UP, Action.NAV_DOWN, Action.NAV_LEFT, Action.NAV_RIGHT):
            moved = self.focus.move(action)
            if moved is None and action == Action.NAV_UP and self.embedded and not self._panel:
                self.on_back_cb()       # off the top: back to the host's tabs
            w = QApplication.focusWidget()
            if isinstance(w, (SlotAvatar, SubChip)):
                self._show_slot(w.number - 1)
            event.accept()
            return
        super().keyPressEvent(event)
