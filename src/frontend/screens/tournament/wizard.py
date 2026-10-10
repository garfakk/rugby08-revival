"""
screens/tournament/wizard.py — Setting up a new tournament, in four steps:

  1 COMPETITION  competition cards, season, the tournament's name
  2 THE DRAW     who plays in which pool (crest + team per slot), default
                 teams / shuffle the draw
  3 YOUR TEAM    pick the team you manage from crest tiles; optional second
                 player's team
  4 RULES        difficulty, half length, realism (injuries, fatigue...)

A step bar on top (click a step, or LB / RB), a summary rail on the right
and BACK / NEXT at the bottom; the last step's NEXT is START TOURNAMENT,
which creates and saves it and opens the dashboard.
"""
import random

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import (QGridLayout, QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout,
                             QWidget)

from app.challenges import DIFFICULTIES, HALF_LENGTHS
from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.season import season_label
from app.tournament import engine, formats
from app import variants as V
from app.tournament.session import TournamentSession
from shared.log import get_logger
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, page_header, tracked_font
from ui.editor_kit import ChoiceField, FieldGrid, Note, TextField, compact_button
from ui.theme import (ACCENT, BG_BASE, BG_PANEL, BORDER, BTN_HEIGHT, FG_MUTED, FG_PRIMARY,
                      FG_SECONDARY, FG_TERTIARY, FONT_BODY, FONT_DISPLAY, GREEN, WARN)

from .common import (ActivatableCard, PixmapLabel, SectionTitle, Tag, YOU_TINT, clear_layout,
                     competition_emblem, placeholder_crest, section, team_crest, transparent)

log = get_logger(__name__)

ON_OFF = ["on", "off"]
VARIANCE = {"predictable": 0.6, "normal": 1.0, "chaotic": 1.6}
INJURY_RATES = {"rare": 0.5, "normal": 1.0, "frequent": 1.8}
STEPS = ["competition", "the draw", "your team", "rules"]


def _format_line(tpl) -> str:
    stages = tpl.get("stages", [])
    rr = [s for s in stages if s.get("kind", "round_robin") == "round_robin"]
    ko = [s for s in stages if s.get("kind") == "knockout"]
    groups = sum(len(s.get("group_names") or {}) for s in rr)
    teams = sum(len(ts) for st in (tpl.get("participants", {}).get("default", {}) or {}).values()
                for ts in st.values())
    parts = [f"{teams} teams"] if teams else []
    if rr:
        parts.append(f"{groups} pools" if groups > 1 else "league")
    if ko:
        rounds = [r.get("name", "") for s in ko for r in s.get("rounds", [])]
        parts.append(f"{len(rounds)} knockout rounds" if len(rounds) > 1 else "final")
    return " · ".join(parts)


