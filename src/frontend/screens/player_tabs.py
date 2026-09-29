"""
screens/player_tabs.py — the three tabs of the player editor
==============================================================
Profile (identity + positions + physical), Ratings (24 ratings in six
groups with season-on-season deltas), Appearance (cosmetics + preview).
Identity keys live at the record's top level; everything else belongs to
the season picked in the header.
"""
import os
from datetime import datetime

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QSizePolicy
from PyQt5.QtGui import QPainter, QColor, QPen, QFont
from PyQt5.QtCore import Qt, QRectF, pyqtSignal

from backend import game_specific_variables as gsv
from backend.mod_utils import stock_portrait_path
from app import appearance as A
from app import team_ops as T
from app import player_ops as P
from app.game_data import (
    POSITIONS, POSITION_ALIASES, SKIN_TONES, TAPES, FEET, SOCKS, BOOT_STYLES,
    SHIRT_POSITIONS,
)
from app.ratings import GROUPS, LABELS, group_avg, position_overall, previous_season
from app.season import season_label
from app import plugin_lookup
from ui.broadcast import tracked_font, display_label, eyebrow_label
from ui.editor_kit import (
    FieldGrid, SectionCard, TextField, NumberField, RatingField, ChoiceField, SegmentField,
    Note, Thumb, compact_button, browse_assets, load_pixmap, Badge, ToggleGrid,
    LayerStackField,
)
from ui.dropdown import PopupList
from ui.face_picker import FacePicker
from ui.team_sheet import SHEET_ROWS, POSITION_NAMES, POSITION_SHORT
from ui.face_thumbs import face_thumbnail
from ui.theme import (
    BG_BASE, BG_RAISED, BORDER, ACCENT, WARN, GREEN, INFO, DANGER_LITE, HOME_TINT,
    FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FG_MUTED, FONT_DISPLAY,
    T_SMALL, T_LABEL, T_VALUE, T_TITLE,
)
from shared.config import config

TAB_PROFILE, TAB_RATINGS, TAB_APPEARANCE, TAB_SKILLS, TAB_TEAMS = range(5)


from shared.log import get_logger

log = get_logger(__name__)


def position_name(p):
    return POSITION_NAMES.get(p, p.replace("_", " "))


def normalise_birthdate(text):
    t = (text or "").strip()
    digits = "".join(c for c in t if c.isdigit())
    if len(digits) == 8 and not any(c in t for c in "/-."):
        return f"{digits[:4]}/{digits[4:6]}/{digits[6:]}"
    return t.replace("-", "/").replace(".", "/")


class PlayerTab:
    def __init__(self, screen, index):
        self.screen = screen
        self.index = index
        self.page = screen.shell.page(index)
        self.body = self.page.layout_

    def record(self):
        return self.screen.session.working if self.screen.session else {}

    def stats(self):
        return self.screen.stats()

    def edit_identity(self, label, key, value):
        self.screen.edit(label, lambda r: r.__setitem__(key, value),
                         coalesce_key=key, view_hint={"tab": self.index, "field": key})

    def edit_stat(self, label, key, value, coalesce=True):
        season = self.screen.season
        self.screen.edit(label, lambda r: r.setdefault("stats", {}).setdefault(season, {})
                         .__setitem__(key, value),
                         coalesce_key=f"{season}.{key}" if coalesce else None,
                         view_hint={"season": season, "tab": self.index, "field": key})

    def register(self, key, widget):
        return self.screen.register_field(key, widget, self.index)

    def hints(self, focused):
        return []


