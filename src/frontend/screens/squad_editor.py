"""
screens/squad_editor.py — Squad editor (broadcast redesign)
================================================================
Team-sheet disposition: the starting XV laid out the way a matchday
graphic shows it (front row, locks, back row, half-backs, three-quarters,
full-back), with the 7 replacements underneath — 22 players, which is what
the backend actually accepts.

Replaces lineup_edit.py, whose domain constants (position per shirt, roles,
set plays) are carried over below.
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QSizePolicy, QLabel
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics
from PyQt5.QtCore import Qt, QRect, QRectF, QTimer, pyqtSignal

from app.screen_base import Screen
from app.input import Action, KEYMAP
from ui import StyledButton
from ui.broadcast import (
    Card, SelectorRow, HintBar, SegmentedToggle, page_header, eyebrow_label,
    display_label, tracked_font,
)
from ui.dropdown import PopupList
from ui.side_panel import SidePanelSlide
from ui.theme import (
    BG_BASE, BG_CARD, BG_RAISED, BG_HIGHLIGHT, BORDER, BG_PANEL,
    ACCENT, WARN, HOME_TINT, FG_PRIMARY, FG_SECONDARY, FG_MUTED,
    FONT_DISPLAY, BTN_HEIGHT,
)

# Shared with the team editor's squad tab.
from ui.team_sheet import (   # noqa: E402
    POSITION_FOR_NUMBER, SHEET_ROWS, STARTERS, SUBSTITUTES, SQUAD_SIZE,
    POSITION_NAMES, ACCEPTED_POSITIONS, SlotAvatar, SubChip, StatsPanel,
    PlayerPickerPopup, FITS, ALL, route_picker_key,
    last_name as _last_name, all_positions as _all_positions, initials as _initials,
)

SET_PLAY_KEYS = {
    "up": "Up Arrow", "down": "Down Arrow",
    "left": "Left Arrow", "right": "Right Arrow",
}

SET_PLAY_OPTIONS = {
    "classic": "Classic", "pivot": "Pivot", "pocket": "Pocket",
    "dummy_switch": "Dummy Switch", "miss": "Miss", "cross_kick": "Cross Kick",
    "loop": "Loop", "miss_pivot": "Miss Pivot",
}

# Roles the backend writes. viceCaptain was missing from the old editor
# although the team JSON carries it and the backend expects it.
ROLE_LABELS = {
    "captain": "Captain", "viceCaptain": "Vice-captain",
    "longGK": "Long GK", "shortGK": "Short GK",
    "longPunt": "Long Punt", "shortPunt": "Short Punt", "kickoff": "Kick-off",
}

# Fixed width for the stats side panel — set once and never negotiated
# against the sheet's stretch factor, so swapping to a longer player name
# or a longer position list can't jump the whole layout around.
SIDE_PANEL_WIDTH = 340    # the left-hand actions card
SIDE_PANEL_MARGIN = 22
ROLES_PANEL_W = 440       # the roles/set-plays slide-over on the right


def _elide_for(label, text: str) -> str:
    """Elide `text` to whatever width `label` actually has, so a long name
    or position list never forces the label — and the fixed-width panel
    around it — to grow."""
    fm = QFontMetrics(label.font())
    return fm.elidedText(text, Qt.ElideRight, label.width())


class SquadEditorScreen(Screen):
    def __init__(self, side, team_name, players: dict, lineup: dict,
                 on_confirm, on_discard):
        super().__init__(on_back=on_discard)
        self.side = side
        self.tint = HOME_TINT
        self.team_name = team_name
        self.players = {int(k): v for k, v in players.items()}
        self.on_confirm = on_confirm
        self.on_discard = on_discard

        # A player can only hold one shirt: dedupe rather than letting a
        # repeated id in the team file fill several slots with the same man.
        # `if pid` (not just `is not None`) — an empty-string slot is a real
        # possibility here: some source rosters have a reserve slot pointing
        # at a player id that doesn't exist anywhere else in the file, and
        # that's recorded as "" rather than dropped, to keep every other
        # slot's jersey number where it belongs. int("") would otherwise
        # crash the screen open.
        raw = [int(pid) for pid in lineup.get("players_id", []) if pid]
        pool = []
        for pid in raw:
            if pid in self.players and pid not in pool:
                pool.append(pid)
        pool += [pid for pid in self.players if pid not in pool]
        self.available = len(pool)
        self.assignment = {n: (pool[i] if i < len(pool) else None)
                           for i, n in enumerate(STARTERS + SUBSTITUTES)}

        self.roles = {k: self._to_int(v) for k, v in (lineup.get("roles") or {}).items()}
        self.set_plays = dict(lineup.get("set_plays") or {})
        self._roles_open = False
        # The shirt the open picker belongs to. Distinct from _last_slot,
        # which follows the mouse across the sheet and so must never be what
        # a pick is applied to.
        self._picker_slot = None

        self._build()
        self._refresh_all()

    @staticmethod
    def _to_int(value):
        try:
            return int(value)
        except (TypeError, ValueError):
            return None

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        short = self.available < SQUAD_SIZE
        right = (f"{self.available} / {SQUAD_SIZE} players — squad incomplete"
                 if short else f"{SQUAD_SIZE} players")
        root.addWidget(page_header("Squad", breadcrumb=f"{self.team_name} · {self.side}",
                                    right=right, on_back=self._on_back_clicked))

        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(60, 20, 60, 16)
        bl.setSpacing(24)

        bl.addWidget(self._build_sheet(), stretch=1)
        bl.addWidget(self._build_side_panel())
        root.addWidget(body, stretch=1)

        self.hintbar = HintBar()
        root.addWidget(self.hintbar)

        self.roles_panel = self._build_roles_panel()
        self.roles_panel.setParent(self)
        self.roles_panel.hide()
        # Slides in and out through the screen edge it rests against —
        # same motion as match setup's ADVANCED pane (ui/side_panel.py).
        self._roles_slide = SidePanelSlide(self.roles_panel, self._roles_rect)

        # Before the first _update_hints: which hints are shown depends on
        # whether the picker is open.
        self.picker = PlayerPickerPopup(self)
        self.picker.picked.connect(self._on_picker_pick)
        self.picker.hovered.connect(self._preview_from_popup)
        self.picker.closed.connect(self._on_picker_closed)
        self._update_hints()

    def _build_sheet(self):
        card = Card(stripe=self.tint)
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 16, 24, 16)
        v.setSpacing(6)
        v.addWidget(eyebrow_label("starting xv", color=self.tint, size=13))

        self.avatars = {}
        for row in SHEET_ROWS:
            hl = QHBoxLayout()
            hl.setSpacing(18)
            hl.addStretch(1)
            for number in row:
                av = SlotAvatar(number, self.tint)
                av.activated.connect(self._on_slot_activated)
                av.hovered.connect(self._on_slot_hovered)
                self.focus.register(av)
                self.avatars[number] = av
                hl.addWidget(av)
            hl.addStretch(1)
            v.addLayout(hl)

        v.addSpacing(4)
        rule = QWidget()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {BORDER};")
        v.addWidget(rule)
        v.addSpacing(6)

        v.addWidget(eyebrow_label("replacements", color=FG_SECONDARY, size=12))
        subs = QHBoxLayout()
        subs.setSpacing(8)
        self.sub_chips = {}
        for number in SUBSTITUTES:
            chip = SubChip(number, self.tint)
            chip.activated.connect(self._on_slot_activated)
            chip.hovered.connect(self._on_slot_hovered)
            self.focus.register(chip)
            self.sub_chips[number] = chip
            subs.addWidget(chip)
        v.addLayout(subs)
        return card

    def _build_side_panel(self):
        # Read-only: stats for whichever shirt was last touched. Selection
        # itself happens on the sheet — clicking a shirt opens the picker
        # right there, rather than routing through a control over here.
        card = Card()
        card.setFixedWidth(SIDE_PANEL_WIDTH)
        v = QVBoxLayout(card)
        v.setContentsMargins(SIDE_PANEL_MARGIN, 16, SIDE_PANEL_MARGIN, 16)
        v.setSpacing(10)

        self.slot_lbl = eyebrow_label("number 1", color=ACCENT, size=13)
        v.addWidget(self.slot_lbl)

        inner_w = SIDE_PANEL_WIDTH - 2 * SIDE_PANEL_MARGIN
        self.player_name_lbl = display_label("—", 26, QFont.Bold, track=0.6)
        self.player_name_lbl.setFixedWidth(inner_w)
        v.addWidget(self.player_name_lbl)
        self.player_pos_lbl = display_label("", 11, QFont.DemiBold, track=1.6,
                                            color=FG_SECONDARY)
        self.player_pos_lbl.setFixedWidth(inner_w)
        v.addWidget(self.player_pos_lbl)

        v.addSpacing(10)
        v.addWidget(eyebrow_label("attributes", color=FG_SECONDARY, size=12))
        self.stats = StatsPanel()
        v.addWidget(self.stats)

        v.addStretch(1)

        self.fit_lbl = display_label("", 11, QFont.DemiBold, track=1.2, color=FG_MUTED)
        v.addWidget(self.fit_lbl)

        self.roles_btn = StyledButton("ROLES / SET PLAYS", "neutral")
        self.roles_btn.setMinimumHeight(BTN_HEIGHT)
        self.roles_btn.clicked.connect(self.toggle_roles)
        self.focus.register(self.roles_btn)
        v.addWidget(self.roles_btn)

        self.clear_btn = StyledButton("CLEAR ALL", "danger")
        self.clear_btn.setMinimumHeight(BTN_HEIGHT)
        self.clear_btn.clicked.connect(self._clear_all)
        self.focus.register(self.clear_btn)
        v.addWidget(self.clear_btn)

        # Why SAVE is unavailable — filled by _update_save_state
        self.save_note = QLabel("")
        self.save_note.setWordWrap(True)
        self.save_note.setStyleSheet(f"color: {WARN}; background: transparent;")
        self.save_note.hide()
        v.addWidget(self.save_note)

        self.save_btn = StyledButton("SAVE SQUAD", "primary")
        self.save_btn.setMinimumHeight(BTN_HEIGHT)
        self.save_btn.clicked.connect(self._save)
        self.focus.register(self.save_btn)
        v.addWidget(self.save_btn)
        return card

    def _build_roles_panel(self):
        panel = Card()
        panel.setObjectName("rolesPanel")
        panel.setStyleSheet(f"QWidget#rolesPanel {{ background: {BG_PANEL};"
                            f" border-left: 3px solid {ACCENT}; }}")
        v = QVBoxLayout(panel)
        v.setContentsMargins(30, 24, 30, 24)
        v.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(display_label("Roles / set plays", 20, QFont.Bold, track=1.2))
        head.addStretch(1)
        close_btn = StyledButton("CLOSE", "ghost")
        close_btn.clicked.connect(self.toggle_roles)
        head.addWidget(close_btn)
        v.addLayout(head)

        self.role_rows = {}
        for key, label in ROLE_LABELS.items():
            row = SelectorRow(label, compact=True)
            row.changed.connect(lambda k=key: self._on_role_changed(k))
            self.focus.register(row)
            self.role_rows[key] = row
            v.addWidget(row)

        v.addSpacing(8)
        v.addWidget(eyebrow_label("set plays", color=FG_SECONDARY, size=12))
        self.set_play_rows = {}
        options = list(SET_PLAY_OPTIONS.items())
        for key, label in SET_PLAY_KEYS.items():
            row = SelectorRow(label, values=options, display=lambda t: t[1], compact=True)
            idx = next((i for i, (k, _) in enumerate(options)
                        if k == self.set_plays.get(key)), 0)
            row.set_index(idx)
            row.changed.connect(lambda k=key: self._on_set_play_changed(k))
            self.focus.register(row)
            self.set_play_rows[key] = row
            v.addWidget(row)

        v.addStretch(1)
        panel.setFixedWidth(ROLES_PANEL_W)
        return panel

    def _roles_rect(self):
        return QRect(self.width() - ROLES_PANEL_W, 0, ROLES_PANEL_W, self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_roles_slide"):
            self._roles_slide.sync_geometry()
        if hasattr(self, "picker") and self.picker.isVisible():
            self.picker.hide()   # anchor geometry is stale after a resize

    # ── state ────────────────────────────────────────────────────────────
    def _player(self, number):
        pid = self.assignment.get(number)
        return self.players.get(pid) if pid is not None else None

    def _current_slot(self):
        w = self.focusWidget()
        if isinstance(w, (SlotAvatar, SubChip)):
            return w.number
        return getattr(self, "_last_slot", 1)

    def _fits(self, player, number):
        accepted = ACCEPTED_POSITIONS.get(number)
        if not accepted or not player:
            return True
        return bool(accepted & {player.get("position1", ""), player.get("position2", ""),
                                 player.get("position3", "")})

    def _update_save_state(self):
        """An incomplete squad is never saved: the game needs all 22 shirts."""
        empty = sum(1 for n in STARTERS + SUBSTITUTES if not self.assignment.get(n))
        self.save_btn.setEnabled(empty == 0)
        if empty:
            self.save_note.setText(f"{empty} of {SQUAD_SIZE} shirts empty — fill them all to save.")
            self.save_note.show()
        else:
            self.save_note.hide()

    def _refresh_all(self):
        self._update_save_state()
        captain_pid = self.roles.get("captain")
        for number, av in self.avatars.items():
            pid = self.assignment.get(number)
            av.set_player(self.players.get(pid) if pid else None,
                          is_captain=(pid is not None and pid == captain_pid))
        for number, chip in self.sub_chips.items():
            pid = self.assignment.get(number)
            chip.set_player(self.players.get(pid) if pid else None)
        self._refresh_role_options()
        self._refresh_side_panel(self._current_slot())

    def _refresh_side_panel(self, number):
        """Hovering or clicking a shirt on the sheet: update which slot the
        panel refers to AND preview that slot's own occupant."""
        self._last_slot = number
        pos_key = POSITION_FOR_NUMBER.get(number)
        label = "number %d" % number
        if pos_key:
            label += " · " + POSITION_NAMES.get(pos_key, pos_key).lower()
        elif number in SUBSTITUTES:
            label += " · replacement"
        self.slot_lbl.setText(label.upper())
        self._show_player_preview(self._player(number), number)

    def _on_slot_hovered(self, number):
        """Sheet hover. Ignored while the picker is open: the popup stays
        anchored to the shirt it was opened for, so letting the cursor
        re-point the panel (and, before this, the pick itself) at whatever
        shirt it crossed on the way to the list is never what was meant."""
        if self.picker.isVisible():
            return
        self._refresh_side_panel(number)

    def _preview_from_popup(self, pid):
        """The picker's highlight moved — by mouse or by d-pad, they are the
        same event. Preview that player against the slot the picker is open
        for, without touching which slot is considered "current"."""
        self._show_player_preview(self.players.get(pid), self._picker_slot)
        self._update_hints()

    def _show_player_preview(self, player, fit_number):
        self.player_name_lbl.setText(_elide_for(self.player_name_lbl, _last_name(player)))
        self.player_pos_lbl.setText(_elide_for(self.player_pos_lbl, _all_positions(player)))
        self.stats.set_player(player)

        if player and not self._fits(player, fit_number):
            # Short enough to fit the fixed-width panel — the longer phrasing
            # elided to "...FOR THIS SHI".
            self.fit_lbl.setText("✗ OUT OF POSITION")
            self.fit_lbl.setStyleSheet(f"color: {ACCENT}; background: transparent;"
                                        f" font-family: '{FONT_DISPLAY}'; font-size: 11pt;"
                                        f" font-weight: 600;")
        else:
            self.fit_lbl.setText("")

    def _refresh_role_options(self):
        """Roles may only be held by a player in the starting XV."""
        if not hasattr(self, "role_rows"):
            return
        starters = [self.assignment[n] for n in STARTERS if self.assignment.get(n)]
        for key, row in self.role_rows.items():
            current = self.roles.get(key)
            idx = starters.index(current) if current in starters else 0
            row.set_values(starters, index=idx)
            row._display = lambda pid: _last_name(self.players.get(pid))
            if starters and current not in starters:
                self.roles[key] = starters[idx]

    # ── interaction ──────────────────────────────────────────────────────
    def _on_slot_activated(self, number):
        self._refresh_side_panel(number)
        self._open_picker(number)

    def _picker_entries(self, number):
        """The whole squad as [(pid, name, fits)], ranked so the default
        FITS view opens on the players worth considering first.

        Fit outranks assignment: a prop will never play 10, whereas moving a
        fitting player off the bench is routine."""
        current_pid = self.assignment.get(number)
        taken = {pid for n, pid in self.assignment.items()
                 if pid is not None and n != number}

        def rank(pid):
            if pid == current_pid:
                return 0
            fits = self._fits(self.players[pid], number)
            return (1 if fits else 3) + (1 if pid in taken else 0)

        pids = sorted(self.players, key=lambda pid: (rank(pid), _last_name(self.players[pid])))
        return [(pid, _last_name(self.players[pid]), self._fits(self.players[pid], number))
                for pid in pids]

    def _open_picker(self, number):
        anchor = self.avatars.get(number) or self.sub_chips.get(number)
        if anchor is None:
            return
        taken_by = {pid: n for n, pid in self.assignment.items()
                   if pid is not None and n != number}

        pos_key = POSITION_FOR_NUMBER.get(number)
        title = "NUMBER %d" % number
        if pos_key:
            title += " · " + POSITION_NAMES.get(pos_key, pos_key).upper()
        elif number in SUBSTITUTES:
            title += " · REPLACEMENT"

        self._picker_slot = number
        self.picker.open_for(title, self._picker_entries(number),
                             self.assignment.get(number), taken_by, anchor, self)
        self._update_hints()

    def _on_picker_pick(self, pid):
        number = self._picker_slot
        if number is None or pid is None or self.assignment.get(number) == pid:
            return
        # A player holds one shirt at a time, so this is a MOVE: the shirt he
        # came from is vacated rather than back-filled with whoever he
        # displaced. Loop rather than find-first, so a duplicated id in the
        # source lineup can't leave a stale second copy behind.
        for n, held in list(self.assignment.items()):
            if held == pid and n != number:
                self.assignment[n] = None
        self.assignment[number] = pid
        self._refresh_all()

    def _on_picker_closed(self):
        """Every exit funnels here — CONFIRM, BACK, a click outside, and the
        stale-anchor hide on resize — so the panel always falls back to the
        slot's real occupant instead of keeping the last candidate on show."""
        self._picker_slot = None
        self._refresh_side_panel(self._last_slot)
        self._update_hints()

    def _clear_all(self):
        self.assignment = {n: None for n in STARTERS + SUBSTITUTES}
        self.roles = {}
        self._refresh_all()

    def _on_role_changed(self, key):
        self.roles[key] = self.role_rows[key].current()
        self._refresh_all()

    def _on_set_play_changed(self, key):
        entry = self.set_play_rows[key].current()
        if entry:
            self.set_plays[key] = entry[0]

    def toggle_roles(self):
        self._roles_open = not self._roles_open
        self._roles_slide.set_open(self._roles_open)
        self._update_hints()

    def auto_fill(self):
        """Greedy best-fit: scarcest positions first, so specialists keep
        their shirt instead of an earlier slot taking them."""
        used = set()
        by_slot = {}
        order = sorted(STARTERS, key=lambda n: sum(
            1 for p in self.players.values() if self._fits(p, n)))
        for number in order:
            cands = [pid for pid, p in self.players.items()
                     if pid not in used and self._fits(p, number)]
            if not cands:
                continue
            best = max(cands, key=lambda pid: int(self.players[pid].get("attack", 0) or 0))
            by_slot[number] = best
            used.add(best)
        leftovers = [pid for pid in self.players if pid not in used]
        for number in STARTERS + SUBSTITUTES:
            if number in by_slot:
                self.assignment[number] = by_slot[number]
            else:
                self.assignment[number] = leftovers.pop(0) if leftovers else None
        self._refresh_all()

    def _save(self):
        players_id = [self.assignment.get(n) for n in STARTERS + SUBSTITUTES]
        if any(pid is None for pid in players_id):
            self._update_save_state()
            return
        lineup = {
            "players_id": [pid for pid in players_id if pid is not None],
            "roles": {k: v for k, v in self.roles.items() if v is not None},
            "set_plays": dict(self.set_plays),
        }
        self.on_confirm(lineup)

    def _on_back_clicked(self):
        """The header's mouse-clickable back button. Closing the roles
        panel or picker takes precedence — handled by their own BACK
        branches above this in keyPressEvent, and by the caller checking
        them before invoking this directly from the header click."""
        if self._roles_open:
            self.toggle_roles()
        elif self.picker.isVisible():
            self.picker.hide()
        elif self.on_discard:
            self.on_discard()

    # ── hints / keys ─────────────────────────────────────────────────────
    def _picker_verb(self):
        """What CONFIRM would do to the highlighted player, named exactly —
        "assign" and "move from 9" are different enough to be worth saying
        before the button is pressed."""
        pid = self.picker.highlighted_pid()
        if pid is None:
            return "—"
        if pid == self.assignment.get(self._picker_slot):
            return "keep"
        held = next((n for n, p in self.assignment.items()
                     if p == pid and n != self._picker_slot), None)
        return f"move from {held}" if held is not None else "assign"

    def _update_hints(self):
        if self.picker.isVisible():
            self.hintbar.set_hints([
                ("↕", "browse"), ("←→", "suggested / all"),
                ("A", self._picker_verb()), ("B", "cancel"),
            ])
        elif self._roles_open:
            self.hintbar.set_hints([("A", "change"), ("B", "close panel")])
        else:
            self.hintbar.set_hints([
                ("A", "pick player"), ("X", "auto-fill"), ("F", "roles & plays"),
                ("B", "back · discard"),
            ])

    def _picker_key(self, action):
        if action == Action.NAV_UP:
            self.picker.move_highlight(-1)
        elif action == Action.NAV_DOWN:
            self.picker.move_highlight(1)
        elif action == Action.NAV_LEFT:
            self.picker.cycle_mode(-1)
        elif action == Action.NAV_RIGHT:
            self.picker.cycle_mode(1)
        elif action == Action.TAB_PREV:
            self.picker.page_highlight(-1)
        elif action == Action.TAB_NEXT:
            self.picker.page_highlight(1)
        elif action == Action.CONFIRM:
            self.picker.activate()
        elif action == Action.BACK:
            self.picker.hide()

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        # An open picker owns the keyboard outright. Anything that fell
        # through would act on the sheet *behind* it — NAV moving focus off
        # the shirt the popup is still anchored to, X auto-filling the whole
        # squad, F sliding the roles panel over the top of it.
        if self.picker.isVisible():
            self._picker_key(action)
            event.accept()
            return
        if action == Action.ADVANCED:
            self.toggle_roles(); event.accept(); return
        if action == Action.ALT:
            self.auto_fill(); event.accept(); return
        if action == Action.BACK and self._roles_open:
            self.toggle_roles(); event.accept(); return
        if action == Action.BACK:
            self._on_back_clicked(); event.accept(); return
        if action == Action.CONFIRM:
            w = self.focusWidget()
            if isinstance(w, (SlotAvatar, SubChip)):
                self._on_slot_activated(w.number)
                event.accept()
                return
        if action in (Action.NAV_UP, Action.NAV_DOWN, Action.NAV_LEFT, Action.NAV_RIGHT):
            super().keyPressEvent(event)
            w = self.focusWidget()
            if isinstance(w, (SlotAvatar, SubChip)):
                self._refresh_side_panel(w.number)
            return
        super().keyPressEvent(event)
