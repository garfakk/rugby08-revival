"""
screens/mission_editor.py — hand-authored mission state (config.advanced_user)
====================================================================================
Reached only from match_setup.py's ADVANCED pane ("EDIT MISSION STATE…"
button, itself only built when config.advanced_user is True). Edits
MatchConfig fields in place, the same way every row in the advanced pane
does — no separate confirm/discard step, since these are all plain-value
fields with nothing that needs a "cancel this whole edit" escape hatch.

Schema (start mode, score events, objectives/parameters) is verified against
the 93 stock .mis files that ship inside data.gob — see
backend/game_specific_variables.py for the exact vocabularies and which
parts are still EXPERIMENTAL (dropping a non-kickoff MODE, or an objective,
into an otherwise plain exhibition match is not in-game confirmed; the
*schema* is — this editor just doesn't stop you writing something the
stock engine has never actually been asked to load this way).
"""
from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame
from PyQt5.QtCore import Qt

from backend import game_specific_variables as gsv
from app.screen_base import Screen
from ui.broadcast import Card, SelectorRow, HintBar, page_header
from ui.editor_kit import SectionCard, TextField, NumberField, SuggestField, compact_button, Note
from ui.theme import BG_BASE, FG_MUTED


class ScoreEventRow(QWidget):
    """One <SCORE><EVENT> — type/team/player/time. Mutates its `data` dict
    in place on every change (the screen never reads these back out; the
    dict IS the entry that lives in cfg.score_events)."""

    def __init__(self, data: dict, on_remove, focus_register, parent=None):
        super().__init__(parent)
        self.data = data
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)

        self.type_row = SelectorRow("type", compact=True)
        self.type_row.set_values(gsv.score_event_types,
                                 index=gsv.score_event_types.index(data["type"])
                                 if data.get("type") in gsv.score_event_types else 0)
        self.type_row.changed.connect(lambda: data.__setitem__("type", self.type_row.current()))
        h.addWidget(self.type_row, stretch=3)
        focus_register(self.type_row)

        self.team_row = SelectorRow("team", compact=True)
        self.team_row.set_values(["home", "away"], index=0 if data.get("team", "home") == "home" else 1)
        self.team_row.changed.connect(lambda: data.__setitem__("team", self.team_row.current()))
        h.addWidget(self.team_row, stretch=2)
        focus_register(self.team_row)

        self.player_field = NumberField("player #", lo=0, hi=23, allow_blank=False)
        self.player_field.label_width = 70
        self.player_field.set_value(data.get("player", 0))
        self.player_field.edited.connect(
            lambda v: data.__setitem__("player", int(v) if v else 0))
        h.addWidget(self.player_field, stretch=2)
        focus_register(self.player_field)

        self.time_field = NumberField("time (s)", lo=0, hi=9999, allow_blank=False)
        self.time_field.label_width = 70
        self.time_field.set_value(data.get("time", 0))
        self.time_field.edited.connect(
            lambda v: data.__setitem__("time", int(v) if v else 0))
        h.addWidget(self.time_field, stretch=2)
        focus_register(self.time_field)

        rm = compact_button("✕")
        rm.setFixedWidth(32)
        rm.clicked.connect(lambda: on_remove(self))
        h.addWidget(rm)
        focus_register(rm)


