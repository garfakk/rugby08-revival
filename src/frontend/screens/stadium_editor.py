"""
screens/stadium_editor.py — Stadium editor (Tools)
====================================================
The mod's own stadiums (data/stadiums/<Folder>: their own scene packs) in
3D, wearing the dressing you try on them: post pads and corner flags,
posts, ad boards, or a competition's look at once. Hovering a set in a list
puts it on the stadium; SAVE writes the picks as the stadium's "dressing"
in the user's edits (user_data/edits/stadiums, app/dressing.save_stadium), which every match there then wears
unless the match or its competition picks another. The Pitch tab shows the
game's pitch textures on the grass and ticks the ones a match there may use
(the stadium's "pitches": quick match offers only those, a tournament draws
its weather's pitch from them).

Layout (EditorScreen): the stadiums on the left, the tabs in the middle,
the 3D view on the right (camera views, zoom, environment).

A record is {"pads", "posts", "ads", "pitches"}: a set reference each, ""
= the stock set of the stadium's game slot, and the pitch names ticked
([] = any).
"""
import math
import os

from PyQt5.QtCore import Qt, QTimer
from PyQt5.QtWidgets import QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from app import dressing, user_stadiums
from app.game_data import save_target
from backend import pitch_lines, pitch_logos, pitch_stripes, pitches
from shared.log import get_logger
from ui.dressing_picker import DressingRow
from ui.editor_kit import (ChoiceField, FieldGrid, Note, NumberField, SectionCard, SegmentField, ToggleGrid,
                           compact_button)
from ui.pitch_grid import PitchGrid
from ui.theme import ACCENT, FG_SECONDARY, FG_TERTIARY, GREEN

from .editor_base import EditorScreen

log = get_logger(__name__)

KIND_LABELS = {"pads": "pads & flags", "posts": "posts", "ads": "ad boards"}
ENV_ORDER = ("day", "overcast", "night", "cold")


class LiveDressingRow(DressingRow):
    """A dressing list whose cursor tries the set on the big 3D view
    (`on_try(ref)`); closing it without a pick puts the current one back
    (`on_restore()`)."""

    def __init__(self, label, kind, get_choices, on_try, on_restore, parent=None):
        super().__init__(label, kind, get_choices, preview=None, parent=parent)
        self._on_try, self._on_restore = on_try, on_restore
        self.group_open = self.group_order          # every set listed: this is the place to browse them

    def _make_preview(self):
        holder = QWidget()
        holder.setFixedHeight(0)

        def show(option):
            try:
                self._on_try(self.effective_ref(option))
            except Exception as e:             # a broken set must not break the list
                log.warning(f"{self.kind} preview: {e}")
        return holder, show

    def _on_popup_closed(self):
        super()._on_popup_closed()
        self._on_restore()


class _LogoDrag:
    """Drags a pitch logo on the 3D view (the Logos tab): a press on one
    picks it, the drag moves it, the release makes it one undo step."""

    def __init__(self, editor):
        self.ed = editor
        self.start = None

    def press(self, x, z):
        ed = self.ed
        if ed.session is None or ed.shell.tabs.index() != 2:
            return False
        best = None
        for i, logo in enumerate(ed._logos()):
            d = math.hypot(x / pitch_logos.UNITS_PER_M - logo["x"], z / pitch_logos.UNITS_PER_M - logo["z"])
            if d <= max(2.0, logo["size"] * 0.6) and (best is None or d < best[0]):
                best = (d, i)
        if best is None:
            return False
        ed._logo_index = best[1]
        logo = ed._logos()[best[1]]
        self.start = (x, z, logo["x"], logo["z"])
        ed._refresh_logo_fields()
        return True

    def move(self, x, z):
        ed = self.ed
        if self.start is None:
            return
        sx, sz, lx, lz = self.start
        i = ed._logo_index
        nx = round(lx + (x - sx) / pitch_logos.UNITS_PER_M, 1)
        nz = round(lz + (z - sz) / pitch_logos.UNITS_PER_M, 1)

        def change(ls):
            ls[i]["x"], ls[i]["z"] = nx, nz
        ed._edit_logos("move a logo", change, coalesce=("logo drag", id(self.start)))
        ed._show_logos(fast=True)

    def release(self):
        self.start = None
        self.ed._show_logos()


