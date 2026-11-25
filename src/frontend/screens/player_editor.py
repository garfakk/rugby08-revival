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
from PyQt5.QtWidgets import QApplication, QVBoxLayout, QHBoxLayout, QGridLayout, QWidget

from app import appearance as A
from app import player_ops as P
from app.game_data import (
    check_player_detailed, save_player, save_target, saves_to_user_edits, SaveError, EditsOffError, POSITIONS, SHIRT_POSITIONS,
)
from app.ratings import position_overall
from app.season import season_label
from app import plugin_lookup
from backend.mod_utils import stock_head_path, stock_kit_paths
from ui.team_sheet import STAR, STAR_COLOR, is_star
from screens.editor_base import EditorScreen
from screens.player_batch import BatchPanel
from screens.player_tabs import (
    ProfileTab, RatingsTab, AppearanceTab, SkillsTab, TeamsTab, TAB_PROFILE, TAB_RATINGS,
    TAB_APPEARANCE, TAB_SKILLS, TAB_TEAMS,
    position_name, normalise_birthdate,
)
from ui import motion
from ui.broadcast import Card, display_label, eyebrow_label, tracked_font
from ui.editor_kit import (
    Avatar, Badge, FormDialog, ConfirmDialog, TextField, NumberField, ChoiceField,
    SegmentField, RatingField, Note, compact_button, open_season_menu, ScopeCheck, LOAD_FILES,
)
from ui.form import SearchList
from ui.skin_preview import compose as skin_compose
from ui.team_sheet import POSITION_SHORT
from ui.theme import (
    ACCENT, GREEN, DANGER_LITE, INFO, FG_SECONDARY, FG_TERTIARY, T_LABEL, FONT_DISPLAY,
)
from shared.config import config
from shared import commentary, shirt_names
from ui.sound_preview import SoundPreview

from shared.log import get_logger

log = get_logger(__name__)


def clip_file_name(name):
    """A name as it goes in a clip's file name: plain letters, "_" for spaces."""
    import re
    import unicodedata
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]+", "_", plain).strip("_") or "Name"

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