# ═════════════════════════════════════════════════════════════════════════
class PitchFit(QWidget):
    """The 15 starting shirts in team-sheet layout, lit where the player's
    positions fit."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(170, 150)
        self.fits = {}      # shirt -> rank (0 primary, 1, 2)

    def set_fits(self, fits):
        self.fits = fits
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.fillRect(self.rect(), QColor("#0f1a14"))
        p.setPen(QPen(QColor("#1f3a2a"), 1))
        p.drawRect(QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5))
        rows = len(SHEET_ROWS)
        for r, shirts in enumerate(SHEET_ROWS):
            y = 16 + r * (self.height() - 30) / (rows - 1)
            for c, n in enumerate(shirts):
                x = self.width() * (c + 1) / (len(shirts) + 1)
                rank = self.fits.get(n)
                colour = {0: ACCENT, 1: "#c9a13a", 2: "#8d7a3e"}.get(rank, BG_RAISED)
                p.setBrush(QColor(colour))
                p.setPen(QPen(QColor(BORDER), 1))
                p.drawEllipse(QRectF(x - 9, y - 9, 18, 18))
                p.setPen(QColor(BG_BASE if rank is not None else FG_TERTIARY))
                p.setFont(tracked_font(FONT_DISPLAY, 8, QFont.Bold, 0))
                p.drawText(QRectF(x - 9, y - 9, 18, 18), Qt.AlignCenter, str(n))


class ProfileTab(PlayerTab):
    def __init__(self, screen, index):
        super().__init__(screen, index)
        row = QHBoxLayout()
        row.setSpacing(14)
        left = QVBoxLayout()
        left.setSpacing(12)
        right = QVBoxLayout()
        right.setSpacing(12)

        # Identity (display name, birthdate, ...) lives in the always-on
        # identity pane above now — see player_editor.py's
        # _build_identity_pane — since it's the same in every season, not a
        # property of whichever one happens to be selected here.

        phys = SectionCard("physical")
        g = FieldGrid(columns=1)
        self.height_f = self.register("height", NumberField("Height (cm)", 100, 230))
        self.height_f.set_hint("game uses 180")
        self.height_f.edited.connect(lambda v: self.edit_stat("height", "height", v))
        g.add(self.height_f)
        self.weight_f = self.register("weight", NumberField("Weight (kg)", 40, 160))
        self.weight_f.set_hint("game uses 80")
        self.weight_f.edited.connect(lambda v: self.edit_stat("weight", "weight", v))
        g.add(self.weight_f)
        self.foot = self.register("foot", SegmentField("Stronger foot", FEET,
                                                        display=lambda v: v.replace("_footed", "")))
        self.foot.edited.connect(lambda v: self.edit_stat("foot", "foot", v, coalesce=False))
        g.add(self.foot)
        self.nationality = self.register("nationality", TextField("Nationality"))
        self.nationality.edited.connect(lambda v: self.edit_stat("nationality", "nationality", v))
        g.add(self.nationality)
        phys.add(g)
        left.addWidget(phys)
        left.addStretch(1)

        pos = SectionCard("positions")
        prow = QHBoxLayout()
        prow.setSpacing(14)
        pg = FieldGrid(columns=1)
        self.positions = {}
        for key, label in (("position1", "Primary"), ("position2", "Second"), ("position3", "Third")):
            f = self.register(key, ChoiceField(label, POSITIONS, display=position_name,
                                               allow_blank=(key != "position1"),
                                               blank_label="— none"))
            f.popup_title = f"{label.lower()} position"
            f.tag_for = lambda v: (POSITION_SHORT.get(v, ""), FG_TERTIARY)
            f.edited.connect(lambda v, k=key: self.edit_stat(k.replace("position", "position "),
                                                              k, v, coalesce=False))
            pg.add(f)
            self.positions[key] = f
        pcol = QVBoxLayout()
        pcol.addWidget(pg)
        self.fit_note = Note("", color=FG_SECONDARY, size=T_LABEL)
        pcol.addWidget(self.fit_note)
        self.fix_btn = compact_button("FIX GENERIC POSITION")
        self.fix_btn.clicked.connect(self._fix_positions)
        screen.focus.register(self.fix_btn)
        pcol.addWidget(self.fix_btn)
        pcol.addStretch(1)
        prow.addLayout(pcol, stretch=1)
        self.pitch = PitchFit()
        prow.addWidget(self.pitch, alignment=Qt.AlignTop)
        pos.add_layout(prow)
        right.addWidget(pos)

        squads = SectionCard("squads · every season")
        self.squads_note = Note("", color=FG_SECONDARY, size=T_LABEL)
        squads.add(self.squads_note)
        self.squad_buttons = QVBoxLayout()
        self.squad_buttons.setSpacing(4)
        squads.add_layout(self.squad_buttons)
        self._squad_btns = []
        for _ in range(4):
            b = compact_button("", height=32)
            b.setStyleSheet(b.styleSheet() + "QPushButton { text-align: left; }")
            b.hide()
            screen.focus.register(b)
            self.squad_buttons.addWidget(b)
            self._squad_btns.append(b)
        right.addWidget(squads)

        danger = SectionCard("player record")
        self.file_note = Note("", color=FG_TERTIARY)
        danger.add(self.file_note)
        self.delete_btn = compact_button("DELETE PLAYER…", "danger")
        self.delete_btn.clicked.connect(screen.delete_record)
        screen.focus.register(self.delete_btn)
        danger.add(self.delete_btn)
        right.addWidget(danger)
        right.addStretch(1)

        row.addLayout(left, stretch=5)
        row.addLayout(right, stretch=4)
        self.body.addLayout(row)

    def _fix_positions(self):
        stats = self.stats()
        fixes = {k: POSITION_ALIASES[stats.get(k)] for k in ("position1", "position2", "position3")
                 if stats.get(k) and stats.get(k) not in POSITIONS and stats.get(k) in POSITION_ALIASES}
        if not fixes:
            return
        season = self.screen.season
        self.screen.edit("fix positions", lambda r: r["stats"][season].update(fixes),
                         view_hint={"season": season, "tab": self.index})
        self.screen.shell.footer.set_status(
            "Rewrote " + ", ".join(f"{k.replace('position', 'position ')} → {position_name(v)}"
                                   for k, v in fixes.items()) + " (Ctrl+Z to undo)", GREEN)

    def refresh(self):
        record = self.record()
        stats = self.stats()
        season = self.screen.season
        self.height_f.set_value(stats.get("height", ""))
        self.weight_f.set_value(stats.get("weight", ""))
        self.foot.set_value(stats.get("foot", ""))
        self.nationality.set_value(stats.get("nationality", ""))
        for key, f in self.positions.items():
            f.set_value(stats.get(key, ""))
        fits = {}
        for shirt in range(1, 16):
            rank = T.fit_rank({"stats": {season: stats}}, season, shirt)
            if rank is not None and (stats.get("position1") or stats.get("position2")):
                fits[shirt] = rank
        self.pitch.set_fits(fits)
        shirts = sorted(fits)
        self.fit_note.setText(("Fits shirt" + ("s " if len(shirts) > 1 else " ") +
                               ", ".join(map(str, shirts))) if shirts else
                              "Fits no starting shirt — check the positions.")
        generic = [stats.get(k) for k in self.positions if stats.get(k) in POSITION_ALIASES]
        self.fix_btn.setVisible(bool(generic))
        if generic:
            self.fix_btn.setText(f"REWRITE “{generic[0]}” AS {position_name(POSITION_ALIASES[generic[0]]).upper()}")
        sources = self.screen.ds.players_sources.get(self.screen.record_id, [])
        self.file_note.setText("Defined in " + ", ".join(os.path.basename(x) for x in sources)
                               + ("  — the last one is used" if len(sources) > 1 else ""))
        memberships = self.screen.ds.memberships(self.screen.record_id)
        self.squads_note.setText(f"In {len(memberships)} squad list(s)." if memberships else
                                 "Not in any squad.")
        for i, b in enumerate(self._squad_btns):
            try:
                b.clicked.disconnect()
            except TypeError:
                pass
            if i < len(memberships):
                tid, name, s, shirt = memberships[i]
                role = "starter" if shirt <= 15 else ("bench" if shirt <= 22 else "not loaded")
                b.setText(f"{name}  {s}  ·  #{shirt} {role}   →")
                b.clicked.connect(lambda _=False, t=tid, ss=s, sh=shirt: self.screen.open_team(t, ss, sh))
                b.show()
            else:
                b.hide()

    def hints(self, focused):
        if isinstance(focused, NumberField):
            return [("0-9", "type"), ("←→", "adjust"), ("Del", "clear")]
        if isinstance(focused, (TextField,)):
            return [("A", "edit")]
        return []


# ═════════════════════════════════════════════════════════════════════════
class RatingsTab(PlayerTab):
    def __init__(self, screen, index):
        super().__init__(screen, index)
        strip = QHBoxLayout()
        strip.setSpacing(14)
        self.ovr = display_label("OVR —", T_TITLE, QFont.Bold, track=0.6, upper=False)
        strip.addWidget(self.ovr)
        self.ovr_note = Note("", color=FG_SECONDARY, size=T_LABEL)
        strip.addWidget(self.ovr_note, stretch=1)
        self.copy_btn = compact_button("COPY RATINGS FROM…")
        self.copy_btn.clicked.connect(self._copy_menu)
        screen.focus.register(self.copy_btn)
        strip.addWidget(self.copy_btn)
        self.body.addLayout(strip)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(12)
        self.fields = {}
        self.group_labels = {}
        for i, (name, keys) in enumerate(GROUPS):
            avg = display_label("", T_LABEL, QFont.Bold, track=0.6, color=FG_SECONDARY, upper=False)
            card = SectionCard(name, right=avg)
            fg = FieldGrid(columns=1, v_spacing=2)
            for key in keys:
                f = self.register(key, RatingField(LABELS[key]))
                f.edited.connect(lambda v, k=key: self.edit_stat(LABELS[k].lower(), k, v))
                fg.add(f)
                self.fields[key] = f
            card.add(fg)
            card.v.addStretch(1)
            self.group_labels[name] = avg
            grid.addWidget(card, i // 3, i % 3)
        self.body.addLayout(grid)
        self.body.addStretch(1)

    def _copy_menu(self):
        from ui.dropdown import PopupList
        seasons = [s for s in (self.record().get("stats") or {}) if s != self.screen.season]
        popup = PopupList(self.screen, width=300, height=260, own_keys=True)
        popup.set_title(f"copy ratings into {season_label(self.screen.season)}")
        for s in sorted(seasons, reverse=True):
            popup.add_row(f"From {season_label(s)}", s,
                         subtitle=f"OVR {position_overall(self.record()['stats'][s])}")
        if not seasons:
            popup.add_row("this player has no other season", None, disabled=True)
        popup.size_to(max(1, len(seasons)))
        popup.picked.connect(self._copy_from)
        popup.open_at(self.copy_btn, self.screen)

    def _copy_from(self, source):
        if not source:
            return
        target = self.screen.season
        counter = {}

        def fn(r):
            counter["n"] = P.copy_ratings(r, source, target)
        self.screen.edit(f"copy ratings from {season_label(source)}", fn,
                         view_hint={"season": target, "tab": self.index})
        self.screen.shell.footer.set_status(
            f"Copied {counter.get('n', 0)} rating(s) from {season_label(source)} (Ctrl+Z to undo)", GREEN)

    def copy_previous_value(self, field):
        prev = previous_season(self.record(), self.screen.season)
        if not prev or field.key not in self.fields:
            return False
        value = (self.record()["stats"][prev] or {}).get(field.key, "")
        if value:
            self.edit_stat(f"{LABELS[field.key].lower()} from {season_label(prev)}", field.key, value,
                           coalesce=False)
        return True

    def refresh(self):
        stats = self.stats()
        record = self.record()
        prev_key = previous_season(record, self.screen.season)
        prev = (record.get("stats") or {}).get(prev_key) if prev_key else None
        for key, f in self.fields.items():
            f.set_value(stats.get(key, ""))
            f.set_reference(prev.get(key) if prev else None)
        for name, keys in GROUPS:
            avg = group_avg(stats, keys)
            text = f"AVG {avg}" if avg is not None else "AVG —"
            if prev:
                pavg = group_avg(prev, keys)
                if avg is not None and pavg is not None and avg != pavg:
                    d = avg - pavg
                    text += f"  {'▲' if d > 0 else '▼'}{abs(d)}"
            self.group_labels[name].setText(text)
        pos = stats.get("position1", "")
        ovr = position_overall(stats, pos)
        self.ovr.setText(f"OVR {ovr if ovr is not None else '—'}")
        note = f"as {position_name(pos).lower()}" if pos in POSITIONS else "no roster position"
        if prev:
            pov = position_overall(prev, pos)
            if pov is not None and ovr is not None:
                d = ovr - pov
                note += f"  ·  {'+' if d >= 0 else '−'}{abs(d)} vs {season_label(prev_key)}"
        self.ovr_note.setText(note)
        self.copy_btn.setEnabled(len(record.get("stats") or {}) > 1)

    def hints(self, focused):
        if isinstance(focused, RatingField):
            return [("0-9", "type"), ("←→", "±1"), ("⇧←→", "±5"), ("Y", "previous season")]
        return []


# ═════════════════════════════════════════════════════════════════════════
class AppearanceTab(PlayerTab):
    """Everything the game paints on the player: the skin (a stock tone or a
    custom texture), the layers painted over it bottom to top (strap,
    bottom baselayer, top baselayer, gloves — see LAYER_SECTIONS), the
    boots, and the stock roster bits (face, socks, tapes). All four layer
    kinds still live in the one `skin_overlay` list backend/game_files_processor
    and app/appearance already read — this tab just splits that flat list
    into four dedicated stacks by asset folder (and, for baselayers, by the
    baselayer_top_*/baselayer_bottom_* filename convention) and reassembles
    it in LAYER_SECTIONS order on every edit."""

    #: (zone key, UI label, asset kind) — also the fixed bottom-to-top
    #: compositing order, both on screen and in the reassembled skin_overlay.
    LAYER_SECTIONS = [
        ("straps", "strap", "straps"),
        ("baselayer_bottom", "bottom baselayer", "baselayers"),
        ("baselayer_top", "top baselayer", "baselayers"),
        ("gloves", "gloves", "gloves"),
    ]

    def __init__(self, screen, index):
        super().__init__(screen, index)
        left = QVBoxLayout()
        left.setSpacing(12)

        # ── skin ─────────────────────────────────────────────────────────
        skin_card = SectionCard("skin")
        g = FieldGrid(columns=1)
        self.skin = self.register("skin", ChoiceField("Skin", allow_blank=False))
        self.register("skin_tone", self.skin)   # same widget answers for both keys
        self.skin.popup_title = "skin"
        self.skin.display = self._skin_display
        self.skin.off_list_badge = False
        self.skin.subtitle_for = lambda v: ("browse for a file" if v == "__file__" else
                                            "stock skin tone" if v in SKIN_TONES else
                                            "custom texture · 512×256")
        self.skin.edited.connect(self._on_skin)
        g.add(self.skin)
        skin_card.add(g)

        left.addWidget(skin_card)

        # ── layers: strap, bottom baselayer, top baselayer, gloves ─────────
        # Four dedicated stacks instead of one mixed one, each multi-layer,
        # composited bottom to top in this fixed order onto the skin above.
        self.layer_stacks = {}
        for zone, label, kind in self.LAYER_SECTIONS:
            card = SectionCard(label)
            stack = LayerStackField(show_base=False)
            stack.key = f"skin_overlay_{zone}"
            self.screen.focus.register(stack)
            stack.edited.connect(lambda values, z=zone: self._on_zone_layers(z, values))
            stack.add_requested.connect(lambda z=zone: self._add_zone_layer(z))
            stack.row_activated.connect(lambda idx, z=zone: self._replace_zone_layer(z, idx))
            card.add(stack)
            left.addWidget(card)
            self.layer_stacks[zone] = stack


        # ── gear ─────────────────────────────────────────────────────────
        gear = SectionCard("General")

        # Head: one button/preview for both stock faces and the mod's own
        # custom heads — the picker itself offers a STOCK/CUSTOM toggle
        # (ui.face_picker.FacePicker), so there's one place to pick either,
        # not two competing controls for the one `face` value.
        head_row = QHBoxLayout()
        head_row.setSpacing(10)
        self.face_thumb = Thumb(72, 72)
        head_row.addWidget(self.face_thumb)
        head_col = QVBoxLayout()
        head_col.setSpacing(4)
        self.face_note = Note("", color=FG_SECONDARY, size=T_LABEL)
        head_col.addWidget(self.face_note)
        self.face_btn = compact_button("CHOOSE HEAD…")
        self.face_btn.clicked.connect(self._open_head_picker)
        head_col.addWidget(self.face_btn)
        if plugin_lookup.available():
            self.match_face_btn = compact_button("MATCH PHOTO…")
            self.match_face_btn.clicked.connect(self._open_face_match)
            self.screen.focus.register(self.match_face_btn)
            head_col.addWidget(self.match_face_btn)
        head_row.addLayout(head_col, stretch=1)
        gear.add_layout(head_row)

        g2 = FieldGrid(columns=1)
        self.boots = self.register("boot_style", ChoiceField("Boots", allow_blank=False))
        self.boots.popup_title = "boots"
        self.boots.display = self._boot_display
        self.boots.off_list_badge = False
        self.boots.subtitle_for = lambda v: ("browse for a file" if v == "__file__" else
                                             "stock boots in the game" if str(v).isdigit() else
                                             "custom texture · 256×256")
        self.boots.edited.connect(self._on_boots)
        g2.add(self.boots)

        # Goal-kick animation bank (reR08 ENABLE_KICKSTYLE, .rdf +0x50) —
        # code-only on the game side; any player can use any of the 20
        # stock banks via this byte.
        self.goal_kick_style = self.register("goal_kicking_style", ChoiceField(
            "Goal-kick style", list(gsv.goal_kicking_style_values), allow_blank=False,
            display=lambda v: v.replace("_", " ").title()))
        self.goal_kick_style.edited.connect(
            lambda v: self.edit_stat("goal-kick style", "goal_kicking_style", v, coalesce=False))
        g2.add(self.goal_kick_style)

        self.headgear = self.register("headgear", TextField("Headgear"))
        self.headgear.set_badge("UNUSED")
        self.headgear.edited.connect(lambda v: self.edit_stat("headgear", "headgear", v))
        g2.add(self.headgear)
        gear.add(g2)

        # Socks and the three tapes are all short segmented pickers — packed
        # two per row instead of the one-per-row grid above so they don't
        # each burn a full-width line.
        g3 = FieldGrid(columns=2)
        self.socks = self.register("socks", SegmentField("Socks", SOCKS))
        self.socks.edited.connect(lambda v: self.edit_stat("socks", "socks", v, coalesce=False))
        g3.add(self.socks)
        self.tapes = {}
        for key, label in (("wrist_tape", "Wrist tape"), ("tight_tape", "Thigh tape"),
                           ("finger_tape", "Finger tape")):
            f = self.register(key, SegmentField(label, TAPES, allow_blank=True, blank_label="—"))
            f.edited.connect(lambda v, k=key, l=label: self.edit_stat(l.lower(), k, v,
                                                                      coalesce=False))
            g3.add(f)
            self.tapes[key] = f
        gear.add(g3)
        left.addWidget(gear)
        left.addStretch(1)
        self.body.addLayout(left)

    # ── helpers ──────────────────────────────────────────────────────────
    @property
    def mod_dir(self):
        return config.mod_data_directory

    def _image_display(self, v):
        return "Browse file…" if v == "__file__" else A.label_of(v)

    def _skin_display(self, v):
        if v == "__file__":
            return "Browse file…"
        if v in SKIN_TONES:
            return {"l_medium": "light-med", "d_medium": "dark-med"}.get(v, v)
        return A.label_of(v)

    def _boot_display(self, v):
        if v == "__file__":
            return "Browse file…"
        return f"Style {v}" if str(v).isdigit() else A.label_of(v)

    def _browse(self, anchor, kind, on_pick, title):
        rel, root = A.asset_dir(self.mod_dir, kind)
        browse_assets(self.screen, anchor, root, {"ext": A.IMAGE_EXTS, "size": A.SPECS[
            "layer" if kind in A.LAYER_KINDS else ("boots" if kind == "boots" else kind)]["size"]},
            "", lambda picked: on_pick(f"{rel}/{picked}" if picked else ""), title=title)

    # ── skin base ────────────────────────────────────────────────────────
    def _on_skin(self, value):
        if value == "__file__":
            self._browse(self.skin, "skins",
                         lambda rel: self.edit_stat("skin image", "skin", rel, coalesce=False),
                         "custom skin texture")
            self.refresh()
            return
        if value in SKIN_TONES:
            season = self.screen.season
            self.screen.edit("skin tone", lambda r: r.setdefault("stats", {}).setdefault(
                                 season, {}).update({"skin_tone": value, "skin": ""}),
                             view_hint={"season": season, "tab": self.index, "field": "skin"})
            return
        self.edit_stat("skin image", "skin", value, coalesce=False)

    # ── layers ───────────────────────────────────────────────────────────
    def _on_layers(self, values):
        self.edit_stat("skin layers", "skin_overlay", list(values), coalesce=False)
        self.refresh()

    def _layers(self):
        return A.overlay_list(self.stats().get("skin_overlay"))

    def _zone_info(self, zone):
        return next((label, kind) for z, label, kind in self.LAYER_SECTIONS if z == zone)

    def _overlay_zone(self, rel):
        """Which LAYER_SECTIONS zone a stored skin_overlay path belongs to
        ('' if it's under none of their asset folders — kept in the list,
        just not shown in any of the four stacks)."""
        kind = A.kind_of_path(self.mod_dir, rel)
        if kind == "baselayers":
            return f"baselayer_{A.baselayer_zone(rel)}"
        return kind if kind in ("straps", "gloves") else ""

    def _zone_layers(self, zone):
        return [rel for rel in self._layers() if self._overlay_zone(rel) == zone]

    def _zone_options(self, zone):
        _, kind = self._zone_info(zone)
        return [rel for rel in A.asset_options(self.mod_dir, kind)
                if self._overlay_zone(rel) == zone]

    def _on_zone_layers(self, zone, values):
        """Rebuild the one skin_overlay list from all four stacks' current
        values, in LAYER_SECTIONS (bottom-to-top) order, with `zone`'s slice
        replaced by `values`. Anything already in the list that isn't under
        one of the four asset folders is preserved (prepended) rather than
        silently dropped."""
        zones = [z for z, *_ in self.LAYER_SECTIONS]
        current = {z: self._zone_layers(z) for z in zones}
        current[zone] = list(values)
        other = [rel for rel in self._layers() if self._overlay_zone(rel) == ""]
        self._on_layers(other + [rel for z in zones for rel in current[z]])

    def _add_zone_layer(self, zone):
        label, kind = self._zone_info(zone)
        stack = self.layer_stacks[zone]
        options = self._zone_options(zone)
        popup = PopupList(self.screen, width=420, height=460, own_keys=True)
        popup.set_title(f"add {label} layer")
        for rel in options:
            popup.add_row(A.label_of(rel), rel, icon=load_pixmap(
                A.abs_path(self.mod_dir, rel), 64), subtitle=os.path.dirname(rel))
        popup.add_row("Browse file…", "__file__")
        popup.size_to(min(14, len(options) + 1))
        popup.picked.connect(lambda v: self._zone_layer_picked(zone, v))
        popup.closed.connect(lambda: stack.setFocus())
        popup.open_at(stack, self.screen)

    def _zone_layer_picked(self, zone, value):
        if value is None:
            return
        if value == "__file__":
            _, kind = self._zone_info(zone)
            self._browse(self.layer_stacks[zone], kind,
                         lambda rel: self._append_zone_layer(zone, rel), f"{kind} texture")
            return
        self._append_zone_layer(zone, value)

    def _append_zone_layer(self, zone, rel):
        if not rel:
            return
        self._on_zone_layers(zone, self._zone_layers(zone) + [rel])
        self.layer_stacks[zone].select_value(rel)

    def _replace_zone_layer(self, zone, index):
        values = self._zone_layers(zone)
        if not 0 <= index < len(values):
            return

        def pick(rel):
            if not rel:
                return
            new = list(values)
            new[index] = rel
            self._on_zone_layers(zone, new)
        label, kind = self._zone_info(zone)
        stack = self.layer_stacks[zone]
        options = self._zone_options(zone)
        popup = PopupList(self.screen, width=420, height=460, own_keys=True)
        popup.set_title(f"replace {label} layer {index + 1}")
        for rel in options:
            popup.add_row(A.label_of(rel), rel, selected=(rel == values[index]),
                          icon=load_pixmap(A.abs_path(self.mod_dir, rel), 64),
                          subtitle=os.path.dirname(rel))
        popup.size_to(min(14, len(options)))
        popup.picked.connect(lambda v: pick(v) if v else None)
        popup.closed.connect(lambda: stack.setFocus())
        popup.open_at(stack, self.screen)

    # ── boots / face ─────────────────────────────────────────────────────

    def _on_boots(self, value):
        if value == "__file__":
            self._browse(self.boots, "boots",
                         lambda rel: self.edit_stat("boots", "boot_style", rel or "0",
                                                    coalesce=False), "custom boot image")
            self.refresh()
            return
        self.edit_stat("boots", "boot_style", value, coalesce=False)

    def _open_head_picker(self):
        current = str(self.stats().get("face") or "")
        # on_cancel restores the REAL stored face (self.screen.refresh_stage
        # with no override) — live-previewed candidates never touch it.
        picker = FacePicker(self.screen, current=current,
                            on_preview=self.screen.preview_face,
                            on_cancel=self.screen.refresh_stage)
        picker.picked.connect(
            lambda value: self.edit_stat("face", "face", value, coalesce=False))

    def _open_face_match(self):
        plugin = plugin_lookup.get()
        if plugin is None:
            return
        record = self.record()
        name = f"{record.get('first_name', '')} {record.get('last_name', '')}".strip()
        query = name or record.get("display_name", "")
        plugin.open_face_match(
            self.screen, query=query,
            on_pick=lambda value: self.edit_stat("face", "face", value, coalesce=False),
            on_preview=self.screen.preview_face, on_cancel=self.screen.refresh_stage)

    # ── refresh ──────────────────────────────────────────────────────────
    def refresh(self):
        stats = self.stats()
        mod = self.mod_dir
        skin = str(stats.get("skin") or "")
        custom = bool(skin) and A.normalize_tone(skin) is None
        skin_opts = A.asset_options(mod, "skins")
        self.skin.set_options(list(SKIN_TONES) + skin_opts + ["__file__"])
        self.skin.set_value(skin if custom else (A.normalize_tone(stats.get("skin_tone")) or "light"))

        # layer stacks: strap, bottom baselayer, top baselayer, gloves
        for zone, _label, kind in self.LAYER_SECTIONS:
            spec = "gloves" if kind == "gloves" else "layer"
            self.layer_stacks[zone].set_layers(
                [self._layer_row(mod, rel, spec) for rel in self._zone_layers(zone)])

        boot = str(stats.get("boot_style") or "")
        self.boots.set_options(list(BOOT_STYLES) + A.asset_options(mod, "boots") + ["__file__"])
        self.boots.set_value(boot)
        self.boots.set_hint("style 0" if not boot else "")
        self.goal_kick_style.set_value(stats.get("goal_kicking_style") or "default")

        self.socks.set_value(stats.get("socks", ""))
        for key, f in self.tapes.items():
            f.set_value(stats.get(key, ""))
        self.headgear.set_value(stats.get("headgear", ""))

        self._refresh_face_thumb(stats)

    def _layer_row(self, mod, rel, spec="layer"):
        problems = A.asset_problems(mod, rel, spec)
        sev = problems[0][1] if problems else None
        tag = {"error": "MISSING", "warn": "NO ALPHA", "info": "RESIZED"}.get(sev, "")
        if problems and problems[0][0].endswith("is not an image file"):
            tag = "NOT IMAGE"
        return {"value": rel, "label": A.label_of(rel), "thumb": A.abs_path(mod, rel),
                "tag": tag, "tag_color": {"error": DANGER_LITE, "warn": WARN,
                                          "info": INFO}.get(sev)}

    def _refresh_face_thumb(self, stats):
        face = str(stats.get("face") or "")
        if face.endswith(".big"):
            big = os.path.join(self.mod_dir, face)
            pix = (face_thumbnail(os.path.join(config.temp_directory, "head_thumbs"), big)
                   if os.path.isfile(big) else None)
            if pix is not None and not pix.isNull():
                self.face_thumb.set_pixmap(pix, "NO FACE")
                self.face_note.setText(f"Custom head {os.path.basename(face)}")
            else:
                self.face_thumb.set_text("NO FACE")
                self.face_note.setText(f"Custom head {os.path.basename(face)} could not be read")
        elif face.isdigit():
            portrait = stock_portrait_path(face, os.path.join(config.temp_directory, "stock_portraits"))
            pix = (face_thumbnail(os.path.join(config.temp_directory, "head_thumbs"), portrait)
                   if portrait else None)
            if pix is not None and not pix.isNull():
                self.face_thumb.set_pixmap(pix, "NO FACE")
                self.face_note.setText(f"Stock face {face}")
            else:
                self.face_thumb.set_text(f"FACE\n{face}")
                self.face_note.setText(
                    f"Stock face {face} — data.gob not found, can't extract it"
                    if not os.path.isfile(config.R08_data_gob_filepath) else f"Stock face {face}")
        else:
            self.face_thumb.set_text("GENERIC")
            self.face_note.setText("No head set, the game uses its generic face (666).")

    def hints(self, focused):
        if isinstance(focused, LayerStackField):
            return [("↑↓", "pick"), ("⇧↑↓", "move"), ("DEL", "remove"), ("A", "add / replace")]
        if isinstance(focused, SegmentField):
            return [("←→", "change")]
        if isinstance(focused, ChoiceField):
            return [("A", "choose"), ("←→", "step")]
        return []


# ═════════════════════════════════════════════════════════════════════════
TENDENCY_NAMES = ["default", "scrum", "lineout", "tackler", "runner", "passer", "kicker",
                  "crasher", "ruck", "goal kicker", "playmaker"]
# Star player class, written to the roster record's star-flag byte (reR08
# patches_dll ENABLE_STARPLAYERS). Flag 0 =
# none, 1 = the generic base StarPlayer, 2-26 = named classes gated on that
# byte value. Cross-referenced against game.h's flag->roster-id table by id
# (STAR_ABILITIES.md's own "flag" column uses a different, inconsistent
# numbering — not trusted here); 6 flags there (2, 4, 5, 7, 18, 23) have no
# confirmed real-player identity yet, so they're left as "Class N".
STAR_PLAYER_NAMES = {
    0: "— none", 1: "Star player (generic)", 2: "Class 2", 3: "Wilkinson",
    4: "Class 4", 5: "Class 5", 6: "Henson", 7: "Class 7", 8: "Carter",
    9: "Dallaglio", 10: "Betsen", 11: "O'Driscoll", 12: "Larkham",
    13: "Tuqiri", 14: "Spencer", 15: "Montgomery", 16: "Gregan",
    17: "Collins", 18: "Class 18", 19: "Latham", 20: "Giteau", 21: "Umaga",
    22: "McCaw", 23: "Class 23", 24: "G. Smith", 25: "Burger", 26: "Lewsey",
}
# Offered in the picker: "— none" plus only the confirmed-identity classes —
# excludes 1 (generic base class) and the 6 "Class N" placeholders above.
STAR_PLAYER_CHOICES = [0] + [i for i in range(2, 27) if not STAR_PLAYER_NAMES[i].startswith("Class")]
SKILLS = [
    ("ss_command", "Command"), ("ss_passer", "Passer"), ("ss_play_maker", "Playmaker"),
    ("ss_scoring", "Try scorer"), ("ss_goal_kicker", "Goal kicker"),
    ("ss_tactical_kicking", "Tactical kicker"), ("ss_crashball", "Crash ball"),
    ("ss_tackle_breaker", "Tackle breaker"), ("ss_tackling", "Big tackler"),
    ("ss_ball_winner", "Ball winner"), ("ss_defensive_organisation", "Defensive organiser"),
    ("ss_scrummager", "Scrummager"), ("ss_jumper", "Line-out jumper"),
]
TRUE_WORDS = {"1", "true", "yes", "on", "up"}


class SkillsTab(PlayerTab):
    """Game data the roster carries beyond the 24 ratings: two extra
    ratings, the AI tendency and the star special skills. Blank means the
    game default (0 / no skill)."""

    def __init__(self, screen, index):
        super().__init__(screen, index)
        row = QHBoxLayout()
        row.setSpacing(14)

        left = SectionCard("extra ratings")
        left.setFixedWidth(400)
        g = FieldGrid(columns=1)
        self.extra = {}
        for key, label in (("crashball", "Crash ball"), ("gap_defense", "Gap defence")):
            f = self.register(key, RatingField(label))
            f.edited.connect(lambda v, k=key, l=label: self.edit_stat(l.lower(), k, v))
            g.add(f)
            self.extra[key] = f
        self.tendency = self.register("special_ability", ChoiceField(
            "AI tendency", [str(i) for i in range(len(TENDENCY_NAMES))], allow_blank=True,
            blank_label="— default", display=lambda v: TENDENCY_NAMES[int(v)] if str(v).isdigit()
            and int(v) < len(TENDENCY_NAMES) else str(v)))
        self.tendency.edited.connect(lambda v: self.edit_stat("tendency", "special_ability", v,
                                                              coalesce=False))
        g.add(self.tendency)
        # Star player class (reR08 ENABLE_STARPLAYERS, .rdf +0x4e) — grants
        # that class's query-dispatcher abilities (special kicks, tackle
        # breaking, ruck dominance, ...) regardless of ratings. Only the
        # confirmed-identity classes are offered — flag 1 (the generic base
        # class) and the 6 flags with no confirmed real-player identity
        # (see STAR_PLAYER_NAMES) are excluded so the list is never a guess.
        self.star_attribute = self.register("star_attribute", ChoiceField(
            "Star player ability", [str(i) for i in STAR_PLAYER_CHOICES], allow_blank=True,
            blank_label=STAR_PLAYER_NAMES[0],
            display=lambda v: STAR_PLAYER_NAMES.get(int(v), v) if str(v).isdigit() else str(v)))
        self.star_attribute.edited.connect(
            lambda v: self.edit_stat("star player ability", "star_attribute", v, coalesce=False))
        g.add(self.star_attribute)
        left.add(g)

        left.v.addStretch(1)
        row.addWidget(left)

        right = SectionCard("special skills")
        # 3 columns left several labels ("Defensive organiser", "Tactical
        # kicker"...) clipped mid-word once the mid pane widened. 2 columns
        # in the freed-up width (left card also narrowed, above) comfortably
        # fits the longest label.
        self.skills = ToggleGrid(SKILLS, columns=2)
        self.register("ss_skills", self.skills)
        self.skills.toggled.connect(self._toggle)
        right.add(self.skills)
        right.v.addStretch(1)
        row.addWidget(right, stretch=1)
        self.body.addLayout(row)
        self.body.addStretch(1)

    def _toggle(self, key, on):
        self.edit_stat(dict(SKILLS)[key].lower(), key, "yes" if on else "", coalesce=False)

    def refresh(self):
        stats = self.stats()
        prev_key = previous_season(self.record(), self.screen.season)
        prev = (self.record().get("stats") or {}).get(prev_key) if prev_key else None
        for key, f in self.extra.items():
            f.set_value(stats.get(key, ""))
            f.set_reference(prev.get(key) if prev else None)
        self.tendency.set_value(stats.get("special_ability", ""))
        self.star_attribute.set_value(str(stats.get("star_attribute") or ""))
        self.skills.set_values(k for k, _ in SKILLS
                               if str(stats.get(k, "")).strip().lower() in TRUE_WORDS)

    def hints(self, focused):
        if focused is self.skills:
            return [("←→↕", "move"), ("A", "toggle")]
        if isinstance(focused, RatingField):
            return [("0-9", "type"), ("←→", "±1")]
        return []


class TeamsTab(PlayerTab):
    """Every squad this player is named in for the season currently
    selected in the mid pane — one season can list him in more than one
    (a club and a country, say)."""

    def __init__(self, screen, index):
        super().__init__(screen, index)
        card = SectionCard("teams")
        self.note = Note("", color=FG_SECONDARY, size=T_LABEL)
        card.add(self.note)
        self.rows = QVBoxLayout()
        self.rows.setSpacing(4)
        card.add_layout(self.rows)
        self.body.addWidget(card)
        self.body.addStretch(1)
        self._row_btns = []

    def refresh(self):
        while self.rows.count():
            item = self.rows.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._row_btns = []

        season = self.screen.season
        memberships = [m for m in self.screen.ds.memberships(self.screen.record_id) if m[2] == season]
        self.note.setText(f"In {len(memberships)} squad{'s' if len(memberships) != 1 else ''} "
                          f"for {season_label(season)}." if memberships else
                          f"Not named in any squad for {season_label(season)}.")
        for tid, name, s, shirt in memberships:
            role = "starter" if shirt <= 15 else ("bench" if shirt <= 22 else "not loaded")
            b = compact_button(f"{name}   ·   #{shirt} {role}   →", height=32)
            b.setStyleSheet(b.styleSheet() + "QPushButton { text-align: left; }")
            b.clicked.connect(lambda _=False, t=tid, ss=s, sh=shirt: self.screen.open_team(t, ss, sh))
            self.screen.focus.register(b)
            self.rows.addWidget(b)
            self._row_btns.append(b)
