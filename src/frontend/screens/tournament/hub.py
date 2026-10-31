"""
screens/tournament/hub.py — Tournament mode's front door.

NEW TOURNAMENT on its own on top, then the saved tournaments in two
sections, newest first: IN PROGRESS and COMPLETED (emblem, name and
edition, your team, where it stands, last played), each with a delete
zone at its right end (a bin; asked first). The cards rise in one after the other. Pad: A open,
X delete, Y new, B back.
"""
from datetime import datetime

from PyQt5.QtCore import QPointF, QRectF, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPainterPath, QPen
from PyQt5.QtWidgets import QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.tournament import formats, persistence, report
from app.tournament.session import TournamentSession
from shared.log import get_logger
from ui import motion
from ui.broadcast import HintBar, page_header, tracked_font
from ui.editor_kit import ConfirmDialog
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BORDER, DANGER, DANGER_LITE, FG_MUTED, FG_PRIMARY, FG_SECONDARY,
                      FG_TERTIARY, FONT_DISPLAY, GREEN, WARN)

from .common import (ActivatableCard, SectionTitle, clear_layout, competition_emblem, team_crest,
                     transparent)

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


def paint_bin(p, c, size, color):
    """A bin (delete) centred on `c`: lid, handle, can with two ribs."""
    s = size
    pen = QPen(QColor(color), max(1.6, s / 11), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
    p.setPen(pen)
    p.setBrush(Qt.NoBrush)
    top = c.y() - s * 0.42
    p.drawLine(QPointF(c.x() - s * 0.45, top + s * 0.14), QPointF(c.x() + s * 0.45, top + s * 0.14))
    p.drawLine(QPointF(c.x() - s * 0.14, top), QPointF(c.x() + s * 0.14, top))
    can = QPainterPath(QPointF(c.x() - s * 0.34, top + s * 0.28))
    can.lineTo(c.x() - s * 0.27, c.y() + s * 0.46)
    can.lineTo(c.x() + s * 0.27, c.y() + s * 0.46)
    can.lineTo(c.x() + s * 0.34, top + s * 0.28)
    p.drawPath(can)
    for dx in (-0.1, 0.1):
        p.drawLine(QPointF(c.x() + s * dx, top + s * 0.42), QPointF(c.x() + s * dx, c.y() + s * 0.3))


class DeleteZone(QWidget):
    """The right end of a save card: a bin over DELETE, set off by a rule.
    Quiet until the card is focused; red under the mouse. Click: clicked."""

    WIDTH = 92
    clicked = pyqtSignal()

    def __init__(self, card):
        super().__init__(card)
        self._card = card
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("Delete this tournament")

    def enterEvent(self, e):
        self.update()
        self._card.update()

    def leaveEvent(self, e):
        self.update()
        self._card.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            event.accept()
            self.clicked.emit()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        w, h = self.width(), self.height()
        hover = self.underMouse()
        if hover:
            p.fillRect(QRectF(0, 1, w - 1, h - 2), QColor(DANGER))
        else:
            p.fillRect(QRectF(0, 18, 1, h - 36), QColor(BORDER))
        hot = self._card.hasFocus() or self._card.selected
        color = DANGER_LITE if hover else (FG_SECONDARY if hot else FG_MUTED)
        paint_bin(p, QPointF(w / 2, h / 2 - 9), 26, color)
        p.setPen(QColor(color))
        p.setFont(tracked_font(FONT_DISPLAY, 9, QFont.Bold, 1.4))
        p.drawText(QRectF(0, h / 2 + 12, w, 20), Qt.AlignCenter, "DELETE")


class SaveCard(ActivatableCard):
    """One saved tournament: emblem, name (and the competition when the
    name doesn't say it), edition, your team(s); where it stands on the
    right, with a progress bar and when it was last played."""

    def __init__(self, ds, save, template, where="", parent=None):
        super().__init__(parent)
        self.save = save
        self.setFixedHeight(108)
        self._emblem = competition_emblem(ds, template or {"name": save.get("name", "")}, 76)
        self._crests = [team_crest(ds, tid, season, 30) for tid, season in save.get("human_ids") or []]
        self._comp = (template or {}).get("name", save.get("template_id", ""))
        self._where = where
        self._err = save.get("error")
        self.delete_zone = DeleteZone(self)

    def resizeEvent(self, event):
        self.delete_zone.setGeometry(self.width() - DeleteZone.WIDTH, 0, DeleteZone.WIDTH, self.height())
        super().resizeEvent(event)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        self.paint_background(p)
        s, h = self.save, self.height()
        w = self.width() - DeleteZone.WIDTH      # the content ends clear of the delete zone
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
        sub = self._comp.upper() if self._comp.upper() not in name else ""
        if (s.get("options") or {}).get("reality"):
            sub += ("  ·  " if sub else "") + "REALITY MODE"
        p.drawText(QRectF(x, 44, w - x - 230, 18), Qt.AlignLeft | Qt.AlignVCenter, sub)
        if self._err:
            p.setPen(QColor(WARN))
            p.drawText(QRectF(x, 66, w - x - 20, 24), Qt.AlignLeft | Qt.AlignVCenter, "SAVE CAN'T BE READ")
            return
        cx = x
        for crest, team in zip(self._crests, s.get("humans") or []):
            p.drawPixmap(int(cx), 68, crest)
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, 0.6))
            p.setPen(QColor(FG_SECONDARY))
            tw = p.fontMetrics().horizontalAdvance(team.upper())
            p.drawText(QRectF(cx + 36, 68, tw + 4, 30), Qt.AlignLeft | Qt.AlignVCenter, team.upper())
            cx += 36 + tw + 22
        rx = w - 210
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.4))
        if s.get("champion"):
            p.setPen(QColor(AWAY_TINT))
            p.drawText(QRectF(rx, 18, 190, 18), Qt.AlignRight | Qt.AlignVCenter, "★ COMPLETED")
        else:
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(QRectF(rx - 60, 18, 250, 18), Qt.AlignRight | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(self._where.upper(), Qt.ElideLeft, 250))
        total = max(1, s.get("total") or 1)
        frac = 1.0 if s.get("champion") else (s.get("played") or 0) / total
        bar = QRectF(rx + 30, 42, 160, 6)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#10200c").lighter(140))
        p.drawRoundedRect(bar, 3, 3)
        p.setBrush(QColor(AWAY_TINT if s.get("champion") else ACCENT))
        p.drawRoundedRect(QRectF(bar.x(), bar.y(), max(6, bar.width() * frac), bar.height()), 3, 3)
        p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, 1.0))
        p.setPen(QColor(FG_MUTED))
        p.drawText(QRectF(rx, 70, 190, 24), Qt.AlignRight | Qt.AlignVCenter,
                   relative_time(s.get("updated")).upper())