class NisRow(Card):
    """One <STATE><NIS> — the restart position (ball/player placement) a
    non-kickoff start mode needs: a scrum, lineout or penalty script plus
    where it's set up. Two lines — script_name/team/player/controller on
    top, the placement (angle/x/y/z, all optional/blank in stock samples)
    below — eight fields don't read cleanly on one row."""

    def __init__(self, data: dict, on_remove, focus_register, parent=None):
        super().__init__(parent=parent)
        self.data = data
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)

        top = QHBoxLayout()
        top.setSpacing(8)
        self.script_field = SuggestField("script", suggestions=gsv.nis_script_names,
                                         placeholder=gsv.nis_script_names[1])
        self.script_field.set_value(data.get("script_name", ""))
        self.script_field.edited.connect(lambda v: data.__setitem__("script_name", v))
        top.addWidget(self.script_field, stretch=3)
        focus_register(self.script_field)

        self.team_row = SelectorRow("team", compact=True)
        self.team_row.set_values(["home", "away"], index=0 if data.get("team", "home") == "home" else 1)
        self.team_row.changed.connect(lambda: data.__setitem__("team", self.team_row.current()))
        top.addWidget(self.team_row, stretch=2)
        focus_register(self.team_row)

        self.player_field = NumberField("player #", lo=0, hi=23, allow_blank=False)
        self.player_field.label_width = 70
        self.player_field.set_value(data.get("player", 0))
        self.player_field.edited.connect(lambda v: data.__setitem__("player", int(v) if v else 0))
        top.addWidget(self.player_field, stretch=1)
        focus_register(self.player_field)

        rm = compact_button("✕")
        rm.setFixedWidth(32)
        rm.clicked.connect(lambda: on_remove(self))
        top.addWidget(rm)
        focus_register(rm)
        v.addLayout(top)

        bottom = QHBoxLayout()
        bottom.setSpacing(8)
        self.controller_field = NumberField("ctrl", lo=0, hi=8, allow_blank=False)
        self.controller_field.label_width = 40
        self.controller_field.set_value(data.get("controller", 0))
        self.controller_field.edited.connect(
            lambda v: data.__setitem__("controller", int(v) if v else 0))
        bottom.addWidget(self.controller_field, stretch=1)
        focus_register(self.controller_field)

        self._coord_fields = {}
        for key, label, lo, hi in (
            ("angle", "angle°", -180, 180), ("x", "x", -100, 100),
            ("y", "y", -100, 100), ("z", "z", -100, 100),
        ):
            field = NumberField(label, lo=lo, hi=hi, allow_blank=True)
            field.label_width = 44
            field.set_value(data.get(key))
            field.edited.connect(lambda v, k=key: data.__setitem__(k, int(v) if v else None))
            bottom.addWidget(field, stretch=1)
            focus_register(field)
            self._coord_fields[key] = field
        v.addLayout(bottom)


class ParameterRow(QWidget):
    """One <PARAMETER name= value=> under an OBJECTIVE. Free name/value pair
    — no per-type schema was ever reversed (see game_specific_variables.py's
    objective_parameter_names), so this is a raw editor, not a validated
    one; the name field's placeholder is the only hint offered."""

    def __init__(self, data: dict, on_remove, focus_register, parent=None):
        super().__init__(parent)
        self.data = data
        h = QHBoxLayout(self)
        h.setContentsMargins(24, 0, 0, 0)
        h.setSpacing(8)

        self.name_field = SuggestField("name", suggestions=gsv.objective_parameter_names,
                                       placeholder="e.g. " + gsv.objective_parameter_names[0])
        self.name_field.label_width = 60
        self.name_field.set_value(data.get("name", ""))
        self.name_field.edited.connect(lambda v: data.__setitem__("name", v))
        h.addWidget(self.name_field, stretch=1)
        focus_register(self.name_field)

        self.value_field = TextField("value")
        self.value_field.label_width = 60
        self.value_field.set_value(str(data.get("value", "")))
        self.value_field.edited.connect(lambda v: data.__setitem__("value", v))
        h.addWidget(self.value_field, stretch=1)
        focus_register(self.value_field)

        rm = compact_button("✕")
        rm.setFixedWidth(32)
        rm.clicked.connect(lambda: on_remove(self))
        h.addWidget(rm)
        focus_register(rm)


class ObjectiveRow(Card):
    """One <OBJECTIVE> — type/mustpass/stringid plus its own nested list of
    PARAMETER rows."""

    def __init__(self, data: dict, on_remove, focus_register, parent=None):
        super().__init__(parent=parent)
        self.data = data
        self._focus_register = focus_register
        data.setdefault("parameters", [])
        v = QVBoxLayout(self)
        v.setContentsMargins(14, 10, 14, 10)
        v.setSpacing(6)

        head = QHBoxLayout()
        self.type_row = SelectorRow("type", compact=True)
        self.type_row.set_values(gsv.objective_types,
                                 index=gsv.objective_types.index(data["type"])
                                 if data.get("type") in gsv.objective_types else 0)
        self.type_row.changed.connect(lambda: data.__setitem__("type", self.type_row.current()))
        head.addWidget(self.type_row, stretch=3)
        focus_register(self.type_row)

        self.mustpass_row = SelectorRow("mustpass", compact=True)
        self.mustpass_row.set_values(["no", "yes"], index=1 if data.get("mustpass") else 0)
        self.mustpass_row.changed.connect(
            lambda: data.__setitem__("mustpass", self.mustpass_row.current() == "yes"))
        head.addWidget(self.mustpass_row, stretch=2)
        focus_register(self.mustpass_row)

        rm = compact_button("✕ REMOVE")
        rm.clicked.connect(lambda: on_remove(self))
        head.addWidget(rm)
        focus_register(rm)
        v.addLayout(head)

        self.stringid_field = TextField("stringid", placeholder="optional")
        self.stringid_field.set_value(data.get("stringid", ""))
        self.stringid_field.edited.connect(lambda v: data.__setitem__("stringid", v))
        v.addWidget(self.stringid_field)
        focus_register(self.stringid_field)

        self.param_list = QVBoxLayout()
        self.param_list.setSpacing(4)
        v.addLayout(self.param_list)
        for param in data["parameters"]:
            self._add_param_row(param)

        add_param_btn = compact_button("+ PARAMETER")
        add_param_btn.clicked.connect(self._add_parameter)
        v.addWidget(add_param_btn, alignment=Qt.AlignLeft)
        focus_register(add_param_btn)

    def _add_param_row(self, param):
        row = ParameterRow(param, self._remove_parameter, self._focus_register)
        self.param_list.addWidget(row)
        return row

    def _add_parameter(self):
        param = {"name": "", "value": ""}
        self.data["parameters"].append(param)
        self._add_param_row(param)

    def _remove_parameter(self, row):
        self.data["parameters"].remove(row.data)
        row.setParent(None)
        row.deleteLater()


