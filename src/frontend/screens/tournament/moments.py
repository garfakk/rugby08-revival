"""
screens/tournament/moments.py — The tournament's big moments, full screen.

After an action plays matches, the dashboard hands what changed to
`moments_after()` and plays the overlays it returns, one after the other:

  MatchdayRecap    full time: your match big (the score counts up), the
                   other results sliding in, your pool position moving
  StageCard        a new stage or knockout round begins ("QUARTER-FINALS")
  EliminationCard  your last team is out
  ChampionMoment   the final whistle of the tournament: crest, confetti

Each is painted on a clock (ms since it started), so it can be skipped to
its final frame at any time: the first key or click shows the whole
moment, the next one closes it. With animations off (user_prefs.
animations) every moment opens on its final frame.

Pure painting: no child widgets, nothing focusable but the overlay itself.
"""
import math
import random
from dataclasses import dataclass, field

from PyQt5.QtCore import QElapsedTimer, QEvent, QPointF, QRectF, Qt, QTimer
from PyQt5.QtGui import (QColor, QFont, QImage, QLinearGradient, QPainter, QPen, QPixmap,
                         QRadialGradient)
from PyQt5.QtWidgets import QWidget

from app.input import KEYMAP, Action
from app.tournament import engine, report, standings
from ui import motion
from ui.broadcast import tracked_font
from ui.theme import (ACCENT, AWAY_TINT, BG_CARD, BORDER, DANGER_LITE, FG_MUTED,
                      FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FONT_DISPLAY, GREEN, INFO, WARN)

from .common import YOU_TINT, tournament_crest

FRAME_MS = 16
FADE_OUT_MS = 180
VIRTUAL_W, VIRTUAL_H = 1920, 1080


def _ease(x):
    """OutCubic on 0..1 (clamped)."""
    x = max(0.0, min(1.0, x))
    return 1 - (1 - x) ** 3


def _ease_back(x):
    """OutBack: overshoots a little, then settles — for things landing."""
    x = max(0.0, min(1.0, x))
    c1 = 1.4
    return 1 + (c1 + 1) * (x - 1) ** 3 + c1 * (x - 1) ** 2


def _phase(ms, start, length):
    """0..1 progress of a phase starting at `start` ms lasting `length`."""
    return max(0.0, min(1.0, (ms - start) / max(1, length)))


def ordinal(n):
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ── what changed ─────────────────────────────────────────────────────────
@dataclass
class Before:
    """The bits of a tournament the moments compare against."""
    finished: bool = False
    alive: set = field(default_factory=set)
    positions: dict = field(default_factory=dict)     # team_id -> (group name, 1-based position)
    stage_key: tuple = ()


def human_ids(t):
    return [e.team_id for e in t.human_teams()]


def pool_position(t, team_id):
    """(group name, 1-based position, qualify count) of the team's pool while
    the pool stage runs, else None."""
    for st in t.stages:
        if st.kind != "round_robin" or st.status == "done":
            continue
        for g in st.groups:
            if team_id in g.teams:
                tab = standings.group_table(t, st, g)
                pos = next((i + 1 for i, r in enumerate(tab) if r.team_id == team_id), None)
                name = g.name if len(st.groups) > 1 else st.name
                return name, pos, int(st.spec.get("qualify", 0))
    return None


def stage_key(t):
    """What stage / round the next unplayed match belongs to: (stage id,
    round name when a knockout)."""
    nxt = next((f for f in sorted(t.fixtures, key=lambda f: f.day) if not f.played), None)
    if not nxt:
        return ()
    return (nxt.stage_id, nxt.round_name if nxt.knockout else "")


def snapshot(t) -> Before:
    humans = human_ids(t)
    positions = {}
    for h in humans:
        pp = pool_position(t, h)
        if pp:
            positions[h] = pp[:2]
    return Before(finished=t.finished,
                  alive={h for h in humans if not engine.is_eliminated(t, h)},
                  positions=positions, stage_key=stage_key(t))