class NewTile(ActivatableCard):
    """NEW TOURNAMENT, the first entry of the list."""

    def __init__(self, parent=None):
        super().__init__(parent, stripe=GREEN)
        self.setFixedHeight(84)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        h = self.height()
        c = QRectF(34, (h - 48) / 2, 48, 48)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ACCENT if self.hasFocus() else GREEN))
        p.drawEllipse(c)
        p.setPen(QColor(BG_BASE))
        p.setFont(tracked_font(FONT_DISPLAY, 26, QFont.Bold, 0))
        p.drawText(c.adjusted(0, -2, 0, 0), Qt.AlignCenter, "+")
        p.setPen(QColor(FG_PRIMARY))
        p.setFont(tracked_font(FONT_DISPLAY, 20, QFont.Bold, 1.2))
        p.drawText(QRectF(116, 0, self.width() - 130, h), Qt.AlignLeft | Qt.AlignVCenter, "NEW TOURNAMENT")


class TournamentHubScreen(Screen):
    def __init__(self, ds, on_back, on_new, on_open):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_new = on_new
        self.on_open = on_open
        self._saves = []
        self._cards = []
        self._loaded = {}            # save id -> (updated, Tournament)
        self._selected = None        # the focused save; None = NEW TOURNAMENT
        self._build()

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Tournament", on_back=self.on_back_cb))

        body = QWidget()
        body.setObjectName("hubBody")
        body.setStyleSheet(f"QWidget#hubBody {{ background: {BG_BASE}; }}")
        bl = QHBoxLayout(body)
        bl.setContentsMargins(80, 28, 80, 24)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.setMaximumWidth(1200)
        self._scroll = scroll
        holder = transparent(QWidget(), "hubSaves")
        hv = QVBoxLayout(holder)
        hv.setContentsMargins(0, 0, 8, 0)
        hv.setSpacing(10)
        self.new_tile = NewTile()
        self.new_tile.activated.connect(self.on_new)
        self.new_tile.focused.connect(lambda: self._select(None))
        self.focus.register(self.new_tile)
        hv.addWidget(self.new_tile)
        hv.addSpacing(30)
        # two sections: the tournaments under way, the finished ones
        self.sections = {}
        for key, title in (("progress", "in progress"), ("done", "completed")):
            section = transparent(QWidget(), f"hub_{key}")
            sv = QVBoxLayout(section)
            sv.setContentsMargins(0, 0, 0, 18)
            sv.setSpacing(10)
            heading = SectionTitle(title)
            sv.addWidget(heading)
            rows = QVBoxLayout()
            rows.setSpacing(10)
            sv.addLayout(rows)
            hv.addWidget(section)
            self.sections[key] = (section, heading, rows)
        hv.addStretch(1)
        scroll.setWidget(holder)
        scroll.viewport().setStyleSheet("background: transparent;")
        bl.addStretch(1)
        bl.addWidget(scroll, stretch=100)
        bl.addStretch(1)
        root.addWidget(body, stretch=1)

        self.hints = HintBar()
        root.addWidget(self.hints)

    # ── data ─────────────────────────────────────────────────────────────
    def on_show(self):
        super().on_show()
        self.reload()
        (self._cards[0] if self._cards else self.new_tile).setFocus()
        motion.stagger_in([self.new_tile] + self._cards[:8], step=55)

    def _tournament(self, s):
        """The save's Tournament (cached until the save changes), else None."""
        if not s or s.get("error"):
            return None
        hit = self._loaded.get(s["id"])
        if hit and hit[0] == s.get("updated"):
            return hit[1]
        try:
            t = persistence.load(s["id"])
        except Exception as e:
            log.warning("tournament %s: %s", s["id"], e)
            return None
        self._loaded[s["id"]] = (s.get("updated"), t)
        return t

    def reload(self):
        self.templates = formats.load_templates()
        self._saves = persistence.list_saves()
        for w in self._cards:
            self.focus.unregister(w)
        self._cards = []
        count = {"progress": 0, "done": 0}
        for _section, _heading, rows in self.sections.values():
            clear_layout(rows)
        # in progress first, then completed: the focus order follows the page
        for key in ("progress", "done"):
            for s in self._saves:
                if ("done" if s.get("champion") else "progress") != key:
                    continue
                t = self._tournament(s)
                tpl = (t.template if t else None) or self.templates.get(s.get("template_id"))
                card = SaveCard(self.ds, s, tpl if not s.get("error") else None,
                                report.where_now(t) if t else "")
                card.activated.connect(lambda s=s: (self._select(s), self._continue()))
                card.focused.connect(lambda s=s: self._select(s))
                card.delete_zone.clicked.connect(lambda s=s, c=card: (c.setFocus(), self._select(s),
                                                                      self._delete()))
                self.sections[key][2].addWidget(card)
                self.focus.register(card)
                self._cards.append(card)
                count[key] += 1
        for key, (section, heading, _rows) in self.sections.items():
            section.setVisible(bool(count[key]))
            heading.set_right(str(count[key]))
        keep = self._selected["id"] if self._selected else None
        self._select(next((s for s in self._saves if s["id"] == keep), None), force=True)

    def _select(self, s, force=False):
        if s is self._selected and not force:
            return
        self._selected = s
        for c in self._cards:
            c.selected = c.save is s
            c.update()
        self.new_tile.selected = s is None
        self.new_tile.update()
        has = s is not None
        self.hints.set_hints([("A", "continue"), ("X", "delete"), ("Y", "new"), ("B", "back")] if has
                             else [("A", "new tournament"), ("B", "back")])

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
                self._loaded.pop(s["id"], None)
                self._selected = None
                self.reload()
                (self._cards[0] if self._cards else self.new_tile).setFocus()
            elif s in self._saves:
                card = next((c for c in self._cards if c.save is s), None)
                if card is not None:
                    card.setFocus()
        ConfirmDialog(self, "Delete tournament?", f"“{s['name']}” and all its progress will be lost.",
                      [("CANCEL", "neutral", "cancel"), ("DELETE", "danger", "ok")], done)
