"""
screens/roster_import.py — import a Rugby 08 roster (.ros / .rdf)
===================================================================
A four-step wizard; nothing is written before the last step.

  1. File & options  — which roster, target season, birth-year correction,
                       which field groups to import, squad size, target file
  2. Teams           — tick teams, name them (rosters carry no names), link
                       each to an existing team or create a new one
  3. Players         — every player of the chosen squads with a suggested
                       match: update an existing player, create, or skip
  4. Review          — counts, files that will change, warnings → Import
"""
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QStackedWidget, QFileDialog, QApplication, QLineEdit,
)
from PyQt5.QtGui import QFont
from PyQt5.QtCore import Qt, QTimer

from app.screen_base import Screen
from app.input import Action, KEYMAP
from app.game_data import TEAM_TYPES, SaveError
from app.ratings import position_overall
from app.roster_import.reader import read_roster, RosterError, TENDENCIES
from app.roster_import import plan as P
from ui.broadcast import page_header, display_label
from ui.dropdown import PopupList
from ui.editor_kit import (
    SectionCard, FieldGrid, TextField, NumberField, ChoiceField, SegmentField, Note,
    TabStrip, compact_button, TabPage,
)
from ui.form import SearchList
from ui.team_sheet import POSITION_SHORT, POSITION_NAMES
from ui.broadcast import HintBar
from ui.theme import (
    BG_BASE, BG_PANEL, BORDER, ACCENT, GREEN, WARN, INFO, DANGER_LITE, FG_PRIMARY,
    FG_SECONDARY, FG_TERTIARY, FONT_DISPLAY, T_LABEL, T_TITLE, T_VALUE, BTN_HEIGHT_SM,
)

STEP_FILE, STEP_TEAMS, STEP_PLAYERS, STEP_REVIEW = range(4)
DECISION_TAG = {P.CREATE: ("NEW", INFO), P.SKIP: ("SKIP", FG_TERTIARY)}


def _pos(p):
    return POSITION_SHORT.get(p, "—") if p else "—"