def moments_after(ds, t, before: Before, done) -> list:
    """The overlays to play for the matches in `done` (in order)."""
    out = []
    played = [f for f in (done or []) if f.played]
    if played:
        out.append(MatchdayRecap(ds, t, before, played))
    humans = human_ids(t)
    if t.finished and not before.finished:
        out.append(ChampionMoment(ds, t))
        return out
    alive = {h for h in humans if not engine.is_eliminated(t, h)}
    if humans and before.alive and not alive:
        out.append(EliminationCard(ds, t, sorted(before.alive)[0]))
    key = stage_key(t)
    if key and before.stage_key and key != before.stage_key:
        out.append(StageCard(ds, t))
    return out


def play_moments(host, moments, on_done=None):
    """Play the overlays one after the other over `host`; on_done once the
    last one closes (at once when there are none)."""
    queue = list(moments)

    def nxt():
        if not queue:
            if on_done:
                on_done()
            return
        m = queue.pop(0)
        m.open(host, nxt)
    nxt()


# ── the base overlay ─────────────────────────────────────────────────────
class MomentOverlay(QWidget):
    """A full-screen painted moment over `host`. Subclasses set DURATION
    (ms until the final frame) and paint_moment(p, ms)."""

    DURATION = 1500
    AUTO_CLOSE = None          # ms after the final frame to close by itself (None: wait for a key)
    HINT = "A  CONTINUE"

    def __init__(self, ds, t):
        super().__init__()
        self.ds, self.t = ds, t
        self._ms = 0
        self._clock = QElapsedTimer()
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._closing = False
        self._fade = 1.0
        self._on_close = None
        self.vw, self.vh = VIRTUAL_W, VIRTUAL_H       # the canvas paint_moment draws on
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)

    # lifecycle
    def open(self, host, on_close=None):
        self._on_close = on_close
        self.setParent(host)
        self.setGeometry(host.rect())
        host.installEventFilter(self)
        self.show()
        self.raise_()
        self.setFocus(Qt.OtherFocusReason)
        if motion.enabled():
            self._clock.start()
            self._timer.start()
        else:
            self._ms = self.DURATION
            self._settled()

    @property
    def settled(self):
        return self._ms >= self.DURATION

    def skip(self):
        """Jump to the final frame."""
        self._ms = self.DURATION
        self._settled()
        self.update()

    def _tick(self):
        if self._closing:
            self._fade = 1.0 - min(1.0, self._clock.elapsed() / FADE_OUT_MS)
            if self._fade <= 0:
                self._finish()
                return
        elif not self.settled:
            self._ms = min(self.DURATION, self._clock.elapsed())
            if self.settled:
                self._settled()
        self.update()

    def _settled(self):
        """The final frame is on: the hint keeps breathing at a low rate,
        and a moment that closes by itself starts counting."""
        if motion.enabled():
            self._timer.setInterval(50)
            if not self._timer.isActive():
                self._timer.start()
            if self.AUTO_CLOSE is not None:
                QTimer.singleShot(self.AUTO_CLOSE, self._auto_close)

    def _auto_close(self):
        if not self._closing and self.isVisible():
            self.close_moment()

    def close_moment(self):
        if self._closing:
            return
        self._closing = True
        if motion.enabled():
            self._clock.restart()
            self._timer.setInterval(FRAME_MS)
            self._timer.start()
        else:
            self._finish()

    def _finish(self):
        self._timer.stop()
        host = self.parentWidget()
        if host is not None:
            host.removeEventFilter(self)
        self.hide()
        cb, self._on_close = self._on_close, None
        self.deleteLater()
        if cb:
            cb()

    def eventFilter(self, watched, event):
        if watched is self.parentWidget() and event.type() == QEvent.Resize:
            self.setGeometry(watched.rect())
        return False

    # input: first press shows everything, the next closes
    def _advance(self):
        if self._closing:
            return
        if not self.settled:
            self.skip()
        else:
            self.close_moment()

    def mousePressEvent(self, event):
        self._advance()
        event.accept()

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action in (Action.CONFIRM, Action.BACK) or event.key() in (
                Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_Escape):
            self._advance()
        event.accept()            # nothing reaches the dashboard behind

    # painting
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.setOpacity(self._fade)
        self.paint_backdrop(p)
        # the moment itself is laid out for 1920 x 1080 and scaled down to
        # fit a smaller window (never up: big crests would just blur)
        scale = max(0.1, min(1.0, self.width() / VIRTUAL_W, self.height() / VIRTUAL_H))
        p.scale(scale, scale)
        self.vw, self.vh = self.width() / scale, self.height() / scale
        self.paint_moment(p, self._ms)
        if self.settled and not self._closing and self.HINT:
            self.paint_hint(p)

    def paint_backdrop(self, p):
        w, h = self.width(), self.height()
        a = _ease(_phase(self._ms, 0, 260))
        p.fillRect(self.rect(), QColor(4, 10, 4, int(238 * a)))
        glow = QRadialGradient(w / 2, h * 0.42, max(w, h) * 0.55)
        c = QColor(self.glow_color())
        c.setAlpha(int(46 * a))
        glow.setColorAt(0, c)
        glow.setColorAt(1, QColor(0, 0, 0, 0))
        p.fillRect(self.rect(), glow)

    def glow_color(self):
        return ACCENT

    def paint_hint(self, p):
        p.save()
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._clock.elapsed() / 380.0)) \
            if self._clock.isValid() else 1.0
        p.setOpacity(self._fade * pulse)
        p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, 2.0))
        p.setPen(QColor(FG_TERTIARY))
        p.drawText(QRectF(0, self.vh - 70, self.vw, 30), Qt.AlignCenter, self.HINT)
        p.restore()

    def paint_moment(self, p, ms):
        pass

    # shared drawing bits
    def text(self, p, rect, txt, size, color=FG_PRIMARY, weight=QFont.Bold, track=1.0,
             align=Qt.AlignCenter, opacity=1.0):
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.setFont(tracked_font(FONT_DISPLAY, size, weight, track))
        p.setPen(QColor(color))
        p.drawText(rect, align, txt)
        p.restore()

    def crest(self, p, team_id, cx, cy, size, opacity=1.0, scale=1.0, grey=False):
        pix = tournament_crest(self.ds, self.t, team_id, size)
        if pix is None or pix.isNull():
            return
        if grey:
            pix = QPixmap.fromImage(pix.toImage().convertToFormat(QImage.Format_Grayscale8))
        s = size * scale
        p.save()
        p.setOpacity(p.opacity() * opacity)
        p.drawPixmap(QRectF(cx - s / 2, cy - s / 2, s, s), pix, QRectF(pix.rect()))
        p.restore()

    def sweep(self, p, y, h, progress, color=ACCENT):
        """A coloured band wiping in from the left (title underline)."""
        w = self.vw
        band = QRectF(0, y, w * _ease(progress), h)
        g = QLinearGradient(0, 0, w, 0)
        c0, c1 = QColor(color), QColor(color)
        c0.setAlpha(0)
        c1.setAlpha(200)
        g.setColorAt(0, c0)
        g.setColorAt(0.5, c1)
        g.setColorAt(1, c0)
        p.fillRect(band, g)


