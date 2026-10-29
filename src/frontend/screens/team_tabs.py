"""
screens/team_tabs.py — the four tabs of the team editor
=========================================================
Each tab builds its widgets once (so focus registration never goes stale)
and `refresh()` pushes the working copy of the current season into them.
Every change goes back through `screen.edit(label, fn)`.
"""
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QStackedWidget, QSizePolicy,
)
from PyQt5.QtGui import QPainter, QColor, QPen, QFont, QFontMetrics, QDrag
from PyQt5.QtCore import Qt, QRectF, QTimer, pyqtSignal, QMimeData, QPoint

from app import team_ops as T
from app.game_data import (
    ASSET_SPECS, COUNTRIES, country_label, ROLE_KEYS, SET_PLAYS, TEAM_TYPES, STARTING_XV, SQUAD_SIZE,
    frontend_logo, looks_reversed,
)
from app.ratings import position_overall
from app.season import season_label
from ui.broadcast import Card, draw_frame, tracked_font, display_label, eyebrow_label
from app import variants as V
from ui.editor_kit import (
    VariantPicker, FormDialog,
    FieldGrid, SectionCard, TextField, NumberField, ChoiceField, SegmentField, AssetField, ColorField,
    FrameStrip, Thumb, Note, Badge, TabStrip, browse_assets, load_pixmap, compact_button,
    SEVERITY_COLOR, worst,
)
from ui.team_sheet import (
    MATCH_SHEET_ROWS, SUBSTITUTES, SlotAvatar, SubChip, PlayerPickerPopup, FITS, SEARCH, POSITION_NAMES,
    POSITION_SHORT, ROLE_SHORT, last_name,
)
from ui.widgets import StyledButton
from ui.shirt_name_canvas import NameAreaCanvas
from shared import shirt_names as SN
from shared.config import config
from ui.theme import (
    BG_BASE, BG_CARD, BG_RAISED, BG_HIGHLIGHT, BORDER, BORDER_EM, ACCENT, WARN,
    GREEN, INFO, DANGER_LITE, HOME_TINT, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY,
    FG_MUTED, FONT_DISPLAY, T_SMALL, T_LABEL, T_VALUE, T_TITLE, BTN_HEIGHT_SM,
)

ROLE_LABELS = {
    "captain": "Captain", "viceCaptain": "Vice-captain", "longGK": "Goal kicks (long)",
    "shortGK": "Goal kicks (short)", "longPunt": "Punts (long)", "shortPunt": "Punts (short)",
    "kickoff": "Kick-offs",
}
SET_PLAY_DEFAULTS = {"up": "classic", "down": "pivot", "left": "pocket", "right": "dummy_switch"}
TAB_OVERVIEW, TAB_KITS, TAB_NAMES, TAB_SQUAD, TAB_ASSETS = range(5)


from shared.log import get_logger

log = get_logger(__name__)


def _transparent(widget, name):
    widget.setObjectName(name)
    widget.setStyleSheet(f"QWidget#{name} {{ background: transparent; }}")
    return widget


def _button(text, variant="neutral", h=BTN_HEIGHT_SM):
    return compact_button(text, variant, h)


class TeamTab:
    # Edits follow the squad variant picked in the header only where a squad
    # variant can differ: players, roles and set plays (the squad tab).
    SQUAD_SCOPED = False

    def __init__(self, screen, index):
        self.screen = screen
        self.index = index
        self.page = screen.shell.page(index)
        self.body = self.page.layout_

    def info(self):
        return self.screen.info()

    def edit(self, label, fn, key=None, coalesce=None):
        season = self.screen.season
        picked = getattr(self.screen, "variant", "")
        variant = picked if self.SQUAD_SCOPED else ""
        if variant:
            # edit the variant as it resolves; only its differences are kept
            def mutate(w):
                return T.edit_variant(w[season], variant, fn)
        else:
            def mutate(w):
                return fn(w[season])
        return self.screen.edit(label, mutate, coalesce_key=coalesce,
                                view_hint={"season": season, "variant": picked,
                                           "tab": self.index, "field": key, **self.view_extra()})

    def view_extra(self):
        """Extra view state an undo/redo of this tab's edits brings back."""
        return {}

    def register(self, key, widget):
        return self.screen.register_field(key, widget, self.index)

    def hints(self, focused):
        return []


# ═════════════════════════════════════════════════════════════════════════
# Overview
# ═════════════════════════════════════════════════════════════════════════
def _set_optional(info, key, value):
    value = (value or "").strip()
    if value:
        info[key] = value
    else:
        info.pop(key, None)


class OverviewTab(TeamTab):
    def __init__(self, screen, index):
        super().__init__(screen, index)
        row = QHBoxLayout()
        row.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        right = QVBoxLayout()
        right.setSpacing(12)

        ident = SectionCard("identity · this season")
        grid = FieldGrid(columns=1)
        self.name = self.register("name", TextField("Team name"))
        self.name.edited.connect(lambda v: self.edit("team name", lambda i: i.__setitem__("name", v), "name"))
        grid.add(self.name)
        self.type = self.register("type", SegmentField("Type", TEAM_TYPES))
        self.type.edited.connect(lambda v: self.edit("team type", lambda i: i.__setitem__("type", v), "type"))
        grid.add(self.type)
        self.country = self.register("country", ChoiceField("Country", allow_blank=True, display=country_label))
        self.country.edited.connect(lambda v: self.edit("country", lambda i: _set_optional(i, "country", v), "country"))
        grid.add(self.country)
        self.category = self.register("category", ChoiceField("Category", allow_blank=True))
        self.category.edited.connect(self._on_category)
        grid.add(self.category)
        ident.add(grid)
        left.addWidget(ident)

        crest = SectionCard("crest")
        crow = QHBoxLayout()
        crow.setSpacing(16)
        self.crest_big = Thumb(128, 128)
        crow.addWidget(self.crest_big)
        ccol = QVBoxLayout()
        cgrid = FieldGrid(columns=1)
        self.crest = self.register("logos.main", AssetField("Main crest", ASSET_SPECS["logos.main"]))
        self._wire_asset(self.crest, "logos.main")
        cgrid.add(self.crest)
        self.crest_frontend = self.register("logos.frontend",
                                            AssetField("Frontend logo", ASSET_SPECS["logos.frontend"]))
        self._wire_asset(self.crest_frontend, "logos.frontend")
        cgrid.add(self.crest_frontend)
        ccol.addWidget(cgrid)
        ccol.addStretch(1)
        crow.addLayout(ccol, stretch=1)
        crest.add_layout(crow)
        left.addWidget(crest)
        left.addStretch(1)

        summary = SectionCard("season summary")
        self.summary_grid = QGridLayout()
        self.summary_grid.setHorizontalSpacing(12)
        self.summary_grid.setVerticalSpacing(10)
        self.summary_labels = {}
        for r, (key, label) in enumerate((("squad", "Squad"), ("starters", "Starting XV fit"),
                                          ("roles", "Roles set"), ("kits", "Kits"),
                                          ("assets", "Asset files"))):
            name = display_label(label, T_LABEL, QFont.DemiBold, track=0.6, color=FG_SECONDARY,
                                 upper=False)
            value = display_label("—", T_VALUE, QFont.Bold, track=0.4, upper=False)
            self.summary_grid.addWidget(name, r, 0)
            self.summary_grid.addWidget(value, r, 1)
            self.summary_labels[key] = value
        summary.add_layout(self.summary_grid)
        right.addWidget(summary)

        seasons = SectionCard("seasons of this team")
        self.seasons_note = Note("", color=FG_SECONDARY, size=T_LABEL)
        seasons.add(self.seasons_note)
        srow = QHBoxLayout()
        for text, action in (("ADD", "add"), ("DUPLICATE", "duplicate"), ("DELETE", "delete")):
            b = _button(text, "danger" if action == "delete" else "neutral")
            b.clicked.connect(lambda _=False, a=action: screen.season_action(a))
            screen.focus.register(b)
            srow.addWidget(b)
        seasons.add_layout(srow)
        right.addWidget(seasons)

        danger = SectionCard("team file")
        self.file_note = Note("", color=FG_TERTIARY)
        danger.add(self.file_note)
        self.delete_btn = _button("DELETE TEAM…", "danger")
        self.delete_btn.clicked.connect(screen.delete_record)
        screen.focus.register(self.delete_btn)
        danger.add(self.delete_btn)
        right.addWidget(danger)
        right.addStretch(1)

        row.addLayout(left, stretch=3)
        row.addLayout(right, stretch=2)
        self.body.addLayout(row)

    def _wire_asset(self, field, key):
        field.browse_requested.connect(lambda: browse_assets(
            self.screen, field, self.screen.team_folder(), field.spec, field.value(),
            field.set_picked, title=field.label))
        field.edited.connect(lambda v: self.edit(field.label, lambda i: T_set_path(i, key, v), key))

    def _on_category(self, value):
        if value == "__other__":
            self.screen.ask_text("New category", "Category", self.info().get("category", ""),
                                 lambda v: self.edit("category",
                                                     lambda i: i.__setitem__("category", v),
                                                     "category"))
            self.refresh()
            return
        self.edit("category", lambda i: i.__setitem__("category", value), "category")

    def refresh(self):
        info = self.info()
        self.name.set_value(info.get("name", ""))
        self.type.set_value(info.get("type", ""))
        cur_country = info.get("country", "")
        self.country.set_options(COUNTRIES + ([cur_country] if cur_country and cur_country not in COUNTRIES else []))
        self.country.set_value(cur_country)
        cats = list(self.screen.ds.all_categories())
        cur = info.get("category", "")
        if cur and cur not in cats:
            cats.append(cur)
        self.category.set_options(sorted(cats) + ["__other__"])
        self.category.display = lambda v: "Other…" if v == "__other__" else v
        self.category.set_value(cur)
        root = self.screen.team_folder()
        self.crest.set_root(root)
        self.crest.set_value((info.get("logos") or {}).get("main", ""))
        self.crest_frontend.set_root(root)
        self.crest_frontend.set_value((info.get("logos") or {}).get("frontend", ""))
        shown = frontend_logo(info)
        self.crest_big.set_image(os.path.join(root, shown) if shown else "", "NO CREST")

        roster = [str(p) for p in info.get("players", [])]
        players = self.screen.ds.players
        season = self.screen.season
        n = len(roster)
        self._set_summary("squad", f"{n} players",
                          GREEN if n >= 22 else DANGER_LITE)
        fit = sum(1 for i, pid in enumerate(roster[:15]) if T.fits(players.get(pid), season, i + 1))
        self._set_summary("starters", f"{fit} / 15 in position", GREEN if fit == 15 else WARN)
        starters = roster[:15]
        roles_ok = sum(1 for k in ROLE_KEYS if str((info.get("roles") or {}).get(k, "")) in starters
                       and str((info.get("roles") or {}).get(k, "")))
        self._set_summary("roles", f"{roles_ok} / 7", GREEN if roles_ok == 7 else WARN)
        kits = info.get("kits") or {}
        self._set_summary("kits", ", ".join(kits) if kits else "none", FG_PRIMARY if kits else DANGER_LITE)
        missing = sum(1 for key, _, _ in self.screen.issues if key.startswith(("kits.", "logos.", "ball",
                                                                              "banners", "pads")))
        self._set_summary("assets", "all found" if not missing else f"{missing} problem(s)",
                          GREEN if not missing else WARN)
        seasons = list(self.screen.session.working)
        self.seasons_note.setText("  ·  ".join(
            (f"[{season_label(s)}]" if s == season else season_label(s)) for s in seasons))
        self.file_note.setText(self.screen.file_label())

    def _set_summary(self, key, text, color):
        lbl = self.summary_labels[key]
        lbl.setText(text)
        lbl.setStyleSheet(lbl.styleSheet().split("color:")[0] + f"color: {color};"
                          if False else
                          f"color: {color}; background: transparent; font-family: '{FONT_DISPLAY}';"
                          f" font-size: {T_VALUE}pt; font-weight: 700;")

    def hints(self, focused):
        if isinstance(focused, AssetField):
            return [("A", "browse"), ("X", "type path"), ("Del", "clear")]
        return []


