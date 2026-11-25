"""
screens/team_editor.py — Team editor
=========================================
Edits teams/<Team>/<team>.json: {team_id: {season: {...}}}. Everything in a
season block — name, kits, crest, squad, roles — belongs to that season, so
the season picker lives in the header and governs every tab.

A season may also carry competition variants (app/variants.py): the variant
picker next to the season picker switches every tab to that variant as it
resolves; edits made there are stored as the variant's differences only.

Tabs: Overview (identity, crest, a summary of what the game will get),
Kits (ordered list, live preview, files), Shirt names (players' names on
the back: lettering, name area, colours per kit), Squad & roles (the team sheet —
list order IS the shirt number), Match-day assets (ball, banners, pads,
secondary logos).
"""
import copy
import os

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import QTimer

from app import disk_import
from app import team_ops as T
from app import variants as V
from app.game_data import (
    check_team_detailed, check_team_variants, season_errors, save_team, delete_team, save_target, saves_to_user_edits, SaveError, EditsOffError,
    TEAM_TYPES, ASSET_SPECS, frontend_logo,
)
from app.team_browse import GROUPS, group_label, info_group
from app.season import season_label
from screens.editor_base import EditorScreen
from screens.team_tabs import (
    OverviewTab, KitsTab, ShirtNamesTab, SquadTab, AssetsTab, TAB_OVERVIEW, TAB_KITS, TAB_NAMES,
    TAB_SQUAD, TAB_ASSETS,
)
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget
from ui.broadcast import Card, eyebrow_label
from ui.form import SearchList
from ui.editor_kit import (
    Badge, compact_button, open_season_menu, VariantPicker, ConfirmDialog, FormDialog, TextField, NumberField, ChoiceField,
    SegmentField, asset_status, load_pixmap,
)
from ui.theme import (
    ACCENT, GREEN, INFO, WARN, DANGER_LITE, FG_SECONDARY, FG_TERTIARY, HOME_TINT,
)
from shared.config import config