class StepBar(QWidget):
    """① COMPETITION ── ② THE DRAW ── ③ YOUR TEAM ── ④ RULES"""

    picked = pyqtSignal(int)

    def __init__(self, steps, parent=None):
        super().__init__(parent)
        self.steps = steps
        self.index = 0
        self.done = set()
        self.setFixedHeight(56)
        self.setCursor(Qt.PointingHandCursor)

    def set_state(self, index, done):
        self.index, self.done = index, set(done)
        self.update()

    def _rects(self):
        w = self.width() / len(self.steps)
        return [QRectF(i * w, 0, w, self.height()) for i in range(len(self.steps))]

    def mousePressEvent(self, e):
        for i, r in enumerate(self._rects()):
            if r.contains(e.pos()):
                self.picked.emit(i)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rects = self._rects()
        cy = self.height() / 2
        for i, r in enumerate(rects):
            active, done = i == self.index, i in self.done and i != self.index
            col = QColor(ACCENT if active else (GREEN if done else FG_MUTED))
            c = QRectF(r.x() + 8, cy - 15, 30, 30)
            label_font = tracked_font(FONT_DISPLAY, 14, QFont.Bold, 1.6)
            label_w = QFontMetrics(label_font).horizontalAdvance(self.steps[i].upper()) + 12
            if i < len(rects) - 1:
                p.setPen(QPen(QColor(GREEN if done else BORDER), 2))
                p.drawLine(int(c.right() + 12 + label_w + 8), int(cy), int(rects[i + 1].x() - 4), int(cy))
            p.setPen(Qt.NoPen)
            p.setBrush(col if (active or done) else QColor(BG_PANEL))
            p.drawEllipse(c)
            if not (active or done):
                p.setPen(QPen(col, 1.5))
                p.setBrush(Qt.NoBrush)
                p.drawEllipse(c.adjusted(1, 1, -1, -1))
            p.setPen(QColor(BG_BASE if (active or done) else FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, 0))
            p.drawText(c, Qt.AlignCenter, "✓" if done else str(i + 1))
            p.setFont(label_font)
            p.setPen(QColor(FG_PRIMARY if active else (FG_SECONDARY if done else FG_TERTIARY)))
            p.drawText(QRectF(c.right() + 12, 0, label_w, self.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       self.steps[i].upper())


class CompetitionCard(ActivatableCard):
    def __init__(self, ds, tid, tpl, parent=None):
        super().__init__(parent)
        self.tid, self.tpl = tid, tpl
        self.setFixedHeight(118)
        self._emblem = competition_emblem(ds, tpl, 80)
        self._format = _format_line(tpl)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        w, h = self.width(), self.height()
        p.drawPixmap(18, (h - 80) // 2, self._emblem)
        x = 116
        p.setFont(tracked_font(FONT_DISPLAY, 19, QFont.Bold, 1.0))
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(x, 12, w - x - 14, 28), Qt.AlignLeft | Qt.AlignVCenter,
                   self.tpl.get("name", self.tid).upper())
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.4))
        p.setPen(QColor(ACCENT if self.selected else FG_TERTIARY))
        p.drawText(QRectF(x, 40, w - x - 14, 16), Qt.AlignLeft | Qt.AlignVCenter, self._format.upper())
        f = QFont(FONT_BODY)
        f.setPointSize(9)
        p.setFont(f)
        p.setPen(QColor(FG_SECONDARY))
        p.drawText(QRectF(x, 60, w - x - 14, h - 66), Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap,
                   self.tpl.get("description", ""))
        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(QRectF(w - 30, 12, 18, 18))
            p.setPen(QColor(BG_BASE))
            p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.Bold, 0))
            p.drawText(QRectF(w - 30, 12, 18, 18), Qt.AlignCenter, "✓")


class TeamTile(ActivatableCard):
    """Crest + name: picking the team you manage."""

    def __init__(self, crest, name, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 132)
        self._crest, self._name = crest, name
        self.player2 = False

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        w = self.width()
        p.drawPixmap(int((w - 64) / 2), 14, self._crest)
        p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, 0.8))
        p.setPen(QColor(YOU_TINT if self.selected else FG_PRIMARY))
        p.drawText(QRectF(6, 84, w - 12, 22), Qt.AlignCenter,
                   p.fontMetrics().elidedText(self._name.upper(), Qt.ElideRight, w - 12))
        tag = "YOU" if self.selected else ("P2" if self.player2 else "")
        if tag:
            r = QRectF((w - 44) / 2, 108, 44, 16)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(YOU_TINT if self.selected else GREEN))
            p.drawRoundedRect(r, 2, 2)
            p.setPen(QColor(BG_BASE))
            p.setFont(tracked_font(FONT_DISPLAY, 9, QFont.Bold, 1.2))
            p.drawText(r, Qt.AlignCenter, tag)


def _scroll(widget):
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QScrollArea.NoFrame)
    s.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
    s.setStyleSheet("QScrollArea { background: transparent; border: none; }")
    s.viewport().setStyleSheet("background: transparent;")
    s.setWidget(widget)
    return s