def T_set_path(info, key, value):
    if "." in key:
        group, slot = key.split(".", 1)
        info.setdefault(group, {})[slot] = value
    else:
        info[key] = value


# ═════════════════════════════════════════════════════════════════════════
# Kits
# ═════════════════════════════════════════════════════════════════════════
class KitList(QWidget):
    """Ordered kit names — one focus stop. Up/Down select, Alt+Up/Down (or
    drag) reorders, because the game picks a kit by its position."""

    selected = pyqtSignal(int)
    moved = pyqtSignal(int, int)

    ROW = 38

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumHeight(self.ROW * 4)
        self.names = []
        self.status = {}
        self.index = 0
        self._press = None
        self._drag_row = None

    def set_kits(self, names, index, status):
        self.names = list(names)
        self.status = status
        self.index = max(0, min(index, len(self.names) - 1)) if self.names else 0
        self.setMinimumHeight(self.ROW * max(3, len(self.names)))
        self.update()

    def _row_at(self, y):
        r = int(y // self.ROW)
        return r if 0 <= r < len(self.names) else None

    def mousePressEvent(self, event):
        self.setFocus()
        r = self._row_at(event.y())
        if r is not None:
            self._press = r
            self.index = r
            self.selected.emit(r)
            self.update()

    def mouseMoveEvent(self, event):
        if self._press is None or not (event.buttons() & Qt.LeftButton):
            return
        r = self._row_at(event.y())
        if r is not None and r != self._drag_row:
            self._drag_row = r
            self.update()

    def mouseReleaseEvent(self, event):
        if self._press is not None and self._drag_row is not None and self._drag_row != self._press:
            self.moved.emit(self._press, self._drag_row)
        self._press = None
        self._drag_row = None
        self.update()

    def keyPressEvent(self, event):
        k = event.key()
        if k in (Qt.Key_Up, Qt.Key_Down) and self.names:
            step = -1 if k == Qt.Key_Up else 1
            target = max(0, min(len(self.names) - 1, self.index + step))
            if event.modifiers() & Qt.AltModifier:
                if target != self.index:
                    self.moved.emit(self.index, target)
            elif target != self.index:
                self.index = target
                self.selected.emit(target)
                self.update()
            else:
                super().keyPressEvent(event)   # at an end: let focus leave
                return
            event.accept()
            return
        super().keyPressEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        focused = self.hasFocus()
        p.fillRect(self.rect(), QColor(BG_CARD))
        for i, name in enumerate(self.names):
            r = QRectF(0, i * self.ROW, self.width(), self.ROW - 2)
            on = i == self.index
            if on:
                p.fillRect(r, QColor(BG_HIGHLIGHT))
                p.fillRect(QRectF(0, r.y(), 3, r.height()), QColor(ACCENT if focused else BORDER_EM))
            if self._drag_row == i and self._press is not None and self._press != i:
                p.fillRect(QRectF(0, r.y(), r.width(), 2), QColor(ACCENT))
            p.setFont(tracked_font(FONT_DISPLAY, T_LABEL, QFont.Bold, 0.4))
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(QRectF(12, r.y(), 22, r.height()), Qt.AlignLeft | Qt.AlignVCenter, str(i + 1))
            p.setFont(tracked_font(FONT_DISPLAY, T_VALUE, QFont.Bold, 0.8))
            p.setPen(QColor(ACCENT if on and focused else FG_PRIMARY))
            p.drawText(QRectF(36, r.y(), r.width() - 70, r.height()), Qt.AlignLeft | Qt.AlignVCenter,
                       name.upper())
            sev = self.status.get(name)
            if sev:
                p.setBrush(QColor(SEVERITY_COLOR.get(sev, FG_TERTIARY)))
                p.setPen(Qt.NoPen)
                p.setRenderHint(QPainter.Antialiasing)
                p.drawEllipse(QRectF(r.right() - 20, r.center().y() - 4, 8, 8))
        if not self.names:
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(self.rect(), Qt.AlignCenter, "no kits")
        if focused:
            draw_frame(p, self.rect(), ACCENT)


class KitsTab(TeamTab):
    def __init__(self, screen, index):
        super().__init__(screen, index)
        self.kit_index = 0
        # A variant of the selected kit (a tournament patch…): the same kit
        # with a few files of its own; the fields show it as it resolves and
        # edits store only what differs from the plain kit.
        self.kit_variant = V.DEFAULT
        row = QHBoxLayout()
        row.setSpacing(14)

        # left: list
        left = SectionCard("kits · in game order")
        left.setFixedWidth(250)
        self.kit_list = KitList()
        self.kit_list.selected.connect(self._select)
        self.kit_list.moved.connect(self._move)
        screen.register_field("kits", self.kit_list, index)
        left.add(self.kit_list)
        btns = QGridLayout()
        btns.setSpacing(6)
        self.kit_buttons = {}
        for n, (text, action) in enumerate((("+ ADD", "add"), ("DUPLICATE", "duplicate"),
                                             ("RENAME", "rename"), ("DELETE", "delete"),
                                             ("▲ UP", "up"), ("▼ DOWN", "down"))):
            b = _button(text, "danger" if action == "delete" else "neutral", 32)
            b.clicked.connect(lambda _=False, a=action: self.kit_action(a))
            screen.focus.register(b)
            btns.addWidget(b, n // 2, n % 2)
            self.kit_buttons[action] = b
        left.add_layout(btns)
        left.v.addStretch(1)
        row.addWidget(left)

        # middle: preview
        mid = SectionCard("preview")
        mid.setFixedWidth(330)
        from ui.player_stage import KitStage
        self.stage = KitStage(default_yaw=20.0)
        self.stage.setFixedHeight(360)
        mid.add(self.stage)
        mgrid = FieldGrid(columns=1)
        self.fit = self.register("kits.model3d.fit",
                                 SegmentField("Fit", ["tight", "loose"], allow_blank=True,
                                              blank_label="auto"))
        self.fit.edited.connect(lambda v: self._set_model3d("fit", v))
        mgrid.add(self.fit)
        self.collar = self.register("kits.model3d.collar",
                                    SegmentField("Collar", ["open", "crew", "stand"], allow_blank=True,
                                                 blank_label="auto"))
        self.collar.edited.connect(lambda v: self._set_model3d("collar", v))
        mgrid.add(self.collar)
        mid.add(mgrid)
        mid.v.addStretch(1)
        row.addWidget(mid)

        # right: files
        right = SectionCard("files")
        self.kit_title = right.title_lbl
        self.variant_picker = VariantPicker(
            display=lambda vid: V.kit_variant_label(self.stored_kit(), vid), width=300,
            add_subtitle="this kit with a small difference (a patch, a logo)")
        self.variant_picker.variant_picked.connect(self._pick_variant)
        self.variant_picker.action.connect(self.variant_action)
        screen.register_field("kits.variant", self.variant_picker.choice, index)
        screen.focus.register(self.variant_picker.menu_btn)
        right.add(self.variant_picker)
        fgrid = FieldGrid(columns=1)
        self.front = self.register("kits.frontKitFile",
                                   AssetField("Shirt front", ASSET_SPECS["frontKitFile"]))
        self.back = self.register("kits.backKitFile",
                                  AssetField("Back numbers", ASSET_SPECS["backKitFile"]))
        self.preview = self.register("kits.previewFile",
                                     AssetField("Menu picture", ASSET_SPECS["previewFile"]))
        for f, key in ((self.front, "frontKitFile"), (self.back, "backKitFile"),
                       (self.preview, "previewFile")):
            self._wire_asset(f, key)
            fgrid.add(f)
        right.add(fgrid)
        right.add(Note(ASSET_SPECS["backKitFile"]["note"] + " A kit_back_%.png series is expected."))
        self.back_strip = FrameStrip(22, thumb=(46, 46), max_show=11)
        right.add(self.back_strip)
        ugrid = FieldGrid(columns=1)
        self.color = self.register("kits.color", TextField("Colour"))
        self.color.set_badge("UNUSED")
        self.color.edited.connect(lambda v: self._edit_kit("colour", lambda k: k.__setitem__("color", v)))
        ugrid.add(self.color)
        ugrid.hide()        # the colour is unused by the game: hidden for now
        right.add(ugrid)
        right.v.addStretch(1)
        row.addWidget(right, stretch=1)
        self.body.addLayout(row)

    # ── helpers ──────────────────────────────────────────────────────────
    def kit_names(self):
        return list((self.info().get("kits") or {}).keys())

    def current_kit_name(self):
        names = self.kit_names()
        if not names:
            return None
        self.kit_index = max(0, min(self.kit_index, len(names) - 1))
        return names[self.kit_index]

    def stored_kit(self):
        """The selected kit as stored (plain, with its "variants")."""
        name = self.current_kit_name()
        return (self.info().get("kits") or {}).get(name, {}) if name else {}

    def current_variant(self):
        """The picked kit variant if the selected kit has it, else "" (the
        pick is kept while browsing kits without it)."""
        vid = self.kit_variant
        return vid if vid in V.kit_variant_ids(self.stored_kit()) else V.DEFAULT

    def view_extra(self):
        return {"kit_variant": self.kit_variant}

    def _edit_kit(self, label, fn):
        name = self.current_kit_name()
        if name is None:
            return
        vid = self.current_variant()
        if vid:
            self.edit(f"{name} kit ({vid}) {label}",
                      lambda i: T.edit_kit_variant(i["kits"][name], vid, fn),
                      f"kits.{name}.variants.{vid}")
        else:
            self.edit(f"{name} kit {label}", lambda i: fn(i["kits"][name]), f"kits.{name}")

    def _pick_variant(self, vid):
        self.kit_variant = vid or V.DEFAULT
        self.refresh()

    def variant_action(self, action):
        name = self.current_kit_name()
        if name is None:
            return
        kit = self.stored_kit()
        vid = self.current_variant()
        screen = self.screen

        def kit_edit(label, fn):
            self.edit(f"{name} kit {label}", lambda i: fn(i["kits"][name]), f"kits.{name}")

        if action == "add":
            taken = set(V.kit_variant_ids(kit))
            world_cup = None
            if self.info().get("type") == "international":
                # international kits only get the World Cup patch, named
                # after the tournament held the year before the season
                try:
                    year = int(self.screen.season) - 1
                    world_cup = (f"rwc_{year}", f"RWC {year}")
                except (TypeError, ValueError):
                    pass
            if world_cup:
                if world_cup[0] in taken:
                    screen.shell.footer.set_status(
                        f"{name} kit already has {world_cup[0]}", DANGER_LITE)
                    return
                fields = {}
            else:
                known = [v for v in screen._known_variant_ids() if v not in taken]
                family = ChoiceField("Competition", known, allow_blank=True,
                                     blank_label="(type a new id below)",
                                     display=lambda v: v.replace("_", " "))
                family.set_value(known[0] if known else "")
                other = TextField("New id")
                label = TextField("Label")
                fields = {"family": family, "other": other, "label": label}

            def done(role):
                screen._dialog = None
                if role != "ok":
                    return
                if world_cup:
                    new, new_label = world_cup
                else:
                    new = (other.value() or "").strip().lower() or family.value()
                    new_label = label.value().strip()
                try:
                    T.add_kit_variant({V.KIT_VARIANTS_KEY: dict.fromkeys(taken)}, new)  # validate only
                except ValueError as e:
                    screen.shell.footer.set_status(str(e), DANGER_LITE)
                    return
                self.kit_variant = new
                kit_edit(f"add variant {new}",
                         lambda k: T.add_kit_variant(k, new, new_label))
                screen.shell.footer.set_status(
                    f"{name} kit · {V.kit_variant_label(self.stored_kit(), new)} added — it is "
                    "the plain kit until you give it its own files", GREEN)

            if world_cup:
                intro = (f"The {name} kit with the World Cup patch: id {world_cup[0]}, label "
                         f"\"{world_cup[1]}\". Only the files you change are stored; the rest "
                         "stay the plain kit's.")
            else:
                intro = (f"The {name} kit with a small difference for one competition (a "
                         "tournament patch, a logo), named after the competition's id "
                         "(world_cup, six_nations…). Only the files you change are stored; "
                         "the rest stay the plain kit's.")
            screen.show_dialog(FormDialog(
                screen, "Add kit variant", intro, fields,
                [("CANCEL", "neutral", "cancel"), ("ADD VARIANT", "primary", "ok")], done))
        elif action == "rename" and vid:
            label = TextField("Label")
            label.set_value(V.kit_variant_label(kit, vid))

            def done(role):
                screen._dialog = None
                if role == "ok":
                    kit_edit(f"rename variant {vid}",
                             lambda k: T.set_kit_variant_label(k, vid, label.value().strip()))
            screen.show_dialog(FormDialog(screen, "Rename kit variant", f"Id {vid} stays the same.",
                                          {"label": label},
                                          [("CANCEL", "neutral", "cancel"),
                                           ("RENAME", "primary", "ok")], done))
        elif action == "reset" and vid:
            screen.confirm(f"Reset {V.kit_variant_label(kit, vid)} to the plain {name} kit?",
                           "Its own files are dropped (the image files stay on disk; Ctrl+Z "
                           "to undo until you save).", "RESET",
                           lambda: kit_edit(f"reset variant {vid}",
                                            lambda k: T.clear_kit_variant(k, vid)))
        elif action == "delete" and vid:
            def go():
                self.kit_variant = V.DEFAULT
                kit_edit(f"delete variant {vid}", lambda k: T.delete_kit_variant(k, vid))
            screen.confirm(f"Delete {V.kit_variant_label(kit, vid)} from the {name} kit?",
                           "Competitions asking for it wear the plain kit instead "
                           "(Ctrl+Z to undo until you save).", "DELETE VARIANT", go)

    def _wire_asset(self, field, key):
        field.browse_requested.connect(lambda: browse_assets(
            self.screen, field, self.screen.team_folder(), field.spec, field.value(),
            field.set_picked, title=f"{self.current_kit_name() or ''} kit · {field.label}"))
        field.edited.connect(lambda v: self._edit_kit(field.label.lower(),
                                                      lambda k: k.__setitem__(key, v)))

    def _set_model3d(self, key, value):
        self._edit_kit(key, lambda k: T.set_model3d(k, key, value))

    def _select(self, i):
        self.kit_index = i
        self.refresh()

    def _move(self, a, b):
        self.kit_index = b
        self.edit("kit order", lambda i: T.reorder_kits(i, a, b), "kits")

    def kit_action(self, action):
        names = self.kit_names()
        name = self.current_kit_name()
        if action in ("up", "down") and name is not None:
            target = self.kit_index + (-1 if action == "up" else 1)
            if 0 <= target < len(names):
                self._move(self.kit_index, target)
        elif action == "add":
            self.screen.ask_text("Add kit", "Kit name", T.free_kit_name(self.info()),
                                 lambda v: self._add(v, None), hint="lowercase, e.g. third")
        elif action == "duplicate" and name is not None:
            self.screen.ask_text("Duplicate kit", "New kit name", T.free_kit_name(self.info()),
                                 lambda v: self._add(v, name), hint=f"copy of {name}")
        elif action == "rename" and name is not None:
            self.screen.ask_text("Rename kit", "Kit name", name, lambda v: self._rename(name, v))
        elif action == "delete" and name is not None:
            self.screen.confirm(f"Delete the {name} kit?",
                                "Its file paths are removed from this season (the image files "
                                "stay on disk). Undo with Ctrl+Z.",
                                "DELETE", lambda: self.edit(f"delete {name} kit",
                                                            lambda i: T.delete_kit(i, name), "kits"))

    def _add(self, name, source):
        try:
            info = self.info()
            src = (info.get("kits") or {}).get(source) if source else None
            if name in (info.get("kits") or {}):
                raise ValueError(f"a kit named {name} already exists")
            if not T.KIT_NAME_RE.match(name or ""):
                raise ValueError("use lowercase letters, digits and _ only")
            self.edit(f"add {name} kit", lambda i: T.add_kit(i, name, src), "kits")
            self.kit_index = len(self.kit_names()) - 1
        except ValueError as e:
            self.screen.shell.footer.set_status(str(e), DANGER_LITE)

    def _rename(self, old, new):
        try:
            probe = {"kits": dict(self.info().get("kits") or {})}
            T.rename_kit(probe, old, new)
            self.edit(f"rename {old} kit", lambda i: T.rename_kit(i, old, new), "kits")
        except ValueError as e:
            self.screen.shell.footer.set_status(str(e), DANGER_LITE)

    # ── refresh ──────────────────────────────────────────────────────────
    def refresh(self):
        info = self.info()
        kits = info.get("kits") or {}
        names = list(kits)
        status = {}
        for key, _, sev in self.screen.issues:
            parts = key.split(".")
            if parts[0] == "kits" and len(parts) > 1 and parts[1] in kits:
                status[parts[1]] = worst([status.get(parts[1]), sev])
        self.kit_list.set_kits(names, self.kit_index, status)
        name = self.current_kit_name()
        stored = kits.get(name, {}) if name else {}
        # Another kit without the variant shows plain; the id is kept, so
        # stepping back to a kit that has it shows that variant again.
        ids = V.kit_variant_ids(stored)
        vid = self.current_variant()
        kit = V.resolve_kit(stored, vid)
        over = V.kit_overrides(stored, vid)
        has = name is not None
        for w in (self.front, self.back, self.preview, self.color, self.fit, self.collar,
                  self.variant_picker):
            w.setEnabled(has)
        self.variant_picker.set_variants(ids, vid)
        for action, b in self.kit_buttons.items():
            b.setEnabled(has or action == "add")
        title = f"{name} kit" + (f" · {V.kit_variant_label(stored, vid)}" if vid else "")
        self.kit_title.setText(f"{title} · files".upper() if has else "FILES")
        root = self.screen.team_folder()
        prefix = f"kits.{name}.variants.{vid}" if vid else f"kits.{name}"
        for w, key in ((self.front, "frontKitFile"), (self.back, "backKitFile"),
                       (self.preview, "previewFile")):
            w.key = f"{prefix}.{key}" if has else f"kits.{key}"
            w.set_root(root)
            w.set_value(kit.get(key, ""))
        # on a variant, mark what it changes (the rest is the plain kit's)
        for w, key in ((self.front, "frontKitFile"), (self.back, "backKitFile"),
                       (self.preview, "previewFile"), (self.fit, "model3d"),
                       (self.collar, "model3d")):
            w.set_badge(("OWN" if key in over else "PLAIN KIT") if vid else "")
        self.color.set_value(kit.get("color", ""))
        self.color.key = f"{prefix}.color"
        model = kit.get("model3d") or {}
        self.fit.set_value(model.get("fit", ""))
        self.collar.set_value(model.get("collar", ""))
        self.back_strip.set_pattern(root, kit.get("backKitFile", ""))
        self._refresh_stage(root, kit)

    def _refresh_stage(self, root, kit):
        preview = kit.get("previewFile", "")
        pix = load_pixmap(os.path.join(root, preview), 512) if preview else None
        front = os.path.join(root, kit["frontKitFile"]) if kit.get("frontKitFile") else ""
        back = kit.get("backKitFile", "")
        back_path = os.path.join(root, back.replace("%", "1", 1)) if back else ""
        key = (front, back_path, preview, str(kit.get("model3d")))
        if getattr(self, "_stage_key", None) == key:
            return
        self._stage_key = key
        try:
            self.stage.update_kit(pix if pix is not None and not pix.isNull() else None,
                                  front, back_path, kit.get("model3d"))
        except Exception as e:     # preview must never break editing
            log.warning(f"kit preview failed: {e}")

    def hints(self, focused):
        if focused is self.kit_list:
            return [("↕", "select kit"), ("Alt ↕", "reorder"), ("drag", "reorder")]
        if isinstance(focused, AssetField):
            return [("A", "browse"), ("X", "type path"), ("Del", "clear")]
        return []


# ═════════════════════════════════════════════════════════════════════════
# Shirt names
# ═════════════════════════════════════════════════════════════════════════
TEXT_MODE_LABELS = {"surname": "surname", "initial": "j. surname", "display": "in-game",
                    "full": "full name"}
CASE_LABELS = {"upper": "capitals", "asis": "as typed"}
PLACEMENT_LABELS = {"auto": "auto", "above": "above no.", "below": "below no.", "custom": "custom"}


class ShirtNamesTab(TeamTab):
    """The player's name on the back of the shirt (shared/shirt_names.py).
    The lettering is the season's, the colours each kit's own. The back is
    shown as the game gets it — flat, with the name area to drag, and on the
    3D player seen from behind."""

    def __init__(self, screen, index):
        super().__init__(screen, index)
        self.kit_name = None          # kit shown (and whose colours are edited)
        self.kit_variant = V.DEFAULT  # its variant, if it has the picked one
        self.preview_shirt = 10       # whose back is shown
        self.try_name = ""            # a name typed to test the lettering (not stored)
        self._printer = None
        self._render_timer = QTimer()
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(15)
        self._render_timer.timeout.connect(self._render)
        self._stage_timer = QTimer()
        self._stage_timer.setSingleShot(True)
        self._stage_timer.setInterval(280)
        self._stage_timer.timeout.connect(self._refresh_stage)
        self._live_area = None        # area while it is dragged (not stored yet)
        self._last_image = None
        row = QHBoxLayout()
        row.setSpacing(14)

        # left: the flat back, name area to drag
        left = SectionCard("back of the shirt")
        left.setMinimumWidth(440)
        self.canvas = NameAreaCanvas()
        self.canvas.setMinimumSize(400, 400)
        self.canvas.area_changing.connect(self._area_changing)
        self.canvas.area_changed.connect(self._area_changed)
        screen.focus.register(self.canvas)
        left.add(self.canvas, stretch=1)
        pgrid = FieldGrid(columns=1)
        self.kit_pick = ChoiceField("Kit", allow_blank=False, display=lambda v: str(v).upper())
        self.kit_pick.popup_title = "kit to preview"
        self.kit_pick.edited.connect(self._pick_kit)
        pgrid.add(self.kit_pick)
        self.variant_pick = ChoiceField("Kit variant", allow_blank=True, blank_label="Default",
                                        display=lambda v: V.kit_variant_label(self._stored_kit(), v))
        self.variant_pick.popup_title = "kit variant"
        self.variant_pick.edited.connect(self._pick_kit_variant)
        pgrid.add(self.variant_pick)
        self.shirt_pick = ChoiceField("Preview shirt", [str(n) for n in range(1, SQUAD_SIZE + 1)],
                                      allow_blank=False, display=self._shirt_label)
        self.shirt_pick.popup_title = "whose back"
        self.shirt_pick.edited.connect(self._pick_shirt)
        pgrid.add(self.shirt_pick)
        self.try_field = TextField("Try a name", placeholder="type to test a long name")
        self.try_field.edited.connect(self._try)
        pgrid.add(self.try_field)
        for w in (self.kit_pick, self.variant_pick, self.shirt_pick, self.try_field):
            screen.focus.register(w)
        left.add(pgrid)
        self.left_note = Note("", color=FG_TERTIARY)
        left.add(self.left_note)
        row.addWidget(left, stretch=5)

        # middle: the 3D player from behind
        mid = SectionCard("3d preview")
        mid.setFixedWidth(300)
        from ui.player_stage import KitStage
        self.stage = KitStage(default_yaw=180.0)
        self.stage.setFixedHeight(470)
        mid.add(self.stage)
        mid.add(Note("Drag to turn the player.", color=FG_TERTIARY))
        mid.v.addStretch(1)
        row.addWidget(mid)

        # right: settings
        right = QVBoxLayout()
        right.setSpacing(12)
        lettering = SectionCard("lettering · this season")
        lgrid = FieldGrid(columns=1)
        self.enabled = self.register("shirtNames.enabled",
                                     SegmentField("Shirt names", ["off", "on"]))
        self.enabled.edited.connect(lambda v: self._set("enabled", True if v == "on" else None,
                                                        "shirt names " + v))
        lgrid.add(self.enabled)
        self.text_mode = self.register("shirtNames.text", SegmentField(
            "Text", list(SN.TEXT_MODES), display=lambda v: TEXT_MODE_LABELS.get(v, v)))
        self.text_mode.edited.connect(lambda v: self._set("text", v, "name text"))
        lgrid.add(self.text_mode)
        self.case = self.register("shirtNames.case", SegmentField(
            "Case", list(SN.CASES), display=lambda v: CASE_LABELS.get(v, v)))
        self.case.edited.connect(lambda v: self._set("case", v, "name case"))
        lgrid.add(self.case)
        self.font = self.register("shirtNames.font", ChoiceField(
            "Font", allow_blank=False, display=self._font_label))
        self.font.popup_title = "font"
        self.font.subtitle_for = lambda v: ("your font file in the team folder" if SN.is_font_file(v)
                                            else "bundled")
        self.font.edited.connect(lambda v: self._set("font", v, "name font"))
        lgrid.add(self.font)
        self.size = self.register("shirtNames.size", NumberField("Letter height", 8, 120))
        self.size.edited.connect(lambda v: self._set_number("size", v, "name size"))
        lgrid.add(self.size)
        self.spacing = self.register("shirtNames.spacing", NumberField("Letter spacing %", -20, 60))
        self.spacing.edited.connect(lambda v: self._set_number("spacing", v, "letter spacing"))
        lgrid.add(self.spacing)
        self.arch = self.register("shirtNames.arch", NumberField("Arch %", -60, 60))
        self.arch.edited.connect(lambda v: self._set_number("arch", v, "name arch"))
        lgrid.add(self.arch)
        self.placement = self.register("shirtNames.placement", SegmentField(
            "Placement", list(SN.PLACEMENTS), display=lambda v: PLACEMENT_LABELS.get(v, v)))
        self.placement.edited.connect(self._set_placement)
        lgrid.add(self.placement)
        self.gap = self.register("shirtNames.gap", NumberField("Gap to number", -40, 120))
        self.gap.edited.connect(lambda v: self._set_number("gap", v, "name gap"))
        lgrid.add(self.gap)
        lettering.add(lgrid)
        brow = QHBoxLayout()
        brow.setSpacing(8)
        self.copy_btn = _button("COPY TO OTHER SEASONS")
        self.copy_btn.clicked.connect(self._copy_to_seasons)
        screen.focus.register(self.copy_btn)
        brow.addWidget(self.copy_btn)
        brow.addStretch(1)
        lettering.add_layout(brow)
        right.addWidget(lettering)

        colours = SectionCard("colours · kit")
        self.colours_card = colours
        cgrid = FieldGrid(columns=1)
        self.color = self.register("shirtName.color", ColorField("Text", blank_label="auto"))
        self.color.edited.connect(lambda v: self._set_kit("color", v, "name colour"))
        cgrid.add(self.color)
        self.outline = self.register("shirtName.outline", ColorField("Outline", blank_label="none"))
        self.outline.edited.connect(lambda v: self._set_kit("outline", v, "name outline"))
        cgrid.add(self.outline)
        self.outline_w = self.register("shirtName.outlineWidth", NumberField("Outline width", 0, 12))
        self.outline_w.edited.connect(lambda v: self._set_kit(
            "outlineWidth", int(v) if str(v).lstrip("-").isdigit() and int(v) else None,
            "name outline width"))
        cgrid.add(self.outline_w)
        colours.add(cgrid)
        colours.add(Note("AUTO takes the colour of the kit's own numbers.", color=FG_TERTIARY))
        right.addWidget(colours)
        self.help = Note(
            "Each player's name is printed on their own back-number texture when the match "
            "starts: shirt N gets the name of player N of the squad. A player's \"shirt name\" "
            "(player editor) replaces the generated text. Your own .ttf/.otf files in the team "
            "folder appear in the font list.", color=FG_TERTIARY)
        right.addWidget(self.help)
        right.addStretch(1)
        row.addLayout(right, stretch=4)
        self.body.addLayout(row)

    # ── helpers ──────────────────────────────────────────────────────────
    def _season_block(self):
        return self.info().get("shirtNames") or {}

    def _kits(self):
        return self.info().get("kits") or {}

    def _current_kit(self):
        kits = self._kits()
        if self.kit_name not in kits:
            kits_tab = self.screen.tabs[TAB_KITS] if hasattr(self.screen, "tabs") else None
            name = kits_tab.current_kit_name() if kits_tab else None
            self.kit_name = name if name in kits else next(iter(kits), None)
        return self.kit_name

    def _stored_kit(self):
        name = self._current_kit()
        return self._kits().get(name) or {} if name else {}

    def _current_variant(self):
        """The picked kit variant if the shown kit has it, else "" (the plain kit)."""
        vid = self.kit_variant
        return vid if vid in V.kit_variant_ids(self._stored_kit()) else V.DEFAULT

    def _kit_dict(self):
        name = self._current_kit()
        return V.resolve_kit(self._kits().get(name) or {}, self._current_variant()) if name else {}

    def _style(self):
        return SN.season_style_for(self.info(), self._kit_dict())

    def _player(self, shirt):
        roster = [str(p) for p in self.info().get("players", [])]
        if 1 <= shirt <= len(roster):
            return self.screen.ds.players.get(roster[shirt - 1])
        return None

    def _shirt_label(self, value):
        try:
            n = int(value)
        except (TypeError, ValueError):
            return str(value)
        style = self._style()
        text = SN.shirt_text(self._player(n), style["text"], style["case"])
        return f"{n} · {text}" if text else f"{n} · —"

    def _font_label(self, value):
        if SN.is_font_file(value):
            return f"{os.path.basename(value)}  (team folder)"
        return value

    def _set(self, key, value, label):
        self.edit(label, lambda i: T.set_shirt_names(i, key, value), f"shirtNames.{key}")

    def _set_number(self, key, value, label):
        try:
            n = int(value)
        except (TypeError, ValueError):
            n = None
        self._set(key, n, label)

    def _set_kit(self, key, value, label):
        name = self._current_kit()
        if name is None:
            return
        vid = self._current_variant()
        if vid:
            self.edit(f"{name} kit ({vid}) {label}",
                      lambda i: T.edit_kit_variant(
                          i["kits"][name], vid, lambda k: T.set_kit_shirt_name(k, key, value)),
                      f"shirtName.{key}")
            return
        self.edit(f"{name} kit {label}",
                  lambda i: T.set_kit_shirt_name(i["kits"][name], key, value),
                  f"shirtName.{key}")

    def _set_placement(self, value):
        if value == "custom":
            area = self._printer.area if self._printer else None
            self.edit("name placement", lambda i: T.set_shirt_name_area(i, area),
                      "shirtNames.placement")
        else:
            self._set("placement", value, "name placement")

    def _pick_kit(self, name):
        self.kit_name = name
        self.refresh()

    def _pick_kit_variant(self, vid):
        self.kit_variant = vid or V.DEFAULT
        self.refresh()

    def _pick_shirt(self, value):
        try:
            self.preview_shirt = int(value)
        except (TypeError, ValueError):
            return
        self._schedule()

    def _try(self, text):
        self.try_name = (text or "").strip()
        self._schedule()

    def _area_changing(self, area):
        self._live_area = area
        self._schedule(stage=False)

    def _area_changed(self, area):
        self._live_area = None
        self.edit("name area", lambda i: T.set_shirt_name_area(i, area), "shirtNames.area")

    def _copy_to_seasons(self):
        season = self.screen.season
        others = [s for s in self.screen.session.working if s != season]
        if not others:
            self.screen.shell.footer.set_status("this team has only one season", DANGER_LITE)
            return

        def go():
            self.screen.edit("copy shirt names to every season",
                             lambda w: T.copy_shirt_names(w, season),
                             view_hint={"season": season, "tab": self.index})
            self.screen.shell.footer.set_status(
                f"Shirt names of {season_label(season)} copied to {len(others)} other season(s)",
                GREEN)
        self.screen.confirm(f"Copy these shirt names to the {len(others)} other season(s)?",
                            "The lettering and each kit's name colours (matched by kit name) "
                            "replace theirs. Ctrl+Z to undo until you save.", "COPY", go)

    # ── refresh / render ─────────────────────────────────────────────────
    def refresh(self):
        kits = self._kits()
        name = self._current_kit()
        style = self._style()
        block = self._season_block()
        on = style["enabled"]
        vid = self._current_variant()
        self.kit_pick.set_options(list(kits))
        self.kit_pick.set_value(name or "")
        ids = V.kit_variant_ids(self._stored_kit())
        self.variant_pick.set_options(ids)
        self.variant_pick.set_value(self._current_variant())
        self.variant_pick.setEnabled(bool(ids))
        self.shirt_pick.set_value(str(self.preview_shirt))
        self.enabled.set_value("on" if on else "off")
        self.text_mode.set_value(style["text"])
        self.case.set_value(style["case"])
        root = self.screen.team_folder()
        fonts = list(SN.BUILTIN_FONTS) + SN.team_font_files(root)
        if block.get("font") and block["font"] not in fonts:
            fonts.append(block["font"])         # shown off-list until fixed
        self.font.set_options(fonts)
        self.font.set_value(block.get("font") or SN.DEFAULT_FONT)
        for w, key in ((self.size, "size"), (self.spacing, "spacing"), (self.arch, "arch"),
                       (self.gap, "gap")):
            w.set_value(str(int(style[key])))
            w.set_hint("")
        self.placement.set_value(style["placement"])
        kit_block = self._kit_dict().get("shirtName") or {}
        self.color.set_value(kit_block.get("color", ""))
        self.outline.set_value(kit_block.get("outline", ""))
        self.outline_w.set_value(str(int(style["outlineWidth"])) if style["outlineWidth"] else "")
        self.outline_w.set_hint("none")
        self.colours_card.set_title(f"colours · {name} kit" + (f" · {V.kit_variant_label(self._stored_kit(), vid)}"
                                      if vid else "") if name else "colours")
        for w in (self.text_mode, self.case, self.font, self.size, self.spacing, self.arch,
                  self.placement, self.color, self.outline, self.outline_w):
            w.setEnabled(on)
        self.gap.setEnabled(on and style["placement"] != "custom")
        self.copy_btn.setEnabled(bool(block))
        self.canvas.set_editable(on)
        self._schedule()

    def _schedule(self, stage=True):
        self._render_timer.start()
        if stage:
            self._stage_timer.start()

    def _back_pattern(self):
        back = self._kit_dict().get("backKitFile", "")
        root = self.screen.team_folder()
        return os.path.join(root, back) if back else ""

    def _render(self):
        """Letter the previewed shirt's back and show it."""
        style = self._style()
        pattern = self._back_pattern()
        self._printer = None
        self._last_image = None
        if not pattern or "%" not in pattern:
            self.canvas.set_image(None)
            self.canvas.set_placeholder(
                "SHIRT NAMES NEED THE KIT'S BACK NUMBERS AS A PNG SERIES (KIT_BACK_%.PNG)"
                if pattern else "THIS KIT HAS NO BACK NUMBERS")
            self.left_note.setText("")
            return
        if self._live_area:
            style = dict(style, placement="custom", area=self._live_area)
        font_path, variation, found = SN.resolve_font(style["font"], self.screen.team_folder())
        try:
            printer = SN.BackPrinter(style, font_path, SN.expand_back_paths(pattern), variation)
            text = (self.try_name or SN.shirt_text(self._player(self.preview_shirt), style["text"],
                                                   style["case"])) if style["enabled"] else ""
            if self.try_name and style["case"] == "upper":
                text = text.upper()
            image = printer.render(self.preview_shirt - 1, text)
        except Exception as e:         # a preview must never break editing
            log.warning(f"shirt name preview failed: {e}")
            self.canvas.set_image(None)
            self.canvas.set_placeholder("PREVIEW FAILED — SEE THE LOG")
            return
        self._printer = printer
        if image is None:
            self.canvas.set_image(None)
            self.canvas.set_placeholder(f"BACK NUMBER {self.preview_shirt} IS MISSING")
            return
        self._last_image = image
        self.canvas.set_image(_pil_to_qimage(image))
        self.canvas.set_area(printer.area if style["enabled"] else None)
        self.canvas.set_number_box(printer.analysis.get("box"))
        self.canvas.set_caption("NAME AREA" + {"auto": " · AUTO", "above": " · ABOVE NUMBER",
                                               "below": " · BELOW NUMBER"}.get(style["placement"], ""))
        notes = []
        if not found:
            notes.append(f"Font \"{style['font']}\" not found: {SN.DEFAULT_FONT} is used.")
        if style["enabled"] and SN.area_overlap(printer.area, printer.analysis) > 0.25:
            notes.append("The name runs over a logo here: drag the box to a free spot, or "
                         "try another placement.")
        if style["enabled"]:
            notes.append("Drag the box to move the name, its handles to resize it "
                         "(arrows / Alt+arrows with the box focused).")
        else:
            notes.append("Turn shirt names on to print each player's name on their back.")
        self.left_note.setText(" ".join(notes))

    def _refresh_stage(self):
        if self._render_timer.isActive():
            self._render()
            self._render_timer.stop()
        kit = self._kit_dict()
        root = self.screen.team_folder()
        front = os.path.join(root, kit["frontKitFile"]) if kit.get("frontKitFile") else ""
        numbers = ""
        if self._last_image is not None and self._printer is not None:
            folder = os.path.join(config.temp_directory, "shirt_names")
            try:
                os.makedirs(folder, exist_ok=True)
                numbers = os.path.join(folder, self._printer.cache_name(
                    self.preview_shirt - 1, repr((self.try_name, self._style()))))
                if not os.path.isfile(numbers):
                    _prune(folder)
                    self._last_image.save(numbers)
            except OSError as e:
                log.warning(f"shirt name preview: {e}")
                numbers = ""
        else:
            pattern = self._back_pattern()
            numbers = pattern.replace("%", str(self.preview_shirt), 1) if pattern else ""
        preview = kit.get("previewFile", "")
        pix = load_pixmap(os.path.join(root, preview), 512) if preview else None
        try:
            self.stage.update_kit(pix if pix is not None and not pix.isNull() else None,
                                  front, numbers, kit.get("model3d"))
        except Exception as e:     # preview must never break editing
            log.warning(f"shirt name 3D preview failed: {e}")

    def hints(self, focused):
        if focused is self.canvas:
            return [("drag", "move / resize"), ("←→↑↓", "move"), ("Alt ←→↑↓", "resize"),
                    ("Shift", "bigger steps")]
        return []


def _pil_to_qimage(image):
    from PyQt5.QtGui import QImage
    rgba = image.convert("RGBA")
    data = rgba.tobytes("raw", "RGBA")
    q = QImage(data, rgba.width, rgba.height, rgba.width * 4, QImage.Format_RGBA8888)
    return q.copy()        # own the pixels: `data` goes away with this frame


def _prune(folder, keep=40):
    """Drop the oldest preview images, so the folder never grows past `keep`."""
    try:
        files = sorted((os.path.join(folder, f) for f in os.listdir(folder)), key=os.path.getmtime)
        for path in files[:-keep]:
            os.remove(path)
    except OSError:
        pass


# ═════════════════════════════════════════════════════════════════════════
# Squad & roles
# ═════════════════════════════════════════════════════════════════════════
class SquadTab(TeamTab):
    SQUAD_SCOPED = True

    def __init__(self, screen, index):
        super().__init__(screen, index)
        self.selected_shirt = 1
        self.carrying = None
        row = QHBoxLayout()
        row.setSpacing(14)

        sheet = SectionCard("starting xv", stripe=HOME_TINT)
        sheet.v.setSpacing(2)
        sheet.v.setContentsMargins(14, 10, 14, 10)
        self.sheet_card = sheet
        self.slots = {}
        for shirts in MATCH_SHEET_ROWS:
            hl = QHBoxLayout()
            hl.setSpacing(8)
            hl.addStretch(1)
            for n in shirts:
                slot = SlotAvatar(n, HOME_TINT, size="compact")
                self._wire_slot(slot)
                hl.addWidget(slot)
            hl.addStretch(1)
            sheet.add_layout(hl)
        sheet.add(self._rule())
        sheet.add(eyebrow_label("replacements", color=FG_SECONDARY, size=T_SMALL))
        bench = QGridLayout()
        bench.setHorizontalSpacing(6)
        bench.setVerticalSpacing(4)
        for i, n in enumerate(SUBSTITUTES):
            chip = SubChip(n, HOME_TINT, size="compact")
            self._wire_slot(chip)
            bench.addWidget(chip, i // 4, i % 4)
        sheet.add_layout(bench)
        self.extras = Note("", color=FG_TERTIARY)
        sheet.add(self.extras)
        sheet_col = QVBoxLayout()
        sheet_col.setSpacing(14)
        sheet_col.addWidget(sheet)

        # Extra players (past the 22): a squad pool beyond the 22 in a card
        # of its own, one chip each (no number, a × to remove it). Chips are
        # made as the roster grows and hidden when it shrinks.
        self.extra_add_btn = _button("+ ADD", h=28)
        self.extra_add_btn.clicked.connect(lambda: self.open_picker(len(self.roster()) + 1))
        screen.focus.register(self.extra_add_btn)
        extras_card = SectionCard("extra players", right=self.extra_add_btn)
        extras_card.v.setContentsMargins(14, 10, 14, 12)
        self.extras_card = extras_card
        self.extras_grid = QGridLayout()
        self.extras_grid.setHorizontalSpacing(6)
        self.extras_grid.setVerticalSpacing(4)
        extras_card.add_layout(self.extras_grid)
        self.extras_empty = Note("No extra players: + ADD puts one in the squad pool.")
        extras_card.add(self.extras_empty)
        self.extra_chips = []
        sheet_col.addWidget(extras_card)
        sheet_col.addStretch(1)
        row.addLayout(sheet_col, stretch=1)
        self._hovered = None

        side = QVBoxLayout()
        side.setSpacing(10)
        self.side_col = side        # the team editor puts the squad variant picker on top
        player_card = SectionCard("selected player")
        player_card.setFixedWidth(390)
        player_card.v.setSpacing(6)
        self.sel_title = player_card.title_lbl
        self.sel_name = display_label("—", T_TITLE, QFont.Bold, track=0.4, upper=False)
        player_card.add(self.sel_name)
        self.sel_meta = Note("", color=FG_SECONDARY, size=T_LABEL)
        player_card.add(self.sel_meta)
        player_card.v.addStretch(1)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.edit_player_btn = _button("EDIT PLAYER", h=32)
        self.edit_player_btn.clicked.connect(self._edit_player)
        screen.focus.register(self.edit_player_btn)
        prow.addWidget(self.edit_player_btn)
        prow.addStretch(1)
        player_card.add_layout(prow)
        # fixed: the name and the wrapped details must not resize the card
        # (and shift everything under it) as the hovered player changes
        player_card.setFixedHeight(190)
        self.sel_name.setMinimumWidth(1)
        side.addWidget(player_card)

        tactics = SectionCard("roles & set plays")
        tactics.setFixedWidth(390)
        tactics.v.setSpacing(4)
        self.tactics_tabs = TabStrip(["Roles", "Set plays"])
        screen.focus.register(self.tactics_tabs)
        tactics.add(self.tactics_tabs)
        self.tactics_stack = _transparent(QStackedWidget(), "tacticsStack")
        roles_page = _transparent(QWidget(), "rolesPage")
        rg = FieldGrid(columns=1, v_spacing=2)
        QVBoxLayout(roles_page).addWidget(rg)
        roles_page.layout().setContentsMargins(0, 8, 0, 0)
        self.role_fields = {}
        for key in ROLE_KEYS:
            f = self.register(f"roles.{key}", ChoiceField(ROLE_LABELS[key], allow_blank=True,
                                                          blank_label="— unset"))
            f.popup_title = ROLE_LABELS[key]
            f.off_list_badge = False
            f.setFixedHeight(34)
            f.edited.connect(lambda v, k=key: self.edit(
                ROLE_LABELS[k].lower(), lambda i: i.setdefault("roles", {}).__setitem__(k, v),
                f"roles.{k}"))
            rg.add(f)
            self.role_fields[key] = f
        self.tactics_stack.addWidget(roles_page)

        plays_page = _transparent(QWidget(), "playsPage")
        pv = QVBoxLayout(plays_page)
        pv.setContentsMargins(0, 8, 0, 0)
        pg = FieldGrid(columns=1, v_spacing=4)
        self.play_fields = {}
        for key, arrow in (("up", "▲ Up"), ("left", "◀ Left"), ("right", "▶ Right"), ("down", "▼ Down")):
            f = self.register(f"setPlays.{key}", ChoiceField(arrow, SET_PLAYS, allow_blank=True,
                                                             blank_label=f"default · {SET_PLAY_DEFAULTS[key].replace('_', ' ')}"))
            f.popup_title = f"set play · {key}"
            f.setFixedHeight(34)
            f.edited.connect(lambda v, k=key: self.edit(
                f"set play {k}", lambda i: i.setdefault("setPlays", {}).__setitem__(k, v),
                f"setPlays.{k}"))
            pg.add(f)
            self.play_fields[key] = f
        pv.addWidget(pg)
        pv.addWidget(Note("Set plays are called in a match with the d-pad direction shown. "
                          "Blank uses the game's default play."))
        self.tactics_stack.addWidget(plays_page)
        self.tactics_tabs.changed.connect(self.tactics_stack.setCurrentIndex)
        tactics.add(self.tactics_stack)
        side.addWidget(tactics)
        side.addStretch(1)
        row.addLayout(side)
        self.body.addLayout(row)

        self.picker = PlayerPickerPopup(screen, width=380, height=460, own_keys=True)
        self.picker.picked.connect(self._on_pick)
        self._picker_shirt = None

    # ── data ─────────────────────────────────────────────────────────────
    def roster(self):
        return [str(p) for p in self.info().get("players", [])]

    def player(self, pid):
        return self.screen.ds.players.get(str(pid)) if pid else None

    def stats(self, pid):
        return T.season_stats(self.player(pid), self.screen.season)

    def _wire_slot(self, slot):
        slot.enable_dnd(True)
        slot.activated.connect(self._on_slot_activated)
        slot.hovered.connect(self._on_slot_hovered)
        slot.unhovered.connect(self._on_slot_unhovered)
        slot.dropped.connect(self._on_drop)
        slot.double_clicked.connect(lambda n: self._edit_player(n))
        self.slots[slot.number] = slot
        self.register(f"players.{slot.number - 1}", slot)

    @staticmethod
    def _rule():
        rule = QWidget()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {BORDER};")
        return rule

    def _show_extras(self, count, shown):
        """`count` extra chips; the card itself only once the 22 are filled."""
        while len(self.extra_chips) < count:
            i = len(self.extra_chips)
            chip = SubChip(SQUAD_SIZE + 1 + i, HOME_TINT, size="compact", show_number=False)
            chip.removable = True
            chip.remove_requested.connect(self._remove)
            self._wire_slot(chip)
            self.extras_grid.addWidget(chip, i // 4, i % 4)
            self.extra_chips.append(chip)
        for i, chip in enumerate(self.extra_chips):
            chip.setVisible(i < count)
        self.extras_empty.setVisible(count == 0)
        self.extras_card.setVisible(shown)

    def _on_slot_hovered(self, number):
        """The player under the mouse fills the info card; leaving him puts
        the selected one back. Not while the picker is open."""
        if self.picker.isVisible():
            return
        self._hovered = number
        self._refresh_selection()

    def _on_slot_unhovered(self, number):
        if self._hovered == number:
            self._hovered = None
            self._refresh_selection()

    def on_focus(self, widget):
        if isinstance(widget, (SlotAvatar, SubChip)) and widget.number != self.selected_shirt:
            self.selected_shirt = widget.number
            self._refresh_selection()

    # ── interaction ──────────────────────────────────────────────────────
    def _on_slot_activated(self, number):
        self.selected_shirt = number
        if self.carrying is not None:
            src = self.carrying
            self.set_carrying(None)
            if src != number:
                self._swap(src, number)
            return
        self._refresh_selection()
        self.open_picker(number)

    def set_carrying(self, number):
        if self.carrying is not None and self.carrying in self.slots:
            self.slots[self.carrying].set_carrying(False)
        self.carrying = number
        if number is not None and number in self.slots:
            self.slots[number].set_carrying(True)
        self.screen._update_hints()

    def toggle_carry(self, number):
        if self.carrying is None:
            if number <= len(self.roster()):
                self.set_carrying(number)
        else:
            src = self.carrying
            self.set_carrying(None)
            if src != number:
                self._swap(src, number)

    def _on_drop(self, src, dst):
        self._swap(src, dst)

    def _swap(self, a, b):
        roster = self.roster()
        if a - 1 >= len(roster):
            return
        self.edit(f"swap players {a} and {b}", lambda i: T.swap(i, a - 1, b - 1), f"players.{b - 1}")
        self.selected_shirt = min(b, len(roster))

    def open_picker(self, number):
        roster = self.roster()
        index = number - 1
        if index > len(roster):
            index = len(roster)
            number = index + 1
        anchor = self.slots.get(number) or self.extra_add_btn
        players = self.screen.ds.players
        season = self.screen.season
        current = roster[index] if index < len(roster) else None
        in_squad = {pid: i + 1 for i, pid in enumerate(roster)}

        def fits(pid):
            return number > STARTING_XV or T.fits(players.get(pid), season, number)

        def rank(pid):
            if pid == current:
                return (0, "")
            return (1 if pid in in_squad else 2, 0 if fits(pid) else 1, last_name(players.get(pid)))

        # SUGGESTED / ALL: this team's squad; SEARCH: every player in the data.
        pool = [p for p in dict.fromkeys(roster) if p in players or p == current]
        pool.sort(key=rank)
        everyone = sorted((p for p in players if p not in in_squad),
                          key=lambda p: last_name(players.get(p)))

        def entry(pid):
            return (pid, (players.get(pid) or {}).get("display_name") or pid, fits(pid))
        if current is None and index >= SQUAD_SIZE:
            # a new extra player: only the search, only players not in the squad
            entries, search = [], [entry(pid) for pid in everyone]
        else:
            entries = [entry(pid) for pid in pool]
            search = [entry(pid) for pid in pool + everyone]
        taken = {pid: s for pid, s in in_squad.items() if pid != current}
        tags = {pid: ("NEW", FG_TERTIARY) for pid in everyone}
        def subtitle(pid):
            s = self.stats(pid)
            pos = POSITION_SHORT.get(s.get("position1", ""), s.get("position1", ""))
            ovr = position_overall(s)
            return f"{pos}  {ovr if ovr is not None else ''}"
        # Callables: the picker lists every player in the data, and only the
        # rows actually scrolled into view need their rating worked out.
        subtitles = {pid: (lambda p=pid: subtitle(p)) for pid in pool + everyone}
        title = f"PLAYER {number}"
        if number <= STARTING_XV:
            from app.game_data import SHIRT_POSITIONS
            title += " · " + POSITION_NAMES.get(SHIRT_POSITIONS[number], "").upper()
        elif number <= SQUAD_SIZE:
            title += " · REPLACEMENT"
        elif index < len(roster):
            title = "EXTRA PLAYER"
        else:
            title = "ADD TO SQUAD"
        self._picker_shirt = number
        self.picker.open_for(title, entries, current, taken, anchor, self.screen, tags=tags,
                             subtitles=subtitles, search=search,
                             mode=SEARCH if current is None else FITS)

    def _on_pick(self, pid):
        number = self._picker_shirt
        if number is None or pid is None:
            return
        roster = self.roster()
        if number - 1 < len(roster) and roster[number - 1] == str(pid):
            return
        name = (self.player(pid) or {}).get("display_name", pid)
        self.edit(f"put {name} as player {number}", lambda i: T.place(i, number - 1, pid),
                  f"players.{number - 1}")
        self.selected_shirt = min(number, len(self.roster()) + 1)
        QTimer.singleShot(0, lambda: self.slots.get(self.selected_shirt, self.extra_add_btn).setFocus())

    def _remove(self, number=None):
        roster = self.roster()
        n = number or self.selected_shirt
        if n - 1 >= len(roster):
            return
        name = (self.player(roster[n - 1]) or {}).get("display_name", roster[n - 1])
        self.edit(f"remove {name}", lambda i: T.remove(i, n - 1), f"players.{n - 1}")
        self.screen.shell.footer.set_status(
            f"Removed {name} — later players moved up one (Ctrl+Z to undo)", FG_SECONDARY)

    def _auto_sort(self):
        moved = {}

        def fn(i):
            moved["n"] = T.auto_sort(i, self.screen.ds.players, self.screen.season)
        self.edit("auto-sort squad", fn, "players")
        self.screen.shell.footer.set_status(
            f"Auto-sort moved {moved.get('n', 0)} player(s) — Ctrl+Z to undo", FG_SECONDARY)

    def _reverse(self):
        self.edit("reverse squad order", T.reverse, "players")

    def _edit_player(self, number=None):
        number = number or self.selected_shirt
        roster = self.roster()
        if number - 1 < len(roster):
            self.screen.open_player(roster[number - 1])

    # ── refresh ──────────────────────────────────────────────────────────
    def refresh(self):
        info = self.info()
        roster = self.roster()
        players = self.screen.ds.players
        season = self.screen.season
        roles = info.get("roles") or {}
        badges = {}
        for key in ROLE_KEYS:
            pid = str(roles.get(key, "") or "")
            if pid:
                badges.setdefault(pid, []).append(ROLE_SHORT[key])
        issue_by_index = {}
        for key, _, sev in self.screen.issues:
            if key.startswith("players."):
                idx = int(key.split(".")[1])
                issue_by_index[idx] = worst([issue_by_index.get(idx), sev])
        self._show_extras(max(0, len(roster) - SQUAD_SIZE), len(roster) >= SQUAD_SIZE)
        seen = set()
        for n, slot in self.slots.items():
            pid = roster[n - 1] if n - 1 < len(roster) else None
            player = players.get(pid) if pid else None
            flat = dict(player or {})
            flat.update(T.season_stats(player, season))
            slot.set_player(flat if pid else None) if isinstance(slot, SubChip) else \
                slot.set_player(flat if pid else None)
            if pid and player is None:
                slot.set_player({"display_name": f"? {pid}", "last_name": f"? {pid}"})
            slot.set_badges(badges.get(pid, []) if pid else [])
            sev = issue_by_index.get(n - 1)
            if sev:
                slot.set_issue(SEVERITY_COLOR[sev])
            elif pid and n <= STARTING_XV and not T.fits(player, season, n):
                slot.set_issue(WARN)
            else:
                slot.set_issue(None)
            if isinstance(slot, SlotAvatar):
                slot.empty_label = "+" if n - 1 == len(roster) else ""
            seen.add(pid)
        self.extras.setText(f"{len(roster)} / 22 players" if len(roster) < SQUAD_SIZE else "")
        self.extras.setVisible(len(roster) < SQUAD_SIZE)

        starters = roster[:STARTING_XV]
        for key, f in self.role_fields.items():
            rating = T.ROLE_RATING.get(key)
            f.set_options(sorted(starters, key=lambda pid: -self._rating(pid, rating)) if rating else starters)
            f.display = self._role_display(roster)
            f.tag_for = (lambda pid, r=rating: (str(self._rating(pid, r)), FG_TERTIARY)) if rating \
                else (lambda pid: (POSITION_SHORT.get(self.stats(pid).get("position1", ""), ""), FG_TERTIARY))
            f.set_value(str(roles.get(key, "") or ""))
        for key, f in self.play_fields.items():
            f.set_value((info.get("setPlays") or {}).get(key, "") or "")
        self._refresh_selection()

    def _rating(self, pid, key):
        try:
            return int(self.stats(pid).get(key, 0) or 0)
        except ValueError:
            return 0

    def _role_display(self, roster):
        players = self.screen.ds.players

        def display(pid):
            if not pid:
                return "— unset"
            p = players.get(pid)
            name = (p or {}).get("display_name") or f"? {pid}"
            if pid in roster:
                shirt = roster.index(pid) + 1
                suffix = (f"  #{shirt}" if shirt <= STARTING_XV else
                          f"  #{shirt} · not starting" if shirt <= SQUAD_SIZE else "  · extra player")
            else:
                suffix = "  · not in squad"
            return name + suffix
        return display

    def _refresh_selection(self):
        roster = self.roster()
        selected = self.selected_shirt
        self.edit_player_btn.setEnabled(selected - 1 < len(roster))
        # the card shows the player under the mouse, else the selected one;
        # the buttons always act on the selected one
        n = self._hovered if self._hovered is not None else selected
        pid = roster[n - 1] if n - 1 < len(roster) else None
        from app.game_data import SHIRT_POSITIONS
        pos_name = POSITION_NAMES.get(SHIRT_POSITIONS.get(n, ""), "")
        where = pos_name.lower() if n <= STARTING_XV else ("replacement" if n <= SQUAD_SIZE
                                                            else "extra player")
        self.sel_title.setText((f"PLAYER {n} · {where}" if n <= SQUAD_SIZE else "EXTRA PLAYER").upper())
        if pid is None:
            self.sel_name.setText("Empty")
            self.sel_meta.setText("Pick a player for this slot, or drag one here."
                                  if n - 1 <= len(roster) else "Fill the slots before this one first.")
            return
        player = self.player(pid)
        s = self.stats(pid)
        self.sel_name.setText((player or {}).get("display_name") or f"Unknown player {pid}")
        if player is None:
            self.sel_meta.setText(f"Id {pid} is not in the player files — the game drops this player.")
            return
        positions = [POSITION_NAMES.get(p, p) for p in (s.get("position1"), s.get("position2"),
                                                         s.get("position3")) if p]
        ovr = position_overall(s, SHIRT_POSITIONS.get(n))
        fit = "fits the position" if n > STARTING_XV or T.fits(player, self.screen.season, n) \
            else "OUT OF POSITION"
        self.sel_meta.setText(f"{' / '.join(positions) or 'no position'}  ·  OVR {ovr}  ·  {fit}")

    def hints(self, focused):
        if isinstance(focused, (SlotAvatar, SubChip)):
            if self.carrying is not None:
                return [("A", f"swap with {self.carrying}"), ("X", "drop here"), ("B", "cancel")]
            return [("A", "pick player"), ("X", "move"), ("Y", "edit player"), ("drag", "swap")]
        return []


# ═════════════════════════════════════════════════════════════════════════
# Match-day assets
# ═════════════════════════════════════════════════════════════════════════
# Stadium pads are switched off for now: no field in the editor, no issue
# raised for them (the team editor checks the same flag).
PADS_ENABLED = False


class AssetsTab(TeamTab):
    def __init__(self, screen, index):
        super().__init__(screen, index)
        grid = QGridLayout()
        grid.setSpacing(14)

        ball = SectionCard("ball")
        g = FieldGrid(columns=1)
        self.ball = self.register("ball", AssetField("Ball frames", ASSET_SPECS["ball"]))
        self._wire(self.ball, "ball")
        g.add(self.ball)
        ball.add(g)
        self.ball_strip = FrameStrip(2, thumb=(128, 64))
        ball.add(self.ball_strip)
        grid.addWidget(ball, 0, 0)

        banners = SectionCard("banners")
        g = FieldGrid(columns=1)
        self.banners = self.register("banners", AssetField("Banner images", ASSET_SPECS["banners"]))
        self._wire(self.banners, "banners")
        g.add(self.banners)
        banners.add(g)
        self.banner_strip = FrameStrip(4, thumb=(128, 32))
        banners.add(self.banner_strip)
        grid.addWidget(banners, 0, 1)

        self.pads = None
        if PADS_ENABLED:
            pads = SectionCard("stadium pads")
            g = FieldGrid(columns=1)
            self.pads = self.register("pads", AssetField("Pads archive", ASSET_SPECS["pads"]))
            self._wire(self.pads, "pads")
            g.add(self.pads)
            pads.add(g)
            pads.v.addStretch(1)
            grid.addWidget(pads, 1, 1)

        logos = SectionCard("secondary logos")
        g = FieldGrid(columns=1)
        self.logos = {}
        for slot, label in (("small", "Small logo"), ("left", "Left logo"), ("right", "Right logo")):
            f = self.register(f"logos.{slot}", AssetField(label, ASSET_SPECS[f"logos.{slot}"]))
            self._wire(f, f"logos.{slot}")
            g.add(f)
            self.logos[slot] = f
        logos.add(g)
        grid.addWidget(logos, 1, 0)
        self.body.addLayout(grid)
        self.body.addStretch(1)

    def _wire(self, field, key):
        field.browse_requested.connect(lambda: browse_assets(
            self.screen, field, self.screen.team_folder(), field.spec, field.value(),
            field.set_picked, title=field.label))
        field.edited.connect(lambda v: self.edit(field.label.lower(), lambda i: T_set_path(i, key, v), key))

    def refresh(self):
        info = self.info()
        root = self.screen.team_folder()
        for f, key in ((self.ball, "ball"), (self.banners, "banners"), (self.pads, "pads")):
            if f is None:
                continue
            f.set_root(root)
            f.set_value(info.get(key, ""))
        for slot, f in self.logos.items():
            f.set_root(root)
            f.set_value((info.get("logos") or {}).get(slot, ""))
        self.ball_strip.set_pattern(root, info.get("ball", "") if "%" in info.get("ball", "") else "")
        self.banner_strip.set_pattern(root, info.get("banners", "") if "%" in info.get("banners", "") else "")

    def hints(self, focused):
        if isinstance(focused, AssetField):
            return [("A", "browse"), ("X", "type path"), ("Del", "clear")]
        return []
