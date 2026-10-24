"""
screens/tournament/hub.py — Tournament mode's front door.

Left: the saved tournaments as cards, newest first (emblem, managed team,
progress, last played). Right: a NEW TOURNAMENT tile and the focused save
with CONTINUE / DELETE; its description and options wait behind DETAILS.
The cards rise in one after the other. Pad: A continue, X delete, Y new,
B back.
"""
from datetime import datetime

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.season import season_label
from app.tournament import formats, persistence
from app.tournament.session import TournamentSession
from shared.log import get_logger
from ui import motion
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, page_header, tracked_font
from ui.editor_kit import ConfirmDialog, Note, compact_button
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BTN_HEIGHT, FG_MUTED, FG_PRIMARY, FG_SECONDARY,
                      FG_TERTIARY, FONT_DISPLAY, GREEN, WARN)

from .common import (ActivatableCard, PixmapLabel, ProgressStrip, SectionTitle, Tag, clear_layout,
                     competition_emblem, team_crest, transparent)

log = get_logger(__name__)


def relative_time(stamp) -> str:
    try:
        then = datetime.fromisoformat(stamp)
    except (TypeError, ValueError):
        return ""
    secs = (datetime.now() - then).total_seconds()
    if secs < 90:
        return "just now"
    if secs < 3600:
        return f"{int(secs // 60)} min ago"
    if secs < 86400:
        return f"{int(secs // 3600)} h ago"
    days = int(secs // 86400)
    return "yesterday" if days == 1 else (f"{days} days ago" if days < 30 else then.strftime("%d %b %Y"))


def _options_line(opts) -> str:
    parts = [str(opts.get("difficulty", "")).upper(), f"{opts.get('halftime_length', '')} halves"]
    if opts.get("injuries", True):
        parts.append("injuries")
    if opts.get("fatigue", True):
        parts.append("fatigue")
    if opts.get("suspensions", True):
        parts.append("suspensions")
    return " · ".join(p for p in parts if p.strip())


class SaveCard(ActivatableCard):
    """One saved tournament."""

    def __init__(self, ds, save, template, parent=None):
        super().__init__(parent)
        self.save = save
        self.setFixedHeight(108)
        err = save.get("error")
        self._emblem = competition_emblem(ds, template or {"name": save.get("name", "")}, 76)
        self._crests = [team_crest(ds, tid, season, 30) for tid, season in save.get("human_ids") or []]
        self._comp = (template or {}).get("name", save.get("template_id", ""))
        self._err = err

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self.paint_background(p)
        s, w, h = self.save, self.width(), self.height()
        p.drawPixmap(20, (h - 76) // 2, self._emblem)
        x = 116
        p.setFont(tracked_font(FONT_DISPLAY, 20, QFont.Bold, 0.8))
        p.setPen(QColor(FG_PRIMARY))
        p.drawText(QRectF(x, 14, w - x - 230, 30), Qt.AlignLeft | Qt.AlignVCenter,
                   p.fontMetrics().elidedText(s.get("name", "").upper(), Qt.ElideRight, w - x - 230))
        p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.DemiBold, 1.4))
        p.setPen(QColor(FG_TERTIARY))
        # the competition once: not again under a save named after it
        name = s.get("name", "").strip().upper()
        sub = self._comp.upper() if self._comp.upper() != name else ""
        if s.get("season"):
            sub += ("  ·  " if sub else "") + season_label(s["season"])
        p.drawText(QRectF(x, 44, w - x - 230, 18), Qt.AlignLeft | Qt.AlignVCenter, sub)
        if self._err:
            p.setPen(QColor(WARN))
            p.drawText(QRectF(x, 66, w - x - 20, 24), Qt.AlignLeft | Qt.AlignVCenter, "SAVE CAN'T BE READ")
            return
        # managed team(s)
        cx = x
        for crest, name in zip(self._crests, s.get("humans") or []):
            p.drawPixmap(int(cx), 68, crest)
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, 0.6))
            p.setPen(QColor(FG_SECONDARY))
            tw = p.fontMetrics().horizontalAdvance(name.upper())
            p.drawText(QRectF(cx + 36, 68, tw + 4, 30), Qt.AlignLeft | Qt.AlignVCenter, name.upper())
            cx += 36 + tw + 22
        # progress / champion, right side
        rx = w - 210
        if s.get("champion"):
            p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.4))
            p.setPen(QColor(AWAY_TINT))
            p.drawText(QRectF(rx, 18, 190, 18), Qt.AlignRight | Qt.AlignVCenter, "★ COMPLETED")
            p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, 0.6))
            p.setPen(QColor(FG_PRIMARY))
            p.drawText(QRectF(rx, 38, 190, 22), Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(f"WON BY {s['champion'].upper()}", Qt.ElideRight, 190))
        else:
            p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.4))
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(QRectF(rx, 18, 190, 18), Qt.AlignRight | Qt.AlignVCenter,
                       f"MATCHDAY {s.get('day', 0) + 1} / {s.get('last_day', 0) + 1}")
            total = max(1, s.get("total") or 1)
            frac = (s.get("played") or 0) / total
            bar = QRectF(rx + 30, 42, 160, 6)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#10200c").lighter(140))
            p.drawRoundedRect(bar, 3, 3)
            p.setBrush(QColor(ACCENT))
            p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(6, bar.width() * frac), bar.height()), 3, 3)
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, 1.0))
        p.setPen(QColor(FG_MUTED))
        p.drawText(QRectF(rx, 70, 190, 24), Qt.AlignRight | Qt.AlignVCenter,
                   relative_time(s.get("updated")).upper())