# ── matchday recap ───────────────────────────────────────────────────────
class MatchdayRecap(MomentOverlay):
    """Full time: your match first, then the rest of the results, then how
    your pool position moved."""

    MAX_OTHERS = 8

    def __init__(self, ds, t, before, played):
        super().__init__(ds, t)
        humans = set(human_ids(t))
        self.mine = next((f for f in played if f.home in humans or f.away in humans), None)
        self.others = [f for f in played if f is not self.mine]
        self.humans = humans
        self.focus_team = None
        if self.mine:
            self.focus_team = self.mine.home if self.mine.home in humans else self.mine.away
        self.moves = []                      # [(team_id, group, old, new, qualify)]
        for h in sorted(humans):
            pp = pool_position(t, h)
            if pp and pp[1]:
                old = before.positions.get(h, (pp[0], None))[1]
                self.moves.append((h, pp[0], old, pp[1], pp[2]))
        ref = self.mine or (played[0] if played else None)
        if ref is None:
            self.eyebrow = "RESULTS"
        elif ref.knockout:
            self.eyebrow = (ref.round_name or "knockouts").upper()
        else:
            days = {f.day for f in played}
            self.eyebrow = (f"MATCHDAY {ref.day + 1}" if len(days) == 1
                            else f"MATCHDAYS {min(days) + 1}–{max(days) + 1}")
            if ref.group and self.mine:
                self.eyebrow += f"  ·  {self._group_name(ref)}".upper()
        self.title = "FULL TIME" if self.mine else "AROUND THE GROUNDS"
        n_others = min(len(self.others), self.MAX_OTHERS)
        self._others_start = 1500 if self.mine else 500
        self.DURATION = self._others_start + n_others * 90 + 500

    def _group_name(self, f):
        st = self.t.stage(f.stage_id)
        g = st.group(f.group) if st else None
        return g.name if g else f.group

    def outcome(self):
        """WIN / LOSS / DRAW of the focus team, with its colour."""
        r = self.mine.result
        w = r.winner_id()
        if w is None:
            return "DRAW", WARN
        return ("WIN", GREEN) if w == self.focus_team else ("DEFEAT", DANGER_LITE)

    def glow_color(self):
        if not self.mine:
            return INFO
        return self.outcome()[1]

    def paint_moment(self, p, ms):
        w, h = self.vw, self.vh
        head = _ease(_phase(ms, 80, 420))
        top = h * 0.09
        self.text(p, QRectF(0, top - 10 * (1 - head), w, 26), self.eyebrow, 14, ACCENT, track=3.0,
                  opacity=head)
        self.text(p, QRectF(0, top + 22 - 10 * (1 - head), w, 60), self.title, 44, track=3.0,
                  opacity=head)
        self.sweep(p, top + 88, 2, _phase(ms, 200, 600))
        y = top + 116
        if self.mine:
            y = self._paint_mine(p, ms, y)
        self._paint_others(p, ms, y + 18)

    def _paint_mine(self, p, ms, y):
        w = self.vw
        f, r = self.mine, self.mine.result
        card_h = 250
        card = QRectF(w / 2 - 520, y, 1040, card_h)
        a = _ease(_phase(ms, 250, 450))
        p.save()
        p.setOpacity(p.opacity() * a)
        p.fillRect(card, QColor(BG_CARD))
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRect(card)
        label, col = self.outcome()
        p.fillRect(QRectF(card.x(), card.y(), card.width(), 4), QColor(col))
        p.restore()
        cy = y + 104
        slide = 80 * (1 - _ease(_phase(ms, 300, 520)))
        for tid, cx in ((f.home, card.x() + 120 + -slide), (f.away, card.right() - 120 + slide)):
            dim = r.winner_id() is not None and r.winner_id() != tid
            self.crest(p, tid, cx, cy, 128, opacity=a * (0.55 if dim and self.settled else 1.0))
            name = self.t.team_name(tid).upper()
            self.text(p, QRectF(cx - 150, cy + 72, 300, 30), name, 18,
                      YOU_TINT if tid in self.humans else (FG_TERTIARY if dim else FG_PRIMARY),
                      track=1.0, opacity=a)
        # score, counting up
        sp = _ease(_phase(ms, 520, 760))
        hs, as_ = int(round(r.home.points * sp)), int(round(r.away.points * sp))
        self.text(p, QRectF(card.x(), cy - 50, card.width(), 90), f"{hs}  –  {as_}", 64, track=2.0,
                  opacity=_ease(_phase(ms, 450, 200)))
        detail = []
        tries = (r.home.tries, r.away.tries)
        if any(tries):
            detail.append(f"{tries[0]} – {tries[1]} TRIES")
        if r.decided_by and r.decided_by not in ("forfeit",):
            detail.append(r.score_text().split(" ", 1)[-1].strip("()").upper())
        motm = r.extra.get("motm")
        if motm:
            detail.append(f"PLAYER OF THE MATCH: {self.t.player_name(motm).upper()}")
        da = _ease(_phase(ms, 1200, 300))
        self.text(p, QRectF(card.x(), cy + 34, card.width(), 24), "   ·   ".join(detail), 12,
                  FG_TERTIARY, weight=QFont.DemiBold, track=1.4, opacity=da)
        # the verdict stamp
        stamp = _phase(ms, 1250, 260)
        if stamp > 0:
            s = 1.0 + 0.6 * (1 - _ease_back(stamp))
            p.save()
            p.translate(card.center().x(), card.bottom() - 34)
            p.scale(s, s)
            p.setOpacity(p.opacity() * min(1.0, stamp * 2))
            self.text(p, QRectF(-200, -20, 400, 40), label, 26, col, track=6.0)
            p.restore()
        return card.bottom()

    def _paint_others(self, p, ms, y):
        w = self.vw
        shown = self.others[:self.MAX_OTHERS]
        if not shown and not self.moves:
            return
        # position movement first (one line per managed team in a pool)
        for i, (tid, group, old, new, qualify) in enumerate(self.moves):
            a = _ease(_phase(ms, self._others_start - 300 + i * 120, 360))
            if a <= 0:
                continue
            arrow, col = "", FG_SECONDARY
            if old and new < old:
                arrow, col = "▲", GREEN
            elif old and new > old:
                arrow, col = "▼", DANGER_LITE
            where = f"{group.upper()}:  " if group else ""
            change = f"{ordinal(old).upper()}  →  {ordinal(new).upper()}" if old and old != new \
                else ordinal(new).upper()
            tail = ""
            if qualify:
                tail = "   ·   IN THE QUALIFYING PLACES" if new <= qualify else \
                    f"   ·   TOP {qualify} QUALIFY"
            name = self.t.team_name(tid).upper() if len(self.moves) > 1 else ""
            line = f"{name + '  ' if name else ''}{where}{change}  {arrow}{tail}"
            self.text(p, QRectF(0, y, w, 30), line, 16, col if arrow else FG_SECONDARY, track=1.6,
                      opacity=a)
            y += 32
        if not shown:
            return
        y += 14
        a = _ease(_phase(ms, self._others_start - 100, 300))
        real = all(f.result.source == "real" for f in shown)
        head = ("REAL RESULTS" if real else "OTHER RESULTS") if self.mine else ("REAL RESULTS" if real else "")
        self.text(p, QRectF(0, y, w, 20), head, 11, INFO if real else FG_MUTED, track=2.4, opacity=a)
        y += 28
        cols = 2 if len(shown) > 3 else 1
        row_w, row_h = 500, 40
        total_w = cols * row_w + (cols - 1) * 24
        x0 = (w - total_w) / 2
        for i, f in enumerate(shown):
            col_i, row_i = (i % cols, i // cols)
            ra = _ease(_phase(ms, self._others_start + i * 90, 320))
            if ra <= 0:
                continue
            rect = QRectF(x0 + col_i * (row_w + 24), y + row_i * (row_h + 8) + 12 * (1 - ra), row_w, row_h)
            self._result_row(p, f, rect, ra)
        extra = len(self.others) - len(shown)
        if extra > 0 and self.settled:
            rows = (len(shown) + cols - 1) // cols
            self.text(p, QRectF(0, y + rows * (row_h + 8) + 4, w, 20),
                      f"+ {extra} MORE · SEE FIXTURES", 11, FG_MUTED, track=1.6)

    def _result_row(self, p, f, rect, a):
        p.save()
        p.setOpacity(p.opacity() * a)
        p.fillRect(rect, QColor(BG_CARD))
        p.setPen(QPen(QColor(BORDER), 1))
        p.drawRect(rect)
        if f.home in self.humans or f.away in self.humans:
            p.fillRect(QRectF(rect.x(), rect.y(), 3, rect.height()), QColor(YOU_TINT))
        r = f.result
        win = r.winner_id()
        mid = rect.center().x()
        self.crest(p, f.home, rect.x() + 22, rect.center().y(), 24)
        self.crest(p, f.away, rect.right() - 22, rect.center().y(), 24)
        for tid, box, align in ((f.home, QRectF(rect.x() + 42, rect.y(), mid - rect.x() - 90, rect.height()),
                                 Qt.AlignLeft),
                                (f.away, QRectF(mid + 48, rect.y(), rect.right() - mid - 90, rect.height()),
                                 Qt.AlignRight)):
            dim = win is not None and tid != win
            p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold if tid == win else QFont.DemiBold, 0.5))
            p.setPen(QColor(FG_TERTIARY if dim else FG_PRIMARY))
            p.drawText(box, align | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(self.t.team_name(tid).upper(), Qt.ElideRight,
                                                  int(box.width())))
        p.setFont(tracked_font(FONT_DISPLAY, 15, QFont.Bold, 0.5))
        p.setPen(QColor(INFO if r.source == "real" else FG_PRIMARY))
        p.drawText(QRectF(mid - 44, rect.y(), 88, rect.height()), Qt.AlignCenter,
                   f"{r.home.points} – {r.away.points}")
        p.restore()


