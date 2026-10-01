"""
screens/challenge_editor.py — Challenge editor (Tools)
=========================================================
Authors the files in mod_data/challenges/ (see app/challenges.py): one match
per file — squads, rules, weather, presentation extras, a mid-match starting
state, objectives, and the texts/unlocks that frame it in CHALLENGE MODE.

The edited challenge is one plain dict (`self.data`); every field writes its
key back on change, the score/restart/objective rows mutate their own dicts
in place (they are the same row widgets the advanced mission editor uses).
SAVE writes the file; moving to another challenge with unsaved edits asks
first.
"""
import copy
import json

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFrame
from PyQt5.QtCore import Qt

from backend import game_specific_variables as gsv
from app import challenges as ch
from app.screen_base import Screen
from ui.broadcast import HintBar, page_header
from ui.editor_kit import (
    SectionCard, TextField, NumberField, ChoiceField, SegmentField, SuggestField, FieldGrid,
    ConfirmDialog, Note, compact_button,
)
from ui.theme import BG_BASE, FG_MUTED, FG_SECONDARY, GREEN, WARN
from screens.mission_editor import ScoreEventRow, NisRow, ObjectiveRow


def _yes_no(value):
    return {True: "yes", False: "no"}.get(value, "stock")


class UnlockableRow(QWidget):
    """One <UNLOCKABLE name= id=> — what a win gives the player."""

    def __init__(self, data, on_remove, focus_register, parent=None):
        super().__init__(parent)
        self.data = data
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(8)
        self.name_field = TextField("unlocks", placeholder="e.g. MATCH BALL 1")
        self.name_field.set_value(data.get("name", ""))
        self.name_field.edited.connect(lambda v: data.__setitem__("name", v))
        h.addWidget(self.name_field, stretch=3)
        focus_register(self.name_field)
        self.id_field = NumberField("id", lo=0, hi=999, allow_blank=False)
        self.id_field.label_width = 50
        self.id_field.set_value(data.get("id", 0))
        self.id_field.edited.connect(lambda v: data.__setitem__("id", int(v) if v else 0))
        h.addWidget(self.id_field, stretch=1)
        focus_register(self.id_field)
        rm = compact_button("✕")
        rm.setFixedWidth(32)
        rm.clicked.connect(lambda: on_remove(self))
        h.addWidget(rm)
        focus_register(rm)


