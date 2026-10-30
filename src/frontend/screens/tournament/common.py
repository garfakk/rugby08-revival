"""
screens/tournament/common.py — the visual kit the tournament screens share.

Broadcast-style pieces, all custom-painted so they match the rest of the
redesign: team crests (with a painted shield when a team has none),
competition emblems, W/D/L form pills, score cards, news items, rating
comparison bars, and DataTable — the read-only grid every list is built
from, with crest icons, form pills, section rows and a qualification rule.
"""
import os
import zlib

from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (QBrush, QColor, QFont, QIcon, QLinearGradient, QPainter, QPainterPath,
                         QPen, QPixmap)
from PyQt5.QtWidgets import (QAbstractItemView, QFrame, QHBoxLayout, QHeaderView,
                             QSizePolicy, QStyle, QStyledItemDelegate, QTableWidget,
                             QTableWidgetItem, QVBoxLayout, QWidget)

from app import variants as V
from app.game_data import frontend_logo
from app.input import KEYMAP, Action
from ui.broadcast import draw_frame, eyebrow_label, tracked_font
from ui.theme import (ACCENT, ACCENT_DIM, AWAY_TINT, BG_BASE, BG_CARD, BG_HIGHLIGHT, BG_PANEL,
                      BG_RAISED, BORDER, DANGER_LITE, FG_MUTED, FG_PRIMARY, FG_SECONDARY,
                      FG_TERTIARY, FONT_BODY, FONT_DISPLAY, GREEN, HOME_TINT, INFO, T_LABEL, WARN)

# ── colours with a meaning across the mode ───────────────────────────────
FORM_COLORS = {"W": GREEN, "D": WARN, "L": DANGER_LITE}
NEWS_COLORS = {"knock": FG_TERTIARY, "injury": WARN, "suspension": DANGER_LITE, "return": GREEN, "upset": INFO,
               "champion": ACCENT, "award": AWAY_TINT, "stage": INFO, "result": FG_SECONDARY}
NEWS_TAGS = {"knock": "KNOCK", "injury": "INJURY", "suspension": "BAN", "return": "RETURN", "upset": "UPSET",
             "champion": "CHAMPIONS", "award": "AWARD", "stage": "STAGE", "result": "RESULT"}
YOU_TINT = HOME_TINT          # the user's team, everywhere in the mode

# A stable fallback colour per team (when it has no crest file).
_TEAM_PALETTE = ["#c0392b", "#2471a3", "#1e8449", "#b7950b", "#7d3c98", "#ca6f1e",
                 "#117a65", "#a93226", "#2e4053", "#839192", "#5b2c6f", "#1a5276"]


def _initials(name, n=2):
    words = [w for w in (name or "?").replace("-", " ").split() if w]
    if len(words) >= 2:
        return "".join(w[0] for w in words[:n]).upper()
    return (words[0][:n] if words else "?").upper()


def team_color(team_id) -> str:
    return _TEAM_PALETTE[zlib.crc32(str(team_id).encode()) % len(_TEAM_PALETTE)]


# ── crests ───────────────────────────────────────────────────────────────
_CREST_CACHE = {}


def _shield_path(r: QRectF) -> QPainterPath:
    path = QPainterPath()
    x, y, w, h = r.x(), r.y(), r.width(), r.height()
    path.moveTo(x + w * 0.5, y)
    path.lineTo(x + w, y + h * 0.12)
    path.lineTo(x + w, y + h * 0.5)
    path.cubicTo(x + w, y + h * 0.78, x + w * 0.72, y + h * 0.92, x + w * 0.5, y + h)
    path.cubicTo(x + w * 0.28, y + h * 0.92, x, y + h * 0.78, x, y + h * 0.5)
    path.lineTo(x, y + h * 0.12)
    path.closeSubpath()
    return path


def painted_crest(name, team_id, size) -> QPixmap:
    """A shield in the team's stable colour with its initials — for a team
    whose data carries no crest."""
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(size * 0.1, size * 0.04, size * 0.8, size * 0.92)
    base = QColor(team_color(team_id))
    grad = QLinearGradient(r.topLeft(), r.bottomRight())
    grad.setColorAt(0, base.lighter(135))
    grad.setColorAt(1, base.darker(150))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor(255, 255, 255, 200), max(1.0, size / 28)))
    p.drawPath(_shield_path(r))
    p.setPen(QColor(255, 255, 255, 235))
    p.setFont(tracked_font(FONT_DISPLAY, max(6, int(size * 0.26)), QFont.Bold, 0.5))
    p.drawText(r.adjusted(0, -size * 0.04, 0, 0), Qt.AlignCenter, _initials(name))
    p.end()
    return pix


