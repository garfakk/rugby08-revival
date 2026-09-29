"""
screens/match_setup.py — Match Setup screen (broadcast redesign)
====================================================================
Replaces team_selection.py's TeamSelectionWidget. Three columns — home /
match / away — built on MatchConfig/DataStore instead of QComboBox state.
The backend contract (_build_match_data) is unchanged: see
app/match_data_builder.py, ported verbatim.
"""
import os
import random
import threading
from copy import deepcopy

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QStackedWidget, QFrame,
    QGraphicsOpacityEffect, QScrollArea,
)
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import (
    Qt, QPoint, QRect, QEasingCurve, QPropertyAnimation, QParallelAnimationGroup, QTimer,
)

from backend import game_specific_variables as gsv
from backend.mod_utils import stock_head_path
from shared.config import config
from shared.user_prefs import user_prefs
from app.screen_base import Screen
from app.input import Action, KEYMAP
from app.state import DataStore, MatchConfig, TeamSlot
from app.match_data_builder import build_match_data
from app.game_data import SNOW_INTENSITY_MAX, WIND_POWER_MAX
from app.season import season_label
from ui import StyledButton
from ui.player_stage import KitStage, _try_load_model
from ui.dropdown import DropdownRow
from ui.atmosphere import AtmosphereWidget
from ui.pixmap_utils import trim_transparent
from ui.side_panel import SidePanelSlide
from ui.broadcast import (
    Card, SelectorRow, TeamNamePicker, HintBar,
    page_header, eyebrow_label, display_label,
)
from ui.theme import (
    BG_PANEL, BORDER,
    ACCENT, HOME_TINT, AWAY_TINT,
    FG_MUTED, BTN_HEIGHT,
)
from screens.squad_editor import SquadEditorScreen


# Degrees each column's 3D player turns toward the centre by default —
# home turns right, away turns left, so they read as facing off rather
# than each looking straight out of the screen.
FACE_YAW = 18.0

# How long the kickoff sequence's run-off takes. Deliberately long: this
# time is hidden real backend work (see _start_kickoff_sequence) — the
# longer the run, the more of the game's slow prep steps finish before the
# loading screen is ever shown, which is what actually fixes a loading bar
# that otherwise visibly stalls partway through.
WALKOFF_MS = 2200
ADVANCED_PANEL_W = 520   # slide-over width; also its travel (see ui/side_panel.py)

# Gap between the players' 3D zoom-in starting and the crest flight kicking
# off, so the crests visibly follow the players rather than moving with them.
CREST_DELAY_MS = 200

# Duration of the loading screen's own fade-in (names, wheel...). Scheduled
# to START early enough that it reaches full opacity exactly when the crest
# flight (which begins CREST_DELAY_MS after zoom-in) lands.
LOADING_FADE_MS = 1200


from shared.log import get_logger

log = get_logger(__name__)


def _load_crest(path: str) -> QPixmap:
    """Full-resolution crest — scaled to the card's current crest box by
    TeamColumn, which sizes it as a share of card height."""
    if path and os.path.exists(path):
        pix = QPixmap(path)
        if not pix.isNull():
            return pix
    return QPixmap()


# The two 3D mannequins are drawn from this pool every time the match setup
# screen opens (see MatchSetupScreen.on_show) instead of always wearing the
# same generic head, so the preview reads as two different players each
# time rather than a fixed pair. Each entry is (face_id, bare-hand skin.fsh
# entry) — face_id is a `playermanager.xml` location value with a
# confirmed skin="1..4" tag, and the tone was verified by decoding the
# actual face texture, not just trusting the tag: one or two real players
# per stock tone (light, light-medium, dark-medium, dark). One light and
# one dark entry also carry a scrum cap (medhairstyle="SCR" in the same
# file), confirmed by rendering — headgear isn't limited to either tone.
MANNEQUIN_POOL = [
    (5535,   "wksk"),   # Ignacio Lobbe        — light, scrum cap
    (4966,   "wksk"),   # Andrew Farrell       — light, no headgear
    (24221,  "lmsk"),   # Chris Masoe          — light-medium
    (16343,  "dmsk"),   # Jonah Lomu           — dark-medium
    (21963,  "dksk"),   # Ayoola Erinle        — dark, no headgear
    (41105,  "dksk"),   # location 41105       — dark, scrum cap
]


