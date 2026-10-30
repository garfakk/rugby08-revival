"""
screens/tournament/hub.py — Tournament mode's front door.

Left: one list — NEW TOURNAMENT on top, then the saved tournaments, newest
first (emblem, name and edition, your team, where it stands, last played).
Right: a preview of whatever is focused in the list, never a copy of its
card: for a save, how your team is doing (position or campaign, record),
its next match and last result, the options, with CONTINUE / DELETE; for
NEW TOURNAMENT, the competitions on offer. The cards rise in one after the
other. Pad: A open, X delete, Y new, B back.
"""
from datetime import datetime

from PyQt5.QtCore import QRectF, Qt
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QScrollArea, QVBoxLayout, QWidget

from app.input import KEYMAP, Action
from app.screen_base import Screen
from app.tournament import calendar, engine, formats, persistence, report
from app.tournament.session import TournamentSession
from shared.log import get_logger
from ui import motion
from ui.broadcast import Card, HintBar, display_label, eyebrow_label, page_header, tracked_font
from ui.editor_kit import ConfirmDialog, Note, compact_button
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BTN_HEIGHT, FG_MUTED, FG_PRIMARY, FG_SECONDARY,
                      FG_TERTIARY, FONT_DISPLAY, GREEN, WARN)

from .common import (ActivatableCard, FormStrip, PixmapLabel, ProgressStrip, SectionTitle, YOU_TINT,
                     clear_layout, competition_emblem, hline, team_crest, tournament_crest, transparent)

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
    if opts.get("reality"):
        parts.append("reality mode")
    return " · ".join(p for p in parts if p.strip())


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


def _record(t, team_id) -> str:
    played = [f for f in t.fixtures if f.played and f.involves(team_id)]
    if not played:
        return "no match played yet"
    won = sum(1 for f in played if f.result.winner_id() == team_id)
    drawn = sum(1 for f in played if f.result.winner_id() is None)
    lost = len(played) - won - drawn
    return f"played {len(played)} · won {won}" + (f" · drawn {drawn}" if drawn else "") + f" · lost {lost}"


