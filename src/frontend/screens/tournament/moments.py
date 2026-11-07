"""
screens/tournament/moments.py — The tournament's big moments, full screen.

After an action plays matches, the dashboard hands what changed to
`moments_after()` and plays the overlays it returns, one after the other:

  MatchdayRecap    full time: your match big (the score counts up), the
                   other results sliding in, your pool position moving
                   (only for a round you played in: a round without your
                   match is shown on the dashboard's Home instead)
  StageCard        a new stage or knockout round begins ("QUARTER-FINALS")
  EliminationCard  your last team is out
  ChampionMoment   the final whistle of the tournament: crest, and rays + confetti
                   when a human team won

Each is painted on a clock (ms since it started), so it can be skipped to
its final frame at any time: the first key or click shows the whole
moment, the next one closes it. With animations off (user_prefs.
animations) every moment opens on its final frame.

Kept cheap for slow machines: the clock advances by at most MAX_STEP_MS a
frame (a stall — the window coming back from the game, a save — slows the
moment down instead of skipping half of it), an overlay whose backdrop
covers the screen is opaque (the dashboard behind is not repainted every
frame), the backdrop is painted once into a pixmap, and Python's garbage
collector waits until the moment has played.

Pure painting: no child widgets, nothing focusable but the overlay itself.
"""
import gc
import math
import random
from dataclasses import dataclass, field

from PyQt5.QtCore import QElapsedTimer, QEvent, QPointF, QRect, QRectF, Qt, QTimer
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
MAX_STEP_MS = 50       # the most one frame moves a moment on (see the docstring)
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
    """(where, 1-based position, qualify count) of the team's pool while the
    pool stage runs, else None; `where` is "Pool A", or "" in a one-league
    stage (the table), and the position is None before its first match."""
    for st in t.stages:
        if st.kind != "round_robin" or st.status == "done":
            continue
        for g in st.groups:
            if team_id in g.teams:
                tab = standings.group_table(t, st, g)
                pos = next((i + 1 for i, r in enumerate(tab) if r.team_id == team_id and r.played), None)
                name = g.name if len(st.groups) > 1 else ""
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


