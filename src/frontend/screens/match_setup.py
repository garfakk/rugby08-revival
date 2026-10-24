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
    QScrollArea, QGridLayout,
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
from app.state import CONTROLLER_SLOTS, DataStore, MatchConfig, TeamSlot
from app import difficulty
from app import variants as V
from app.match_data_builder import build_match_data
from app.game_data import (
    SNOW_INTENSITY_MAX, WIND_BEARINGS, WIND_POWER_NAMES, frontend_logo, wind_direction_label,
)
from app.season import season_label
from app.shell import present
from ui import StyledButton
from ui.player_stage import KitStage, _try_load_model
from ui.dropdown import DropdownRow
from ui.atmosphere import AtmosphereWidget
from ui.kickoff_transition import KickoffTransition, WALKOFF_MS
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

ADVANCED_PANEL_W = 520   # slide-over width; also its travel (see ui/side_panel.py)


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
        self.kit_row.changed.connect(self._on_kit_changed)
        screen.focus.register(self.kit_row)
        chrome_bottom_v.addWidget(self.kit_row)

        # Variants of the picked kit itself (a tournament patch…) — only
        # shown when that kit has one. The squad variant is picked in the
        # squad editor, independently.
        self.kit_variant_row = SelectorRow("variant", display=self._kit_variant_label,
                                           compact=True)
        self.kit_variant_row.set_force_arrows(True)
        self.kit_variant_row.changed.connect(self._on_kit_variant_changed)
        screen.focus.register(self.kit_variant_row)
        chrome_bottom_v.addWidget(self.kit_variant_row)
        self.kit_variant_row.hide()
        # The variant last picked by hand: kept while switching kits, so
        # home → away → home with a World Cup patch keeps the patch.
        self._wanted_kit_variant = ""

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

    def restore_stage(self):
        """Puts the stage back between the two chrome wrappers after the
        kickoff sequence reparented it."""
        self.card.layout().insertWidget(1, self.stage)
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

    def _stored_kit(self):
        """The picked kit as stored (with its "variants")."""
        return self._slot().kits(self.screen.ds).get(self.kit_row.current() or "", {})

    def _kit_variant_label(self, vid):
        return V.kit_variant_label(self._stored_kit(), vid)

    def _sync_kit_variants(self):
        """Refill the variant row for the picked kit; hidden without any."""
        ids = V.kit_variant_ids(self._stored_kit())
        values = [""] + ids
        want = self._wanted_kit_variant if self._wanted_kit_variant in ids else ""
        self.kit_variant_row.set_values(values, index=values.index(want))
        self.kit_variant_row.setVisible(bool(ids))

    def _on_kit_changed(self):
        self._sync_kit_variants()
        self._refresh_kit_preview()

    def _on_kit_variant_changed(self):
        self._wanted_kit_variant = self.kit_variant_row.current() or ""
        self._refresh_kit_preview()

    def _on_team_changed(self):
        """Team picked: back to its default squad (a competition squad is
        picked in the squad editor), then load it."""
        slot = self._slot()
        tid = self.name_picker.current()
        slot.team_id = tid
        slot.variant = ""
        if not tid:
            return
        self._load_team()

    def _load_crest(self):
        ds = self.screen.ds
        slot = self._slot()
        info = slot.info(ds)
        crest_path = os.path.join(ds.teams_folder_path.get(slot.team_id, ""),
                                   frontend_logo(info))
        self._crest_src = _load_crest(crest_path)
        if not self._crest_src.isNull():
            self._apply_crest()
        else:
            self.crest_lbl.clear()
            self.crest_lbl.setText("NO CREST")
            self.crest_lbl.setStyleSheet(f"color: {FG_MUTED}; background: transparent;")

    def _load_team(self):
        ds = self.screen.ds
        slot = self._slot()
        self._load_crest()
        slot.lineup = ds.get_lineup(slot.team_id, slot.season, slot.variant)
        slot.players = ds.get_players(slot.lineup.get("players_id", []), slot.season)

        # Home side opens on its home kit, away side on its away kit —
        # the usual pairing, and it stops both sides showing the same
        # strip. Falls back to the first kit when a side isn't named.
        kit_keys = list(slot.kits(ds)) or ["default"]
        preferred = "home" if self.side == "home" else "away"
        kit_index = kit_keys.index(preferred) if preferred in kit_keys else 0
        self.kit_row.set_values(kit_keys, index=kit_index)
        self._wanted_kit_variant = ""
        self._sync_kit_variants()
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
        self._apply_kit_choice()
        kit = slot.kit(ds)
        team_root = ds.teams_folder_path.get(slot.team_id, "")
        # backKitFile is the shirt's own back panel ("jbck") — without it that
        # panel falls back to plain white. It ships as a %-pattern, one image
        # per shirt number (home_back_1.png, ...); "1" stands in since this
        # preview isn't tied to a specific player.
        kit_source = os.path.join(team_root, kit.get("frontKitFile", "")) if kit else ""
        back_pattern = kit.get("backKitFile", "") if kit else ""
        back_source = os.path.join(team_root, back_pattern.replace("%", "1", 1)) if back_pattern else ""
        return kit, kit_source, back_source

    def _apply_kit_choice(self):
        """Store the kit and variant rows' picks on the slot; returns the
        kit key."""
        slot = self._slot()
        key = self.kit_row.current() or ""
        keys = list(slot.kits(self.screen.ds))
        slot.kit_index = keys.index(key) if key in keys else 0
        slot.kit_variant = (self.kit_variant_row.current() or "") \
            if self.kit_variant_row.has_values() else ""
        return key

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
        key = self._apply_kit_choice()
        kit = slot.kit(ds)
        team_root = ds.teams_folder_path.get(slot.team_id, "")
        fp = os.path.join(team_root, kit.get("previewFile", ""))
        cache_key = (slot.team_id, slot.season, slot.kit_variant, key)
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


