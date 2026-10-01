"""
screens/tournament/wizard.py — Setting up a new tournament: competition,
season, who plays in which pool, which team(s) the user manages, rules
and difficulty. START creates and saves it and opens the dashboard.
"""
import random

from PyQt5.QtCore import Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from app.challenges import DIFFICULTIES, HALF_LENGTHS
from app.screen_base import Screen
from app.season import season_label
from app.tournament import engine, formats
from app.tournament.session import TournamentSession
from shared.log import get_logger
from ui.broadcast import Card, HintBar, display_label, page_header
from ui.editor_kit import ChoiceField, FieldGrid, Note, TextField, compact_button
from ui.theme import BG_BASE, FG_SECONDARY, T_TITLE, WARN

from .common import clear_layout, section

log = get_logger(__name__)

ON_OFF = ["on", "off"]
VARIANCE = {"predictable": 0.6, "normal": 1.0, "chaotic": 1.6}
INJURY_RATES = {"rare": 0.5, "normal": 1.0, "frequent": 1.8}


class TournamentWizardScreen(Screen):
    def __init__(self, ds, on_back, on_created):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_created = on_created
        self.templates = {}
        self.slot_fields = {}      # (stage_id, group_id, index) -> ChoiceField
        self._building = False
        self._build()

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("New tournament", breadcrumb="tournament", on_back=self.on_back_cb))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {BG_BASE}; border: none; }}")
        body = QWidget()
        body.setObjectName("wizBody")
        body.setStyleSheet(f"QWidget#wizBody {{ background: {BG_BASE}; }}")
        self.body_layout = bl = QVBoxLayout(body)
        bl.setContentsMargins(100, 24, 100, 24)
        bl.setSpacing(16)
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        # competition
        card = Card()
        cv = QVBoxLayout(card)
        cv.setContentsMargins(24, 18, 24, 18)
        cv.setSpacing(10)
        self.title = display_label("", T_TITLE, QFont.Bold, track=0.8, upper=False)
        cv.addWidget(self.title)
        self.description = Note("", color=FG_SECONDARY)
        cv.addWidget(self.description)
        grid = FieldGrid(columns=3)
        self.competition = ChoiceField("competition", allow_blank=False)
        self.competition.edited.connect(lambda _v: self._template_changed())
        self.season = ChoiceField("season", allow_blank=False, display=season_label)
        self.season.edited.connect(lambda _v: self._season_changed())
        self.name = TextField("name", max_bytes=60)
        for f in (self.competition, self.season, self.name):
            grid.add(f)
            self.focus.register(f)
        cv.addWidget(grid)
        bl.addWidget(card)

        # participants
        w, self.teams_layout = section("teams")
        bl.addWidget(w)
        tools = QHBoxLayout()
        tools.addStretch(1)
        self.reset_btn = compact_button("DEFAULT TEAMS", "neutral")
        self.reset_btn.clicked.connect(self._fill_defaults)
        self.shuffle_btn = compact_button("SHUFFLE DRAW", "neutral")
        self.shuffle_btn.clicked.connect(self._shuffle)
        for b in (self.reset_btn, self.shuffle_btn):
            tools.addWidget(b)
            self.focus.register(b)
        bl.addLayout(tools)
        self.groups_holder = QVBoxLayout()
        self.groups_holder.setSpacing(12)
        bl.addLayout(self.groups_holder)

        # management + rules
        w, v = section("you")
        grid = FieldGrid(columns=2)
        self.human1 = ChoiceField("your team", allow_blank=False)
        self.human2 = ChoiceField("second player's team", allow_blank=True, blank_label="— none —")
        for f in (self.human1, self.human2):
            f.edited.connect(lambda _v: self._validate())
            grid.add(f)
            self.focus.register(f)
        v.addWidget(grid)
        bl.addWidget(w)

        w, v = section("rules & difficulty")
        grid = FieldGrid(columns=3)
        self.difficulty = ChoiceField("difficulty", DIFFICULTIES, allow_blank=False)
        self.half = ChoiceField("half length", HALF_LENGTHS, allow_blank=False)
        self.injuries = ChoiceField("injuries", ON_OFF, allow_blank=False)
        self.injury_rate = ChoiceField("injury frequency", list(INJURY_RATES), allow_blank=False)
        self.suspensions = ChoiceField("suspensions", ON_OFF, allow_blank=False)
        self.fatigue = ChoiceField("fatigue", ON_OFF, allow_blank=False)
        self.variance = ChoiceField("results", list(VARIANCE), allow_blank=False)
        self.seed = TextField("seed (blank = random)", max_bytes=10)
        self.seed.edited.connect(lambda _v: self._validate())
        for f in (self.difficulty, self.half, self.variance, self.injuries, self.injury_rate,
                  self.suspensions, self.fatigue, self.seed):
            grid.add(f)
            self.focus.register(f)
        v.addWidget(grid)
        bl.addWidget(w)

        self.problems = Note("", color=WARN)
        bl.addWidget(self.problems)
        row = QHBoxLayout()
        row.addStretch(1)
        self.start_btn = compact_button("START TOURNAMENT", "primary")
        self.start_btn.clicked.connect(self._start)
        self.focus.register(self.start_btn)
        row.addWidget(self.start_btn)
        bl.addLayout(row)
        bl.addStretch(1)

        hints = HintBar()
        hints.set_hints([("A", "select"), ("B", "back")])
        root.addWidget(hints)

    # ── data ─────────────────────────────────────────────────────────────
    def on_show(self):
        super().on_show()
        self.templates = formats.load_templates()
        keep = self.competition.value()
        self.competition.display = lambda tid: self.templates.get(tid, {}).get("name", tid)
        self.competition.set_options(list(self.templates))
        seasons = sorted({s for seasons in self.ds.teams.values() for s in seasons}, reverse=True)
        self.season.set_options(seasons)
        if not self.season.value() and seasons:
            self.season.set_value("2010" if "2010" in seasons else seasons[0])
        self.competition.set_value(keep if keep in self.templates else next(iter(self.templates), ""))
        self._template_changed()

    def template(self):
        return self.templates.get(self.competition.value(), {})

    def _team_options(self):
        season = self.season.value()
        out = []
        for tid, seasons in self.ds.teams.items():
            s = engine.pick_season(seasons, season)
            if len(engine.usable_squad(self.ds, tid, s)) >= 22:
                out.append((seasons[s].get("name", tid), tid))
        out.sort(key=lambda x: x[0].lower())
        return [tid for _n, tid in out]

    def _team_name(self, tid):
        seasons = self.ds.teams.get(tid)
        if not seasons:
            return tid or "—"
        return seasons[engine.pick_season(seasons, self.season.value())].get("name", tid)

    def _template_changed(self):
        tpl = self.template()
        self.title.setText(tpl.get("name", ""))
        self.description.setText(tpl.get("description", ""))
        self.name.set_value(tpl.get("name", ""))
        opts = tpl.get("default_options") or {}
        self.difficulty.set_value(opts.get("difficulty", "pro"))
        self.half.set_value(opts.get("halftime_length", "5m"))
        self.injuries.set_value("on" if opts.get("injuries", True) else "off")
        self.suspensions.set_value("on" if opts.get("suspensions", True) else "off")
        self.fatigue.set_value("on" if opts.get("fatigue", True) else "off")
        self.variance.set_value("normal")
        self.injury_rate.set_value("normal")
        self._build_groups(engine.default_participants(tpl, self.season.value()))

    def _season_changed(self):
        self._build_groups(self.participants())

    def _build_groups(self, participants):
        self._building = True
        for f in self.slot_fields.values():
            self.focus.unregister(f)
        self.slot_fields = {}
        clear_layout(self.groups_holder)
        options = self._team_options()
        tpl = self.template()
        for spec in tpl.get("stages", []):
            if spec.get("kind", "round_robin") != "round_robin":
                continue
            names = spec.get("group_names") or {}
            groups = participants.get(spec["id"], {})
            cols = 4 if len(groups) > 1 else 3
            for gid, teams in groups.items():
                card = Card()
                cv = QVBoxLayout(card)
                cv.setContentsMargins(18, 12, 18, 12)
                cv.addWidget(display_label(names.get(gid, f"Pool {gid}"), 13, QFont.Bold, track=1.0))
                grid = FieldGrid(columns=cols)
                for i, tid in enumerate(teams):
                    f = ChoiceField(f"team {i + 1}", options, display=self._team_name, allow_blank=False)
                    f.set_value(tid)
                    f.edited.connect(lambda _v: self._participants_changed())
                    grid.add(f)
                    self.focus.register(f)
                    self.slot_fields[(spec["id"], gid, i)] = f
                cv.addWidget(grid)
                self.groups_holder.addWidget(card)
        self._building = False
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
            f.set_options(teams)
            if keep in teams:
                f.set_value(keep)
            elif f is self.human1 and teams:
                f.set_value(teams[0])
            else:
                f.set_value("")
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

    def _validate(self):
        found = formats.problems(self.ds, self.template(), self.season.value(), self.participants())
        if self.human2.value() and self.human2.value() == self.human1.value():
            found.append("the two players must manage different teams")
        seed = self.seed.value().strip()
        if seed and not seed.isdigit():
            found.append("the seed must be a number")
        self.problems.setText("Can't start: " + "; ".join(found) if found else "")
        self.start_btn.setEnabled(not found)
        return not found

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
