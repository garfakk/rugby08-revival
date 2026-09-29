"""
screens/player_editor.py — Player editor
=============================================
Edits players/*.json: identity carried once at the top of a record, and a
`stats` block per SEASON holding the 24 ratings, positions and appearance —
the same man is rated differently in 2008 and 2026. The header's season
picker governs the Ratings and Appearance tabs and the season half of
Profile.
"""
import copy
import os

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QVBoxLayout, QHBoxLayout, QWidget

from app import appearance as A
from app import player_ops as P
from app.game_data import (
    check_player_detailed, save_player, SaveError, POSITIONS, SHIRT_POSITIONS,
)
from app.ratings import position_overall
from app.season import season_label
from app import plugin_lookup
from backend.mod_utils import stock_head_path, stock_kit_paths
from screens.editor_base import EditorScreen
from screens.player_tabs import (
    ProfileTab, RatingsTab, AppearanceTab, SkillsTab, TeamsTab, TAB_PROFILE, TAB_RATINGS,
    TAB_APPEARANCE, TAB_SKILLS, TAB_TEAMS,
    position_name, normalise_birthdate,
)
from ui.broadcast import Card, display_label, eyebrow_label, tracked_font
from ui.editor_kit import (
    Avatar, Badge, FormDialog, ConfirmDialog, TextField, NumberField, ChoiceField,
    SegmentField, RatingField, Note, compact_button, open_season_menu,
)
from ui.form import SearchList
from ui.skin_preview import compose as skin_compose
from ui.team_sheet import POSITION_SHORT
from ui.theme import (
    ACCENT, GREEN, DANGER_LITE, INFO, FG_SECONDARY, FG_TERTIARY, T_LABEL, FONT_DISPLAY,
)
from shared.config import config

from shared.log import get_logger

log = get_logger(__name__)

PROFILE_KEYS = {"record", "display_name", "first_name", "last_name", "birthdate", "commentary",
                "position1", "position2", "position3", "height", "weight", "foot", "nationality"}
APPEARANCE_KEYS = {"skin_tone", "skin", "skin_overlay", "face", "boot_style", "socks", "gloves",
                   "wrist_tape", "tight_tape", "finger_tape", "headgear"}

_NO_PREVIEW = object()   # refresh_stage()'s "use the real stored face" default


def _display_name_default(record):
    """What the in-game name field shows when `display_name` is blank: the
    first letter of the first name, a dot, and the last name — e.g. "J.
    Smith" — falling back to whichever of the two names exists, or the
    game's own real fallback ("Unknown", see app.game_data.check_player)
    when neither does."""
    first = (record.get("first_name") or "").strip()
    last = (record.get("last_name") or "").strip()
    if first and last:
        return P.truncate_bytes(f"{first[0]}. {last}")
    return P.truncate_bytes(last or first) or "Unknown"


def _first_last_default(record):
    """The mirror image of _display_name_default: when BOTH first and last
    name are blank, guess them from the in-game name instead — everything
    but its last word as the first-name hint, its last word as the
    last-name hint — so the big nameplate isn't just empty when there's at
    least an in-game name to go on."""
    name = (record.get("display_name") or "").strip()
    if not name:
        return "", ""
    parts = name.replace(".", ". ").split()
    if len(parts) >= 2:
        return " ".join(parts[:-1]), parts[-1]
    return "", parts[0]


