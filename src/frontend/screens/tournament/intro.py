"""
screens/tournament/intro.py — The few seconds between creating a tournament
and its dashboard: the draw.

  1 the competition's logo grows in under a light sweep, its name below
  2 logo and name rise to the top; the pools appear and every team's crest
    drops into its pool, one after the other (yours highlighted)
  3 YOUR FIRST MATCH slides in from both sides
  4 the dashboard opens by itself

Painted on a clock (ms since it started) on a 1920 x 1080 canvas scaled to
the window. The first key or click shows the whole draw at once, the next
opens the dashboard (as does the end of the hold). With animations off
(user_prefs.animations) it opens on the final frame.
"""
from PyQt5.QtCore import QElapsedTimer, QRectF, Qt, QTimer
from PyQt5.QtGui import QColor, QFont, QLinearGradient, QPainter, QPen, QPixmap, QRadialGradient

from app.screen_base import Screen
from app.tournament import calendar
from ui import motion
from ui.broadcast import tracked_font
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BG_CARD, BORDER, FG_MUTED, FG_PRIMARY,
                      FG_TERTIARY, FONT_DISPLAY)

from .common import YOU_TINT, competition_emblem, tournament_crest

VIRTUAL_W, VIRTUAL_H = 1920, 1080
EMBLEM = 220
LOGO_MS = 1500           # the logo and name on their own
RISE_MS = 600            # ... rising to the top
DROP_STEP = 45           # between two crests landing
DROP_MS = 320            # one crest's fall
MATCH_MS = 700           # your first match sliding in
HOLD_MS = 2600           # the final frame, before the dashboard opens
COL_W, ROW_H = 300, 38
DRAW_TOP = 250
MAX_ROWS = 8             # a bigger pool (a league) wraps into more columns


def _ease(x):
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _ease_back(x):
    x = max(0.0, min(1.0, x))
    c1 = 1.5
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _phase(ms, start, length):
    return max(0.0, min(1.0, (ms - start) / max(1, length)))


def draw_columns(t):
    """[(title, [team ids])] of the first stage's pools (a big one split in
    columns of MAX_ROWS), or every team when the competition has no pools."""
    stage = next((s for s in t.stages if s.kind == "round_robin" and s.groups), None)
    if stage:
        groups = [(g.name if len(stage.groups) > 1 else "the teams", list(g.teams)) for g in stage.groups]
    else:
        groups = [("teams", list(t.teams))]
    cols = []
    for name, teams in groups:
        for i in range(0, max(1, len(teams)), MAX_ROWS):
            cols.append((name if i == 0 else "", teams[i:i + MAX_ROWS]))
    return cols


