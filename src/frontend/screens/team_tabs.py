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
    ASSET_SPECS, ROLE_KEYS, SET_PLAYS, TEAM_TYPES, STARTING_XV, SQUAD_SIZE,
    looks_reversed,
)
from app.ratings import position_overall
from app.season import season_label
from ui.broadcast import Card, draw_frame, tracked_font, display_label, eyebrow_label
from ui.editor_kit import (
    FieldGrid, SectionCard, TextField, ChoiceField, SegmentField, AssetField,
    FrameStrip, Thumb, Note, Badge, TabStrip, browse_assets, load_pixmap, compact_button,
    SEVERITY_COLOR, worst,
)
from ui.team_sheet import (
    SHEET_ROWS, SUBSTITUTES, SlotAvatar, SubChip, PlayerPickerPopup, POSITION_NAMES,
    POSITION_SHORT, ROLE_SHORT, last_name,
)
from ui.widgets import StyledButton
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
TAB_OVERVIEW, TAB_KITS, TAB_SQUAD, TAB_ASSETS = range(4)


from shared.log import get_logger

log = get_logger(__name__)


def _transparent(widget, name):
    widget.setObjectName(name)
    widget.setStyleSheet(f"QWidget#{name} {{ background: transparent; }}")
    return widget


def _button(text, variant="neutral", h=BTN_HEIGHT_SM):
    return compact_button(text, variant, h)


class TeamTab:
    def __init__(self, screen, index):
        self.screen = screen
        self.index = index
        self.page = screen.shell.page(index)
        self.body = self.page.layout_

    def info(self):
        return self.screen.info()

    def edit(self, label, fn, key=None, coalesce=None):
        season = self.screen.season
        return self.screen.edit(label, lambda w: fn(w[season]), coalesce_key=coalesce,
                                view_hint={"season": season, "tab": self.index, "field": key})

    def register(self, key, widget):
        return self.screen.register_field(key, widget, self.index)

    def hints(self, focused):
        return []


