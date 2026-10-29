"""
screens/tournament/dashboard.py — The running tournament.

The header (the competition's logo, the tournament's name) over five tabs:

  Home         where the tournament stands (stage, progress), the next
               match as a broadcast-style hero card with ONE primary action
               (PLAY MATCH / CONTINUE / SIMULATE TO END), your pool or
               knockout path, the last matchday, three headlines
  Squad        the matchday squad (screens.tournament.squad)
  Competition  Table / Fixtures / Bracket
  Stats        leader boards, team of the tournament on a pitch
  News         every headline, by matchday

Home stays glanceable: the secondary actions (simulate, enter a result,
simulate to the end, undo) sit in the MORE menu, the full match details
(form, positions, weather, unavailable players) in MATCH DETAILS.

Whatever an action plays is shown as it happens (screens.tournament.
moments): the matchday recap, a new stage, elimination, the champions.

Every action goes through the TournamentSession, which saves after each
step. Pad: Q/E switch tabs, A select, X Competition view, Y more, B back.
"""
from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QStackedWidget, QVBoxLayout, QWidget

from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.tournament import calendar, engine, report, standings, stats, weather
from shared.user_prefs import user_prefs
from ui import motion
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, page_header
from ui.dropdown import PopupList
from ui.editor_kit import ConfirmDialog, Note, TabPage, TabStrip, compact_button
from ui.stat_compare import StatComparison
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BTN_HEIGHT, DANGER_LITE, FG_MUTED, FG_PRIMARY,
                      FG_SECONDARY, FG_TERTIARY, GREEN, INFO, WARN)
from ui.widgets import style_button

from . import moments
from .bracket import BracketView
from .common import (DataTable, FormStrip, NewsItem, PixmapLabel, ProgressStrip,
                     ScoreCard, Section, SectionTitle, Tag, YOU_TINT, clear_layout,
                     competition_emblem, hline, section, tournament_crest, transparent)
from .manual_result import ManualResultView
from .pitch import LineupPitch
from .squad import TournamentSquadScreen

TABS = ["Home", "Squad", "Competition", "Stats", "News"]
HOME, TEAM, COMP, STATS, NEWS = range(len(TABS))
VIEWS = ["Table", "Fixtures", "Bracket"]
TABLE, FIXTURES, BRACKET = range(len(VIEWS))

LATEST_SHOWN = 4          # result cards on Home (yours first)
HEADLINES_SHOWN = 3       # news items on Home


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


def stage_progress(t):
    """(caption, 0..1) of where the tournament stands: "POOL STAGE ·
    MATCHDAY 3 OF 7", the share of matchdays played."""
    last = t.last_day()
    if t.finished:
        return "tournament complete", 1.0
    nxt = next((f for f in sorted(t.fixtures, key=lambda f: f.day) if not f.played), None)
    stage = t.stage(nxt.stage_id) if nxt else None
    where = (nxt.round_name if nxt and nxt.knockout and nxt.round_name else (stage.name if stage else ""))
    caption = " · ".join(x for x in (where, f"matchday {t.day + 1} of {last + 1}") if x)
    return caption, (t.day / (last + 1)) if last >= 0 else 0.0


