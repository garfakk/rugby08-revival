"""
screens/tournament/squad.py — Team management for a human team: the
matchday 22 (15 + 7), captain and kickers, from the tournament squad.

Pick a slot on the left, then a player on the right (Enter / double-click)
to put him there; a player already in the 22 swaps slots. Every change is
saved at once. Ratings show the player's value in that slot with today's
modifiers (fatigue...), base value in brackets when they differ.
"""
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.screen_base import Screen
from app.tournament import report, selection
from app.tournament.effects import MatchContext, base_ratings, effective_stats, is_available
from app.tournament.strength import SLOT_POSITIONS, position_fit, slot_rating
from ui.broadcast import HintBar, page_header
from ui.editor_kit import ChoiceField, FieldGrid, Note, compact_button
from ui.theme import BG_BASE, DANGER_LITE, FG_TERTIARY, GREEN, HOME_TINT, WARN

from .common import DataTable, clear_layout, section


POSITION_ABBR = {
    "loosehead_prop": "LP", "hooker": "HK", "tighthead_prop": "TP", "second_row": "LK",
    "blindside_flanker": "BF", "openside_flanker": "OF", "number_eight": "N8",
    "scrum_half": "SH", "fly_half": "FH", "centre": "CE", "winger": "WG", "fullback": "FB",
}


def _pos(p):
    return (p or "").replace("_", " ")


def _abbr(p):
    return POSITION_ABBR.get(p, _pos(p))