class NewTile(ActivatableCard):
    """The big NEW TOURNAMENT entry."""

    def __init__(self, parent=None):
        super().__init__(parent, stripe=GREEN)
        self.setFixedHeight(96)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        h = self.height()
        c = QRectF(24, (h - 48) / 2, 48, 48)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT if self.hasFocus() else GREEN))
        p.drawEllipse(c)
        p.setPen(QColor(BG_BASE))
        p.setFont(tracked_font(FONT_DISPLAY, 26, QFont.Bold, 0))
        p.drawText(c.adjusted(0, -2, 0, 0), Qt.AlignCenter, "+")
        p.setPen(QColor(FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 22, QFont.Bold, 1.2))
        p.drawText(QRectF(92, 18, self.width() - 110, 32), Qt.AlignLeft | Qt.AlignVCenter, "NEW TOURNAMENT")
        p.setPen(QColor(FG_TERTIARY))
        p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.DemiBold, 1.4))
        p.drawText(QRectF(92, 50, self.width() - 110, 22), Qt.AlignLeft | Qt.AlignVCenter,
                   "PICK A COMPETITION, DRAW THE POOLS, TAKE CHARGE")


class TournamentHubScreen(Screen):
    def __init__(self, ds, on_back, on_new, on_open):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_new = on_new
        self.on_open = on_open
        self._saves = []
        self._cards = []
        self._selected = None
        self._build()

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Tournament", breadcrumb="game modes", on_back=self.on_back_cb))

        body = QWidget()
        body.setObjectName("hubBody")
        body.setStyleSheet(f"QWidget#hubBody {{ background: {BG_BASE}; }}")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(80, 28, 80, 24)
        bl.setSpacing(28)

        # saves
        left = transparent(QWidget(), "hubLeft")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)
        self.saves_title = SectionTitle("your tournaments")
        lv.addWidget(self.saves_title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self._scroll = scroll
        holder = transparent(QWidget(), "hubSaves")
        self.list_layout = QVBoxLayout(holder)
        self.list_layout.setContentsMargins(0, 0, 8, 0)
        self.list_layout.setSpacing(10)
        scroll.setWidget(holder)
        scroll.viewport().setStyleSheet("background: transparent;")
        lv.addWidget(scroll, stretch=1)
        bl.addWidget(left, stretch=3)

        # new + details
        right = transparent(QWidget(), "hubRight")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(16)
        rv.addWidget(SectionTitle("start"))
        self.new_tile = NewTile()
        self.new_tile.activated.connect(self.on_new)
        self.focus.register(self.new_tile)
        rv.addWidget(self.new_tile)
        rv.addSpacing(8)

        self.detail = Card(stripe=ACCENT, translucent=True)
        dv = QVBoxLayout(self.detail)
        dv.setContentsMargins(26, 20, 26, 22)
        dv.setSpacing(10)
        dv.addWidget(eyebrow_label("selected", color=ACCENT, size=12))
        top = QHBoxLayout()
        top.setSpacing(16)
        self.d_emblem = PixmapLabel(84)
        top.addWidget(self.d_emblem)
        tv = QVBoxLayout()
        tv.setSpacing(2)
        self.d_name = display_label("", 22, QFont.Bold, track=0.8)
        self.d_name.setWordWrap(True)
        tv.addWidget(self.d_name)
        self.d_comp = eyebrow_label("", color=FG_TERTIARY, size=11)
        tv.addWidget(self.d_comp)
        top.addLayout(tv, stretch=1)
        dv.addLayout(top)
        self.d_status = display_label("", 14, QFont.Bold, track=1.0, color=FG_PRIMARY)
        dv.addWidget(self.d_status)
        self.d_progress = ProgressStrip(height=8)
        dv.addWidget(self.d_progress)
        self.d_when = Note("", color=FG_TERTIARY)
        dv.addWidget(self.d_when)
        # the rest on demand: the competition's description, the options
        self.d_more = transparent(QWidget(), "hubMore")
        mv = QVBoxLayout(self.d_more)
        mv.setContentsMargins(0, 4, 0, 0)
        mv.setSpacing(8)
        self.d_desc = Note("", color=FG_SECONDARY)
        mv.addWidget(self.d_desc)
        self.d_opts = Note("", color=FG_TERTIARY)
        mv.addWidget(self.d_opts)
        self.d_more.hide()
        dv.addWidget(self.d_more)
        dv.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.delete_btn = compact_button("DELETE", "danger", height=BTN_HEIGHT)
        self.delete_btn.clicked.connect(self._delete)
        row.addWidget(self.delete_btn)
        self.more_btn = compact_button("DETAILS  ▾", "ghost", height=BTN_HEIGHT)
        self.more_btn.clicked.connect(self._toggle_details)
        row.addWidget(self.more_btn)
        row.addStretch(1)
        self.continue_btn = compact_button("CONTINUE", "primary", height=BTN_HEIGHT)
        self.continue_btn.setMinimumWidth(200)
        self.continue_btn.clicked.connect(self._continue)
        row.addWidget(self.continue_btn)
        dv.addLayout(row)
        for b in (self.continue_btn, self.more_btn, self.delete_btn):
            self.focus.register(b)
        rv.addWidget(self.detail)

        self.empty = Card(translucent=True)
        ev = QVBoxLayout(self.empty)
        ev.setContentsMargins(26, 22, 26, 22)
        ev.addWidget(display_label("no tournament yet", 18, QFont.Bold, track=1.0, color=FG_SECONDARY))
        ev.addWidget(Note("Pick a competition, draw the pools and lead your nation or club "
                          "through every round. Progress is saved after each match.",
                          color=FG_TERTIARY))
        # The empty state sits where the saves would be.
        lv.insertWidget(1, self.empty)
        rv.addStretch(1)
        bl.addWidget(right, stretch=2)
        root.addWidget(body, stretch=1)

        self.hints = HintBar()
        root.addWidget(self.hints)

    # ── data ─────────────────────────────────────────────────────────────
    def on_show(self):
        super().on_show()
        self.reload()
        (self._cards[0] if self._cards else self.new_tile).setFocus()
        motion.stagger_in(self._cards[:8] + [self.new_tile, self.detail if self._saves else self.empty],
                          step=55)

    def _toggle_details(self):
        show = self.d_more.isHidden()
        self.d_more.setVisible(show)
        self.more_btn.setText("DETAILS  ▴" if show else "DETAILS  ▾")
        if show:
            motion.fade_in(self.d_more, ms=200)

    def reload(self):
        self.templates = formats.load_templates()
        self._saves = persistence.list_saves()
        for c in self._cards:
            self.focus.unregister(c)
        clear_layout(self.list_layout)
        self._cards = []
        for s in self._saves:
            card = SaveCard(self.ds, s, self.templates.get(s.get("template_id")) if not s.get("error") else None)
            card.activated.connect(lambda s=s: (self._select(s), self._continue()))
            card.focused.connect(lambda s=s: self._select(s))
            self.focus.register(card)
            self.list_layout.addWidget(card)
            self._cards.append(card)
        self.list_layout.addStretch(1)
        has = bool(self._saves)
        self.saves_title.set_right(f"{len(self._saves)} saved" if has else "")
        self.empty.setVisible(not has)
        self.detail.setVisible(has)
        keep = self._selected["id"] if self._selected else None
        self._select(next((s for s in self._saves if s["id"] == keep), self._saves[0] if has else None))
        self.hints.set_hints([("A", "continue"), ("X", "delete"), ("Y", "new"), ("B", "back")] if has
                             else [("A", "select"), ("Y", "new"), ("B", "back")])

    def _select(self, s):
        changed = s is not self._selected
        self._selected = s
        for c in self._cards:
            c.selected = c.save is s
            c.update()
        if not s:
            return
        if changed and self.isVisible():
            motion.fade_in(self.detail, ms=160)
        tpl = self.templates.get(s.get("template_id"), {})
        self.d_emblem.set_pixmap(competition_emblem(self.ds, tpl or {"name": s.get("name", "")}, 84))
        self.d_name.setText(s.get("name", "").upper())
        comp = tpl.get("name", s.get("template_id", ""))
        parts = [comp if comp.upper() != s.get("name", "").strip().upper() else "",
                 season_label(s["season"]) if s.get("season") else ""]
        self.d_comp.setText(" · ".join(p for p in parts if p).upper())
        self.d_desc.setText(tpl.get("description", ""))
        self.more_btn.setVisible(bool(tpl.get("description")) or not s.get("error"))
        if s.get("error"):
            self.d_status.setText("This save can't be read")
            self.d_progress.set_value(0)
            self.d_opts.setText(s["error"])
            self.d_when.setText("")
            self.continue_btn.setEnabled(False)
        else:
            if s.get("champion"):
                self.d_status.setText(f"★  {s['champion']} are champions".upper())
                self.d_progress.set_value(1.0, AWAY_TINT)
            else:
                managing = ", ".join(s.get("humans") or []) or "spectating"
                self.d_status.setText(f"{managing} · matchday {s.get('day', 0) + 1} of "
                                      f"{s.get('last_day', 0) + 1}".upper())
                self.d_progress.set_value((s.get("played") or 0) / max(1, s.get("total") or 1), ACCENT)
            self.d_opts.setText(_options_line(s.get("options") or {}))
            self.d_when.setText("Last played " + (relative_time(s.get("updated")) or "—"))
            self.continue_btn.setEnabled(True)
            self.continue_btn.setText("VIEW" if s.get("champion") else "CONTINUE")

    # ── actions ──────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action == Action.ALT and self._selected:
            self._delete(); event.accept(); return
        if action == Action.AUX:
            self.on_new(); event.accept(); return
        super().keyPressEvent(event)

    def _continue(self):
        s = self._selected
        if not s or s.get("error"):
            return
        try:
            session = TournamentSession.load(s["id"], self.ds)
        except Exception as e:
            log.exception("loading tournament %s", s["id"])
            ConfirmDialog(self, "Can't open this tournament", str(e), [("OK", "primary", "ok")],
                          lambda _r: None, cancel_role="ok")
            return
        interrupted = persistence.has_snapshot(session.t.id, "prematch")
        if interrupted:
            # The save already holds the pre-match state (begin_game saves
            # before launching), so the marker only needs clearing.
            session.abandon_game()
        self.on_open(session, "Your last match was not completed. It is still to be played."
                     if interrupted else "")

    def _delete(self):
        s = self._selected
        if not s:
            return

        def done(role):
            if role == "ok":
                persistence.delete(s["id"])
                self._selected = None
                self.reload()
                (self._cards[0] if self._cards else self.new_tile).setFocus()
        ConfirmDialog(self, "Delete tournament?", f"“{s['name']}” and all its progress will be lost.",
                      [("CANCEL", "neutral", "cancel"), ("DELETE", "danger", "ok")], done)