def team_crest(ds, team_id, season=None, size=40, name=None, variant="") -> QPixmap:
    """The team's crest scaled into a size x size square (cached), or a
    painted shield when it has none. `season` picks the season's logo; any
    season of the team will do otherwise. `variant`: a competition variant's
    own logo, when it has one (app/variants.py)."""
    key = (team_id, season, variant, size)
    if key in _CREST_CACHE:
        return _CREST_CACHE[key]
    seasons = (ds.teams.get(team_id) or {}) if ds is not None and team_id else {}
    info = seasons.get(season) or (next(iter(seasons.values())) if seasons else {})
    if variant and season in seasons:
        info = V.resolve(info, variant)
    rel = frontend_logo(info)
    path = os.path.join(ds.teams_folder_path.get(team_id, ""), rel) if rel and ds else ""
    pix = QPixmap(path) if path and os.path.exists(path) else QPixmap()
    if pix.isNull():
        out = painted_crest(name or info.get("name") or team_id or "?", team_id, size)
    else:
        scaled = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        out = QPixmap(size, size)
        out.fill(Qt.transparent)
        p = QPainter(out)
        p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2, scaled)
        p.end()
    _CREST_CACHE[key] = out
    return out


def tournament_crest(ds, t, team_id, size=40) -> QPixmap:
    """team_crest for a team taking part in tournament `t` (its season)."""
    if not team_id:
        return placeholder_crest(size)
    entry = t.teams.get(team_id)
    return team_crest(ds, team_id, entry.season if entry else None, size,
                      name=entry.name if entry else None,
                      variant=getattr(entry, "variant", "") if entry else "")


def placeholder_crest(size) -> QPixmap:
    """A dashed outline: a knockout slot whose team isn't known yet."""
    key = ("?", None, size)
    if key not in _CREST_CACHE:
        pix = QPixmap(size, size)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QPen(QColor(FG_MUTED), max(1.0, size / 30), Qt.DashLine))
        p.drawPath(_shield_path(QRectF(size * 0.14, size * 0.08, size * 0.72, size * 0.84)))
        p.end()
        _CREST_CACHE[key] = pix
    return _CREST_CACHE[key]


def clear_crest_cache():
    _CREST_CACHE.clear()


def competition_emblem(ds, template, size=72) -> QPixmap:
    """The competition's menu logo ("logo_frontend", else the in-game
    "logo") when its data folder has one (an edition's own: a World Cup 2015
    never shows the 2023 logo), otherwise a painted roundel with its
    initials and year."""
    branding = template.get("branding")
    folder = ds.tournaments_folder_path.get(branding, "") if ds is not None and branding else ""
    seasons = ds.tournaments.get(branding, {}) if folder else {}
    edition = str(template.get("branding_season") or "")
    entries = [seasons.get(edition) or {}] if edition else [s for _, s in sorted(seasons.items(), reverse=True)]
    candidates = [os.path.join(folder, e[k]) for e in entries for k in ("logo_frontend", "logo") if e.get(k)]
    path = next((c for c in candidates if os.path.isfile(c)), "")
    if path:
        pix = QPixmap(path)
        if not pix.isNull():
            return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    pix = QPixmap(size, size)
    pix.fill(Qt.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.Antialiasing)
    r = QRectF(2, 2, size - 4, size - 4)
    grad = QLinearGradient(r.topLeft(), r.bottomRight())
    grad.setColorAt(0, QColor("#2a0c0f"))
    grad.setColorAt(1, QColor("#0d1d0a"))
    p.setBrush(QBrush(grad))
    p.setPen(QPen(QColor("#d4a53a"), max(1.5, size / 30)))
    p.drawEllipse(r)
    p.setPen(QPen(QColor(212, 165, 58, 120), 1))
    p.drawEllipse(r.adjusted(size * 0.08, size * 0.08, -size * 0.08, -size * 0.08))
    # A ball across the roundel, behind the initials.
    p.save()
    p.translate(r.center())
    p.rotate(-30)
    p.setPen(QPen(QColor(224, 32, 43, 120), max(1.0, size / 40)))
    p.setBrush(QColor(224, 32, 43, 40))
    p.drawEllipse(QRectF(-size * 0.32, -size * 0.19, size * 0.64, size * 0.38))
    p.restore()
    p.setPen(QColor("#f3e2b3"))
    p.setFont(tracked_font(FONT_DISPLAY, max(7, int(size * 0.24)), QFont.Bold, 1.0))
    name = template.get("name", "")
    year = next((w for w in name.split() if w.isdigit() and len(w) == 4), "")
    words = " ".join(w for w in name.split() if w != year)
    if year:
        p.drawText(r.adjusted(0, 0, 0, -size * 0.16), Qt.AlignCenter, _initials(words)[:3])
        p.setFont(tracked_font(FONT_DISPLAY, max(6, int(size * 0.13)), QFont.Bold, 1.0))
        p.drawText(r.adjusted(0, size * 0.42, 0, 0), Qt.AlignCenter, year)
    else:
        p.drawText(r, Qt.AlignCenter, _initials(name)[:3])
    p.end()
    return pix