def _surname_key(record):
    """Players are listed by surname ("Stuart, Will"), not by the initial
    their in-game name starts with."""
    last = (record.get("last_name") or "").strip()
    first = (record.get("first_name") or "").strip()
    if not last:
        first, last = _first_last_default(record)
    return f"{last} {first}".strip()


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
    EDIT_KIND = "players"
    LIST_PLACEHOLDER = "name, id, position, team"
    MID_PANE = True
    COMPACT_HEADER = True
    FIT_PANES = True
    PREVIEW_TABS = (TAB_APPEARANCE,)
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
        self._build_batch()
        ds.events.team_changed.connect(lambda _: self._external_change())
        ds.events.team_removed.connect(lambda _: self._external_change())

        # Per-player list facts (issues, position, overall), computed once
        # and kept while the record object is the same one — every save
        # replaces the record, so an edit is a miss. Filled in the background
        # (prewarm / _revalidate) so opening the editor doesn't pay for
        # thousands of players at once.
        self._row_cache = {}       # pid -> (record, facts)
        self._warm_job = None
        self._warm_timer = QTimer(self)
        # Paced, not back to back: a tick every frame or so leaves the event
        # loop free in between, and none at all while something animates
        # (one player's head check alone can take tens of ms).
        self._warm_timer.setInterval(15)
        self._warm_timer.timeout.connect(self._warm_step)

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

    # ── batch mode: many players changed at once ─────────────────────────
    def _build_batch(self):
        self.batch = BatchPanel(self)
        self.select_btn = compact_button("SELECT")
        self.select_btn.setToolTip("Change many players at once")
        self.select_btn.clicked.connect(lambda: self.enter_batch())
        # beside FILTERS: the row above has no room left in a narrow window
        lay = self.shell.list_layout
        at = lay.indexOf(self.filters_toggle)
        lay.removeWidget(self.filters_toggle)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(self.filters_toggle, stretch=1)
        row.addWidget(self.select_btn, stretch=1)
        lay.insertLayout(at, row)
        self.focus.register(self.select_btn)

        self.batch_bar = QWidget()
        bar = QHBoxLayout(self.batch_bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(6)
        self.all_btn = compact_button("ALL")
        self.all_btn.setToolTip("Tick every player the list shows")
        self.all_btn.clicked.connect(self.list.check_shown)
        self.none_btn = compact_button("NONE")
        self.none_btn.clicked.connect(lambda: self.list.set_checked(()))
        self.done_btn = compact_button("DONE", "primary")
        self.done_btn.clicked.connect(self.leave_batch)
        for b in (self.all_btn, self.none_btn, self.done_btn):
            bar.addWidget(b)
            self.focus.register(b)
        self.shell.list_layout.insertWidget(1, self.batch_bar)
        self.batch_bar.hide()
        self.list.checked_changed.connect(self._on_checked)
        self.list.multi_requested.connect(self._on_multi_click)

    def _on_checked(self):
        if self.batch.active:
            n = len(self.list.checked_data())
            self.none_btn.setEnabled(bool(n))
            self.batch.refresh()

    def _on_multi_click(self, pid):
        """Ctrl / Shift + click on a row: picking starts with the player on
        screen and that one."""
        start = [p for p in (self.record_id, pid) if p]
        self.enter_batch(start)

    def enter_batch(self, checked=None):
        if self.batch.active:
            return

        def go():
            for b in (self.new_btn, self.dup_btn, self.select_btn):
                b.hide()
            self.batch_bar.show()
            self.batch.enter()
            self.list.set_checkable(True, checked if checked is not None
                                    else [self.record_id] if self.record_id else [])
            self.fit_panes()
            self.list.setFocus()
        self.guard_dirty(go)

    def leave_batch(self, then=None):
        if not self.batch.active:
            if then:
                then()
            return

        def go():
            self.batch.leave()
            self.list.set_checkable(False)
            self.batch_bar.hide()
            for b in (self.new_btn, self.dup_btn, self.select_btn):
                b.show()
            if self.record_id is not None and self.record_id not in self.ds.players:
                self.record_id, self.session = None, None
            if self.session is None and self.list.count():
                self.list.set_highlight(0)
                self.open_record(self.list.highlighted_data())
            else:
                self.refresh_all()
            self.fit_panes()
            self.list.setFocus()
            if then:
                then()

        if not self.batch.is_dirty():
            go()
            return

        def choice(role):
            self._dialog = None
            if role == "apply":
                if self.batch.apply():
                    go()
            elif role == "discard":
                go()

        n = len(self.batch.pids())
        self.show_dialog(ConfirmDialog(
            self, "Apply the changes?",
            f"The changes to {n} player{'s' if n != 1 else ''} have not been applied.",
            [("CANCEL", "neutral", "cancel"), ("DISCARD", "danger", "discard"),
             ("APPLY", "primary", "apply")], choice))

    def after_batch(self, pids):
        """Players were rewritten by the batch: the list, the panel and the
        open record (when it is one of them) show the new data."""
        self.reload_list()
        if self.record_id in pids and self.session is not None and not self.session.is_dirty():
            self.session.changed.disconnect(self._on_session_changed)
            self.session.deleteLater()
            self.session = None
            record = self.load_record(self.record_id)
            if record is not None:
                from app.edit_session import EditSession
                self.session = EditSession(record, self)
                self.session.changed.connect(self._on_session_changed)
                self.on_record_opened()
        self.batch.refresh()

    def after_batch_delete(self, pids):
        if self.record_id in pids:
            if self.session is not None:
                self.session.changed.disconnect(self._on_session_changed)
                self.session.deleteLater()
            self.record_id, self.session = None, None
        self.reload_list()
        self.batch.refresh()

    def _edit_identity(self, label, key, value):
        self.edit(label, lambda r: r.__setitem__(key, value), coalesce_key=key,
                 view_hint={"tab": TAB_PROFILE, "field": key})

    # ── commentary name ──────────────────────────────────────────────────
    def _commentary_label(self, value):
        if value == LOAD_FILES:
            return "Load from disk…"
        name = self._commentary_names.get(int(value)) if str(value).isdigit() else None
        return f"{name} ({value})" if name else f"#{value}"

    def _commentary_options(self):
        names = self._commentary_names
        return [LOAD_FILES] + sorted((str(i) for i in names),
                                     key=lambda v: (names[int(v)].lower(), int(v)))

    def _commentary_guess(self):
        """Where the list opens for a player with no clip yet: the first
        clip named like his last name."""
        last = (self.session.working.get("last_name", "") if self.session else "").strip().lower()
        if not last:
            return None
        for v in self.commentary.options:
            if v != LOAD_FILES and self._commentary_names[int(v)].lower().startswith(last):
                return v
        return None

    def _play_commentary(self, value):
        if value and str(value).isdigit():
            self._sound.play(f"commentary_{value}", lambda: commentary.wav_bytes(value))

    def _on_commentary(self, value):
        if value == LOAD_FILES:
            self._show_commentary()             # the stored one until a file is loaded
            QTimer.singleShot(0, self._load_commentary)
            return
        self._edit_identity("commentary", "commentary", value)

    def _show_commentary(self, record=None):
        if record is None:
            record = self.session.working if self.session else {}
        cid = str(record.get("commentary", "") or "").strip()
        self.commentary.set_value("" if cid in ("", "0") else cid)

    def _load_commentary(self):
        """A recording from disk becomes this player's commentary name: kept
        in the user's mod data as <id>_<last name>.wav, added to the game at
        the next match (backend/commentary_deploy.py)."""
        from PyQt5.QtWidgets import QFileDialog
        from app import disk_import
        from shared import commentary_audio
        from ui.editor_kit import load_from_disk
        start = getattr(load_from_disk, "last_dir", "") or os.path.expanduser("~")
        src, _ = QFileDialog.getOpenFileName(self, "Commentary recording", start,
                                             "Recordings (*.wav)")
        if not src or self.session is None:
            return
        load_from_disk.last_dir = os.path.dirname(os.path.normpath(src))
        try:
            commentary_audio.samples(src)
        except ValueError as e:
            ConfirmDialog(self, "Recording not usable", str(e).capitalize() + ".",
                          [("OK", "primary", "ok")], lambda _r: None, cancel_role="ok")
            return
        record = self.session.working
        said = record.get("last_name") or os.path.splitext(os.path.basename(src))[0]
        cid = commentary.next_id()
        dst = os.path.join(commentary.custom_folder(), f"{cid:04d}_{clip_file_name(said)}.wav")
        try:
            disk_import.copy_into_data(src, dst)
        except (OSError, ValueError) as e:
            ConfirmDialog(self, "Could not load the recording", str(e),
                          [("OK", "primary", "ok")], lambda _r: None, cancel_role="ok")
            return
        self._commentary_names = commentary.names()
        self.commentary.set_options(self._commentary_options())
        self._edit_identity("commentary", "commentary", str(cid))

    def _edit_shirt_name(self, value):
        value = (value or "").strip()

        def mutate(r):
            if value:
                r["shirt_name"] = value
            else:
                r.pop("shirt_name", None)      # blank: the generated text, no key in the file
        self.edit("shirt name", mutate, coalesce_key="shirt_name",
                  view_hint={"tab": TAB_PROFILE, "field": "shirt_name"})

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
        # each field goes to the seasons its card's ALL SEASONS box picks
        targets = {k: self.tabs[TAB_PROFILE].target_seasons(k) for k in stats}

        def mutate(r):
            r.update(identity)
            if stats and season:
                for k, v in stats.items():
                    for s in targets[k]:
                        r.setdefault("stats", {}).setdefault(s, {})[k] = v

        self.edit("search online", mutate, view_hint={"tab": TAB_PROFILE, "season": season})
        self.refresh_all()
        self.shell.footer.set_status("Fields applied from the online search", GREEN)

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

        # birthdate / in-game name / commentary: one line, two in a narrow
        # window (_place_identity)
        small_row = self._id_grid = QGridLayout()
        small_row.setHorizontalSpacing(16)
        small_row.setVerticalSpacing(8)
        small_row.setContentsMargins(56 + 16, 0, 0, 0)   # under the name fields, past the avatar
        self._id_two_lines = None

        self.birthdate = self.register_field(
            "birthdate", TextField("Birthdate", placeholder="YYYY/MM/DD",
                                   validator=normalise_birthdate), TAB_PROFILE)
        self.birthdate.label_width = 88
        self.birthdate.edited.connect(lambda v: self._edit_identity("birthdate", "birthdate", v))

        self.display_name = self.register_field(
            "display_name", TextField("In-game name", max_bytes=14), TAB_PROFILE)
        self.display_name.label_width = 98
        self.display_name.edited.connect(lambda v: self._edit_identity("in-game name", "display_name", v))

        # What a team with shirt names prints on this player's back instead
        # of the generated text (shared/shirt_names.py).
        self.shirt_name = self.register_field(
            "shirt_name", TextField("Shirt name"), TAB_PROFILE)
        self.shirt_name.label_width = 88
        self.shirt_name.edited.connect(self._edit_shirt_name)
        self.shirt_name.setVisible(False)      # hidden for now; saved overrides still apply

        # The name the commentators say, picked from the game's recorded
        # clips (shared/commentary.py). The list is searchable; each row
        # has a play icon (nothing plays on its own) and an ASSIGN button.
        self._commentary_names = commentary.names()
        self.commentary = self.register_field(
            "commentary", ChoiceField(
                "Commentary", self._commentary_options(),
                display=self._commentary_label, blank_label="none", clearable=True), TAB_PROFILE)
        self.commentary.actions = (LOAD_FILES,)
        self.commentary.label_width = 98
        self.commentary.popup_title = "commentary name"
        self.commentary.off_list_badge = bool(self._commentary_names)
        self.commentary.default_highlight = self._commentary_guess
        self.commentary.searchable = True
        self.commentary.on_play = self._play_commentary
        self.commentary.on_popup_closed = lambda: self._sound.stop()
        self.commentary.edited.connect(self._on_commentary)
        outer.addLayout(small_row)

        self._sound = SoundPreview(self)

        # labels sized to their text, never cut ("First na…")
        for f in (self.first_name, self.last_name, self.birthdate, self.display_name,
                  self.shirt_name, self.commentary):
            f.label_width = f.label_text_width() + 18
        self._place_identity(False)
        self.shell.identity_layout.addWidget(id_card)

    def _place_identity(self, two_lines):
        if two_lines == self._id_two_lines:
            return
        self._id_two_lines = two_lines
        grid = self._id_grid
        for w in (self.birthdate, self.display_name, self.commentary):
            grid.removeWidget(w)
        if two_lines:
            grid.addWidget(self.display_name, 0, 0)
            grid.addWidget(self.birthdate, 0, 1)
            grid.addWidget(self.commentary, 1, 0, 1, 2)
        else:
            grid.addWidget(self.birthdate, 0, 0)
            grid.addWidget(self.display_name, 0, 1)
            grid.addWidget(self.commentary, 0, 2)

    def fit_panes(self):
        super().fit_panes()
        self._place_identity(self.width() < 1400)
        if getattr(self, "batch", None) is not None and self.batch.active:
            # the before / after list, when there is room for it (the
            # title counts the players going up and down either way)
            show = self.width() >= 1250
            self.shell.preview_pane.setVisible(show)
            self.shell.preview_sep.setVisible(show)
            QTimer.singleShot(0, self.batch.fit)

    def save(self, then=None):
        if self.batch.active:
            return self.batch.apply()
        return super().save(then)

    def confirm_revert(self):
        if self.batch.active:
            self.batch.revert_or_undo()
            return
        super().confirm_revert()

    def undo(self):
        if self.batch.active:
            if not self.batch.is_dirty():
                self.batch.undo()
            return
        super().undo()

    def redo(self):
        if not self.batch.active:
            super().redo()

    def request_leave(self):
        if self.batch.active:
            self.leave_batch()
            return
        super().request_leave()

    def request_open(self, record_id):
        if not self.batch.active:
            super().request_open(record_id)

    def switch_tab(self, delta):
        if not self.batch.active:
            super().switch_tab(delta)

    def _focus_first_in_tab(self):
        if self.batch.active:
            self.focus.focus_first(within=self.batch.page)
            return
        super()._focus_first_in_tab()

    def _update_hints(self):
        if not (getattr(self, "batch", None) is not None and self.batch.active) \
                or self._dialog is not None:
            super()._update_hints()
            return
        if self.pane() == "list":
            hints = [("↕", "browse"), ("A", "tick"), ("X", "filter"), ("→", "edit"),
                     ("B", "done")]
        else:
            focused = QApplication.focusWidget()
            hints = self.tab_hints(focused) or [("↕←→", "move"), ("A", "edit")]
            hints = hints + [("B", "list")]
        self.shell.footer.hints.set_hints(hints)

    def _on_focus_changed(self, old, new):
        super()._on_focus_changed(old, new)
        page = self.batch.page if getattr(self, "batch", None) is not None else None
        if page is not None and self.batch.active and new is not None \
                and page.isAncestorOf(new) and new is not page.widget():
            page.ensureWidgetVisible(new, 0, 40)

    def _refresh_chrome(self):
        super()._refresh_chrome()
        if getattr(self, "batch", None) is not None and self.batch.active:
            self.dup_btn.setEnabled(False)
            self.batch.refresh_footer()
        else:
            self.shell.footer.revert_btn.setText("REVERT")

    # ── seasons pane (narrow column left of the tabs) ──────────────────────
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
    EXTRA_FILTERS = [("nationality", "Nationality")]

    def _row_facts(self, pid, record):
        """What the list shows for one player, from the record alone."""
        stats = record.get("stats") or {}
        latest = sorted(stats)[-1] if stats else None
        block = stats.get(latest, {}) if latest else {}
        issues = check_player_detailed(record, latest, config.mod_data_directory) if latest else []
        pos = block.get("position1", "")
        return {
            "errors": sum(1 for _, _, s in issues if s == "error"),
            "issues": sum(1 for _, _, s in issues if s != "info"),
            "pos": pos,
            "short": POSITION_SHORT.get(pos, pos[:3].upper() if pos else "—"),
            "ovr": position_overall(block) if block else None,
            "star": is_star(block),
            "nat": str(block.get("nationality") or "").strip(),
        }

    def _cached_facts(self, pid, record):
        hit = self._row_cache.get(pid)
        if hit is not None and hit[0] is record:
            return hit[1]
        facts = self._row_facts(pid, record)
        self._row_cache[pid] = (record, facts)
        return facts

    # ── background warm-up ───────────────────────────────────────────────
    CHUNK_SECONDS = 0.008      # per timer tick: well inside one frame

    def prewarm(self):
        """Fill the list cache a few players per event-loop turn, so the
        first visit opens on a ready list and the UI never stalls for it."""
        self._start_warm(changed_only=False)

    def _start_warm(self, changed_only):
        players = self.ds.players
        self._warm_job = (iter(list(players.items())), changed_only, [False])
        self._warm_timer.start()

    def _warm_step(self):
        import time
        job = self._warm_job
        if job is None:
            self._warm_timer.stop()
            return
        if motion.animating():
            return
        items, recheck, dirty = job
        end = time.perf_counter() + self.CHUNK_SECONDS
        for pid, record in items:
            if recheck:
                # Asset files can change on disk without the record
                # changing: recompute, and note when the list would differ.
                facts = self._row_facts(pid, record)
                hit = self._row_cache.get(pid)
                if hit is None or hit[0] is not record or hit[1] != facts:
                    dirty[0] = True
                self._row_cache[pid] = (record, facts)
            else:
                self._cached_facts(pid, record)
            if time.perf_counter() > end:
                return
        self._warm_timer.stop()
        self._warm_job = None
        if recheck and dirty[0] and self.isVisible():
            self._quiet_reload()

    def _quiet_reload(self):
        """reload_list without moving anything the user can see: the cursor
        stays on its row and the list keeps its scroll position."""
        bar = self.list.scroll.verticalScrollBar()
        top = bar.value()
        items, search = self.list_items()
        self.list.set_items(items, keep_data=self.list.highlighted_data(), search_text=search)
        bar.setValue(top)

    def list_rows(self):
        team_names = {}
        from app.team_ops import squad_blocks
        for tid, seasons in self.ds.teams.items():
            for info in seasons.values():
                for _vid, block in squad_blocks(info):     # default + competition variants
                    for p in block.get("players", []):
                        team_names.setdefault(str(p), set()).add(info.get("name", tid))
        live = set(self.ds.players)
        for pid in [p for p in self._row_cache if p not in live]:
            del self._row_cache[pid]
        rows = []
        for pid, record in self.ds.players.items():
            f = self._cached_facts(pid, record)
            errors, ovr, pos, short = f["errors"], f["ovr"], f["pos"], f["short"]
            teams = sorted(team_names.get(pid, []))
            rows.append({
                "id": pid, "text": (f"{STAR} " if f["star"] else "")
                                   + (record.get("display_name") or record.get("last_name") or pid),
                "tag": f"{errors} ERR" if errors else f"{short}  {ovr if ovr is not None else ''}",
                "color": DANGER_LITE if errors else FG_TERTIARY,
                "search": f"{pid} {record.get('first_name', '')} {record.get('last_name', '')} "
                          f"{pos.replace('_', ' ')} {short} {' '.join(teams)}"
                          + (" star" if f["star"] else ""),
                "errors": errors,
                "issues": f["issues"],
                "group": teams[0] if teams else "", "groups": teams,
                "sort": {"ovr": ovr},
                "name_key": _surname_key(record),
                "filters": {"nationality": f["nat"]},
            })
        return rows

    def on_show(self):
        super().on_show()
        # The list just opened from the cache; re-check it against the disk
        # (asset files) in the background and refresh it only if it changed.
        QTimer.singleShot(0, lambda: self._start_warm(changed_only=True))

    def on_hide(self):
        if self._warm_job is not None and self._warm_job[1]:
            self._warm_timer.stop()
            self._warm_job = None

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
        if self.batch.active:
            self.batch.refresh()
            return
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
        self.shirt_name.set_value(record.get("shirt_name", ""))
        self._show_commentary(record)

    def _refresh_seasons(self, stats):
        items = []
        for s in sorted(stats):
            block = stats[s]
            pos = block.get("position1", "")
            short = POSITION_SHORT.get(pos, pos[:3].upper() if pos else "—")
            ovr = position_overall(block)
            tag = f"{short}  {ovr}" if ovr is not None else short
            star = is_star(block)
            items.append((s, season_label(s), f"{STAR} {tag}" if star else tag,
                         STAR_COLOR if star else FG_TERTIARY, False))
        self.season_pill.set_text(
            f"SEASON {season_label(self.season)}" if self.season else "NO SEASON")
        self.season_list.set_items(items, keep_data=self.season)
        self.season_list.set_selected(self.season)

    # ── 3D preview ───────────────────────────────────────────────────────
    def refresh_stage(self, preview_face=_NO_PREVIEW, preview_boots=_NO_PREVIEW, preview_skin=None):
        """Rebuild the always-visible 3D preview from the current season's
        appearance. `preview_face` overrides the stored `face` value without
        touching the record — same format either way (a stock id, a custom
        .big path, or blank/None for generic) — used by the head picker to
        show a candidate live while it's still just being browsed; omit it
        to show the real stored face. `preview_boots` does the same for
        `boot_style` (the boots picker's hovered row). `preview_skin` is a whole
        skin texture to wear instead (the tattoo editor's work in progress)."""
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

        boot = str(stats.get("boot_style") or "") if preview_boots is _NO_PREVIEW else str(preview_boots or "")
        boots = A.abs_path(mod, boot) if A.boot_kind(boot) == "image" else None
        boots_index = int(boot) if boot.isdigit() else 0

        resolved = A.resolve(stats, mod)
        skin_path, skin_entry = skin_compose(resolved, os.path.join(config.temp_directory, "skin_previews"),
                                             force=True)
        if preview_skin:
            skin_path = preview_skin

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

    def preview_boots(self, boot_value):
        """Live-preview a candidate boot style (stock number or custom image
        path) on the 3D stage without committing it."""
        self.refresh_stage(preview_boots=boot_value)

    def collect_issues(self):
        if self.session is None or not self.season:
            return [("stats", "this player has no season", "error")] if self.session else []
        issues = check_player_detailed(self.session.working, self.season,
                                       config.mod_data_directory)
        sources = self.ds.players_sources.get(self.record_id, [])
        if len(sources) > 1:
            issues.append(("record",
                           f"also defined in {', '.join(os.path.basename(s) for s in sources[:-1])}"
                           f"; only {os.path.basename(sources[-1])} is used", "warn"))
        return issues

    def tab_for_issue(self, key):
        key = key.split(".")[0]          # "skin_overlay.2" belongs to its field
        if key in ("crashball", "gap_defense", "special_ability", "star_attribute",
                   "hide_star", "star_voice") or key.startswith("ss_"):
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
        return f"Saved to {save_target(path)}"

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
        if isinstance(focused, ScopeCheck):
            return [("A", "edit every season" if not focused.checked else "edit this season only")]
        if isinstance(focused, NumberField):
            return [("0-9", "type"), ("←→", "adjust"), ("SELECT", "clear")]
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
    def open_team(self, tid, season=None, shirt=None, variant=""):
        if self._open_team_cb is None:
            self.shell.footer.set_status("Open the team editor from Tools", FG_SECONDARY)
            return
        self.guard_dirty(lambda: self._open_team_cb(tid, season, shirt, variant))

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
            year = NumberField("Season", lo=1900, hi=2100, allow_blank=False, formatter=season_label)
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
            hint = ("Type the year the season ends in (2026 is 2025-2026). "
                    "Squads using a season this player lacks fall back to the nearest one.")
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
            extra = (f" {', '.join(users)} will use another season's ratings." if users else "")
            self.confirm(f"Delete season {season_label(season)}?",
                         f"Ratings, positions and appearance for {season_label(season)} will be removed."
                         f"{extra}", "DELETE SEASON",
                         lambda: self._delete_season(season))

    def _delete_season(self, season):
        self.edit(f"delete season {season_label(season)}", lambda r: P.delete_season(r, season),
                  view_hint={"season": season, "tab": self.shell.tabs.index()})
        self.season = sorted(self.session.working["stats"])[-1]
        self.refresh_all()

    # ── create / duplicate / delete ──────────────────────────────────────
    def new_record(self):
        if not self.batch.active:
            self._player_dialog(duplicate=False)

    def duplicate_record(self):
        if self.session is not None and not self.batch.active:
            self._player_dialog(duplicate=True)

    def _player_dialog(self, duplicate):
        name = TextField("In-game name", max_bytes=14)
        first = TextField("First name")
        last = TextField("Last name")
        year = NumberField("Season", lo=1900, hi=2100, allow_blank=False, formatter=season_label)
        year.set_value(self.season or (self.ds.seasons() or ["2026"])[-1])
        position = ChoiceField("Position", POSITIONS, allow_blank=False, display=position_name)
        position.set_value((self.stats() or {}).get("position1") or "centre" if self.record_id else "centre")
        level = SegmentField("Level", [k for k, _l, _o in P.LEVELS],
                             display=lambda v: next(lab for k, lab, _o in P.LEVELS if k == v))
        level.set_value("international")
        # the team the new player joins: the one the player on screen plays for
        team_names = {tid: (self.ds.team_seasons(tid).get(max(self.ds.team_seasons(tid)), {}) or {})
                      .get("name", tid) for tid in self.ds.team_ids() if self.ds.team_seasons(tid)}
        team = ChoiceField("Team", sorted(team_names, key=lambda t: team_names[t].lower()),
                           allow_blank=True, blank_label="none", display=lambda t: team_names.get(t, t))
        team.searchable = True
        team.popup_title = "team"
        here = [m[0] for m in self.ds.memberships(self.record_id) if m[2] == self.season] \
            if self.record_id else []
        team.set_value(here[0] if here else "")
        if duplicate:
            fields = {"name": name}
            name.set_value(P.duplicate_record(self.session.working)["display_name"])
        else:
            fields = {"first": first, "last": last, "position": position, "level": level,
                      "team": team, "year": year}

        def done(role):
            self._dialog = None
            if role == "ok":
                run()

        def run():
            try:
                if duplicate:
                    self._duplicate_player(name.value().strip())
                else:
                    self._create_player(first.value(), last.value(), year.value(), position.value(),
                                        level.value(), team.value())
            except EditsOffError:
                self.ask_edits_on(run, replaces=False)
            except (ValueError, SaveError, OSError) as e:
                self.shell.footer.set_status(f"Could not create player: {e}", DANGER_LITE)

        self.show_dialog(FormDialog(
            self, "Duplicate player" if duplicate else "New player",
            "Copies every season under a new id. Squads are unchanged." if duplicate else
            "Ratings start at the level picked, shaped like other players in that position.",
            fields, [("CANCEL", "neutral", "cancel"), ("CREATE", "primary", "ok")], done))

    def _duplicate_player(self, name):
        if not name:
            raise ValueError("the player needs an in-game name")
        path = P.target_players_file(self.ds, self.record_id)
        if not path:
            raise ValueError("there is no players file to save into")
        pid = P.allocate_player_id(self.ds.players_files(), self.ds.players)
        record = copy.deepcopy(self.session.working)
        record["display_name"] = P.truncate_bytes(name)
        from app.game_data import add_player
        add_player(path, pid, record)
        self.ds.register_player(pid, record, path)
        self._open_created(pid, f"Created {name}")

    def _create_player(self, first, last, year, position, level="international", team=""):
        pid = P.create_player(self.ds, first, last, year, position, level=level, near_pid=self.record_id)
        name = self.ds.players[pid]["display_name"]
        note = ""
        if team:
            try:
                shirt = P.add_to_squad(self.ds, pid, team, year)
                tname = self.ds.team_seasons(team)[str(year)].get("name", team)
                note = f" · {tname} #{shirt}"
            except (ValueError, SaveError, OSError, KeyError):
                note = " · not added to the team: it has no squad that season"
        self._open_created(pid, f"Created {name}{note}", season=str(year))

    def _open_created(self, pid, text, season=None):
        self.reload_list()

        def go():
            self.open_record(pid)
            if season:
                self.set_season(season)
            self.shell.footer.set_status(text, GREEN)
        self.guard_dirty(go)

    def delete_record(self):
        if self.record_id is None:
            return
        pid = self.record_id
        name = self.session.working.get("display_name", pid)
        memberships = self.ds.memberships(pid, with_variants=True)
        remove = SegmentField("Also remove from squads", ["yes", "no"])
        remove.set_value("yes" if memberships else "no")
        sources = self.ds.players_sources.get(pid, [])
        text = (f"{name} (id {pid}) will be removed from "
                f"{', '.join(os.path.basename(s) for s in sources) or 'its file'}.")
        if memberships:
            text += (f" Listed in {len(memberships)} squad(s): "
                     + ", ".join(f"{m[1]} {m[2]} #{m[3]}" for m in memberships[:5])
                     + ("…" if len(memberships) > 5 else "")
                     + ". Later shirts move up and the player's roles are cleared.")

        def done(role):
            self._dialog = None
            if role == "ok":
                run()

        def run():
            try:
                files, teams, skipped = P.delete_everywhere(self.ds, pid, remove.value() == "yes")
            except EditsOffError:
                self.ask_edits_on(run, replaces=False)
                return
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
                f"Deleted {name}" + (f" and removed from {len(teams)} team file(s)" if teams else ""),
                FG_SECONDARY)

        fields = {"remove": remove} if memberships else {}
        self.show_dialog(FormDialog(self, f"Delete {name}?", text, fields,
                                    [("CANCEL", "neutral", "cancel"), ("DELETE PLAYER", "danger", "ok")],
                                    done))
