"""
screens/tournament/squad.py — Team management for a human team: the
matchday 22 (15 + 7), captain and kickers, from the tournament squad.

Left: the 22 on a pitch, bench below — each token shows the player's
rating in that slot, ringed by state (fit / out of position / unavailable).
Right: the selected slot, the roles, and the squad sorted by how well each
player fits that slot, with the gain or loss against the current pick.

Pick a slot (arrows / click), A jumps to the squad list, A on a player puts
him there (a player already in the 22 swaps slots) and returns to the
pitch. Every change is saved at once.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.tournament import report, selection
from app.tournament.effects import MatchContext, base_ratings, effective_stats, is_available
from app.tournament.strength import SLOT_POSITIONS, position_fit, slot_rating
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, label_css, page_header
from ui.editor_kit import ChoiceField, FieldGrid, Note, compact_button
from ui.theme import (ACCENT, BG_BASE, BTN_HEIGHT, DANGER_LITE, FG_MUTED, FG_PRIMARY, FG_SECONDARY,
                      FG_TERTIARY, GREEN, WARN)

from .common import (DataTable, PixmapLabel, SectionTitle, Tag, YOU_TINT, clear_layout,
                     tournament_crest, transparent)
from .pitch import LineupPitch

POSITION_ABBR = {
    "loosehead_prop": "LP", "hooker": "HK", "tighthead_prop": "TP", "second_row": "LK",
    "blindside_flanker": "BF", "openside_flanker": "OF", "number_eight": "N8",
    "scrum_half": "SH", "fly_half": "FH", "centre": "CE", "winger": "WG", "fullback": "FB",
}


def _pos(p):
    return (p or "").replace("_", " ")


def _abbr(p):
    return POSITION_ABBR.get(p, _pos(p))


def rating_color(v):
    return GREEN if v >= 80 else (FG_PRIMARY if v >= 65 else (WARN if v >= 50 else DANGER_LITE))


class TournamentSquadScreen(Screen):
    def __init__(self, on_back, embedded=False):
        """`embedded`: shown inside the dashboard's Manage your team tab —
        no page header, DONE button or hint bar of its own."""
        super().__init__(on_back=on_back)
        self.embedded = embedded
        self.session = None
        self.team_id = None
        self.ds = None
        self._slot = 0
        self._build()

    @property
    def t(self):
        return self.session.t

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header_holder = QVBoxLayout()
        root.addLayout(self.header_holder)

        body = QWidget()
        body.setObjectName("squadBody")
        body.setStyleSheet(f"QWidget#squadBody {{ background: {BG_BASE}; }}")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(*((0, 0, 0, 0) if self.embedded else (50, 14, 50, 12)))
        bv.setSpacing(12)

        # team bar: crest, name, next match, team picker (two humans)
        bar = QHBoxLayout()
        bar.setSpacing(14)
        self.crest = PixmapLabel(52)
        bar.addWidget(self.crest)
        tv = QVBoxLayout()
        tv.setSpacing(0)
        self.team_name = display_label("", 20, QFont.Bold, track=1.0, color=YOU_TINT)
        tv.addWidget(self.team_name)
        self.next_label = eyebrow_label("", color=FG_TERTIARY, size=10)
        tv.addWidget(self.next_label)
        bar.addLayout(tv, stretch=1)
        self.team = ChoiceField("team", allow_blank=False)
        self.team.setFixedWidth(260)
        self.team.edited.connect(lambda tid: self._switch(tid))
        self.focus.register(self.team)
        bar.addWidget(self.team)
        self.auto_btn = compact_button("AUTO PICK", "neutral", height=BTN_HEIGHT)
        self.auto_btn.clicked.connect(self._auto)
        self.done_btn = compact_button("DONE", "primary", height=BTN_HEIGHT)
        self.done_btn.setMinimumWidth(150)
        self.done_btn.clicked.connect(lambda: self.on_back_cb())
        bar.addWidget(self.auto_btn)
        bar.addWidget(self.done_btn)
        self.done_btn.setVisible(not self.embedded)
        bv.addLayout(bar)

        cols = QHBoxLayout()
        cols.setSpacing(22)
        left = transparent(QWidget(), "squadLeft")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(8)
        self.xv_title = SectionTitle("matchday squad · 15 + 7")
        lv.addWidget(self.xv_title)
        self.pitch = LineupPitch(interactive=True, bench=True)
        self.pitch.slot_selected.connect(self._on_slot)
        self.pitch.slot_activated.connect(lambda _i: self._to_pool())
        self.focus.register(self.pitch)
        lv.addWidget(self.pitch, stretch=1)
        legend = QHBoxLayout()
        legend.setSpacing(12)
        for text, color in (("fit", FG_SECONDARY), ("out of position", WARN), ("unavailable", DANGER_LITE)):
            legend.addWidget(Tag(text, color, filled=False))
        legend.addStretch(1)
        lv.addLayout(legend)
        cols.addWidget(left, stretch=5)

        right = transparent(QWidget(), "squadRight")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(10)
        # selected slot
        self.slot_card = Card(stripe=ACCENT, translucent=True)
        sv = QHBoxLayout(self.slot_card)
        sv.setContentsMargins(20, 12, 20, 12)
        sv.setSpacing(14)
        self.slot_num = display_label("1", 34, QFont.Bold, track=0.5, color=ACCENT)
        sv.addWidget(self.slot_num)
        stv = QVBoxLayout()
        stv.setSpacing(0)
        self.slot_pos = eyebrow_label("", color=FG_TERTIARY, size=11)
        stv.addWidget(self.slot_pos)
        self.slot_player = display_label("", 18, QFont.Bold, track=0.6)
        stv.addWidget(self.slot_player)
        self.slot_status = Note("", color=FG_TERTIARY)
        stv.addWidget(self.slot_status)
        sv.addLayout(stv, stretch=1)
        self.slot_rating = display_label("", 30, QFont.Bold, track=0.5)
        sv.addWidget(self.slot_rating)
        rv.addWidget(self.slot_card)

        roles = FieldGrid(columns=3)
        self.captain = ChoiceField("captain", allow_blank=False)
        self.kicker = ChoiceField("goal kicker", allow_blank=False)
        self.punter = ChoiceField("tactical kicker", allow_blank=False)
        for f, role in ((self.captain, ("captain",)), (self.kicker, ("longGK", "shortGK")),
                        (self.punter, ("longPunt", "shortPunt"))):
            f.edited.connect(lambda v, r=role: self._set_role(r, v))
            roles.add(f)
            self.focus.register(f)
        rv.addWidget(roles)

        self.pool_title = SectionTitle("squad")
        rv.addWidget(self.pool_title)
        self.pool = DataTable(["Player", "Pos", "Rating", "±", "Status", "Apps"], stretch_col=0,
                              widths={1: 92, 2: 70, 3: 56, 4: 150, 5: 52})
        self.pool.activated_row.connect(self._assign)
        self.focus.register(self.pool)
        rv.addWidget(self.pool, stretch=1)
        self.issues = Note("", color=WARN)
        rv.addWidget(self.issues)
        cols.addWidget(right, stretch=6)
        bv.addLayout(cols, stretch=1)
        root.addWidget(body, stretch=1)

        self.hints = HintBar()
        self.hints.set_hints([("A", "pick slot / place player"), ("X", "auto pick"), ("B", "done")])
        root.addWidget(self.hints)
        self.hints.setVisible(not self.embedded)

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
                                                     breadcrumb=f"tournament · {self.t.name}",
                                                     on_back=self.on_back_cb))
        self.crest.set_pixmap(tournament_crest(self.ds, self.t, team_id, 52))
        self.team_name.setText(self.t.team_name(team_id).upper())
        nxt = next((f for f in sorted(self.t.fixtures, key=lambda f: f.day)
                    if not f.played and f.involves(team_id)), None)
        self.next_label.setText(
            f"next: {report.fixture_caption(self.t, nxt)}".upper() if nxt
            else "no match left to play".upper())
        entry = self.t.teams[team_id]
        if not entry.selection.get("players") or len(entry.selection["players"]) < 22:
            self.session.auto_select(team_id)
        self._slot = 0
        self.pitch.set_current(0)
        self.refresh()

    def on_show(self):
        super().on_show()
        self.pitch.setFocus()

    # ── data ─────────────────────────────────────────────────────────────
    def _sel(self):
        return self.t.teams[self.team_id].selection

    def _positions(self):
        pos = list(self._sel().get("positions") or [])
        return pos + SLOT_POSITIONS[len(pos):]

    def _ratings(self, p, pos, slot):
        ctx = MatchContext(team_id=self.team_id, position=pos, slot=slot + 1)
        eff = slot_rating(effective_stats(self.t, p, ctx), pos, p.positions)
        base = slot_rating(base_ratings(p), pos, p.positions)
        return eff, base

    def refresh(self):
        t = self.t
        sel = self._sel()
        positions = self._positions()
        roles = sel.get("roles", {})
        slots = []
        starters_rating = []
        for i, pos in enumerate(positions[:22]):
            pids = sel.get("players", [])
            pid = pids[i] if i < len(pids) else None
            p = t.players.get(pid)
            slot = {"number": i + 1, "sub": _abbr(pos)}
            if not p:
                slot.update({"name": "—", "faded": True, "ring": FG_MUTED})
            else:
                eff, _base = self._ratings(p, pos, i)
                fit = position_fit(p.positions, pos)
                ring = DANGER_LITE if not is_available(t, p) else (WARN if fit < 0.9 else
                                                                    (YOU_TINT if i < 15 else FG_SECONDARY))
                marks = [mark for key, mark in (("captain", "C"), ("longGK", "K")) if roles.get(key) == pid]
                sub = " · ".join([_abbr(pos)] + marks)
                slot.update({"name": p.name, "value": f"{eff:.0f}", "ring": ring, "sub": sub,
                             "value_color": rating_color(eff)})
                if i < 15:
                    starters_rating.append(eff)
            slots.append(slot)
        self.pitch.set_slots(slots)
        if starters_rating:
            self.xv_title.set_right(f"xv average {sum(starters_rating) / len(starters_rating):.0f}")

        starters = [pid for pid in sel.get("players", [])[:15] if pid in t.players]
        for f, key in ((self.captain, "captain"), (self.kicker, "longGK"), (self.punter, "longPunt")):
            f.display = t.player_name
            f.set_options(starters)
            f.set_value(roles.get(key, ""))
        errors, warnings = selection.validate(t, self.team_id, sel)
        self.issues.setText(("⚠  " + "; ".join(errors + warnings)) if errors or warnings else "")
        self.issues.setStyleSheet(self.issues.styleSheet().replace(WARN, DANGER_LITE) if errors
                                  else self.issues.styleSheet().replace(DANGER_LITE, WARN))
        self.issues.setVisible(bool(errors or warnings))
        self._refresh_slot()

    def _refresh_slot(self):
        t = self.t
        slot = self._slot
        positions = self._positions()
        pos = positions[slot] if slot < len(positions) else SLOT_POSITIONS[0]
        sel = self._sel().get("players", [])
        current = t.players.get(sel[slot]) if slot < len(sel) else None
        self.slot_num.setText(str(slot + 1))
        self.slot_pos.setText(f"{_pos(pos)} · {'starter' if slot < 15 else 'replacement'}".upper())
        cur_eff = None
        if current:
            cur_eff, base = self._ratings(current, pos, slot)
            self.slot_player.setText(current.name.upper())
            status = report.player_status(t, current)
            fit = position_fit(current.positions, pos)
            extra = "" if fit >= 0.95 else f" · plays {_pos(current.position)}"
            self.slot_status.setText(status + extra + (f" · base {base:.0f}" if round(base) != round(cur_eff) else ""))
            self.slot_rating.setText(f"{cur_eff:.0f}")
            self.slot_rating.setStyleSheet(label_css(30, QFont.Bold, rating_color(cur_eff)))
        else:
            self.slot_player.setText("EMPTY")
            self.slot_status.setText("")
            self.slot_rating.setText("")
        self.pool_title.set_title(f"best for {_pos(pos)}")

        entry = t.teams[self.team_id]
        apps = t.stats.get("players", {})
        rows, keys, tint = [], [], {}
        scored = []
        for pid in entry.squad:
            p = t.players[pid]
            eff, _b = self._ratings(p, pos, slot)
            scored.append((eff, pid, p))
        scored.sort(key=lambda x: (not is_available(t, x[2]), -x[0]))
        for i, (eff, pid, p) in enumerate(scored):
            where = sel.index(pid) + 1 if pid in sel else None
            available = is_available(t, p)
            delta = None if cur_eff is None or pid == (current.pid if current else None) else eff - cur_eff
            rows.append([
                {"text": p.name + (f"   #{where}" if where else ""),
                 "color": DANGER_LITE if not available else (FG_PRIMARY if where else FG_SECONDARY),
                 "bold": where is not None and where <= 15},
                {"text": " ".join(_abbr(x) for x in p.positions), "color": FG_TERTIARY},
                {"text": f"{eff:.0f}", "color": rating_color(eff), "bold": True, "align": Qt.AlignHCenter},
                {"text": "" if delta is None else f"{delta:+.0f}", "align": Qt.AlignHCenter,
                 "color": GREEN if (delta or 0) > 0 else (FG_TERTIARY if not delta else DANGER_LITE)},
                {"text": report.player_status(t, p), "color": DANGER_LITE if not available else FG_TERTIARY},
                {"text": apps.get(pid, {}).get("apps", 0), "align": Qt.AlignHCenter, "color": FG_TERTIARY},
            ])
            keys.append(pid)
            if current and pid == current.pid:
                tint[i] = ACCENT
        self.pool.set_rows(rows, keys=keys, tint=tint)

    # ── edits ────────────────────────────────────────────────────────────
    def _on_slot(self, i):
        self._slot = i
        self._refresh_slot()

    def _to_pool(self):
        self.pool.setFocus()
        if self.pool.currentRow() < 0 and self.pool.rowCount():
            self.pool.selectRow(0)

    def keyPressEvent(self, event):
        if KEYMAP.get(event.key()) == Action.ALT:
            self._auto()
            event.accept()
            return
        super().keyPressEvent(event)

    def _commit(self, players, roles=None):
        sel = self._sel()
        self.session.set_selection(self.team_id, players, self._positions(), roles or sel.get("roles"))
        self.refresh()

    def _assign(self, row):
        pid = self.pool.keys[row]
        slot = self._slot
        players = list(self._sel().get("players", []))
        if slot >= len(players):
            return
        if pid in players:
            j = players.index(pid)
            players[j], players[slot] = players[slot], players[j]
        else:
            players[slot] = pid
        self._commit(players)
        self.pitch.set_current(slot)
        self.pitch.setFocus()

    def _set_role(self, keys, pid):
        roles = dict(self._sel().get("roles", {}))
        for k in keys:
            roles[k] = pid
        self._commit(list(self._sel().get("players", [])), roles)

    def _auto(self):
        self.session.auto_select(self.team_id)
        self.refresh()
