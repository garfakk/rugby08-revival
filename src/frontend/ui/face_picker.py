"""
ui/face_picker.py — browse & pick a player's head, stock or custom
=======================================================================
One modal, one grid, two sources: the ~550 stock faces
app.stock_faces.load_stock_faces() lists (id + the real player name it was
modelled on, where known) or the mod's own custom players/heads/*.big
files (app.player_ops.head_options). A STOCK/CUSTOM toggle swaps which one
the grid shows; both share the same click-to-arm-and-live-preview,
USE THIS HEAD-or-double-click-to-confirm mechanics.

Thumbnails are never bulk-extracted: each is decoded lazily, only once its
cell actually scrolls into view, off the GUI thread (QThreadPool) — see
face_png_bytes() in ui.face_thumbs for why that split exists. It already
handles both shapes a head comes in (a standalone portrait .fsh for stock,
backend.mod_utils.stock_portrait_path — or a full head_<n>.big for custom),
and both land in their usual disk caches under config.temp_directory, so
re-opening the picker, or picking a head browsed before, costs no re-decode.

An optional skin-tone filter narrows the STOCK grid — see
app.stock_faces.available_attributes(): the filter row is built entirely
from whatever assets/data/stock_face_attributes.xml actually defines, so
it only appears once there's data, and only for whichever category(ies)
are tagged. tools/classify_stock_faces.py only tags the ~192 generic
filler faces (from the developers' own ethnicity label in each one's
name), not the ~345 real named players — no hair_color, beard or
headgear either, all tried and dropped as unreliable pixel guesses; see
that script's docstring.

Modelled on ui.editor_kit.ConfirmDialog's modal-overlay mechanics (dimmed
backdrop, centered card, Escape to close) but self-contained rather than
routed through a screen's show_dialog/_dialog bookkeeping — the same
choice ui.editor_kit.browse_assets makes for its own PopupList, since this
is a free-form "browse and pick" flow, not a button-choice confirmation.

The whole window dims, same as any other modal here — but if `screen` has
borrow_stage()/reclaim_stage() (PlayerEditorScreen's 3D preview), the
picker pulls that stage out of its normal spot for the duration and shows
it in its own undimmed holder beside the grid, so a candidate can be
compared against a full backdrop without the preview itself going dark
too. reclaim_stage() puts it back on close, picked or not.
"""
import os

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QScrollArea, QLineEdit,
)
from PyQt5.QtGui import QPainter, QColor, QFont, QPixmap
from PyQt5.QtCore import (
    Qt, QRect, QPoint, QTimer, QEvent, QObject, QThreadPool, QRunnable, pyqtSignal,
)

from app import player_ops as P
from app.stock_faces import search_stock_faces, available_attributes
from backend.mod_utils import stock_portrait_path
from ui.broadcast import Card, display_label, eyebrow_label
from ui.editor_kit import Thumb, Note, ChoiceField, SegmentField, compact_button
from ui.face_thumbs import face_png_bytes
from ui.theme import (
    BG_HIGHLIGHT, BORDER, ACCENT, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY,
    FONT_BODY, T_TITLE, T_SMALL,
)
from shared.config import config
from shared.log import get_logger

log = get_logger(__name__)

CELL_W, CELL_H = 108, 132
THUMB_SIZE = 88
COLUMNS = 5
SEARCH_DEBOUNCE_MS = 150


class _ThumbSignals(QObject):
    done = pyqtSignal(object, bytes)   # key (int id or path str), PNG bytes (empty = none found)


class _ThumbJob(QRunnable):
    """Resolve (if needed) + decode one head's thumbnail off the GUI
    thread. Both steps already cache themselves to disk (by face id /
    archive mtime), so a repeat job (re-opening the picker, scrolling back
    up) is a cheap cache hit, not a re-read of data.gob / the mod folder."""

    def __init__(self, key, resolve_path, thumb_dir, signals):
        super().__init__()
        self.key = key
        self.resolve_path = resolve_path
        self.thumb_dir = thumb_dir
        self.signals = signals

    def run(self):
        try:
            path = self.resolve_path(self.key)
            data = face_png_bytes(self.thumb_dir, path) if path else None
        except Exception as e:   # a thumbnail is never worth crashing a worker thread
            log.warning(f"head {self.key} thumbnail: {e}")
            data = None
        self.signals.done.emit(self.key, data or b"")