class StadiumEditorScreen(EditorScreen):
    TAB_TITLES = ["Dressing", "Pitch", "Logos"]
    RECORD_NOUN = "stadium"
    LIST_PLACEHOLDER = "filter"
    PREVIEW_PANE = True
    GROUP_LABEL = "Country"
    SORTS = [("name", "name")]

    def __init__(self, ds, on_back):
        self._scene = None
        self._scene_key = None
        self._applied = {}            # kind -> ref shown on the view
        self._env = ""
        self._rows_for = None
        self._pitch_shown = None      # the pitch name on the view
        self._pitch_key = ""          # the tile it was asked for ("" = the stadium's own)
        self._pitch_pics = False
        self._pack_stripe_cache = {}  # (stadium, environment) -> the scene pack's own stripes
        super().__init__(ds, on_back)
        self._layout_panes()
        self._build_dressing()
        self._build_pitch()
        self._build_logos()
        self._build_view()
        self.view.ground_handler = _LogoDrag(self)
        self.shell.tabs.changed.connect(lambda _i: self._show_logos())
        self.filters_toggle.hide()
        self.dup_btn.hide()
        self.new_btn.hide()
        self.reset_btn = compact_button("RESET")
        self.reset_btn.setToolTip("the stock dressing of the stadium's slot, any pitch")
        self.reset_btn.clicked.connect(self._reset)
        self.shell.list_layout.itemAt(0).layout().addWidget(self.reset_btn)
        self.focus.register(self.reset_btn)
        self.shell.footer.target.setText("")

    # ── layout ───────────────────────────────────────────────────────────
    def _layout_panes(self):
        sh = self.shell
        sh.list_pane.setFixedWidth(240)
        sh.tabs.set_metrics(13, 30)
        for w in (sh.tabs, sh.stack):
            w.setMaximumWidth(460)
            w.setMinimumWidth(360)
        sh.preview_pane.setMinimumWidth(360)
        sh.preview_pane.setMaximumWidth(16777215)
        sh.preview_pane.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        body = sh.right_layout.parent()
        if body is not None:
            body.setStretchFactor(sh.right_layout, 0)
            body.setStretchFactor(sh.preview_pane, 1)

    def _build_dressing(self):
        page = self.shell.page(0).layout_
        card = SectionCard("Stadium")
        grid = FieldGrid(columns=1)
        self.f_enabled = SegmentField("played", ["on", "off"],
                                      display={"on": "in matches", "off": "not played"}.get)
        self.f_enabled.edited.connect(self._set_enabled)
        grid.add(self.f_enabled)
        self.register_field("enabled", self.f_enabled, 0)
        card.add(grid)
        page.addWidget(card)
        card = SectionCard("Dressing")
        self.rows = {}
        for kind in dressing.KINDS:
            row = LiveDressingRow(KIND_LABELS[kind], kind,
                                  lambda cur, k=kind: self._choices(k, cur),
                                  on_try=lambda ref, k=kind: self._show({k: ref}),
                                  on_restore=self._show_record)
            row.changed.connect(lambda k=kind, r=row: self._pick(k, r.current_ref()))
            self.register_field(kind, row, 0)
            card.add(row)
            self.rows[kind] = row
        page.addWidget(card)

        card = SectionCard("A competition's look")
        grid = FieldGrid(columns=1)
        self.f_comp = ChoiceField("competition", allow_blank=True, blank_label="try one…",
                                  display=lambda i: self._looks[int(i)]["label"] if str(i).isdigit()
                                  and int(i) < len(self._looks) else "")
        self.f_comp.searchable = True
        self.f_comp.popup_title = "pads, posts and ads of"
        self.f_comp.edited.connect(self._pick_look)
        grid.add(self.f_comp)
        self.register_field("competition", self.f_comp, 0)
        card.add(grid)
        page.addWidget(card)
        self.note = Note("", color=FG_TERTIARY)
        page.addWidget(self.note)
        page.addStretch(1)
        self._looks = []

    def _build_pitch(self):
        page = self.shell.page(1).layout_
        regions = {}
        for name in pitches.NAMES:
            regions.setdefault(pitches.region_of(name), []).append((name, pitches.label(name)))
        groups = [("", [("", "Stadium's own")])] + list(regions.items())
        card = SectionCard("Environments")
        self.f_envs = ToggleGrid([], columns=2)
        self.f_envs.toggled.connect(self._toggle_env)
        self.register_field("environments", self.f_envs, 1)
        card.add(self.f_envs)
        page.addWidget(card)
        card = SectionCard("Stripes")
        grid = FieldGrid(columns=1)
        self.stripe_fields = {}
        for key, label in (("opacity", "opacity (%)"), ("brightness", "brightness (%)")):
            lo, hi = pitch_stripes.RANGES[key]
            f = NumberField(label, lo=lo, hi=hi, allow_blank=False)
            f.edited.connect(lambda v, k=key: self._set_stripe(k, v))
            grid.add(f)
            self.register_field(f"stripes.{key}", f, 1)
            self.stripe_fields[key] = f
        card.add(grid)
        row = QHBoxLayout()
        self.stripe_stock = compact_button("STOCK")
        self.stripe_stock.clicked.connect(self._stock_stripes)
        row.addWidget(self.stripe_stock)
        self.focus.register(self.stripe_stock)
        row.addStretch(1)
        card.add_layout(row)
        page.addWidget(card)
        card = SectionCard("Lines")
        grid = FieldGrid(columns=1)
        self.f_lines = SegmentField("numbers", ["on", "off"])
        self.f_lines.edited.connect(self._set_lines)
        grid.add(self.f_lines)
        self.register_field("lines", self.f_lines, 1)
        card.add(grid)
        page.addWidget(card)
        card = SectionCard("Default pitch")
        grid = FieldGrid(columns=1)
        labels = pitches.simple_labels(sorted(pitches.NAMES, key=pitches.condition_order))
        self.f_default_pitch = ChoiceField("pitch", sorted(pitches.NAMES, key=pitches.condition_order),
                                           allow_blank=True, blank_label="stadium's own",
                                           display=lambda n: f"{labels.get(n, n)} · {pitches.full_label(n)}"
                                           if n else "stadium's own")
        self.f_default_pitch.popup_title = "the pitch of a match left on default"
        self.f_default_pitch.on_hover = lambda n: self._show_pitch(n or "")
        self.f_default_pitch.on_popup_closed = lambda: self._show_pitch(self.d.get("pitch", ""))
        self.f_default_pitch.edited.connect(self._set_default_pitch)
        grid.add(self.f_default_pitch)
        self.register_field("pitch", self.f_default_pitch, 1)
        card.add(grid)
        page.addWidget(card)
        card = SectionCard("Pitches")
        row = QHBoxLayout()
        row.setSpacing(6)
        self.pitch_count = Note("", color=FG_SECONDARY)
        self.pitch_count.setMinimumWidth(0)
        row.addWidget(self.pitch_count, stretch=1)
        self.pitch_all = compact_button("ALL")
        self.pitch_none = compact_button("NONE")
        self.pitch_all.clicked.connect(lambda: self._pick_pitches(list(pitches.NAMES)))
        self.pitch_none.clicked.connect(lambda: self._pick_pitches([]))
        for w in (self.pitch_all, self.pitch_none):
            row.addWidget(w)
            self.focus.register(w)
        card.add_layout(row)
        self.f_pitches = PitchGrid(groups)
        self.f_pitches.toggled.connect(self._toggle_pitch)
        self.f_pitches.previewed.connect(self._show_pitch)
        self.register_field("pitches", self.f_pitches, 1)
        card.add(self.f_pitches)
        page.addWidget(card)
        page.addStretch(1)

    def _build_logos(self):
        page = self.shell.page(2).layout_
        card = SectionCard("Pitch logos")
        grid = FieldGrid(columns=1)
        self.f_logo_look = ChoiceField("competition", allow_blank=False,
                                       display=lambda c: dict(self._logo_looks).get(c, c))
        self.f_logo_look.searchable = True
        self.f_logo_look.popup_title = "pitch logos of"
        self.f_logo_look.edited.connect(lambda _v: self._show_logos())
        grid.add(self.f_logo_look)
        self.focus.register(self.f_logo_look)
        self.f_logo = ChoiceField("logo", allow_blank=False, display=self._logo_label)
        self.f_logo.edited.connect(self._select_logo)
        grid.add(self.f_logo)
        self.register_field("logo", self.f_logo, 2)
        self.f_logo_kind = SegmentField("type", list(pitch_logos.TYPES),
                                        display=lambda k: {"centre": "main", "side": "side"}[k])
        self.f_logo_kind.edited.connect(lambda v: self._set_logo("kind", v))
        grid.add(self.f_logo_kind)
        self.register_field("logo.kind", self.f_logo_kind, 2)
        self.logo_fields = {}
        for key, label, lo, hi in (("x", "across (m)", -60, 60), ("z", "along (m)", -80, 80),
                                   ("size", "size (m)", 1, 60), ("angle", "turn (°)", -180, 180)):
            f = NumberField(label, lo=lo, hi=hi, allow_blank=False)
            f.edited.connect(lambda v, k=key: self._set_logo(k, v))
            grid.add(f)
            self.register_field(f"logo.{key}", f, 2)
            self.logo_fields[key] = f
        card.add(grid)
        row = QHBoxLayout()
        row.setSpacing(6)
        self.logo_add = compact_button("+ ADD")
        self.logo_remove = compact_button("REMOVE")
        self.logo_stock = compact_button("STOCK")
        self.logo_add.clicked.connect(self._add_logo)
        self.logo_remove.clicked.connect(self._remove_logo)
        self.logo_stock.clicked.connect(self._stock_logos)
        for b in (self.logo_add, self.logo_remove, self.logo_stock):
            row.addWidget(b)
            self.focus.register(b)
        row.addStretch(1)
        card.add_layout(row)
        page.addWidget(card)
        self.logo_note = Note("", color=FG_TERTIARY)
        page.addWidget(self.logo_note)
        page.addStretch(1)
        self._logo_looks = []
        self._logo_index = 0
        self._logo_images = {}

    def _build_view(self):
        lay = self.shell.preview_layout
        lay.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(8)
        from ui.stadium_view import VIEW_LABELS, StadiumView
        self.f_view = SegmentField("", list(VIEW_LABELS), display=lambda v: VIEW_LABELS[v])
        self.f_view.label_width = 0
        self.f_view.set_value("broadcast")
        self.f_view.edited.connect(lambda v: self.view.set_view(v))
        bar.addWidget(self.f_view, stretch=1)
        self.zoom_out = compact_button("−")
        self.zoom_in = compact_button("+")
        for b, f in ((self.zoom_out, 1 / 0.8), (self.zoom_in, 0.8)):
            b.setFixedWidth(40)
            b.clicked.connect(lambda _=False, f=f: self.view.zoom(f))
            bar.addWidget(b)
            self.focus.register(b)
        self.focus.register(self.f_view)
        lay.addLayout(bar)
        self.view = StadiumView()
        self.view.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.view.view_changed.connect(lambda name: self.f_view.set_value(name))
        lay.addWidget(self.view, stretch=1)
        self.focus.register(self.view)
        bottom = QHBoxLayout()
        self.f_env = SegmentField("", [], display=self._env_label)
        self.f_env.label_width = 0
        self.f_env.edited.connect(self._pick_env)
        bottom.addWidget(self.f_env, stretch=1)
        self.focus.register(self.f_env)
        lay.addLayout(bottom)

    # ── data ─────────────────────────────────────────────────────────────
    def _info(self, sid=None):
        return dict(self.ds.all_stadiums.get(str(self.record_id if sid is None else sid)) or {})

    def _own_info(self):
        """The stadium without its "dressing": "Default" in the lists is its
        game slot's stock sets."""
        info = self._info()
        info.pop("dressing", None)
        return info

    def _choices(self, kind, current):
        return dressing.choices(self.ds, kind, current, self._own_info(),
                                dressing.suggested_refs(self.ds, kind, (), self._own_info()))

    def _effective(self, kind, ref=None):
        ref = self.d.get(kind, "") if ref is None else ref
        return ref or dressing.own_default(self._own_info(), kind)

    @property
    def d(self):
        return self.session.working if self.session else {}

    def list_rows(self):
        rows = []
        for sid, info in self.ds.all_stadiums.items():
            if not isinstance(info, dict):
                continue
            name = info.get("name") or sid
            country = str(info.get("country") or "").title()
            tag = "OFF" if not user_stadiums.enabled(info) else "EDITED" if user_stadiums.is_edited(sid) else ""
            rows.append({"id": str(sid), "text": name, "tag": tag,
                         "color": FG_TERTIARY if tag == "OFF" else ACCENT,
                         "search": f"{name} {country} {'custom' if info.get('is_custom') else 'stock'}",
                         "group": country, "errors": 0, "issues": 0})
        return rows

    def load_record(self, record_id):
        if str(record_id) not in self.ds.all_stadiums:
            return None
        info = self.ds.all_stadiums[str(record_id)]
        own = info.get("dressing") or {}
        logos = pitch_logos.clean(info["pitch_logos"]) if info.get("pitch_logos") is not None else None
        stripes = {e: pitch_stripes.clean(v) for e, v in (info.get("stripes") or {}).items()}
        envs = [e for e in ENV_ORDER if e in (info.get("environments") or [])]
        return dict({k: own.get(k, "") for k in dressing.KINDS}, pitches=pitches.allowed(info),
                    logos=logos, stripes={e: v for e, v in stripes.items() if v},
                    environments=envs or self._default_envs_of(info, record_id),
                    pitch=str(info.get("pitch") or ""), lines=pitch_lines.clean(info.get("lines") or ""),
                    enabled=user_stadiums.enabled(info))

    def write_record(self):
        w = self.session.working
        envs = None if set(w["environments"]) == set(self._default_envs()) else w["environments"]
        path = dressing.save_stadium(self.ds, self.record_id, {k: w[k] for k in dressing.KINDS},
                                     w["pitches"], w["logos"], w["stripes"], envs,
                                     enabled=w["enabled"], pitch=w["pitch"], lines=w["lines"])
        return f"Saved in {save_target(path)}"

    # ── edits ────────────────────────────────────────────────────────────
    def _pick(self, kind, ref):
        if self.session is None or self.d.get(kind, "") == (ref or ""):
            return

        def mutate(w):
            w[kind] = ref or ""
        self.edit(KIND_LABELS[kind], mutate)

    def _pick_look(self, value):
        if self.session is None or not str(value).isdigit():
            return
        look = self._looks[int(value)]

        def mutate(w):
            for kind in dressing.KINDS:
                if kind in look["refs"]:
                    w[kind] = look["refs"][kind]
        self.edit(look["label"], mutate)
        QTimer.singleShot(0, lambda: self.f_comp.set_value(""))

    def _reset(self):
        if self.session is None:
            return

        def mutate(w):
            for kind in dressing.KINDS:
                w[kind] = ""
            w["pitches"] = []
            w["logos"] = None
            w["stripes"] = {}
            w["environments"] = self._default_envs()
            w["pitch"] = ""
            w["lines"] = ""
            w["enabled"] = True
        self.edit("stock dressing", mutate)

    def _set_lines(self, value):
        style = "no_numbers" if value == "off" else ""
        if self.session is None or self.d.get("lines", "") == style:
            return

        def mutate(w):
            w["lines"] = style
        self.edit(pitch_lines.LABELS[style], mutate)

    def _show_lines(self):
        """The stadium's line style on the view."""
        self.view.set_line_style(self.d.get("lines", "") if self.session else "")

    def _set_enabled(self, value):
        on = value != "off"
        if self.session is None or self.d["enabled"] == on:
            return

        def mutate(w):
            w["enabled"] = on
        self.edit("played" if on else "not played", mutate)

    def _set_default_pitch(self, name):
        name = name or ""
        if self.session is None or self.d["pitch"] == name:
            return

        def mutate(w):
            w["pitch"] = name
        self.edit("default pitch", mutate)
        self._show_pitch(name)

    def _toggle_pitch(self, name, on):
        have = set(self.d["pitches"])
        (have.add if on else have.discard)(name)
        self._pick_pitches([n for n in pitches.NAMES if n in have])

    def _pick_pitches(self, names):
        if self.session is None or self.d["pitches"] == names:
            return

        def mutate(w):
            w["pitches"] = list(names)
        self.edit("pitches", mutate)

    def _env_label(self, env):
        """"closed" for the environment that has the stadium's roof shut."""
        from app.tournament import weather
        return weather.env_label(self._info(), env)

    @staticmethod
    def _default_envs_of(info, sid=None):
        """What the stadium offers until told otherwise: the environments the
        data pack lists for it, else (a custom stadium) its own scenes'."""
        own = (user_stadiums.pack_of(sid, info) if sid is not None else {}).get("environments") \
            or list(info.get("scenes") or {})
        return [e for e in ENV_ORDER if e in own]

    def _default_envs(self):
        return self._default_envs_of(self._info(), self.record_id)

    def _toggle_env(self, env, on):
        if self.session is None:
            return
        have = set(self.d["environments"])
        (have.add if on else have.discard)(env)
        names = [e for e in ENV_ORDER if e in have]
        if names and names != self.d["environments"]:
            def mutate(w):
                w["environments"] = names
            self.edit("environments", mutate)
        else:
            self.f_envs.set_values(self.d["environments"])        # the last one stays

    def _pick_env(self, env):
        if env and env != self._env:
            self._env = env
            self._load_scene()
            self._refresh_stripe_fields()

    # ── the 3D view ──────────────────────────────────────────────────────
    def _load_scene(self):
        from backend import stadium_scene
        info = self._info()
        key = (self.record_id, self._env)
        if key == self._scene_key and self._scene is not None:
            return
        self._scene_key = key
        self.view.set_message("Loading…")
        self.view.repaint()

        def go():
            if self._scene_key != key:
                return
            try:
                path = stadium_scene.pack_path(info, self._env)
                scene = stadium_scene.load(path) if path else None
            except Exception as e:
                log.exception("stadium scene")
                scene, path = None, f"error: {e}"
            if scene is None:
                self._scene = None
                self.view.set_message("This stadium's 3D scene isn't found: is the game folder set in "
                                      "Settings?")
                return
            self._scene = scene
            self._applied = {}
            self.view.set_message("")
            self.view.set_scene(scene)
            self.view.set_environment(self._env)
            self._pitch_shown = None
            if self._pitch_pics:
                self._own_tile()
            self._show_pitch()
            self._show_logos()
            self._show_record()
            self.view.set_textures(self._team_textures())
            self._show_lines()
            self._refresh_stripe_fields()
        QTimer.singleShot(10, go)

    def _show(self, refs):
        """Put {kind: ref} ("" = the stadium's own) on the view."""
        if self._scene is None:
            return
        from backend import stadium_scene
        want = {k: self._effective(k, r) for k, r in refs.items()}
        pads = want.get("pads", self._applied.get("pads"))
        posts = want.get("posts", self._applied.get("posts"))
        images = {}
        if ("pads" in want and want["pads"] != self._applied.get("pads")) or \
                ("posts" in want and want["posts"] != self._applied.get("posts")):
            images.update(stadium_scene.pads_textures(pads or "", posts or ""))
            self._applied["pads"], self._applied["posts"] = pads, posts
        if "ads" in want and want["ads"] != self._applied.get("ads"):
            images.update(stadium_scene.ads_textures(self._scene, want["ads"]))
            self._applied["ads"] = want["ads"]
        if images:
            self.view.set_textures(images)

    # ── pitch stripes ────────────────────────────────────────────────────
    def _pack_stripes(self):
        """The stripes the stadium's scene pack of the viewed environment has."""
        key = (self.record_id, self._env)
        if key not in self._pack_stripe_cache:
            from backend import stadium_scene
            path = stadium_scene.pack_path(self._info(), self._env)
            self._pack_stripe_cache[key] = pitch_stripes.read(path) if path else {}
        return self._pack_stripe_cache[key]

    def _stripes(self):
        """{"opacity", "brightness"} (percent) of the viewed environment: the
        stadium's own, else its scene pack's; {} when the pack has none."""
        own = (self.d.get("stripes") or {}).get(self._env) if self.session else None
        return dict(self._pack_stripes(), **own) if own else dict(self._pack_stripes())

    def _set_stripe(self, key, value):
        if self.session is None or not self._env:
            return
        try:
            value = int(round(float(value)))
        except (TypeError, ValueError):
            return
        now = self._stripes()
        if not now or now.get(key) == value:
            return
        env, new = self._env, pitch_stripes.clean(dict(now, **{key: value}))

        def mutate(w):
            w["stripes"] = dict(w["stripes"], **{env: new})
        self.edit("stripes", mutate, coalesce_key=("stripes", key))

    def _stock_stripes(self):
        env = self._env
        if self.session is None or env not in self.d["stripes"]:
            return

        def mutate(w):
            w["stripes"] = {e: v for e, v in w["stripes"].items() if e != env}
        self.edit("stock stripes", mutate)

    def _refresh_stripe_fields(self):
        if self.session is None:
            return
        now = self._stripes()
        for key, f in self.stripe_fields.items():
            f.set_value(str(now[key]) if key in now else "")
            f.setEnabled(bool(now))
        self.stripe_stock.setEnabled(self._env in self.d["stripes"])
        if self._scene is not None:
            self.view.set_stripes(pitch_stripes.contrast(now) if now else None)

    # ── pitch logos ──────────────────────────────────────────────────────
    def _logos(self):
        """The logos shown: the stadium's own layout, else the game's."""
        own = self.d.get("logos") if self.session else None
        return list(own) if own is not None else pitch_logos.stock_layout()

    def _logo_label(self, index):
        logos = self._logos()
        try:
            logo = logos[int(index)]
        except (TypeError, ValueError, IndexError):
            return ""
        return f"{int(index) + 1}. {pitch_logos.KIND_LABELS[logo['kind']]}"

    def _select_logo(self, index):
        try:
            self._logo_index = int(index)
        except (TypeError, ValueError):
            return
        self._refresh_logo_fields()

    def _edit_logos(self, label, change, coalesce=None):
        if self.session is None:
            return

        def mutate(w):
            logos = [dict(l) for l in (w.get("logos") if w.get("logos") is not None
                                       else pitch_logos.stock_layout())]
            change(logos)
            w["logos"] = pitch_logos.clean(logos)
        self.edit(label, mutate, coalesce_key=coalesce)

    def _set_logo(self, key, value):
        logos = self._logos()
        i = self._logo_index
        if not (0 <= i < len(logos)):
            return
        if key == "kind":
            if pitch_logos.type_of(logos[i]["kind"]) == value:
                return
            value = pitch_logos.kind_for(value, logos, skip=i)
        else:
            try:
                value = float(value)
            except (TypeError, ValueError):
                return
            if round(logos[i][key]) == round(value):
                return

        def change(ls):
            ls[i][key] = value
        self._edit_logos("logo " + key, change)

    def _add_logo(self):
        logos = self._logos()
        if len(logos) >= pitch_logos.MAX_LOGOS:
            return
        base = logos[self._logo_index] if 0 <= self._logo_index < len(logos) else \
            {"kind": "side_a", "x": 0.0, "z": 0.0, "size": 8.0, "angle": 0.0}
        new = dict(base, x=round(base["x"] + 10.0) if abs(base["x"]) < 30 else 0.0,
                   kind=pitch_logos.kind_for(pitch_logos.type_of(base["kind"]), logos))

        def change(ls):
            ls.append(new)
        self._edit_logos("add a logo", change)
        self._logo_index = len(logos)

    def _remove_logo(self):
        i = self._logo_index
        if not (0 <= i < len(self._logos())):
            return

        def change(ls):
            del ls[i]
        self._edit_logos("remove a logo", change)
        self._logo_index = max(0, i - 1)

    def _stock_logos(self):
        if self.session is None or self.d.get("logos") is None:
            return

        def mutate(w):
            w["logos"] = None
        self.edit("the game's logos", mutate)

    def _logo_look_images(self):
        """{"loga", "logb": PIL image} of the competition picked to show."""
        from PIL import Image
        from app import competition_branding
        choice = self.f_logo_look.value()
        if choice in self._logo_images:
            return self._logo_images[choice]
        images = {}
        tid, info = competition_branding.resolve(self.ds, choice)
        pattern = (info or {}).get("pitch_logo") or ""
        folder = self.ds.tournaments_folder_path.get(tid, "") if tid else ""
        for i, tag in ((1, "loga"), (2, "logb")):
            path = os.path.join(folder, pattern.replace("%", str(i))) if pattern else ""
            try:
                images[tag] = Image.open(path).convert("RGBA")
            except (OSError, ValueError):
                pass
        self._logo_images[choice] = images
        return images

    def _show_logos(self, fast=False):
        if self._scene is None:
            return
        try:
            quads = pitch_logos.quads(self._logos())
        except Exception as e:                   # a broken model must not break the view
            log.warning(f"pitch logos preview: {e}")
            quads = {}
        self.view.set_logos(quads, self._logo_look_images(), fast=fast)

    def _refresh_logo_fields(self):
        logos = self._logos()
        self.f_logo.set_options([str(i) for i in range(len(logos))])
        self._logo_index = min(self._logo_index, len(logos) - 1) if logos else 0
        self.f_logo.set_value(str(self._logo_index) if logos else "")
        logo = logos[self._logo_index] if logos else None
        self.f_logo_kind.set_value(pitch_logos.type_of(logo["kind"]) if logo else "")
        for key, f in self.logo_fields.items():
            f.set_value(str(round(logo[key])) if logo else "")
            f.setEnabled(logo is not None)
        own = self.d.get("logos") is not None if self.session else False
        self.logo_remove.setEnabled(bool(logos))
        self.logo_add.setEnabled(len(logos) < pitch_logos.MAX_LOGOS)
        self.logo_stock.setEnabled(own)
        self.logo_note.setText("" if logos or pitch_logos.stock_path() else
                               "The game's logo model isn't found: is the game folder set in Settings?")

    def _own_pitch(self):
        """The pitch texture the stadium's scene (in the viewed environment)
        plays on."""
        from backend import stadium_scene
        path = stadium_scene.pack_path(self._info(), self._env)
        return pitches.own_name(path) if path else ""

    def _show_pitch(self, key=None):
        """Lay pitch `key` ("" = the stadium's own) on the view."""
        if self._scene is None:
            return
        self._pitch_key = self._pitch_key if key is None else key
        name = self._pitch_key or self._own_pitch()
        if name == self._pitch_shown:
            return
        self._pitch_shown = name
        self.view.set_pitch(pitches.scene(name) if name else None)

    def _load_pitch_pictures(self):
        """The grass of every texture in the grid (read from the game once)."""
        if self._pitch_pics:
            return
        self._pitch_pics = True
        pics = {n: pitches.grass(n) for n in pitches.NAMES}
        self.f_pitches.set_pictures(pics)
        self._own_tile()

    def _own_tile(self):
        """The first tile: the stadium's own pitch in the viewed environment."""
        own = self._own_pitch()
        self.f_pitches.set_pictures(dict(self.f_pitches.raw, **{"": pitches.grass(own) if own else None}))
        self.f_pitches.set_label("", f"Own · {pitches.label(own)}" if own else "Stadium's own")

    def _home_teams(self):
        """Up to two teams playing here (their latest season's
        `primaryStadium`): [(team id, season block)], nations first."""
        found = []
        for tid in self.ds.teams:
            seasons = self.ds.teams.get(tid) or {}
            for season in sorted(seasons, reverse=True):
                info = seasons[season] or {}
                if info.get("primaryStadium"):
                    if str(info["primaryStadium"]) == str(self.record_id):
                        found.append((info.get("type") != "international", str(season), tid, info))
                    break
        found.sort(key=lambda f: f[0])
        return [(tid, info) for _n, _s, tid, info in found[:2]]

    def _team_textures(self):
        """The flags and banners of the teams at home here (team_textures);
        none found = the stadium's neutral stand-ins."""
        from backend import stadium_scene
        refs = []
        for tid, info in self._home_teams():
            rel = info.get("banners") or ""
            folder = self.ds.teams_folder_path.get(tid, "")
            refs.append(os.path.join(folder, rel) if rel and folder else "")
        refs += ["", ""]
        return stadium_scene.team_textures(refs[0], refs[1])

    def _show_record(self):
        if self.session is not None:
            self._show({k: self.d.get(k, "") for k in dressing.KINDS})

    # ── refresh ──────────────────────────────────────────────────────────
    def on_record_opened(self):
        self._pitch_key = self.d.get("pitch", "") if self.session else ""
        self.f_pitches.cursor = ""
        envs = self._envs()
        self.f_envs.set_items([(e, self._env_label(e)) for e in envs])
        self.f_env.options = envs
        if self._env not in envs:
            self._env = envs[0] if envs else ""
        self.f_env.set_value(self._env)
        self._looks = dressing.competition_looks(self.ds)
        self.f_comp.set_options([str(i) for i in range(len(self._looks))])
        if not self._logo_looks:
            from app import competition_branding
            self._logo_looks = competition_branding.choices(self.ds, "pitch_logo")
            self.f_logo_look.set_options([c for c, _l in self._logo_looks])
            first = next((c for c, l in self._logo_looks if "default" in c.lower()),
                         self._logo_looks[0][0] if self._logo_looks else "")
            self.f_logo_look.set_value(first)
        self._logo_index = 0
        self._load_scene()
        QTimer.singleShot(30, self._load_pitch_pictures)

    def _envs(self):
        from backend import stadium_scene
        return stadium_scene.environments(self._info())

    def refresh_view(self):
        for kind, row in self.rows.items():
            if self._rows_for != self.record_id or row.current_ref() != self.d.get(kind, ""):
                row.refresh(self.d.get(kind, ""))
        self._rows_for = self.record_id
        self.f_pitches.set_values(self.d["pitches"])
        n = len(self.d["pitches"])
        self.pitch_count.setText(f"{n} of {len(pitches.NAMES)} allowed" if n else "any pitch allowed")
        self.f_envs.set_values(self.d["environments"])
        self.f_enabled.set_value("on" if self.d["enabled"] else "off")
        self.f_default_pitch.set_value(self.d["pitch"])
        self.f_lines.set_value("off" if self.d.get("lines") == "no_numbers" else "on")
        own = all(not self.d.get(k) for k in dressing.KINDS) and not n and self.d.get("logos") is None \
            and not self.d["stripes"] and set(self.d["environments"]) == set(self._default_envs()) \
            and not self.d["pitch"] and not self.d.get("lines") and self.d["enabled"]
        self._refresh_logo_fields()
        self._refresh_stripe_fields()
        self._show_logos()
        self.reset_btn.setEnabled(not own)
        dirty = self.session is not None and self.session.is_dirty()
        self.note.setText("SAVE keeps it in your edits." if dirty else "")
        self._show_record()
        if self._scene is not None:
            self._show_lines()

    def collect_issues(self):
        return []

    def header_state(self):
        info = self._info()
        name = info.get("name") or str(self.record_id)
        n = len(info.get("pitches") or [])
        return {"title": name,
                "eyebrow": " · ".join(x for x in (str(info.get("country") or "").title(),
                                                  "dressed" if info.get("dressing") else "",
                                                  f"{n} pitches" if n else "") if x),
                "subtitle": "", "chips": [], "initials": "".join(w[0] for w in name.split()[:2]).upper()}

    def _refresh_chrome(self):
        super()._refresh_chrome()
        self.shell.header.issues_btn.setVisible(False)

    def tab_hints(self, focused):
        if focused is self.view:
            return [("←→↑↓", "turn"), ("+ −", "zoom")]
        return [("↕←→", "move"), ("A", "change")]