class _TeamBlock(QWidget):
    """One side of the hero card: crest, name, tags, form."""

    CREST = 116

    def __init__(self, side):
        super().__init__()
        transparent(self, f"hero{side}")
        self.side = side
        right = side == "away"
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(18)
        self.crest = PixmapLabel(self.CREST)
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
        self.crest.set_pixmap(tournament_crest(ds, t, team_id, self.CREST))
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
        self._view = TABLE
        self._dynamic = []            # focusable widgets rebuilt on refresh
        self._pending = None          # (before, done) to play as moments on show
        self._playing = False         # moments on screen: no refresh animation under them
        self._primary = None          # what the hero's primary button does
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

        top = QHBoxLayout()
        top.setSpacing(18)
        self.tabs = TabStrip(TABS)
        self.tabs.changed.connect(self._tab_changed)
        self.focus.register(self.tabs)
        top.addWidget(self.tabs, stretch=1)
        # where the tournament stands, always in view
        prog = QVBoxLayout()
        prog.setSpacing(5)
        prog.addStretch(1)
        self.stage_line = eyebrow_label("", color=FG_TERTIARY, size=10)
        self.stage_line.setAlignment(Qt.AlignRight)
        prog.addWidget(self.stage_line)
        self.progress = ProgressStrip(height=5)
        self.progress.setFixedWidth(280)
        prog.addWidget(self.progress, alignment=Qt.AlignRight)
        prog.addStretch(1)
        top.addLayout(prog)
        bv.addLayout(top)

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

        self._build_home(self.pages[HOME].layout_)
        # the squad screen without its own header / hint bar; B goes back
        # to the tabs
        self.squad = TournamentSquadScreen(on_back=lambda: self.tabs.setFocus(), embedded=True)
        self.pages[TEAM].layout_.addWidget(self.squad, stretch=1)
        self._build_competition(self.pages[COMP].layout_)
        self.stats_holder = self.pages[STATS].layout_
        self.news_holder = self.pages[NEWS].layout_

        self.hints = HintBar()
        root.addWidget(self.hints)
        self._update_hints()

    def _build_home(self, v):
        # system messages only (an abandoned match, undo...): results are
        # shown by the matchday recap instead
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
        hv.setSpacing(14)
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

        self.next_avail = Note("", color=FG_TERTIARY)
        hv.addWidget(self.next_avail)
        hv.addWidget(hline())
        row = QHBoxLayout()
        row.setSpacing(10)
        # the details live behind these two; the hero shows one action
        self.details_btn = compact_button("MATCH DETAILS", "ghost", height=BTN_HEIGHT)
        self.details_btn.clicked.connect(self._match_details)
        self.more_btn = compact_button("MORE  ▾", "neutral", height=BTN_HEIGHT)
        self.more_btn.setMinimumWidth(130)
        self.more_btn.clicked.connect(self._more_menu)
        self.primary_btn = compact_button("PLAY MATCH", "primary", height=BTN_HEIGHT)
        self.primary_btn.setMinimumWidth(240)
        self.primary_btn.clicked.connect(lambda: self._primary and self._primary())
        row.addWidget(self.details_btn)
        row.addStretch(1)
        row.addWidget(self.more_btn)
        row.addWidget(self.primary_btn)
        # Registration order = where focus starts: the primary action first.
        for b in (self.primary_btn, self.more_btn, self.details_btn):
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
        self.side_more = compact_button("FULL TABLE  →", "ghost")
        self.side_more.clicked.connect(lambda: self._open_view(TABLE))
        self.focus.register(self.side_more)
        sv.addWidget(self.side_more, alignment=Qt.AlignRight)
        sv.addStretch(1)
        top.addWidget(side, stretch=2)
        v.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(18)
        w, lv = section("last matchday")
        self.latest_title = w.title
        self.latest_grid = QGridLayout()
        self.latest_grid.setHorizontalSpacing(10)
        self.latest_grid.setVerticalSpacing(10)
        lv.addLayout(self.latest_grid)
        self.latest_more = compact_button("ALL RESULTS  →", "ghost")
        self.latest_more.clicked.connect(lambda: self._open_view(FIXTURES))
        self.focus.register(self.latest_more)
        lv.addWidget(self.latest_more, alignment=Qt.AlignRight)
        lv.addStretch(1)
        bottom.addWidget(w, stretch=3)
        w, rv = section("headlines")
        self.news_card = Card(translucent=True)
        self.news_list = QVBoxLayout(self.news_card)
        self.news_list.setContentsMargins(6, 4, 6, 4)
        self.news_list.setSpacing(0)
        rv.addWidget(self.news_card)
        self.news_more = compact_button("ALL NEWS  →", "ghost")
        self.news_more.clicked.connect(lambda: self._go_tab(NEWS))
        self.focus.register(self.news_more)
        rv.addWidget(self.news_more, alignment=Qt.AlignRight)
        rv.addStretch(1)
        bottom.addWidget(w, stretch=2)
        v.addLayout(bottom)
        v.addStretch(1)

    def _build_competition(self, v):
        row = QHBoxLayout()
        row.setSpacing(8)
        self.view_btns = []
        for i, name in enumerate(VIEWS):
            b = compact_button(name.upper(), "primary" if i == TABLE else "neutral")
            b.clicked.connect(lambda _=False, i=i: self._set_view(i))
            row.addWidget(b)
            self.focus.register(b)
            self.view_btns.append(b)
        row.addSpacing(24)
        # fixtures only: all matches or yours
        self.fx_all = compact_button("ALL MATCHES", "primary")
        self.fx_mine = compact_button("YOUR MATCHES", "neutral")
        self.fx_all.clicked.connect(lambda: self._set_mine(False))
        self.fx_mine.clicked.connect(lambda: self._set_mine(True))
        for b in (self.fx_all, self.fx_mine):
            row.addWidget(b)
            self.focus.register(b)
        row.addStretch(1)
        self.comp_note = Note("", color=FG_TERTIARY)
        row.addWidget(self.comp_note)
        v.addLayout(row)

        self.view_pages = QStackedWidget()
        table_page = transparent(QWidget(), "compTable")
        self.standings_holder = QVBoxLayout(table_page)
        self.standings_holder.setContentsMargins(0, 0, 0, 0)
        self.standings_holder.setSpacing(16)
        fixtures_page = transparent(QWidget(), "compFixtures")
        fv = QVBoxLayout(fixtures_page)
        fv.setContentsMargins(0, 0, 0, 0)
        self.fixtures = DataTable(["Round", "Home", "", "Away", "Venue"], stretch_col=1,
                                  widths={0: 190, 2: 120, 3: 300, 4: 200},
                                  header_align={1: Qt.AlignRight})
        self.fixtures.activated_row.connect(lambda r: self._report(self.fixtures.keys[r]))
        self.focus.register(self.fixtures)
        fv.addWidget(self.fixtures, stretch=1)
        bracket_page = transparent(QWidget(), "compBracket")
        self.bracket_holder = QVBoxLayout(bracket_page)
        self.bracket_holder.setContentsMargins(0, 0, 0, 0)
        for page in (table_page, fixtures_page, bracket_page):
            self.view_pages.addWidget(page)
        v.addWidget(self.view_pages, stretch=1)

    # ── entry ────────────────────────────────────────────────────────────
    def set_session(self, session, message=""):
        self.session = session
        self._message = message
        self._pending = None
        clear_layout(self.header_holder)
        t = session.t
        self.header_holder.addWidget(page_header(t.name,
                                                 icon=competition_emblem(self.ds, t.template, 52)))
        self._has_bracket = any(s.kind == "knockout" for s in t.stages)
        self.view_btns[BRACKET].setVisible(self._has_bracket)
        self._has_table = any(s.kind == "round_robin" for s in t.stages)
        self.view_btns[TABLE].setVisible(self._has_table)
        self._view = TABLE if self._has_table else FIXTURES
        self.tabs.set_index(0, notify=False)
        self.stack.setCurrentIndex(0)
        self.refresh()

    def set_message(self, text):
        self._message = text
        self.refresh()

    def queue_moments(self, before, done):
        """Matches just played outside this screen (in the game): shown as
        moments the next time the dashboard opens."""
        self._pending = (before, done)

    def on_show(self):
        super().on_show()
        if self.session:
            self.refresh()
            if self.tabs.index() == HOME and self.primary_btn.isVisible():
                self.primary_btn.setFocus()
            if self._pending:
                before, done = self._pending
                self._pending = None
                # after the screen has settled (shell.present) and painted once
                QTimer.singleShot(0, lambda: self._play_moments(before, done))

    def _tab_changed(self, i):
        self.stack.setCurrentIndex(i)
        self.refresh()
        motion.fade_in(self.stack.currentWidget(), ms=180)
        self._update_hints()

    def _go_tab(self, i):
        self.tabs.set_index(i)

    def _open_view(self, view):
        self._set_view(view, refresh=False)
        if self.tabs.index() != COMP:
            self.tabs.set_index(COMP)
        else:
            self.refresh()

    def _update_hints(self):
        hints = [("A", "select"), ("LB", "prev tab"), ("RB", "next tab")]
        if self.tabs.index() == COMP:
            hints.append(("X", "change view"))
        elif self.tabs.index() == HOME and self.more_btn.isVisible():
            hints.append(("Y", "more"))
        self.hints.set_hints(hints + [("B", "back")])

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
        if action == Action.ALT and self.tabs.index() == COMP:
            shown = [i for i, b in enumerate(self.view_btns) if not b.isHidden()]
            if shown:
                self._set_view(shown[(shown.index(self._view) + 1) % len(shown)]
                               if self._view in shown else shown[0])
            event.accept()
            return
        if action == Action.AUX and self.tabs.index() == HOME and self.more_btn.isVisible():
            self._more_menu()
            event.accept()
            return
        super().keyPressEvent(event)

    def _register_dynamic(self, w):
        self.focus.register(w)
        self._dynamic.append(w)
        return w

    def refresh(self, animate=False):
        if not self.session:
            return
        for w in self._dynamic:
            self.focus.unregister(w)
        self._dynamic = []
        caption, frac = stage_progress(self.t)
        self.stage_line.setText(caption.upper())
        self.progress.set_value(frac, AWAY_TINT if self.t.finished else ACCENT)
        i = self.tabs.index()
        self._refresh_home(animate)
        if i == TEAM:
            self._refresh_team()
        elif i == COMP:
            self._refresh_competition()
        elif i == STATS:
            self._refresh_stats()
        elif i == NEWS:
            self._refresh_news()
        self._update_hints()

    # ── home ─────────────────────────────────────────────────────────────
    def _human_ids(self):
        return [e.team_id for e in self.t.human_teams()]

    def _upcoming_human(self):
        """Next unplayed fixture for any human team (may be a later day)."""
        humans = set(self._human_ids())
        return next((f for f in self.t.fixtures if not f.played and (f.home in humans or f.away in humans)),
                    None)

    def _shown_fixture(self):
        """The fixture the hero shows (due now, or your next one)."""
        if not self.session or self.t.finished:
            return None
        return self.session.human_fixture() or self._upcoming_human()

    def _show_match(self, f):
        t = self.t
        humans = set(self._human_ids())
        self.match_view.show()
        self.message_view.hide()
        self.hero_eyebrow.setText("NEXT MATCH" if f.ready else "COMING UP")
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

    def _set_primary(self, text, action):
        self._primary = action
        self.primary_btn.setText(text)
        self.primary_btn.setVisible(action is not None)

    def _more_items(self):
        """(label, data, subtitle) of the MORE menu in the current state."""
        t = self.t
        due = self.session.human_fixture()
        out = []
        if due:
            out.append(("Simulate this match", "simulate", "the simulator decides it"))
            if user_prefs.expert_mode:
                out.append(("Enter the result", "enter", "type in the score and events"))
        if not t.finished and self._human_ids() and (due or self._upcoming_human()):
            out.append(("Simulate to the end", "sim_end", "every match left, yours included"))
        if self._my_played():
            out.append(("Your matches", "mine", "results and stats of every match you played"))
        if self.session.can_undo():
            out.append(("Undo last step", "undo", "only one step back"))
        return out

    def _my_played(self):
        """Your teams' played fixtures, newest first."""
        humans = set(self._human_ids())
        return [f for f in reversed(self.t.fixtures) if f.played and (f.home in humans or f.away in humans)]

    def _refresh_home(self, animate=False):
        t = self.t
        self.banner_text.setText(self._message)
        self.banner.setVisible(bool(self._message))
        due = self.session.human_fixture()
        upcoming = due or self._upcoming_human()
        humans = self._human_ids()
        alive = [h for h in humans if not engine.is_eliminated(t, h)]
        self.next_avail.setText("")
        self.details_btn.setVisible(False)
        if t.finished:
            won = t.champion in humans
            final = next((f for f in reversed(t.fixtures) if f.final and f.result), None)
            info = [f"Final: {report.fixture_caption(t, final)} {final.result.score_text()}" if final else ""]
            info += [f"{t.team_name(h)}: {report.campaign_summary(t, h)}" for h in humans if h != t.champion]
            self._show_message("tournament over", "champions" if not won else "★ you are champions",
                               t.team_name(t.champion), "  ·  ".join(x for x in info if x),
                               tournament_crest(self.ds, t, t.champion, 120))
            self._set_primary("SEE THE AWARDS", lambda: self._go_tab(STATS))
        elif due:
            self._show_match(due)
            out = sum(len(report.availability(t, tid)) for tid in (due.home, due.away) if t.teams[tid].human)
            self.next_avail.setText(f"⚠  {out} player{'s' if out != 1 else ''} unavailable — see match details"
                                    if out else "")
            self.details_btn.setVisible(True)
            self._set_primary("PLAY MATCH", self._play)
        elif upcoming:
            self._show_match(upcoming)
            self.next_avail.setText("The other teams play first.")
            self.details_btn.setVisible(True)
            self._set_primary("CONTINUE", self._continue)
        else:
            if not humans:
                title, info = "spectator mode", "Simulate the tournament to see who wins."
            elif not alive:
                title = "your campaign is over"
                info = "  ·  ".join([f"{t.team_name(h)}: {report.campaign_summary(t, h)}" for h in humans]
                                    + ["Simulate the rest to see who lifts the trophy."])
            else:
                title, info = "waiting for the draw", "Simulate the remaining matches to find your opponent."
            self._show_message("out of the running" if humans and not alive else "waiting", "",
                               title, info,
                               tournament_crest(self.ds, t, humans[0], 120) if humans else None)
            self._set_primary("SIMULATE TO THE END", self._sim_to_end)
        self.more_btn.setVisible(bool(self._more_items()))
        self.next_avail.setVisible(bool(self.next_avail.text()))

        self._refresh_side()

        clear_layout(self.latest_grid)
        playedf = [f for f in t.fixtures if f.played]
        last_day = max(f.day for f in playedf) if playedf else None
        recent = [f for f in playedf if f.day == last_day] if last_day is not None else []
        mine = set(humans)
        recent.sort(key=lambda f: not (f.home in mine or f.away in mine))
        cards = []
        if not recent:
            self.latest_grid.addWidget(Note("No match played yet.", color=FG_MUTED), 0, 0)
        for i, f in enumerate(recent[:LATEST_SHOWN]):
            card = ScoreCard(self.ds, t, f, highlight=mine)
            card.activated.connect(lambda fid=f.id: self._report(fid))
            self._register_dynamic(card)
            self.latest_grid.addWidget(card, i // 2, i % 2)
            cards.append(card)
        self.latest_title.set_right(f"{len(recent)} matches" if len(recent) > LATEST_SHOWN else "")
        self.latest_more.setVisible(bool(playedf))

        clear_layout(self.news_list)
        news = list(reversed(t.news))[:HEADLINES_SHOWN]
        if not news:
            self.news_list.addWidget(Note("  No news yet.", color=FG_MUTED))
        items = []
        for n in news:
            item = NewsItem(n, compact=True)
            self.news_list.addWidget(item)
            items.append(item)
        self.news_more.setVisible(len(t.news) > HEADLINES_SHOWN)
        if animate and self.tabs.index() == HOME:
            motion.fade_in(self.hero, ms=260)
            motion.stagger_in(cards + items, start=120)

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
            for f in ties[-4:]:
                card = ScoreCard(self.ds, t, f, highlight=humans)
                card.activated.connect(lambda fid=f.id: self._report(fid))
                self._register_dynamic(card)
                self.side_holder.addWidget(card)
            self.side_more.setText("BRACKET  →")
            self.side_more.clicked.disconnect()
            self.side_more.clicked.connect(lambda: self._open_view(BRACKET))
            return
        self.side_more.setText("FULL TABLE  →")
        self.side_more.clicked.disconnect()
        self.side_more.clicked.connect(lambda: self._open_view(TABLE))
        if group is None:
            st = next((s for s in t.stages if s.kind == "round_robin" and s.groups), None)
            if not st:
                self.side_more.hide()
                return
            stage, group = st, st.groups[0]
        self.side_more.show()
        self.side_title.set_title(group.name if len(stage.groups) > 1 else stage.name)
        qualify = int(stage.spec.get("qualify", 0))
        self.side_title.set_right(f"top {qualify} qualify" if qualify else "")
        table = self._standings_table(t, stage, group, compact=True)
        self.side_holder.addWidget(table)

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

    # ── competition: table / fixtures / bracket ──────────────────────────
    def _style_toggles(self):
        for i, b in enumerate(self.view_btns):
            style_button(b, "primary" if i == self._view else "neutral")
        style_button(self.fx_all, "neutral" if self._mine_only else "primary")
        style_button(self.fx_mine, "primary" if self._mine_only else "neutral")
        for b in self.view_btns + [self.fx_all, self.fx_mine]:
            b.setStyleSheet(b.styleSheet() + "QPushButton { padding: 4px 10px; letter-spacing: 1px; }")

    def _set_view(self, view, refresh=True):
        self._view = view
        self._style_toggles()
        if refresh and self.tabs.index() == COMP:
            self._refresh_competition()
            motion.fade_in(self.view_pages.currentWidget(), ms=160)

    def _refresh_competition(self):
        if (self._view == BRACKET and not self._has_bracket) or (self._view == TABLE and not self._has_table):
            self._view = FIXTURES
        self._style_toggles()
        self.view_pages.setCurrentIndex(self._view)
        humans = bool(self._human_ids())
        for b in (self.fx_all, self.fx_mine):
            b.setVisible(self._view == FIXTURES and humans)
        real = bool((self.t.options or {}).get("reality"))
        self.comp_note.setText({TABLE: "", FIXTURES: "A on a played match opens its report."
                                + ("  Blue scores: real results." if real else ""),
                                BRACKET: "A on a played tie opens its report."}[self._view])
        if self._view == TABLE:
            self._refresh_standings()
        elif self._view == FIXTURES:
            self._refresh_fixtures()
        else:
            self._refresh_bracket()

    def _set_mine(self, mine):
        self._mine_only = mine
        self._style_toggles()
        self._refresh_fixtures()

    def _refresh_fixtures(self):
        t = self.t
        humans = set(self._human_ids())
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
                 "color": (INFO if f.result.source == "real" else FG_PRIMARY) if f.result else FG_MUTED},
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
        cards = []
        for i, (key, title) in enumerate(boards):
            cards.append(self._leader_card(key, title))
            grid.addWidget(cards[-1], i // 2, i % 2)
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
        motion.stagger_in(cards + [w], step=70)

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
    def _run(self, action):
        """Run a session action that plays matches, then show what happened:
        the matchday recap and whatever else changed (moments.py)."""
        before = moments.snapshot(self.t)
        done = action() or []
        self._message = ""
        self._play_moments(before, done)

    def _play_moments(self, before, done):
        found = moments.moments_after(self.ds, self.t, before, done)
        self.refresh()
        if not found:
            return
        self._playing = True

        def finished():
            self._playing = False
            self.tabs.set_index(HOME)
            self.refresh(animate=True)
            if self.primary_btn.isVisible():
                self.primary_btn.setFocus()
        moments.play_moments(self, found, finished)

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
                self._run(lambda: self.session.simulate(f))
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
                self._run(lambda: self.session.enter_result(f, view.result()))
        ConfirmDialog(self, "Enter the result",
                      f"{report.fixture_caption(self.t, f)}: add the scoring events, cards and "
                      "injuries. The score follows from them. You can UNDO it afterwards.",
                      [("CANCEL", "neutral", "cancel"), ("RECORD", "primary", "ok")], go,
                      content=view, width=760)

    def _continue(self):
        self._run(self.session.advance_to_human)

    def _sim_to_end(self):
        def go(role):
            if role == "ok":
                def run():
                    played = {f.id for f in self.t.fixtures if f.played}
                    self.session.simulate_to_end()
                    return [f for f in self.t.fixtures if f.played and f.id not in played]
                self._run(run)
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
                self.refresh(animate=True)
        ConfirmDialog(self, "Undo the last step?",
                      "The results recorded by the last action are removed (only one step can be undone).",
                      [("CANCEL", "neutral", "cancel"), ("UNDO", "danger", "ok")], go)

    def _more_menu(self):
        items = self._more_items()
        if not items:
            return
        popup = PopupList(self, width=460, height=320, own_keys=True)
        popup.set_title("more")
        for label, data, sub in items:
            popup.add_row(label, data, subtitle=sub,
                          tag_color=DANGER_LITE if data == "undo" else None)
        popup.size_to(len(items))
        actions = {"simulate": self._simulate, "enter": self._enter_result,
                   "sim_end": self._sim_to_end, "undo": self._undo, "mine": self._your_matches}
        # after the popup has closed: a dialog opened from inside the pick
        # would lose its focus to the popup's own teardown
        popup.picked.connect(lambda data: QTimer.singleShot(0, actions[data]))
        popup.closed.connect(lambda: self.more_btn.setFocus() if not self._playing else None)
        popup.open_at(self.more_btn, self)
        popup.set_highlight(0)
        self._more_popup = popup

    def _your_matches(self):
        """Every match your teams played, newest first; A opens its report
        with the match stats."""
        played = self._my_played()
        if not played:
            return
        humans = set(self._human_ids())
        table = DataTable(["Round", "Home", "", "Away", "", ""], stretch_col=1,
                          widths={0: 170, 2: 90, 3: 220, 4: 74, 5: 96},
                          header_align={1: Qt.AlignRight})
        rows = []
        for f in played:
            r = f.result
            win = r.winner_id()
            me = f.home if f.home in humans else f.away
            verdict, color = (("DRAW", WARN) if win is None else
                              (("WIN", GREEN) if win == me else ("DEFEAT", DANGER_LITE)))
            rows.append([
                {"text": f.label, "color": FG_TERTIARY},
                {"text": self.t.team_name(f.home), "icon": tournament_crest(self.ds, self.t, f.home, 22),
                 "align": Qt.AlignRight, "bold": win == f.home,
                 "color": YOU_TINT if f.home in humans else None},
                {"text": f"{r.home.points} – {r.away.points}", "align": Qt.AlignHCenter, "bold": True},
                {"text": self.t.team_name(f.away), "icon": tournament_crest(self.ds, self.t, f.away, 22),
                 "bold": win == f.away, "color": YOU_TINT if f.away in humans else None},
                {"text": verdict, "color": color, "bold": True, "align": Qt.AlignHCenter},
                {"text": "played" if r.source == "game" else ("entered" if r.source == "manual"
                                                             else r.source.replace("sim", "simulated")),
                 "color": GREEN if r.source == "game" else FG_MUTED},
            ])
        table.set_rows(rows, keys=[f.id for f in played])
        table.fit_height(max_rows=10)
        dialog = ConfirmDialog(self, "Your matches", "A on a match shows its report and statistics.",
                               [("CLOSE", "primary", "ok")], lambda _r: None, cancel_role="ok",
                               content=table, width=900)

        def open_report(row):
            fid = table.keys[row]
            dialog.choose("ok")
            # once this dialog is gone: the report comes back here on CLOSE
            QTimer.singleShot(0, lambda: self._report(fid, back=self._your_matches))
        table.activated_row.connect(open_report)
        table.selectRow(0)
        table.setFocus()

    def _match_details(self):
        f = self._shown_fixture()
        if not f:
            return
        ConfirmDialog(self, report.fixture_caption(self.t, f), "", [("CLOSE", "primary", "ok")],
                      lambda _r: None, cancel_role="ok",
                      content=MatchPreviewView(self.ds, self.t, f, set(self._human_ids())), width=820)

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

    def _report(self, fid, back=None):
        """A played match's report and statistics; `back` reopens what it
        was picked from on CLOSE."""
        f = self.t.fixture(fid) if fid else None
        if not f or not f.played:
            return
        ConfirmDialog(self, f.label, "", [("CLOSE", "primary", "ok")],
                      lambda _r: back and QTimer.singleShot(0, back),
                      cancel_role="ok", content=MatchReportView(self.ds, self.t, f), width=820)


class MatchPreviewView(QWidget):
    """MATCH DETAILS: everything about the next match the hero card leaves
    out — each side's position, form, record in the tournament and who is
    missing; the date, ground, weather and pitch; an earlier meeting."""

    def __init__(self, ds, t, f, humans, parent=None):
        super().__init__(parent)
        transparent(self, "matchPreview")
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(12)
        meta = [f.label, calendar.short_date(calendar.fixture_date(t, f)), report.venue_name(ds, f),
                "neutral venue" if f.neutral else ""]
        v.addWidget(eyebrow_label("  ·  ".join(m for m in meta if m), color=FG_TERTIARY, size=10))
        if f.stadium_id:
            v.addWidget(Note(f"Weather: {weather.forecast(t, f, ds)['summary']}", color=INFO))
        v.addWidget(hline())
        cols = QHBoxLayout()
        cols.setSpacing(24)
        for i, tid in enumerate((f.home, f.away)):
            col = QVBoxLayout()
            col.setSpacing(8)
            top = QHBoxLayout()
            top.setSpacing(12)
            top.addWidget(PixmapLabel(56, tournament_crest(ds, t, tid, 56)))
            nv = QVBoxLayout()
            nv.setSpacing(2)
            nv.addWidget(display_label(t.team_name(tid), 18, QFont.Bold, track=0.6,
                                       color=YOU_TINT if tid in humans else FG_PRIMARY))
            pp = moments.pool_position(t, tid)
            where = f"{moments.ordinal(pp[1])} in {pp[0]}" if pp and pp[1] else report.campaign_summary(t, tid)
            nv.addWidget(eyebrow_label(where or "", color=FG_TERTIARY, size=10))
            top.addLayout(nv, stretch=1)
            col.addLayout(top)
            played = [g for g in t.fixtures if g.played and g.involves(tid)]
            won = sum(1 for g in played if g.result.winner_id() == tid)
            lost = sum(1 for g in played if g.result.winner_id() not in (None, tid))
            pf = sum(g.result.side(tid).points for g in played if g.result.side(tid))
            pa = sum(g.result.opponent(tid).points for g in played if g.result.opponent(tid))
            col.addWidget(eyebrow_label("form", color=ACCENT, size=9))
            col.addWidget(FormStrip(team_form(t, tid), cell=18))
            if played:
                col.addWidget(Note(f"Played {len(played)} · won {won} · lost {lost} · "
                                   f"points {pf}–{pa}", color=FG_SECONDARY))
            missing = report.availability(t, tid) if tid in t.teams else []
            col.addWidget(eyebrow_label("unavailable", color=WARN if missing else ACCENT, size=9))
            if missing:
                for pid, reason in missing[:8]:
                    col.addWidget(Note(f"{t.player_name(pid)} — {reason}", color=WARN))
                if len(missing) > 8:
                    col.addWidget(Note(f"+ {len(missing) - 8} more", color=FG_MUTED))
            else:
                col.addWidget(Note("Everyone is available.", color=GREEN))
            col.addStretch(1)
            cols.addLayout(col, stretch=1)
        v.addLayout(cols)
        met = [g for g in t.fixtures if g.played and g.involves(f.home) and g.involves(f.away)]
        if met:
            v.addWidget(hline())
            g = met[-1]
            v.addWidget(Note(f"Earlier in this tournament: {report.fixture_caption(t, g)} "
                             f"{g.result.score_text()} ({g.label})", color=FG_SECONDARY))


def _ref(t, ref):
    from .common import ref_label
    return ref_label(t, ref)


def _source_label(r):
    """How a result came about, for the report's meta line."""
    real = (r.extra or {}).get("reality") or {}
    if r.source == "real":
        if real.get("cancelled"):
            return "real result: cancelled, draw awarded"
        return "real result" + (" (scorers generated)" if real.get("scorers") == "generated" else "")
    if real.get("diverged"):
        return "simulated: this match didn't happen in reality"
    return {"game": "played in the game", "forfeit": "awarded (forfeit)",
            "manual": "entered manually"}.get(r.source, "simulated")


class MatchReportView(QWidget):
    """A played match: crests, score, scorers side by side, cards, injuries,
    player of the match, then the match statistics (scoring, kicks,
    tackles, cards; scrums and lineouts when it was played in the game)
    and each side's top tacklers."""

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
                _source_label(r)]
        if r.decided_by:
            meta.append(r.score_text().split(" ", 1)[-1].strip("()"))
        meta_label = eyebrow_label("  ·  ".join(m for m in meta if m), color=FG_TERTIARY, size=10)
        meta_label.setWordWrap(True)
        v.addWidget(meta_label)
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
        v.addWidget(hline())
        v.addWidget(eyebrow_label("match statistics", color=ACCENT, size=11))
        table = StatComparison(report.match_stats(r), row_h=34)
        v.addWidget(table)
        tacklers = [report.top_tacklers(t, side) for side in (r.home, r.away)]
        if any(tacklers):
            row = QHBoxLayout()
            row.setSpacing(24)
            for i, text in enumerate(tacklers):
                note = Note(f"Top tacklers: {text}" if text else "", color=FG_SECONDARY)
                if i:
                    note.setAlignment(Qt.AlignRight)
                row.addWidget(note, stretch=1)
            v.addLayout(row)