# ── a new stage ──────────────────────────────────────────────────────────
class StageCard(MomentOverlay):
    """"POOL STAGE COMPLETE → QUARTER-FINALS", and who you face."""

    DURATION = 1300
    AUTO_CLOSE = 2200

    def __init__(self, ds, t):
        super().__init__(ds, t)
        nxt = next((f for f in sorted(t.fixtures, key=lambda f: f.day) if not f.played), None)
        stage = t.stage(nxt.stage_id) if nxt else None
        self.title = ((nxt.round_name if nxt and nxt.knockout and nxt.round_name else
                       (stage.name if stage else "next stage")) or "next stage").upper()
        self.kicker = "THE KNOCKOUTS BEGIN" if nxt and nxt.knockout and not any(
            f.knockout and f.played for f in t.fixtures) else "NEXT UP"
        humans = set(human_ids(t))
        self.tie = next((f for f in t.fixtures if not f.played and f.stage_id == (nxt.stage_id if nxt else None)
                         and (nxt.round_name == f.round_name)
                         and (f.home in humans or f.away in humans)), None) if nxt else None
        self.humans = humans

    def glow_color(self):
        return AWAY_TINT

    def paint_moment(self, p, ms):
        w, h = self.vw, self.vh
        cy = h * 0.40
        self.text(p, QRectF(0, cy - 90, w, 30), self.kicker, 16, AWAY_TINT, track=4.0,
                  opacity=_ease(_phase(ms, 0, 400)))
        # the title slides in from the right, letter spacing closing up
        tp = _ease(_phase(ms, 120, 620))
        self.text(p, QRectF(140 * (1 - tp), cy - 50, w, 90), self.title, 64,
                  track=4.0 + 10 * (1 - tp), opacity=tp)
        self.sweep(p, cy + 50, 3, _phase(ms, 300, 600), AWAY_TINT)
        if self.tie:
            a = _ease(_phase(ms, 700, 500))
            f = self.tie
            self.text(p, QRectF(0, cy + 80, w, 24), "YOUR TIE", 12, FG_TERTIARY, track=3.0, opacity=a)
            for tid, cx in ((f.home, w / 2 - 170), (f.away, w / 2 + 170)):
                self.crest(p, tid, cx, cy + 170, 96, opacity=a, scale=0.8 + 0.2 * a)
                self.text(p, QRectF(cx - 160, cy + 226, 320, 28),
                          (self.t.team_name(tid) if tid else "TBD").upper(), 16,
                          YOU_TINT if tid in self.humans else FG_PRIMARY, opacity=a)
            self.text(p, QRectF(w / 2 - 60, cy + 150, 120, 40), "VS", 26, FG_TERTIARY, track=3.0, opacity=a)