class ChallengeEditorScreen(Screen):
    def __init__(self, ds, on_back, parent=None):
        super().__init__(on_back=on_back, parent=parent)
        self.ds = ds
        self.cid = None          # None = a new, never-saved challenge
        self.data = ch.new_challenge()
        self._saved = json.dumps(self.data, sort_keys=True)
        self._all = {}
        self._dialog = None
        self._loading = False
        self._build()
        self.reload_list()

    # ── build ────────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Challenge Editor", breadcrumb="tools · mod data",
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
        self._bound = []   # (field, refresh) — refresh() re-reads the field from self.data

        # ── file ─────────────────────────────────────────────────────────
        card = SectionCard("Challenge file")
        self.pick_field = ChoiceField("challenge", allow_blank=False)
        self.pick_field.edited.connect(self._on_pick)
        card.add(self.pick_field)
        self.focus.register(self.pick_field)
        row = QHBoxLayout()
        row.setSpacing(8)
        for text, slot in (("NEW", self._new), ("SAVE", self._save),
                           ("DUPLICATE", self._duplicate), ("DELETE", self._confirm_delete)):
            b = compact_button(text, "primary" if text == "SAVE" else "neutral")
            b.clicked.connect(slot)
            row.addWidget(b)
            self.focus.register(b)
        row.addStretch(1)
        card.add_layout(row)
        self.status = Note("", color=FG_SECONDARY)
        card.add(self.status)
        v.addWidget(card)

        # ── description ──────────────────────────────────────────────────
        card = SectionCard("Briefing")
        grid = FieldGrid(columns=1)
        self._text(grid, "name", "name")
        self._text(grid, "description", "briefing", placeholder="shown before the match")
        self._text(grid, "win_text", "on win", placeholder="shown after a win")
        self._text(grid, "draw_text", "on draw", placeholder="shown after a draw")
        self._text(grid, "loss_text", "on loss", placeholder="shown after a loss")
        self._number(grid, "order", "list position", 0, 999, blank=False)
        card.add(grid)
        v.addWidget(card)

        # ── teams ────────────────────────────────────────────────────────
        card = SectionCard("Teams")
        grid = FieldGrid(columns=1)
        self._choice(grid, "user_side", "you control", ch.USER_SIDES)
        self._team_fields(grid, "home")
        self._team_fields(grid, "away")
        card.add(grid)
        v.addWidget(card)

        # ── match rules ──────────────────────────────────────────────────
        card = SectionCard("Match rules")
        grid = FieldGrid(columns=2)
        self._stadium_field(grid)
        self._choice(grid, "difficulty", "difficulty", ch.DIFFICULTIES)
        self._choice(grid, "halftime_length", "half length", ch.HALF_LENGTHS)
        self._choice(grid, "kick_off", "kick-off", ch.KICK_OFFS)
        self._choice(grid, "home_team_side", "home plays", ch.SIDES)
        self._choice(grid, "match_type", "match type", list(gsv.match_type))
        self._choice(grid, "match_subtype", "stage", list(gsv.match_subtype))
        self._choice(grid, "kick_assist", "easy goal kick", [False, True], display=_yes_no)
        card.add(grid)
        v.addWidget(card)

        # ── weather ──────────────────────────────────────────────────────
        card = SectionCard("Weather & pitch")
        grid = FieldGrid(columns=2)
        self._choice(grid, "environment", "environment", ch.ENVIRONMENTS)
        self._choice(grid, "pitch_texture", "pitch", ["default"] + gsv.pitch_textures)
        self._choice(grid, "precip_mode", "precipitation", ch.PRECIP_MODES)
        self._choice(grid, "rain", "rain (plain)", [False, True], display=_yes_no)
        self._number(grid, "wind_power", "wind power", 0, 10,
                     convert=lambda n: n or None, show=lambda n: n or 0)
        self._choice(grid, "wind_dir_deg", "wind direction", list(range(0, 360, 45)),
                     display=lambda n: f"{n}°", allow_blank=False)
        self._number(grid, "snow_intensity", "snow intensity", 0, 26)
        self._choice(grid, "breath", "visible breath", [False, True],
                     display=_yes_no, blank="stock")
        card.add(grid)
        v.addWidget(card)

        # ── presentation ─────────────────────────────────────────────────
        card = SectionCard("Presentation")
        grid = FieldGrid(columns=2)
        self._choice(grid, "anthem", "anthem", gsv.anthem_choices, allow_blank=False)
        self._choice(grid, "trophy_lift", "trophy lift", gsv.trophy_lift_choices,
                     allow_blank=False)
        self._choice(grid, "haka_home", "home haka", [False, True], display=_yes_no,
                     allow_blank=False)
        self._choice(grid, "haka_away", "away haka", [False, True], display=_yes_no,
                     allow_blank=False)
        self._choice(grid, "stadium_flags", "stadium flags", [False, True],
                     display=_yes_no, blank="stock")
        card.add(grid)
        v.addWidget(card)

        # ── player choices ───────────────────────────────────────────────
        card = SectionCard("Left to the player")
        card.add(Note("A field set to \"player picks\" is chosen on the match presentation "
                      "screen before kick-off, starting from the value set above. A fixed "
                      "kit is shown there but cannot be changed.", color=FG_MUTED))
        grid = FieldGrid(columns=2)
        for key, label in ch.CHOOSABLE.items():
            self._user_choice_field(grid, key, label)
        card.add(grid)
        v.addWidget(card)

        # ── start state ──────────────────────────────────────────────────
        card = SectionCard("Start state")
        card.add(Note("A non-default start mode, restart positions and objectives follow "
                      "the same schema as the mission editor, and the same caveat: only "
                      "a plain kick-off has been confirmed in-game.", color=FG_MUTED))
        grid = FieldGrid(columns=2)
        self._choice(grid, "mission_mode_name", "start mode", gsv.mission_mode_names[1:],
                     allow_blank=True, blank="kick-off (default)")
        self._number(grid, "mission_mode_period", "period", 0, 5)
        self._mode_min = NumberField("minute", lo=0, hi=200)
        self._mode_sec = NumberField("second", lo=0, hi=59)
        for f in (self._mode_min, self._mode_sec):
            f.edited.connect(self._on_mode_time)
            grid.add(f)
            self.focus.register(f)
        self._bound.append((self._mode_min, self._refresh_mode_time))
        card.add(grid)
        v.addWidget(card)

        self._lists = {}
        self._list_card(v, "mission_nis", "Restart positions (NIS)", "+ RESTART POSITION",
                        NisRow, lambda: {"script_name": "", "controller": 0, "team": "home",
                                         "player": 0, "angle": None, "x": None, "y": None,
                                         "z": None})
        self._list_card(v, "score_events", "Score so far", "+ SCORE EVENT", ScoreEventRow,
                        lambda: {"type": gsv.score_event_types[0], "team": "home",
                                 "player": 0, "time": 0})
        self._list_card(v, "objectives", "Objectives", "+ OBJECTIVE", ObjectiveRow,
                        lambda: {"type": gsv.objective_types[0], "mustpass": False,
                                 "stringid": "", "parameters": []})
        self._list_card(v, "unlockables", "Rewards", "+ REWARD", UnlockableRow,
                        lambda: {"name": "", "id": 0})

        v.addStretch(1)
        scroll.setWidget(body)
        root.addWidget(scroll, stretch=1)
        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "edit"), ("B", "back")])
        root.addWidget(self.hintbar)

    # ── field factories ──────────────────────────────────────────────────
    def _register(self, grid, field, key, refresh):
        grid.add(field)
        self.focus.register(field)
        self._bound.append((field, refresh))
        return field

    def _text(self, grid, key, label, placeholder=""):
        f = TextField(label, placeholder=placeholder)
        f.edited.connect(lambda v, k=key: self._set(k, v))
        return self._register(grid, f, key, lambda: f.set_value(self.data[key]))

    def _number(self, grid, key, label, lo, hi, blank=True, convert=None, show=None):
        f = NumberField(label, lo=lo, hi=hi, allow_blank=blank)
        convert = convert or (lambda n: n)
        show = show or (lambda n: n)

        def write(v):
            n = int(v) if str(v).strip() != "" else None
            self._set(key, convert(n) if n is not None else None)
        f.edited.connect(write)
        return self._register(grid, f, key, lambda: f.set_value(show(self.data[key])))

    def _choice(self, grid, key, label, options, display=None, allow_blank=None, blank="—"):
        # A value the list does not hold (None = "stock"/"default") needs the blank slot.
        if allow_blank is None:
            allow_blank = ch.DEFAULTS[key] is None
        f = ChoiceField(label, options, display=display, allow_blank=allow_blank,
                        blank_label=blank)
        f.edited.connect(lambda v, k=key: self._set(k, None if v == "" else v))
        return self._register(grid, f, key, lambda: f.set_value(self.data[key]))

    def _user_choice_field(self, grid, key, label):
        f = SegmentField(label, ["fixed", "player"],
                         display={"fixed": "fixed", "player": "player picks"}.get)

        def write(v):
            if self._loading:
                return
            picked = set(self.data.get("user_choice") or [])
            picked.discard(key)
            if v == "player":
                picked.add(key)
            # Kept in CHOOSABLE order so the file diffs cleanly.
            self.data["user_choice"] = [k for k in ch.CHOOSABLE if k in picked]
            self._changed()
        f.edited.connect(write)
        return self._register(grid, f, "user_choice",
                              lambda: f.set_value("player" if ch.is_choice(self.data, key) else "fixed"))

    def _team_fields(self, grid, side):
        teams = sorted(((tid, s[max(s)].get("name", tid))
                        for tid, s in self.ds.teams.items()), key=lambda t: t[1].lower())
        names = dict(teams)
        team = ChoiceField(f"{side} team", [t for t, _ in teams], display=lambda t: names.get(t, t),
                           allow_blank=True, blank_label="— choose —")
        season = ChoiceField(f"{side} season", allow_blank=False)
        kit = ChoiceField(f"{side} kit", allow_blank=False)

        def sync_options():
            tid = self.data[side]["team_id"]
            seasons = sorted(self.ds.teams.get(tid, {}), reverse=True)
            season.set_options(seasons)
            kits = list(self.ds.teams.get(tid, {}).get(self.data[side]["season"], {}).get("kits", {}))
            kit.set_options(kits)

        def on_team(v):
            slot = self.data[side]
            slot["team_id"] = v
            seasons = sorted(self.ds.teams.get(v, {}), reverse=True)
            slot["season"] = seasons[0] if seasons else ""
            sync_options()
            season.set_value(slot["season"])
            pick_kit()
            self._changed()

        def pick_kit():
            slot = self.data[side]
            kits = list(self.ds.teams.get(slot["team_id"], {}).get(slot["season"], {}).get("kits", {}))
            want = "home" if side == "home" else "away"
            if slot["kit"] not in kits:
                slot["kit"] = want if want in kits else (kits[0] if kits else "")
            kit.set_value(slot["kit"])

        def on_season(v):
            self.data[side]["season"] = v
            sync_options()
            pick_kit()
            self._changed()

        def on_kit(v):
            self.data[side]["kit"] = v
            self._changed()

        def refresh():
            sync_options()
            slot = self.data[side]
            team.set_value(slot["team_id"])
            season.set_value(slot["season"])
            kit.set_value(slot["kit"])

        team.edited.connect(on_team)
        season.edited.connect(on_season)
        kit.edited.connect(on_kit)
        for f in (team, season, kit):
            grid.add(f)
            self.focus.register(f)
        self._bound.append((team, refresh))

    def _stadium_field(self, grid):
        stadiums = sorted(self.ds.stadiums.items(), key=lambda kv: kv[1].get("name", "").lower())
        names = {sid: f"{i.get('name', sid)} ({i.get('country', '')})" for sid, i in stadiums}
        f = ChoiceField("stadium", [s for s, _ in stadiums], display=lambda s: names.get(s, s),
                        allow_blank=True, blank_label="default")
        f.edited.connect(lambda v: self._set("stadium_id", v))
        self._register(grid, f, "stadium_id", lambda: f.set_value(self.data["stadium_id"]))

    def _list_card(self, layout, key, title, add_text, row_cls, make):
        card = SectionCard(title)
        rows = QVBoxLayout()
        rows.setSpacing(6)
        card.add_layout(rows)
        add = compact_button(add_text)
        card.add(add)
        self.focus.register(add)

        def remove(row):
            self.data[key].remove(row.data)
            row.setParent(None)
            row.deleteLater()
            self._changed()

        def add_row(entry):
            rows.addWidget(row_cls(entry, remove, self.focus.register))

        def on_add():
            entry = make()
            self.data[key].append(entry)
            add_row(entry)
            self._changed()

        def rebuild():
            while rows.count():
                w = rows.takeAt(0).widget()
                if w is not None:
                    w.setParent(None)
                    w.deleteLater()
            for entry in self.data[key]:
                add_row(entry)

        add.clicked.connect(on_add)
        self._bound.append((add, rebuild))
        layout.addWidget(card)

    # ── start-time min/sec ───────────────────────────────────────────────
    def _on_mode_time(self, _v):
        m, s = self._mode_min.as_int(), self._mode_sec.as_int()
        self._set("mission_mode_time", None if m is None and s is None else (m or 0) * 60 + (s or 0))

    def _refresh_mode_time(self):
        total = self.data["mission_mode_time"]
        m, s = (None, None) if total is None else divmod(int(total), 60)
        self._mode_min.set_value(m)
        self._mode_sec.set_value(s)

    # ── state ────────────────────────────────────────────────────────────
    def _set(self, key, value):
        if not self._loading:
            self.data[key] = value
            self._changed()

    def _say(self, text, color=FG_SECONDARY):
        self.status.setText(text)
        self.status.setStyleSheet(f"color: {color}; background: transparent;")

    def _changed(self):
        if self._loading:
            return
        self._say("unsaved changes" if self._dirty() else "", WARN)

    def _dirty(self):
        return json.dumps(self.data, sort_keys=True) != self._saved

    def _display_name(self, cid):
        return self._all.get(cid, {}).get("name", cid)

    def reload_list(self, select=None):
        self._all = ch.load_all()
        self.pick_field.display = lambda c: (self._all[c]["name"] if c in self._all else "(new)")
        options = list(self._all)
        if self.cid is None:
            options = ["(new)"] + options
        self.pick_field.set_options(options)
        if select is not None:
            self._open(select)
        elif self.cid in self._all:
            self.pick_field.set_value(self.cid)
        elif self.cid is None and not self._all:
            self._open(None)
        elif self.cid is None:
            self.pick_field.set_value("(new)")

    def on_show(self):
        super().on_show()
        if not self._dirty():
            self.reload_list()

    def _open(self, cid, data=None):
        """Load `cid` (None = a new challenge) into the fields. `data`
        overrides the file's content (a duplicate starts from a copy)."""
        self._loading = True
        self.cid = cid
        if data is None:
            data = self._all[cid] if cid in self._all else ch.new_challenge()
        self.data = copy.deepcopy(data)
        for _field, refresh in self._bound:
            refresh()
        self._saved = json.dumps(self.data, sort_keys=True)
        self.pick_field.set_options(list(self._all) if cid in self._all
                                    else ["(new)"] + list(self._all))
        self.pick_field.set_value(cid if cid in self._all else "(new)")
        self._loading = False
        self._flag_problems()

    def _flag_problems(self):
        found = ch.problems(self.ds, self.data)
        if found:
            self._say("cannot be played yet: " + "; ".join(found), WARN)
        else:
            self._say(ch.summary(self.ds, self.data))

    # ── actions ──────────────────────────────────────────────────────────
    def _guard(self, then, cancel=None):
        """Run `then` now, or after the user agrees to drop unsaved edits
        (`cancel` runs if they keep editing)."""
        if not self._dirty():
            then()
            return

        def chosen(role):
            self._dialog = None
            if role == "discard":
                then()
            elif cancel:
                cancel()
        self._dialog = ConfirmDialog(
            self, "Discard changes?", "This challenge has unsaved edits.",
            [("KEEP EDITING", "neutral", "cancel"), ("DISCARD", "danger", "discard")], chosen)

    def _on_pick(self, cid):
        if self._loading or cid == (self.cid or "(new)"):
            return
        previous = self.cid
        self._guard(lambda: self._open(None if cid == "(new)" else cid),
                    cancel=lambda: self.pick_field.set_value(previous or "(new)"))

    def _new(self):
        self._guard(lambda: self._open(None))

    def _save(self):
        name = (self.data["name"] or "").strip()
        if not name:
            self._say("give the challenge a name first", WARN)
            return
        cid = self.cid or ch.unique_id(name, set(self._all))
        try:
            ch.save(cid, self.data)
        except OSError as e:
            self._say(f"could not save: {e}", WARN)
            return
        self._all = ch.load_all()
        self._saved = json.dumps(self.data, sort_keys=True)
        self.cid = cid
        self.reload_list()
        self.pick_field.set_value(cid)
        self._say(f"saved as {cid}.json", GREEN)

    def _duplicate(self):
        data = copy.deepcopy(self.data)
        data["name"] = (data["name"] or "challenge") + " copy"
        self._open(None, data)
        self._saved = ""   # a copy is unsaved by definition
        self._changed()

    def _confirm_delete(self):
        if self.cid is None:
            return

        def chosen(role):
            self._dialog = None
            if role == "delete":
                ch.delete(self.cid)
                self.cid = None
                self._all = ch.load_all()
                first = next(iter(self._all), None)
                self.reload_list(select=first)
        self._dialog = ConfirmDialog(
            self, "Delete challenge?",
            f"{self._display_name(self.cid)} will be removed from mod_data/challenges.",
            [("CANCEL", "neutral", "cancel"), ("DELETE", "danger", "delete")], chosen)