class _FaceCell(QWidget):
    """One grid cell: thumbnail + title + subtitle. A single click arms it
    (live preview, stays open); a double-click confirms it straight away."""

    clicked = pyqtSignal()
    activated = pyqtSignal()

    def __init__(self, key, title, subtitle, selected=False, parent=None):
        super().__init__(parent)
        self.key = key
        self.loading = False
        self.has_thumb = False
        self.setFixedSize(CELL_W, CELL_H)
        self.setCursor(Qt.PointingHandCursor)
        v = QVBoxLayout(self)
        v.setContentsMargins(4, 4, 4, 2)
        v.setSpacing(2)
        self.thumb = Thumb(THUMB_SIZE, THUMB_SIZE)
        self.thumb.set_text("…")
        self.set_selected(selected)
        thumb_row = QHBoxLayout()
        thumb_row.addStretch(1)
        thumb_row.addWidget(self.thumb)
        thumb_row.addStretch(1)
        v.addLayout(thumb_row)
        title_lbl = Note(str(title), color=FG_SECONDARY, size=T_SMALL)
        title_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(title_lbl)
        sub_lbl = Note(subtitle or "—", color=FG_TERTIARY, size=T_SMALL)
        sub_lbl.setAlignment(Qt.AlignCenter)
        v.addWidget(sub_lbl)

    def set_selected(self, selected):
        self.thumb.set_border(ACCENT if selected else BORDER)

    def set_thumb(self, data):
        self.has_thumb = True
        self.loading = False
        if data:
            pix = QPixmap()
            pix.loadFromData(data)
            self.thumb.set_pixmap(pix, "NO FACE")
        else:
            self.thumb.set_text("NO FACE")

    def mousePressEvent(self, event):
        self.clicked.emit()

    def mouseDoubleClickEvent(self, event):
        self.activated.emit()