class PixmapLabel(QWidget):
    """A fixed-size painted pixmap (crest, emblem) — no QLabel stylesheet
    surprises, transparent everywhere else."""

    def __init__(self, size, pixmap=None, parent=None):
        super().__init__(parent)
        self.setFixedSize(size, size)
        self._pix = pixmap

    def set_pixmap(self, pixmap):
        self._pix = pixmap
        self.update()

    def paintEvent(self, event):
        if self._pix is None or self._pix.isNull():
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        pw, ph = self._pix.width(), self._pix.height()
        s = min(self.width() / max(pw, 1), self.height() / max(ph, 1))
        w, h = pw * s, ph * s
        p.drawPixmap(QRectF((self.width() - w) / 2, (self.height() - h) / 2, w, h), self._pix,
                     QRectF(0, 0, pw, ph))


# ── small painted pieces ─────────────────────────────────────────────────
def paint_form(p, rect: QRectF, form, cell=16, gap=3, align_right=False):
    """Up to five W/D/L pills, oldest first, vertically centred in rect."""
    form = list(form)[-5:]
    total = len(form) * cell + max(0, len(form) - 1) * gap
    x = rect.right() - total if align_right else rect.x()
    y = rect.center().y() - cell / 2
    p.save()
    p.setRenderHint(QPainter.Antialiasing)
    p.setFont(tracked_font(FONT_DISPLAY, max(6, int(cell * 0.5)), QFont.Bold, 0))
    for ch in form:
        col = QColor(FORM_COLORS.get(ch, FG_MUTED))
        r = QRectF(x, y, cell, cell)
        p.setPen(Qt.NoPen)
        p.setBrush(col)
        p.drawRoundedRect(r, 3, 3)
        p.setPen(QColor(BG_BASE))
        p.drawText(r, Qt.AlignCenter, ch)
        x += cell + gap
    p.restore()


class FormStrip(QWidget):
    def __init__(self, form=(), cell=18, align_right=False, parent=None):
        super().__init__(parent)
        self._form, self._cell, self._right = list(form), cell, align_right
        self.setFixedHeight(cell + 2)
        self.setMinimumWidth(5 * (cell + 3))

    def set_form(self, form):
        self._form = list(form)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        if not self._form:
            p.setPen(QColor(FG_MUTED))
            p.setFont(tracked_font(FONT_DISPLAY, 9, QFont.DemiBold, 1.0))
            p.drawText(QRectF(self.rect()), (Qt.AlignRight if self._right else Qt.AlignLeft)
                       | Qt.AlignVCenter, "NO FORM YET")
            return
        paint_form(p, QRectF(self.rect()), self._form, self._cell, align_right=self._right)


class ProgressStrip(QWidget):
    """A thin progress bar with a caption: matchday n of N."""

    def __init__(self, parent=None, height=6, color=ACCENT):
        super().__init__(parent)
        self.setFixedHeight(height)
        self._v, self._color = 0.0, color

    def set_value(self, v, color=None):
        self._v = max(0.0, min(1.0, v))
        if color:
            self._color = color
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(BG_RAISED))
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        if self._v > 0:
            p.setBrush(QColor(self._color))
            p.drawRoundedRect(QRectF(r.x(), r.y(), max(r.height(), r.width() * self._v), r.height()),
                              r.height() / 2, r.height() / 2)


