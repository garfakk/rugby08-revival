"""
screens/tournament/dashboard.py — The running tournament.

Tabs: Overview (next match: play / simulate / squad, latest results,
news), Standings, Fixtures, Bracket, Stats, News. Every action goes
through the TournamentSession, which saves after each step.
"""
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from app.screen_base import Screen
from app.tournament import engine, report, standings, stats
from app.tournament.strength import team_rating
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, page_header
from ui.editor_kit import ConfirmDialog, Note, TabPage, TabStrip, compact_button
from ui.theme import (ACCENT, BG_BASE, FG_MUTED, FG_SECONDARY, FG_TERTIARY, GREEN,
                      HOME_TINT, INFO, T_TITLE, WARN)

from .common import DataTable, clear_layout, section

TABS = ["Overview", "Standings", "Fixtures", "Bracket", "Stats", "News"]
NEWS_COLORS = {"injury": WARN, "suspension": WARN, "return": GREEN, "upset": INFO,
               "champion": ACCENT, "award": ACCENT, "stage": INFO}


class TournamentDashboardScreen(Screen):
    def __init__(self, ds, on_back, on_play, on_squad):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_play = on_play        # fn(session, fixture)
        self.on_squad = on_squad      # fn(session, team_id)
        self.session = None
        self._message = ""
        self._build()

    @property
    def t(self):
        return self.session.t if self.session else None

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header_holder = QVBoxLayout()
        self.header_holder.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self.header_holder)

        body = QWidget()
        body.setObjectName("dashBody")
        body.setStyleSheet(f"QWidget#dashBody {{ background: {BG_BASE}; }}")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(60, 10, 60, 8)
        bv.setSpacing(0)
        self.tabs = TabStrip(TABS)
        self.tabs.changed.connect(self._tab_changed)
        self.focus.register(self.tabs)
        bv.addWidget(self.tabs)
        self.stack = QStackedWidget()
        self.pages = [TabPage() for _ in TABS]
        for p in self.pages:
            self.stack.addWidget(p)
        bv.addWidget(self.stack, stretch=1)
        root.addWidget(body, stretch=1)

        self._build_overview(self.pages[0].layout_)
        self.standings_holder = self.pages[1].layout_
        self.fixtures = DataTable(["Day", "Round", "Home", "Score", "Away", "Venue"], stretch_col=1)
        self.fixtures.activated_row.connect(self._fixture_report)
        self.focus.register(self.fixtures)
        self.pages[2].layout_.addWidget(self.fixtures, stretch=1)
        self.pages[2].layout_.addWidget(Note("Enter / double-click a played match for its report.",
                                             color=FG_TERTIARY))
        self.bracket_holder = QHBoxLayout()
        self.bracket_holder.setSpacing(16)
        self.pages[3].layout_.addLayout(self.bracket_holder)
        self.pages[3].layout_.addStretch(1)
        self.stats_holder = QGridLayout()
        self.stats_holder.setSpacing(16)
        self.pages[4].layout_.addLayout(self.stats_holder)
        self.pages[4].layout_.addStretch(1)
        self.news = DataTable(["Day", "Headline"], stretch_col=1)
        self.focus.register(self.news)
        self.pages[5].layout_.addWidget(self.news, stretch=1)

        hints = HintBar()
        hints.set_hints([("A", "select"), ("B", "back")])
        root.addWidget(hints)

    def _build_overview(self, v):
        self.banner = Note("", color=INFO)
        v.addWidget(self.banner)
        self.next_card = Card(stripe=ACCENT)
        nv = QVBoxLayout(self.next_card)
        nv.setContentsMargins(24, 16, 24, 16)
        nv.setSpacing(8)
        self.next_eyebrow = eyebrow_label("next match", color=ACCENT, size=12)
        nv.addWidget(self.next_eyebrow)
        self.next_title = display_label("", T_TITLE + 6, QFont.Bold, track=0.8, upper=False)
        nv.addWidget(self.next_title)
        self.next_info = Note("", color=FG_SECONDARY)
        nv.addWidget(self.next_info)
        self.next_avail = Note("", color=WARN)
        nv.addWidget(self.next_avail)
        row = QHBoxLayout()
        self.undo_btn = compact_button("UNDO LAST", "ghost")
        self.undo_btn.clicked.connect(self._undo)
        row.addWidget(self.undo_btn)
        row.addStretch(1)
        self.squad_btn = compact_button("SQUAD", "neutral")
        self.squad_btn.clicked.connect(self._squad)
        self.sim_end_btn = compact_button("SIMULATE TO END", "neutral")
        self.sim_end_btn.clicked.connect(self._sim_to_end)
        self.sim_btn = compact_button("SIMULATE MATCH", "neutral")
        self.sim_btn.clicked.connect(self._simulate)
        self.continue_btn = compact_button("CONTINUE", "primary")
        self.continue_btn.clicked.connect(self._continue)
        self.play_btn = compact_button("PLAY MATCH", "primary")
        self.play_btn.clicked.connect(self._play)
        for b in (self.undo_btn, self.squad_btn, self.sim_end_btn, self.sim_btn, self.continue_btn,
                  self.play_btn):
            if b is not self.undo_btn:
                row.addWidget(b)
            self.focus.register(b)
        nv.addLayout(row)
        v.addWidget(self.next_card)

        cols = QHBoxLayout()
        cols.setSpacing(16)
        w, lv = section("latest results")
        self.latest = DataTable(["Home", "Score", "Away"], stretch_col=0)
        self.latest.activated_row.connect(lambda r: self._report(self.latest.keys[r]))
        self.focus.register(self.latest)
        lv.addWidget(self.latest)
        cols.addWidget(w, stretch=1)
        w, rv = section("news")
        self.recent_news = DataTable(["Headline"], stretch_col=0)
        self.focus.register(self.recent_news)
        rv.addWidget(self.recent_news)
        cols.addWidget(w, stretch=1)
        v.addLayout(cols, stretch=1)

    # ── entry ────────────────────────────────────────────────────────────
    def set_session(self, session, message=""):
        self.session = session
        self._message = message
        clear_layout(self.header_holder)
        tpl_name = session.t.template.get("name", session.t.template_id)
        self.header_holder.addWidget(page_header(session.t.name, breadcrumb=f"tournament · {tpl_name}",
                                                 on_back=self.on_back_cb))
        self.tabs.set_index(0)
        self.refresh()

    def set_message(self, text):
        self._message = text
        self.refresh()

    def on_show(self):
        super().on_show()
        if self.session:
            self.refresh()

    def _tab_changed(self, i):
        self.stack.setCurrentIndex(i)
        self.refresh()

    def refresh(self):
        if not self.session:
            return
        i = self.tabs.index()
        self._refresh_overview()
        if i == 1:
            self._refresh_standings()
        elif i == 2:
            self._refresh_fixtures()
        elif i == 3:
            self._refresh_bracket()
        elif i == 4:
            self._refresh_stats()
        elif i == 5:
            self._refresh_news()

    # ── overview ─────────────────────────────────────────────────────────
    def _human_ids(self):
        return [e.team_id for e in self.t.human_teams()]

    def _upcoming_human(self):
        """Next unplayed fixture for any human team (may be a later day)."""
        humans = set(self._human_ids())
        return next((f for f in self.t.fixtures if not f.played and (f.home in humans or f.away in humans)),
                    None)

    def _refresh_overview(self):
        t = self.t
        self.banner.setText(self._message)
        self.banner.setVisible(bool(self._message))
        due = self.session.human_fixture()
        upcoming = due or self._upcoming_human()
        alive = [h for h in self._human_ids() if not engine.is_eliminated(t, h)]
        for b in (self.play_btn, self.sim_btn, self.continue_btn, self.squad_btn, self.sim_end_btn):
            b.setVisible(False)
        self.next_avail.setText("")
        if t.finished:
            self.next_eyebrow.setText("tournament over")
            self.next_title.setText(f"{t.team_name(t.champion)} are champions")
            final = next((f for f in reversed(t.fixtures) if f.final and f.result), None)
            self.next_info.setText(f"Final: {report.fixture_caption(t, final)} {final.result.score_text()}"
                                   if final else "")
        elif due:
            self.next_eyebrow.setText(f"matchday {due.day + 1} · {due.label}")
            self.next_title.setText(report.fixture_caption(t, due))
            venue = report.venue_name(self.ds, due)
            ratings = f"{t.team_name(due.home)} {team_rating(t, due.home):.1f}  ·  " \
                      f"{t.team_name(due.away)} {team_rating(t, due.away):.1f}"
            self.next_info.setText((f"{venue}  ·  " if venue else "") + "team ratings: " + ratings)
            out = []
            for tid in (due.home, due.away):
                if t.teams[tid].human:
                    for pid, reason in report.availability(t, tid):
                        out.append(f"{t.player_name(pid)} — {reason}")
            self.next_avail.setText(("Unavailable: " + "; ".join(out)) if out else "")
            for b in (self.play_btn, self.sim_btn, self.squad_btn):
                b.setVisible(True)
        elif upcoming:
            self.next_eyebrow.setText(f"your next match · matchday {upcoming.day + 1} · {upcoming.label}")
            self.next_title.setText(report.fixture_caption(t, upcoming))
            self.next_info.setText(f"Matchday {t.day + 1}: other fixtures first. CONTINUE simulates them.")
            for b in (self.continue_btn, self.squad_btn, self.sim_end_btn):
                b.setVisible(True)
        else:
            self.next_eyebrow.setText("out of the running" if not alive else "waiting")
            self.next_title.setText("Your campaign is over" if not alive else "Waiting for the draw")
            self.next_info.setText("Simulate the rest of the tournament to see who wins.")
            for b in (self.sim_end_btn, self.squad_btn):
                b.setVisible(True)
        self.squad_btn.setVisible(self.squad_btn.isVisible() and bool(self._human_ids()))
        self.undo_btn.setVisible(self.session.can_undo())

        played = [f for f in t.fixtures if f.played]
        last_day = played[-1].day if played else None
        recent = [f for f in played if f.day == last_day] if last_day is not None else []
        humans = set(self._human_ids())
        self.latest.set_rows([[t.team_name(f.home), f.result.score_text(), t.team_name(f.away)] for f in recent],
                             keys=[f.id for f in recent],
                             colors={i: HOME_TINT for i, f in enumerate(recent)
                                     if f.home in humans or f.away in humans})
        news = list(reversed(t.news))[:14]
        self.recent_news.set_rows([[n["text"]] for n in news],
                                  colors={i: NEWS_COLORS.get(n["kind"]) for i, n in enumerate(news)
                                          if n["kind"] in NEWS_COLORS})

    # ── other tabs ───────────────────────────────────────────────────────
    def _refresh_standings(self):
        clear_layout(self.standings_holder)
        t = self.t
        humans = set(self._human_ids())
        for stage in t.stages:
            if stage.kind != "round_robin":
                continue
            qualify = int(stage.spec.get("qualify", 0))
            for g in stage.groups:
                w, v = section(g.name if len(t.stages) == 1 or len(stage.groups) > 1
                               else f"{stage.name}")
                table = DataTable(["#", "Team", "P", "W", "D", "L", "PF", "PA", "+/-", "TB", "LB", "Pts", "Form"],
                                  stretch_col=1)
                rows, colors, bold = [], {}, set()
                for i, r in enumerate(standings.group_table(t, stage, g)):
                    rows.append([i + 1, t.team_name(r.team_id), r.played, r.won, r.drawn, r.lost,
                                 r.points_for, r.points_against, f"{r.points_diff:+d}", r.try_bonus,
                                 r.losing_bonus, r.points, "".join(r.form[-5:])])
                    if i < qualify:
                        colors[i] = GREEN
                    if r.team_id in humans:
                        colors[i] = HOME_TINT
                        bold.add(i)
                table.set_rows(rows, colors=colors, bold=bold)
                table.fit_height()
                v.addWidget(table)
                self.standings_holder.addWidget(w)
        self.standings_holder.addStretch(1)

    def _refresh_fixtures(self):
        t = self.t
        humans = set(self._human_ids())
        rows, colors = [], {}
        for i, f in enumerate(t.fixtures):
            rows.append([f.day + 1, f.label,
                         t.team_name(f.home) if f.home else f.home_ref,
                         f.result.score_text() if f.result else "v",
                         t.team_name(f.away) if f.away else f.away_ref,
                         report.venue_name(self.ds, f)])
            if f.home in humans or f.away in humans:
                colors[i] = HOME_TINT
            elif not f.played:
                colors[i] = FG_TERTIARY
        self.fixtures.set_rows(rows, keys=[f.id for f in t.fixtures], colors=colors)
        nxt = next((f for f in t.fixtures if not f.played), None)
        if nxt and self.fixtures.currentRow() < 0:
            self.fixtures.select_key(nxt.id)
            self.fixtures.scrollTo(self.fixtures.currentIndex())

    def _refresh_bracket(self):
        clear_layout(self.bracket_holder)
        t = self.t
        rounds = []
        for f in t.fixtures:
            if not f.knockout:
                continue
            if not rounds or rounds[-1][0] != f.round_id:
                rounds.append((f.round_id, f.round_name, []))
            rounds[-1][2].append(f)
        if not rounds:
            self.bracket_holder.addWidget(Note("This competition has no knockout stage.", color=FG_MUTED))
            return
        for _rid, name, ties in rounds:
            col = QVBoxLayout()
            col.setSpacing(10)
            col.addWidget(eyebrow_label(name, color=ACCENT, size=12))
            for f in ties:
                card = Card(stripe=GREEN if f.played else None)
                cv = QVBoxLayout(card)
                cv.setContentsMargins(12, 8, 12, 8)
                cv.setSpacing(2)
                winner = f.result.winner_id() if f.result else None
                for tid, ref, pts in ((f.home, f.home_ref, f.result.home.points if f.result else None),
                                      (f.away, f.away_ref, f.result.away.points if f.result else None)):
                    label = t.team_name(tid) if tid else ref
                    text = f"{label}   {pts}" if pts is not None else label
                    color = FG_SECONDARY if tid else FG_MUTED
                    if winner and tid == winner:
                        color = GREEN
                    cv.addWidget(display_label(text, 13, QFont.Bold if tid == winner else QFont.Normal,
                                               track=0.5, color=color, upper=False))
                if f.result and f.result.decided_by:
                    cv.addWidget(Note(f.result.score_text(), color=FG_TERTIARY))
                col.addWidget(card)
            col.addStretch(1)
            self.bracket_holder.addLayout(col, stretch=1)

    def _refresh_stats(self):
        clear_layout(self.stats_holder)
        t = self.t
        boards = [("points", "Points"), ("tries", "Tries"), ("tackles", "Tackles"),
                  ("motm", "Player of the match")]
        for i, (key, title) in enumerate(boards):
            w, v = section(title)
            table = DataTable(["Player", "Team", title], stretch_col=0)
            rows = [[t.player_name(pid), t.team_name(t.players[pid].team_id) if pid in t.players else "", n]
                    for pid, n in stats.leaders(t, key, 10)]
            table.set_rows(rows)
            table.fit_height(10)
            v.addWidget(table)
            self.stats_holder.addWidget(w, i // 2, i % 2)
        w, v = section("team of the tournament" + ("" if t.finished else " so far"))
        table = DataTable(["Position", "Player", "Team"], stretch_col=1)
        team = stats.team_of_the_tournament(t)
        table.set_rows([[pos.replace("_", " "), t.player_name(pid), t.team_name(t.players[pid].team_id)]
                        for pos, pid in team])
        table.fit_height()
        v.addWidget(table)
        self.stats_holder.addWidget(w, 2, 0, 1, 2)

    def _refresh_news(self):
        news = list(reversed(self.t.news))
        self.news.set_rows([[n["day"] + 1, n["text"]] for n in news],
                           colors={i: NEWS_COLORS.get(n["kind"]) for i, n in enumerate(news)
                                   if n["kind"] in NEWS_COLORS})

    # ── actions ──────────────────────────────────────────────────────────
    def _summary(self, fixtures):
        humans = set(self._human_ids())
        mine = [f for f in fixtures if f.home in humans or f.away in humans]
        parts = [f"{report.fixture_caption(self.t, f)} {f.result.score_text()}" for f in mine if f.result]
        return ("  ·  ".join(parts) + f"   ({len(fixtures)} match{'es' if len(fixtures) != 1 else ''} played)") \
            if parts else (f"{len(fixtures)} matches simulated." if fixtures else "")

    def _play(self):
        f = self.session.human_fixture()
        if f:
            self._message = ""
            self.on_play(self.session, f)

    def _simulate(self):
        f = self.session.human_fixture()
        if f:
            self.set_message(self._summary(self.session.simulate(f)))

    def _continue(self):
        done = self.session.advance_to_human()
        self.set_message(self._summary(done))

    def _sim_to_end(self):
        def go(role):
            if role == "ok":
                self.session.simulate_to_end()
                self.set_message("The rest of the tournament was simulated.")
        ConfirmDialog(self, "Simulate to the end?",
                      "Every remaining match, including your team's, is simulated.",
                      [("CANCEL", "neutral", "cancel"), ("SIMULATE", "primary", "ok")], go)

    def _undo(self):
        def go(role):
            if role == "ok" and self.session.undo():
                self.set_message("Last step undone.")
        ConfirmDialog(self, "Undo the last step?",
                      "The results recorded by the last action are removed (only one step can be undone).",
                      [("CANCEL", "neutral", "cancel"), ("UNDO", "danger", "ok")], go)

    def _squad(self):
        due = self.session.human_fixture() or self._upcoming_human()
        humans = self._human_ids()
        team = next((tid for tid in ((due.home, due.away) if due else ()) if tid in humans), None)
        self.on_squad(self.session, team or (humans[0] if humans else None))

    def _fixture_report(self, row):
        self._report(self.fixtures.keys[row])

    def _report(self, fid):
        f = self.t.fixture(fid)
        if not f or not f.played:
            return
        ConfirmDialog(self, f"{f.label}", report.match_report(self.t, f), [("CLOSE", "primary", "ok")],
                      lambda _r: None, cancel_role="ok", width=720)