# ═════════════════════════════════════════════════════════════════════════
# Overview
# ═════════════════════════════════════════════════════════════════════════
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
        ccol.addWidget(cgrid)
        ccol.addWidget(Note(ASSET_SPECS["logos.main"]["note"] + " 256×256 PNG."))
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
        self.crest_big.set_image(os.path.join(root, self.crest.value()) if self.crest.value() else "",
                                 "NO CREST")

        roster = [str(p) for p in info.get("players", [])]
        players = self.screen.ds.players
        season = self.screen.season
        n = len(roster)
        self._set_summary("squad", f"{n} / 22" + (f"  (+{n - 22} extra)" if n > 22 else ""),
                          GREEN if n == 22 else (WARN if n > 22 else DANGER_LITE))
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

    def _edit_kit(self, label, fn):
        name = self.current_kit_name()
        if name is None:
            return
        self.edit(f"{name} kit {label}", lambda i: fn(i["kits"][name]), f"kits.{name}")

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
        kit = kits.get(name, {}) if name else {}
        has = name is not None
        for w in (self.front, self.back, self.preview, self.color, self.fit, self.collar):
            w.setEnabled(has)
        for action, b in self.kit_buttons.items():
            b.setEnabled(has or action == "add")
        self.kit_title.setText(f"{name} kit · files".upper() if has else "FILES")
        root = self.screen.team_folder()
        for w, key in ((self.front, "frontKitFile"), (self.back, "backKitFile"),
                       (self.preview, "previewFile")):
            w.key = f"kits.{name}.{key}" if has else f"kits.{key}"
            w.set_root(root)
            w.set_value(kit.get(key, ""))
        self.color.set_value(kit.get("color", ""))
        self.color.key = f"kits.{name}.color"
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
# Squad & roles
# ═════════════════════════════════════════════════════════════════════════
class SquadTab(TeamTab):
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
        for shirts in SHEET_ROWS:
            hl = QHBoxLayout()
            hl.setSpacing(8)
            hl.addStretch(1)
            for n in shirts:
                slot = SlotAvatar(n, HOME_TINT, size="compact")
                self._wire_slot(slot)
                hl.addWidget(slot)
            hl.addStretch(1)
            sheet.add_layout(hl)
        rule = QWidget()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {BORDER};")
        sheet.add(rule)
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
        row.addWidget(sheet, stretch=1)

        side = QVBoxLayout()
        side.setSpacing(10)
        player_card = SectionCard("selected shirt")
        player_card.setFixedWidth(390)
        player_card.v.setSpacing(6)
        self.sel_title = player_card.title_lbl
        self.sel_name = display_label("—", T_TITLE, QFont.Bold, track=0.4, upper=False)
        player_card.add(self.sel_name)
        self.sel_meta = Note("", color=FG_SECONDARY, size=T_LABEL)
        player_card.add(self.sel_meta)
        prow = QHBoxLayout()
        prow.setSpacing(6)
        self.pick_btn = _button("CHANGE", h=32)
        self.pick_btn.clicked.connect(lambda: self.open_picker(self.selected_shirt))
        self.edit_player_btn = _button("EDIT PLAYER", h=32)
        self.edit_player_btn.clicked.connect(self._edit_player)
        self.remove_btn = _button("REMOVE", "danger", 32)
        self.remove_btn.clicked.connect(self._remove)
        for b in (self.pick_btn, self.edit_player_btn, self.remove_btn):
            screen.focus.register(b)
            prow.addWidget(b)
        player_card.add_layout(prow)
        arow = QHBoxLayout()
        arow.setSpacing(6)
        self.add_btn = _button("+ ADD PLAYER", h=32)
        self.add_btn.clicked.connect(lambda: self.open_picker(len(self.roster()) + 1))
        self.sort_btn = _button("AUTO-SORT", h=32)
        self.sort_btn.clicked.connect(self._auto_sort)
        self.reverse_btn = _button("REVERSE ORDER", h=32)
        self.reverse_btn.clicked.connect(self._reverse)
        for b in (self.add_btn, self.sort_btn, self.reverse_btn):
            screen.focus.register(b)
            arow.addWidget(b)
        player_card.add_layout(arow)
        side.addWidget(player_card)

        tactics = SectionCard("roles & set plays")
        tactics.setFixedWidth(390)
        tactics.v.setSpacing(4)
        self.tactics_tabs = TabStrip(["Roles", "Set plays"])
        screen.focus.register(self.tactics_tabs)
        tactics.add(self.tactics_tabs)
        self.tactics_stack = QStackedWidget()
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
        slot.hovered.connect(lambda n: None)
        slot.dropped.connect(self._on_drop)
        slot.double_clicked.connect(lambda n: self._edit_player(n))
        self.slots[slot.number] = slot
        self.register(f"players.{slot.number - 1}", slot)

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
        self.edit(f"swap shirts {a} and {b}", lambda i: T.swap(i, a - 1, b - 1), f"players.{b - 1}")
        self.selected_shirt = min(b, len(roster))

    def open_picker(self, number):
        roster = self.roster()
        index = number - 1
        if index > len(roster):
            index = len(roster)
            number = index + 1
        anchor = self.slots.get(number) or self.add_btn
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

        pool = list(dict.fromkeys(roster + list(players)))
        pool = [p for p in pool if p in players or p == current]
        pool.sort(key=rank)
        entries = [(pid, (players.get(pid) or {}).get("display_name") or pid, fits(pid)) for pid in pool]
        taken = {pid: s for pid, s in in_squad.items() if pid != current}
        tags = {pid: ("NEW", FG_TERTIARY) for pid in pool if pid not in in_squad}
        subtitles = {}
        for pid in pool:
            s = self.stats(pid)
            pos = POSITION_SHORT.get(s.get("position1", ""), s.get("position1", ""))
            ovr = position_overall(s)
            subtitles[pid] = f"{pos}  {ovr if ovr is not None else ''}"
        title = f"SHIRT {number}"
        if number <= STARTING_XV:
            from app.game_data import SHIRT_POSITIONS
            title += " · " + POSITION_NAMES.get(SHIRT_POSITIONS[number], "").upper()
        elif number <= SQUAD_SIZE:
            title += " · REPLACEMENT"
        else:
            title = "ADD TO SQUAD"
        self._picker_shirt = number
        self.picker.open_for(title, entries, current, taken, anchor, self.screen, tags=tags,
                             subtitles=subtitles)

    def _on_pick(self, pid):
        number = self._picker_shirt
        if number is None or pid is None:
            return
        roster = self.roster()
        if number - 1 < len(roster) and roster[number - 1] == str(pid):
            return
        name = (self.player(pid) or {}).get("display_name", pid)
        self.edit(f"put {name} in shirt {number}", lambda i: T.place(i, number - 1, pid),
                  f"players.{number - 1}")
        self.selected_shirt = min(number, len(self.roster()) + 1)
        QTimer.singleShot(0, lambda: self.slots.get(self.selected_shirt, self.add_btn).setFocus())

    def _remove(self):
        roster = self.roster()
        n = self.selected_shirt
        if n - 1 >= len(roster):
            return
        name = (self.player(roster[n - 1]) or {}).get("display_name", roster[n - 1])
        self.edit(f"remove {name}", lambda i: T.remove(i, n - 1), f"players.{n - 1}")
        self.screen.shell.footer.set_status(
            f"Removed {name} — later shirts moved up one (Ctrl+Z to undo)", FG_SECONDARY)

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
        extras = roster[SQUAD_SIZE:]
        if extras:
            names = ", ".join(last_name(players.get(p)) for p in extras)
            self.extras.setText(f"EXTRA PLAYERS ({len(extras)}): {names}")
            self.extras.setStyleSheet(self.extras.styleSheet().replace(FG_TERTIARY, WARN))
        else:
            self.extras.setText(f"{len(roster)} / 22 players" if len(roster) < SQUAD_SIZE else "")
        self.reverse_btn.setVisible(looks_reversed(roster, players, season))

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
                suffix = f"  #{shirt}" if shirt <= STARTING_XV else f"  #{shirt} · not starting"
            else:
                suffix = "  · not in squad"
            return name + suffix
        return display

    def _refresh_selection(self):
        roster = self.roster()
        n = self.selected_shirt
        pid = roster[n - 1] if n - 1 < len(roster) else None
        from app.game_data import SHIRT_POSITIONS
        pos_name = POSITION_NAMES.get(SHIRT_POSITIONS.get(n, ""), "")
        where = pos_name.lower() if n <= STARTING_XV else ("replacement" if n <= SQUAD_SIZE
                                                            else "not loaded by the game")
        self.sel_title.setText(f"SHIRT {n} · {where}".upper())
        has = pid is not None
        self.remove_btn.setEnabled(has)
        self.edit_player_btn.setEnabled(has)
        if not has:
            self.sel_name.setText("Empty")
            self.sel_meta.setText("Pick a player for this shirt, or drag one here."
                                  if n - 1 <= len(roster) else "Fill the shirts before this one first.")
            return
        player = self.player(pid)
        s = self.stats(pid)
        self.sel_name.setText((player or {}).get("display_name") or f"Unknown player {pid}")
        if player is None:
            self.sel_meta.setText(f"Id {pid} is not in the player files — the game drops this shirt.")
            return
        positions = [POSITION_NAMES.get(p, p) for p in (s.get("position1"), s.get("position2"),
                                                         s.get("position3")) if p]
        ovr = position_overall(s, SHIRT_POSITIONS.get(n))
        fit = "fits the shirt" if n > STARTING_XV or T.fits(player, self.screen.season, n) \
            else "OUT OF POSITION for this shirt"
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
        ball.add(Note(ASSET_SPECS["ball"]["note"] + " ball_%.png: 2 images, 256×128."))
        grid.addWidget(ball, 0, 0)

        banners = SectionCard("banners")
        g = FieldGrid(columns=1)
        self.banners = self.register("banners", AssetField("Banner images", ASSET_SPECS["banners"]))
        self._wire(self.banners, "banners")
        g.add(self.banners)
        banners.add(g)
        self.banner_strip = FrameStrip(4, thumb=(128, 32))
        banners.add(self.banner_strip)
        banners.add(Note(ASSET_SPECS["banners"]["note"] + " banner_%.png: 4 images, 512×128."))
        grid.addWidget(banners, 0, 1)

        pads = SectionCard("stadium pads")
        g = FieldGrid(columns=1)
        self.pads = self.register("pads", AssetField("Pads archive", ASSET_SPECS["pads"]))
        self._wire(self.pads, "pads")
        g.add(self.pads)
        pads.add(g)
        pads.add(Note(ASSET_SPECS["pads"]["note"] + " A .fsh texture archive, copied as-is."))
        pads.v.addStretch(1)
        grid.addWidget(pads, 1, 0)

        logos = SectionCard("secondary logos")
        g = FieldGrid(columns=1)
        self.logos = {}
        for slot, label in (("small", "Small logo"), ("left", "Left logo"), ("right", "Right logo")):
            f = self.register(f"logos.{slot}", AssetField(label, ASSET_SPECS[f"logos.{slot}"]))
            self._wire(f, f"logos.{slot}")
            g.add(f)
            self.logos[slot] = f
        logos.add(g)
        grid.addWidget(logos, 1, 1)
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