class Tag(QWidget):
    """A small filled or outlined label: NEWS kinds, YOU, CHAMPIONS..."""

    def __init__(self, text, color, filled=True, parent=None):
        super().__init__(parent)
        self._text, self._color, self._filled = text.upper(), color, filled
        self._font = tracked_font(FONT_DISPLAY, 9, QFont.Bold, 1.2)
        from PyQt5.QtGui import QFontMetrics
        self.setFixedSize(QFontMetrics(self._font).horizontalAdvance(self._text) + 16, 18)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        col = QColor(self._color)
        if self._filled:
            p.setPen(Qt.NoPen)
            p.setBrush(col)
            p.drawRoundedRect(r, 2, 2)
            p.setPen(QColor(BG_BASE))
        else:
            p.setPen(QPen(col, 1))
            p.setBrush(Qt.NoBrush)
            p.drawRoundedRect(r, 2, 2)
        p.setFont(self._font)
        p.drawText(r, Qt.AlignCenter, self._text)


# ── clickable cards ──────────────────────────────────────────────────────
class ActivatableCard(QWidget):
    """Focusable, clickable panel: hover/focus lift it with an accent frame
    and stripe. Enter / click emits `activated`."""

    activated = pyqtSignal()
    focused = pyqtSignal()

    def __init__(self, parent=None, stripe=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setAttribute(Qt.WA_Hover)
        self.setCursor(Qt.PointingHandCursor)
        self._stripe = stripe
        self.selected = False

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self.activated.emit()

    def keyPressEvent(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space):
            self.activated.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def focusInEvent(self, e):
        self.update()
        self.focused.emit()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)

    def paint_background(self, p):
        hot = self.hasFocus() or self.underMouse()
        r = QRectF(self.rect())
        p.fillRect(r, QColor(BG_HIGHLIGHT if hot or self.selected else BG_CARD))
        stripe = ACCENT if (self.hasFocus() or self.selected) else self._stripe
        if stripe:
            p.fillRect(QRectF(0, 0, 4, r.height()), QColor(stripe))
        draw_frame(p, self.rect(), ACCENT if self.hasFocus() else (BORDER if not self.selected else ACCENT_DIM))

    def paintEvent(self, event):
        p = QPainter(self)
        self.paint_background(p)


class ScoreCard(ActivatableCard):
    """One result (or upcoming tie): crest NAME [score] NAME crest, the
    winner bright and the loser dimmed, a caption above."""

    def __init__(self, ds, t, fixture, highlight=(), caption=None, parent=None):
        super().__init__(parent, stripe=YOU_TINT if (fixture.home in highlight
                                                      or fixture.away in highlight) else None)
        self.ds, self.t, self.f = ds, t, fixture
        self.caption = fixture.label if caption is None else caption
        self.setFixedHeight(62)
        self.setMinimumWidth(300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self._crests = (tournament_crest(ds, t, fixture.home, 28),
                        tournament_crest(ds, t, fixture.away, 28))

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        self.paint_background(p)
        f, t, w = self.f, self.t, self.width()
        p.setFont(tracked_font(FONT_DISPLAY, 8, QFont.DemiBold, 1.4))
        p.setPen(QColor(FG_TERTIARY))
        p.drawText(QRectF(14, 4, w - 28, 14), Qt.AlignLeft | Qt.AlignVCenter, (self.caption or "").upper())
        if f.result and f.result.source in ("game", "real"):
            # PLAYED: in the game; REAL: reality mode's real result
            p.setPen(QColor(GREEN if f.result.source == "game" else INFO))
            p.drawText(QRectF(14, 4, w - 28, 14), Qt.AlignRight | Qt.AlignVCenter,
                       "PLAYED" if f.result.source == "game" else "REAL")
        winner = f.result.winner_id() if f.result else None
        y, h = 20, 36
        score_w = 74
        mid = w / 2
        p.drawPixmap(14, int(y + 4), self._crests[0])
        p.drawPixmap(int(w - 14 - 28), int(y + 4), self._crests[1])
        for tid, ref, rect, align in (
                (f.home, f.home_ref, QRectF(50, y, mid - score_w / 2 - 58, h), Qt.AlignLeft),
                (f.away, f.away_ref, QRectF(mid + score_w / 2 + 8, y, mid - score_w / 2 - 58, h), Qt.AlignRight)):
            dim = winner is not None and tid != winner
            p.setFont(tracked_font(FONT_DISPLAY, 13, QFont.Bold if tid == winner else QFont.DemiBold, 0.4))
            p.setPen(QColor(FG_MUTED if not tid else (FG_TERTIARY if dim else FG_PRIMARY)))
            name = t.team_name(tid) if tid else ref_label(t, ref)
            p.drawText(rect, align | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(name.upper(), Qt.ElideRight, int(rect.width())))
        box = QRectF(mid - score_w / 2, y + 5, score_w, h - 10)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(BG_BASE if f.result else BG_RAISED))
        p.drawRoundedRect(box, 3, 3)
        p.setFont(tracked_font(FONT_DISPLAY, 15, QFont.Bold, 0.5))
        if f.result:
            r = f.result
            p.setPen(QColor(FG_PRIMARY))
            p.drawText(box, Qt.AlignCenter, f"{r.home.points} – {r.away.points}")
        else:
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(box, Qt.AlignCenter, "V")