class RosterImportScreen(Screen):
    def __init__(self, ds, on_back, on_open_team=None, on_open_player=None):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_open_team = on_open_team
        self.on_open_player = on_open_player
        self.plan = None
        self.roster = None
        self._build()
        self._go(STEP_FILE)

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Import roster", breadcrumb="rugby 08 .ros / .rdf",
                                   on_back=self.request_back))
        body = QWidget()
        body.setObjectName("importBody")
        body.setStyleSheet(f"QWidget#importBody {{ background: {BG_BASE}; }}")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(40, 12, 40, 8)
        bv.setSpacing(0)
        self.steps = TabStrip(["1  File & options", "2  Teams", "3  Players", "4  Review"])
        self.steps.changed.connect(self._on_step_clicked)
        bv.addWidget(self.steps)
        self.stack = QStackedWidget()
        self.pages = [TabPage() for _ in range(4)]
        for page in self.pages:
            self.stack.addWidget(page)
        bv.addWidget(self.stack, stretch=1)
        root.addWidget(body, stretch=1)

        foot = QWidget()
        foot.setObjectName("importFoot")
        foot.setAttribute(Qt.WA_StyledBackground, True)
        foot.setStyleSheet(f"QWidget#importFoot {{ background: {BG_PANEL}; border-top: 1px solid {BORDER}; }}")
        foot.setFixedHeight(56)
        fh = QHBoxLayout(foot)
        fh.setContentsMargins(0, 0, 20, 0)
        self.hints = HintBar(framed=False)
        fh.addWidget(self.hints, stretch=2)
        self.status = display_label("", T_LABEL, QFont.DemiBold, track=0.4, color=FG_SECONDARY,
                                    upper=False)
        fh.addWidget(self.status, stretch=3)
        self.back_btn = compact_button("‹ BACK")
        self.back_btn.clicked.connect(self.request_back)
        self.next_btn = compact_button("NEXT ›", "primary")
        self.next_btn.setMinimumWidth(160)
        self.next_btn.clicked.connect(self.next_step)
        fh.addWidget(self.back_btn)
        fh.addWidget(self.next_btn)
        root.addWidget(foot)
        for b in (self.back_btn, self.next_btn):
            self.focus.register(b)

        self._build_file_page(self.pages[STEP_FILE].layout_)
        self._build_teams_page(self.pages[STEP_TEAMS].layout_)
        self._build_players_page(self.pages[STEP_PLAYERS].layout_)
        self._build_review_page(self.pages[STEP_REVIEW].layout_)

    def _reg(self, *widgets):
        for w in widgets:
            self.focus.register(w)
        return widgets[0] if len(widgets) == 1 else widgets

    # ── step 1 ───────────────────────────────────────────────────────────
    def _build_file_page(self, lay):
        row = QHBoxLayout()
        row.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)

        fcard = SectionCard("roster file")
        frow = QHBoxLayout()
        self.path = self._reg(TextField("File"))
        self.path.edited.connect(lambda v: self.load_file(v))
        frow.addWidget(self.path, stretch=1)
        browse = self._reg(compact_button("BROWSE…", height=40))
        browse.clicked.connect(self._browse)
        frow.addWidget(browse)
        fcard.add_layout(frow)
        self.file_summary = Note("Choose a .ros saved roster (community patches) or a raw .rdf "
                                 "roster file.", color=FG_SECONDARY, size=T_LABEL)
        fcard.add(self.file_summary)
        left.addWidget(fcard)

        ocard = SectionCard("how to import")
        g = FieldGrid(columns=1)
        self.season = self._reg(NumberField("Target season", 1900, 2100, allow_blank=False))
        self.season.set_value("2026")
        self.season.edited.connect(self._on_options)
        g.add(self.season)
        self.offset = self._reg(NumberField("Birth-year correction", 0, 40, allow_blank=False))
        self.offset.set_value("0")
        self.offset.edited.connect(self._on_options)
        g.add(self.offset)
        self.squad_size = self._reg(SegmentField("Squad size", ["22", "30"],
                                                 display=lambda v: f"first {v}"))
        self.squad_size.set_value("22")
        self.squad_size.edited.connect(self._on_options)
        g.add(self.squad_size)
        self.scope = self._reg(SegmentField("Players", ["squads", "all"],
                                            display=lambda v: {"squads": "of the chosen squads",
                                                               "all": "every player in the file"}[v]))
        self.scope.set_value("squads")
        self.scope.edited.connect(self._on_options)
        g.add(self.scope)
        self.target = self._reg(ChoiceField("New players go into", allow_blank=False,
                                            display=lambda p: os.path.basename(p)))
        self.target.edited.connect(self._on_options)
        g.add(self.target)
        self.star = self._reg(SegmentField("Star marker “^”", ["keep", "remove"],
                                           display=lambda v: f"{v} in names"))
        self.star.set_value("keep")
        self.star.edited.connect(self._on_options)
        g.add(self.star)
        ocard.add(g)
        left.addWidget(ocard)
        left.addStretch(1)
        row.addLayout(left, stretch=3)

        gcard = SectionCard("what to import")
        gg = FieldGrid(columns=1, v_spacing=3)
        self.group_fields = {}
        for key, label, on in P.GROUPS:
            f = self._reg(SegmentField(label, ["yes", "no"]))
            f.setFixedHeight(36)
            f.set_value("yes" if on else "no")
            f.edited.connect(self._on_options)
            gg.add(f)
            self.group_fields[key] = f
        gg.align_labels(cap=330)
        gcard.add(gg)
        gcard.v.addStretch(1)
        row.addWidget(gcard, stretch=2)
        lay.addLayout(row)

    def _browse(self):
        start = os.path.dirname(self.path.value()) if self.path.value() else os.path.expanduser("~")
        path, _ = QFileDialog.getOpenFileName(self, "Rugby 08 roster", start,
                                              "Rugby 08 roster (*.ros *.rdf);;All files (*)")
        if path:
            self.path.set_value(path)
            self.load_file(path)

    def load_file(self, path):
        path = (path or "").strip()
        if not path:
            return
        try:
            roster = read_roster(path)
        except RosterError as e:
            self.file_summary.setText(f"Could not read it: {e}")
            self.set_status(str(e), DANGER_LITE)
            return
        self.roster = roster
        season = self.season.value() or "2026"
        self.plan = P.ImportPlan(roster, self.ds, season)
        self.offset.set_value(str(self.plan.birth_offset))
        files = self.ds.players_files()
        self.target.set_options(files)
        self.target.set_value(self.plan.players_file)
        in_squads = {rid for t in roster["teams"].values() for rid in t["squad"]}
        multi = sum(1 for rid in in_squads
                    if sum(rid in t["squad"] for t in roster["teams"].values()) > 1)
        self.file_summary.setText(
            f"{'Saved roster (.ros)' if roster['kind'] == 'ros' else 'Raw roster (.rdf)'} · "
            f"{len(roster['players'])} players · {len(roster['teams'])} teams with a squad\n"
            f"{multi} players are in more than one squad (club and country), "
            f"{sum(1 for rid in roster['players'] if rid not in in_squads)} are in none.")
        self._on_options()
        self._refresh_teams()
        self.set_status(f"Read {os.path.basename(path)}", GREEN)

    def _on_options(self, *_):
        if self.plan is None:
            return
        season = self.season.value() or self.plan.season
        offset_changed = self.offset.as_int() != self.plan.birth_offset
        self.plan.season = season
        self.plan.birth_offset = self.offset.as_int() or 0
        self.plan.squad_size = int(self.squad_size.value() or 22)
        self.plan.scope = self.scope.value() or "squads"
        self.plan.players_file = self.target.value()
        self.plan.strip_star = self.star.value() == "remove"
        self.plan.groups = {k for k, f in self.group_fields.items() if f.value() == "yes"}
        if offset_changed:
            self.plan.players = {}
            self.plan.rematch()

    # ── step 2 ───────────────────────────────────────────────────────────
    def _build_teams_page(self, lay):
        row = QHBoxLayout()
        row.setSpacing(14)
        lcol = QVBoxLayout()
        bar = QHBoxLayout()
        for text, fn in (("ALL", lambda: self._include_all(True)),
                         ("NONE", lambda: self._include_all(False)),
                         ("LINKED ONLY", self._include_linked)):
            b = self._reg(compact_button(text))
            b.clicked.connect(fn)
            bar.addWidget(b)
        lcol.addLayout(bar)
        self.team_list = self._reg(SearchList("filter teams"))
        self.team_list.setFixedWidth(360)
        self.team_list.highlighted.connect(self._show_team)
        self.team_list.activated.connect(self._toggle_team)
        lcol.addWidget(self.team_list, stretch=1)
        self.team_count = Note("", color=FG_TERTIARY)
        lcol.addWidget(self.team_count)
        row.addLayout(lcol)

        card = SectionCard("team")
        self.team_title = card.title_lbl
        g = FieldGrid(columns=1)
        self.t_include = self._reg(SegmentField("Import this team", ["yes", "no"]))
        self.t_include.edited.connect(lambda v: self._team_set("include", v == "yes"))
        g.add(self.t_include)
        self.t_name = self._reg(TextField("Name"))
        self.t_name.edited.connect(lambda v: self._team_set("name", v))
        g.add(self.t_name)
        self.t_link = self._reg(ChoiceField("Into", allow_blank=False))
        self.t_link.display = lambda v: ("New team" if v == "new" else
                                         f"Existing: {self._existing_name(v)}")
        self.t_link.edited.connect(lambda v: self._team_set("link", v))
        g.add(self.t_link)
        self.t_type = self._reg(SegmentField("Type", TEAM_TYPES))
        self.t_type.edited.connect(lambda v: self._team_set("type", v))
        g.add(self.t_type)
        self.t_category = self._reg(ChoiceField("Category", allow_blank=True))
        self.t_category.edited.connect(lambda v: self._team_set("category", v))
        g.add(self.t_category)
        card.add(g)
        self.t_link_note = Note("", color=FG_SECONDARY, size=T_LABEL)
        card.add(self.t_link_note)
        self.t_squad = Note("", color=FG_PRIMARY, size=T_LABEL)
        card.add(self.t_squad)
        card.v.addStretch(1)
        row.addWidget(card, stretch=1)
        lay.addLayout(row)

    def _existing_name(self, tid):
        seasons = self.ds.teams.get(tid) or {}
        latest = sorted(seasons)[-1] if seasons else None
        return (seasons.get(latest) or {}).get("name", tid)

    def _refresh_teams(self, keep=None):
        if self.plan is None:
            return
        items, search = [], []
        for tid, c in sorted(self.plan.teams.items(), key=lambda kv: kv[1].name.lower()):
            link = "NEW" if c.link == "new" else "→ " + self._existing_name(c.link)[:14]
            tag = ("✓ " + link) if c.include else link
            items.append((tid, c.name, tag, GREEN if c.include else FG_TERTIARY, not c.include))
            search.append(f"{tid} {c.team['type']}")
        self.team_list.set_items(items, keep_data=keep, search_text=search)
        chosen = len(self.plan.selected_teams())
        self.team_count.setText(f"{chosen} of {len(self.plan.teams)} teams selected")
        self._show_team(self.team_list.highlighted_data())

    def _current_team(self):
        tid = self.team_list.highlighted_data()
        return self.plan.teams.get(tid) if self.plan and tid is not None else None

    def _show_team(self, tid):
        c = self.plan.teams.get(tid) if self.plan and tid is not None else None
        if c is None:
            return
        self.team_title.setText(f"GAME TEAM {tid} · {c.team['name']}".upper())
        self.t_include.set_value("yes" if c.include else "no")
        self.t_name.set_value(c.name)
        self.t_link.set_options(["new"] + sorted(self.ds.teams, key=self._existing_name))
        self.t_link.set_value(c.link)
        self.t_type.set_value(c.type if c.type in TEAM_TYPES else "club")
        self.t_category.set_options(self.ds.all_categories())
        self.t_category.set_value(c.category)
        if c.link == "new":
            self.t_link_note.setText("A new team folder is created with one season.")
        else:
            has = self.plan.season in self.ds.teams.get(c.link, {})
            self.t_link_note.setText(
                f"Season {self.plan.season} of {self._existing_name(c.link)} "
                + ("gets its squad, roles and set plays replaced; kits, crest and assets stay."
                   if has else "is added as a copy of its latest season, with the imported squad."))
        players = self.roster["players"]
        lines = []
        for i, rid in enumerate(c.team["squad"][:30]):
            rp = players.get(rid)
            if rp is None:
                continue
            marker = "" if i < self.plan.squad_size else "  (not imported)"
            lines.append(f"{i + 1:>2}  {rp['name']}  ·  {_pos(rp['positions'][0])}{marker}")
        captain = players.get(c.team["roles"]["captain"])
        lines.append(f"\nCaptain {captain['name'] if captain else '—'}  ·  set plays "
                     + ", ".join(f"{k} {v.replace('_', ' ')}" for k, v in c.team["set_plays"].items()))
        self.t_squad.setText("\n".join(lines))

    def _team_set(self, attr, value):
        c = self._current_team()
        if c is None:
            return
        setattr(c, attr, value)
        if attr == "link" and value != "new":
            c.name = self._existing_name(value)
        self._refresh_teams(keep=self.team_list.highlighted_data())

    def _toggle_team(self, tid):
        c = self.plan.teams.get(tid) if self.plan else None
        if c:
            c.include = not c.include
            self._refresh_teams(keep=tid)

    def _include_all(self, on):
        if self.plan:
            for c in self.plan.teams.values():
                c.include = on
            self._refresh_teams(keep=self.team_list.highlighted_data())

    def _include_linked(self):
        if self.plan:
            for c in self.plan.teams.values():
                c.include = c.link != "new"
            self._refresh_teams(keep=self.team_list.highlighted_data())

    # ── step 3 ───────────────────────────────────────────────────────────
    def _build_players_page(self, lay):
        row = QHBoxLayout()
        row.setSpacing(14)
        lcol = QVBoxLayout()
        fg = FieldGrid(columns=1)
        self.p_show = self._reg(ChoiceField("Show", ["check", "update", "create", "skip"],
                                            allow_blank=True, blank_label="all",
                                            display=lambda v: {"check": "matches to check",
                                                               "update": "updates",
                                                               "create": "new players",
                                                               "skip": "skipped"}[v]))
        self.p_show.label_width = 60
        self.p_show.edited.connect(lambda _: self._refresh_players())
        fg.add(self.p_show)
        lcol.addWidget(fg)
        bar = QHBoxLayout()
        for text, fn in (("CREATE UNMATCHED", lambda: self._bulk(P.CREATE, "none")),
                         ("SKIP TO CHECK", lambda: self._bulk(P.SKIP, "check"))):
            b = self._reg(compact_button(text))
            b.clicked.connect(fn)
            bar.addWidget(b)
        lcol.addLayout(bar)
        self.player_list = self._reg(SearchList("filter players"))
        self.player_list.setFixedWidth(380)
        self.player_list.highlighted.connect(self._show_player)
        lcol.addWidget(self.player_list, stretch=1)
        self.player_count = Note("", color=FG_TERTIARY)
        lcol.addWidget(self.player_count)
        row.addLayout(lcol)

        right = QVBoxLayout()
        right.setSpacing(12)
        dcard = SectionCard("player")
        self.p_title = dcard.title_lbl
        g = FieldGrid(columns=1)
        self.p_decision = self._reg(ChoiceField("Import as", allow_blank=False))
        self.p_decision.popup_title = "import as"
        self.p_decision.edited.connect(self._on_decision)
        g.add(self.p_decision)
        dcard.add(g)
        self.p_compare = Note("", color=FG_PRIMARY, size=T_LABEL)
        self.p_compare.setTextFormat(Qt.RichText)
        dcard.add(self.p_compare)
        dcard.v.addStretch(1)
        right.addWidget(dcard, stretch=1)
        row.addLayout(right, stretch=1)
        lay.addLayout(row)

    def _refresh_players(self, keep=None):
        if self.plan is None:
            return
        scope = self.plan.players_in_scope()
        show = self.p_show.value()
        items, search = [], []
        counts = {}
        for rid in scope:
            c = self.plan.players[rid]
            kind = "check" if (c.decision == P.UPDATE and c.confidence == "check") else c.decision
            counts[kind] = counts.get(kind, 0) + 1
            if show and kind != show:
                continue
            if c.decision == P.UPDATE:
                tag, col = ("UPDATE ✓", GREEN) if c.confidence == "exact" else ("CHECK ?", WARN)
            else:
                tag, col = DECISION_TAG[c.decision]
            items.append((rid, c.rp["name"], tag, col, c.decision == P.SKIP))
            search.append(f"{rid} {' '.join(c.rp['positions'])}")
        self.player_list.set_items(items, keep_data=keep, search_text=search)
        self.player_count.setText(
            f"{len(scope)} players · {counts.get('update', 0)} update · "
            f"{counts.get('check', 0)} to check · {counts.get('create', 0)} new · "
            f"{counts.get('skip', 0)} skipped")
        self._show_player(self.player_list.highlighted_data())

    def _show_player(self, rid):
        c = self.plan.players.get(rid) if self.plan and rid is not None else None
        if c is None:
            self.p_compare.setText("No player in this view.")
            return
        rp = c.rp
        self.p_title.setText(f"{rp['name']} · roster id {rid}".upper())
        options = [P.CREATE, P.SKIP] + [f"update:{pid}" for pid in c.candidates] + ["other"]
        self.p_decision.set_options(options)
        self.p_decision.display = lambda v: {
            P.CREATE: "a new player", P.SKIP: "skip — don't import",
            "other": "update another player…"}.get(v) or (
            f"update {self.ds.players.get(v[7:], {}).get('display_name', v[7:])} (id {v[7:]})")
        value = f"update:{c.pid}" if c.decision == P.UPDATE else c.decision
        if value not in options:
            options.insert(2, value)
            self.p_decision.set_options(options)
        self.p_decision.set_value(value)
        self.p_compare.setText(self._compare_html(c))

    def _compare_html(self, c):
        rp = c.rp
        off = self.plan.birth_offset
        roster_col = {
            "Name": rp["name"],
            "Positions": " / ".join(POSITION_NAMES.get(p, p) for p in rp["positions"] if p) or "—",
            "Born": f"{rp['birth'][0] + off}" + (f" (file {rp['birth'][0]})" if off else ""),
            "Height / weight": f"{rp['height_cm']} cm / {rp['weight_kg']} kg",
            "Nationality": ", ".join(rp["nationalities"]) or "—",
            "Attack / defence": f"{rp['ratings']['attack']} / {rp['ratings']['defense']}",
            "Speed / kicking": f"{rp['ratings']['speed']} / {rp['ratings']['kicking']}",
            "Tendency": TENDENCIES[rp["tendency"]],
            "Skills": ", ".join(s.replace("_", " ") for s in rp["skills"]) or "—",
        }
        mine = {}
        if c.decision == P.UPDATE and c.pid in self.ds.players:
            rec = self.ds.players[c.pid]
            stats = rec.get("stats") or {}
            latest = sorted(stats)[-1] if stats else None
            b = stats.get(latest, {}) if latest else {}
            mine = {
                "Name": rec.get("display_name", ""),
                "Positions": " / ".join(POSITION_NAMES.get(b.get(k), b.get(k)) for k in
                                        ("position1", "position2", "position3") if b.get(k)) or "—",
                "Born": (rec.get("birthdate") or "—")[:4],
                "Height / weight": f"{b.get('height') or '—'} cm / {b.get('weight') or '—'} kg",
                "Nationality": b.get("nationality") or "—",
                "Attack / defence": f"{b.get('attack', '—')} / {b.get('defense', '—')}",
                "Speed / kicking": f"{b.get('speed', '—')} / {b.get('kicking', '—')}",
                "Tendency": TENDENCIES[int(b["special_ability"])] if str(b.get("special_ability", "")).isdigit()
                and int(b["special_ability"]) < len(TENDENCIES) else "—",
                "Skills": ", ".join(k[3:].replace("_", " ") for k, v in b.items()
                                    if k.startswith("ss_") and str(v).lower() in P_TRUE) or "—",
            }
            head = (f"<b>In the file</b></td><td style='padding-left:24px'>"
                    f"<b>Existing player {c.pid} (latest season {latest})</b>")
        else:
            head = "<b>In the file</b></td><td>"
        rows = [f"<tr><td style='color:{FG_TERTIARY};padding-right:18px'></td><td>{head}</td></tr>"]
        for key, val in roster_col.items():
            other = mine.get(key, "")
            colour = WARN if mine and other and str(other) != str(val) and key != "Born" else FG_PRIMARY
            rows.append(f"<tr><td style='color:{FG_TERTIARY};padding-right:18px'>{key}</td>"
                        f"<td>{val}</td><td style='padding-left:24px;color:{colour}'>{other}</td></tr>")
        verdict = {
            ("update", "exact"): "Matched by name, and birth year or position agrees.",
            ("update", "check"): "Name matches but the details disagree or several players share "
                                 "it — check before updating.",
            ("create", "none"): "No player with this name — a new player will be created.",
        }.get((c.decision, c.confidence), "")
        return (f"<table cellspacing='4'>{''.join(rows)}</table>"
                f"<p style='color:{FG_SECONDARY}'>{verdict}</p>")

    def _on_decision(self, value):
        rid = self.player_list.highlighted_data()
        c = self.plan.players.get(rid) if self.plan else None
        if c is None:
            return
        if value == "other":
            self._pick_other(c, rid)
            return
        if value.startswith("update:"):
            c.decision, c.pid = P.UPDATE, value[7:]
            c.confidence = "exact"          # a human confirmed it
        else:
            c.decision = value
        self._refresh_players(keep=rid)

    def _pick_other(self, c, rid):
        popup = PopupList(self, width=460, height=460, own_keys=True)
        popup.set_title(f"update which player with {c.rp['name']}?")
        for pid, rec in sorted(self.ds.players.items(), key=lambda kv: (kv[1].get("display_name") or "").lower()):
            stats = rec.get("stats") or {}
            b = stats.get(sorted(stats)[-1], {}) if stats else {}
            popup.add_row(rec.get("display_name") or pid, pid, tag=_pos(b.get("position1")),
                          subtitle=(rec.get("birthdate") or "")[:4])
        popup.size_to(len(self.ds.players))
        popup.picked.connect(lambda pid: self._on_decision(f"update:{pid}") if pid else None)
        popup.open_at(self.p_decision, self)

    def _bulk(self, decision, confidence):
        if self.plan is None:
            return
        n = 0
        for rid in self.plan.players_in_scope():
            c = self.plan.players[rid]
            if c.confidence == confidence and c.decision != decision:
                c.decision = decision
                n += 1
        self._refresh_players(keep=self.player_list.highlighted_data())
        self.set_status(f"{n} player(s) changed", FG_SECONDARY)

    # ── step 4 ───────────────────────────────────────────────────────────
    def _build_review_page(self, lay):
        card = SectionCard("review")
        self.review = Note("", color=FG_PRIMARY, size=T_VALUE)
        self.review.setTextFormat(Qt.RichText)
        card.add(self.review)
        brow = QHBoxLayout()
        self.open_team_btn = self._reg(compact_button("OPEN TEAM EDITOR"))
        self.open_team_btn.clicked.connect(lambda: self.on_open_team and self.on_open_team())
        self.open_player_btn = self._reg(compact_button("OPEN PLAYER EDITOR"))
        self.open_player_btn.clicked.connect(lambda: self.on_open_player and self.on_open_player())
        brow.addWidget(self.open_team_btn)
        brow.addWidget(self.open_player_btn)
        brow.addStretch(1)
        card.add_layout(brow)
        card.v.addStretch(1)
        lay.addWidget(card, stretch=1)
        self._imported = None

    def _refresh_review(self):
        if self.plan is None:
            self.review.setText("Choose a roster file first.")
            return
        s = self.plan.summary()
        scope = self.plan.players_in_scope()
        groups = [label.split(" —")[0] for key, label, _ in P.GROUPS if key in self.plan.groups]
        teams = self.plan.selected_teams()
        files = set()
        for rid in scope:
            c = self.plan.players[rid]
            if c.decision == P.UPDATE and c.pid in self.ds.players:
                files.add(os.path.basename(self.ds.players_file_path[c.pid]))
            elif c.decision == P.CREATE:
                files.add(os.path.basename(self.plan.players_file))
        team_lines = []
        for t in teams:
            if "squads" not in self.plan.groups:
                break
            target = "new team" if t.link == "new" else f"into {self._existing_name(t.link)}"
            team_lines.append(f"· {t.name} — season {self.plan.season}, {target}")
            if t.link == "new":
                files.add(f"{t.name}/  (new team folder)")
            else:
                files.add(os.path.basename(self.ds.teams_file_path.get(t.link, "")))
        warn = []
        if s["players_to_check"]:
            warn.append(f"{s['players_to_check']} name matches were not confirmed — step 3 "
                        f"“matches to check”.")
        if not teams and self.plan.scope == "squads":
            warn.append("No team is selected, so no player is in scope.")
        for t in teams:
            kept = [r for r in t.team["squad"][:self.plan.squad_size]
                    if self.plan.players.get(r) and self.plan.players[r].decision != P.SKIP]
            if len(kept) < 22 and "squads" in self.plan.groups:
                warn.append(f"{t.name}: {len(kept)} players after skips — the game needs 22.")
        html = (
            f"<p><b>Season {self.plan.season}</b> · birth years +{self.plan.birth_offset} · "
            f"importing: {', '.join(groups) or 'nothing'}</p>"
            f"<p><b>Players</b>: {s['players_create']} new, {s['players_update']} updated, "
            f"{s['players_skip']} skipped</p>"
            f"<p><b>Teams</b>: {s['teams_new']} new, {s['teams_update']} updated"
            f"{'<br>' + '<br>'.join(team_lines) if team_lines else ''}</p>"
            f"<p><b>Files written</b> (a .bak of each original is kept on first save):<br>"
            f"{'<br>'.join(sorted(files)) or '—'}</p>"
        )
        if warn:
            html += f"<p style='color:{WARN}'>" + "<br>".join(warn) + "</p>"
        if self._imported:
            html = self._imported
        self.review.setText(html)

    def do_import(self):
        if self.plan is None:
            return
        self._on_options()
        try:
            result = P.apply_import(self.plan)
        except (SaveError, OSError, ValueError) as e:
            self.set_status(f"Import failed: {e}", DANGER_LITE)
            return
        for tid in result["teams_created"] + result["teams_updated"]:
            self.ds.events.team_changed.emit(tid)
        for pid in result["players_created"] + result["players_updated"]:
            self.ds.events.player_changed.emit(pid)
        self._imported = (
            f"<p style='color:{GREEN}'><b>Import complete.</b></p>"
            f"<p>{len(result['players_created'])} players created, "
            f"{len(result['players_updated'])} updated · {len(result['teams_created'])} teams "
            f"created, {len(result['teams_updated'])} updated.</p>"
            f"<p>Files written:<br>{'<br>'.join(sorted(os.path.basename(f) for f in result['files']))}</p>"
            + (f"<p style='color:{WARN}'>" + "<br>".join(result["warnings"]) + "</p>"
               if result["warnings"] else ""))
        self._refresh_review()
        self.next_btn.setText("DONE")
        self.set_status("Imported", GREEN)

    # ── navigation ───────────────────────────────────────────────────────
    def _go(self, step):
        self._step = step
        self.stack.setCurrentIndex(step)
        self.steps.set_index(step, notify=False)
        if step == STEP_TEAMS:
            self._refresh_teams(keep=self.team_list.highlighted_data())
        elif step == STEP_PLAYERS:
            self._on_options()
            self._refresh_players(keep=self.player_list.highlighted_data())
        elif step == STEP_REVIEW:
            self._on_options()
            self._refresh_review()
        self.back_btn.setText("‹ CANCEL" if step == STEP_FILE else "‹ BACK")
        if step == STEP_REVIEW:
            self.next_btn.setText("DONE" if self._imported else "IMPORT")
        else:
            self.next_btn.setText("NEXT ›")
        self.open_team_btn.setVisible(bool(self._imported))
        self.open_player_btn.setVisible(bool(self._imported))
        hints = {
            STEP_FILE: [("A", "edit"), ("E", "next")],
            STEP_TEAMS: [("A", "include / exclude"), ("↕", "browse"), ("E", "next")],
            STEP_PLAYERS: [("↕", "browse"), ("→", "decide"), ("E", "next")],
            STEP_REVIEW: [("A", "import")],
        }[step]
        self.hints.set_hints(hints + [("B", "back")])
        QTimer.singleShot(0, lambda: self.focus.focus_first(within=self.pages[step]))

    def _on_step_clicked(self, index):
        if index > self._step and not self._can_advance(index):
            self.steps.set_index(self._step, notify=False)
            return
        self._go(index)

    def _can_advance(self, target):
        if self.plan is None:
            self.set_status("Choose a roster file first", WARN)
            return False
        if target >= STEP_PLAYERS and self.plan.scope == "squads" and not self.plan.selected_teams():
            self.set_status("Select at least one team (or import every player on step 1)", WARN)
            return False
        return True

    def next_step(self):
        if self._step == STEP_REVIEW:
            if self._imported:
                self.leave()
            else:
                self.do_import()
            return
        if self._can_advance(self._step + 1):
            target = self._step + 1
            if target == STEP_TEAMS and self.plan.scope == "all" and "squads" not in self.plan.groups:
                target = STEP_PLAYERS
            self._go(target)

    def request_back(self):
        if self._step == STEP_FILE:
            self.leave()
        else:
            self._go(self._step - 1)

    def leave(self):
        self.reset()
        if self.on_back_cb:
            self.on_back_cb()

    def reset(self):
        self.plan = None
        self.roster = None
        self._imported = None
        self.path.set_value("")
        self.file_summary.setText("Choose a .ros saved roster (community patches) or a raw "
                                  ".rdf roster file.")
        self.team_list.set_items([])
        self.player_list.set_items([])
        self._go(STEP_FILE)

    def set_status(self, text, color=FG_SECONDARY):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent;"
                                  f" font-family: '{FONT_DISPLAY}'; font-size: {T_LABEL}pt;"
                                  f" font-weight: 600;")

    def on_show(self):
        self._go(self._step)

    def keyPressEvent(self, event):
        focused = QApplication.focusWidget()
        if isinstance(focused, QLineEdit) or PopupList.any_open():
            super(Screen, self).keyPressEvent(event)
            return
        action = KEYMAP.get(event.key())
        if action == Action.TAB_NEXT:
            self.next_step()
        elif action == Action.TAB_PREV or (action == Action.BACK and not isinstance(focused, TextField)):
            self.request_back()
        elif action == Action.CONFIRM and focused is self.team_list:
            self.team_list.activate()
        elif action in (Action.NAV_UP, Action.NAV_DOWN, Action.NAV_LEFT, Action.NAV_RIGHT):
            self.focus.move(action)
        else:
            super().keyPressEvent(event)
            return
        event.accept()


P_TRUE = {"1", "true", "yes", "on", "up"}