class TeamColumn(QWidget):
    """One team card, laid out in three bands: identity (season/competition
    pickers, crest, name), kit (stage + selector), actions (edit squad).
    Crest and kit stage are sized as a share of the card height —
    CREST_SHARE / KIT_SHARE — so the proportions hold at any window size."""

    CREST_SHARE = 0.20
    KIT_SHARE = 0.40   # crest and name share a line, so the kit gets the rest

    def __init__(self, side, tint, screen, parent=None):
        super().__init__(parent)
        self.side = side           # "home" | "away"
        self._head_path = None
        self._skin_entry = None
        self.tint = tint
        self.screen = screen       # back-reference to MatchSetupScreen (data + callbacks)

        # This wrapper is a bare QWidget around the card, normally fully
        # hidden behind it — but the app-wide stylesheet paints every
        # unscoped QWidget with a background, and the kickoff sequence now
        # fades the CARD's own fill to nothing (Card.bg_opacity) so the
        # player stays opaque while the box disappears. Without scoping
        # this wrapper too, that reveals not the atmosphere behind it but
        # this widget's own flat inherited fill — a second, harder-edged
        # box exactly the size of the card, right where the first one used
        # to be.
        self.setObjectName(f"teamColumn{side}")
        self.setStyleSheet(f"QWidget#{self.objectName()} {{ background: transparent; }}")

        self.card = Card(stripe=tint, translucent=True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)

        v = QVBoxLayout(self.card)
        v.setContentsMargins(22, 16, 22, 16)
        v.setSpacing(8)

        # Everything but the 3D stage lives in these two wrapper widgets, so
        # the kickoff sequence can fade "all UI except the players" in one
        # shot per wrapper instead of chasing individual widgets.
        self._chrome_top = QWidget()
        self._chrome_bottom = QWidget()
        # Plain QWidgets pick up the app-wide QSS background (BG_BASE),
        # which is darker than the card and shows as a band over it.
        for i, w in enumerate((self._chrome_top, self._chrome_bottom)):
            w.setObjectName(f"chrome{side}{i}")
            w.setStyleSheet(f"QWidget#{w.objectName()} {{ background: transparent; }}")
        chrome_top_v = QVBoxLayout(self._chrome_top)
        chrome_top_v.setContentsMargins(0, 0, 0, 0)
        chrome_top_v.setSpacing(8)
        chrome_bottom_v = QVBoxLayout(self._chrome_bottom)
        chrome_bottom_v.setContentsMargins(0, 0, 0, 0)
        chrome_bottom_v.setSpacing(8)

        # ── band 1: identity ────────────────────────────────────────────
        # Side label left, the two pickers grouped together on the right so
        # neither sits above the crest.
        top_row = QHBoxLayout()
        top_row.setSpacing(10)
        top_row.addWidget(eyebrow_label(side, color=tint, size=13), alignment=Qt.AlignVCenter)
        top_row.addStretch(1)

        self.season_row = SelectorRow("season", compact=True)
        self.season_row.set_values(screen.ds.seasons())
        self.season_row._display = season_label
        self.season_row.setMinimumWidth(150)
        self.season_row.setMaximumWidth(190)
        self.season_row.changed.connect(self._on_season_row_changed)
        screen.focus.register(self.season_row)
        top_row.addWidget(self.season_row)

        # Filters this column's own team list to one category (international
        # sides vs. Top 14 clubs, etc.) — not a tournament/branding picker;
        # see _reload_teams / _reload_teams_for_category.
        self.category_row = SelectorRow("category", compact=True)
        self.category_row.setMinimumWidth(150)
        self.category_row.setMaximumWidth(184)
        self.category_row.changed.connect(self._on_category_row_changed)
        screen.focus.register(self.category_row)
        top_row.addWidget(self.category_row)

        chrome_top_v.addLayout(top_row)
        chrome_top_v.addStretch(1)

        # Crest and name share one line. Away mirrors home (name left,
        # crest right) rather than repeating the same order, so the two
        # cards read as a symmetric pair either side of the middle column.
        ident_row = QHBoxLayout()
        ident_row.setSpacing(16)

        self.crest_lbl = QLabel()
        self.crest_lbl.setFixedSize(132, 132)
        self.crest_lbl.setAlignment(Qt.AlignCenter)
        self.crest_lbl.setStyleSheet("background: transparent;")

        self.name_picker = TeamNamePicker(
            display=lambda tid: screen.ds.teams[tid][self._season()]["name"],
            subtitle=lambda tid: screen.ds.teams[tid][self._season()].get("category", ""),
        )
        self.name_picker.changed.connect(self._on_team_changed)
        screen.focus.register(self.name_picker)

        if side == "home":
            ident_row.addWidget(self.crest_lbl, alignment=Qt.AlignVCenter)
            ident_row.addWidget(self.name_picker, stretch=1, alignment=Qt.AlignVCenter)
        else:
            ident_row.addWidget(self.name_picker, stretch=1, alignment=Qt.AlignVCenter)
            ident_row.addWidget(self.crest_lbl, alignment=Qt.AlignVCenter)

        chrome_top_v.addLayout(ident_row)
        chrome_top_v.addStretch(1)

        rule = QFrame()
        rule.setFixedHeight(1)
        rule.setStyleSheet(f"background: {BORDER}; border: none;")
        chrome_top_v.addWidget(rule)
        chrome_top_v.addSpacing(2)

        v.addWidget(self._chrome_top)

        # ── band 2: kit — the one thing that survives the kickoff fade ──
        # Angled slightly toward the centre — two players both staring
        # dead ahead read as posing for separate ID photos, not lining up
        # across from each other. Positive yaw turns the model to face
        # screen-right, negative screen-left (see FACE_YAW).
        self.stage = KitStage(default_yaw=FACE_YAW if side == "home" else -FACE_YAW)
        self.stage.setFixedHeight(196)
        v.addWidget(self.stage)

        self.kit_row = SelectorRow("kit", compact=True)
        # Home/away is a 2-3 item list — always cycle with < / >, never the
        # popup, regardless of the dropdown_menus preference.
        self.kit_row.set_force_arrows(True)
        self.kit_row.changed.connect(self._refresh_kit_preview)
        screen.focus.register(self.kit_row)
        chrome_bottom_v.addWidget(self.kit_row)

        chrome_bottom_v.addStretch(1)

        # ── band 3: actions ─────────────────────────────────────────────
        self.edit_squad_btn = StyledButton("EDIT SQUAD", "neutral")
        self.edit_squad_btn.setMinimumHeight(BTN_HEIGHT)
        self.edit_squad_btn.clicked.connect(lambda: screen.open_squad_editor(side))
        screen.focus.register(self.edit_squad_btn)
        chrome_bottom_v.addWidget(self.edit_squad_btn)

        v.addWidget(self._chrome_bottom)

        self._kit_cache = {}
        self._crest_src = QPixmap()
        self._crest_size = 132

    # ── proportional sizing ──────────────────────────────────────────────
    def resizeEvent(self, event):
        super().resizeEvent(event)
        h = self.card.height()
        if h <= 0:
            return
        crest = max(64, int(h * self.CREST_SHARE))
        if crest != self._crest_size:
            self._crest_size = crest
            self.crest_lbl.setFixedSize(crest, crest)
            self._apply_crest()
        self._apply_stage_height()

    def _apply_stage_height(self):
        """Restores the stage's card-proportional fixed height — needed
        after the kickoff sequence relaxes it to animate the stage's
        geometry freely, then reparents it back into the card."""
        h = self.card.height()
        if h > 0:
            self.stage.setFixedHeight(max(90, int(h * self.KIT_SHARE)))

    def _apply_crest(self):
        if self._crest_src.isNull():
            return
        self.crest_lbl.setPixmap(self._crest_src.scaled(
            self._crest_size, self._crest_size, Qt.KeepAspectRatio, Qt.SmoothTransformation))

    # ── state plumbing ───────────────────────────────────────────────────
    def _slot(self) -> TeamSlot:
        return self.screen.cfg.home if self.side == "home" else self.screen.cfg.away

    def _season(self):
        return self._slot().season or (self.screen.ds.seasons() or [""])[-1]

    def init_random(self, season, category, avoid=None):
        """Startup only: force the SAME randomly-picked season and category
        on both columns, so home/away start in sync (an international vs.
        international opener, not a country vs. a club) — each stays
        independently editable afterward. `avoid` is the other column's
        team, so the two sides never open on the same team."""
        idx = self.season_row.index_of(season)
        self.season_row.set_index(idx if idx is not None else 0)
        self._slot().season = season
        cats = self.screen.ds.categories_for(season) if season else []
        cat_idx = cats.index(category) if category in cats else 0
        self.category_row.set_values(cats, index=cat_idx)
        self._reload_teams_for_category(pick_random=True, avoid=avoid)

    def _reload_teams(self, season, pick_random, avoid=None):
        """Season changed — refill the category list for the new season
        (keeping the current category if it still exists there, same as
        the team preservation below), then refill the team list from it."""
        ds = self.screen.ds
        slot = self._slot()
        slot.season = season
        cats = ds.categories_for(season) if season else []
        prev_cat = self.category_row.current()
        if pick_random or prev_cat not in cats:
            cat_idx = random.randrange(len(cats)) if cats else 0
        else:
            cat_idx = cats.index(prev_cat)
        self.category_row.set_values(cats, index=cat_idx)
        self._reload_teams_for_category(pick_random, avoid=avoid)

    def _reload_teams_for_category(self, pick_random, avoid=None):
        ds = self.screen.ds
        slot = self._slot()
        season = slot.season
        category = self.category_row.current()
        teams = ds.teams_for(season, category) if season and category else {}
        team_ids = sorted(teams.keys(), key=lambda tid: teams[tid]["name"])
        if not team_ids:
            self.name_picker.set_values([])
            self.crest_lbl.clear()
            return
        prev = slot.team_id
        if pick_random or prev not in team_ids:
            choices = [t for t in team_ids if t != avoid] or team_ids
            idx = team_ids.index(random.choice(choices))
        else:
            idx = team_ids.index(prev)
        self.name_picker.set_values(team_ids, index=idx)
        self._on_team_changed()

    def _on_category_row_changed(self):
        self._reload_teams_for_category(pick_random=False)

    def _on_season_row_changed(self):
        self._reload_teams(self.season_row.current(), pick_random=False)

    def _on_team_changed(self):
        ds = self.screen.ds
        slot = self._slot()
        tid = self.name_picker.current()
        slot.team_id = tid
        slot.kit_index = 0
        if not tid:
            return
        season = slot.season
        info = ds.teams[tid][season]
        crest_path = os.path.join(ds.teams_folder_path.get(tid, ""),
                                   info.get("logos", {}).get("main", ""))
        self._crest_src = _load_crest(crest_path)
        if not self._crest_src.isNull():
            self._apply_crest()
        else:
            self.crest_lbl.clear()
            self.crest_lbl.setText("NO CREST")
            self.crest_lbl.setStyleSheet(f"color: {FG_MUTED}; background: transparent;")

        slot.lineup = ds.get_lineup(tid, season)
        slot.players = ds.get_players(slot.lineup.get("players_id", []), season)

        # Home side opens on its home kit, away side on its away kit —
        # the usual pairing, and it stops both sides showing the same
        # strip. Falls back to the first kit when a side isn't named.
        kit_keys = [k for k, _ in info.get("kits", {}).items()] or ["default"]
        preferred = "home" if self.side == "home" else "away"
        kit_index = kit_keys.index(preferred) if preferred in kit_keys else 0
        self.kit_row.set_values(kit_keys, index=kit_index)
        self._refresh_kit_preview()
        self.screen.on_team_changed(self.side)

    def set_mannequin(self, face_id, skin_entry):
        """Which stock head/skin the 3D preview's player wears — picked by
        MatchSetupScreen.on_show from MANNEQUIN_POOL, not stored per-column,
        so a screen re-open re-rolls it. Doesn't refresh the stage itself;
        the caller does that once both columns are set."""
        self._head_path = stock_head_path(face_id, os.path.join(config.temp_directory, "stock_heads"))
        self._skin_entry = skin_entry

    def _kit_files(self):
        """(kit dict, front kit path, back-panel path) of the selected kit."""
        ds = self.screen.ds
        slot = self._slot()
        kits = ds.teams[slot.team_id][slot.season].get("kits", {})
        key = self.kit_row.current()
        kit = kits.get(key, {}) if key else {}
        team_root = ds.teams_folder_path.get(slot.team_id, "")
        # backKitFile is the shirt's own back panel ("jbck") — without it that
        # panel falls back to plain white. It ships as a %-pattern, one image
        # per shirt number (home_back_1.png, ...); "1" stands in since this
        # preview isn't tied to a specific player.
        kit_source = os.path.join(team_root, kit.get("frontKitFile", "")) if kit else ""
        back_pattern = kit.get("backKitFile", "") if kit else ""
        back_source = os.path.join(team_root, back_pattern.replace("%", "1", 1)) if back_pattern else ""
        return kit, kit_source, back_source

    def kit_model_args(self):
        """The (args, kwargs) `_try_load_model` gets for this column's kit, or
        None with no team picked — lets a worker thread decode the same
        textures ahead of time (see MatchSetupScreen._start_preload)."""
        slot = self._slot()
        if not slot.team_id or not slot.season:
            return None
        kit, kit_source, back_source = self._kit_files()
        return ((kit_source, back_source, kit.get("model3d") if kit else None),
                {"head_path": self._head_path, "skin_entry": self._skin_entry})

    def _refresh_kit_preview(self):
        ds = self.screen.ds
        slot = self._slot()
        if not slot.team_id or not slot.season:
            self.stage.set_placeholder()
            return
        info = ds.teams[slot.team_id][slot.season]
        kits = info.get("kits", {})
        key = self.kit_row.current()
        kit = kits.get(key, {}) if key else {}
        slot.kit_index = list(kits.keys()).index(key) if key in kits else 0
        team_root = ds.teams_folder_path.get(slot.team_id, "")
        fp = os.path.join(team_root, kit.get("previewFile", ""))
        cache_key = (slot.team_id, slot.season, key)
        if cache_key not in self._kit_cache:
            self._kit_cache[cache_key] = QPixmap(fp) if os.path.exists(fp) else None
        pix = self._kit_cache[cache_key]

        # The 3D kit textures are separate assets from the flat preview image
        # (usually PNGs, occasionally real .big/.fsh) that KitStage loads
        # directly.
        _, kit_source, back_source = self._kit_files()
        self.stage.update_kit(pix if pix and not pix.isNull() else None, kit_source, back_source,
                              kit.get("model3d") if kit else None,
                              head_path=self._head_path, skin_entry=self._skin_entry,
                              load_3d=not self.screen._defer_3d)