def ref_label(t, ref) -> str:
    """A readable name for a knockout slot not yet filled: "Winner QF 1",
    "Pool A winner", "Pool B runner-up"..."""
    if not ref:
        return "TBD"
    if ref.startswith(("W:", "L:")):
        f = t.fixture(ref[2:])
        what = "Winner" if ref[0] == "W" else "Loser"
        return f"{what} {f.label}" if f else what
    if ":" not in ref:
        return t.team_name(ref)
    sid, rest = ref.split(":", 1)
    if rest.startswith("P") and "#" in rest:
        pos, n = rest[1:].split("#")
        place = {"1": "group winner", "2": "runner-up", "3": "third place"}.get(pos, f"#{pos}")
        return f"Best {place} {n}" if n != "1" else f"Best {place}"
    gid = rest.rstrip("0123456789")
    pos = rest[len(gid):]
    stage = t.stage(sid)
    group = stage.group(gid) if stage else None
    if stage and group and len(stage.groups) == 1:
        # one league: "1st in the table", "6th in the table"
        n = int(pos) if pos.isdigit() else 0
        return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')} in the table"
    name = group.name if group else f"Pool {gid}"
    place = {"1": "winner", "2": "runner-up", "3": "third"}.get(pos, f"#{pos}")
    return f"{name} {place}"


class NewsItem(QWidget):
    """One headline: a coloured kind tag, the text, the round (`day_label`,
    "R3" / "QF": report.round_short)."""

    def __init__(self, item, compact=False, show_day=True, day_label=None, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_StyledBackground, False)
        kind = item.get("kind", "")
        color = NEWS_COLORS.get(kind, FG_TERTIARY)
        h = QHBoxLayout(self)
        h.setContentsMargins(10, 6 if compact else 8, 10, 6 if compact else 8)
        h.setSpacing(10)
        self._color = color
        tag = Tag(NEWS_TAGS.get(kind, kind or "news"), color, filled=kind in ("champion", "award"))
        h.addWidget(tag, alignment=Qt.AlignTop)
        from ui.editor_kit import Note
        text = Note(item.get("text", ""), color=FG_PRIMARY if not compact else FG_SECONDARY,
                    size=T_LABEL - (1 if compact else 0))
        h.addWidget(text, stretch=1)
        if show_day:
            day = eyebrow_label(day_label or f"R{item.get('day', 0) + 1}", color=FG_MUTED, size=9)
            h.addWidget(day, alignment=Qt.AlignTop)

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(QRectF(0, self.height() - 1, self.width(), 1), QColor(BORDER).darker(160))


