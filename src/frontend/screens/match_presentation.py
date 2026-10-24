"""
screens/match_presentation.py — Pre-match presentation for the game modes
=============================================================================
What CHALLENGE MODE and TOURNAMENT show between picking a match and kicking
it off: the two teams wearing their kits (the same 3D stage as match setup,
the kit's flat preview when 3D is off or unavailable), what the match is,
and whatever the mode leaves to the player.

The screen only displays and reports: the mode builds a Presentation, keeps
its own state, and is called back on every pick and on KICK OFF / BACK. A
kit the mode fixes is shown but cannot be changed.
"""
import os
import random
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QFrame, QScrollArea
from PyQt5.QtGui import QPixmap, QFont
from PyQt5.QtCore import Qt

from backend.mod_utils import stock_head_path
from shared.config import config
from app.screen_base import Screen
from app import variants as V
from app.game_data import frontend_logo
from ui import StyledButton
from ui.kickoff_transition import KickoffTransition
from ui.atmosphere import AtmosphereWidget
from ui.player_stage import KitStage
from ui.broadcast import Card, SelectorRow, HintBar, page_header, eyebrow_label, display_label
from ui.editor_kit import Note
from ui.theme import (
    ACCENT, HOME_TINT, AWAY_TINT, BORDER, FG_MUTED, FG_PRIMARY, FG_SECONDARY, T_VALUE, BTN_HEIGHT, T_TITLE,
)
from screens.match_setup import FACE_YAW, MANNEQUIN_POOL, _load_crest


@dataclass
class SideSpec:
    team_id: str
    season: str
    kit: str                        # key in the season's "kits"
    kit_locked: bool = False        # fixed by the mode: shown, not changeable
    variant: str = ""               # squad variant of the season ("" = default)
    kit_variant: str = ""           # variant of the kit (a tournament patch…), if it has it
    # kit fields (frontKitFile/backKitFile/previewFile, team-folder relative)
    # replacing the picked kit's: a mode's own kit, worn whatever is picked
    kit_override: dict = field(default_factory=dict)


@dataclass
class Choice:
    """One setting the player picks before kick-off."""
    label: str
    values: list
    value: object
    display: Callable = str
    apply: Optional[Callable] = None    # fn(value)


@dataclass
class Presentation:
    title: str
    breadcrumb: str
    home: SideSpec
    away: SideSpec
    eyebrow: str = "match"
    heading: str = ""
    briefing: str = ""
    details: List[str] = field(default_factory=list)
    objectives: List[str] = field(default_factory=list)   # shown in their own highlighted block
    choices: List[Choice] = field(default_factory=list)
    on_kit: Optional[Callable] = None        # fn(side, kit_key)
    on_kickoff: Optional[Callable] = None    # fn()
    on_back: Optional[Callable] = None       # fn()
    controlled: Optional[Callable] = None    # fn() -> sides the player controls
    # fn(side): EDIT SQUAD on each side the player controls (as in quick
    # match); the mode opens the squad editor and presents again after it
    on_edit_squad: Optional[Callable] = None


def _kit_assets(ds, team_id, season, key, kit_variant="", kit_override=None):
    """(flat preview path, front kit path, back-panel path, model3d) for one
    kit — the same files match setup's TeamColumn feeds its KitStage."""
    kit = V.resolve_kit(ds.team_season(team_id, season).get("kits", {}).get(key), kit_variant)
    kit.update(kit_override or {})
    root = ds.teams_folder_path.get(team_id, "")
    preview = os.path.join(root, kit.get("previewFile", "")) if kit.get("previewFile") else ""
    front = os.path.join(root, kit.get("frontKitFile", "")) if kit.get("frontKitFile") else ""
    back_pattern = kit.get("backKitFile", "")
    back = os.path.join(root, back_pattern.replace("%", "1", 1)) if back_pattern else ""
    return preview, front, back, kit.get("model3d")