class TeamEditorScreen(EditorScreen):
    TAB_TITLES = ["Overview", "Kits", "Shirt names", "Squad & roles", "Other"]
    RECORD_NOUN = "team"
    EDIT_KIND = "teams"
    LIST_PLACEHOLDER = "filter teams"
    MID_PANE = True
    FIT_PANES = True

    def __init__(self, ds, on_back, open_player=None):
        self.season = None
        self.variant = V.DEFAULT
        self._open_player_cb = open_player
        super().__init__(ds, on_back)
        self.new_btn.setText("+ NEW TEAM")

        self._build_season_pane()
        self.tabs = [OverviewTab(self, TAB_OVERVIEW), KitsTab(self, TAB_KITS),
                     ShirtNamesTab(self, TAB_NAMES), SquadTab(self, TAB_SQUAD),
                     AssetsTab(self, TAB_ASSETS)]
        # Squad variants only hold players, roles and set plays, so their
        # picker lives on the squad tab (kit variants have their own, on the
        # kits tab).
        self.variant_picker = VariantPicker(display=self._variant_display, width=270)
        self.variant_picker.variant_picked.connect(self.set_variant)
        self.variant_picker.action.connect(self.variant_action)
        self.tabs[TAB_SQUAD].side_col.insertWidget(0, self.variant_picker)
        self.focus.register(self.variant_picker.choice)
        self.focus.register(self.variant_picker.menu_btn)
        ds.events.player_changed.connect(lambda _: self._external_change())
        ds.events.player_removed.connect(lambda _: self._external_change())

    # ── seasons pane (narrow column left of the tabs, as in the player editor) ──
    def _build_season_pane(self):
        seasons_card = Card()
        sv = QVBoxLayout(seasons_card)
        sv.setContentsMargins(8, 12, 8, 10)
        sv.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(eyebrow_label("seasons", color=FG_TERTIARY, size=11))
        head.addStretch(1)
        self.season_add_btn = compact_button("+ ADD")
        self.season_add_btn.setMinimumWidth(0)
        self.season_add_btn.clicked.connect(lambda: self.season_action("add"))
        head.addWidget(self.season_add_btn)
        self.season_menu_btn = compact_button("⋯")
        self.season_menu_btn.setFixedWidth(30)
        self.season_menu_btn.clicked.connect(
            lambda: open_season_menu(self.season_menu_btn, self.window(), self.season_action))
        head.addWidget(self.season_menu_btn)
        sv.addLayout(head)
        self.season_list = SearchList("", show_filter=False)
        self.season_list.activated.connect(self.set_season)
        sv.addWidget(self.season_list, stretch=1)
        self.shell.mid_layout.addWidget(seasons_card, stretch=1)
        for w in (self.season_add_btn, self.season_menu_btn, self.season_list):
            self.focus.register(w)

        self.season_row = QWidget()
        ctx = QHBoxLayout(self.season_row)
        ctx.setContentsMargins(0, 0, 0, 10)
        ctx.setSpacing(8)
        self.season_pill = Badge("NO SEASON", ACCENT, filled=True)
        ctx.addWidget(self.season_pill)
        # the mod leaves a season with errors out until it is fixed and saved
        self.season_warn = Badge("TEAM NOT USED UNTIL ERRORS ARE FIXED:", WARN, filled=True)
        self.season_warn.hide()
        ctx.addWidget(self.season_warn)
        ctx.addStretch(1)
        self.shell.right_layout.insertWidget(0, self.season_row)

    def _refresh_seasons(self):
        working = self.session.working
        self.season_warn.setVisible(bool(self.season) and bool(
            season_errors(self.season_block(), self.ds.players, self.season)))
        items = [(s, season_label(s),
                  "DRAFT" if working[s].get("draft") else
                  str(len([p for p in working[s].get('players', []) if p])),
                  WARN if working[s].get("draft") else FG_TERTIARY, False) for s in sorted(working)]
        self.season_pill.set_text(
            f"SEASON {season_label(self.season)}" if self.season else "NO SEASON")
        self.season_list.set_items(items, keep_data=self.season)
        self.season_list.set_selected(self.season)

    # ── record plumbing ──────────────────────────────────────────────────
    GROUP_LABEL = "Group"
    SORTS = [("name", "name"), ("issues", "most issues"), ("squad", "squad size")]
    EXTRA_FILTERS = [("type", "Type")]

    def list_rows(self):
        rows = []
        for tid in self.ds.team_ids():
            seasons = self.ds.team_seasons(tid)
            latest = sorted(seasons)[-1] if seasons else None
            info = seasons.get(latest, {}) if latest else {}
            issues = (check_team_detailed(info, self.ds.players, latest)
                      + check_team_variants(info, self.ds.players, latest)) if info else []
            errors = sum(1 for _, _, s in issues if s == "error")
            drafts = sum(1 for i in seasons.values() if i.get("draft"))
            n = len([p for p in info.get("players", []) if p])
            tag = "DRAFT" if drafts else f"{errors} ERR" if errors else f"{n} players"
            rows.append({
                "id": tid, "text": info.get("name") or tid, "tag": tag,
                # the player count is not a warning: any size from 22 up is fine
                "color": WARN if drafts else DANGER_LITE if errors else FG_TERTIARY,
                "search": f"{tid} {info_group(info)} {' '.join(seasons)}",
                "errors": errors + drafts, "issues": len(issues), "group": info_group(info),
                "sort": {"squad": n},
                "filters": {"type": info.get("type") or ""},
            })
        return rows

    def load_record(self, tid):
        seasons = self.ds.team_seasons(tid)
        return copy.deepcopy(seasons) if seasons else None

    def on_record_opened(self):
        seasons = sorted(self.session.working)
        if self.season not in seasons:
            self.season = seasons[-1] if seasons else None
        self.tabs[TAB_KITS].kit_index = 0
        self.tabs[TAB_KITS].kit_variant = V.DEFAULT
        self.tabs[TAB_NAMES].kit_name = None
        self.tabs[TAB_SQUAD].selected_shirt = 1
        self.tabs[TAB_SQUAD].set_carrying(None)
        if self.variant not in V.variant_ids(self.session.working.get(self.season, {})):
            self.variant = V.DEFAULT

    def season_block(self):
        """The stored season block (default + its "variant" map)."""
        if self.session is None or self.season not in self.session.working:
            return {}
        return self.session.working[self.season]

    def info(self):
        """What every tab shows and edits: the season block, or — with a
        variant picked — a resolved copy of it (edits go through
        TeamTab.edit, which stores only the variant's differences)."""
        block = self.season_block()
        if self.variant and block:
            return V.resolve(block, self.variant)
        return block

    def _variant_display(self, vid):
        return V.variant_label(self.season_block(), vid)

    def team_folder(self):
        return self.ds.teams_folder_path.get(self.record_id, "")

    def file_label(self):
        path = self.ds.teams_file_path.get(self.record_id, "")
        if not path:
            return ""
        try:
            return os.path.relpath(path, config.mod_data_directory)
        except ValueError:
            return path

    def set_season(self, season):
        if self.session is None or season not in self.session.working or season == self.season:
            return
        self.season = season
        if self.variant not in V.variant_ids(self.session.working[season]):
            self.variant = V.DEFAULT
        self.tabs[TAB_SQUAD].set_carrying(None)
        self.refresh_all()

    def set_variant(self, variant):
        variant = variant or V.DEFAULT
        if self.session is None or variant == self.variant:
            return
        if variant and variant not in V.variant_ids(self.season_block()):
            return
        self.variant = variant
        self.tabs[TAB_SQUAD].set_carrying(None)
        self.refresh_all()

    def current_view_hint(self):
        return {"season": self.season, "variant": self.variant, "tab": self.shell.tabs.index()}

    def apply_view_hint(self, hint):
        if not hint:
            return
        season = hint.get("season")
        if season and self.session is not None and season in self.session.working:
            self.season = season
            variant = hint.get("variant", self.variant) or V.DEFAULT
            self.variant = variant if variant in V.variant_ids(self.session.working[season]) \
                else V.DEFAULT
        if "kit_variant" in hint:
            self.tabs[TAB_KITS].kit_variant = hint["kit_variant"] or V.DEFAULT
        super().apply_view_hint(hint)

    def refresh_view(self):
        seasons = list(self.session.working)
        if self.season not in self.session.working:
            self.season = sorted(seasons)[-1] if seasons else None
        self._refresh_seasons()
        if self.season is None:
            return
        variants = V.variant_ids(self.season_block())
        if self.variant not in variants:
            self.variant = V.DEFAULT
        self.variant_picker.set_variants(variants, self.variant)
        # issues first: tabs colour their widgets from them
        self.issues = self.collect_issues()
        for tab in self.tabs:
            tab.refresh()

    def collect_issues(self):
        info = self.info()
        if not info:
            return []
        issues = check_team_detailed(info, self.ds.players, self.season)
        root = self.team_folder()

        def check(key, rel, spec_key):
            state, detail, _ = asset_status(root, rel, ASSET_SPECS.get(spec_key))
            if state in ("missing", "outside", "size", "bad"):
                issues.append((key, f"{key}: {detail}", "warn"))
            elif state == "partial":
                issues.append((key, f"{key}: {detail}", "info"))

        for key in ("ball", "banners"):
            check(key, info.get(key, ""), key)
        for slot, rel in (info.get("logos") or {}).items():
            check(f"logos.{slot}", rel, f"logos.{slot}")
        for name, kit in (info.get("kits") or {}).items():
            for field in ("frontKitFile", "backKitFile", "previewFile"):
                check(f"kits.{name}.{field}", kit.get(field, ""), field)
            for vid in V.kit_variant_ids(kit):
                over = V.kit_overrides(kit, vid)
                for field in ("frontKitFile", "backKitFile", "previewFile"):
                    if field in over:
                        check(f"kits.{name}.variants.{vid}.{field}", over[field], field)
        issues += self._shirt_name_issues(info, root)
        return issues

    @staticmethod
    def _shirt_name_issues(info, root):
        from shared import shirt_names as SN
        out = []
        for name, kit in (info.get("kits") or {}).items():
            style = SN.season_style_for(info, kit)
            if not style["enabled"]:
                continue
            font = style["font"]
            if font and not SN.resolve_font(font, root)[2]:
                out.append((f"shirtName.font.{name}", f"shirt names: the {name} kit's font {font} "
                            f"was not found, using {SN.DEFAULT_FONT}", "warn"))
        return out

    def tab_for_issue(self, key):
        if key.startswith(("shirtNames", "shirtName.")):
            return TAB_NAMES
        if key.startswith("kits"):
            return TAB_KITS
        if key.startswith(("players", "roles", "setPlays")):
            return TAB_SQUAD
        if key in ("ball", "banners") or key.startswith(("logos.small", "logos.left",
                                                                 "logos.right")):
            return TAB_ASSETS
        return TAB_OVERVIEW

    def _field_for_key(self, key):
        # Kit fields are one set of widgets showing whichever kit is selected:
        # an issue on another kit must not light them up.
        parts = key.split(".")
        if parts[0] == "kits" and len(parts) >= 3:
            kits_tab = self.tabs[TAB_KITS] if hasattr(self, "tabs") else None
            current = kits_tab.current_kit_name() if kits_tab else None
            if parts[1] != current:
                return self.fields.get("kits")
            if parts[2] == "variants":       # kits.<kit>.variants.<id>[.<field>]
                if len(parts) < 5 or parts[3] != kits_tab.current_variant():
                    return self.fields.get("kits.variant") or self.fields.get("kits")
                parts = parts[:2] + parts[4:]
            elif kits_tab.current_variant():
                return self.fields.get("kits")  # the plain kit's file, variant shown
            return self.fields.get(f"kits.{parts[2]}") or self.fields.get("kits")
        return super()._field_for_key(key)

    def reveal(self, key):
        parts = key.split(".")
        if parts[0] == "kits" and len(parts) >= 2:
            kits_tab = self.tabs[TAB_KITS]
            names = kits_tab.kit_names()
            if parts[1] in names:
                kits_tab.kit_index = names.index(parts[1])
                kits_tab.kit_variant = parts[3] if len(parts) >= 4 and parts[2] == "variants" \
                    else V.DEFAULT
                self.refresh_all()
        super().reveal(key)

    def write_record(self):
        saved = self.ds.team_seasons(self.record_id)
        drafts = T.mark_drafts(self.session.working, saved, self.ds.players)
        path = self.ds.teams_file_path.get(self.record_id)
        save_team(path, self.record_id, self.session.working)
        self.ds.set_team_seasons(self.record_id, copy.deepcopy(self.session.working))
        if drafts:
            names = ", ".join(season_label(s) for s in drafts)
            return (f"Saved, but not used in the mod until fixed: {names}", WARN)
        return f"Saved to {save_target(path)}"

    def after_save(self):
        self.ds.events.team_changed.emit(self.record_id)

    def header_state(self):
        info = self.info()
        root = self.team_folder()
        crest = frontend_logo(info)
        chips = []          # no category / type / country tags: only the variant edited
        if self.variant:
            chips.append((V.variant_label(self.season_block(), self.variant), ACCENT))
        name = info.get("name") or self.record_id or "—"
        return {
            "eyebrow": "",
            "title": name,
            "subtitle": "",
            "chips": chips,
            "pixmap": load_pixmap(os.path.join(root, crest), 128) if crest else None,
            "initials": "".join(w[:1] for w in name.split()[:2]) or "?",
        }

    def tab_hints(self, focused):
        if focused is self.season_list:
            return [("↕", "browse"), ("A", "load season")]
        if focused in (self.season_add_btn, self.season_menu_btn):
            return [("A", "open")]
        tab = self.tabs[self.shell.tabs.index()]
        return tab.hints(focused)

    def _on_focus_changed(self, old, new):
        super()._on_focus_changed(old, new)
        if hasattr(self, "tabs") and new is not None:
            self.tabs[TAB_SQUAD].on_focus(new)

    def _external_change(self):
        if self.isVisible() and self.session is not None:
            self.refresh_all()

    # ── actions routed by the key layer ──────────────────────────────────
    def alt_action(self, focused):
        squad = self.tabs[TAB_SQUAD]
        if getattr(focused, "number", None) in squad.slots and squad.slots.get(focused.number) is focused:
            squad.toggle_carry(focused.number)
            return True
        return super().alt_action(focused)

    def aux_action(self, focused):
        squad = self.tabs[TAB_SQUAD]
        if getattr(focused, "number", None) in squad.slots and squad.slots.get(focused.number) is focused:
            squad._edit_player(focused.number)
            return True
        return False

    def keyPressEvent(self, event):
        squad = self.tabs[TAB_SQUAD] if hasattr(self, "tabs") else None
        from PyQt5.QtCore import Qt
        if squad is not None and squad.carrying is not None and event.key() in (
                Qt.Key_Escape, Qt.Key_Backspace) and self._dialog is None:
            squad.set_carrying(None)
            event.accept()
            return
        super().keyPressEvent(event)

    def show_team(self, tid, season=None, shirt=None, variant=V.DEFAULT):
        """Entry point used by the player editor's squad links."""
        def go():
            if tid != self.record_id:
                self.open_record(tid)
            if season and self.session is not None and season in self.session.working:
                self.set_season(season)
                self.set_variant(variant)
            if shirt:
                self.tabs[TAB_SQUAD].selected_shirt = shirt
                self.reveal(f"players.{int(shirt) - 1}")
        self.guard_dirty(go)

    def open_player(self, pid):
        if self._open_player_cb is None:
            self.shell.footer.set_status("Open the player editor from Tools", FG_SECONDARY)
            return
        self.guard_dirty(lambda: self._open_player_cb(pid, self.season))

    # ── dialogs ──────────────────────────────────────────────────────────
    def season_action(self, action):
        if self.session is None:
            return
        seasons = self.session.working
        if action in ("add", "duplicate"):
            year = NumberField("Season", lo=1900, hi=2100, allow_blank=False, formatter=season_label)
            try:
                suggestion = str(max(int(s) for s in seasons) + 1)
            except ValueError:
                suggestion = "2026"
            year.set_value(suggestion)
            source = ChoiceField("Start from", sorted(seasons), allow_blank=True,
                                 blank_label="Blank season (empty squad and files)",
                                 display=lambda s: f"Copy of {season_label(s)}")
            source.set_value(self.season if action == "duplicate" else "")

            def done(role):
                self._dialog = None
                if role != "ok":
                    return
                y = year.value()
                if y in seasons:
                    self.shell.footer.set_status(f"Season {season_label(y)} already exists", DANGER_LITE)
                    return
                info = self.info()
                src = source.value() or None
                self.edit(f"add season {season_label(y)}", lambda w: T.add_season(
                    w, y, src, info.get("name", ""), info.get("type", "club"), info.get("group", "")),
                    view_hint={"season": y, "tab": self.shell.tabs.index()})
                self.season = y
                self.refresh_all()
                self.shell.footer.set_status(
                    f"Season {season_label(y)} added" + (f" from {season_label(src)}" if src else ""), GREEN)

            self.show_dialog(FormDialog(
                self, "Add season" if action == "add" else "Duplicate season",
                "Type the year the season ends in (2026 is 2025-2026). Each season has its own name, kits, crest, squad and roles.",
                {"year": year, "source": source},
                [("CANCEL", "neutral", "cancel"), ("ADD SEASON", "primary", "ok")], done))
        elif action == "delete":
            if len(seasons) <= 1:
                self.shell.footer.set_status("A team needs at least one season", DANGER_LITE)
                return
            season = self.season
            self.confirm(f"Delete season {season_label(season)}?",
                         "Its name, kits, squad and roles will be removed from this team.",
                         "DELETE SEASON",
                         lambda: self._delete_season(season))

    def _delete_season(self, season):
        self.edit(f"delete season {season_label(season)}", lambda w: T.delete_season(w, season),
                  view_hint={"season": season, "tab": self.shell.tabs.index()})
        self.season = sorted(self.session.working)[-1]
        self.refresh_all()

    # ── competition variants ─────────────────────────────────────────────
    def _known_variant_ids(self):
        """Competition family ids: every competition template, every variant
        id already used in the data."""
        try:
            from app.tournament import formats
            ids = set(formats.load_templates())
        except Exception:
            ids = set()
        return sorted(ids | set(V.all_variant_ids(self.ds.teams)))

    def variant_action(self, action):
        if self.session is None or self.season is None:
            return
        block = self.season_block()
        season = self.season
        hint = {"season": season, "tab": self.shell.tabs.index()}
        if action == "add":
            taken = set(V.variant_ids(block))
            known = [v for v in self._known_variant_ids() if v not in taken]
            family = ChoiceField("Competition", known, allow_blank=True,
                                 blank_label="(type a new id below)",
                                 display=lambda v: v.replace("_", " "))
            family.set_value(known[0] if known else "")
            other = TextField("New id")
            label = TextField("Label")

            def done(role):
                self._dialog = None
                if role != "ok":
                    return
                vid = (other.value() or "").strip().lower() or family.value()
                try:
                    self.edit(f"add variant {vid}",
                              lambda w: T.add_variant(w[season], vid, label.value().strip()),
                              view_hint=hint)
                except ValueError as e:
                    self.shell.footer.set_status(str(e), DANGER_LITE)
                    return
                self.variant = vid
                self.refresh_all()
                self.shell.footer.set_status(
                    f"Variant {V.variant_label(self.season_block(), vid)} added, copied from the default",
                    GREEN)

            self.show_dialog(FormDialog(
                self, "Add variant",
                f"A squad for one competition in season {season_label(season)}: players, roles "
                "and set plays. Named after a tournament (rwc_2023, six_nations_2024…: that "
                "edition only) or a competition (world_cup: any edition that asks for it); "
                "starts as a copy of the default. Competition kits are kit variants "
                "(Kits tab).",
                {"family": family, "other": other, "label": label},
                [("CANCEL", "neutral", "cancel"), ("ADD VARIANT", "primary", "ok")], done))
        elif action == "rename" and self.variant:
            vid = self.variant
            label = TextField("Label")
            label.set_value(V.variant_label(block, vid))

            def done(role):
                self._dialog = None
                if role == "ok":
                    self.edit(f"rename variant {vid}",
                              lambda w: T.set_variant_label(w[season], vid, label.value().strip()),
                              view_hint=hint)
            self.show_dialog(FormDialog(self, "Rename variant", f"Id {vid} stays the same.",
                                        {"label": label},
                                        [("CANCEL", "neutral", "cancel"), ("RENAME", "primary", "ok")],
                                        done))
        elif action == "reset" and self.variant:
            vid = self.variant
            self.confirm(f"Reset {V.variant_label(block, vid)} to default?",
                         "Its squad, roles and set plays will be replaced by the season's default.",
                         "RESET",
                         lambda: self.edit(f"reset variant {vid}",
                                           lambda w: T.clear_variant(w[season], vid), view_hint=hint))
        elif action == "delete" and self.variant:
            vid = self.variant

            def go():
                self.edit(f"delete variant {vid}", lambda w: T.delete_variant(w[season], vid),
                          view_hint=hint)
                self.variant = V.DEFAULT
                self.refresh_all()
            self.confirm(f"Delete variant {V.variant_label(block, vid)}?",
                         "Competitions using it will get the default squad.", "DELETE VARIANT", go)

    # ── whole-team create / duplicate / delete ───────────────────────────
    def new_record(self):
        self._team_dialog(duplicate=False)

    def duplicate_record(self):
        if self.session is not None:
            self._team_dialog(duplicate=True)

    def _team_dialog(self, duplicate):
        name = TextField("Team name")
        name.blank_text = ""
        team_type = SegmentField("Type", TEAM_TYPES)
        group = ChoiceField("Group", GROUPS, allow_blank=False, blank_label="", display=group_label)
        group.popup_title = "group (where the team is listed)"
        year = NumberField("Season", lo=1900, hi=2100, allow_blank=False, formatter=season_label)
        copy_files = SegmentField("Copy image files", ["yes", "no"])
        info = self.info() if duplicate else {}
        name.set_value(f"{info.get('name', '')} copy" if duplicate else "")
        team_type.set_value(info.get("type", "club") if duplicate else "club")
        group.set_value(info.get("group", "") if duplicate else "")
        year.set_value(self.season or "2026")
        copy_files.set_value("yes")
        if not duplicate:
            fields = {"name": name, "type": team_type, "group": group, "year": year}
        else:
            fields = {"name": name, "type": team_type, "group": group, "copy": copy_files}

        def done(role):
            self._dialog = None
            if role == "ok":
                run()

        def run():
            try:
                self._create_team(name.value().strip(), team_type.value() or "club",
                                  group.value(), year.value(), duplicate,
                                  copy_files.value() == "yes")
            except EditsOffError:
                self.ask_edits_on(run, replaces=False)
            except (ValueError, OSError, SaveError) as e:
                self.shell.footer.set_status(f"Could not create team: {e}", DANGER_LITE)

        self.show_dialog(FormDialog(
            self, "Duplicate team" if duplicate else "New team",
            "Copies every season into a new team." if duplicate else "",
            fields, [("CANCEL", "neutral", "cancel"),
                     ("CREATE", "primary", "ok")], done, required=("name",) if duplicate else ("name", "group")))

    def _create_team(self, name, team_type, group, year, duplicate, copy_files):
        if not name:
            raise ValueError("the team needs a name")
        if not group and not duplicate:
            raise ValueError("the team needs a group")
        teams_dir = config.directory_teams
        folder = T.safe_folder_name(name, teams_dir)
        tid = T.allocate_team_id(team_type, self.ds.team_json_ids, {**self.ds.teams, **self.ds.team_drafts})
        if duplicate:
            seasons = copy.deepcopy(self.session.working)
            for info in seasons.values():
                info["name"] = name
                info["type"] = team_type
                if group:
                    info["group"] = group
                else:
                    info.pop("group", None)
            source_folder = self.team_folder() if copy_files else None
        else:
            seasons = {str(year): T.new_team_season(name, team_type, group)}
            source_folder = None
        T.mark_drafts(seasons, {}, self.ds.players)
        json_path, missing = T.create_team(teams_dir, folder, tid, seasons, source_folder,
                                           copy_file=disk_import.copy_into_data)
        self.ds.register_team(tid, seasons, os.path.join(teams_dir, folder), json_path)
        self.reload_list()

        def open_new():
            self.open_record(tid)
            note = f" ({len(missing)} pictures were missing)" if missing else ""
            self.shell.footer.set_status(f"Created {name}{note}", GREEN)
        self.guard_dirty(open_new)

    def delete_record(self):
        if self.record_id is None:
            return
        tid = self.record_id
        path = self.ds.teams_file_path.get(tid, "")
        name = self.info().get("name", tid)
        memberships = ""

        def do_delete():
            try:
                outcome = delete_team(path, tid)
            except EditsOffError:
                self.ask_edits_on(do_delete, replaces=False)
                return
            except SaveError as e:
                self.shell.footer.set_status(f"Delete failed: {e}", DANGER_LITE)
                return
            if self.session is not None:
                self.session.revert()
            self.ds.unregister_team(tid)
            self.record_id = None
            self.session = None
            self.reload_list()
            if self.list.count():
                self.list.set_highlight(0)
                self.open_record(self.list.highlighted_data())
            else:
                self.refresh_all()
            self.shell.footer.set_status(
                f"Deleted {name}: {outcome}", FG_SECONDARY)

        text = ("The team is removed in your edits. The data pack is unchanged and you can "
                "restore it from Tools › My edits."
                if saves_to_user_edits() else
                f"{os.path.basename(path)} will be renamed to …deleted-<date>. Image files "
                f"stay, and renaming the file back restores the team.")
        self.confirm(f"Delete team {name}?", text + memberships, "DELETE TEAM", do_delete)