class MatchSetupScreen(KickoffTransition, Screen):
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
        self._toss = None              # the coin toss overlay while it runs
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
        self.reset_kickoff_visuals()
        self._apply_expert_mode()      # picks up a Settings toggle flipped meanwhile
        self._apply_coin_toss_lock()   # same, for Settings > Coin Toss Before Match
        # Settings > Wind: Advanced = a fresh random strength each time the
        # screen opens (editable); Standard = no row, the game's own wind.
        self.wind_power_row.setVisible(user_prefs.wind_mode == "advanced")
        self.wind_power_row.set_values(
            list(WIND_POWER_NAMES), index=random.randrange(len(WIND_POWER_NAMES)))
        self._on_wind_changed()
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

    def _apply_coin_toss_lock(self):
        """With the coin toss on, the toss decides who kicks off and which
        end each team takes — the two rows show that instead of a value and
        take no input (a disabled row is skipped by pad/keyboard navigation).
        cfg keeps their values for when the toss is turned off again."""
        locked = user_prefs.coin_toss
        for row in (self.side_row, self.kickoff_row):
            row.set_free_text("coin toss" if locked else None)
            row.set_disabled_visual(locked)

    def _on_wind_changed(self):
        """Strength None = the game's stock random wind (rolled by the
        backend), 0 = none. The direction (relative to home, see
        app.game_data) only matters for a set strength."""
        power = self.wind_power_row.current() if user_prefs.wind_mode == "advanced" else None
        self.cfg.wind_power = power
        # wind_dir_row stays hidden (random direction each match)
        direction = self.wind_dir_row.current()
        if direction is not None:
            self.cfg.wind_dir_deg = float(direction)

    # ── kickoff transition hooks (ui/kickoff_transition.py) ──────────────
    def kt_columns(self):
        return self.home_col, self.away_col

    def kt_fade_widgets(self):
        return [self.home_col._chrome_top, self.home_col._chrome_bottom,
                self.away_col._chrome_top, self.away_col._chrome_bottom,
                self.mid_col, self.header_widget, self.hintbar, self.play_btn]

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
        self.difficulty_row.set_values(difficulty.LEVELS, index=difficulty.LEVELS.index("elite"))
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

        # Wind (the reR08 wind patch): strength and direction, each can be
        # left on "random" (strength: the game's own wind; direction: a fresh
        # one at each kick-off, see _play).
        self.wind_power_row = SelectorRow("wind")
        self.wind_power_row.set_values(list(WIND_POWER_NAMES), index=0)   # re-rolled in on_show
        self.wind_power_row._display = lambda n: WIND_POWER_NAMES.get(n, str(n))
        self.wind_power_row.changed.connect(self._on_wind_changed)
        self.focus.register(self.wind_power_row)
        v.addWidget(self.wind_power_row)
        self.wind_dir_row = SelectorRow("wind direction")
        self.wind_dir_row.set_values([None] + list(WIND_BEARINGS), index=0)
        self.wind_dir_row._display = lambda d: "random" if d is None else wind_direction_label(d)
        self.wind_dir_row.changed.connect(self._on_wind_changed)
        # Temporarily hidden: direction stays on "random" (rolled per match
        # in _play). Re-enable: register in focus + restore setVisible in
        # _on_wind_changed.
        v.addWidget(self.wind_dir_row)
        self.wind_dir_row.setVisible(False)

        self.advanced_btn = StyledButton("ADVANCED", "neutral")
        self.advanced_btn.setMinimumHeight(BTN_HEIGHT)
        self.advanced_btn.clicked.connect(self.toggle_advanced)
        self.focus.register(self.advanced_btn)
        v.addWidget(self.advanced_btn)
        wv.addWidget(card)
        wv.addSpacing(14)

        # Controllers — its own container below the match card: the
        # keyboard and up to three gamepads, each given to a team (or left
        # off). They become the .mis c0..c3 the reR08 controllers patch reads
        # (keyboard = the game's device 0, pads in their connection order);
        # a pad that isn't plugged in is simply absent in game. Every device
        # off = CPU vs CPU.
        controls_card = Card(translucent=True)
        cv = QVBoxLayout(controls_card)
        cv.setContentsMargins(24, 18, 24, 20)
        cv.setSpacing(10)
        cv.addWidget(eyebrow_label("Controllers", color=ACCENT, size=15))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(10)
        self.controller_rows = {}
        for i, (slot_id, kind, label) in enumerate(CONTROLLER_SLOTS):
            row = SelectorRow(label.lower(), compact=True)
            zones = [("home", "home"), ("away", "away"), ("off", "none")]
            row.set_values(zones, index=0 if kind == "kbd" else len(zones) - 1)
            row._display = lambda t: t[0]
            row.changed.connect(lambda slot_id=slot_id: self._on_controller_zone_changed(slot_id))
            self.focus.register(row)
            grid.addWidget(row, i // 2, i % 2)
            self.controller_rows[slot_id] = row
        cv.addLayout(grid)
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

        # Only two pitch-logo packs ship today (data/competitions/*/assets/pitch_logos)
        # — "none" forces no logo; any tournament choice forces that pack.
        # Defaults to the "Default" pack rather than "none" so picking a
        # pitch logo isn't itself a hidden extra step.
        from app import competition_branding
        self._pitch_logo_choices = [("none", "none")] + competition_branding.choices(self.ds, "pitch_logo")
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
        # ("pads"): taken from the tournaments' own files, one entry per
        # season that has the file on disk, both defaulting to the "Default"
        # tournament.
        def tournament_choices(key):
            return competition_branding.choices(self.ds, key)

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
        for label in ("referee",):
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
        """The weather extras reR08 supports beyond the plain rain toggle
        above (wind lives on the match card — see _build_mid_column). Every row here is additive/optional at the MatchConfig
        level (see its own comment) — leaving all of them at their default
        produces the exact same .mis this screen has always produced."""
        v.addWidget(eyebrow_label("WEATHER", color=ACCENT, size=13))

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

    # ── controllers (keyboard + 3 gamepads, no pad detection) ─────────────
    def _init_devices(self):
        # Matches each row's own default: keyboard home, pads off.
        self.cfg.controllers = {
            slot_id: {"kind": kind, "label": label, "zone": "home" if kind == "kbd" else "none"}
            for slot_id, kind, label in CONTROLLER_SLOTS}

    def _on_controller_zone_changed(self, slot_id):
        zone = self.controller_rows[slot_id].current()
        default = "home" if self.cfg.controllers[slot_id]["kind"] == "kbd" else "none"
        self.cfg.controllers[slot_id]["zone"] = zone[1] if zone else default

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
            info = slot.info(self.ds)
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

    def refresh_after_lineup_edit(self, side, data, variant="", players=None):
        slot = self.cfg.home if side == "home" else self.cfg.away
        if variant != slot.variant:
            slot.variant = variant
            slot.players = players or {}
        slot.lineup = data

    def _play(self):
        if self._kickoff_running or self._toss is not None:
            return
        # Direction left on "random": a fresh one each match.
        if self.wind_dir_row.current() is None:
            self.cfg.wind_dir_deg = float(random.choice(WIND_BEARINGS))
        if user_prefs.coin_toss:
            from ui.coin_toss import toss_for_match
            self._toss = toss_for_match(self, self.ds, self.cfg,
                                        self._on_toss_done, self._on_toss_cancelled)
            return
        self._launch(self.cfg)

    def _on_toss_done(self, cfg):
        self._toss = None
        self._launch(cfg)

    def _on_toss_cancelled(self):
        self._toss = None
        self.play_btn.setFocus()

    def _launch(self, cfg):
        match_data = build_match_data(self.ds, cfg)
        if match_data is None:
            return
        self.start_kickoff_sequence(match_data)

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
        present(self.stack, self.mission_editor_screen)

    def _open_squad_editor(self, side, cfg):
        slot = cfg.home if side == "home" else cfg.away
        if not slot.team_id:
            return
        self._editing_side = side
        team_name = slot.info(self.ds).get("name", slot.team_id)
        tid, season = slot.team_id, slot.season
        block = self.ds.teams.get(tid, {}).get(season, {})
        # Only variants with a squad of their own: a kit-only variant is the
        # default squad, and its kit is picked on the setup card.
        variants = [(vid, V.variant_label(block, vid)) for vid in V.variant_ids(block)
                    if "players" in V.overrides(block, vid)]

        def load_variant(vid):
            lineup = self.ds.get_lineup(tid, season, vid)
            return self.ds.get_players(lineup.get("players_id", []), season), lineup

        widget = SquadEditorScreen(
            side, team_name, slot.players, deepcopy(slot.lineup),
            on_confirm=self._on_confirm,
            on_discard=self._show_setup,
            variants=variants, variant=slot.variant, load_variant=load_variant,
        )
        self.stack.addWidget(widget)
        present(self.stack, widget)

    def _show_setup(self):
        present(self.stack, self.setup_screen, call_on_show=False)

    def _on_confirm(self, data, variant="", players=None):
        self.setup_screen.refresh_after_lineup_edit(self._editing_side, data, variant, players)
        self._show_setup()