class FacePicker(QWidget):
    """Modal grid of heads — stock faces or the mod's own custom
    players/heads/*.big files, switched with a STOCK/CUSTOM toggle. A click
    arms a candidate — live-previewed via `on_preview` (e.g. the screen's 3D
    stage) without closing the grid, so several can be compared before
    committing. USE THIS HEAD or a double-click emits `picked` (str: a
    digit id for stock, a mod-relative .big path for custom) and closes;
    Escape or CLOSE closes without one, calling `on_cancel` to revert
    whatever `on_preview` last showed.

    `current` is the record's raw `face` value (a digit string, a
    mod-relative .big path, or blank) — it picks the toggle's starting
    side and the initially-highlighted cell."""

    picked = pyqtSignal(str)

    def __init__(self, screen, current="", on_preview=None, on_cancel=None):
        super().__init__(screen)
        self._screen = screen
        self._cells = {}          # key -> _FaceCell, for the CURRENT filter/mode only
        self._on_preview = on_preview
        self._on_cancel = on_cancel
        current = str(current or "")
        if current.isdigit():
            self._mode = "stock"
            self._current = int(current)
        elif current:
            self._mode = "custom"
            self._current = current
        else:
            self._mode = "stock"
            self._current = None
        self._pool = QThreadPool.globalInstance()
        # QThreadPool.start() doesn't itself keep a Python reference to the
        # QRunnable it's handed, and _load_visible() below builds one fresh
        # per call with nothing else holding onto it — occasionally (rare,
        # timing-dependent) that let a job get garbage collected before a
        # worker thread ever ran it: silently, no error, that cell's
        # thumbnail just never arrives, indistinguishable from a slow
        # network/disk until you scroll away and back and the next
        # _load_visible() pass — which skips it, since `cell.loading` was
        # already set and never got cleared — never retries it either.
        # Held here until each job's own done signal reports back.
        self._active_jobs = set()
        self._signals = _ThumbSignals()
        self._signals.done.connect(self._on_thumb_ready)
        self._portraits_dir = os.path.join(config.temp_directory, "stock_portraits")
        self._thumb_dir = os.path.join(config.temp_directory, "head_thumbs")
        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.timeout.connect(self._apply_search)

        self.setGeometry(screen.rect())
        self.card = Card(stripe=ACCENT)
        self.card.setParent(self)
        self.card.setFixedSize(660, 600)
        v = QVBoxLayout(self.card)
        v.setContentsMargins(20, 16, 20, 16)
        v.setSpacing(10)

        head = QHBoxLayout()
        head.addWidget(display_label("head", T_TITLE, QFont.Bold, track=0.8, upper=False))
        head.addStretch(1)
        self.mode_seg = SegmentField("", ["stock", "custom"])
        self.mode_seg.label_width = 0
        self.mode_seg.setFixedWidth(180)
        self.mode_seg.set_value(self._mode)
        self.mode_seg.edited.connect(self._on_mode_changed)
        head.addWidget(self.mode_seg)
        head.addStretch(1)
        self.use_btn = compact_button("USE THIS HEAD", "primary")
        self.use_btn.setEnabled(self._current is not None)
        self.use_btn.clicked.connect(self._confirm)
        head.addWidget(self.use_btn)
        close_btn = compact_button("CLOSE", "neutral")
        close_btn.clicked.connect(self._close)
        head.addWidget(close_btn)
        v.addLayout(head)

        self.search = QLineEdit()
        self.search.setStyleSheet(
            f"QLineEdit {{ background: {BG_HIGHLIGHT}; color: {FG_PRIMARY}; border: 1px solid {BORDER};"
            f" border-radius: 3px; padding: 6px 8px; font-family: '{FONT_BODY}'; font-size: 12pt; }}")
        self.search.textEdited.connect(lambda _: self._search_timer.start(SEARCH_DEBOUNCE_MS))
        v.addWidget(self.search)

        # Attribute filters — stock only, and only for whichever categories
        # assets/data/stock_face_attributes.xml actually has values for
        # (skin_tone, for ~192 of the 557 faces, as of writing).
        self._filter_fields = {}
        self.filter_row = QHBoxLayout()
        self.filter_row.setSpacing(10)
        for name, values in available_attributes().items():
            f = ChoiceField(name.replace("_", " "), values, allow_blank=True, blank_label="all")
            f.label_width = 72
            f.edited.connect(lambda _v: self._apply_search())
            self.filter_row.addWidget(f, stretch=1)
            self._filter_fields[name] = f
        if self._filter_fields:
            v.addLayout(self.filter_row)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setStyleSheet(f"background: {BG_HIGHLIGHT}; border: 1px solid {BORDER};")
        self.scroll.viewport().setStyleSheet(f"background: {BG_HIGHLIGHT};")
        self._grid_host = QWidget()
        self._grid_host.setStyleSheet(f"background: {BG_HIGHLIGHT};")
        self._grid = QGridLayout(self._grid_host)
        self._grid.setSpacing(4)
        self._grid.setContentsMargins(6, 6, 6, 6)
        self.scroll.setWidget(self._grid_host)
        self.scroll.verticalScrollBar().valueChanged.connect(self._load_visible)
        v.addWidget(self.scroll, stretch=1)

        self.count_note = Note("", color=FG_TERTIARY, size=T_SMALL)
        v.addWidget(self.count_note)

        # Borrow the screen's 3D stage for the duration, if it has one to
        # lend — shown undimmed in its own holder beside the grid. See
        # PlayerEditorScreen.borrow_stage/reclaim_stage.
        self._preview_holder = None
        borrow = getattr(screen, "borrow_stage", None)
        if callable(borrow):
            self._preview_holder = Card(stripe=ACCENT)
            self._preview_holder.setParent(self)
            ph_v = QVBoxLayout(self._preview_holder)
            ph_v.setContentsMargins(14, 14, 14, 12)
            ph_v.setSpacing(8)
            ph_v.addWidget(eyebrow_label("preview", color=FG_TERTIARY, size=11))
            ph_v.addWidget(borrow(self._preview_holder), stretch=1)
            self._preview_holder.show()

        self._update_mode_chrome()
        self._place()
        self._rebuild(self._entries())   # schedules its own first _load_visible
        self.show()
        self.raise_()
        self.search.setFocus()
        screen.installEventFilter(self)

    # ── layout / overlay mechanics (mirrors ConfirmDialog) ─────────────────
    def _place(self):
        self.setGeometry(self.parentWidget().rect())
        self.card.move((self.width() - self.card.width()) // 2,
                       max(30, (self.height() - self.card.height()) // 2))
        if self._preview_holder is not None:
            gap = 16
            x = self.card.x() + self.card.width() + gap
            w = max(0, min(340, self.width() - x - 20))
            visible = w >= 160
            self._preview_holder.setVisible(visible)
            if visible:
                self._preview_holder.setGeometry(x, self.card.y(), w, self.card.height())

    def eventFilter(self, watched, event):
        if watched is self._screen and event.type() == QEvent.Resize:
            self._place()
            self._load_visible()
        return False

    def paintEvent(self, event):
        p = QPainter(self)
        p.fillRect(self.rect(), QColor(0, 0, 0, 170))

    def mousePressEvent(self, event):
        event.accept()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._close()
        event.accept()

    def _close(self, committed=False):
        if not committed and self._on_cancel is not None:
            self._on_cancel()
        if self._preview_holder is not None:
            reclaim = getattr(self._screen, "reclaim_stage", None)
            if callable(reclaim):
                reclaim()
        self._screen.removeEventFilter(self)
        self.hide()
        self.deleteLater()

    # ── mode / source ───────────────────────────────────────────────────
    def _resolve_stock(self, key):
        return stock_portrait_path(key, self._portraits_dir)

    def _resolve_custom(self, key):
        path = os.path.join(config.mod_data_directory, key)
        return path if os.path.isfile(path) else None

    def _resolver(self):
        return self._resolve_stock if self._mode == "stock" else self._resolve_custom

    def _update_mode_chrome(self):
        self.search.setPlaceholderText(
            "search by id or player name…" if self._mode == "stock" else "search by file name…")
        for f in self._filter_fields.values():
            f.setVisible(self._mode == "stock")

    def _on_mode_changed(self, mode):
        self._mode = mode
        self._update_mode_chrome()
        self._apply_search()

    # ── grid / search ────────────────────────────────────────────────────
    def _entries(self):
        query = self.search.text()
        if self._mode == "stock":
            filters = {name: f.value() for name, f in self._filter_fields.items()}
            return search_stock_faces(query, filters)
        q = query.strip().lower()
        out = []
        for rel in P.head_options(config.mod_data_directory):
            label = os.path.basename(rel).replace("head_", "Head ").replace(".big", "")
            if q and q not in label.lower() and q not in rel.lower():
                continue
            out.append({"id": rel, "name": label})
        return out

    def _apply_search(self):
        self._rebuild(self._entries())

    def _rebuild(self, entries):
        while self._grid.count():
            item = self._grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.setParent(None)
                w.deleteLater()
        self._cells = {}
        subtitle_of = ((lambda e: e["name"]) if self._mode == "stock" else
                       (lambda e: os.path.dirname(e["id"])))
        title_of = ((lambda e: e["id"]) if self._mode == "stock" else (lambda e: e["name"]))
        for i, entry in enumerate(entries):
            key = entry["id"]
            cell = _FaceCell(key, title_of(entry), subtitle_of(entry), selected=(key == self._current))
            cell.clicked.connect(lambda k=key: self._arm(k))
            cell.activated.connect(lambda k=key: self._arm(k, confirm=True))
            self._grid.addWidget(cell, i // COLUMNS, i % COLUMNS)
            self._cells[key] = cell
        total = (len(search_stock_faces("")) if self._mode == "stock"
                else len(P.head_options(config.mod_data_directory)))
        self.count_note.setText(f"{len(entries)} of {total} heads"
                                if len(entries) != total else f"{total} heads")
        QTimer.singleShot(0, self._load_visible)

    def _load_visible(self):
        # Layout activation is lazy — adding cells to the grid doesn't
        # position them immediately, only on Qt's own next internal
        # layout pass, and the QTimer.singleShot(0, ...) that schedules a
        # call here isn't guaranteed to run after that pass rather than
        # before it. When it runs first, every cell still reports its
        # layout's untouched default geometry (0,0,w,h) — so every one of
        # them "intersects" the viewport at (0,0) and this loads the
        # entire catalog at once instead of just what's on screen.
        # activate() alone turned out not to be enough on its own — the
        # grid's HOST widget (what the scroll area resizes to fit the
        # content, via setWidgetResizable(True)) hadn't been resized to
        # match yet either, a chicken-and-egg the two calls below
        # resolve: adjust the host to the now-activated layout's real
        # size hint, then activate again so cell positions are correct
        # against THAT.
        self._grid.activate()
        self.scroll.widget().adjustSize()
        self._grid.activate()
        viewport = self.scroll.viewport().rect()
        resolver = self._resolver()
        for key, cell in self._cells.items():
            if cell.has_thumb or cell.loading:
                continue
            top_left = cell.mapTo(self.scroll.viewport(), QPoint(0, 0))
            if not viewport.intersects(QRect(top_left, cell.size())):
                continue
            cell.loading = True
            job = _ThumbJob(key, resolver, self._thumb_dir, self._signals)
            self._active_jobs.add(job)
            self._pool.start(job)

    def _on_thumb_ready(self, key, data):
        cell = self._cells.get(key)
        if cell is None:
            return   # filtered out (a different search/mode) since the job started
        cell.set_thumb(data)

    def _arm(self, key, confirm=False):
        if key != self._current:
            old = self._cells.get(self._current)
            if old is not None:
                old.set_selected(False)
            self._current = key
            cell = self._cells.get(key)
            if cell is not None:
                cell.set_selected(True)
            self.use_btn.setEnabled(True)
            if self._on_preview is not None:
                self._on_preview(key)
        if confirm:
            self._confirm()

    def _confirm(self):
        if self._current is None:
            return
        self.picked.emit(str(self._current))
        self._close(committed=True)