class _SideCard(QWidget):
    """Crest + name, the kit on its stage, the kit selector."""

    def __init__(self, side, tint, screen):
        super().__init__()
        self.side = side
        self.tint = tint
        self.screen = screen
        self.spec = None
        self._head_path = None
        self._skin_entry = None
        self._pix_cache = {}
        self.setObjectName(f"presentSide{side}")
        self.setStyleSheet(f"QWidget#{self.objectName()} {{ background: transparent; }}")

        self.card = Card(stripe=tint, translucent=True)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.card)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(22, 16, 22, 16)
        v.setSpacing(10)

        self.eyebrow = eyebrow_label(side, color=tint, size=13)
        v.addWidget(self.eyebrow)

        ident = QHBoxLayout()
        ident.setSpacing(16)
        self.crest = self.crest_lbl = QLabel()
        self.crest.setFixedSize(96, 96)
        self.crest.setAlignment(Qt.AlignCenter)
        self.crest.setStyleSheet("background: transparent;")
        self.name = display_label("", T_TITLE + 4, QFont.Bold, track=0.8)
        self.name.setWordWrap(True)
        if side == "home":
            ident.addWidget(self.crest)
            ident.addWidget(self.name, stretch=1)
        else:
            self.name.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            ident.addWidget(self.name, stretch=1)
            ident.addWidget(self.crest)
        v.addLayout(ident)

        self.rule = QFrame()
        self.rule.setFixedHeight(1)
        self.rule.setStyleSheet(f"background: {BORDER}; border: none;")
        v.addWidget(self.rule)

        self.stage = KitStage(default_yaw=FACE_YAW if side == "home" else -FACE_YAW)
        self.stage.setMinimumHeight(180)
        v.addWidget(self.stage, stretch=1)

        self.kit_row = SelectorRow("kit", compact=True)
        self.kit_row.set_force_arrows(True)
        self.kit_row.changed.connect(self._on_kit)
        screen.focus.register(self.kit_row)
        v.addWidget(self.kit_row)

        self.squad_btn = StyledButton("EDIT SQUAD", "neutral")
        self.squad_btn.setMinimumHeight(BTN_HEIGHT)
        self.squad_btn.clicked.connect(self._on_squad)
        screen.focus.register(self.squad_btn)
        v.addWidget(self.squad_btn)
        self.squad_btn.hide()

    def chrome(self):
        """What the kickoff sequence fades out around the stage and crest."""
        return [self.eyebrow, self.name, self.rule, self.kit_row, self.squad_btn]

    def _on_squad(self):
        if self.screen.p and self.screen.p.on_edit_squad:
            self.screen.p.on_edit_squad(self.side)

    def restore_stage(self):
        """Puts the stage back in the card after the kickoff sequence took it
        out to animate it freely."""
        self.card.layout().insertWidget(3, self.stage)    # after eyebrow, identity, rule
        self.stage.setMinimumHeight(180)

    def set_mannequin(self, face_id, skin_entry):
        self._head_path = stock_head_path(face_id, os.path.join(config.temp_directory, "stock_heads"))
        self._skin_entry = skin_entry

    def set_spec(self, spec: SideSpec):
        ds = self.screen.ds
        self.spec = spec
        info = ds.team_season(spec.team_id, spec.season, spec.variant)
        self.name.setText((info.get("name") or spec.team_id or "?").upper())
        crest = _load_crest(os.path.join(ds.teams_folder_path.get(spec.team_id, ""),
                                         frontend_logo(info)))
        if crest.isNull():
            self.crest.clear()
            self.crest.setText("NO CREST")
            self.crest.setStyleSheet(f"color: {FG_MUTED}; background: transparent;")
        else:
            self.crest.setPixmap(crest.scaled(96, 96, Qt.KeepAspectRatio, Qt.SmoothTransformation))

        kits = list(info.get("kits", {})) or [spec.kit or "default"]
        index = kits.index(spec.kit) if spec.kit in kits else 0
        self.kit_row.set_values(kits, index=index)
        # A fixed kit stays readable but takes no input — and a disabled row
        # is skipped by pad/keyboard navigation (FocusManager.alive).
        custom = bool(spec.kit_override)
        locked = spec.kit_locked or custom or len(kits) < 2
        self.kit_row.set_label("kit · custom" if custom else "kit · fixed" if spec.kit_locked else "kit")
        self.kit_row.set_disabled_visual(locked)

    def set_controlled(self, controlled):
        self.eyebrow.setText(f"{self.side} · you".upper() if controlled else self.side.upper())
        p = self.screen.p
        self.squad_btn.setVisible(bool(controlled and p and p.on_edit_squad))

    def _on_kit(self):
        key = self.kit_row.current()
        self.spec.kit = key
        if self.screen.p and self.screen.p.on_kit:
            self.screen.p.on_kit(self.side, key)
        self.refresh_preview()

    def refresh_preview(self, load_3d=True):
        if self.spec is None or not self.spec.team_id:
            self.stage.set_placeholder()
            return
        preview, front, back, model3d = _kit_assets(self.screen.ds, self.spec.team_id,
                                                    self.spec.season, self.kit_row.current(),
                                                    self.spec.kit_variant, self.spec.kit_override)
        if preview not in self._pix_cache:
            self._pix_cache[preview] = QPixmap(preview) if preview and os.path.exists(preview) else None
        pix = self._pix_cache[preview]
        self.stage.update_kit(pix if pix and not pix.isNull() else None, front, back, model3d,
                              head_path=self._head_path, skin_entry=self._skin_entry,
                              load_3d=load_3d)