class TournamentSquadScreen(Screen):
    def __init__(self, on_back):
        super().__init__(on_back=on_back)
        self.session = None
        self.team_id = None
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
        bv.setContentsMargins(50, 14, 50, 10)
        bv.setSpacing(10)

        top = FieldGrid(columns=4)
        self.team = ChoiceField("team", allow_blank=False)
        self.team.edited.connect(lambda tid: self._switch(tid))
        self.captain = ChoiceField("captain", allow_blank=False)
        self.kicker = ChoiceField("goal kicker", allow_blank=False)
        self.punter = ChoiceField("tactical kicker", allow_blank=False)
        for f, role in ((self.captain, ("captain",)), (self.kicker, ("longGK", "shortGK")),
                        (self.punter, ("longPunt", "shortPunt"))):
            f.edited.connect(lambda v, r=role: self._set_role(r, v))
        for f in (self.team, self.captain, self.kicker, self.punter):
            top.add(f)
            self.focus.register(f)
        bv.addWidget(top)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        w, lv = section("matchday 22")
        self.lineup = DataTable(["#", "Slot", "Player", "Rating", "Status"], stretch_col=2)
        self.lineup.activated_row.connect(lambda _r: self.pool.setFocus())
        self.focus.register(self.lineup)
        lv.addWidget(self.lineup, stretch=1)
        cols.addWidget(w, stretch=1)
        w, rv = section("squad")
        self.pool = DataTable(["Player", "Pos", "In slot", "Status", "Apps"], stretch_col=0)
        self.pool.activated_row.connect(self._assign)
        self.focus.register(self.pool)
        rv.addWidget(self.pool, stretch=1)
        cols.addWidget(w, stretch=1)
        self.lineup.itemSelectionChanged.connect(self._refresh_pool)
        bv.addLayout(cols, stretch=1)

        self.issues = Note("", color=WARN)
        bv.addWidget(self.issues)
        row = QHBoxLayout()
        row.addWidget(Note("Pick a slot, then Enter on a squad player to put him there.", color=FG_TERTIARY))
        row.addStretch(1)
        self.auto_btn = compact_button("AUTO PICK", "neutral")
        self.auto_btn.clicked.connect(self._auto)
        self.done_btn = compact_button("DONE", "primary")
        self.done_btn.clicked.connect(lambda: self.on_back_cb())
        for b in (self.auto_btn, self.done_btn):
            row.addWidget(b)
            self.focus.register(b)
        bv.addLayout(row)
        root.addWidget(body, stretch=1)

        hints = HintBar()
        hints.set_hints([("A", "select / place"), ("B", "back")])
        root.addWidget(hints)

    # ── entry ────────────────────────────────────────────────────────────
    def set_team(self, session, team_id):
        self.session = session
        humans = [e.team_id for e in session.t.human_teams()]
        self.team.display = self.t.team_name
        self.team.set_options(humans)
        self._switch(team_id or (humans[0] if humans else None))

    def _switch(self, team_id):
        self.team_id = team_id
        self.team.set_value(team_id)
        clear_layout(self.header_holder)
        self.header_holder.addWidget(page_header(f"Squad · {self.t.team_name(team_id)}",
                                                 breadcrumb=f"tournament · {self.t.name}",
                                                 on_back=self.on_back_cb))
        entry = self.t.teams[team_id]
        if not entry.selection.get("players") or len(entry.selection["players"]) < 22:
            self.session.auto_select(team_id)
        self.refresh()
        self.lineup.selectRow(0)

    # ── data ─────────────────────────────────────────────────────────────
    def _sel(self):
        return self.t.teams[self.team_id].selection

    def _positions(self):
        sel = self._sel()
        pos = list(sel.get("positions") or [])
        return pos + SLOT_POSITIONS[len(pos):]

    def _rating(self, p, pos, slot):
        ctx = MatchContext(team_id=self.team_id, position=pos, slot=slot + 1)
        eff = slot_rating(effective_stats(self.t, p, ctx), pos, p.positions)
        base = slot_rating(base_ratings(p), pos, p.positions)
        return f"{eff:.0f}" if round(eff) == round(base) else f"{eff:.0f} ({base:.0f})"

    def refresh(self):
        t = self.t
        sel = self._sel()
        positions = self._positions()
        rows, colors = [], {}
        for i, pid in enumerate(sel.get("players", [])):
            p = t.players.get(pid)
            pos = positions[i]
            if not p:
                rows.append([i + 1, _pos(pos), "—", "", ""])
                continue
            status = report.player_status(t, p)
            fit = position_fit(p.positions, pos)
            rows.append([i + 1, _pos(pos), p.name + ("" if fit >= 0.95 else f"  ({_pos(p.position)})"),
                         self._rating(p, pos, i), status])
            if not is_available(t, p):
                colors[i] = DANGER_LITE
            elif fit < 0.9:
                colors[i] = WARN
            elif i >= 15:
                colors[i] = FG_TERTIARY
        self.lineup.set_rows(rows, keys=list(range(len(rows))), colors=colors)

        starters = [pid for pid in sel.get("players", [])[:15] if pid in t.players]
        roles = sel.get("roles", {})
        for f, key in ((self.captain, "captain"), (self.kicker, "longGK"), (self.punter, "longPunt")):
            f.display = t.player_name
            f.set_options(starters)
            f.set_value(roles.get(key, ""))
        errors, warnings = selection.validate(t, self.team_id, sel)
        text = "; ".join(errors + warnings)
        self.issues.setText(text)
        self.issues.setStyleSheet(self.issues.styleSheet().replace(WARN, DANGER_LITE) if errors
                                  else self.issues.styleSheet().replace(DANGER_LITE, WARN))
        self._refresh_pool()

    def _refresh_pool(self):
        t = self.t
        slot = self.lineup.current_key()
        slot = 0 if slot is None else slot
        pos = self._positions()[slot] if slot < len(self._positions()) else SLOT_POSITIONS[0]
        sel = self._sel().get("players", [])
        entry = t.teams[self.team_id]
        apps = t.stats.get("players", {})
        rows, colors, keys = [], {}, []
        squad = sorted(entry.squad, key=lambda pid: -slot_rating(
            effective_stats(t, t.players[pid]), pos, t.players[pid].positions))
        for i, pid in enumerate(squad):
            p = t.players[pid]
            where = f" [#{sel.index(pid) + 1}]" if pid in sel else ""
            rows.append([p.name + where, " ".join(_abbr(x) for x in p.positions),
                         self._rating(p, pos, slot), report.player_status(t, p),
                         apps.get(pid, {}).get("apps", 0)])
            keys.append(pid)
            if not is_available(t, p):
                colors[i] = DANGER_LITE
            elif pid in sel:
                colors[i] = HOME_TINT if sel.index(pid) < 15 else GREEN
        self.pool.set_rows(rows, keys=keys, colors=colors)

    # ── edits ────────────────────────────────────────────────────────────
    def _commit(self, players, roles=None):
        sel = self._sel()
        self.session.set_selection(self.team_id, players, self._positions(), roles or sel.get("roles"))
        self.refresh()

    def _assign(self, row):
        pid = self.pool.keys[row]
        slot = self.lineup.current_key()
        if slot is None:
            return
        players = list(self._sel().get("players", []))
        if pid in players:
            j = players.index(pid)
            players[j], players[slot] = players[slot], players[j]
        else:
            players[slot] = pid
        self._commit(players)
        self.lineup.selectRow(slot)

    def _set_role(self, keys, pid):
        roles = dict(self._sel().get("roles", {}))
        for k in keys:
            roles[k] = pid
        self._commit(list(self._sel().get("players", [])), roles)

    def _auto(self):
        self.session.auto_select(self.team_id)
        self.refresh()
