"""
screens/tournament/wizard.py — Setting up a new tournament, in two steps:

  1 COMPETITION  competition cards, one per competition
  2 SETUP        edition (only the ones the data can play: a real edition,
                 e.g. the Six Nations 2008, or a club league's season; a team
                 the data doesn't have is left out, never replaced), name,
                 difficulty; the match rules (half length, injuries, fatigue,
                 suspensions) folded into one summary line until MATCH RULES
                 opens them; the teams you control (crest tiles, none taken
                 to start with: click to take a team, again to leave it; two
                 at most, P1 and P2). EDIT THE DRAW opens who plays in which
                 pool (crest + team per slot), the edition's draw / shuffle.

A step bar on top (click a step, or LB / RB) and BACK / NEXT at the bottom;
the last step's NEXT is START TOURNAMENT, which creates and saves it and
opens the dashboard.
"""
import copy
import random

from PyQt5.QtCore import QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PyQt5.QtWidgets import (QGridLayout, QHBoxLayout, QScrollArea, QStackedWidget, QVBoxLayout,
                             QWidget)

from app import difficulty
from app.challenges import DIFFICULTIES, HALF_LENGTHS
from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.tournament import engine, formats, reality
from app import variants as V
from app.tournament.session import TournamentSession
from shared.log import get_logger
from ui import motion
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, page_header, tracked_font
from ui.editor_kit import ChoiceField, FieldGrid, Note, TextField, compact_button
from ui.theme import (ACCENT, BG_BASE, BG_PANEL, BORDER, BTN_HEIGHT, FG_MUTED, FG_PRIMARY,
                      FG_SECONDARY, FG_TERTIARY, FONT_DISPLAY, GREEN, WARN)

from .common import (ActivatableCard, PixmapLabel, SectionTitle, YOU_TINT, clear_layout,
                     competition_emblem, placeholder_crest, section, team_crest, transparent)

log = get_logger(__name__)

ON_OFF = ["on", "off"]
STEPS = ["competition", "setup"]
DRAW_PAGE = len(STEPS)      # the stack page EDIT THE DRAW opens (part of setup)
MAX_HUMANS = 2


def _format_line(edition) -> str:
    stages = edition.template.get("stages", [])
    rr = [s for s in stages if s.get("kind", "round_robin") == "round_robin"]
    ko = [s for s in stages if s.get("kind") == "knockout"]
    groups = sum(len(g) for g in edition.participants.values())
    teams = edition.team_count()
    parts = [f"{teams} teams"] if teams else []
    if rr:
        parts.append(f"{groups} pools" if groups > 1 else "league")
    if ko:
        rounds = [r.get("name", "") for s in ko for r in s.get("rounds", [])]
        parts.append(f"{len(rounds)} knockout rounds" if len(rounds) > 1 else "final")
    return " · ".join(parts)


class StepBar(QWidget):
    """① COMPETITION ── ② SETUP"""

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
    """One competition (`tid` = its family) and the span of its editions;
    shows the edition picked last."""

    def __init__(self, ds, tid, editions, parent=None):
        super().__init__(parent)
        self.ds, self.tid, self.editions = ds, tid, editions
        self.setFixedHeight(96)
        self.set_edition(editions[0])

    def set_edition(self, edition):
        self.tpl = edition.template
        self._emblem = competition_emblem(self.ds, self.tpl, 72)
        self._format = _format_line(edition)
        labels = [e.label for e in self.editions if e.label]
        if len(labels) > 1:
            self._format += f" · {len(labels)} editions, {labels[-1]} to {labels[0]}"
        elif labels:
            self._format += f" · {labels[0]}"
        self.update()

    def _title(self):
        """The competition's name, without an edition's year ("Six Nations")."""
        name = str(self.editions[-1].template.get("name", self.tid))
        label = self.editions[-1].label
        return name[:-len(label)].strip() if label and name.endswith(label) else name

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        w, h = self.width(), self.height()
        p.drawPixmap(14, (h - 72) // 2, self._emblem)
        x = 104
        p.setFont(tracked_font(FONT_DISPLAY, 19, QFont.Bold, 1.0))
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(x, 20, w - x - 40, 28), Qt.AlignLeft | Qt.AlignVCenter,
                   self._title().upper())
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.4))
        p.setPen(QColor(ACCENT if self.selected else FG_TERTIARY))
        p.drawText(QRectF(x, 50, w - x - 14, 16), Qt.AlignLeft | Qt.AlignVCenter, self._format.upper())
        if self.selected:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ACCENT))
            p.drawEllipse(QRectF(w - 30, 12, 18, 18))
            p.setPen(QColor(BG_BASE))
            p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.Bold, 0))
            p.drawText(QRectF(w - 30, 12, 18, 18), Qt.AlignCenter, "✓")