class PlayerEditorScreen(EditorScreen):
    TAB_TITLES = ["Profile", "Ratings", "Appearance", "Skills", "Teams"]
    RECORD_NOUN = "player"
    LIST_PLACEHOLDER = "name, id, position, team"
    MID_PANE = True
    COMPACT_HEADER = True
    IDENTITY_PANE = True
    PREVIEW_PANE = True

    def __init__(self, ds, on_back, open_team=None):
        self.season = None
        self._open_team_cb = open_team
        self._stage_key = None
        super().__init__(ds, on_back)
        self.new_btn.setText("+ NEW PLAYER")
        self._build_identity_pane()
        self._build_season_pane()
        self._build_preview_pane()

        self.tabs = [ProfileTab(self, TAB_PROFILE), RatingsTab(self, TAB_RATINGS),
                     AppearanceTab(self, TAB_APPEARANCE), SkillsTab(self, TAB_SKILLS),
                     TeamsTab(self, TAB_TEAMS)]
        self._build_no_season_page()
        ds.events.team_changed.connect(lambda _: self._external_change())
        ds.events.team_removed.connect(lambda _: self._external_change())

    def _build_no_season_page(self):
        """Shown instead of the tabs when the record has no season to show
        (a broken/empty player — `collect_issues` already flags it)."""
        self._no_season_page = QWidget()
        v = QVBoxLayout(self._no_season_page)
        v.addStretch(1)
        msg = display_label("Please select a season", 19, QFont.DemiBold, track=0.3, upper=False)
        msg.setAlignment(Qt.AlignCenter)
        v.addWidget(msg)
        sub = Note("", color=FG_TERTIARY, size=T_LABEL)
        sub.setAlignment(Qt.AlignCenter)
        sub.setMaximumWidth(360)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(sub)
        row.addStretch(1)
        v.addLayout(row)
        v.addStretch(1)
        self.shell.stack.addWidget(self._no_season_page)

    def _edit_identity(self, label, key, value):
        self.edit(label, lambda r: r.__setitem__(key, value), coalesce_key=key,
                 view_hint={"tab": TAB_PROFILE, "field": key})

    def _open_bio_search(self):
        plugin = plugin_lookup.get()
        if plugin is None or self.session is None:
            return
        record = self.session.working
        name = f"{record.get('first_name', '')} {record.get('last_name', '')}".strip()
        query = name or record.get("display_name", "")
        plugin.open_bio_search(self, query=query, on_apply=self._apply_bio_fields)

    def _apply_bio_fields(self, fields):
        if self.session is None or not fields:
            return
        season = self.season
        identity = {k: v for k, v in fields.items() if k in ("first_name", "last_name", "birthdate")}
        stat_map = {"height_cm": "height", "weight_kg": "weight", "nationality": "nationality",
                   "position1": "position1", "position2": "position2"}
        # Every stat field is stored as a string ("183", not 183) — game_data's
        # own validation assumes it (str.strip()) — but height_cm/weight_kg
        # come back from Wikidata as ints.
        stats = {stat_map[k]: str(v) for k, v in fields.items() if k in stat_map}

        def mutate(r):
            r.update(identity)
            if stats and season:
                r.setdefault("stats", {}).setdefault(season, {}).update(stats)

        self.edit("search online", mutate, view_hint={"tab": TAB_PROFILE, "season": season})
        self.refresh_all()
        self.shell.footer.set_status("Applied fields from online search (Ctrl+Z to undo)", GREEN)

    # ── identity pane (above the season/tabs/preview row, not the list) ───
    def _build_identity_pane(self):
        id_card = Card()
        outer = QVBoxLayout(id_card)
        outer.setContentsMargins(18, 14, 18, 12)
        outer.setSpacing(8)

        if plugin_lookup.available():
            lookup_row = QHBoxLayout()
            lookup_row.addStretch(1)
            self.lookup_btn = compact_button("SEARCH ONLINE…")
            self.lookup_btn.clicked.connect(self._open_bio_search)
            self.focus.register(self.lookup_btn)
            lookup_row.addWidget(self.lookup_btn)
            outer.addLayout(lookup_row)

        # First/last name is the nameplate — the big, primary identity —
        # with everything else (birthdate, in-game name, commentary) a
        # smaller line below rather than competing for the same weight.
        big_row = QHBoxLayout()
        big_row.setSpacing(16)
        self.id_avatar = Avatar(56)
        big_row.addWidget(self.id_avatar, alignment=Qt.AlignVCenter)

        big_font = tracked_font(FONT_DISPLAY, 20, QFont.Bold, 0.3)
        self.first_name = self.register_field("first_name", TextField("First name"), TAB_PROFILE)
        self.first_name.label_width = 88
        self.first_name._value_font = big_font
        self.first_name.setFixedHeight(52)
        self.first_name.edited.connect(lambda v: self._edit_identity("first name", "first_name", v))
        big_row.addWidget(self.first_name, stretch=1)

        self.last_name = self.register_field("last_name", TextField("Last name"), TAB_PROFILE)
        self.last_name.label_width = 88
        self.last_name._value_font = big_font
        self.last_name.setFixedHeight(52)
        self.last_name.edited.connect(lambda v: self._edit_identity("last name", "last_name", v))
        big_row.addWidget(self.last_name, stretch=1)
        outer.addLayout(big_row)

        small_row = QHBoxLayout()
        small_row.setSpacing(16)
        small_row.addSpacing(56 + 16)   # align under the name fields, past the avatar

        self.birthdate = self.register_field(
            "birthdate", TextField("Birthdate", placeholder="YYYY/MM/DD",
                                   validator=normalise_birthdate), TAB_PROFILE)
        self.birthdate.label_width = 88
        self.birthdate.edited.connect(lambda v: self._edit_identity("birthdate", "birthdate", v))
        small_row.addWidget(self.birthdate, stretch=1)

        self.display_name = self.register_field(
            "display_name", TextField("In-game name", max_bytes=14), TAB_PROFILE)
        self.display_name.label_width = 98
        self.display_name.edited.connect(lambda v: self._edit_identity("in-game name", "display_name", v))
        small_row.addWidget(self.display_name, stretch=1)

        self.commentary = self.register_field(
            "commentary", NumberField("Commentary id", 0, 65535), TAB_PROFILE)
        self.commentary.set_hint("game uses 0")
        self.commentary.label_width = 98
        self.commentary.edited.connect(lambda v: self._edit_identity("commentary id", "commentary", v))
        small_row.addWidget(self.commentary, stretch=1)
        outer.addLayout(small_row)

        self.shell.identity_layout.addWidget(id_card)

    # ── seasons pane (narrow column left of the tabs) ──────────────────────
    def _build_season_pane(self):
        mid = self.shell.mid_layout
        seasons_card = Card()
        sv = QVBoxLayout(seasons_card)
        sv.setContentsMargins(10, 12, 10, 10)
        sv.setSpacing(6)
        head = QHBoxLayout()
        head.addWidget(eyebrow_label("seasons", color=FG_TERTIARY, size=11))
        head.addStretch(1)
        self.season_add_btn = compact_button("+ ADD")
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
        mid.addWidget(seasons_card, stretch=1)

        for w in (self.season_add_btn, self.season_menu_btn, self.season_list):
            self.focus.register(w)

        # A visible thread from "which season is picked" to "whose data this
        # is": the pill's colour is the same accent the active row in the
        # seasons list uses, and it sits right where that season's tab
        # content begins.
        self.season_row = QWidget()
        ctx = QHBoxLayout(self.season_row)
        ctx.setContentsMargins(0, 0, 0, 10)
        ctx.setSpacing(8)
        self.season_pill = Badge("SEASON —", ACCENT, filled=True)
        ctx.addWidget(self.season_pill)
        ctx.addStretch(1)
        self.shell.right_layout.insertWidget(0, self.season_row)

    # ── 3D preview pane (fixed width, always visible) ──────────────────────
    def _build_preview_pane(self):
        from ui.player_stage import KitStage
        self._preview_card = Card()
        self._preview_layout = QVBoxLayout(self._preview_card)
        self._preview_layout.setContentsMargins(14, 14, 14, 12)
        self._preview_layout.setSpacing(8)
        self._preview_layout.addWidget(eyebrow_label("3d preview", color=FG_TERTIARY, size=11))
        self.stage = KitStage(default_yaw=15.0)
        self._preview_layout.addWidget(self.stage, stretch=1)
        self.shell.preview_layout.addWidget(self._preview_card, stretch=1)

    def borrow_stage(self, new_parent):
        """Pull the 3D stage out of its normal spot in the preview pane for
        a modal that wants to show it undimmed beside itself (the head
        picker, so a candidate can be compared against a full-window-dimmed
        backdrop without the stage itself going dark too) — see
        reclaim_stage() to put it back."""
        self._preview_layout.removeWidget(self.stage)
        self.stage.setParent(new_parent)
        self.stage.show()
        return self.stage

    def reclaim_stage(self):
        self.stage.setParent(self._preview_card)
        self._preview_layout.addWidget(self.stage, stretch=1)

    # ── record plumbing ──────────────────────────────────────────────────
    GROUP_LABEL = "Team"
    SORTS = [("name", "name"), ("ovr", "overall"), ("issues", "most issues")]

    def list_rows(self):
        team_names = {}
        for tid, seasons in self.ds.teams.items():
            for info in seasons.values():
                for p in info.get("players", []):
                    team_names.setdefault(str(p), set()).add(info.get("name", tid))
        rows = []
        for pid, record in self.ds.players.items():
            stats = record.get("stats") or {}
            latest = sorted(stats)[-1] if stats else None
            block = stats.get(latest, {}) if latest else {}
            issues = check_player_detailed(record, latest, config.mod_data_directory) if latest else []
            errors = sum(1 for _, _, s in issues if s == "error")
            pos = block.get("position1", "")
            short = POSITION_SHORT.get(pos, pos[:3].upper() if pos else "—")
            ovr = position_overall(block) if block else None
            teams = sorted(team_names.get(pid, []))
            rows.append({
                "id": pid, "text": record.get("display_name") or record.get("last_name") or pid,
                "tag": f"{errors} ERR" if errors else f"{short}  {ovr if ovr is not None else ''}",
                "color": DANGER_LITE if errors else FG_TERTIARY,
                "search": f"{pid} {record.get('first_name', '')} {record.get('last_name', '')} "
                          f"{pos.replace('_', ' ')} {short} {' '.join(teams)}",
                "errors": errors,
                "issues": sum(1 for _, _, s in issues if s != "info"),
                "group": teams[0] if teams else "", "groups": teams,
                "sort": {"ovr": ovr},
            })
        return rows

    def bulk_actions(self):
        from app.game_data import POSITION_ALIASES
        from app import appearance as A
        generic = skin = boots = 0
        for record in self.ds.players.values():
            for block in (record.get("stats") or {}).values():
                if any(block.get(k) in POSITION_ALIASES for k in ("position1", "position2", "position3")):
                    generic += 1
                tone = str(block.get("skin_tone") or "")
                if tone and A.normalize_tone(tone) and A.normalize_tone(tone) != tone:
                    skin += 1
                if A.boot_kind(block.get("boot_style")) == "invalid":
                    boots += 1
        return [("positions", "Rewrite generic positions (flanker → openside flanker…)", generic),
                ("skin", "Write numeric skin tones as names (“2” → dark-med)", skin),
                ("boots", "Reset boot styles the game can't use to style 0", boots)]

    def run_bulk_action(self, key):
        from app.game_data import POSITION_ALIASES, _load_json, _write_json
        count = dict((k, n) for k, _, n in self.bulk_actions()).get(key, 0)

        def fix(block):
            if key == "positions":
                for k in ("position1", "position2", "position3"):
                    if block.get(k) in POSITION_ALIASES:
                        block[k] = POSITION_ALIASES[block[k]]
            elif key == "skin":
                from app import appearance as A
                tone = A.normalize_tone(block.get("skin_tone"))
                if tone and tone != block.get("skin_tone"):
                    block["skin_tone"] = tone
            elif key == "boots":
                from app import appearance as A
                if A.boot_kind(block.get("boot_style")) == "invalid":
                    block["boot_style"] = "0"

        def go():
            by_file = {}
            for pid, path in self.ds.players_file_path.items():
                by_file.setdefault(path, []).append(pid)
            written = 0
            try:
                for path, pids in by_file.items():
                    data = _load_json(path)
                    if not isinstance(data, dict):
                        continue
                    for pid in pids:
                        if pid in data:
                            for block in (data[pid].get("stats") or {}).values():
                                fix(block)
                            self.ds.players[pid] = copy.deepcopy(data[pid])
                    _write_json(path, data)
                    written += 1
            except SaveError as e:
                self.shell.footer.set_status(f"Bulk fix failed: {e}", DANGER_LITE)
                return
            if self.record_id:
                self.open_record_keep_view(self.record_id)
            self.reload_list()
            self.shell.footer.set_status(f"Fixed {count} season block(s) in {written} file(s)", GREEN)

        what = {"positions": "generic positions become the roster position they most likely meant "
                             "(flanker → openside flanker, prop → loosehead prop…)",
                "skin": "a numeric skin tone is written as the name the game reads it as",
                "boots": "a boot style the game can't use (10 or more, or a missing image) "
                         "becomes style 0"}.get(key, "")
        self.guard_dirty(lambda: self.confirm(
            f"Fix {count} season block(s)?",
            f"In every player file, {what}. Files are saved immediately (a .bak of each original "
            f"is kept on first save).", "FIX AND SAVE", go))

    def load_record(self, pid):
        record = self.ds.players.get(pid)
        return copy.deepcopy(record) if record is not None else None

    def on_record_opened(self):
        seasons = sorted((self.session.working.get("stats") or {}))
        if self.season not in seasons:
            self.season = seasons[-1] if seasons else None

    def stats(self):
        if self.session is None or not self.season:
            return {}
        return (self.session.working.get("stats") or {}).get(self.season) or {}

    def set_season(self, season):
        stats = (self.session.working.get("stats") or {}) if self.session else {}
        if season in stats and season != self.season:
            self.season = season
            self.refresh_all()

    def current_view_hint(self):
        return {"season": self.season, "tab": self.shell.tabs.index()}

    def apply_view_hint(self, hint):
        if not hint:
            return
        season = hint.get("season")
        if season and season in ((self.session.working.get("stats") or {}) if self.session else {}):
            self.season = season
        super().apply_view_hint(hint)

    def refresh_view(self):
        stats = self.session.working.get("stats") or {}
        if self.season not in stats:
            self.season = sorted(stats)[-1] if stats else None
        self._refresh_identity()
        self._refresh_seasons(stats)
        self.issues = self.collect_issues()
        if self.season is None:
            self.season_row.hide()
            self.shell.tabs.hide()
            self.shell.stack.setCurrentWidget(self._no_season_page)
            self.refresh_stage()
            return
        self.season_row.show()
        self.shell.tabs.show()
        self.shell.stack.setCurrentIndex(self.shell.tabs.index())
        for tab in self.tabs:
            tab.refresh()
        self.refresh_stage()

    def _refresh_identity(self):
        """Record-level fields — the same in every season, so they live in
        the identity pane above the season/tabs/preview row rather than in
        any one tab. See TAB_TITLES/_build_identity_pane."""
        record = self.session.working
        first = (record.get("first_name") or "")[:1]
        last = (record.get("last_name") or record.get("display_name") or "")[:1]
        self.id_avatar.set_initials(first + last)

        self.first_name.set_value(record.get("first_name", ""))
        self.last_name.set_value(record.get("last_name", ""))
        if not record.get("first_name") and not record.get("last_name"):
            hint_first, hint_last = _first_last_default(record)
        else:
            hint_first, hint_last = "", ""
        self.first_name.set_hint(hint_first)
        self.last_name.set_hint(hint_last)
        self.birthdate.set_value(record.get("birthdate", ""))
        self.display_name.set_value(record.get("display_name", ""))
        self.display_name.set_hint(_display_name_default(record))
        self.commentary.set_value(record.get("commentary", ""))

    def _refresh_seasons(self, stats):
        self.season_pill.set_text(
            f"SEASON {season_label(self.season)}" if self.season else "SEASON —")
        items = []
        for s in sorted(stats):
            block = stats[s]
            pos = block.get("position1", "")
            short = POSITION_SHORT.get(pos, pos[:3].upper() if pos else "—")
            ovr = position_overall(block)
            items.append((s, season_label(s), f"{short}  {ovr}" if ovr is not None else short,
                         FG_TERTIARY, False))
        self.season_list.set_items(items, keep_data=self.season)
        self.season_list.set_selected(self.season)

    # ── 3D preview ───────────────────────────────────────────────────────
    def refresh_stage(self, preview_face=_NO_PREVIEW):
        """Rebuild the always-visible 3D preview from the current season's
        appearance. `preview_face` overrides the stored `face` value without
        touching the record — same format either way (a stock id, a custom
        .big path, or blank/None for generic) — used by the head picker to
        show a candidate live while it's still just being browsed; omit it
        to show the real stored face."""
        if self.session is None or self.season is None:
            self.stage.set_placeholder("NO SEASON")
            self._stage_key = None
            return
        stats = self.stats()
        mod = config.mod_data_directory
        self.stage.set_body(stats.get("height"), stats.get("weight"))
        front, back_path = stock_kit_paths(os.path.join(config.temp_directory, "stock_kit"))
        front, back_path = front or "", back_path or ""

        face = str(stats.get("face") or "") if preview_face is _NO_PREVIEW else str(preview_face or "")
        if face.endswith(".big"):
            head = os.path.join(mod, face)
        elif face.isdigit():
            head = stock_head_path(face, os.path.join(config.temp_directory, "stock_heads"))
        else:
            head = None

        boot = str(stats.get("boot_style") or "")
        boots = A.abs_path(mod, boot) if A.boot_kind(boot) == "image" else None
        boots_index = int(boot) if boot.isdigit() else 0

        resolved = A.resolve(stats, mod)
        skin_path, skin_entry = skin_compose(resolved, os.path.join(config.temp_directory, "skin_previews"),
                                             force=True)

        finger_tape = str(stats.get("finger_tape") or "none")
        wrist_tape = str(stats.get("wrist_tape") or "none")
        thigh_tape = str(stats.get("tight_tape") or "none")
        socks = str(stats.get("socks") or "down")     # the roster's default: only "up" is up

        key = (front, back_path, head, boots, boots_index, skin_path, skin_entry, finger_tape,
               wrist_tape, thigh_tape, socks)
        if key == self._stage_key:
            return
        self._stage_key = key
        try:
            self.stage.update_kit(None, front, back_path, None,
                                  head_path=head, boots_path=boots, boots_index=boots_index,
                                  skin_entry=skin_entry, skin_path=skin_path,
                                  finger_tape=finger_tape, wrist_tape=wrist_tape,
                                  thigh_tape=thigh_tape, socks=socks)
        except Exception as e:
            log.warning(f"preview failed: {e}")

    def preview_face(self, face_value):
        """Live-preview a candidate head (stock id or custom .big path) on
        the 3D stage without committing it — see FacePicker's on_preview/
        on_cancel."""
        self.refresh_stage(preview_face=face_value)

    def collect_issues(self):
        if self.session is None or not self.season:
            return [("stats", "this player has no season", "error")] if self.session else []
        issues = check_player_detailed(self.session.working, self.season,
                                       config.mod_data_directory)
        sources = self.ds.players_sources.get(self.record_id, [])
        if len(sources) > 1:
            issues.append(("record",
                           f"also defined in {', '.join(os.path.basename(s) for s in sources[:-1])}"
                           f" — only {os.path.basename(sources[-1])} is used", "warn"))
        return issues

    def tab_for_issue(self, key):
        key = key.split(".")[0]          # "skin_overlay.2" belongs to its field
        if key in ("crashball", "gap_defense", "special_ability") or key.startswith("ss_"):
            return TAB_SKILLS
        if key in APPEARANCE_KEYS:
            return TAB_APPEARANCE
        if key in PROFILE_KEYS or key == "stats":
            return TAB_PROFILE
        return TAB_RATINGS

    def write_record(self):
        path = self.ds.players_file_path.get(self.record_id)
        save_player(path, self.record_id, self.session.working)
        self.ds.players[self.record_id] = copy.deepcopy(self.session.working)
        return f"Saved {os.path.basename(path)}"

    def after_save(self):
        self.ds.events.player_changed.emit(self.record_id)

    def header_state(self):
        # No player info up here any more — name, birthdate and commentary
        # live in the identity pane instead (see _build_identity_pane/
        # _refresh_identity). The header is now the same regardless of
        # which player is open.
        path = self.ds.players_file_path.get(self.record_id, "")
        return {
            "eyebrow": "",
            "title": "Player Editor",
            "subtitle": "",
            "chips": [],
            "pixmap": None,
            "initials": "",
            "target": f"→ {os.path.basename(path)}" if path else "",
        }

    def tab_hints(self, focused):
        # The mid pane (identity + seasons) isn't part of any tab page, but
        # the base hint bar still asks the CURRENTLY ACTIVE tab for hints
        # whenever focus isn't in the search list — so before this, tabbing
        # into "In-game name" or the seasons list while on, say, Ratings
        # showed Ratings' own hints (or nothing), never anything about the
        # widget actually focused. Handle the mid pane's own widgets first;
        # identity fields reuse the exact hints ProfileTab already gives the
        # same field types, since it's the same widgets, just relocated.
        if focused is self.season_list:
            return [("↕", "browse"), ("A", "load season")]
        if focused in (self.season_add_btn, self.season_menu_btn):
            return [("A", "open")]
        if isinstance(focused, NumberField):
            return [("0-9", "type"), ("←→", "adjust"), ("Del", "clear")]
        if isinstance(focused, TextField):
            return [("A", "edit")]
        return self.tabs[self.shell.tabs.index()].hints(focused)

    def _external_change(self):
        if self.isVisible() and self.session is not None:
            self.refresh_all()

    def aux_action(self, focused):
        if isinstance(focused, RatingField) and focused.key in self.tabs[TAB_RATINGS].fields:
            return self.tabs[TAB_RATINGS].copy_previous_value(focused)
        return False

    # ── cross-navigation ─────────────────────────────────────────────────
    def open_team(self, tid, season=None, shirt=None):
        if self._open_team_cb is None:
            self.shell.footer.set_status("Open the team editor from Tools to edit teams", FG_SECONDARY)
            return
        self.guard_dirty(lambda: self._open_team_cb(tid, season, shirt))

    def show_player(self, pid, season=None):
        """Entry point used by the team editor's "edit player"."""
        def go():
            if pid != self.record_id:
                self.open_record(pid)
            stats = (self.session.working.get("stats") or {}) if self.session else {}
            if season in stats:
                self.set_season(season)
            self.shell.tabs.set_index(TAB_PROFILE)
        self.guard_dirty(go)

    # ── seasons ──────────────────────────────────────────────────────────
    def season_action(self, action):
        if self.session is None:
            return
        stats = self.session.working.get("stats") or {}
        if action in ("add", "duplicate"):
            year = NumberField("Year", lo=1900, hi=2100, allow_blank=False)
            team_seasons = sorted({s for m in self.ds.memberships(self.record_id) for s in [m[2]]}
                                  - set(stats))
            all_seasons = sorted(set(self.ds.seasons()) - set(stats))
            suggestion = (team_seasons or all_seasons or [str(max(int(s) for s in stats) + 1)
                                                          if stats else "2026"])[0]
            year.set_value(suggestion)
            source = ChoiceField("Start from", sorted(stats), allow_blank=True,
                                 blank_label="Blank season (all ratings 50)",
                                 display=lambda s: f"Copy of {season_label(s)}")
            source.set_value(self.season if action == "duplicate" else (sorted(stats)[-1] if stats else ""))
            hint = ("Squads that list this player in a season he doesn't have fall back to the "
                    "nearest season's ratings.")
            if team_seasons:
                hint += (f" Squad seasons without ratings: "
                        f"{', '.join(season_label(s) for s in team_seasons)}.")

            def done(role):
                self._dialog = None
                if role != "ok":
                    return
                y = year.value()
                try:
                    probe = copy.deepcopy(self.session.working)
                    P.add_season(probe, y, source.value() or None)
                except ValueError as e:
                    self.shell.footer.set_status(str(e), DANGER_LITE)
                    return
                src = source.value() or None
                self.edit(f"add season {season_label(y)}", lambda r: P.add_season(r, y, src),
                          view_hint={"season": y, "tab": self.shell.tabs.index()})
                self.season = y
                self.refresh_all()
                self.shell.footer.set_status(
                    f"Season {season_label(y)} added" + (f" from {season_label(src)}" if src else " blank"),
                    GREEN)

            self.show_dialog(FormDialog(self, "Add season" if action == "add" else "Duplicate season",
                                        hint, {"year": year, "source": source},
                                        [("CANCEL", "neutral", "cancel"),
                                         ("ADD SEASON", "primary", "ok")], done))
        elif action == "delete":
            if len(stats) <= 1:
                self.shell.footer.set_status("A player needs at least one season", DANGER_LITE)
                return
            season = self.season
            users = [f"{m[1]} {season_label(m[2])}" for m in self.ds.memberships(self.record_id)
                    if m[2] == season]
            extra = (f" {', '.join(users)} will fall back to another season's ratings." if users else "")
            self.confirm(f"Delete season {season_label(season)}?",
                         f"Ratings, positions and appearance for {season_label(season)} are removed."
                         f"{extra} Ctrl+Z undoes until you save.", "DELETE SEASON",
                         lambda: self._delete_season(season))

    def _delete_season(self, season):
        self.edit(f"delete season {season_label(season)}", lambda r: P.delete_season(r, season),
                  view_hint={"season": season, "tab": self.shell.tabs.index()})
        self.season = sorted(self.session.working["stats"])[-1]
        self.refresh_all()

    # ── create / duplicate / delete ──────────────────────────────────────
    def new_record(self):
        self._player_dialog(duplicate=False)

    def duplicate_record(self):
        if self.session is not None:
            self._player_dialog(duplicate=True)

    def _player_dialog(self, duplicate):
        files = [f for f in self.ds.players_files()]
        name = TextField("In-game name", max_bytes=14)
        target = ChoiceField("Save into", files, allow_blank=False,
                             display=lambda p: os.path.basename(p))
        current_path = self.ds.players_file_path.get(self.record_id) if self.record_id else None
        if current_path in files:
            target.set_value(current_path)
        elif files:
            counts = {}
            for path in self.ds.players_file_path.values():
                counts[path] = counts.get(path, 0) + 1
            target.set_value(max(files, key=lambda f: counts.get(f, 0)))
        year = NumberField("First season", lo=1900, hi=2100, allow_blank=False)
        year.set_value(self.season or (self.ds.seasons() or ["2026"])[-1])
        position = ChoiceField("Primary position", POSITIONS, allow_blank=False, display=position_name)
        position.set_value("centre")
        fields = {"name": name, "target": target}
        if duplicate:
            name.set_value(P.duplicate_record(self.session.working)["display_name"])
        else:
            fields["year"] = year
            fields["position"] = position

        def done(role):
            self._dialog = None
            if role != "ok":
                return
            try:
                self._create_player(name.value().strip(), target.value(), year.value(),
                                    position.value(), duplicate)
            except (ValueError, SaveError, OSError) as e:
                self.shell.footer.set_status(f"Could not create player: {e}", DANGER_LITE)

        self.show_dialog(FormDialog(
            self, "Duplicate player" if duplicate else "New player",
            ("A copy of every season of this player under a new id. Squads are not changed."
             if duplicate else "The player is written to the chosen file straight away."),
            fields, [("CANCEL", "neutral", "cancel"), ("CREATE", "primary", "ok")], done))

    def _create_player(self, name, path, year, position, duplicate):
        if not name:
            raise ValueError("the player needs an in-game name")
        if not path:
            raise ValueError("choose a players file")
        pid = P.allocate_player_id(self.ds.players_files(), self.ds.players)
        if duplicate:
            record = copy.deepcopy(self.session.working)
            record["display_name"] = P.truncate_bytes(name)
        else:
            record = P.blank_player(P.truncate_bytes(name), year, position)
        from app.game_data import add_player
        add_player(path, pid, record)
        self.ds.register_player(pid, record, path)
        self.reload_list()

        def go():
            self.open_record(pid)
            self.shell.footer.set_status(f"Created {name} · id {pid} in {os.path.basename(path)}", GREEN)
        self.guard_dirty(go)

    def delete_record(self):
        if self.record_id is None:
            return
        pid = self.record_id
        name = self.session.working.get("display_name", pid)
        memberships = self.ds.memberships(pid)
        remove = SegmentField("Also remove from squads", ["yes", "no"])
        remove.set_value("yes" if memberships else "no")
        sources = self.ds.players_sources.get(pid, [])
        text = (f"{name} (id {pid}) is removed from "
                f"{', '.join(os.path.basename(s) for s in sources) or 'its file'}.")
        if memberships:
            text += (f" He is listed in {len(memberships)} squad(s): "
                     + ", ".join(f"{m[1]} {m[2]} #{m[3]}" for m in memberships[:5])
                     + ("…" if len(memberships) > 5 else "")
                     + ". Removing him shifts later shirts up and clears roles he holds.")

        def done(role):
            self._dialog = None
            if role != "ok":
                return
            try:
                files, teams, skipped = P.delete_everywhere(self.ds, pid, remove.value() == "yes")
            except (SaveError, OSError) as e:
                self.shell.footer.set_status(f"Delete failed: {e}", DANGER_LITE)
                return
            for tid in teams:
                self.ds.events.team_changed.emit(tid)
            if self.session is not None:
                self.session.revert()
            self.ds.unregister_player(pid)
            self.record_id = None
            self.session = None
            self.reload_list()
            if self.list.count():
                self.list.set_highlight(0)
                self.open_record(self.list.highlighted_data())
            self.shell.footer.set_status(
                f"Deleted {name}" + (f" and removed him from {len(teams)} team file(s)" if teams else ""),
                FG_SECONDARY)

        fields = {"remove": remove} if memberships else {}
        self.show_dialog(FormDialog(self, f"Delete {name}?", text, fields,
                                    [("CANCEL", "neutral", "cancel"), ("DELETE PLAYER", "danger", "ok")],
                                    done))