class TournamentWizardScreen(Screen):
    def __init__(self, ds, on_back, on_created):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_created = on_created
        self.templates = {}
        self.slot_fields = {}      # (stage_id, group_id, index) -> ChoiceField
        self.slot_crests = {}      # same key -> PixmapLabel
        self._comp_cards = []
        self._team_tiles = []
        self._building = False
        self._step = 0
        self._build()

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("New tournament", breadcrumb="tournament", on_back=self._back_step))

        body = QWidget()
        body.setObjectName("wizBody")
        body.setStyleSheet(f"QWidget#wizBody {{ background: {BG_BASE}; }}")
        bv = QVBoxLayout(body)
        bv.setContentsMargins(70, 14, 70, 16)
        bv.setSpacing(12)
        self.steps = StepBar(STEPS)
        self.steps.picked.connect(self._go)
        bv.addWidget(self.steps)

        cols = QHBoxLayout()
        cols.setSpacing(24)
        self.stack = QStackedWidget()
        self.stack.addWidget(_scroll(self._page_competition()))
        self.stack.addWidget(_scroll(self._page_draw()))
        self.stack.addWidget(_scroll(self._page_team()))
        self.stack.addWidget(_scroll(self._page_rules()))
        cols.addWidget(self.stack, stretch=3)
        cols.addWidget(self._summary_rail(), stretch=1)
        bv.addLayout(cols, stretch=1)

        foot = QHBoxLayout()
        foot.setSpacing(12)
        self.prev_btn = compact_button("BACK", "neutral", height=BTN_HEIGHT)
        self.prev_btn.setMinimumWidth(140)
        self.prev_btn.clicked.connect(self._back_step)
        foot.addWidget(self.prev_btn)
        self.problems = Note("", color=WARN)
        foot.addWidget(self.problems, stretch=1)
        self.next_btn = compact_button("NEXT", "primary", height=BTN_HEIGHT)
        self.next_btn.setMinimumWidth(240)
        self.next_btn.clicked.connect(self._next_step)
        foot.addWidget(self.next_btn)
        bv.addLayout(foot)
        root.addWidget(body, stretch=1)

        self.hints = HintBar()
        self.hints.set_hints([("A", "select"), ("LB", "prev step"), ("RB", "next step"), ("B", "back")])
        root.addWidget(self.hints)

    def _page_competition(self):
        page = transparent(QWidget(), "wizP1")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(12)
        v.addWidget(SectionTitle("choose a competition"))
        self.comp_grid = QGridLayout()
        self.comp_grid.setHorizontalSpacing(12)
        self.comp_grid.setVerticalSpacing(12)
        v.addLayout(self.comp_grid)
        v.addSpacing(6)
        v.addWidget(SectionTitle("details"))
        grid = FieldGrid(columns=2)
        self.season = ChoiceField("season", allow_blank=False, display=season_label)
        self.season.edited.connect(lambda _v: self._season_changed())
        self.name = TextField("name", max_bytes=60)
        self.name.edited.connect(lambda _v: self._refresh_summary())
        for f in (self.season, self.name):
            grid.add(f)
            self.focus.register(f)
        v.addWidget(grid)
        v.addWidget(Note("The season picks each team's squad, kits and ratings (the closest season a "
                         "team has when it lacks that one).", color=FG_TERTIARY))
        v.addStretch(1)
        return page

    def _page_draw(self):
        page = transparent(QWidget(), "wizP2")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(12)
        top = QHBoxLayout()
        self.draw_title = SectionTitle("the draw")
        top.addWidget(self.draw_title, stretch=1)
        self.reset_btn = compact_button("DEFAULT TEAMS", "neutral")
        self.reset_btn.clicked.connect(self._fill_defaults)
        self.shuffle_btn = compact_button("SHUFFLE DRAW", "neutral")
        self.shuffle_btn.clicked.connect(self._shuffle)
        for b in (self.reset_btn, self.shuffle_btn):
            top.addWidget(b)
            self.focus.register(b)
        v.addLayout(top)
        self.groups_holder = QGridLayout()
        self.groups_holder.setHorizontalSpacing(14)
        self.groups_holder.setVerticalSpacing(14)
        v.addLayout(self.groups_holder)
        v.addStretch(1)
        return page

    def _page_team(self):
        page = transparent(QWidget(), "wizP3")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(12)
        v.addWidget(SectionTitle("pick the team you manage"))
        self.tiles_grid = QGridLayout()
        self.tiles_grid.setHorizontalSpacing(10)
        self.tiles_grid.setVerticalSpacing(10)
        v.addLayout(self.tiles_grid)
        v.addSpacing(6)
        v.addWidget(SectionTitle("second player (optional)"))
        grid = FieldGrid(columns=2)
        self.human1 = ChoiceField("your team", allow_blank=False)
        self.human2 = ChoiceField("second player's team", allow_blank=True, blank_label="— none —")
        for f in (self.human1, self.human2):
            f.edited.connect(lambda _v: self._humans_changed())
        self.human1.hide()      # driven by the tiles; kept for its value/options
        grid.add(self.human2)
        self.focus.register(self.human2)
        v.addWidget(grid)
        v.addWidget(Note("A second player manages another team with the second controller — "
                         "every other team is run by the computer.", color=FG_TERTIARY))
        v.addStretch(1)
        return page

    def _page_rules(self):
        page = transparent(QWidget(), "wizP4")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(14)
        self.difficulty = ChoiceField("difficulty", DIFFICULTIES, allow_blank=False)
        self.half = ChoiceField("half length", HALF_LENGTHS, allow_blank=False)
        self.variance = ChoiceField("simulated results", list(VARIANCE), allow_blank=False)
        self.injuries = ChoiceField("injuries", ON_OFF, allow_blank=False)
        self.injury_rate = ChoiceField("injury frequency", list(INJURY_RATES), allow_blank=False)
        self.suspensions = ChoiceField("suspensions", ON_OFF, allow_blank=False)
        self.fatigue = ChoiceField("fatigue", ON_OFF, allow_blank=False)
        self.seed = TextField("seed (blank = random)", max_bytes=10)
        self.seed.edited.connect(lambda _v: self._validate())
        for title, fields, note in (
                ("your matches", (self.difficulty, self.half),
                 "How hard the computer plays and how long each half lasts in the game."),
                ("realism", (self.injuries, self.injury_rate, self.suspensions, self.fatigue),
                 "Injuries and bans keep players out; fatigue lowers ratings of players who play "
                 "every match — rotate your squad."),
                ("simulation", (self.variance, self.seed),
                 "How surprising simulated results are. A seed replays the same tournament.")):
            w, sv = section(title)
            grid = FieldGrid(columns=2)
            for f in fields:
                grid.add(f)
                self.focus.register(f)
                f.edited.connect(lambda _v: self._refresh_summary())
            sv.addWidget(grid)
            sv.addWidget(Note(note, color=FG_TERTIARY))
            v.addWidget(w)
        v.addStretch(1)
        return page

    def _summary_rail(self):
        card = Card(stripe=ACCENT, translucent=True)
        v = QVBoxLayout(card)
        v.setContentsMargins(22, 18, 22, 18)
        v.setSpacing(10)
        v.addWidget(eyebrow_label("summary", color=ACCENT, size=12))
        self.s_emblem = PixmapLabel(96)
        v.addWidget(self.s_emblem, alignment=Qt.AlignHCenter)
        self.s_name = display_label("", 20, QFont.Bold, track=0.8)
        self.s_name.setAlignment(Qt.AlignCenter)
        self.s_name.setWordWrap(True)
        v.addWidget(self.s_name)
        self.s_comp = eyebrow_label("", color=FG_TERTIARY, size=10)
        self.s_comp.setAlignment(Qt.AlignCenter)
        v.addWidget(self.s_comp)
        v.addSpacing(6)
        self.s_lines = QVBoxLayout()
        self.s_lines.setSpacing(6)
        v.addLayout(self.s_lines)
        v.addStretch(1)
        you = QHBoxLayout()
        you.setSpacing(12)
        self.s_crest = PixmapLabel(56)
        you.addWidget(self.s_crest)
        yv = QVBoxLayout()
        yv.setSpacing(0)
        yv.addWidget(eyebrow_label("you manage", color=FG_TERTIARY, size=10))
        self.s_team = display_label("", 16, QFont.Bold, track=0.8, color=YOU_TINT)
        self.s_team.setWordWrap(True)
        yv.addWidget(self.s_team)
        you.addLayout(yv, stretch=1)
        v.addLayout(you)
        return card

    # ── data ─────────────────────────────────────────────────────────────
    def on_show(self):
        super().on_show()
        self.templates = formats.load_templates()
        keep = getattr(self, "_comp", None)
        for c in self._comp_cards:
            self.focus.unregister(c)
        clear_layout(self.comp_grid)
        self._comp_cards = []
        for i, (tid, tpl) in enumerate(self.templates.items()):
            card = CompetitionCard(self.ds, tid, tpl)
            card.activated.connect(lambda tid=tid: self._pick_competition(tid))
            self.focus.register(card)
            self.comp_grid.addWidget(card, i // 2, i % 2)
            self._comp_cards.append(card)
        seasons = sorted({s for seasons in self.ds.teams.values() for s in seasons}, reverse=True)
        self.season.set_options(seasons)
        if not self.season.value() and seasons:
            self.season.set_value("2010" if "2010" in seasons else seasons[0])
        self._pick_competition(keep if keep in self.templates else next(iter(self.templates), ""))
        self._go(0)

    def template(self):
        return self.templates.get(getattr(self, "_comp", ""), {})

    def _team_options(self):
        season = self.season.value()
        tpl = self.template()
        out = []
        for tid, seasons in self.ds.teams.items():
            s = engine.pick_season(seasons, season)
            variant = engine.entry_variant(self.ds, tpl, tid, s)
            if len(engine.usable_squad(self.ds, tid, s, variant)) >= 22:
                out.append((seasons[s].get("name", tid), tid))
        out.sort(key=lambda x: x[0].lower())
        return [tid for _n, tid in out]

    def _team_name(self, tid):
        seasons = self.ds.teams.get(tid)
        if not seasons:
            return f"missing team {tid}" if tid else "—"
        s = engine.pick_season(seasons, self.season.value())
        name = seasons[s].get("name", tid)
        variant = engine.entry_variant(self.ds, self.template(), tid, s)
        return f"{name} · {V.variant_label(seasons[s], variant)}" if variant else name

    def _crest(self, tid, size):
        if tid not in self.ds.teams:
            return placeholder_crest(size)
        s = engine.pick_season(self.ds.teams[tid], self.season.value())
        return team_crest(self.ds, tid, s, size,
                          variant=engine.entry_variant(self.ds, self.template(), tid, s))

    def _pick_competition(self, tid):
        self._comp = tid
        for c in self._comp_cards:
            c.selected = c.tid == tid
            c.update()
        tpl = self.template()
        self.name.set_value(tpl.get("name", ""))
        opts = tpl.get("default_options") or {}
        self.difficulty.set_value(opts.get("difficulty", "pro"))
        self.half.set_value(opts.get("halftime_length", "5m"))
        self.injuries.set_value("on" if opts.get("injuries", True) else "off")
        self.suspensions.set_value("on" if opts.get("suspensions", True) else "off")
        self.fatigue.set_value("on" if opts.get("fatigue", True) else "off")
        self.variance.set_value("normal")
        self.injury_rate.set_value("normal")
        # A historical competition (e.g. a World Cup edition) names the
        # season its squads were entered for.
        season = str(tpl.get("season") or "")
        if season and any(season in s for s in self.ds.teams.values()):
            self.season.set_value(season)
        self._build_groups(engine.default_participants(tpl, self.season.value()))

    def _season_changed(self):
        self._build_groups(self.participants())

    def _build_groups(self, participants):
        self._building = True
        for f in self.slot_fields.values():
            self.focus.unregister(f)
        self.slot_fields, self.slot_crests = {}, {}
        clear_layout(self.groups_holder)
        options = self._team_options()
        tpl = self.template()
        cards = []
        for spec in tpl.get("stages", []):
            if spec.get("kind", "round_robin") != "round_robin":
                continue
            names = spec.get("group_names") or {}
            groups = participants.get(spec["id"], {})
            for gid, teams in groups.items():
                card = Card(translucent=True)
                cv = QVBoxLayout(card)
                cv.setContentsMargins(16, 12, 16, 14)
                cv.setSpacing(6)
                head = QHBoxLayout()
                head.addWidget(display_label(names.get(gid, f"Pool {gid}"), 14, QFont.Bold, track=1.2,
                                             color=ACCENT))
                head.addStretch(1)
                head.addWidget(eyebrow_label(f"{len(teams)} teams", color=FG_TERTIARY, size=9))
                cv.addLayout(head)
                for i, tid in enumerate(teams):
                    row = QHBoxLayout()
                    row.setSpacing(10)
                    crest = PixmapLabel(30, self._crest(tid, 30))
                    row.addWidget(crest)
                    f = ChoiceField("", options, display=self._team_name, allow_blank=False)
                    f.set_value(tid)
                    f.edited.connect(lambda _v, k=(spec["id"], gid, i): self._slot_changed(k))
                    row.addWidget(f, stretch=1)
                    cv.addLayout(row)
                    self.focus.register(f)
                    self.slot_fields[(spec["id"], gid, i)] = f
                    self.slot_crests[(spec["id"], gid, i)] = crest
                cards.append(card)
        cols = 2 if len(cards) > 1 else 1
        for i, card in enumerate(cards):
            self.groups_holder.addWidget(card, i // cols, i % cols)
        n = sum(len(ts) for g in participants.values() for ts in g.values())
        self.draw_title.set_right(f"{n} teams · {len(cards)} pool{'s' if len(cards) != 1 else ''}")
        self._building = False
        self._participants_changed()

    def _slot_changed(self, key):
        f = self.slot_fields[key]
        self.slot_crests[key].set_pixmap(self._crest(f.value(), 30))
        self._participants_changed()

    def participants(self) -> dict:
        out = {}
        for (sid, gid, _i), f in self.slot_fields.items():
            out.setdefault(sid, {}).setdefault(gid, []).append(f.value())
        return out

    def _participants_changed(self):
        if self._building:
            return
        teams = [tid for groups in self.participants().values() for ts in groups.values() for tid in ts]
        for f in (self.human1, self.human2):
            keep = f.value()
            f.display = self._team_name
            f.set_options([t for t in teams if t in self.ds.teams])
            if keep in teams:
                f.set_value(keep)
            elif f is self.human1 and teams:
                f.set_value(next((t for t in teams if t in self.ds.teams), ""))
            else:
                f.set_value("")
        self._build_tiles(teams)
        self._humans_changed()

    def _build_tiles(self, teams):
        for tile in self._team_tiles:
            self.focus.unregister(tile)
        clear_layout(self.tiles_grid)
        self._team_tiles = []
        known = sorted((t for t in dict.fromkeys(teams) if t in self.ds.teams), key=lambda t: self._team_name(t).lower())
        for i, tid in enumerate(known):
            tile = TeamTile(self._crest(tid, 64), self._team_name(tid))
            tile.tid = tid
            tile.activated.connect(lambda tid=tid: (self.human1.set_value(tid), self._humans_changed()))
            self.focus.register(tile)
            self.tiles_grid.addWidget(tile, i // 6, i % 6)
            self._team_tiles.append(tile)

    def _humans_changed(self):
        for tile in self._team_tiles:
            tile.selected = tile.tid == self.human1.value()
            tile.player2 = tile.tid == self.human2.value()
            tile.update()
        self._validate()

    def _fill_defaults(self):
        self._build_groups(engine.default_participants(self.template(), self.season.value()))

    def _shuffle(self):
        parts = self.participants()
        for sid, groups in parts.items():
            pool = [t for ts in groups.values() for t in ts]
            random.shuffle(pool)
            i = 0
            for gid, ts in groups.items():
                groups[gid] = pool[i:i + len(ts)]
                i += len(ts)
        self._build_groups(parts)

    # ── validation / summary ─────────────────────────────────────────────
    def _step_problems(self):
        """Problems per step: {step index: [text]}."""
        found = formats.problems(self.ds, self.template(), self.season.value(), self.participants())
        out = {0: [] if self.template() else ["choose a competition"], 1: found, 2: [], 3: []}
        if not self.human1.value():
            out[2].append("pick the team you manage")
        if self.human2.value() and self.human2.value() == self.human1.value():
            out[2].append("the two players must manage different teams")
        seed = self.seed.value().strip()
        if seed and not seed.isdigit():
            out[3].append("the seed must be a number")
        return out

    def _validate(self):
        probs = self._step_problems()
        all_found = [p for i in sorted(probs) for p in probs[i]]
        here = probs.get(self._step, [])
        shown = here or (all_found if self._step == len(STEPS) - 1 else [])
        self.problems.setText(("⚠  " + "; ".join(shown[:3]) + (" …" if len(shown) > 3 else "")) if shown else "")
        last = self._step == len(STEPS) - 1
        self.next_btn.setText("START TOURNAMENT" if last else "NEXT")
        self.next_btn.setEnabled(not all_found if last else True)
        self.steps.set_state(self._step, {i for i in range(len(STEPS)) if i < self._step and not probs.get(i)})
        self._refresh_summary()
        return not all_found

    def _refresh_summary(self):
        tpl = self.template()
        self.s_emblem.set_pixmap(competition_emblem(self.ds, tpl, 96) if tpl else None)
        self.s_name.setText((self.name.value() or tpl.get("name", "")).upper())
        self.s_comp.setText(f"{tpl.get('name', '')} · {season_label(self.season.value())}".upper()
                            if tpl else "")
        clear_layout(self.s_lines)
        parts = self.participants()
        n = sum(len(ts) for g in parts.values() for ts in g.values())
        for label, value in (("format", _format_line(tpl)), ("teams", str(n)),
                             ("difficulty", self.difficulty.value()), ("halves", self.half.value()),
                             ("injuries", self.injuries.value()), ("fatigue", self.fatigue.value())):
            row = QHBoxLayout()
            row.addWidget(eyebrow_label(label, color=FG_TERTIARY, size=9))
            row.addStretch(1)
            row.addWidget(eyebrow_label(str(value), color=FG_SECONDARY, size=10))
            self.s_lines.addLayout(row)
        tid = self.human1.value()
        self.s_crest.set_pixmap(self._crest(tid, 56) if tid else None)
        self.s_team.setText(self._team_name(tid).upper() if tid else "—")

    # ── navigation ───────────────────────────────────────────────────────
    def _go(self, i):
        self._step = max(0, min(len(STEPS) - 1, i))
        self.stack.setCurrentIndex(self._step)
        self.prev_btn.setText("CANCEL" if self._step == 0 else "BACK")
        self._validate()
        first = {0: self._comp_cards[:1], 1: list(self.slot_fields.values())[:1],
                 2: [t for t in self._team_tiles if t.selected][:1] or self._team_tiles[:1],
                 3: [self.difficulty]}.get(self._step) or []
        if first:
            first[0].setFocus()

    def _next_step(self):
        if self._step == len(STEPS) - 1:
            self._start()
        else:
            self._go(self._step + 1)

    def _back_step(self):
        if self._step == 0:
            self.on_back_cb()
        else:
            self._go(self._step - 1)

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action == Action.TAB_NEXT:
            self._go(self._step + 1); event.accept(); return
        if action == Action.TAB_PREV:
            self._go(self._step - 1); event.accept(); return
        if action == Action.BACK:
            self._back_step(); event.accept(); return
        super().keyPressEvent(event)

    def _start(self):
        if not self._validate():
            return
        humans = [h for h in (self.human1.value(), self.human2.value()) if h]
        options = {
            "difficulty": self.difficulty.value(),
            "halftime_length": self.half.value(),
            "injuries": self.injuries.value() == "on",
            "injury_rate": INJURY_RATES.get(self.injury_rate.value(), 1.0),
            "suspensions": self.suspensions.value() == "on",
            "fatigue": self.fatigue.value() == "on",
            "sim_variance": VARIANCE.get(self.variance.value(), 1.0),
        }
        seed = self.seed.value().strip()
        try:
            session = TournamentSession.new(self.ds, self.template(), self.season.value(),
                                            self.participants(), humans, options,
                                            seed=int(seed) if seed else None,
                                            name=self.name.value().strip() or None)
        except Exception as e:
            log.exception("creating tournament")
            self.problems.setText(f"Couldn't create the tournament: {e}")
            return
        self.on_created(session)