class MatchPresentationScreen(KickoffTransition, Screen):
    def __init__(self, ds, on_play_begin, on_play_reveal, parent=None):
        super().__init__(on_back=None, parent=parent)
        # Same split as match setup's: the backend starts the moment the
        # sequence does, the loading screen is only shown part-way through.
        self.on_play_begin = on_play_begin
        self.on_play_reveal = on_play_reveal
        self.on_back_cb = self._back
        self.ds = ds
        self.p = None
        self._choice_rows = []
        self._build()

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header_holder = QVBoxLayout()
        self.header_holder.setContentsMargins(0, 0, 0, 0)
        root.addLayout(self.header_holder)

        self._backdrop = AtmosphereWidget(self)
        self._backdrop.lower()
        body = QWidget()
        body.setObjectName("presentationBody")
        body.setStyleSheet("QWidget#presentationBody { background: transparent; }")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(80, 24, 80, 20)
        bl.setSpacing(24)

        self.home_card = _SideCard("home", HOME_TINT, self)
        self.away_card = _SideCard("away", AWAY_TINT, self)

        self.mid_card = mid = Card(translucent=True)
        mid.setMinimumWidth(340)
        mid.setMaximumWidth(420)
        # Eyebrow, title, objectives and choices always stay in view; only the
        # briefing (and the fixed-settings lines under it) scrolls, when it is
        # taller than the room left. Fits = no scrollbar.
        mv = QVBoxLayout(mid)
        mv.setContentsMargins(24, 18, 24, 20)
        mv.setSpacing(10)
        self.eyebrow = eyebrow_label("match", color=ACCENT, size=15)
        mv.addWidget(self.eyebrow)
        self.heading = display_label("", T_TITLE, QFont.Bold, track=0.8, upper=False)
        self.heading.setWordWrap(True)
        mv.addWidget(self.heading)
        self.text_scroll = QScrollArea()
        self.text_scroll.setWidgetResizable(True)
        self.text_scroll.setFrameShape(QFrame.NoFrame)
        self.text_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.text_scroll.setMinimumHeight(60)
        self.text_scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.text_scroll.viewport().setStyleSheet("background: transparent;")
        text_body = QWidget()
        text_body.setObjectName("presentationText")
        text_body.setStyleSheet("QWidget#presentationText { background: transparent; }")
        tv = QVBoxLayout(text_body)
        tv.setContentsMargins(0, 0, 10, 0)
        tv.setSpacing(10)
        self.briefing = Note("", color=FG_SECONDARY)
        tv.addWidget(self.briefing)
        self.details = Note("", color=FG_MUTED)
        tv.addWidget(self.details)
        tv.addStretch(1)
        self.text_scroll.setWidget(text_body)
        mv.addWidget(self.text_scroll, stretch=100)
        # Objectives: a framed block of their own, bigger and brighter than
        # the rest of the card.
        self.objectives_box = QFrame()
        self.objectives_box.setObjectName("objectivesBox")
        self.objectives_box.setStyleSheet(
            f"QFrame#objectivesBox {{ background: rgba(255,255,255,0.05);"
            f" border: 1px solid {ACCENT}; border-left: 4px solid {ACCENT}; border-radius: 6px; }}"
            " QFrame#objectivesBox QLabel { border: none; background: transparent; }")
        ov = QVBoxLayout(self.objectives_box)
        ov.setContentsMargins(14, 10, 14, 12)
        ov.setSpacing(6)
        ov.addWidget(eyebrow_label("objectives", color=ACCENT, size=13))
        self.objectives_hint = Note("All needed to win the challenge", color=FG_MUTED)
        ov.addWidget(self.objectives_hint)
        self.objectives_list = Note("", color=FG_PRIMARY, size=T_VALUE)
        self.objectives_list.setTextFormat(Qt.RichText)
        ov.addWidget(self.objectives_list)
        mv.addWidget(self.objectives_box)
        self.choices_label = eyebrow_label("your choices", color=ACCENT, size=12)
        mv.addWidget(self.choices_label)
        self.choices_grid = QGridLayout()
        self.choices_grid.setHorizontalSpacing(10)
        self.choices_grid.setVerticalSpacing(8)
        mv.addLayout(self.choices_grid)
        mv.addStretch(1)      # takes the room only when the text block is hidden

        bl.addWidget(self.home_card, stretch=5)
        bl.addWidget(mid, stretch=3)
        bl.addWidget(self.away_card, stretch=5)
        root.addWidget(body, stretch=1)

        bottom = QHBoxLayout()
        bottom.setContentsMargins(80, 0, 80, 20)
        bottom.addStretch(1)
        self.play_btn = StyledButton("KICK OFF", "primary")
        self.play_btn.setMinimumHeight(BTN_HEIGHT + 12)
        self.play_btn.setMinimumWidth(220)
        self.play_btn.clicked.connect(self._kickoff)
        self.focus.register(self.play_btn)
        bottom.addWidget(self.play_btn)
        root.addLayout(bottom)

        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "select"), ("B", "back")])
        root.addWidget(self.hintbar)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._backdrop.setGeometry(self.rect())
        self._backdrop.lower()

    # ── content ──────────────────────────────────────────────────────────
    def present(self, p: Presentation):
        """Fill the screen for `p`. 3D models load in on_show, once the
        screen is actually up."""
        self.p = p
        while self.header_holder.count():
            w = self.header_holder.takeAt(0).widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self.header_holder.addWidget(page_header(p.title, breadcrumb=p.breadcrumb,
                                                 on_back=self._back))
        self.eyebrow.setText(p.eyebrow.upper())
        self.heading.setText(p.heading)
        self.heading.setVisible(bool(p.heading))
        self.briefing.setText(p.briefing)
        self.briefing.setVisible(bool(p.briefing))
        details = "\n".join(d for d in p.details if d)
        self.details.setText(details)
        self.details.setVisible(bool(details))
        self.objectives_list.setText("<br>".join(f"▸&nbsp;<b>{o}</b>" for o in p.objectives))
        self.objectives_box.setVisible(bool(p.objectives))
        self._build_choices(p.choices)
        self.text_scroll.setVisible(bool(p.briefing or details))
        self.text_scroll.verticalScrollBar().setValue(0)

        home_pick, away_pick = random.sample(MANNEQUIN_POOL, 2)
        self.home_card.set_mannequin(*home_pick)
        self.away_card.set_mannequin(*away_pick)
        self.home_card.set_spec(p.home)
        self.away_card.set_spec(p.away)
        for card in (self.home_card, self.away_card):
            card.refresh_preview(load_3d=False)
        self._refresh_controlled()

    def _build_choices(self, choices):
        for row in self._choice_rows:
            self.focus.unregister(row)
            row.setParent(None)
            row.deleteLater()
        self._choice_rows = []
        for i, choice in enumerate(choices):
            row = SelectorRow(choice.label, compact=True)
            row._display = choice.display
            values = list(choice.values)
            row.set_values(values, index=values.index(choice.value) if choice.value in values else 0)
            row.changed.connect(lambda c=choice, r=row: self._on_choice(c, r))
            self.choices_grid.addWidget(row, i // 2, i % 2)
            self.focus.register(row)
            self._choice_rows.append(row)
        self.choices_label.setVisible(bool(choices))

    def _on_choice(self, choice, row):
        choice.value = row.current()
        if choice.apply:
            choice.apply(choice.value)
        self._refresh_controlled()

    def _refresh_controlled(self):
        sides = set(self.p.controlled()) if self.p and self.p.controlled else set()
        self.home_card.set_controlled("home" in sides)
        self.away_card.set_controlled("away" in sides)

    # ── kickoff transition hooks (ui/kickoff_transition.py) ──────────────
    def kt_columns(self):
        return self.home_card, self.away_card

    def kt_fade_widgets(self):
        return [*self.home_card.chrome(), *self.away_card.chrome(),
                self.mid_card, self.header_holder.itemAt(0).widget(),
                self.hintbar, self.play_btn]

    def on_show(self):
        super().on_show()
        self.reset_kickoff_visuals()
        for card in (self.home_card, self.away_card):
            card.refresh_preview()
        self.play_btn.setFocus()

    # ── actions ──────────────────────────────────────────────────────────
    def _kickoff(self):
        if self.p and self.p.on_kickoff:
            self.p.on_kickoff()

    def _back(self):
        if self.p and self.p.on_back:
            self.p.on_back()