class MatchSetupScreen(Screen):
    def __init__(self, ds: DataStore, on_back, on_play_begin, on_play_reveal, on_edit_squad,
                 on_edit_mission=None):
        super().__init__(on_back=on_back)
        # Building this screen must not load 3D models (~0.3 s cold, at
        # start-up, before anyone can see them): the columns show their flat
        # previews, a worker thread warms the texture/model caches, and the
        # first on_show does the (now cheap) 3D load.
        self._defer_3d = True
        self._first_show = True
        self.ds = ds
        self.cfg = MatchConfig()
        # Split in two so the backend can start working (file prep, the
        # game process itself) the instant Kick off is pressed, while the
        # loading screen itself only appears once the vanish/walk-off
        # animation finishes — see _start_kickoff_sequence.
        self.on_play_begin = on_play_begin
        self.on_play_reveal = on_play_reveal
        self.on_edit_squad = on_edit_squad
        # Only reachable from the advanced panel's own button, which only
        # exists when config.advanced_user is True — see
        # _build_advanced_panel. None (the container's default) is never
        # actually called: the button that would call it doesn't exist.
        self.on_edit_mission = on_edit_mission
        self._advanced_open = False
        self._kickoff_running = False
        self._build()
        self._init_devices()

        # Same random season/category for both teams at startup only — each
        # stays independently editable from here on (no centre linking).
        # Prefer a season that can actually field two different teams —
        # some seasons in the data only carry one, and opening on a team
        # against itself looks broken even though it's just thin data.
        seasons = self.ds.seasons()
        playable = [s for s in seasons if len(self.ds.teams_in_season(s)) >= 2]
        season = random.choice(playable or seasons) if seasons else None
        cats = self.ds.categories_for(season) if season else []
        category = random.choice(cats) if cats else None
        self.home_col.init_random(season, category)
        self.away_col.init_random(season, category, avoid=self.cfg.home.team_id)
        self.on_team_changed("home")   # sync cfg.stadium from the initial pick

        # A kit edited in the team editor must not keep showing the cached
        # picture from before the save.
        ds.events.team_changed.connect(self._on_team_data_changed)

        self._defer_3d = False
        self._pick_mannequins()
        self._start_preload()

    def _pick_mannequins(self):
        """Which two mannequins (of MANNEQUIN_POOL's 8) wear the kits — two
        distinct picks so home and away are never the same player."""
        home_pick, away_pick = random.sample(MANNEQUIN_POOL, 2)
        self.home_col.set_mannequin(*home_pick)
        self.away_col.set_mannequin(*away_pick)

    def _start_preload(self):
        """Decode the two opening kits' textures and models on a worker thread
        (PIL/numpy do most of it outside the GIL) so the first visit to this
        screen finds them in the caches. Only warms caches; nothing here
        touches Qt or GL."""
        if not user_prefs.player_3d_preview:
            return
        jobs = [args for args in (self.home_col.kit_model_args(), self.away_col.kit_model_args()) if args]
        if not jobs:
            return

        def work():
            for args, kwargs in jobs:
                try:
                    _try_load_model(*args, **kwargs)
                except Exception as e:      # a warm-up must never matter
                    log.warning(f"3D preview preload failed: {e}")

        self._preload_thread = threading.Thread(target=work, name="kit-preload", daemon=True)
        self._preload_thread.start()

    def prewarm(self):
        """Build the two 3D previews and render their first frame while the
        screen is still hidden, so opening it shows finished players instead of
        creating GL contexts and uploading textures on the click. Idle-time
        work: called shortly after start-up; a later call is a no-op (same kit,
        same mannequin — see KitStage.update_kit)."""
        if not user_prefs.player_3d_preview or self.isVisible():
            return
        thread = getattr(self, "_preload_thread", None)
        if thread is not None and thread.is_alive():
            QTimer.singleShot(150, self.prewarm)       # caches are still filling
            return
        for col in (self.home_col, self.away_col):
            col._refresh_kit_preview()
            view = col.stage.player_view
            if view is not None:
                view.render_first_frame()

    def _on_team_data_changed(self, tid):
        for col in (self.home_col, self.away_col):
            col._kit_cache.clear()
            if col._slot().team_id == tid and self.isVisible():
                col._refresh_kit_preview()

    def on_show(self):
        super().on_show()
        # Undoes a kickoff sequence that was interrupted (game exited back
        # to team selection before a rematch, say) — the cards need their
        # players and chrome back before anything else on this screen makes
        # sense again.
        self._reset_kickoff_visuals()
        self._apply_expert_mode()      # picks up a Settings toggle flipped meanwhile
        # Re-roll which two mannequins wear the kits each time the screen is
        # opened — except the first, which uses the ones already picked (and
        # preloaded) when the screen was built.
        if self._first_show:
            self._first_show = False
        else:
            self._pick_mannequins()
        # Re-decides flat vs 3D per kit stage — picks up a settings toggle
        # flipped while this screen was hidden, without needing a team/kit
        # change to trigger it.
        self.home_col._refresh_kit_preview()
        self.away_col._refresh_kit_preview()
        self.play_btn.setFocus()

    def _apply_expert_mode(self):
        """Show the disabled "coming soon" rows only in expert mode. Hidden
        rows are skipped by keyboard/pad navigation (FocusManager.alive)."""
        for row in getattr(self, "_coming_soon_rows", []):
            row.setVisible(user_prefs.expert_mode)

    def _reset_kickoff_visuals(self):
        if not self._kickoff_running:
            return
        for eff in getattr(self, '_fade_effects', []):
            eff.setOpacity(1.0)
        for widget in (self.home_col._chrome_top, self.home_col._chrome_bottom,
                       self.away_col._chrome_top, self.away_col._chrome_bottom,
                       self.mid_col, self.header_widget, self.hintbar, self.play_btn):
            widget.setGraphicsEffect(None)
        for col in (self.home_col, self.away_col):
            col.card.bg_opacity = 1.0
            col.crest_lbl.setGraphicsEffect(None)
        self._drop_overlay()

        from ui.player_anim import IdleAnimation
        for col in (self.home_col, self.away_col):
            stage = col.stage
            if stage.parentWidget() is self:
                stage.setParent(col.card)
                col.card.layout().insertWidget(1, stage)   # between the two chrome wrappers
                col._apply_stage_height()
                stage.show()
            if stage.player_view is not None:
                rnd = stage.player_view.renderer
                rnd.anim = IdleAnimation(rnd.rig)
                stage.reset_yaw()
                rnd._t0 -= random.uniform(0.0, IdleAnimation.LOOP)
                stage.unfreeze()
                stage.player_view.resume()

        self.play_btn.setEnabled(True)
        self._kickoff_running = False

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header_widget = page_header("Quick match", breadcrumb="Match setup", right="",
                                          on_back=self._on_back_clicked)
        root.addWidget(self.header_widget)

        # The atmosphere backdrop spans the whole screen (see resizeEvent), not
        # just the body: the kickoff sequence fades the header, hint bar and kick
        # off row to nothing, and over a body-only backdrop that left flat dark
        # bands at the top and bottom.
        self._backdrop = AtmosphereWidget(self)
        self._backdrop.lower()
        body = QWidget()
        body.setObjectName("matchSetupBody")
        body.setStyleSheet("QWidget#matchSetupBody { background: transparent; }")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(80, 24, 80, 20)
        bl.setSpacing(24)

        self.home_col = TeamColumn("home", HOME_TINT, self)
        self.mid_col = self._build_mid_column()
        self.away_col = TeamColumn("away", AWAY_TINT, self)

        # Team cards carry the content, the match column is a narrow spine.
        self.mid_col.setMinimumWidth(320)
        self.mid_col.setMaximumWidth(360)
        bl.addWidget(self.home_col, stretch=5)
        bl.addWidget(self.mid_col, stretch=2)
        bl.addWidget(self.away_col, stretch=5)
        root.addWidget(body, stretch=1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(80, 0, 80, 20)
        bottom.addStretch(1)
        self.play_btn = StyledButton("KICK OFF", "primary")
        self.play_btn.setMinimumHeight(BTN_HEIGHT + 12)
        self.play_btn.setMinimumWidth(220)
        self.play_btn.clicked.connect(self._play)
        self.focus.register(self.play_btn)
        bottom.addWidget(self.play_btn)
        root.addLayout(bottom)

        self.hintbar = HintBar()
        root.addWidget(self.hintbar)
        self._update_hints()

        # Advanced slide-over, absolutely positioned over the right side —
        # SidePanelSlide moves it in and out through the screen edge it
        # rests against (see ui/side_panel.py).
        self.advanced_panel = self._build_advanced_panel()
        self.advanced_panel.setParent(self)
        self.advanced_panel.hide()
        self._advanced_slide = SidePanelSlide(self.advanced_panel, self._advanced_rect)

    def _build_mid_column(self):
        wrap = QWidget()
        wv = QVBoxLayout(wrap)
        wv.setContentsMargins(0, 0, 0, 0)
        wv.setSpacing(14)

        card = Card(translucent=True)
        v = QVBoxLayout(card)
        v.setContentsMargins(24, 18, 24, 20)
        v.setSpacing(10)

        v.addWidget(eyebrow_label("match", color=ACCENT, size=15))

        # Difficulty + half length live here now instead of behind Advanced
        # — they're core match settings, not advanced ones, and a compact
        # pair matches how season/competition sit on the team cards.
        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)
        self.difficulty_row = SelectorRow("difficulty", compact=True)
        self.difficulty_row.set_values(["club", "pro", "elite"], index=2)
        self.difficulty_row.changed.connect(
            lambda: setattr(self.cfg, "difficulty", self.difficulty_row.current()))
        self.focus.register(self.difficulty_row)
        settings_row.addWidget(self.difficulty_row, stretch=1)

        self.half_row = SelectorRow("half length", compact=True)
        self.half_row.set_values(["2m", "5m", "10m", "20m", "40m"], index=1)
        self.half_row.changed.connect(
            lambda: setattr(self.cfg, "halftime_length", self.half_row.current()))
        self.focus.register(self.half_row)
        settings_row.addWidget(self.half_row, stretch=1)
        v.addLayout(settings_row)

        self.stadium_row = DropdownRow("stadium")
        stadiums = sorted(self.ds.stadiums.items(),
                           key=lambda x: int(x[1].get("game_id", x[0])) if isinstance(x[1], dict) else 0)
        self._stadium_list = [(sid, info) for sid, info in stadiums if isinstance(info, dict)]
        self.stadium_row.set_values(self._stadium_list)
        self.stadium_row._display = lambda t: t[1].get("name", str(t[0]))
        self.stadium_row.changed.connect(self._on_stadium_changed)
        self.focus.register(self.stadium_row)
        v.addWidget(self.stadium_row)

        # Right after the stadium it belongs to — a core match setting
        # (which environment the ground loads), not an advanced one. Values
        # are only ever whatever the selected stadium supports (stadiums.json
        # "environments"); see _sync_environment_choices, called both below
        # and from _on_stadium_changed.
        self.environment_row = SelectorRow("environment")
        self.environment_row.changed.connect(
            lambda: setattr(self.cfg, "environment", self.environment_row.current()))
        self.focus.register(self.environment_row)
        v.addWidget(self.environment_row)

        self.advanced_btn = StyledButton("ADVANCED", "neutral")
        self.advanced_btn.setMinimumHeight(BTN_HEIGHT)
        self.advanced_btn.clicked.connect(self.toggle_advanced)
        self.focus.register(self.advanced_btn)
        v.addWidget(self.advanced_btn)
        wv.addWidget(card)
        wv.addSpacing(14)

        # Controllers — its own container below the match card. Only the
        # keyboard exists as a controller for now (pad detection is a later
        # migration step), so it's one plain row, not a tile grid.
        controls_card = Card(translucent=True)
        cv = QVBoxLayout(controls_card)
        cv.setContentsMargins(24, 18, 24, 20)
        cv.setSpacing(10)
        cv.addWidget(eyebrow_label("Controllers", color=ACCENT, size=15))
        self.keyboard_row = SelectorRow("keyboard")
        self.keyboard_row.set_values([("home", "home"), ("away", "away")], index=0)
        self.keyboard_row._display = lambda t: t[0]
        self.keyboard_row.changed.connect(self._on_keyboard_zone_changed)
        self.focus.register(self.keyboard_row)
        cv.addWidget(self.keyboard_row)
        wv.addWidget(controls_card)

        wv.addStretch(1)

        if self._stadium_list:
            self._on_stadium_changed()
        return wrap

    def _build_advanced_panel(self):
        panel = Card()
        panel.setObjectName("advancedPanel")
        panel.setStyleSheet(f"QWidget#advancedPanel {{ background: {BG_PANEL}; border-left: 3px solid {ACCENT}; }}")
        outer = QVBoxLayout(panel)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        head = QHBoxLayout()
        head.setContentsMargins(34, 26, 34, 14)
        head.addWidget(display_label("ADVANCED", 22, QFont.Bold, track=1.6))
        head.addStretch(1)
        close_btn = StyledButton("CLOSE", "ghost")
        close_btn.clicked.connect(self.toggle_advanced)
        head.addWidget(close_btn)
        outer.addLayout(head)

        # config.advanced_user adds a lot of rows below (wind/weather extras,
        # presentation toggles, the mission-state button) — a plain fixed
        # panel would run off the bottom of a short window, so the body
        # scrolls (only when it actually needs to: widgetResizable + no
        # horizontal bar means a panel that fits shows no scrollbar at all).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        body = QWidget()
        body.setStyleSheet(f"background: {BG_PANEL};")
        scroll.viewport().setStyleSheet(f"background: {BG_PANEL};")
        v = QVBoxLayout(body)
        v.setContentsMargins(34, 0, 34, 26)
        v.setSpacing(14)
        scroll.setWidget(body)
        outer.addWidget(scroll, stretch=1)

        self.side_row = SelectorRow("home team side")
        self.side_row.set_values(["random", "left", "right"], index=0)
        self.side_row.changed.connect(
            lambda: setattr(self.cfg, "home_team_side", self.side_row.current()))
        self.focus.register(self.side_row)
        v.addWidget(self.side_row)

        self.kickoff_row = SelectorRow("kick-off")
        self.kickoff_row.set_values([("home", "home"), ("away", "away"), ("random", "random")], index=2)
        self.kickoff_row._display = lambda t: t[0]
        self.kickoff_row.changed.connect(
            lambda: setattr(self.cfg, "kick_off",
                             self.kickoff_row.current()[1] if self.kickoff_row.current() else "random"))
        self.focus.register(self.kickoff_row)
        v.addWidget(self.kickoff_row)

        self.rain_row = SelectorRow("rain")
        self.rain_row.set_values(["no", "yes"], index=0)
        self.rain_row.changed.connect(
            lambda: setattr(self.cfg, "rain", self.rain_row.current() == "yes"))
        self.focus.register(self.rain_row)
        v.addWidget(self.rain_row)

        # reR08 ENABLE_PITCH's whitelist (gsv.pitch_textures: the game's own
        # names, which the DLL matches exactly), labelled "<condition> —
        # Region N (variant)". RegN is the texture pack; the variant is the
        # light (d / n / o = day / night / overcast, t as is). "default" (not
        # in the whitelist) = the stadium's own pitch, unset.
        variants = {"d": "day", "n": "night", "o": "overcast"}

        def pitch_label(name):
            region, _, rest = name.split("_", 2)     # "Reg2", "08", "muddy_n"
            condition, _, variant = rest.rpartition("_")
            condition_word = condition.replace("_", " ").capitalize()
            region_word = f"Region {region[3:]}" if region.startswith("Reg") else region
            variant_word = variants.get(variant, variant).capitalize()
            return f"{condition_word} — {region_word} ({variant_word})"

        self.pitch_row = SelectorRow("pitch texture")
        self.pitch_row.set_values(
            [("default", "Default")] + sorted(((n, pitch_label(n)) for n in gsv.pitch_textures),
                                              key=lambda t: t[1]),
            index=0)
        self.pitch_row._display = lambda t: t[1]
        self.pitch_row.changed.connect(
            lambda: setattr(self.cfg, "pitch_texture",
                            (self.pitch_row.current() or ("default", ""))[0]))
        self.focus.register(self.pitch_row)
        v.addWidget(self.pitch_row)

        # Only two pitch-logo packs ship today (data/tournaments/*/pitch_logos)
        # — "none" forces no logo; any tournament choice forces that pack.
        # Defaults to the "Default" pack rather than "none" so picking a
        # pitch logo isn't itself a hidden extra step.
        self._pitch_logo_choices = [("none", "none")] + [
            (tid, next(iter(seasons.values())).get("name", tid))
            for tid, seasons in self.ds.tournaments.items() if seasons
        ]
        default_index = next((i for i, (_, label) in enumerate(self._pitch_logo_choices)
                              if label == "Default"), 0)
        self.pitch_logo_row = SelectorRow("pitch logo")
        self.pitch_logo_row.set_values(self._pitch_logo_choices, index=default_index)
        self.pitch_logo_row._display = lambda t: t[1]
        self.pitch_logo_row.changed.connect(
            lambda: setattr(self.cfg, "pitch_logo_choice",
                            (self.pitch_logo_row.current() or ("none", ""))[0]))
        self.focus.register(self.pitch_logo_row)
        v.addWidget(self.pitch_logo_row)
        self.cfg.pitch_logo_choice = self._pitch_logo_choices[default_index][0]

        # Tournament logo (scoreboard / in-game graphics) and stadium graphics
        # ("pads"): taken from the tournaments' own files, both defaulting to
        # the "Default" tournament.
        def tournament_choices(key):
            return [(tid, next(iter(seasons.values())).get("name", tid))
                    for tid, seasons in self.ds.tournaments.items()
                    if seasons and next(iter(seasons.values())).get(key)]

        self._tournament_logo_choices = tournament_choices("logo")
        if self._tournament_logo_choices:
            logo_index = next((i for i, (_, label) in enumerate(self._tournament_logo_choices)
                               if label == "Default"), 0)
            self.tournament_logo_row = SelectorRow("tournament logo")
            self.tournament_logo_row.set_values(self._tournament_logo_choices, index=logo_index)
            self.tournament_logo_row._display = lambda t: t[1]
            self.tournament_logo_row.changed.connect(
                lambda: setattr(self.cfg, "tournament_logo_choice",
                                (self.tournament_logo_row.current() or ("", ""))[0]))
            self.focus.register(self.tournament_logo_row)
            v.addWidget(self.tournament_logo_row)
            self.cfg.tournament_logo_choice = self._tournament_logo_choices[logo_index][0]

        self._stadium_graphics_choices = tournament_choices("pads")
        if self._stadium_graphics_choices:
            pads_index = next((i for i, (_, label) in enumerate(self._stadium_graphics_choices)
                               if label == "Default"), 0)
            self.stadium_graphics_row = SelectorRow("stadium graphics")
            self.stadium_graphics_row.set_values(self._stadium_graphics_choices, index=pads_index)
            self.stadium_graphics_row._display = lambda t: t[1]
            self.stadium_graphics_row.changed.connect(
                lambda: setattr(self.cfg, "stadium_graphics_choice",
                                (self.stadium_graphics_row.current() or ("", ""))[0]))
            self.focus.register(self.stadium_graphics_row)
            v.addWidget(self.stadium_graphics_row)
            self.cfg.stadium_graphics_choice = self._stadium_graphics_choices[pads_index][0]

        # Which ball the match uses: the home team's (default), the away
        # team's or a tournament's. The open list previews the ball in 3D.
        from ui.ball_picker import BallRow
        from app.ball_options import frames_for
        self.ball_row = BallRow("ball", frames_for)
        self._ball_pick_key = None     # what the player picked; None = follow the home team
        self.ball_row.changed.connect(self._on_ball_changed)
        self.focus.register(self.ball_row)
        v.addWidget(self.ball_row)
        self._refresh_ball_options()

        v.addSpacing(6)
        # "wind" moves out of this coming-soon strip once advanced_user
        # unlocks the real control below; "referee"/"stadium graphics" are
        # still genuinely unimplemented (referee_openplay is EXPERIMENTAL
        # and off by default even in reR08; "stadium graphics" isn't the
        # same thing as the RWC stadium_flags toggle below it).
        # Hidden unless Settings > Expert Mode is on (see _apply_expert_mode).
        self._coming_soon_rows = []
        for label in (("referee",) if config.advanced_user
                     else ("wind", "referee")):
            row = SelectorRow(label)
            row.set_free_text("—")
            row.set_disabled_visual(True)
            row.set_status("COMING SOON", FG_MUTED)
            self.focus.register(row)
            v.addWidget(row)
            self._coming_soon_rows.append(row)
        self._apply_expert_mode()

        if config.advanced_user:
            self._build_advanced_weather_rows(v)

        self.match_type_row = SelectorRow("match type")
        self.match_type_row.set_values(list(gsv.match_type.keys()), index=0)
        self.match_type_row.changed.connect(self._on_match_type_changed)
        self.focus.register(self.match_type_row)
        v.addWidget(self.match_type_row)

        self.match_subtype_row = SelectorRow("match subtype")
        self.match_subtype_row.changed.connect(
            lambda: setattr(self.cfg, "match_subtype", self.match_subtype_row.current()))
        self.focus.register(self.match_subtype_row)
        v.addWidget(self.match_subtype_row)
        self._sync_match_subtype()

        if config.advanced_user:
            self._build_advanced_presentation_rows(v)

        v.addStretch(1)

        panel.setFixedWidth(ADVANCED_PANEL_W)
        return panel

    # ── config.advanced_user rows ────────────────────────────────────────
    def _build_advanced_weather_rows(self, v):
        """Wind + the weather extras reR08 supports beyond the plain rain
        toggle above. Every row here is additive/optional at the MatchConfig
        level (see its own comment) — leaving all of them at their default
        produces the exact same .mis this screen has always produced."""
        v.addWidget(eyebrow_label("WIND & WEATHER", color=ACCENT, size=13))

        self.wind_power_row = SelectorRow("wind power")
        self.wind_power_row.set_values(list(range(WIND_POWER_MAX + 1)), index=0)
        self.wind_power_row._display = lambda n: "off" if n == 0 else str(n)
        self.wind_power_row.changed.connect(
            lambda: setattr(self.cfg, "wind_power", self.wind_power_row.current() or None))
        self.focus.register(self.wind_power_row)
        v.addWidget(self.wind_power_row)

        self.wind_dir_row = SelectorRow("wind direction")
        self.wind_dir_row.set_values(list(range(0, 360, 45)), index=0)
        self.wind_dir_row._display = lambda n: f"{n}°"
        self.wind_dir_row.changed.connect(
            lambda: setattr(self.cfg, "wind_dir_deg", float(self.wind_dir_row.current())))
        self.focus.register(self.wind_dir_row)
        v.addWidget(self.wind_dir_row)

        # Overrides the plain rain toggle above when set to anything but
        # "stock" — it's the only path to real falling snow (precipitation
        # alone can't show it; see game_specific_variables.py).
        self.precip_row = SelectorRow("precipitation override")
        self.precip_row.set_values(["stock", "none", "rain", "snow"], index=0)
        self.precip_row.changed.connect(self._on_precip_mode_changed)
        self.focus.register(self.precip_row)
        v.addWidget(self.precip_row)

        self.snow_intensity_row = SelectorRow("snow intensity")
        self.snow_intensity_row.set_values(list(range(int(SNOW_INTENSITY_MAX) + 1)), index=13)
        self.snow_intensity_row.changed.connect(
            lambda: setattr(self.cfg, "snow_intensity", float(self.snow_intensity_row.current())))
        self.snow_intensity_row.set_disabled_visual(True)
        self.focus.register(self.snow_intensity_row)
        v.addWidget(self.snow_intensity_row)

        self.breath_row = SelectorRow("cold breath")
        self.breath_row.set_values(["stock", "off", "on"], index=0)
        self.breath_row.changed.connect(lambda: setattr(
            self.cfg, "breath", {"off": False, "on": True}.get(self.breath_row.current())))
        self.focus.register(self.breath_row)
        v.addWidget(self.breath_row)

    def _on_precip_mode_changed(self):
        mode = self.precip_row.current()
        self.cfg.precip_mode = mode
        # Snow intensity only means anything once snow is actually chosen —
        # greyed out otherwise so it doesn't read as a live control.
        self.snow_intensity_row.set_disabled_visual(mode != "snow")

    def _build_advanced_presentation_rows(self, v):
        """.mis presentation attrs (anthem/haka/trophy/stadium dressing) and
        the kick-assist gameplay toggle — each a real reR08 patch, default
        on; see game_specific_variables.py."""
        v.addSpacing(6)
        v.addWidget(eyebrow_label("PRESENTATION", color=ACCENT, size=13))

        self.anthem_row = SelectorRow("anthem")
        self.anthem_row.set_values(gsv.anthem_choices, index=0)
        self.anthem_row.changed.connect(
            lambda: setattr(self.cfg, "anthem", self.anthem_row.current()))
        self.focus.register(self.anthem_row)
        v.addWidget(self.anthem_row)

        self.haka_home_row = SelectorRow("haka (home)")
        self.haka_home_row.set_values(["no", "yes"], index=0)
        self.haka_home_row.changed.connect(
            lambda: setattr(self.cfg, "haka_home", self.haka_home_row.current() == "yes"))
        self.focus.register(self.haka_home_row)
        v.addWidget(self.haka_home_row)

        self.haka_away_row = SelectorRow("haka (away)")
        self.haka_away_row.set_values(["no", "yes"], index=0)
        self.haka_away_row.changed.connect(
            lambda: setattr(self.cfg, "haka_away", self.haka_away_row.current() == "yes"))
        self.focus.register(self.haka_away_row)
        v.addWidget(self.haka_away_row)

        self.trophy_row = SelectorRow("trophy lift")
        self.trophy_row.set_values(gsv.trophy_lift_choices, index=0)
        self.trophy_row.changed.connect(
            lambda: setattr(self.cfg, "trophy_lift", self.trophy_row.current()))
        self.focus.register(self.trophy_row)
        v.addWidget(self.trophy_row)

        self.stadium_flags_row = SelectorRow("stadium flags (RWC dressing)")
        self.stadium_flags_row.set_values(["stock", "off", "on"], index=0)
        self.stadium_flags_row.changed.connect(lambda: setattr(
            self.cfg, "stadium_flags",
            {"off": False, "on": True}.get(self.stadium_flags_row.current())))
        self.focus.register(self.stadium_flags_row)
        v.addWidget(self.stadium_flags_row)

        self.kick_assist_row = SelectorRow("kick assist")
        self.kick_assist_row.set_values(["no", "yes"], index=0)
        self.kick_assist_row.changed.connect(
            lambda: setattr(self.cfg, "kick_assist", self.kick_assist_row.current() == "yes"))
        self.focus.register(self.kick_assist_row)
        v.addWidget(self.kick_assist_row)

        v.addSpacing(6)
        v.addWidget(eyebrow_label("MISSION STATE", color=ACCENT, size=13))
        mission_btn = StyledButton("EDIT MISSION STATE…", "neutral")
        mission_btn.setMinimumHeight(BTN_HEIGHT)
        if self.on_edit_mission:
            mission_btn.clicked.connect(lambda: self.on_edit_mission(self.cfg))
        self.focus.register(mission_btn)
        v.addWidget(mission_btn)

    def _advanced_rect(self):
        return QRect(self.width() - ADVANCED_PANEL_W, 0,
                     ADVANCED_PANEL_W, self.height())

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if hasattr(self, "_backdrop"):
            self._backdrop.setGeometry(self.rect())
            self._backdrop.lower()
        if hasattr(self, "_advanced_slide"):
            self._advanced_slide.sync_geometry()

    # ── controllers (keyboard-only this phase; pad detection is a later
    #    migration step per the approved plan) ─────────────────────────────
    def _init_devices(self):
        # Matches self.keyboard_row's own default (index 0, "home").
        self.cfg.controllers = {1: {"kind": "kbd", "label": "KEYBOARD", "zone": "home"}}

    def _on_keyboard_zone_changed(self):
        zone = self.keyboard_row.current()
        self.cfg.controllers[1]["zone"] = zone[1] if zone else "home"

    # ── competition options / backend sync ──────────────────────────────────
    def on_team_changed(self, side):
        # The old tournament/branding picker is gone — "competition" is now
        # each column's own category filter (see TeamColumn.category_row),
        # not a match-wide tournament choice, so there's no longer a value
        # to feed cfg.shared_tournament. build_match_data already falls
        # back to the home team's own crest/pads whenever it's None.
        if side == "home":
            self.cfg.shared_tournament = None
            self._auto_select_home_stadium()
        self._refresh_ball_options()

    def _on_ball_changed(self):
        option = self.ball_row.current() or {}
        self._ball_pick_key = None if option.get("key") == "home" else option.get("key")
        self.cfg.ball_choice = option.get("choice")

    def _refresh_ball_options(self):
        """Rebuild the ball list for the current home/away teams, keeping the
        same pick (home / away / a tournament) when it still exists — the home
        team's ball otherwise."""
        if not hasattr(self, "ball_row"):      # called while the panel is still being built
            return
        from app.ball_options import list_ball_options
        options = list_ball_options(self.ds, self.cfg)
        index = next((i for i, o in enumerate(options)
                      if o["key"] == (self._ball_pick_key or "home")), 0)
        self.ball_row.set_values(options, index=index)
        self.cfg.ball_choice = options[index]["choice"] if options else None

    # ── stadium ──────────────────────────────────────────────────────────
    def _auto_select_home_stadium(self):
        """Picks the venue for the home team's season (its `primaryStadium`
        in teams/*.json) whenever the home side or its season changes —
        matches drop into that team's actual home ground without the user
        having to set it by hand every time. Random when the team carries
        no primaryStadium yet, or it points at a stadium not in the loaded
        list (unset team, or an id that doesn't resolve)."""
        if not self._stadium_list:
            return
        slot = self.cfg.home
        sid = None
        if slot.team_id and slot.season:
            info = self.ds.teams.get(slot.team_id, {}).get(slot.season, {})
            sid = info.get("primaryStadium") or None
        idx = None
        if sid:
            for i, (list_sid, _info) in enumerate(self._stadium_list):
                if str(list_sid) == str(sid):
                    idx = i
                    break
        if idx is None:
            idx = random.randrange(len(self._stadium_list))
        self.stadium_row.set_index(idx)
        self._on_stadium_changed()

    def _on_stadium_changed(self):
        entry = self.stadium_row.current()
        if not entry:
            return
        sid, info = entry
        self.cfg.stadium = {"stadium_id": int(info.get("game_id", sid)), "data": info}
        self._sync_environment_choices()

    # ── advanced panel ───────────────────────────────────────────────────
    def _sync_environment_choices(self):
        """Only offer environments the selected stadium actually has (its
        own stadiums.json "environments" list) — picking one it doesn't
        have would just silently fall back in-game (reR08 ENABLE_ENVIRONMENT
        validates and falls back rather than crashing), which reads as the
        control not working. No "auto": defaults to the stadium's own first
        listed environment (a stadium with none listed falls back to "day")."""
        envs = (self.cfg.stadium or {}).get("data", {}).get("environments", []) or ["day"]
        current = self.cfg.environment if self.cfg.environment in envs else envs[0]
        self.environment_row.set_values(envs, index=envs.index(current))
        self.cfg.environment = current

    def _on_match_type_changed(self):
        self.cfg.match_type = self.match_type_row.current()
        self._sync_match_subtype()

    def _sync_match_subtype(self):
        """Exhibition has no subtype in the stock game: force 'none' and lock
        the row. Every other match type requires a real subtype, so drop
        'none' from the choices instead of leaving a value the game ignores."""
        if self.match_type_row.current() == "exhibition":
            self.match_subtype_row.set_values(["none"], index=0)
            self.match_subtype_row.set_disabled_visual(True)
        else:
            subtypes = [k for k in gsv.match_subtype.keys() if k != "none"]
            self.match_subtype_row.set_values(subtypes, index=0)
            self.match_subtype_row.set_disabled_visual(False)
        self.cfg.match_subtype = self.match_subtype_row.current()

    def toggle_advanced(self):
        self._advanced_open = not self._advanced_open
        self._advanced_slide.set_open(self._advanced_open)
        self._update_hints()

    # ── hints ────────────────────────────────────────────────────────────
    def _update_hints(self):
        if self._advanced_open:
            self.hintbar.set_hints([("A", "change"), ("B", "close panel")])
        else:
            self.hintbar.set_hints([
                ("A", "select"), ("X", "home squad"), ("Y", "away squad"),
                ("F", "advanced"), ("B", "back"),
            ])

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action == Action.ADVANCED:
            self.toggle_advanced(); event.accept(); return
        if action == Action.ALT:
            self.open_squad_editor("home"); event.accept(); return
        if action == Action.AUX:
            self.open_squad_editor("away"); event.accept(); return
        if action == Action.BACK and self._advanced_open:
            self.toggle_advanced(); event.accept(); return
        super().keyPressEvent(event)

    def _on_back_clicked(self):
        """The header's mouse-clickable back button — same precedence as
        the keyboard/pad BACK action: close the advanced panel first if
        it's open, only leave the screen once it isn't."""
        if self._advanced_open:
            self.toggle_advanced()
        elif self.on_back_cb:
            self.on_back_cb()

    # ── squad editing / play ────────────────────────────────────────────
    def open_squad_editor(self, side):
        self.on_edit_squad(side, self.cfg)

    def refresh_after_lineup_edit(self, side, data):
        slot = self.cfg.home if side == "home" else self.cfg.away
        slot.lineup = data

    def _play(self):
        if self._kickoff_running:
            return
        home, away = self.cfg.controller_counts()
        if home + away < 1:
            return
        match_data = build_match_data(self.ds, self.cfg)
        if match_data is None:
            return
        self._start_kickoff_sequence(match_data)

    # ── kickoff sequence: vanish chrome, walk the players off, reveal ────
    def _start_kickoff_sequence(self, match_data):
        self._kickoff_running = True
        self.play_btn.setEnabled(False)

        # Real backend work (file prep, launching the game process) starts
        # now, hidden behind the animation — by the time the loading ring
        # is actually shown it already has a head start. The ring's own
        # display is forced back to 0 on reveal regardless (see
        # on_play_reveal / GameWidget.restart_loading_display), so what the
        # player sees is a normal-looking 0->100 climb that is quietly
        # ahead of schedule the whole way — the "trick" that makes the wait
        # feel shorter without lying about a fixed duration.
        self.on_play_begin(match_data)
        self._make_crest_flyers()

        fade_targets = [
            self.home_col._chrome_top, self.home_col._chrome_bottom,
            self.away_col._chrome_top, self.away_col._chrome_bottom,
            self.mid_col, self.header_widget, self.hintbar, self.play_btn,
        ]
        group = QParallelAnimationGroup(self)
        self._fade_effects = []
        for w in fade_targets:
            eff = QGraphicsOpacityEffect(w)
            w.setGraphicsEffect(eff)
            self._fade_effects.append(eff)
            anim = QPropertyAnimation(eff, b"opacity", self)
            anim.setDuration(450)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.InOutQuad)
            group.addAnimation(anim)
        # The team cards' own panel (fill, border, stripe) fades too — not
        # via QGraphicsOpacityEffect, which would also dim the 3D player
        # stage living inside it, but via the card's own bg_opacity so the
        # player stays fully opaque while its bordered box disappears
        # around it instead of sitting there empty through the whole
        # walk-off / zoom.
        for col in (self.home_col, self.away_col):
            anim = QPropertyAnimation(col.card, b"bg_opacity", self)
            anim.setDuration(450)
            anim.setStartValue(1.0)
            anim.setEndValue(0.0)
            anim.setEasingCurve(QEasingCurve.OutCubic)
            group.addAnimation(anim)

        self._fade_group = group
        # The camera dollies in past the players. (_begin_walk_off, the walk-off
        # that used to be picked at random, is kept but unused.)
        group.finished.connect(self._begin_zoom_in)
        group.start()

    def _begin_walk_off(self):
        # Each player detaches from its card's layout and is reparented onto
        # the screen itself with the same on-screen rect, so the swap is
        # invisible — only then can it be animated past the card's bounds
        # toward whichever edge is nearest its side.
        group = QParallelAnimationGroup(self)
        for col, direction in ((self.home_col, -1), (self.away_col, 1)):
            stage = col.stage
            top_left = stage.mapTo(self, QPoint(0, 0))
            rect = stage.geometry()
            rect.moveTopLeft(top_left)
            layout = stage.parentWidget().layout()
            if layout is not None:
                layout.removeWidget(stage)
            stage.setParent(self)
            stage.setMinimumHeight(0)
            stage.setMaximumHeight(16777215)
            stage.setGeometry(rect)
            stage.show()
            stage.raise_()

            if stage.player_view is not None:
                from ui.player_anim import WalkAnimation, BlendAnimation
                rnd = stage.player_view.renderer
                # Crossfade out of whatever idle pose the body is in, and
                # turn round rather than snapping — the viewer may have
                # orbited the model to any angle, so neither the pose nor
                # the heading can be assumed.
                rnd.anim = BlendAnimation(rnd.anim, WalkAnimation(rnd.rig),
                                          start_t=rnd.now(), duration=0.5)
                rnd.turn_to(270 if direction < 0 else 90, rate=0.12)
                stage.player_view.resume()

            # Longer than a plain slide off-screen, and shrinking as it goes:
            # reads as running away into the distance rather than sliding at
            # a fixed size, so stretching the duration (which is also what
            # hides more of the real backend work behind it — see
            # _start_kickoff_sequence) still looks like acceleration, not
            # slow motion.
            end_w, end_h = max(1, int(rect.width() * 0.4)), max(1, int(rect.height() * 0.4))
            end_x = -end_w - 60 if direction < 0 else self.width() + 60
            end_y = rect.y() + (rect.height() - end_h) // 2
            end_rect = QRect(end_x, end_y, end_w, end_h)
            anim = QPropertyAnimation(stage, b"geometry", self)
            anim.setDuration(WALKOFF_MS)
            anim.setStartValue(rect)
            anim.setEndValue(end_rect)
            # Gentler than InCubic: a walk travels at a fairly steady pace,
            # and a hard acceleration at the end would outrun the leg cycle.
            anim.setEasingCurve(QEasingCurve.InQuad)
            group.addAnimation(anim)
        self._walkoff_group = group
        group.finished.connect(self._finish_kickoff)
        group.start()

    # ── crest flight: match-setup crests -> loading-screen crests ────────
    def _make_crest_flyers(self):
        """From the moment Kick off is pressed, draw each team crest on a
        window-level overlay, on top of the real one (which is hidden), so it
        can later fly to its place on the loading screen."""
        self._overlay = None
        self._flyers = {}
        win = self.window()
        if getattr(win, "screen_ingame", None) is None:
            return
        overlay = QWidget(win)
        overlay.setAttribute(Qt.WA_TransparentForMouseEvents)
        overlay.setStyleSheet("background: transparent;")
        overlay.setGeometry(win.rect())
        for side, col in (("home", self.home_col), ("away", self.away_col)):
            pix = col.crest_lbl.pixmap()
            if pix is None or pix.isNull():
                continue
            trimmed, kept = trim_transparent(pix)
            dpr = pix.devicePixelRatio()
            w, h = int(pix.width() / dpr), int(pix.height() / dpr)
            label_box = QRect(col.crest_lbl.mapTo(win, QPoint(0, 0)), col.crest_lbl.size())
            origin = QPoint(label_box.x() + (label_box.width() - w) // 2,
                            label_box.y() + (label_box.height() - h) // 2)
            start = QRect(origin.x() + int(kept.x() / dpr), origin.y() + int(kept.y() / dpr),
                          max(1, int(kept.width() / dpr)), max(1, int(kept.height() / dpr)))
            fly = QLabel(overlay)
            fly.setScaledContents(True)
            fly.setPixmap(trimmed)
            fly.setStyleSheet("background: transparent;")
            fly.setGeometry(start)
            fly.show()
            self._flyers[side] = fly
            eff = QGraphicsOpacityEffect(col.crest_lbl)
            eff.setOpacity(0.0)
            col.crest_lbl.setGraphicsEffect(eff)
        overlay.show()
        overlay.raise_()
        self._overlay = overlay

    def _drop_overlay(self):
        overlay = getattr(self, "_overlay", None)
        if overlay is None:
            return
        for col in (self.home_col, self.away_col):
            stage = col.stage
            if stage.parentWidget() is overlay:
                stage.setParent(self)     # what _reset_kickoff_visuals expects
                stage.hide()
        overlay.hide()
        overlay.deleteLater()
        self._overlay = None
        self._flyers = {}

    def _begin_zoom_in(self):
        # Players keep their idle loop — only the "camera" moves, dollying
        # in on the point between the two of them. A zoom into that
        # barycentre pushes everything away from it in the frame, so each
        # player grows *and* slides toward whichever edge is already on
        # their side — home left, away right — until they run off it,
        # rather than the two of them converging into one blob at centre.
        #
        # The loading screen is switched to at the START of the zoom: the
        # players (moved onto the window-level overlay) keep zooming over it,
        # the crests fly to their places and the rest of the loading screen
        # fades in. Without a loading screen to hand it falls back to the old
        # behaviour (reveal it once the zoom is over).
        win = self.window()
        ingame = getattr(win, "screen_ingame", None)
        overlay = getattr(self, "_overlay", None)
        transition = ingame is not None and overlay is not None
        parent, offset = (overlay, self.mapTo(win, QPoint(0, 0))) if transition else (self, QPoint(0, 0))

        rects = {}
        for col in (self.home_col, self.away_col):
            stage = col.stage
            top_left = stage.mapTo(self, QPoint(0, 0))
            rect = stage.geometry()
            rect.moveTopLeft(top_left + offset)
            rects[col] = rect
        barycentre = QPoint(
            (rects[self.home_col].center().x() + rects[self.away_col].center().x()) // 2,
            (rects[self.home_col].center().y() + rects[self.away_col].center().y()) // 2)

        group = QParallelAnimationGroup(self)
        scale = 3.4
        for col in (self.home_col, self.away_col):
            stage = col.stage
            rect = rects[col]
            stage.freeze(scale)     # animate one finished image, not a live 3D render
            layout = stage.parentWidget().layout()
            if layout is not None:
                layout.removeWidget(stage)
            stage.setParent(parent)
            stage.setMinimumHeight(0)
            stage.setMaximumHeight(16777215)
            stage.setGeometry(rect)
            stage.show()
            stage.raise_()

            end_w, end_h = int(rect.width() * scale), int(rect.height() * scale)
            end_cx = barycentre.x() + (rect.center().x() - barycentre.x()) * scale
            end_cy = barycentre.y() + (rect.center().y() - barycentre.y()) * scale
            end_rect = QRect(int(end_cx - end_w / 2), int(end_cy - end_h / 2), end_w, end_h)
            anim = QPropertyAnimation(stage, b"geometry", self)
            anim.setDuration(WALKOFF_MS)
            anim.setStartValue(rect)
            anim.setEndValue(end_rect)
            # Accelerating, unlike the walk-off's steady InQuad — a dolly-in
            # starts slow and rushes at the end.
            anim.setEasingCurve(QEasingCurve.InCubic)
            group.addAnimation(anim)
        self._walkoff_group = group

        if not transition:
            group.finished.connect(self._finish_kickoff)
            group.start()
            return

        ingame.prepare_intro_transition()
        self.on_play_reveal()                 # loading screen on, match setup off

        def start_animations():
            # Players start zooming (and, over the run, fading out) right away.
            group.start()

            # The crests follow CREST_DELAY_MS later, in their own group, so
            # they visibly trail the players instead of moving in lockstep.
            crest_group = QParallelAnimationGroup(self)
            for side, fly in self._flyers.items():
                target, _pix = ingame.crest_display_rect(side, win)
                if target.isEmpty():
                    fly.hide()
                    continue
                anim = QPropertyAnimation(fly, b"geometry", self)
                anim.setDuration(WALKOFF_MS)
                anim.setStartValue(fly.geometry())
                anim.setEndValue(target)
                anim.setEasingCurve(QEasingCurve.InOutCubic)
                crest_group.addAnimation(anim)
            self._crest_group = crest_group
            crest_group.finished.connect(self._finish_zoom_transition)

            def start_crest_group():
                # Kickoff may have been reset (e.g. game exited) while we
                # were waiting out the delay — the flyers are gone by then.
                if self._kickoff_running and self._flyers:
                    crest_group.start()
            QTimer.singleShot(CREST_DELAY_MS, start_crest_group)

            # The rest of the loading screen (names, wheel...) fades in so its
            # own end lines up with the crests landing, not starting from there.
            fade_start = max(0, CREST_DELAY_MS + WALKOFF_MS - LOADING_FADE_MS)

            def start_loading_fade():
                if self._kickoff_running:
                    # Re-triggers the ring's 0%-start climb (see
                    # ingame._run_intro_climb) right as it becomes visible —
                    # otherwise the climb that began back when this screen
                    # was first switched to has already run ahead by the
                    # time the fade reveals it.
                    ingame.restart_loading_display()
                    ingame.play_intro_fade(LOADING_FADE_MS)
            QTimer.singleShot(fade_start, start_loading_fade)
        QTimer.singleShot(0, start_animations)

    def _finish_zoom_transition(self):
        ingame = getattr(self.window(), "screen_ingame", None)
        if ingame is not None:
            ingame.show_crests()
        self._drop_overlay()

    def _finish_kickoff(self):
        self.on_play_reveal()


class MatchSetupContainer(QWidget):
    """Owns the nested MatchSetup <-> LineupEdit sub-flow, same pattern the
    pre-redesign TeamSelectionMenu used."""

    def __init__(self, ds: DataStore, on_back, on_play_begin, on_play_reveal):
        super().__init__()
        self.ds = ds
        self.stack = QStackedWidget(self)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.stack)

        self.setup_screen = MatchSetupScreen(
            ds, on_back, on_play_begin, on_play_reveal, self._open_squad_editor,
            on_edit_mission=self._open_mission_editor)
        self.stack.addWidget(self.setup_screen)
        self._editing_side = None
        self.mission_editor_screen = None

    def prewarm(self):
        self.setup_screen.prewarm()

    def on_show(self):
        self.stack.setCurrentWidget(self.setup_screen)
        self.setup_screen.on_show()

    def _open_mission_editor(self, cfg):
        if self.mission_editor_screen is None:
            from screens.mission_editor import MissionEditorScreen
            self.mission_editor_screen = MissionEditorScreen(on_back=self._show_setup)
            self.stack.addWidget(self.mission_editor_screen)
        self.mission_editor_screen.bind(cfg)
        self.stack.setCurrentWidget(self.mission_editor_screen)
        self.mission_editor_screen.on_show()

    def _open_squad_editor(self, side, cfg):
        slot = cfg.home if side == "home" else cfg.away
        if not slot.team_id:
            return
        self._editing_side = side
        team_name = self.ds.teams[slot.team_id][slot.season].get("name", slot.team_id)
        widget = SquadEditorScreen(
            side, team_name, slot.players, deepcopy(slot.lineup),
            on_confirm=self._on_confirm,
            on_discard=self._show_setup,
        )
        self.stack.addWidget(widget)
        self.stack.setCurrentWidget(widget)
        widget.on_show()

    def _show_setup(self):
        self.stack.setCurrentWidget(self.setup_screen)

    def _on_confirm(self, data):
        self.setup_screen.refresh_after_lineup_edit(self._editing_side, data)
        self._show_setup()