def moments_after(ds, t, before: Before, done, game=None) -> list:
    """The overlays to play for the matches in `done` (in order). `game`:
    (match_data, result) of your match when it was just played in the game,
    for the recap's match statistics."""
    out = []
    played = [f for f in (done or []) if f.played]
    humans = set(human_ids(t))
    mine = [f for f in played if f.home in humans or f.away in humans]
    if mine:
        # one round per recap: the round of your match. A round without
        # it (a bye, the rest after you are out) has no recap: Home lists
        # its results (dashboard "no match for you").
        out.append(MatchdayRecap(ds, t, before, max(f.day for f in mine), game=game))
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
    # No gc.collect() first: a full collection here froze the screen just
    # before the first moment (~70 ms on a fast PC). Collection is held off
    # while a moment moves anyway (_hold_gc) and comes back once it settles.
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
        self._clock = QElapsedTimer()      # time since the last frame
        self._pulse = QElapsedTimer()      # the hint's breathing
        self._close_ms = 0
        self._gc_held = False
        self._backdrop_cache = None        # (key, QPixmap)
        self._timer = QTimer(self)
        self._timer.setInterval(FRAME_MS)
        self._timer.timeout.connect(self._tick)
        self._closing = False
        self._fade = 1.0
        self._on_close = None
        self.vw, self.vh = VIRTUAL_W, VIRTUAL_H       # the canvas paint_moment draws on
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.hint = self.HINT

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
            motion.hold(self)
            self._clock.start()
            self._pulse.start()
            self._hold_gc()
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

    def _hold_gc(self):
        """No garbage collection while the moment moves: a full collection
        is a visible hitch on a slow machine. Given back once settled."""
        if not self._gc_held and gc.isenabled():
            gc.disable()
            self._gc_held = True

    def _release_gc(self):
        if self._gc_held:
            self._gc_held = False
            gc.enable()

    def _step(self):
        """ms to move on this frame: the real time since the last one, but
        never more than MAX_STEP_MS."""
        return min(MAX_STEP_MS, self._clock.restart()) if self._clock.isValid() else MAX_STEP_MS

    def _tick(self):
        step = self._step()
        if self._closing:
            self._close_ms += step
            self._fade = 1.0 - min(1.0, self._close_ms / FADE_OUT_MS)
            if self._fade <= 0:
                self._finish()
                return
        elif not self.settled:
            self._ms = min(self.DURATION, self._ms + step)
            if self.settled:
                self._settled()
        elif self.hint:
            self._sync_opaque()
            self.update(self._hint_rect())     # only the hint breathes now
            return
        self._sync_opaque()
        self.update()

    def _sync_opaque(self):
        """Opaque while the backdrop covers everything: Qt then skips
        repainting the screen behind at every frame."""
        opaque = not self._closing and self.backdrop_alpha() >= 1.0
        if opaque != self.testAttribute(Qt.WA_OpaquePaintEvent):
            self.setAttribute(Qt.WA_OpaquePaintEvent, opaque)

    def _hint_rect(self):
        k = self._scale()
        return QRect(0, int(self.height() - 80 * k), self.width(), int(50 * k) + 2)

    def _scale(self):
        return max(0.1, min(1.0, self.width() / VIRTUAL_W, self.height() / VIRTUAL_H))

    def _settled(self):
        """The final frame is on: the hint keeps breathing at a low rate,
        and a moment that closes by itself starts counting."""
        self._release_gc()
        motion.release(self)
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
        self._sync_opaque()
        if motion.enabled():
            motion.hold(self)
            self._close_ms = 0
            self._clock.restart()
            self._timer.setInterval(FRAME_MS)
            self._timer.start()
        else:
            self._finish()

    def _finish(self):
        self._timer.stop()
        self._release_gc()
        motion.release(self)
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
        p.setOpacity(self._fade)
        self.paint_backdrop(p)          # a plain blit: before the render hints
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        # the moment itself is laid out for 1920 x 1080 and scaled down to
        # fit a smaller window (never up: big crests would just blur)
        scale = self._scale()
        p.scale(scale, scale)
        self.vw, self.vh = self.width() / scale, self.height() / scale
        self.paint_moment(p, self._ms)
        if self.settled and not self._closing and self.hint:
            self.paint_hint(p)

    def backdrop_alpha(self):
        """0..1 of the dark backdrop over the screen behind."""
        return _ease(_phase(self._ms, 0, 260))

    def paint_backdrop(self, p):
        """The dark backdrop and its glow, painted once per size and colour
        (a full-screen radial gradient is the dearest thing in a frame) and
        laid over the screen behind at backdrop_alpha()."""
        a = self.backdrop_alpha()
        if a <= 0:
            return
        dpr = self.devicePixelRatioF()
        key = (self.width(), self.height(), dpr, QColor(self.glow_color()).rgba())
        if self._backdrop_cache is None or self._backdrop_cache[0] != key:
            w, h = self.width(), self.height()
            pix = QPixmap(max(1, int(w * dpr)), max(1, int(h * dpr)))
            pix.setDevicePixelRatio(dpr)
            pix.fill(QColor(4, 10, 4))
            bp = QPainter(pix)
            glow = QRadialGradient(w / 2, h * 0.42, max(w, h) * 0.55)
            c = QColor(self.glow_color())
            c.setAlpha(46)
            glow.setColorAt(0, c)
            glow.setColorAt(1, QColor(0, 0, 0, 0))
            bp.fillRect(QRectF(0, 0, w, h), glow)
            bp.end()
            self._backdrop_cache = (key, pix)
        p.save()
        p.setOpacity(p.opacity() * a)
        p.drawPixmap(0, 0, self._backdrop_cache[1])
        p.restore()

    def glow_color(self):
        return ACCENT

    def paint_hint(self, p):
        p.save()
        pulse = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(self._pulse.elapsed() / 380.0)) \
            if self._pulse.isValid() else 1.0
        p.setOpacity(self._fade * pulse)
        p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold, 2.0))
        p.setPen(QColor(FG_TERTIARY))
        p.drawText(QRectF(0, self.vh - 70, self.vw, 30), Qt.AlignCenter, self.hint)
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
    """Full time of one round (matchday `day`): your match first, then the
    round's other results — every match of that round played so far,
    earlier kick-offs included, and nothing from another round — on a
    backdrop that hides the screen behind from the start.

    `game` = (match_data, result) when your match was just played in the
    game to full time: MATCH STATS (or X) opens your match's report in a
    popup, the same as the Competition tab's REPORT."""

    MAX_OTHERS = 8
    CARD_H = 250
    STATS_HINT = "A  CONTINUE      X  MATCH STATS"

    def __init__(self, ds, t, before, day, game=None):
        super().__init__(ds, t)
        self._scores = {}
        humans = set(human_ids(t))
        played = [f for f in t.fixtures if f.day == day and f.played]
        self.mine = next((f for f in reversed(played) if f.home in humans or f.away in humans), None)
        mine_group = self.mine.group if self.mine else None
        # your pool's matches first, then pool by pool
        self.others = sorted((f for f in played if f is not self.mine),
                             key=lambda f: (f.group != mine_group, f.group or ""))
        self.round = report.round_title(t, day)
        self.humans = humans
        self.focus_team = None
        if self.mine:
            self.focus_team = self.mine.home if self.mine.home in humans else self.mine.away
        self.eyebrow = self.round.upper()
        if self.mine and not self.mine.knockout:
            st = t.stage(self.mine.stage_id)
            if st and len(st.groups) > 1:
                self.eyebrow += f"  ·  {self._group_name(self.mine)}".upper()
        self.title = "FULL TIME"
        n_others = min(len(self.others), self.MAX_OTHERS)
        self._others_start = 1500 if self.mine else 500
        self.DURATION = self._others_start + n_others * 90 + 500
        # the game's report, when the match was played to full time
        self.game = game if self.mine and game and game[1] and game[1].get("finished") is not False else None
        self.stats_popup = None        # the match report popup while open
        self._stats_btn = None
        if self.game:
            self.hint = self.STATS_HINT
            self._build_stats()

    # ── the match report, in a popup over the recap ──
    def _build_stats(self):
        from ui.widgets import StyledButton
        self._stats_btn = StyledButton("MATCH STATS", "neutral")
        self._stats_btn.setParent(self)
        self._stats_btn.setFocusPolicy(Qt.NoFocus)
        self._stats_btn.clicked.connect(self.open_stats)
        self._stats_btn.hide()

    def _settled(self):
        super()._settled()
        self._show_stats()

    def _tick(self):
        super()._tick()
        # MATCH STATS comes in with your match's card done, before the
        # other results slide in under it
        if not self._closing and self._ms >= self._others_start - 150:
            self._show_stats()

    def _show_stats(self):
        if self._stats_btn is not None and not self._stats_btn.isVisible() and not self._closing:
            self._place_stats()
            self._stats_btn.show()

    def open_stats(self):
        """Your match's report, the same popup as the Competition tab's
        REPORT (dashboard.show_report); CLOSE comes back to the recap."""
        if self._stats_btn is None or self._closing or self.stats_popup is not None:
            return
        if not self.settled:
            self.skip()
        from .dashboard import show_report

        def closed(_role):
            self.stats_popup = None
            if not self._closing:
                self.setFocus(Qt.OtherFocusReason)
        self.stats_popup = show_report(self, self.ds, self.t, self.mine, closed)

    def _place_stats(self):
        """The button under your match's card (virtual 1920 x 1080
        coordinates, scaled like the paint)."""
        if self._stats_btn is None:
            return
        k = self._scale()
        vw, vh = self.width() / k, self.height() / k
        card_bottom = vh * 0.09 + 116 + self.CARD_H
        bw, bh = 260, 44
        self._stats_btn.setGeometry(int((vw / 2 - bw / 2) * k), int((card_bottom + 18) * k),
                                    int(bw * k), max(32, int(bh * k)))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._stats_btn is not None and self._stats_btn.isVisible():
            self._place_stats()

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if self.game and action == Action.ALT:
            self.open_stats()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if self.stats_popup is None:
            super().mousePressEvent(event)
        event.accept()

    def close_moment(self):
        if self._stats_btn is not None:
            self._stats_btn.hide()
        super().close_moment()

    def backdrop_alpha(self):
        return 1.0          # nothing of the screen behind, from the first frame

    def _score(self, f):
        """(home points, away points, winner) of a fixture, worked out once:
        the points are sums over every player line, and a frame needs them
        for each result row (a few hundred thousand sums over a recap)."""
        hit = self._scores.get(id(f))
        if hit is None:
            r = f.result
            hit = self._scores[id(f)] = (r.home.points, r.away.points, r.winner_id())
        return hit

    def _group_name(self, f):
        st = self.t.stage(f.stage_id)
        g = st.group(f.group) if st else None
        return g.name if g else f.group

    def outcome(self):
        """WIN / DEFEAT / DRAW of the focus team (FORFEITED when it left the
        match), with its colour."""
        r = self.mine.result
        w = self._score(self.mine)[2]
        if w is None and r.decided_by == "forfeit":
            return "FORFEITED", DANGER_LITE           # double forfeit
        if w is None:
            return "DRAW", WARN
        if w == self.focus_team:
            return "WIN", GREEN
        return ("FORFEITED" if r.decided_by == "forfeit" else "DEFEAT"), DANGER_LITE

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
        if self.game:
            y += 18 + 44        # the MATCH STATS button
        self._paint_others(p, ms, y + 18)

    def _paint_mine(self, p, ms, y):
        w = self.vw
        f, r = self.mine, self.mine.result
        card = QRectF(w / 2 - 520, y, 1040, self.CARD_H)
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
            win = self._score(f)[2]
            dim = win is not None and win != tid
            self.crest(p, tid, cx, cy, 128, opacity=a * (0.55 if dim and self.settled else 1.0))
            name = self.t.team_name(tid).upper()
            self.text(p, QRectF(cx - 150, cy + 72, 300, 30), name, 18,
                      YOU_TINT if tid in self.humans else (FG_TERTIARY if dim else FG_PRIMARY),
                      track=1.0, opacity=a)
        # score, counting up
        sp = _ease(_phase(ms, 520, 760))
        hp, ap, _win = self._score(f)
        hs, as_ = int(round(hp * sp)), int(round(ap * sp))
        self.text(p, QRectF(card.x(), cy - 50, card.width(), 90), f"{hs}  –  {as_}", 64, track=2.0,
                  opacity=_ease(_phase(ms, 450, 200)))
        # a knockout draw: how it was decided
        if r.decided_by and r.decided_by != "forfeit":
            da = _ease(_phase(ms, 1200, 300))
            self.text(p, QRectF(card.x(), cy + 34, card.width(), 24),
                      r.score_text().split(" ", 1)[-1].strip("()").upper(), 12,
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
        if not shown:
            return
        y += 14
        a = _ease(_phase(ms, self._others_start - 100, 300))
        real = all(f.result.source == "real" for f in shown)
        head = f"{self.round.upper()}  ·  " + (("REAL RESULTS" if real else "OTHER RESULTS") if self.mine
                                                 else ("REAL RESULTS" if real else "ALL RESULTS"))
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
        hp, ap, win = self._score(f)
        mid = rect.center().x()
        st = self.t.stage(f.stage_id)
        if st and len(st.groups) > 1 and f.group:
            # which pool, just outside the row
            p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.4))
            p.setPen(QColor(FG_MUTED))
            side = QRectF(rect.x() - 96, rect.y(), 88, rect.height()) if rect.x() < self.vw / 2 - 100 \
                else QRectF(rect.right() + 8, rect.y(), 88, rect.height())
            p.drawText(side, (Qt.AlignRight if side.x() < rect.x() else Qt.AlignLeft) | Qt.AlignVCenter,
                       self._group_name(f).upper())
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
                   f"{hp} – {ap}")
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
        self.text(p, QRectF(0, cy + 252, w, 26), "SIMULATE THE REST TO FIND THE WINNER", 12,
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
        if self.won and motion.enabled():
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
        # rays behind the crest, only when a human team won
        ra = _ease(_phase(ms, 300, 900))
        if self.won and ra > 0:
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