class TeamTile(ActivatableCard):
    """Crest + name: a team you can control; `tag` = "P1" / "P2" when you do."""

    def __init__(self, crest, name, parent=None):
        super().__init__(parent)
        self.setFixedSize(150, 132)
        self._crest, self._name = crest, name
        self.tag = ""

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        w = self.width()
        p.drawPixmap(int((w - 64) / 2), 14, self._crest)
        p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, 0.8))
        p.setPen(QColor(YOU_TINT if self.tag else FG_PRIMARY))
        p.drawText(QRectF(6, 84, w - 12, 22), Qt.AlignCenter,
                   p.fontMetrics().elidedText(self._name.upper(), Qt.ElideRight, w - 12))
        tag = self.tag
        if tag:
            r = QRectF((w - 44) / 2, 108, 44, 16)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(YOU_TINT if tag == "P1" else GREEN))
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
        self.slot_fields = {}      # (stage_id, group_id, index) -> ChoiceField
        self.slot_crests = {}      # same key -> PixmapLabel
        self._comp_cards = []
        self._team_tiles = []
        self.humans = []           # team ids you control, P1 first
        self.season = ""           # follows the edition (see _season_for)
        self._building = False
        self._step = 0
        self._page = 0
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

        self.stack = QStackedWidget()
        self.stack.addWidget(_scroll(self._page_competition()))
        self.stack.addWidget(_scroll(self._page_setup()))
        self.stack.addWidget(_scroll(self._page_draw()))
        bv.addWidget(self.stack, stretch=1)

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
        v.addStretch(1)
        return page

    def _page_setup(self):
        page = transparent(QWidget(), "wizP2")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(14)
        self.edition = ChoiceField("edition", allow_blank=False,
                                   display=lambda eid: self._edition_label(eid))
        self.edition.popup_title = "edition"
        self.edition.edited.connect(lambda tid: self._pick_competition(tid))
        self.name = TextField("name", max_bytes=60)
        self.difficulty = ChoiceField("difficulty", DIFFICULTIES, allow_blank=False)
        self.half = ChoiceField("half length", HALF_LENGTHS, allow_blank=False)
        self.injuries = ChoiceField("injuries", ON_OFF, allow_blank=False)
        self.fatigue = ChoiceField("fatigue", ON_OFF, allow_blank=False)
        self.suspensions = ChoiceField("suspensions", ON_OFF, allow_blank=False)
        w, sv = section("tournament")
        grid = FieldGrid(columns=2)
        for f in (self.edition, self.name, self.difficulty):
            grid.add(f)
            self.focus.register(f)
        sv.addWidget(grid)
        # who the edition has to do without (left out, never replaced)
        self.missing_note = Note("", color=FG_TERTIARY)
        sv.addWidget(self.missing_note)
        # the match rules: the competition's defaults suit most, so one
        # summary line until MATCH RULES opens them
        rules = QHBoxLayout()
        rules.setSpacing(12)
        self.rules_btn = compact_button("MATCH RULES  ▾", "ghost")
        self.rules_btn.clicked.connect(self._toggle_rules)
        self.focus.register(self.rules_btn)
        rules.addWidget(self.rules_btn)
        self.rules_summary = Note("", color=FG_TERTIARY)
        rules.addWidget(self.rules_summary, stretch=1)
        sv.addLayout(rules)
        self.rules_grid = FieldGrid(columns=2)
        for f in (self.half, self.injuries, self.fatigue, self.suspensions):
            self.rules_grid.add(f)
            self.focus.register(f)
            f.edited.connect(lambda _v: self._update_rules_summary())
        self.rules_grid.hide()
        sv.addWidget(self.rules_grid)
        # Reality mode (app/tournament/reality.py): only for an edition with
        # real results whose real draw can be played with this data
        self.reality_row = transparent(QWidget(), "wizReality")
        rr = QHBoxLayout(self.reality_row)
        rr.setContentsMargins(0, 4, 0, 0)
        rr.setSpacing(14)
        self.reality = ChoiceField("reality mode", ON_OFF, allow_blank=False)
        self.reality.set_value("off")
        self.reality.setFixedWidth(330)
        self.reality.edited.connect(lambda _v: self._validate())
        self.focus.register(self.reality)
        rr.addWidget(self.reality)
        self.reality_note = Note("The other teams' matches get their real results, with the real "
                                 "injuries and bans. Yours are played as usual.", color=FG_TERTIARY)
        rr.addWidget(self.reality_note, stretch=1)
        sv.addWidget(self.reality_row)
        v.addWidget(w)

        top = QHBoxLayout()
        self.teams_title = SectionTitle("teams you control")
        top.addWidget(self.teams_title, stretch=1)
        self.draw_btn = compact_button("EDIT THE DRAW", "neutral")
        self.draw_btn.clicked.connect(lambda: self._show_page(DRAW_PAGE))
        top.addWidget(self.draw_btn)
        self.focus.register(self.draw_btn)
        v.addLayout(top)
        self.tiles_grid = QGridLayout()
        self.tiles_grid.setHorizontalSpacing(10)
        self.tiles_grid.setVerticalSpacing(10)
        v.addLayout(self.tiles_grid)
        v.addStretch(1)
        return page

    def _toggle_rules(self):
        show = self.rules_grid.isHidden()
        self.rules_grid.setVisible(show)
        self.rules_btn.setText("MATCH RULES  ▴" if show else "MATCH RULES  ▾")
        if show:
            motion.fade_in(self.rules_grid, ms=200)
            self.half.setFocus()

    def _update_rules_summary(self):
        on = [k for k, f in (("injuries", self.injuries), ("fatigue", self.fatigue),
                             ("suspensions", self.suspensions)) if f.value() == "on"]
        off = [k for k, f in (("injuries", self.injuries), ("fatigue", self.fatigue),
                              ("suspensions", self.suspensions)) if f.value() != "on"]
        parts = [f"{self.half.value()} halves"] + on + [f"no {k}" for k in off]
        self.rules_summary.setText(" · ".join(parts))

    def _page_draw(self):
        page = transparent(QWidget(), "wizP3")
        v = QVBoxLayout(page)
        v.setContentsMargins(0, 4, 8, 4)
        v.setSpacing(12)
        top = QHBoxLayout()
        self.draw_title = SectionTitle("the draw")
        top.addWidget(self.draw_title, stretch=1)
        self.reset_btn = compact_button("EDITION'S DRAW", "neutral")
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

    # ── data ─────────────────────────────────────────────────────────────
    def on_show(self):
        super().on_show()
        # the season most teams have (the latest of those), for a template
        # with neither a season of its own nor a category
        seasons = sorted({s for seasons in self.ds.teams.values() for s in seasons}, reverse=True)
        count = {s: sum(1 for ts in self.ds.teams.values() if s in ts) for s in seasons}
        self._default_season = max(seasons, key=lambda s: (count[s], s)) if seasons else ""
        # one card per competition, its editions newest first: only what
        # the data can play
        self.families = {fam: eds for fam, eds in
                         formats.editions(self.ds, default_season=self._default_season).items()}
        self.by_id = {e.id: e for eds in self.families.values() for e in eds}
        self._picked_in = {}
        keep = getattr(self, "_comp", None)
        for c in self._comp_cards:
            self.focus.unregister(c)
        clear_layout(self.comp_grid)
        self._comp_cards = []
        for i, (fam, eds) in enumerate(self.families.items()):
            card = CompetitionCard(self.ds, fam, eds)
            card.activated.connect(lambda fam=fam: self._pick_family(fam))
            self.focus.register(card)
            self.comp_grid.addWidget(card, i // 2, i % 2)
            self._comp_cards.append(card)
        first = next(iter(self.families.values()), [None])[0]
        self.humans = []            # nobody's team until you take one
        if keep in self.by_id or first:
            self._pick_competition(keep if keep in self.by_id else first.id)
        self._go(0)
        motion.stagger_in(self._comp_cards[:12], step=40)

    def current_edition(self):
        return self.by_id.get(getattr(self, "_comp", ""))

    def template(self):
        e = self.current_edition()
        return e.template if e else {}

    def _edition_label(self, eid):
        e = self.by_id.get(eid)
        if not e:
            return ""
        return e.label or "current squads"

    def _team_options(self):
        out = []
        for tid in self._usable():
            seasons = self.ds.teams[tid]
            out.append((seasons[engine.pick_season(seasons, self.season)].get("name", tid), tid))
        out.sort(key=lambda x: x[0].lower())
        return [tid for _n, tid in out]

    def _team_name(self, tid):
        seasons = self.ds.teams.get(tid)
        if not seasons:
            return f"missing team {tid}" if tid else "—"
        s = engine.pick_season(seasons, self.season)
        name = seasons[s].get("name", tid)
        variant = engine.entry_variant(self.ds, self.template(), tid, s)
        return f"{name} · {V.variant_label(seasons[s], variant)}" if variant else name

    def _plain_name(self, tid):
        seasons = self.ds.teams.get(tid)
        if not seasons:
            return self._team_name(tid)
        return seasons[engine.pick_season(seasons, self.season)].get("name", tid)

    def _crest(self, tid, size):
        if tid not in self.ds.teams:
            return placeholder_crest(size)
        s = engine.pick_season(self.ds.teams[tid], self.season)
        return team_crest(self.ds, tid, s, size,
                          variant=engine.entry_variant(self.ds, self.template(), tid, s))

    def _pick_family(self, fam):
        """A competition card: its edition picked last, else its newest."""
        eds = self.families.get(fam) or []
        if eds:
            self._pick_competition(self._picked_in.get(fam) or eds[0].id)

    def _pick_competition(self, eid):
        e = self.by_id.get(eid)
        if not e:
            return
        self._comp = eid
        tpl = e.template
        self._picked_in[e.family] = eid
        for c in self._comp_cards:
            c.selected = c.tid == e.family
            if c.selected:
                c.set_edition(e)
            c.update()
        eds = self.families.get(e.family, [e])
        self.edition.set_options([x.id for x in eds])
        self.edition.set_value(eid)
        self.edition.setEnabled(len(eds) > 1)
        self.name.set_value(tpl.get("name", ""))
        opts = tpl.get("default_options") or {}
        self.difficulty.set_value(difficulty.preferred())     # Settings > Preferred Difficulty
        self.half.set_value(opts.get("halftime_length", "5m"))
        self.injuries.set_value("on" if opts.get("injuries", True) else "off")
        self.suspensions.set_value("on" if opts.get("suspensions", True) else "off")
        self.fatigue.set_value("on" if opts.get("fatigue", True) else "off")
        self._update_rules_summary()
        self.season = e.season
        self.missing_note.setText(self._missing_text(e))
        self.missing_note.setVisible(bool(e.missing))
        offered, why = reality.available(tpl, known_teams=self._usable())
        self._reality_offered = offered
        self.reality_row.setVisible(offered)
        if not offered:
            self.reality.set_value("off")
        self._build_groups(self._edition_draw(e))

    def _usable(self):
        """The teams with a full squad for this edition (cached per edition)."""
        key = (getattr(self, "_comp", ""), self.season)
        if getattr(self, "_usable_key", None) != key:
            self._usable_key = key
            self._usable_set = formats.playable_teams(self.ds, self.template(), self.season)
        return self._usable_set

    def _edition_draw(self, e):
        return {sid: {gid: list(ts) for gid, ts in groups.items()} for sid, groups in e.participants.items()}

    def _missing_text(self, e):
        """Who the edition plays without, and where it shows."""
        if not e.missing:
            return ""
        names = [self._plain_name(t) if t in self.ds.teams else None for t in e.missing]
        known = [n for n in names if n]
        unknown = len(names) - len(known)
        parts = []
        if known:
            parts.append(", ".join(known) + (" have" if len(known) > 1 else " has") + " no full squad")
        if unknown:
            parts.append(f"{unknown} team{'s' if unknown > 1 else ''} of the real draw "
                         f"{'are' if unknown > 1 else 'is'} not in the data")
        short = [f"{self._group_name(sid, gid)} has {len(ts)} teams"
                 for sid, groups in e.participants.items() for gid, ts in groups.items()
                 if len(groups) > 1 and len(ts) < max(len(x) for x in groups.values())]
        text = "; ".join(parts) + ": left out, not replaced"
        return "ⓘ  " + text + (f" ({', '.join(short)})." if short else ".")

    def _group_name(self, sid, gid):
        spec = next((s for s in self.template().get("stages", []) if s.get("id") == sid), {})
        return (spec.get("group_names") or {}).get(gid, f"Pool {gid}")

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
                title = names.get(gid, f"Pool {gid}") if len(groups) > 1 else "the teams"
                head.addWidget(display_label(title, 14, QFont.Bold, track=1.2, color=ACCENT))
                head.addStretch(1)
                head.addWidget(eyebrow_label(f"{len(teams)} teams", color=FG_TERTIARY, size=9))
                cv.addLayout(head)
                for i, tid in enumerate(teams):
                    row = QHBoxLayout()
                    row.setSpacing(10)
                    crest = PixmapLabel(30, self._crest(tid, 30))
                    row.addWidget(crest)
                    f = ChoiceField("", options, display=self._team_name, allow_blank=False)
                    f.label_width = 0           # the crest is the label
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
        self.draw_title.set_right(f"{n} teams · {len(cards)} pools" if len(cards) > 1 else f"{n} teams")
        self.shuffle_btn.setVisible(len(cards) > 1)      # one league: nothing to shuffle
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
        teams = [tid for groups in self.participants().values() for ts in groups.values() for tid in ts
                 if tid in self.ds.teams]
        self.humans = [h for h in self.humans if h in teams]      # never one picked for you
        self._build_tiles(teams)
        self._humans_changed()

    def _build_tiles(self, teams):
        for tile in self._team_tiles:
            self.focus.unregister(tile)
        clear_layout(self.tiles_grid)
        self._team_tiles = []
        known = sorted(dict.fromkeys(teams), key=lambda t: self._team_name(t).lower())
        for i, tid in enumerate(known):
            # the plain name on the tile; its squad variant shows in the draw
            tile = TeamTile(self._crest(tid, 64), self._plain_name(tid))
            tile.tid = tid
            tile.activated.connect(lambda tid=tid: self._toggle_human(tid))
            self.focus.register(tile)
            self.tiles_grid.addWidget(tile, i // 6, i % 6)
            self._team_tiles.append(tile)

    def _toggle_human(self, tid):
        """Take a team, or leave it; with both taken, a third replaces P2."""
        if tid in self.humans:
            self.humans.remove(tid)
        elif len(self.humans) < MAX_HUMANS:
            self.humans.append(tid)
        else:
            self.humans[-1] = tid
        self._humans_changed()

    def _humans_changed(self):
        for tile in self._team_tiles:
            tile.tag = f"P{self.humans.index(tile.tid) + 1}" if tile.tid in self.humans else ""
            tile.update()
        self._validate()

    def _fill_defaults(self):
        if self.current_edition():
            self._build_groups(self._edition_draw(self.current_edition()))

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

    # ── validation ───────────────────────────────────────────────────────
    def _reality_wanted(self):
        return getattr(self, "_reality_offered", False) and self.reality.value() == "on"

    def _step_problems(self):
        """Problems per step: {step index: [text]}."""
        found = formats.problems(self.ds, self.template(), self.season, self.participants())
        out = {0: [] if self.template() else ["choose a competition"], 1: list(found)}
        if not self.humans:
            out[1].append("take a team: click its crest under TEAMS YOU CONTROL")
        if self._reality_wanted():
            ok, why = reality.available(self.template(), self.participants(), self.season, self._usable())
            if not ok:
                out[1].append(why[0].lower() + why[1:] + " (turn reality mode off, or EDITION'S DRAW)")
        return out

    def _validate(self):
        probs = self._step_problems()
        all_found = [p for i in sorted(probs) for p in probs[i]]
        here = probs.get(self._step, [])
        last = self._step == len(STEPS) - 1
        shown = here or (all_found if last else [])
        self.problems.setText(("⚠  " + "; ".join(shown[:3]) + (" …" if len(shown) > 3 else "")) if shown else "")
        self.next_btn.setText("DONE" if self._page == DRAW_PAGE else
                              ("START TOURNAMENT" if last else "NEXT"))
        self.next_btn.setEnabled(self._page == DRAW_PAGE or (not all_found if last else True))
        self.steps.set_state(self._step, {i for i in range(len(STEPS)) if i < self._step and not probs.get(i)})
        return not all_found

    # ── navigation ───────────────────────────────────────────────────────
    def _show_page(self, page):
        changed = page != self._page or not self.stack.currentWidget()
        self._page = page
        self.stack.setCurrentIndex(page)
        if changed and self.isVisible():
            motion.fade_in(self.stack.currentWidget(), ms=200)
        self.prev_btn.setText("CANCEL" if page == 0 else "BACK")
        self._validate()
        first = {0: [c for c in self._comp_cards if c.selected][:1] or self._comp_cards[:1],
                 1: [self.edition], DRAW_PAGE: list(self.slot_fields.values())[:1]}.get(page) or []
        if first:
            first[0].setFocus()

    def _go(self, i):
        self._step = max(0, min(len(STEPS) - 1, i))
        self._show_page(self._step)

    def _next_step(self):
        if self._page == DRAW_PAGE:
            self._show_page(self._step)
        elif self._step == len(STEPS) - 1:
            self._start()
        else:
            self._go(self._step + 1)

    def _back_step(self):
        if self._page == DRAW_PAGE:
            self._show_page(self._step)
        elif self._step == 0:
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
        options = {
            "difficulty": self.difficulty.value(),
            "halftime_length": self.half.value(),
            "injuries": self.injuries.value() == "on",
            "injury_rate": 1.0,
            "suspensions": self.suspensions.value() == "on",
            "fatigue": self.fatigue.value() == "on",
            "sim_variance": 1.0,
            "reality": self._reality_wanted(),
        }
        try:
            session = TournamentSession.new(self.ds, copy.deepcopy(self.template()), self.season,
                                            self.participants(), list(self.humans), options,
                                            name=self.name.value().strip() or None)
        except Exception as e:
            log.exception("creating tournament")
            self.problems.setText(f"Couldn't create the tournament: {e}")
            return
        self.on_created(session)