class TournamentHubScreen(Screen):
    def __init__(self, ds, on_back, on_new, on_open):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_new = on_new
        self.on_open = on_open
        self._saves = []
        self._cards = []
        self._loaded = {}            # save id -> (updated, Tournament) for the previews
        self._selected = None        # the focused save; None = NEW TOURNAMENT
        self._editions = None        # formats.editions(), for the NEW TOURNAMENT preview
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

        # the list: new, then the saves
        left = transparent(QWidget(), "hubLeft")
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)
        self.saves_title = SectionTitle("tournaments")
        lv.addWidget(self.saves_title)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
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
        self.list_layout = QVBoxLayout()
        self.list_layout.setSpacing(10)
        hv.addLayout(self.list_layout)
        hv.addStretch(1)
        scroll.setWidget(holder)
        scroll.viewport().setStyleSheet("background: transparent;")
        lv.addWidget(scroll, stretch=1)
        bl.addWidget(left, stretch=3)

        # the preview of the focused entry
        right = transparent(QWidget(), "hubRight")
        rv = QVBoxLayout(right)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.setSpacing(12)
        self.preview_title = SectionTitle("preview")
        rv.addWidget(self.preview_title)
        self.detail = Card(stripe=ACCENT, translucent=True)
        dv = QVBoxLayout(self.detail)
        dv.setContentsMargins(26, 20, 26, 22)
        dv.setSpacing(10)
        self.d_holder = QVBoxLayout()
        self.d_holder.setSpacing(10)
        dv.addLayout(self.d_holder)
        dv.addSpacing(6)
        row = QHBoxLayout()
        row.setSpacing(10)
        self.delete_btn = compact_button("DELETE", "danger", height=BTN_HEIGHT)
        self.delete_btn.clicked.connect(self._delete)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        self.continue_btn = compact_button("CONTINUE", "primary", height=BTN_HEIGHT)
        self.continue_btn.setMinimumWidth(220)
        self.continue_btn.clicked.connect(self._activate)
        row.addWidget(self.continue_btn)
        dv.addLayout(row)
        for b in (self.continue_btn, self.delete_btn):
            self.focus.register(b)
        rv.addWidget(self.detail)
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
        motion.stagger_in([self.new_tile] + self._cards[:8] + [self.detail], step=55)

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
            log.warning("tournament preview %s: %s", s["id"], e)
            return None
        self._loaded[s["id"]] = (s.get("updated"), t)
        return t

    def reload(self):
        self.templates = formats.load_templates()
        self._editions = None
        self._saves = persistence.list_saves()
        for c in self._cards:
            self.focus.unregister(c)
        clear_layout(self.list_layout)
        self._cards = []
        for s in self._saves:
            t = self._tournament(s)
            tpl = (t.template if t else None) or self.templates.get(s.get("template_id"))
            card = SaveCard(self.ds, s, tpl if not s.get("error") else None,
                            report.where_now(t) if t else "")
            card.activated.connect(lambda s=s: (self._select(s), self._continue()))
            card.focused.connect(lambda s=s: self._select(s))
            self.focus.register(card)
            self.list_layout.addWidget(card)
            self._cards.append(card)
        self.saves_title.set_right(f"{len(self._saves)} saved" if self._saves else "")
        keep = self._selected["id"] if self._selected else None
        self._select(next((s for s in self._saves if s["id"] == keep), self._saves[0] if self._saves else None),
                     force=True)

    def _select(self, s, force=False):
        if s is self._selected and not force:
            return
        self._selected = s
        for c in self._cards:
            c.selected = c.save is s
            c.update()
        self.new_tile.selected = s is None
        self.new_tile.update()
        clear_layout(self.d_holder)
        if s is None:
            self._preview_new()
        else:
            self._preview_save(s)
        if self.isVisible():
            motion.fade_in(self.detail, ms=160)
        has = s is not None
        self.hints.set_hints([("A", "continue"), ("X", "delete"), ("Y", "new"), ("B", "back")] if has
                             else [("A", "new tournament"), ("B", "back")])

    def _preview_new(self):
        self.preview_title.set_title("new tournament")
        v = self.d_holder
        v.addWidget(display_label("start a new tournament", 20, QFont.Bold, track=0.8))
        v.addWidget(Note("Pick a competition and one of its editions, take charge of a team and play "
                         "every round. Progress is saved after each match.", color=FG_SECONDARY))
        v.addWidget(hline())
        v.addWidget(eyebrow_label("competitions", color=ACCENT, size=10))
        if self._editions is None:
            self._editions = formats.editions(self.ds, self.templates)
        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.setVerticalSpacing(8)
        for i, eds in enumerate(list(self._editions.values())[:8]):
            tpl, label = eds[0].template, eds[0].label
            cell = QHBoxLayout()
            cell.setSpacing(10)
            cell.addWidget(PixmapLabel(36, competition_emblem(self.ds, tpl, 36)))
            name = str(tpl.get("name", ""))
            name = name[:-len(label)].strip() if label and name.endswith(label) else name
            span = f"{eds[-1].label} – {eds[0].label}" if len(eds) > 1 else label
            text = QVBoxLayout()
            text.setSpacing(0)
            text.addWidget(eyebrow_label(name, color=FG_PRIMARY, size=11))
            text.addWidget(eyebrow_label(span, color=FG_TERTIARY, size=9))
            cell.addLayout(text, stretch=1)
            grid.addLayout(cell, i // 2, i % 2)
        v.addLayout(grid)
        self.delete_btn.hide()
        self.continue_btn.setEnabled(True)
        self.continue_btn.setText("NEW TOURNAMENT")

    def _preview_save(self, s):
        v = self.d_holder
        self.delete_btn.show()
        self.preview_title.set_title(s.get("name", ""))
        if s.get("error"):
            v.addWidget(display_label("this save can't be read", 18, QFont.Bold, track=0.8, color=WARN))
            v.addWidget(Note(s["error"], color=FG_TERTIARY))
            self.continue_btn.setEnabled(False)
            self.continue_btn.setText("CONTINUE")
            return
        t = self._tournament(s)
        self.continue_btn.setEnabled(t is not None)
        self.continue_btn.setText("VIEW" if s.get("champion") else "CONTINUE")
        if t is None:
            v.addWidget(Note("This save can't be opened.", color=WARN))
            return
        # where it stands
        caption = report.where_now(t)
        v.addWidget(eyebrow_label(caption, color=AWAY_TINT if t.finished else ACCENT, size=11))
        bar = ProgressStrip(height=6)
        bar.set_value(1.0 if t.finished else t.day / max(1, t.last_day() + 1),
                      AWAY_TINT if t.finished else ACCENT)
        v.addWidget(bar)
        if t.finished and t.champion:
            row = QHBoxLayout()
            row.setSpacing(12)
            row.addWidget(PixmapLabel(44, tournament_crest(self.ds, t, t.champion, 44)))
            row.addWidget(display_label(f"{t.team_name(t.champion)} are champions", 16, QFont.Bold,
                                        track=0.6, color=AWAY_TINT), stretch=1)
            v.addLayout(row)
        # each team you manage: how it's doing, its next match, last result
        for e in t.human_teams():
            v.addWidget(hline())
            tid = e.team_id
            row = QHBoxLayout()
            row.setSpacing(14)
            row.addWidget(PixmapLabel(56, tournament_crest(self.ds, t, tid, 56)))
            col = QVBoxLayout()
            col.setSpacing(3)
            col.addWidget(display_label(t.team_name(tid), 18, QFont.Bold, track=0.6, color=YOU_TINT))
            status = report.campaign_summary(t, tid) or "the tournament is about to start"
            if not t.finished and engine.is_eliminated(t, tid):
                status = f"out · {status}"
            col.addWidget(Note(status[0].upper() + status[1:], color=FG_PRIMARY))
            col.addWidget(Note(_record(t, tid)[0].upper() + _record(t, tid)[1:], color=FG_TERTIARY))
            row.addLayout(col, stretch=1)
            row.addWidget(FormStrip([("D" if f.result.winner_id() is None else
                                      ("W" if f.result.winner_id() == tid else "L"))
                                     for f in t.fixtures if f.played and f.involves(tid)][-5:], cell=16,
                                    align_right=True))
            v.addLayout(row)
            nxt = next((f for f in t.fixtures if not f.played and f.involves(tid)), None)
            if nxt:
                other = nxt.away if nxt.home == tid else nxt.home
                when = calendar.short_date(calendar.fixture_date(t, nxt))
                text = " · ".join(x for x in (f"v {t.team_name(other)}" if other else "", nxt.label, when) if x)
                v.addLayout(self._line("next", text))
            last = next((f for f in reversed(t.fixtures) if f.played and f.involves(tid)), None)
            if last:
                v.addLayout(self._line("last", f"{report.fixture_caption(t, last)} "
                                               f"{last.result.score_text()} · {last.label}"))
        v.addWidget(hline())
        v.addWidget(Note(_options_line(s.get("options") or {}), color=FG_TERTIARY))
        v.addWidget(Note("Last played " + (relative_time(s.get("updated")) or "—"), color=FG_MUTED))

    @staticmethod
    def _line(tag, text):
        row = QHBoxLayout()
        row.setSpacing(10)
        label = eyebrow_label(tag, color=ACCENT, size=9)
        label.setFixedWidth(44)
        row.addWidget(label)
        row.addWidget(Note(text, color=FG_SECONDARY), stretch=1)
        return row

    # ── actions ──────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action == Action.ALT and self._selected:
            self._delete(); event.accept(); return
        if action == Action.AUX:
            self.on_new(); event.accept(); return
        super().keyPressEvent(event)

    def _activate(self):
        if self._selected is None:
            self.on_new()
        else:
            self._continue()

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
        ConfirmDialog(self, "Delete tournament?", f"“{s['name']}” and all its progress will be lost.",
                      [("CANCEL", "neutral", "cancel"), ("DELETE", "danger", "ok")], done)