# ── headings, layout helpers ─────────────────────────────────────────────
class SectionTitle(QWidget):
    """EYEBROW TITLE ───────────── right-text"""

    def __init__(self, title, color=ACCENT, right="", parent=None):
        super().__init__(parent)
        self.setFixedHeight(24)
        self._title, self._color, self._right = title.upper(), color, right.upper()

    def set_right(self, text):
        self._right = (text or "").upper()
        self.update()

    def set_title(self, text):
        self._title = (text or "").upper()
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, 1.6))
        fm = p.fontMetrics()
        tw = fm.horizontalAdvance(self._title)
        p.setPen(QColor(self._color))
        p.drawText(QRectF(0, 0, tw + 4, self.height()), Qt.AlignLeft | Qt.AlignVCenter, self._title)
        rw = 0
        if self._right:
            p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.DemiBold, 1.2))
            rw = p.fontMetrics().horizontalAdvance(self._right) + 12
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(QRectF(self.width() - rw, 0, rw, self.height()), Qt.AlignRight | Qt.AlignVCenter,
                       self._right)
        y = self.height() / 2
        p.fillRect(QRectF(tw + 14, y, max(0, self.width() - tw - 26 - rw), 1), QColor(BORDER))


def section(title, color=ACCENT, right=""):
    """Section title + a vertical layout under it, in one widget."""
    w = QWidget()
    w.setObjectName("tSection")
    w.setStyleSheet("QWidget#tSection { background: transparent; }")
    v = QVBoxLayout(w)
    v.setContentsMargins(0, 0, 0, 0)
    v.setSpacing(8)
    title_w = SectionTitle(title, color, right)
    v.addWidget(title_w)
    w.title = title_w
    return w, v


def transparent(widget, name):
    widget.setObjectName(name)
    widget.setStyleSheet(f"QWidget#{name} {{ background: transparent; }}")
    return widget


def clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            # Detach now: deleteLater alone leaves the old widget painted
            # under the new one until the event loop gets round to it.
            w.hide()
            w.setParent(None)
            w.deleteLater()
        elif item.layout() is not None:
            clear_layout(item.layout())


def hline():
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background: {BORDER}; border: none;")
    return f


# ── DataTable ────────────────────────────────────────────────────────────
_FORM_ROLE = Qt.UserRole + 1        # str: W/D/L pills to paint in the cell
_SECTION_ROLE = Qt.UserRole + 2     # bool: a full-width section header row
_RULE_ROLE = Qt.UserRole + 3        # bool: draw the qualification rule under the row
_TINT_ROLE = Qt.UserRole + 4        # str: row background tint (the user's team)


class Section:
    """A header row inside a DataTable (e.g. MATCHDAY 3), spans all columns
    and can't be selected."""

    def __init__(self, text, right="", gap=False):
        self.text, self.right = text, right
        self.gap = gap          # room above the band: it starts a new block


class _TableDelegate(QStyledItemDelegate):
    SECTION_GAP = 18

    def paint(self, p, option, index):
        table = self.parent()
        r = QRectF(option.rect)
        if index.data(_SECTION_ROLE):
            if index.column() == 0:
                full = QRectF(r.x(), r.y(), table.viewport().width(), r.height())
                if index.data(Qt.UserRole + 6):
                    full.setTop(full.top() + self.SECTION_GAP)
                p.fillRect(full, QColor(BG_RAISED))
                p.fillRect(QRectF(full.x(), full.y(), 3, full.height()), QColor(ACCENT))
                p.setFont(tracked_font(FONT_DISPLAY, 10, QFont.Bold, 1.6))
                p.setPen(QColor(FG_SECONDARY))
                p.drawText(full.adjusted(14, 0, -14, 0), Qt.AlignLeft | Qt.AlignVCenter,
                           str(index.data(Qt.DisplayRole) or "").upper())
                right = index.data(Qt.UserRole + 5)
                if right:
                    p.setPen(QColor(ACCENT))
                    p.drawText(full.adjusted(14, 0, -14, 0), Qt.AlignRight | Qt.AlignVCenter,
                               str(right).upper())
            return
        selected = bool(option.state & QStyle.State_Selected)
        tint = index.data(_TINT_ROLE)
        if selected:
            p.fillRect(r, QColor("#173d16"))
        elif tint:
            c = QColor(tint)
            c.setAlpha(26)
            p.fillRect(r, c)
        if selected and index.column() == 0:
            p.fillRect(QRectF(r.x(), r.y(), 3, r.height()), QColor(ACCENT))
        form = index.data(_FORM_ROLE)
        icon = index.data(Qt.DecorationRole)
        if form is not None:
            paint_form(p, r.adjusted(8, 0, -8, 0), form, cell=15,
                       align_right=bool(index.data(Qt.TextAlignmentRole) and
                                        int(index.data(Qt.TextAlignmentRole)) & Qt.AlignRight))
        elif icon is not None:
            # Crest + text drawn by hand so a right-aligned cell keeps its
            # crest next to the name (on the inside edge), not stranded left.
            right = bool(index.data(Qt.TextAlignmentRole) and
                         int(index.data(Qt.TextAlignmentRole)) & Qt.AlignRight)
            size = table.iconSize()
            pix = icon.pixmap(size) if hasattr(icon, "pixmap") else icon
            ix = r.right() - 8 - size.width() if right else r.x() + 8
            p.drawPixmap(int(ix), int(r.center().y() - size.height() / 2), pix)
            font = index.data(Qt.FontRole) or table.font()
            p.setFont(font)
            fg = index.data(Qt.ForegroundRole)
            p.setPen(fg.color() if fg is not None else QColor(FG_PRIMARY))
            tr = (r.adjusted(8, 0, -16 - size.width(), 0) if right
                  else r.adjusted(16 + size.width(), 0, -8, 0))
            text = p.fontMetrics().elidedText(str(index.data(Qt.DisplayRole) or ""), Qt.ElideRight,
                                              int(tr.width()))
            p.drawText(tr, (Qt.AlignRight if right else Qt.AlignLeft) | Qt.AlignVCenter, text)
        else:
            opt = option
            opt.state &= ~QStyle.State_Selected
            opt.state &= ~QStyle.State_HasFocus
            super().paint(p, opt, index)
        if index.data(_RULE_ROLE):
            p.setPen(QPen(QColor(GREEN), 1, Qt.DashLine))
            p.drawLine(QPointF(r.left(), r.bottom()), QPointF(r.right(), r.bottom()))