# ── out ──────────────────────────────────────────────────────────────────
class EliminationCard(MomentOverlay):
    DURATION = 1400

    def __init__(self, ds, t, team_id):
        super().__init__(ds, t)
        self.team_id = team_id
        self.summary = report.campaign_summary(t, team_id)

    def glow_color(self):
        return FG_MUTED

    def paint_moment(self, p, ms):
        w, h = self.vw, self.vh
        cy = h * 0.38
        a = _ease(_phase(ms, 0, 700))
        grey = _phase(ms, 500, 600)
        self.crest(p, self.team_id, w / 2, cy, 170, opacity=a, grey=grey >= 0.5)
        self.text(p, QRectF(0, cy + 104, w, 30), self.t.team_name(self.team_id).upper(), 18,
                  FG_TERTIARY, track=2.0, opacity=a)
        b = _ease(_phase(ms, 500, 600))
        self.text(p, QRectF(0, cy + 140, w, 70), "YOUR CAMPAIGN IS OVER", 44, FG_PRIMARY, track=3.0,
                  opacity=b)
        if self.summary:
            self.text(p, QRectF(0, cy + 214, w, 30), self.summary.upper(), 15, FG_SECONDARY,
                      weight=QFont.DemiBold, track=1.6, opacity=_ease(_phase(ms, 900, 500)))
        self.text(p, QRectF(0, cy + 252, w, 26), "SIMULATE THE REST TO SEE WHO LIFTS THE TROPHY", 12,
                  FG_MUTED, weight=QFont.DemiBold, track=1.8, opacity=_ease(_phase(ms, 1100, 300)))