class MissionEditorScreen(Screen):
    """Bound to a MatchConfig via `bind(cfg)`, called fresh every time
    match_setup.py's MatchSetupContainer opens this screen — so it always
    reflects whichever match (and cfg instance) is currently being set up,
    the same screen instance reused across matches."""

    def __init__(self, on_back, parent=None):
        super().__init__(on_back=on_back, parent=parent)
        self.cfg = None
        self._build()

    def bind(self, cfg):
        self.cfg = cfg
        self._refresh_from_cfg()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Mission State", breadcrumb="advanced · experimental",
                                   on_back=self.on_back_cb))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet(f"QScrollArea {{ background: {BG_BASE}; border: none; }}")
        scroll.viewport().setStyleSheet(f"background: {BG_BASE};")
        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        v = QVBoxLayout(body)
        v.setContentsMargins(40, 20, 40, 24)
        v.setSpacing(16)

        v.addWidget(Note(
            "Schema is verified against the 93 stock mission files the game "
            "ships with. Behaviour beyond a plain kickoff (a non-default "
            "start mode, or objectives, dropped into an ordinary exhibition "
            "match) has not been confirmed in-game — treat it as "
            "experimental.", color=FG_MUTED))

        # ── start mode ───────────────────────────────────────────────────
        start_card = SectionCard("Start state")
        self.mode_row = SelectorRow("start mode")
        self.mode_row.set_values(gsv.mission_mode_names, index=0)
        self.mode_row.changed.connect(self._on_mode_changed)
        start_card.add(self.mode_row)
        self.focus.register(self.mode_row)

        # Minutes/seconds rather than one raw-seconds box — 9999 seconds
        # meant typing 4 digits and doing the math in your head to know what
        # you'd actually set. Both keypad-typeable (NumberField's own
        # digit-buffer entry — see its docstring); either one changing
        # recombines into cfg.mission_mode_time, the single seconds value
        # the .mis MODE time= attribute actually wants.
        time_row = QHBoxLayout()
        time_row.setSpacing(8)
        self.mode_min_field = NumberField("min", lo=0, hi=200, allow_blank=True)
        self.mode_min_field.edited.connect(self._on_mode_minsec_changed)
        time_row.addWidget(self.mode_min_field, stretch=1)
        self.focus.register(self.mode_min_field)

        self.mode_sec_field = NumberField("sec", lo=0, hi=59, allow_blank=True)
        self.mode_sec_field.edited.connect(self._on_mode_minsec_changed)
        time_row.addWidget(self.mode_sec_field, stretch=1)
        self.focus.register(self.mode_sec_field)
        start_card.add_layout(time_row)

        self.mode_period_field = NumberField("period", lo=0, hi=5, allow_blank=True)
        self.mode_period_field.edited.connect(self._on_mode_period_changed)
        start_card.add(self.mode_period_field)
        self.focus.register(self.mode_period_field)
        v.addWidget(start_card)

        # ── restart position (NIS) ──────────────────────────────────────
        self.nis_card = SectionCard("Restart position (NIS)")
        self.nis_list = QVBoxLayout()
        self.nis_list.setSpacing(6)
        self.nis_card.add_layout(self.nis_list)
        add_nis_btn = compact_button("+ RESTART POSITION")
        add_nis_btn.clicked.connect(self._add_nis)
        self.nis_card.add(add_nis_btn)
        self.focus.register(add_nis_btn)
        v.addWidget(self.nis_card)

        # ── score events ─────────────────────────────────────────────────
        self.score_card = SectionCard("Score so far")
        self.score_list = QVBoxLayout()
        self.score_list.setSpacing(6)
        self.score_card.add_layout(self.score_list)
        add_score_btn = compact_button("+ SCORE EVENT")
        add_score_btn.clicked.connect(self._add_score_event)
        self.score_card.add(add_score_btn)
        self.focus.register(add_score_btn)
        v.addWidget(self.score_card)

        # ── objectives ───────────────────────────────────────────────────
        self.objectives_card = SectionCard("Objectives")
        self.objectives_list = QVBoxLayout()
        self.objectives_list.setSpacing(8)
        self.objectives_card.add_layout(self.objectives_list)
        add_obj_btn = compact_button("+ OBJECTIVE")
        add_obj_btn.clicked.connect(self._add_objective)
        self.objectives_card.add(add_obj_btn)
        self.focus.register(add_obj_btn)
        v.addWidget(self.objectives_card)

        v.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("B", "back")])
        root.addWidget(self.hintbar)

    # ── binding ──────────────────────────────────────────────────────────
    def _refresh_from_cfg(self):
        cfg = self.cfg
        idx = (gsv.mission_mode_names.index(cfg.mission_mode_name)
              if cfg.mission_mode_name in gsv.mission_mode_names else 0)
        self.mode_row.set_index(idx)
        total = cfg.mission_mode_time
        if total is None:
            self.mode_min_field.set_value(None)
            self.mode_sec_field.set_value(None)
        else:
            minutes, seconds = divmod(int(total), 60)
            self.mode_min_field.set_value(minutes)
            self.mode_sec_field.set_value(seconds)
        self.mode_period_field.set_value(cfg.mission_mode_period)
        self._rebuild_nis_rows()
        self._rebuild_score_rows()
        self._rebuild_objective_rows()

    @staticmethod
    def _clear_layout(layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()

    def _rebuild_nis_rows(self):
        self._clear_layout(self.nis_list)
        for nis in self.cfg.mission_nis:
            self.nis_list.addWidget(NisRow(nis, self._remove_nis, self.focus.register))

    def _rebuild_score_rows(self):
        self._clear_layout(self.score_list)
        for ev in self.cfg.score_events:
            self.score_list.addWidget(
                ScoreEventRow(ev, self._remove_score_event, self.focus.register))

    def _rebuild_objective_rows(self):
        self._clear_layout(self.objectives_list)
        for obj in self.cfg.objectives:
            self.objectives_list.addWidget(
                ObjectiveRow(obj, self._remove_objective, self.focus.register))

    # ── start mode ───────────────────────────────────────────────────────
    def _on_mode_changed(self):
        self.cfg.mission_mode_name = self.mode_row.current() or ""

    def _on_mode_minsec_changed(self, _v):
        # Blank in both boxes = no override (cfg.mission_mode_time stays
        # None, the sentinel that keeps the .mis MODE's time= attribute
        # unset — see game_files_processor.create_mission_file). Either
        # box holding a value is enough to produce a real total; the other,
        # if left blank, counts as 0 rather than blocking the edit.
        minutes = self.mode_min_field.as_int()
        seconds = self.mode_sec_field.as_int()
        if minutes is None and seconds is None:
            self.cfg.mission_mode_time = None
        else:
            self.cfg.mission_mode_time = (minutes or 0) * 60 + (seconds or 0)

    def _on_mode_period_changed(self, v):
        self.cfg.mission_mode_period = int(v) if v else None

    # ── restart position (NIS) ──────────────────────────────────────────
    def _add_nis(self):
        nis = {"script_name": "", "controller": 0, "team": "home", "player": 0,
              "angle": None, "x": None, "y": None, "z": None}
        self.cfg.mission_nis.append(nis)
        self.nis_list.addWidget(NisRow(nis, self._remove_nis, self.focus.register))

    def _remove_nis(self, row):
        self.cfg.mission_nis.remove(row.data)
        row.setParent(None)
        row.deleteLater()

    # ── score events ─────────────────────────────────────────────────────
    def _add_score_event(self):
        ev = {"type": gsv.score_event_types[0], "team": "home", "player": 0, "time": 0}
        self.cfg.score_events.append(ev)
        self.score_list.addWidget(
            ScoreEventRow(ev, self._remove_score_event, self.focus.register))

    def _remove_score_event(self, row):
        self.cfg.score_events.remove(row.data)
        row.setParent(None)
        row.deleteLater()

    # ── objectives ───────────────────────────────────────────────────────
    def _add_objective(self):
        obj = {"type": gsv.objective_types[0], "mustpass": False, "stringid": "", "parameters": []}
        self.cfg.objectives.append(obj)
        self.objectives_list.addWidget(
            ObjectiveRow(obj, self._remove_objective, self.focus.register))

    def _remove_objective(self, row):
        self.cfg.objectives.remove(row.data)
        row.setParent(None)
        row.deleteLater()
