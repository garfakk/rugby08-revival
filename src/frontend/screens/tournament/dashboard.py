"""
screens/tournament/dashboard.py — The running tournament.

The header (the competition's logo, the tournament's name) over seven tabs:
Overview (the next match as a broadcast-style hero card with both crests,
form, your pool, latest results, news), Manage your team (the matchday
squad, screens.tournament.squad), Standings, Fixtures (by matchday,
filterable to your team), Bracket (painted, with connectors), Stats (leader
boards, team of the tournament on a pitch) and News.

Every action goes through the TournamentSession, which saves after each
step. Pad: Q/E switch tabs, A select, B back.
"""
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.tournament import calendar, engine, report, standings, stats, weather
from shared.user_prefs import user_prefs
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, page_header
from ui.editor_kit import ConfirmDialog, Note, TabPage, TabStrip, compact_button
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BTN_HEIGHT, FG_MUTED, FG_PRIMARY, FG_SECONDARY,
                      FG_TERTIARY, GREEN, HOME_TINT, INFO, WARN)

from .bracket import BracketView
from .common import (DataTable, FormStrip, NewsItem, PixmapLabel,
                     ScoreCard, Section, SectionTitle, Tag, YOU_TINT, clear_layout,
                     competition_emblem, hline, section, tournament_crest, transparent)
from .manual_result import ManualResultView
from .pitch import LineupPitch
from .squad import TournamentSquadScreen

TABS = ["Overview", "Manage your team", "Standings", "Fixtures", "Bracket", "Stats", "News"]
OVERVIEW, TEAM, STANDINGS, FIXTURES, BRACKET, STATS, NEWS = range(len(TABS))


def _without_round(f) -> str:
    """The fixture's label less its round ("Pool A · Round 2" -> "Pool A"):
    the round is the table's section header."""
    suffix = f" · {f.round_name}"
    return f.label[:-len(suffix)] if f.round_name and f.label.endswith(suffix) else f.label


def team_form(t, team_id, n=5):
    """W/D/L of the team's last n played matches, oldest first."""
    out = []
    for f in t.fixtures:
        if f.played and f.involves(team_id):
            w = f.result.winner_id()
            out.append("D" if w is None else ("W" if w == team_id else "L"))
    return out[-n:]


class _TeamBlock(QWidget):
    """One side of the hero card: crest, name, tags, form."""

    def __init__(self, side):
        super().__init__()
        transparent(self, f"hero{side}")
        self.side = side
        right = side == "away"
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(18)
        self.crest = PixmapLabel(104)
        v = QVBoxLayout()
        v.setSpacing(6)
        self.name = display_label("", 28, QFont.Bold, track=1.0)
        self.name.setWordWrap(True)
        self.tags = QHBoxLayout()
        self.tags.setSpacing(6)
        self.form = FormStrip(cell=18, align_right=right)
        align = Qt.AlignRight if right else Qt.AlignLeft
        self.name.setAlignment(align | Qt.AlignVCenter)
        v.addStretch(1)
        v.addWidget(self.name)
        tag_row = QHBoxLayout()
        if right:
            tag_row.addStretch(1)
        tag_row.addLayout(self.tags)
        if not right:
            tag_row.addStretch(1)
        v.addLayout(tag_row)
        v.addWidget(self.form)
        v.addStretch(1)
        if right:
            h.addLayout(v, stretch=1)
            h.addWidget(self.crest)
        else:
            h.addWidget(self.crest)
            h.addLayout(v, stretch=1)

    def set_team(self, ds, t, team_id, label, human):
        self.crest.set_pixmap(tournament_crest(ds, t, team_id, 104))
        self.name.setText(t.team_name(team_id).upper())
        clear_layout(self.tags)
        if label:
            self.tags.addWidget(Tag(label, FG_TERTIARY, filled=False))
        if human:
            self.tags.addWidget(Tag("you", YOU_TINT))
        self.form.set_form(team_form(t, team_id))