class TournamentIntroScreen(Screen):
    def __init__(self, ds, on_done):
        super().__init__()
        self.ds = ds
        self.on_done = on_done
        self.t = None
        self._emblem = None
        self._title, self._edition, self._name = "", "", ""
        self._columns, self._humans, self._first = [], set(), None
        self._ms = 0
        self._duration = LOGO_MS
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)
        self._hold = QTimer(self)
        self._hold.setSingleShot(True)
        self._hold.timeout.connect(self._finish)
        self._pending = False

    def set_session(self, session):
        t = self.t = session.t
        tpl = t.template
        self._emblem = competition_emblem(self.ds, tpl, EMBLEM)
        self._title = str(tpl.get("name", "")).upper()
        self._edition = str(tpl.get("branding_season") or "")
        self._name = t.name.upper() if t.name and t.name.upper() != self._title else ""
        self._columns = draw_columns(t)
        self._humans = {e.team_id for e in t.human_teams()}
        self._first = next((f for f in sorted(t.fixtures, key=lambda f: f.day)
                            if f.home in self._humans or f.away in self._humans), None)
        n = sum(len(teams) for _n, teams in self._columns)
        self._drops_at = LOGO_MS + RISE_MS - 200
        self._match_at = self._drops_at + n * DROP_STEP + DROP_MS + 150
        self._duration = self._match_at + (MATCH_MS if self._first else 0)

    # ── the clock ────────────────────────────────────────────────────────
    def on_show(self):
        super().on_show()
        self._pending = True
        self._hold.stop()
        if motion.enabled():
            self._ms = 0
            self._clock.start()
            self._timer.start()
        else:
            self._settle()

    def _tick(self):
        self._ms = min(self._duration, self._clock.elapsed())
        if self._ms >= self._duration:
            self._settle()
        self.update()

    def _settle(self):
        self._ms = self._duration
        self._timer.stop()
        if not self._hold.isActive():
            self._hold.start(HOLD_MS)
        self.update()

    def _advance(self):
        if self._ms < self._duration:
            self._settle()
        else:
            self._finish()

    def _finish(self):
        if self._pending:
            self._pending = False
            self._timer.stop()
            self._hold.stop()
            self.on_done()

    def mousePressEvent(self, event):
        self._advance()

    def keyPressEvent(self, event):
        self._advance()
        event.accept()

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(BG_BASE))
        if self._emblem is None:
            return
        glow = QRadialGradient(self.width() / 2, self.height() * 0.35, max(self.width(), self.height()) * 0.6)
        c = QColor(ACCENT)
        c.setAlpha(34)
        glow.setColorAt(0, c)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), glow)
        scale = max(0.1, min(1.0, self.width() / VIRTUAL_W, self.height() / VIRTUAL_H))
        w, h = self.width() / scale, self.height() / scale
        p.scale(scale, scale)
        ms = self._ms
        self._paint_header(p, ms, w, h)
        bottom = self._draw_bottom(w)
        if ms >= self._drops_at - 300:
            self._paint_draw(p, ms, w, h)
        if self._first and ms >= self._match_at:
            self._paint_first(p, ms, w, min(h - 210, bottom + 70))
        if ms >= self._duration:
            self._text(p, QRectF(0, h - 60, w, 26), "A  CONTINUE", 12, FG_MUTED, track=2.0)

    def _text(self, p, rect, text, size, color, weight=QFont.Bold, track=1.0, opacity=1.0,
              align=Qt.AlignCenter):
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.setFont(tracked_font(FONT_DISPLAY, size, weight, track))
        p.setPen(QColor(color))
        p.drawText(rect, align, text)
        p.restore()

    def _swept(self, progress):
        """The logo with a band of light across it at `progress` (0..1),
        only on the logo's own pixels."""
        if not 0 < progress < 1:
            return self._emblem
        pix = QPixmap(self._emblem)
        pw = pix.width()
        x = -pw * 0.3 + pw * 1.6 * progress
        g = QLinearGradient(x - pw * 0.25, 0, x + pw * 0.25, pix.height() * 0.3)
        g.setColorAt(0, QColor(255, 255, 255, 0))
        g.setColorAt(0.5, QColor(255, 255, 255, 110))
        g.setColorAt(1, QColor(255, 255, 255, 0))
        q = QPainter(pix)
        q.setCompositionMode(QPainter.CompositionMode_SourceAtop)
        q.fillRect(pix.rect(), g)
        q.end()
        return pix

    def _paint_header(self, p, ms, w, h):
        a = _ease(_phase(ms, 0, 700))
        grow = 0.85 + 0.15 * _ease(_phase(ms, 0, 900))
        rise = _ease(_phase(ms, LOGO_MS, RISE_MS))
        # centred to start with, then up to the top at half size
        k = 1.0 - 0.5 * rise
        top0, top1 = h / 2 - 190, 26
        top = top0 + (top1 - top0) * rise + (1 - a) * 24
        p.save()
        p.translate(w / 2, top)
        p.scale(k, k)
        size = EMBLEM * grow
        p.setOpacity(a)
        p.drawPixmap(QRectF(-size / 2, (EMBLEM - size) / 2, size, size),
                     self._swept(_phase(ms, 450, 700)), QRectF(self._emblem.rect()))
        y = EMBLEM + 28
        ta = _ease(_phase(ms, 350, 600))
        self._text(p, QRectF(-w, y, 2 * w, 56), self._title, 40, FG_PRIMARY, track=3.0, opacity=ta)
        label = " · ".join(x for x in (self._edition, self._name) if x)
        if label:
            self._text(p, QRectF(-w, y + 64, 2 * w, 32), label, 18, ACCENT, QFont.DemiBold, track=4.0,
                       opacity=_ease(_phase(ms, 600, 600)) * (1 - rise))
        p.restore()
        if rise > 0:
            self._text(p, QRectF(0, top1 + (EMBLEM + 104) * k, w, 26), "THE DRAW", 14, ACCENT,
                       track=5.0, opacity=rise)

    def _grid(self, w):
        """(columns per row, x of the first, height of a row of columns)."""
        cols = self._columns
        gap = 22
        per_row = min(len(cols), max(1, int((w - 160 + gap) // (COL_W + gap))))
        x_total = per_row * COL_W + (per_row - 1) * gap
        rows_h = max(len(teams) for _n, teams in cols) * ROW_H + 46
        return per_row, (w - x_total) / 2, rows_h, gap

    def _draw_bottom(self, w):
        if not self._columns:
            return DRAW_TOP
        per_row, _x0, rows_h, _gap = self._grid(w)
        rows = (len(self._columns) + per_row - 1) // per_row
        return DRAW_TOP + rows * (rows_h + 18)

    def _paint_draw(self, p, ms, w, h):
        cols = self._columns
        if not cols:
            return
        per_row, x0, rows_h, gap = self._grid(w)
        top = DRAW_TOP
        i = 0
        for ci, (name, teams) in enumerate(cols):
            col_x = x0 + (ci % per_row) * (COL_W + gap)
            col_y = top + (ci // per_row) * (rows_h + 18)
            ca = _ease(_phase(ms, self._drops_at - 300 + ci * 60, 400))
            card = QRectF(col_x, col_y, COL_W, 40 + len(teams) * ROW_H + 6)
            p.save()
            p.setOpacity(ca)
            p.fillRect(card, QColor(BG_CARD))
            p.setPen(QPen(QColor(BORDER), 1))
            p.drawRect(card)
            p.fillRect(QRectF(card.x(), card.y(), card.width(), 3), QColor(ACCENT))
            p.restore()
            if name:
                self._text(p, QRectF(col_x + 16, col_y + 8, COL_W - 32, 26), name.upper(), 14, ACCENT,
                           track=2.0, opacity=ca, align=Qt.AlignLeft | Qt.AlignVCenter)
            for ri, tid in enumerate(teams):
                d = _phase(ms, self._drops_at + i * DROP_STEP, DROP_MS)
                i += 1
                if d <= 0:
                    continue
                y = col_y + 42 + ri * ROW_H - 26 * (1 - _ease_back(d))
                mine = tid in self._humans
                row = QRectF(col_x + 6, y, COL_W - 12, ROW_H - 4)
                p.save()
                p.setOpacity(min(1.0, d * 2))
                if mine:
                    col = QColor(YOU_TINT)
                    col.setAlpha(46)
                    p.fillRect(row, col)
                    p.fillRect(QRectF(row.x(), row.y(), 3, row.height()), QColor(YOU_TINT))
                pix = tournament_crest(self.ds, self.t, tid, 26)
                p.drawPixmap(QRectF(row.x() + 12, row.center().y() - 13, 26, 26), pix, QRectF(pix.rect()))
                p.setFont(tracked_font(FONT_DISPLAY, 14, QFont.Bold if mine else QFont.DemiBold, 0.6))
                p.setPen(QColor(YOU_TINT if mine else FG_PRIMARY))
                p.drawText(QRectF(row.x() + 50, row.y(), row.width() - 60, row.height()),
                           Qt.AlignLeft | Qt.AlignVCenter,
                           p.fontMetrics().elidedText(self.t.team_name(tid).upper(), Qt.ElideRight,
                                                      int(row.width() - 60)))
                p.restore()

    def _paint_first(self, p, ms, w, y):
        f = self._first
        a = _ease(_phase(ms, self._match_at, MATCH_MS))
        when = calendar.short_date(calendar.fixture_date(self.t, f))
        self._text(p, QRectF(0, y, w, 24), "YOUR FIRST MATCH" + (f"  ·  {when.upper()}" if when else ""), 13,
                   AWAY_TINT, track=4.0, opacity=a)
        slide = 220 * (1 - a)
        for tid, cx, align in ((f.home, w / 2 - 190 - slide, Qt.AlignRight),
                               (f.away, w / 2 + 190 + slide, Qt.AlignLeft)):
            pix = tournament_crest(self.ds, self.t, tid, 72)
            p.save()
            p.setOpacity(a)
            p.drawPixmap(QRectF(cx - 36, y + 34, 72, 72), pix, QRectF(pix.rect()))
            p.restore()
            name_rect = (QRectF(cx - 430, y + 50, 380, 40) if align == Qt.AlignRight
                         else QRectF(cx + 50, y + 50, 380, 40))
            self._text(p, name_rect, (self.t.team_name(tid) if tid else "TBD").upper(), 24,
                       YOU_TINT if tid in self._humans else FG_PRIMARY, track=1.4, opacity=a,
                       align=align | Qt.AlignVCenter)
        self._text(p, QRectF(w / 2 - 60, y + 50, 120, 40), "VS", 24, FG_TERTIARY, track=3.0, opacity=a)