class DataTable(QTableWidget):
    """Read-only grid. set_rows([[cell, ...]], keys, colors={row: color},
    bold={row}, tint={row: color}, rules={row}). A cell is text, a
    (text, color) tuple, or a dict {text, color, icon, form, bold, align}.
    A row may be a Section("MATCHDAY 3") header. Enter / double-click
    emits activated_row; keys[i] is what callers usually want."""
    activated_row = pyqtSignal(int)

    ROW_H = 34

    def __init__(self, columns, stretch_col=1, parent=None, widths=None, header_align=None):
        super().__init__(0, len(columns), parent)
        self.keys = []
        self.setHorizontalHeaderLabels([c.upper() for c in columns])
        # {col: Qt.AlignHCenter / Qt.AlignRight}: line a header up with
        # its column's cells (the default is left)
        for c, align in (header_align or {}).items():
            self.horizontalHeaderItem(c).setTextAlignment(align | Qt.AlignVCenter)
        self.verticalHeader().hide()
        self.verticalHeader().setDefaultSectionSize(self.ROW_H)
        self.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setShowGrid(False)
        self.setWordWrap(False)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setIconSize(QSize(22, 22))
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setItemDelegate(_TableDelegate(self))
        header = self.horizontalHeader()
        header.setHighlightSections(False)
        header.setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        header.setMinimumSectionSize(28)
        widths = widths or {}
        for i in range(len(columns)):
            if i == stretch_col:
                header.setSectionResizeMode(i, QHeaderView.Stretch)
            elif i in widths:
                header.setSectionResizeMode(i, QHeaderView.Fixed)
                self.setColumnWidth(i, widths[i])
            else:
                header.setSectionResizeMode(i, QHeaderView.ResizeToContents)
        self.setStyleSheet(
            f"QTableWidget {{ background: {BG_PANEL}; color: {FG_PRIMARY}; border: 1px solid {BORDER};"
            f" font-family: '{FONT_BODY}'; font-size: {T_LABEL}pt; outline: 0; }}"
            f"QTableWidget:focus {{ border: 1px solid {ACCENT}; }}"
            f"QTableWidget::item {{ padding: 0px 8px; border-bottom: 1px solid #0f240c; }}"
            f"QHeaderView::section {{ background: {BG_BASE}; color: {FG_TERTIARY};"
            f" font-family: '{FONT_DISPLAY}'; font-size: 9pt; font-weight: 700; letter-spacing: 1px;"
            f" border: none; border-bottom: 1px solid {BORDER}; padding: 6px 8px; }}")
        self.doubleClicked.connect(lambda idx: self._activate(idx.row()))

    def _activate(self, row):
        if 0 <= row < len(self.keys) and self.keys[row] is not None:
            self.activated_row.emit(row)

    def set_rows(self, rows, keys=None, colors=None, bold=(), align_right_from=None,
                 tint=None, rules=(), center=()):
        keep = self.current_key()
        self.clearSpans()
        self.keys = list(keys) if keys is not None else [
            None if isinstance(r, Section) else i for i, r in enumerate(rows)]
        colors, tint = colors or {}, tint or {}
        self.setRowCount(len(rows))
        for r, row in enumerate(rows):
            if isinstance(row, Section):
                item = QTableWidgetItem(row.text)
                item.setData(_SECTION_ROLE, True)
                item.setData(Qt.UserRole + 5, row.right)
                item.setData(Qt.UserRole + 6, row.gap)
                item.setFlags(Qt.ItemIsEnabled)
                self.setItem(r, 0, item)
                for c in range(1, self.columnCount()):
                    blank = QTableWidgetItem("")
                    blank.setFlags(Qt.ItemIsEnabled)
                    blank.setData(_SECTION_ROLE, True)
                    self.setItem(r, c, blank)
                self.setSpan(r, 0, 1, self.columnCount())
                self.setRowHeight(r, 30 + (_TableDelegate.SECTION_GAP if row.gap else 0))
                continue
            self.setRowHeight(r, self.ROW_H)
            for c, cell in enumerate(row):
                spec = cell if isinstance(cell, dict) else (
                    {"text": cell[0], "color": cell[1]} if isinstance(cell, tuple) else {"text": cell})
                text = spec.get("text")
                item = QTableWidgetItem("" if text is None else str(text))
                tc = spec.get("color") or colors.get(r)
                if tc:
                    item.setForeground(QColor(tc))
                if spec.get("icon") is not None:
                    item.setIcon(QIcon(spec["icon"]))
                if spec.get("form") is not None:
                    item.setData(_FORM_ROLE, spec["form"])
                if r in bold or spec.get("bold"):
                    f = item.font()
                    f.setBold(True)
                    item.setFont(f)
                align = spec.get("align")
                if align is None and align_right_from is not None and c >= align_right_from:
                    align = Qt.AlignRight
                if align is None and c in center:
                    align = Qt.AlignHCenter
                if align is not None:
                    item.setTextAlignment(align | Qt.AlignVCenter)
                if r in tint:
                    item.setData(_TINT_ROLE, tint[r])
                if r in rules:
                    item.setData(_RULE_ROLE, True)
                self.setItem(r, c, item)
        if keep is not None and keep in self.keys:
            self.selectRow(self.keys.index(keep))

    def current_key(self):
        r = self.currentRow()
        return self.keys[r] if 0 <= r < len(self.keys) else None

    def select_key(self, key):
        if key in self.keys:
            self.selectRow(self.keys.index(key))

    def fit_height(self, max_rows=None):
        """Size to the rows so stacked tables don't each scroll."""
        n = self.rowCount() if max_rows is None else min(self.rowCount(), max_rows)
        h = self.horizontalHeader().sizeHint().height() + sum(self.rowHeight(i) for i in range(n)) + 4
        self.setFixedHeight(max(h, 60))

    def _step_row(self, d):
        r = self.currentRow()
        n = self.rowCount()
        i = r + d
        while 0 <= i < n and self.keys[i] is None:
            i += d
        if 0 <= i < n:
            self.selectRow(i)
            return True
        return False

    def keyPressEvent(self, event):
        action = KEYMAP.get(event.key())
        if action in (Action.TAB_NEXT, Action.TAB_PREV, Action.BACK):
            event.ignore()
        elif event.key() in (Qt.Key_Return, Qt.Key_Enter) and self.currentRow() >= 0:
            self._activate(self.currentRow())
        elif event.key() in (Qt.Key_Up, Qt.Key_Down):
            # Skips section rows; at either end the screen's focus moves on.
            if not self._step_row(-1 if event.key() == Qt.Key_Up else 1):
                event.ignore()
        elif event.key() in (Qt.Key_Left, Qt.Key_Right):
            event.ignore()
        else:
            super().keyPressEvent(event)