# ── champions ────────────────────────────────────────────────────────────
class ChampionMoment(MomentOverlay):
    DURATION = 2200
    CONFETTI = 140
    _COLORS = (ACCENT, AWAY_TINT, GREEN, INFO, FG_PRIMARY, YOU_TINT)

    def __init__(self, ds, t):
        super().__init__(ds, t)
        self.champion = t.champion
        humans = set(human_ids(t))
        self.won = self.champion in humans
        final = next((f for f in reversed(t.fixtures) if f.final and f.result), None)
        self.final_line = ""
        if final:
            self.final_line = (f"FINAL:  {t.team_name(final.home)}  {final.result.home.points} – "
                               f"{final.result.away.points}  {t.team_name(final.away)}").upper()
        rng = random.Random(t.seed)
        self.bits = [(rng.random(), rng.uniform(-0.15, 0.15), rng.uniform(0.25, 0.6), rng.uniform(0, 6.28),
                      rng.uniform(2, 7), rng.choice(self._COLORS), rng.uniform(5, 11))
                     for _ in range(self.CONFETTI)]
        self._confetti_timer = QTimer(self)
        self._confetti_timer.setInterval(33)
        self._confetti_timer.timeout.connect(self.update)
        self._age = QElapsedTimer()

    def open(self, host, on_close=None):
        super().open(host, on_close)
        if motion.enabled():
            self._age.start()
            self._confetti_timer.start()

    def _finish(self):
        self._confetti_timer.stop()
        super()._finish()

    def glow_color(self):
        return AWAY_TINT

    def paint_moment(self, p, ms):
        w, h = self.vw, self.vh
        cy = h * 0.36
        # rays behind the crest
        ra = _ease(_phase(ms, 300, 900))
        if ra > 0:
            p.save()
            p.translate(w / 2, cy)
            spin = (self._age.elapsed() / 9000.0) if self._age.isValid() else 0
            p.rotate(spin * 360)
            col = QColor(AWAY_TINT)
            col.setAlpha(int(28 * ra))
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            for i in range(12):
                p.rotate(30)
                p.drawPolygon(QPointF(0, 0), QPointF(-40, -h), QPointF(40, -h))
            p.restore()
        cp = _phase(ms, 150, 700)
        self.crest(p, self.champion, w / 2, cy, 220, opacity=min(1.0, cp * 2), scale=0.4 + 0.6 * _ease_back(cp))
        k = _ease(_phase(ms, 700, 500))
        kicker = "★  YOU ARE CHAMPIONS  ★" if self.won else "CHAMPIONS"
        self.text(p, QRectF(0, cy + 130, w, 34), kicker, 18, AWAY_TINT, track=5.0, opacity=k)
        tp = _ease(_phase(ms, 850, 600))
        self.text(p, QRectF(0, cy + 164 + 16 * (1 - tp), w, 80), self.t.team_name(self.champion).upper(), 60,
                  track=3.0, opacity=tp)
        self.sweep(p, cy + 252, 3, _phase(ms, 1000, 700), AWAY_TINT)
        sub = _ease(_phase(ms, 1300, 500))
        self.text(p, QRectF(0, cy + 266, w, 28), self.t.name.upper(), 15, FG_SECONDARY, track=2.4, opacity=sub)
        if self.final_line:
            self.text(p, QRectF(0, cy + 298, w, 24), self.final_line, 12, FG_TERTIARY,
                      weight=QFont.DemiBold, track=1.6, opacity=sub)
        self._paint_confetti(p, w, h)

    def _paint_confetti(self, p, w, h):
        if not self._age.isValid():
            return
        t = self._age.elapsed() / 1000.0
        if t < 0.5:
            return
        t -= 0.5
        p.save()
        p.setPen(Qt.NoPen)
        for x0, drift, speed, phase, spin, color, size in self.bits:
            y = ((t * speed + phase / 6.28) % 1.3) - 0.15
            x = (x0 + drift * math.sin(t * 1.3 + phase)) % 1.0
            p.save()
            p.translate(x * w, y * h)
            p.rotate(math.degrees(t * spin + phase))
            c = QColor(color)
            c.setAlpha(int(220 * min(1.0, t * 1.5)))
            p.setBrush(c)
            p.drawRect(QRectF(-size / 2, -size / 4, size, size / 2))
            p.restore()
        p.restore()
