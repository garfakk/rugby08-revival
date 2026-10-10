"""
screens/tournament/bracket.py — the knockout stage drawn as a bracket.

The tree comes from the fixtures' own refs ("W:<fixture id>" = the winner of
that tie): the final(s) are the roots, earlier ties hang off them. Leaves are
ordered by walking the tree so lines never cross, each tie sits halfway
between the two it is fed by, and elbow connectors join them. A tie fed by
losers ("L:") — a bronze final — sits under the final.

Click or Enter on a played tie emits `report(fixture_id)`; the arrows move
between ties while the bracket has focus (leaving it at its edges).
"""
from PyQt5.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPen
from PyQt5.QtWidgets import QSizePolicy, QWidget

from ui.broadcast import tracked_font
from ui.theme import (ACCENT, AWAY_TINT, BG_BASE, BG_CARD, BG_HIGHLIGHT, BORDER, FG_MUTED,
                      FG_PRIMARY, FG_TERTIARY, FONT_DISPLAY, GREEN)

from .common import YOU_TINT, ref_label, tournament_crest

BOX_W, BOX_H = 230, 60
COL_GAP, ROW_GAP = 64, 22
TOP = 34


class BracketView(QWidget):
    report = pyqtSignal(str)

    def __init__(self, ds, t, humans=(), parent=None):
        super().__init__(parent)
        self.ds, self.t, self.humans = ds, t, set(humans)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.boxes = {}          # fixture id -> QRectF
        self.links = []          # (child id, parent id)
        self.titles = []         # (x, text)
        self.order = []          # fixture ids, reading order (for keyboard)
        self.current = None
        self._hover = None
        self._layout()

    # ── geometry ─────────────────────────────────────────────────────────
    def _layout(self):
        t = self.t
        ko = [f for f in t.fixtures if f.knockout]
        if not ko:
            self.setFixedHeight(0)
            return
        rounds = []
        for f in ko:
            if f.round_id not in [r for r, _ in rounds]:
                rounds.append((f.round_id, f.round_name))
        col = {rid: i for i, (rid, _n) in enumerate(rounds)}
        by_id = {f.id: f for f in ko}

        def feeders(f, kind="W:"):
            return [by_id[r[2:]] for r in (f.home_ref, f.away_ref) if r.startswith(kind) and r[2:] in by_id]

        fed = {c.id for f in ko for c in feeders(f)}
        losers_ties = [f for f in ko if feeders(f, "L:") and not feeders(f)]
        roots = [f for f in ko if f.id not in fed and f not in losers_ties]

        y_of = {}
        slot = [0]

        def place(f):
            kids = feeders(f)
            if not kids:
                y_of[f.id] = slot[0] * (BOX_H + ROW_GAP)
                slot[0] += 1
            else:
                for k in kids:
                    place(k)
                y_of[f.id] = sum(y_of[k.id] for k in kids) / len(kids)
            self.order.append(f.id)
            for k in kids:
                self.links.append((k.id, f.id))

        for r in roots:
            place(r)
        # Ties the tree didn't reach (a format without W: refs): stack them
        # in their round's column.
        stacked = {}
        for f in ko:
            if f.id in y_of or f in losers_ties:
                continue
            c = col[f.round_id]
            y_of[f.id] = stacked.get(c, 0) * (BOX_H + ROW_GAP)
            stacked[c] = stacked.get(c, 0) + 1
            self.order.append(f.id)
        bottom = max(y_of.values(), default=0) + BOX_H
        for f in losers_ties:
            # A bronze final: under the final's column, clear of the tree.
            final = next((r for r in roots if r.final), roots[-1] if roots else None)
            c = col[final.round_id] if final else col[f.round_id]
            y_of[f.id] = bottom + ROW_GAP * 2 + 18
            bottom = y_of[f.id] + BOX_H
            self.order.append(f.id)
            col[f.round_id] = c

        for f in ko:
            c = col[f.round_id]
            self.boxes[f.id] = QRectF(c * (BOX_W + COL_GAP) + 2, TOP + y_of[f.id], BOX_W, BOX_H)
        seen = set()
        for rid, name in rounds:
            c = col[rid]
            if (c, name) in seen:
                continue
            seen.add((c, name))
            ties = [f for f in ko if f.round_id == rid]
            bronze = all(f in losers_ties for f in ties)
            y = min(self.boxes[f.id].y() for f in ties) - 26 if bronze else 4
            self.titles.append((c * (BOX_W + COL_GAP) + 2, y, name))
        width = (max(col.values()) + 1) * (BOX_W + COL_GAP)
        self.setMinimumWidth(int(width))
        self.setFixedHeight(int(TOP + bottom + 10))
        self.order.sort(key=lambda fid: (self.boxes[fid].x(), self.boxes[fid].y()))

    def sizeHint(self):
        return QSize(self.minimumWidth(), self.height())

    # ── painting ─────────────────────────────────────────────────────────
    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setFont(tracked_font(FONT_DISPLAY, 11, QFont.Bold, 1.6))
        for x, y, name in self.titles:
            p.setPen(QColor(ACCENT))
            p.drawText(QRectF(x, y, BOX_W, 20), Qt.AlignLeft | Qt.AlignVCenter, name.upper())
        for child, parent in self.links:
            a, b = self.boxes[child], self.boxes[parent]
            f = self.t.fixture(child)
            won = f and f.result
            p.setPen(QPen(QColor(GREEN if won else BORDER), 1.6 if won else 1.2))
            x0, y0 = a.right(), a.center().y()
            x1, y1 = b.left(), b.center().y()
            mid = x0 + (x1 - x0) / 2
            p.drawPolyline(QPointF(x0, y0), QPointF(mid, y0), QPointF(mid, y1), QPointF(x1, y1))
        for fid, r in self.boxes.items():
            self._paint_tie(p, self.t.fixture(fid), r)

    def _paint_tie(self, p, f, r):
        t = self.t
        focused = self.hasFocus() and self.current == f.id
        hot = focused or self._hover == f.id
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(BG_HIGHLIGHT if hot else BG_CARD))
        p.drawRect(r)
        winner = f.result.winner_id() if f.result else None
        mine = f.home in self.humans or f.away in self.humans
        if f.final:
            p.fillRect(QRectF(r.x(), r.y(), r.width(), 2), QColor(AWAY_TINT))
        half = r.height() / 2
        for i, (tid, ref, pts) in enumerate((
                (f.home, f.home_ref, f.result.home.points if f.result else None),
                (f.away, f.away_ref, f.result.away.points if f.result else None))):
            row = QRectF(r.x(), r.y() + i * half, r.width(), half)
            if winner and tid == winner:
                p.fillRect(QRectF(row.x(), row.y(), 3, row.height()), QColor(GREEN))
            p.drawPixmap(int(row.x() + 10), int(row.center().y() - 10), tournament_crest(self.ds, t, tid, 20))
            lost = winner is not None and tid != winner
            you = tid in self.humans
            p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold if tid == winner else QFont.DemiBold, 0.4))
            p.setPen(QColor(YOU_TINT if you else (FG_MUTED if not tid else (FG_TERTIARY if lost else FG_PRIMARY))))
            name = t.team_name(tid) if tid else ref_label(t, ref)
            nr = QRectF(row.x() + 38, row.y(), row.width() - 38 - 44, row.height())
            p.drawText(nr, Qt.AlignLeft | Qt.AlignVCenter,
                       p.fontMetrics().elidedText(name.upper() if tid else name, Qt.ElideRight, int(nr.width())))
            if pts is not None:
                sr = QRectF(row.right() - 40, row.y() + 4, 34, row.height() - 8)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(BG_BASE))
                p.drawRect(sr)
                p.setPen(QColor(FG_PRIMARY if tid == winner else FG_TERTIARY))
                p.setFont(tracked_font(FONT_DISPLAY, 12, QFont.Bold, 0))
                p.drawText(sr, Qt.AlignCenter, str(pts))
        p.setPen(QPen(QColor(BORDER).darker(130), 1))
        p.drawLine(QPointF(r.x() + 36, r.center().y()), QPointF(r.right(), r.center().y()))
        frame = ACCENT if focused else (YOU_TINT if mine else BORDER)
        p.setPen(QPen(QColor(frame), 1.5 if focused or mine else 1))
        p.setBrush(Qt.NoBrush)
        p.drawRect(r.adjusted(0.5, 0.5, -0.5, -0.5))
        if f.result and f.result.decided_by:
            p.setFont(tracked_font(FONT_DISPLAY, 8, QFont.DemiBold, 1.0))
            p.setPen(QColor(FG_TERTIARY))
            p.drawText(QRectF(r.x(), r.bottom() + 1, r.width(), 14), Qt.AlignRight | Qt.AlignVCenter,
                       f.result.score_text().split(" ", 1)[-1].strip("()").upper())

    # ── input ────────────────────────────────────────────────────────────
    def _at(self, pos):
        return next((fid for fid, r in self.boxes.items() if r.contains(pos)), None)

    def mouseMoveEvent(self, e):
        hit = self._at(e.pos())
        if hit != self._hover:
            self._hover = hit
            self.setCursor(Qt.PointingHandCursor if hit else Qt.ArrowCursor)
            self.update()

    def leaveEvent(self, e):
        self._hover = None
        self.update()

    def mousePressEvent(self, e):
        hit = self._at(e.pos())
        if hit:
            self.current = hit
            self.update()
            self.report.emit(hit)

    def _ensure_current(self):
        if self.current is None and self.order:
            # Start on the first tie still to play, else the last one.
            self.current = next((fid for fid in self.order if not self.t.fixture(fid).played),
                                self.order[-1])

    def focusInEvent(self, e):
        self._ensure_current()
        self.update()
        super().focusInEvent(e)

    def focusOutEvent(self, e):
        self.update()
        super().focusOutEvent(e)

    def keyPressEvent(self, e):
        self._ensure_current()
        k = e.key()
        if k in (Qt.Key_Return, Qt.Key_Enter) and self.current:
            self.report.emit(self.current)
            e.accept()
            return
        dirs = {Qt.Key_Left: (-1, 0), Qt.Key_Right: (1, 0), Qt.Key_Up: (0, -1), Qt.Key_Down: (0, 1)}
        if k in dirs and self.current:
            dx, dy = dirs[k]
            cur = self.boxes[self.current].center()
            best, score = None, None
            for fid, r in self.boxes.items():
                v = r.center() - cur
                primary = v.x() * dx + v.y() * dy
                if fid == self.current or primary <= 1:
                    continue
                s = primary + abs(v.x() * dy + v.y() * dx) * 2
                if score is None or s < score:
                    best, score = fid, s
            if best:
                self.current = best
                self.update()
                e.accept()
                return
            e.ignore()          # off the edge: the screen moves focus on
            return
        super().keyPressEvent(e)