class TournamentDashboardScreen(Screen):
    def __init__(self, ds, on_back, on_play):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_play = on_play        # fn(session, fixture)
        self.session = None
        self._message = ""
        self._mine_only = False
        self._dynamic = []            # focusable widgets rebuilt on refresh
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
        bv.setContentsMargins(60, 14, 60, 8)
        bv.setSpacing(10)

        self.tabs = TabStrip(TABS)
        self.tabs.changed.connect(self._tab_changed)
        self.focus.register(self.tabs)
        bv.addWidget(self.tabs)
        self.stack = QStackedWidget()
        self.pages = [TabPage() for _ in TABS]
        for p in self.pages:
            p.layout_.setContentsMargins(0, 16, 10, 10)
            p.layout_.setSpacing(16)
            self.stack.addWidget(p)
        bv.addWidget(self.stack, stretch=1)
        foot = QHBoxLayout()
        foot.addStretch(1)
        self.menu_btn = compact_button("BACK TO MAIN MENU", "neutral", height=BTN_HEIGHT)
        self.menu_btn.clicked.connect(self._leave)
        self.focus.register(self.menu_btn)
        foot.addWidget(self.menu_btn)
        bv.addLayout(foot)
        root.addWidget(body, stretch=1)

        self._build_overview(self.pages[OVERVIEW].layout_)
        # the squad screen without its own header / hint bar; B goes back
        # to the tabs
        self.squad = TournamentSquadScreen(on_back=lambda: self.tabs.setFocus(), embedded=True)
        self.pages[TEAM].layout_.addWidget(self.squad, stretch=1)
        self.standings_holder = self.pages[STANDINGS].layout_
        self._build_fixtures(self.pages[FIXTURES].layout_)
        self.bracket_holder = self.pages[BRACKET].layout_
        self.stats_holder = self.pages[STATS].layout_
        self.news_holder = self.pages[NEWS].layout_

        self.hints = HintBar()
        self.hints.set_hints([("A", "select"), ("LB", "prev tab"), ("RB", "next tab"), ("B", "back")])
        root.addWidget(self.hints)

    def _build_overview(self, v):
        self.banner = Card(stripe=INFO, translucent=True)
        bl = QHBoxLayout(self.banner)
        bl.setContentsMargins(20, 10, 20, 10)
        self.banner_text = Note("", color=FG_PRIMARY)
        bl.addWidget(self.banner_text)
        v.addWidget(self.banner)

        top = QHBoxLayout()
        top.setSpacing(18)
        # hero
        self.hero = Card(stripe=ACCENT)
        hv = QVBoxLayout(self.hero)
        hv.setContentsMargins(28, 18, 28, 20)
        hv.setSpacing(12)
        eb = QHBoxLayout()
        self.hero_eyebrow = display_label("", 20, QFont.Bold, track=1.2, color=ACCENT)
        eb.addWidget(self.hero_eyebrow)
        eb.addStretch(1)
        venue_col = QVBoxLayout()
        venue_col.setSpacing(2)
        self.hero_venue = eyebrow_label("", color=FG_TERTIARY, size=11)
        self.hero_venue.setAlignment(Qt.AlignRight)
        venue_col.addWidget(self.hero_venue)
        self.hero_weather = eyebrow_label("", color=INFO, size=10)
        self.hero_weather.setAlignment(Qt.AlignRight)
        venue_col.addWidget(self.hero_weather)
        eb.addLayout(venue_col)
        hv.addLayout(eb)

        self.match_view = transparent(QWidget(), "heroMatch")
        mv = QVBoxLayout(self.match_view)
        mv.setContentsMargins(0, 0, 0, 0)
        mv.setSpacing(12)
        teams = QHBoxLayout()
        teams.setSpacing(12)
        self.home_block = _TeamBlock("home")
        self.away_block = _TeamBlock("away")
        teams.addWidget(self.home_block, stretch=1)
        vs = QVBoxLayout()
        vs.addStretch(1)
        self.vs_label = display_label("vs", 30, QFont.Bold, track=2.0, color=FG_TERTIARY)
        self.vs_label.setAlignment(Qt.AlignCenter)
        vs.addWidget(self.vs_label)
        vs.addStretch(1)
        teams.addLayout(vs)
        teams.addWidget(self.away_block, stretch=1)
        mv.addLayout(teams)
        hv.addWidget(self.match_view)

        self.message_view = transparent(QWidget(), "heroMessage")
        msv = QHBoxLayout(self.message_view)
        msv.setContentsMargins(0, 6, 0, 6)
        msv.setSpacing(22)
        self.msg_crest = PixmapLabel(120)
        msv.addWidget(self.msg_crest)
        mtv = QVBoxLayout()
        mtv.addStretch(1)
        self.msg_kicker = eyebrow_label("", color=AWAY_TINT, size=14)
        mtv.addWidget(self.msg_kicker)
        self.msg_title = display_label("", 34, QFont.Bold, track=1.2)
        self.msg_title.setWordWrap(True)
        mtv.addWidget(self.msg_title)
        self.msg_info = Note("", color=FG_SECONDARY)
        mtv.addWidget(self.msg_info)
        mtv.addStretch(1)
        msv.addLayout(mtv, stretch=1)
        hv.addWidget(self.message_view)

        self.next_avail = Note("", color=WARN)
        hv.addWidget(self.next_avail)
        hv.addWidget(hline())
        row = QHBoxLayout()
        row.setSpacing(10)
        self.undo_btn = compact_button("UNDO LAST", "ghost", height=BTN_HEIGHT)
        self.undo_btn.clicked.connect(self._undo)
        self.sim_end_btn = compact_button("SIMULATE TO END", "neutral", height=BTN_HEIGHT)
        self.sim_end_btn.clicked.connect(self._sim_to_end)
        self.sim_btn = compact_button("SIMULATE MATCH", "neutral", height=BTN_HEIGHT)
        self.sim_btn.clicked.connect(self._simulate)
        # Expert mode only (user_prefs.expert_mode): type the result in.
        self.enter_btn = compact_button("ENTER RESULT", "neutral", height=BTN_HEIGHT)
        self.enter_btn.clicked.connect(self._enter_result)
        self.continue_btn = compact_button("CONTINUE", "primary", height=BTN_HEIGHT)
        self.continue_btn.clicked.connect(self._continue)
        self.play_btn = compact_button("PLAY MATCH", "primary", height=BTN_HEIGHT)
        self.play_btn.clicked.connect(self._play)
        for b in (self.continue_btn, self.play_btn):
            b.setMinimumWidth(200)
        row.addWidget(self.undo_btn)
        row.addStretch(1)
        for b in (self.sim_end_btn, self.enter_btn, self.sim_btn, self.continue_btn, self.play_btn):
            row.addWidget(b)
        # Registration order = where focus starts: the primary action first.
        for b in (self.play_btn, self.continue_btn, self.sim_btn, self.enter_btn, self.sim_end_btn,
                  self.undo_btn):
            self.focus.register(b)
        hv.addLayout(row)
        top.addWidget(self.hero, stretch=3)

        # your pool / path
        side = transparent(QWidget(), "ovSide")
        sv = QVBoxLayout(side)
        sv.setContentsMargins(0, 0, 0, 0)
        sv.setSpacing(8)
        self.side_title = SectionTitle("your pool")
        sv.addWidget(self.side_title)
        self.side_holder = QVBoxLayout()
        self.side_holder.setSpacing(8)
        sv.addLayout(self.side_holder)
        sv.addStretch(1)
        top.addWidget(side, stretch=2)
        v.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(18)
        w, lv = section("latest results")
        self.latest_title = w.title
        self.latest_grid = QGridLayout()
        self.latest_grid.setHorizontalSpacing(10)
        self.latest_grid.setVerticalSpacing(10)
        lv.addLayout(self.latest_grid)
        lv.addStretch(1)
        bottom.addWidget(w, stretch=3)
        w, rv = section("news")
        self.news_card = Card(translucent=True)
        self.news_list = QVBoxLayout(self.news_card)
        self.news_list.setContentsMargins(6, 4, 6, 4)
        self.news_list.setSpacing(0)
        rv.addWidget(self.news_card)
        rv.addStretch(1)
        bottom.addWidget(w, stretch=2)
        v.addLayout(bottom)
        v.addStretch(1)

    def _build_fixtures(self, v):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.fx_all = compact_button("ALL MATCHES", "primary")
        self.fx_mine = compact_button("YOUR MATCHES", "neutral")
        self.fx_all.clicked.connect(lambda: self._set_mine(False))
        self.fx_mine.clicked.connect(lambda: self._set_mine(True))
        for b in (self.fx_all, self.fx_mine):
            row.addWidget(b)
            self.focus.register(b)
        row.addStretch(1)
        row.addWidget(Note("A on a played match opens its report.", color=FG_TERTIARY))
        v.addLayout(row)
        self.fixtures = DataTable(["Round", "Home", "", "Away", "Venue"], stretch_col=1,
                                  widths={0: 190, 2: 120, 3: 300, 4: 200},
                                  header_align={1: Qt.AlignRight})
        self.fixtures.activated_row.connect(lambda r: self._report(self.fixtures.keys[r]))
        self.focus.register(self.fixtures)
        v.addWidget(self.fixtures, stretch=1)

    # ── entry ────────────────────────────────────────────────────────────
    def set_session(self, session, message=""):
        self.session = session
        self._message = message
        clear_layout(self.header_holder)
        t = session.t
        self.header_holder.addWidget(page_header(t.name,
                                                 icon=competition_emblem(self.ds, t.template, 52)))
        # a competition without a knockout stage has no bracket to show
        self.tabs.set_hidden({BRACKET} if not any(s.kind == "knockout" for s in t.stages) else ())
        self.tabs.set_index(0, notify=False)
        self.stack.setCurrentIndex(0)
        self.refresh()

    def set_message(self, text):
        self._message = text
        self.refresh()

    def on_show(self):
        super().on_show()
        if self.session:
            self.refresh()
            if self.tabs.index() == 0:
                first = next((b for b in (self.play_btn, self.continue_btn, self.sim_end_btn)
                              if b.isVisible()), None)
                if first:
                    first.setFocus()

    def _tab_changed(self, i):
        self.stack.setCurrentIndex(i)
        self.refresh()

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action == Action.BACK:
            self._leave()
            event.accept()
            return
        if action in (Action.TAB_PREV, Action.TAB_NEXT):
            self.tabs.step(1 if action == Action.TAB_NEXT else -1)
            event.accept()
            return
        super().keyPressEvent(event)

    def _register_dynamic(self, w):
        self.focus.register(w)
        self._dynamic.append(w)
        return w

    def refresh(self):
        if not self.session:
            return
        for w in self._dynamic:
            self.focus.unregister(w)
        self._dynamic = []
        i = self.tabs.index()
        self._refresh_overview()
        if i == TEAM:
            self._refresh_team()
        elif i == STANDINGS:
            self._refresh_standings()
        elif i == FIXTURES:
            self._refresh_fixtures()
        elif i == BRACKET:
            self._refresh_bracket()
        elif i == STATS:
            self._refresh_stats()
        elif i == NEWS:
            self._refresh_news()

    # ── overview ─────────────────────────────────────────────────────────
    def _human_ids(self):
        return [e.team_id for e in self.t.human_teams()]

    def _upcoming_human(self):
        """Next unplayed fixture for any human team (may be a later day)."""
        humans = set(self._human_ids())
        return next((f for f in self.t.fixtures if not f.played and (f.home in humans or f.away in humans)),
                    None)

    def _show_match(self, f):
        t = self.t
        humans = set(self._human_ids())
        self.match_view.show()
        self.message_view.hide()
        self.hero_eyebrow.setText("NEXT MATCH")
        venue = report.venue_name(self.ds, f)
        when = calendar.short_date(calendar.fixture_date(t, f))
        # neutral: said once, by the venue, not as a tag on both teams
        self.hero_venue.setText(" · ".join(x for x in (f.label, when, venue,
                                                       "neutral venue" if f.neutral else "") if x)
                                .upper())
        self.hero_weather.setText(weather.forecast(t, f, self.ds)["summary"].upper() if f.stadium_id else "")
        for block, tid, label in ((self.home_block, f.home, "home"), (self.away_block, f.away, "away")):
            block.set_team(self.ds, t, tid, "" if f.neutral else label, tid in humans)

    def _show_message(self, eyebrow, kicker, title, info, crest=None):
        self.match_view.hide()
        self.message_view.show()
        self.hero_eyebrow.setText(eyebrow.upper())
        self.hero_venue.setText("")
        self.hero_weather.setText("")
        self.msg_kicker.setText(kicker.upper())
        self.msg_kicker.setVisible(bool(kicker))
        self.msg_title.setText(title.upper())
        self.msg_info.setText(info)
        self.msg_crest.set_pixmap(crest)
        self.msg_crest.setVisible(crest is not None)

    def _refresh_overview(self):
        t = self.t
        self.banner_text.setText(self._message)
        self.banner.setVisible(bool(self._message))
        due = self.session.human_fixture()
        upcoming = due or self._upcoming_human()
        humans = self._human_ids()
        alive = [h for h in humans if not engine.is_eliminated(t, h)]
        for b in (self.play_btn, self.sim_btn, self.continue_btn, self.sim_end_btn, self.enter_btn):
            b.setVisible(False)
        self.next_avail.setText("")
        if t.finished:
            final = next((f for f in reversed(t.fixtures) if f.final and f.result), None)
            won = t.champion in humans
            info = [f"Final: {report.fixture_caption(t, final)} {final.result.score_text()}" if final else ""]
            info += [f"{t.team_name(h)}: {report.campaign_summary(t, h)}" for h in humans if h != t.champion]
            info.append("See the stats tab for the awards.")
            self._show_message("tournament over", "champions" if not won else "★ you are champions",
                               t.team_name(t.champion), "  ·  ".join(x for x in info if x),
                               tournament_crest(self.ds, t, t.champion, 120))
        elif due:
            self._show_match(due)
            out = []
            for tid in (due.home, due.away):
                if t.teams[tid].human:
                    for pid, reason in report.availability(t, tid):
                        out.append(f"{t.player_name(pid)} ({reason})")
            self.next_avail.setText(f"⚠  {len(out)} unavailable: " + ", ".join(out) if out else "")
            for b in (self.play_btn, self.sim_btn):
                b.setVisible(True)
            self.enter_btn.setVisible(user_prefs.expert_mode)
        elif upcoming:
            self._show_match(upcoming)
            self.next_avail.setText("The other teams play first — CONTINUE simulates their matches.")
            for b in (self.continue_btn, self.sim_end_btn):
                b.setVisible(True)
        else:
            if not humans:
                title, info = "spectator mode", "Simulate the tournament to see who wins."
            elif not alive:
                title = "your campaign is over"
                info = "  ·  ".join([f"{t.team_name(h)}: {report.campaign_summary(t, h)}" for h in humans]
                                    + ["Simulate the rest of the tournament to see who wins."])
            else:
                title, info = "waiting for the draw", "Simulate the remaining matches to find your opponent."
            self._show_message("out of the running" if humans and not alive else "waiting", "",
                               title, info,
                               tournament_crest(self.ds, t, humans[0], 120) if humans else None)
            self.sim_end_btn.setVisible(True)
        self.undo_btn.setVisible(self.session.can_undo())
        self.next_avail.setVisible(bool(self.next_avail.text()))

        self._refresh_side()

        clear_layout(self.latest_grid)
        playedf = [f for f in t.fixtures if f.played]
        last_day = max(f.day for f in playedf) if playedf else None
        recent = [f for f in playedf if f.day == last_day] if last_day is not None else []
        mine = set(humans)
        recent.sort(key=lambda f: not (f.home in mine or f.away in mine))
        if not recent:
            self.latest_grid.addWidget(Note("No match played yet.", color=FG_MUTED), 0, 0)
        for i, f in enumerate(recent[:8]):
            card = ScoreCard(self.ds, t, f, highlight=mine)
            card.activated.connect(lambda fid=f.id: self._report(fid))
            self._register_dynamic(card)
            self.latest_grid.addWidget(card, i // 2, i % 2)

        clear_layout(self.news_list)
        news = list(reversed(t.news))[:6]
        if not news:
            self.news_list.addWidget(Note("  No news yet.", color=FG_MUTED))
        for n in news:
            self.news_list.addWidget(NewsItem(n, compact=True))

    def _refresh_side(self):
        """Your pool's table while the pool stage runs, your knockout path
        after it (or the first pool when nobody is managed)."""
        t = self.t
        clear_layout(self.side_holder)
        humans = set(self._human_ids())
        stage, group = None, None
        for st in t.stages:
            if st.kind != "round_robin":
                continue
            for g in st.groups:
                if humans & set(g.teams):
                    stage, group = st, g
                    break
            if group:
                break
        ko_mine = [f for f in t.fixtures if f.knockout and (f.home in humans or f.away in humans)]
        if ko_mine or (stage is None and any(f.knockout for f in t.fixtures)):
            self.side_title.set_title("your path" if humans else "knockouts")
            self.side_title.set_right("")
            ties = ko_mine or [f for f in t.fixtures if f.knockout][-4:]
            for f in ties:
                card = ScoreCard(self.ds, t, f, highlight=humans)
                card.activated.connect(lambda fid=f.id: self._report(fid))
                self._register_dynamic(card)
                self.side_holder.addWidget(card)
            return
        if group is None:
            st = next((s for s in t.stages if s.kind == "round_robin" and s.groups), None)
            if not st:
                return
            stage, group = st, st.groups[0]
        self.side_title.set_title(group.name if len(stage.groups) > 1 else stage.name)
        qualify = int(stage.spec.get("qualify", 0))
        self.side_title.set_right(f"top {qualify} qualify" if qualify else "")
        table = self._standings_table(t, stage, group, compact=True)
        self.side_holder.addWidget(table)

    # ── standings ────────────────────────────────────────────────────────
    def _standings_table(self, t, stage, group, compact=False):
        humans = set(self._human_ids())
        qualify = int(stage.spec.get("qualify", 0))
        bonus = standings.has_bonus(t.template.get("points"))
        if compact:
            cols = ["#", "Team", "P", "+/-", "Pts", "Form"]
            widths = {0: 34, 2: 36, 3: 52, 4: 48, 5: 106}
        else:
            # no BP column for a competition without bonus points (Six Nations before 2017)
            cols = ["#", "Team", "P", "W", "D", "L", "PF", "PA", "+/-", "BP", "Pts", "Form"]
            widths = {0: 36, 2: 36, 3: 36, 4: 36, 5: 36, 6: 46, 7: 46, 8: 54, 9: 40, 10: 50, 11: 110}
            if not bonus:
                cols.remove("BP")
                widths = {0: 36, 2: 36, 3: 36, 4: 36, 5: 36, 6: 46, 7: 46, 8: 54, 9: 50, 10: 110}
        centred = {i: Qt.AlignHCenter for i, c in enumerate(cols) if c not in ("Team", "Form")}
        table = DataTable(cols, stretch_col=1, widths=widths, header_align=centred)
        rows, tint, rules = [], {}, set()
        tab = standings.group_table(t, stage, group)
        for i, r in enumerate(tab):
            crest = tournament_crest(self.ds, t, r.team_id, 22)
            name = {"text": t.team_name(r.team_id), "icon": crest,
                    "bold": r.team_id in humans, "color": YOU_TINT if r.team_id in humans else None}
            pos = {"text": i + 1, "color": GREEN if i < qualify else FG_TERTIARY, "align": Qt.AlignHCenter}
            pts = {"text": r.points, "bold": True, "align": Qt.AlignHCenter}
            diff = {"text": f"{r.points_diff:+d}", "align": Qt.AlignHCenter,
                    "color": GREEN if r.points_diff > 0 else (FG_TERTIARY if r.points_diff == 0 else WARN)}
            form = {"text": "", "form": "".join(r.form[-5:])}
            c = lambda v: {"text": v, "align": Qt.AlignHCenter}  # noqa: E731
            if compact:
                rows.append([pos, name, c(r.played), diff, pts, form])
            else:
                row = [pos, name, c(r.played), c(r.won), c(r.drawn), c(r.lost), c(r.points_for),
                       c(r.points_against), diff, c(r.bonus), pts, form]
                rows.append(row if bonus else row[:9] + row[10:])
            if r.team_id in humans:
                tint[i] = YOU_TINT
            if qualify and i == qualify - 1 and i < len(tab) - 1:
                rules.add(i)
        table.set_rows(rows, keys=[r.team_id for r in tab], tint=tint, rules=rules)
        table.fit_height()
        self._register_dynamic(table)
        return table

    def _refresh_standings(self):
        clear_layout(self.standings_holder)
        t = self.t
        groups = [(st, g) for st in t.stages if st.kind == "round_robin" for g in st.groups]
        if not groups:
            self.standings_holder.addWidget(Note("This competition has no league table.", color=FG_MUTED))
            self.standings_holder.addStretch(1)
            return
        two_up = len(groups) > 1
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(18)
        for i, (st, g) in enumerate(groups):
            qualify = int(st.spec.get("qualify", 0))
            w, v = section(g.name if len(st.groups) > 1 else st.name,
                           right=f"top {qualify} qualify" if qualify else "")
            v.addWidget(self._standings_table(t, st, g))
            if two_up:
                grid.addWidget(w, i // 2, i % 2)
            else:
                grid.addWidget(w, i, 0)
        self.standings_holder.addLayout(grid)
        self.standings_holder.addStretch(1)

    # ── fixtures ─────────────────────────────────────────────────────────
    def _set_mine(self, mine):
        self._mine_only = mine
        from ui.widgets import style_button
        style_button(self.fx_all, "neutral" if mine else "primary")
        style_button(self.fx_mine, "primary" if mine else "neutral")
        for b in (self.fx_all, self.fx_mine):
            b.setStyleSheet(b.styleSheet() + "QPushButton { padding: 4px 10px; letter-spacing: 1px; }")
        self._refresh_fixtures()

    def _refresh_fixtures(self):
        t = self.t
        humans = set(self._human_ids())
        self.fx_mine.setVisible(bool(humans))
        rows, keys, tint = [], [], {}
        day = None
        for f in sorted(t.fixtures, key=lambda f: f.day):      # stable: keeps pool order within a day
            if self._mine_only and not (f.home in humans or f.away in humans):
                continue
            if f.day != day:
                day = f.day
                state = "current" if day == t.day and not t.finished else (
                    "played" if day < t.day else "")
                when = calendar.short_date(calendar.fixture_date(t, f))
                title = f.round_name or f"Round {day + 1}"
                rows.append(Section(title + (f" · {when}" if when else ""), state, gap=bool(rows)))
                keys.append(None)
            score = (f.result.score_text() if f.result else "v")
            win = f.result.winner_id() if f.result else None
            home_name = t.team_name(f.home) if f.home else _ref(t, f.home_ref)
            away_name = t.team_name(f.away) if f.away else _ref(t, f.away_ref)
            rows.append([
                {"text": _without_round(f), "color": FG_TERTIARY},
                {"text": home_name, "icon": tournament_crest(self.ds, t, f.home, 22),
                 "align": Qt.AlignRight, "bold": win is not None and win == f.home,
                 "color": YOU_TINT if f.home in humans else (FG_MUTED if not f.home else None)},
                {"text": score, "align": Qt.AlignHCenter, "bold": bool(f.result),
                 "color": FG_PRIMARY if f.result else FG_MUTED},
                {"text": away_name, "icon": tournament_crest(self.ds, t, f.away, 22),
                 "bold": win is not None and win == f.away,
                 "color": YOU_TINT if f.away in humans else (FG_MUTED if not f.away else None)},
                {"text": report.venue_name(self.ds, f), "color": FG_TERTIARY},
            ])
            keys.append(f.id)
            if f.home in humans or f.away in humans:
                tint[len(rows) - 1] = YOU_TINT
        self.fixtures.set_rows(rows, keys=keys, tint=tint)
        nxt = next((f for f in sorted(t.fixtures, key=lambda f: f.day)
                    if not f.played and f.id in keys), None)
        if nxt and self.fixtures.current_key() is None:
            self.fixtures.select_key(nxt.id)
            self.fixtures.scrollTo(self.fixtures.currentIndex(), DataTable.PositionAtCenter)

    # ── bracket ──────────────────────────────────────────────────────────
    def _refresh_bracket(self):
        clear_layout(self.bracket_holder)
        t = self.t
        if not any(f.knockout for f in t.fixtures):
            self.bracket_holder.addWidget(Note("This competition has no knockout stage.", color=FG_MUTED))
            self.bracket_holder.addStretch(1)
            return
        view = BracketView(self.ds, t, self._human_ids())
        view.report.connect(self._report)
        self._register_dynamic(view)
        row = QHBoxLayout()
        row.addWidget(view)
        row.addStretch(1)
        self.bracket_holder.addLayout(row)
        self.bracket_holder.addStretch(1)

    # ── stats ────────────────────────────────────────────────────────────
    def _leader_card(self, key, title):
        t = self.t
        w, v = section(title)
        leaders = stats.leaders(t, key, 8)
        card = Card(translucent=True)
        cv = QVBoxLayout(card)
        cv.setContentsMargins(18, 14, 18, 14)
        cv.setSpacing(8)
        if not leaders:
            cv.addWidget(Note("No data yet.", color=FG_MUTED))
            v.addWidget(card)
            return w
        pid, n = leaders[0]
        team = t.players[pid].team_id if pid in t.players else None
        top = QHBoxLayout()
        top.setSpacing(14)
        top.addWidget(PixmapLabel(52, tournament_crest(self.ds, t, team, 52)))
        nv = QVBoxLayout()
        nv.setSpacing(0)
        nv.addWidget(display_label(t.player_name(pid), 18, QFont.Bold, track=0.6))
        nv.addWidget(eyebrow_label(t.team_name(team), color=FG_TERTIARY, size=10))
        top.addLayout(nv, stretch=1)
        top.addWidget(display_label(str(n), 30, QFont.Bold, track=0.5, color=AWAY_TINT))
        cv.addLayout(top)
        if len(leaders) > 1:
            table = DataTable(["#", "Player", "Team", ""], stretch_col=1, widths={0: 34, 3: 52})
            table.set_rows([[{"text": i + 2, "color": FG_TERTIARY, "align": Qt.AlignHCenter},
                             t.player_name(p),
                             {"text": t.team_name(t.players[p].team_id) if p in t.players else "",
                              "icon": tournament_crest(self.ds, t, t.players[p].team_id if p in t.players else None, 20),
                              "color": FG_SECONDARY},
                             {"text": val, "bold": True, "align": Qt.AlignHCenter}]
                            for i, (p, val) in enumerate(leaders[1:])])
            table.horizontalHeader().hide()
            table.fit_height()
            self._register_dynamic(table)
            cv.addWidget(table)
        v.addWidget(card)
        return w

    def _refresh_stats(self):
        clear_layout(self.stats_holder)
        t = self.t
        cols = QHBoxLayout()
        cols.setSpacing(18)
        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(18)
        boards = [("points", "Top points"), ("tries", "Top tries"), ("tackles", "Tackles"),
                  ("motm", "Player of the match awards")]
        for i, (key, title) in enumerate(boards):
            grid.addWidget(self._leader_card(key, title), i // 2, i % 2)
        cols.addLayout(grid, stretch=3)
        w, v = section("team of the tournament" + ("" if t.finished else " · so far"))
        pitch = LineupPitch(interactive=False, bench=False)
        # team_of_the_tournament is one (position, pid) per XV slot, in
        # shirt order.
        slots = [{"number": n} for n in range(1, 16)]
        for i, (_pos, pid) in enumerate(stats.team_of_the_tournament(t)):
            if i < 15:
                tid = t.players[pid].team_id if pid in t.players else None
                slots[i].update({"name": t.player_name(pid), "sub": t.team_name(tid), "ring": YOU_TINT
                                 if tid in set(self._human_ids()) else FG_SECONDARY})
        for s in slots:
            s.setdefault("faded", "name" not in s)
        pitch.set_slots(slots)
        pitch.setFixedHeight(560)
        v.addWidget(pitch)
        v.addStretch(1)
        cols.addWidget(w, stretch=2)
        self.stats_holder.addLayout(cols)
        self.stats_holder.addStretch(1)

    # ── news ─────────────────────────────────────────────────────────────
    def _refresh_news(self):
        clear_layout(self.news_holder)
        news = list(reversed(self.t.news))[:200]
        if not news:
            self.news_holder.addWidget(Note("No news yet.", color=FG_MUTED))
        day, card, lay = None, None, None
        for n in news:
            if n["day"] != day:
                day = n["day"]
                w, v = section(f"matchday {day + 1}")
                card = Card(translucent=True)
                lay = QVBoxLayout(card)
                lay.setContentsMargins(6, 4, 6, 4)
                lay.setSpacing(0)
                v.addWidget(card)
                self.news_holder.addWidget(w)
            lay.addWidget(NewsItem(n, show_day=False))
        self.news_holder.addStretch(1)

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
        if not f:
            return

        def go(role):
            if role == "ok":
                self.set_message(self._summary(self.session.simulate(f)))
        ConfirmDialog(self, "Simulate your match?",
                      f"{report.fixture_caption(self.t, f)} is decided by the simulator instead of "
                      "being played. You can UNDO it afterwards.",
                      [("CANCEL", "neutral", "cancel"), ("SIMULATE", "primary", "ok")], go)

    def _enter_result(self):
        f = self.session.human_fixture()
        if not f:
            return
        self.session.prepare(f)
        view = ManualResultView(self.t, f)

        def go(role):
            if role == "ok":
                self.set_message(self._summary(self.session.enter_result(f, view.result())))
        ConfirmDialog(self, "Enter the result",
                      f"{report.fixture_caption(self.t, f)}: add the scoring events, cards and "
                      "injuries. The score follows from them. You can UNDO it afterwards.",
                      [("CANCEL", "neutral", "cancel"), ("RECORD", "primary", "ok")], go,
                      content=view, width=760)

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

    def _leave(self):
        def go(role):
            if role == "ok":
                self.on_back_cb()
        ConfirmDialog(self, "Back to the main menu?",
                      "Your tournament is saved: open it again from Game modes > Tournament.",
                      [("STAY", "neutral", "cancel"), ("MAIN MENU", "primary", "ok")], go)

    def _undo(self):
        def go(role):
            if role == "ok" and self.session.undo():
                self.set_message("Last step undone.")
        ConfirmDialog(self, "Undo the last step?",
                      "The results recorded by the last action are removed (only one step can be undone).",
                      [("CANCEL", "neutral", "cancel"), ("UNDO", "danger", "ok")], go)

    def _refresh_team(self):
        """Manage your team: the team of the next match you play, else your first."""
        humans = self._human_ids()
        if not humans:
            return
        due = self.session.human_fixture() or self._upcoming_human()
        team = next((tid for tid in ((due.home, due.away) if due else ()) if tid in humans), humans[0])
        if self.squad.session is not self.session or self.squad.team_id not in humans:
            self.squad.set_team(self.session, team)
        else:
            self.squad.refresh()

    def _report(self, fid):
        f = self.t.fixture(fid) if fid else None
        if not f or not f.played:
            return
        ConfirmDialog(self, f.label, "", [("CLOSE", "primary", "ok")], lambda _r: None,
                      cancel_role="ok", content=MatchReportView(self.ds, self.t, f), width=760)


def _ref(t, ref):
    from .common import ref_label
    return ref_label(t, ref)


class MatchReportView(QWidget):
    """A played match: crests, score, scorers side by side, cards, injuries,
    player of the match."""

    def __init__(self, ds, t, f, parent=None):
        super().__init__(parent)
        transparent(self, "matchReport")
        r = f.result
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        top = QHBoxLayout()
        top.setSpacing(14)
        winner = r.winner_id()
        for i, side in enumerate((r.home, r.away)):
            block = QHBoxLayout()
            block.setSpacing(12)
            crest = PixmapLabel(64, tournament_crest(ds, t, side.team_id, 64))
            name = display_label(t.team_name(side.team_id), 18, QFont.Bold, track=0.6,
                                 color=FG_PRIMARY if side.team_id == winner or not winner else FG_TERTIARY)
            name.setWordWrap(True)
            if i == 0:
                block.addWidget(crest)
                block.addWidget(name, stretch=1)
            else:
                name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
                block.addWidget(name, stretch=1)
                block.addWidget(crest)
            top.addLayout(block, stretch=1)
            if i == 0:
                score = display_label(f"{r.home.points} – {r.away.points}", 34, QFont.Bold, track=1.0)
                score.setAlignment(Qt.AlignCenter)
                top.addWidget(score)
        v.addLayout(top)
        meta = [calendar.short_date(calendar.fixture_date(t, f)), report.venue_name(ds, f),
                weather.forecast(t, f, ds)["summary"] if f.stadium_id else "",
                {"game": "played in the game", "forfeit": "awarded (forfeit)",
                 "manual": "entered manually"}.get(r.source, "simulated")]
        if r.decided_by:
            meta.append(r.score_text().split(" ", 1)[-1].strip("()"))
        v.addWidget(eyebrow_label("  ·  ".join(m for m in meta if m), color=FG_TERTIARY, size=10))
        v.addWidget(hline())
        cols = QHBoxLayout()
        cols.setSpacing(24)
        for side in (r.home, r.away):
            col = QVBoxLayout()
            col.setSpacing(6)
            any_line = False
            for key, label in (("tries", "tries"), ("conversions", "conversions"), ("penalties", "penalties"),
                               ("drop_goals", "drop goals")):
                s = report._scorers(t, side, key)
                if s:
                    any_line = True
                    col.addWidget(eyebrow_label(label, color=ACCENT, size=9))
                    col.addWidget(Note(s, color=FG_PRIMARY))
            if side.penalty_tries:
                any_line = True
                col.addWidget(Note(f"Penalty tries: {side.penalty_tries}", color=FG_PRIMARY))
            cards = [(t.player_name(l.pid), "red" if l.red_cards else "yellow")
                     for l in side.players if l.red_cards or l.yellow_cards]
            if cards:
                any_line = True
                col.addWidget(eyebrow_label("cards", color=ACCENT, size=9))
                row = QHBoxLayout()
                row.setSpacing(6)
                for name, kind in cards:
                    row.addWidget(Tag(name, "#e0202b" if kind == "red" else "#f2c14e"))
                row.addStretch(1)
                col.addLayout(row)
            hurt = [t.player_name(l.pid) for l in side.players if l.injured and l.pid]
            if hurt:
                any_line = True
                col.addWidget(eyebrow_label("injured", color=WARN, size=9))
                col.addWidget(Note(", ".join(hurt), color=WARN))
            if not any_line:
                col.addWidget(Note("No scorers.", color=FG_MUTED))
            col.addStretch(1)
            cols.addLayout(col, stretch=1)
        v.addLayout(cols)
        motm = r.extra.get("motm")
        if motm:
            v.addWidget(hline())
            row = QHBoxLayout()
            row.addWidget(Tag("player of the match", AWAY_TINT))
            row.addWidget(display_label(t.player_name(motm), 14, QFont.Bold, track=0.6, upper=False))
            row.addStretch(1)
            v.addLayout(row)
