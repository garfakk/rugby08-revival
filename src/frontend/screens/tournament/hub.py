"""
screens/tournament/hub.py — Tournament mode's front door: the saved
tournaments, newest first, with NEW / CONTINUE / DELETE.
"""
from PyQt5.QtWidgets import QHBoxLayout, QVBoxLayout, QWidget

from app.screen_base import Screen
from app.tournament import formats, persistence
from app.tournament.session import TournamentSession
from shared.log import get_logger
from ui.broadcast import HintBar, page_header
from ui.editor_kit import ConfirmDialog, Note, compact_button
from ui.theme import BG_BASE, FG_MUTED, GREEN, WARN

from .common import DataTable

log = get_logger(__name__)


class TournamentHubScreen(Screen):
    def __init__(self, ds, on_back, on_new, on_open):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.on_new = on_new
        self.on_open = on_open
        self._saves = []
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Tournament", breadcrumb="game modes", on_back=self.on_back_cb))

        body = QWidget()
        body.setStyleSheet(f"background: {BG_BASE};")
        bl = QVBoxLayout(body)
        bl.setContentsMargins(120, 32, 120, 24)
        bl.setSpacing(14)

        self.table = DataTable(["Tournament", "Competition", "Managing", "Progress", "Last played"],
                               stretch_col=0)
        self.table.activated_row.connect(lambda _r: self._continue())
        self.focus.register(self.table)
        bl.addWidget(self.table, stretch=1)
        self.empty = Note("No tournament in progress. Start one with NEW TOURNAMENT.", color=FG_MUTED)
        bl.addWidget(self.empty)

        row = QHBoxLayout()
        self.delete_btn = compact_button("DELETE", "danger")
        self.delete_btn.clicked.connect(self._delete)
        row.addWidget(self.delete_btn)
        row.addStretch(1)
        self.new_btn = compact_button("NEW TOURNAMENT", "neutral")
        self.new_btn.clicked.connect(self.on_new)
        row.addWidget(self.new_btn)
        self.continue_btn = compact_button("CONTINUE", "primary")
        self.continue_btn.clicked.connect(self._continue)
        row.addWidget(self.continue_btn)
        for b in (self.delete_btn, self.new_btn, self.continue_btn):
            self.focus.register(b)
        bl.addLayout(row)
        root.addWidget(body, stretch=1)

        hints = HintBar()
        hints.set_hints([("A", "continue"), ("B", "back")])
        root.addWidget(hints)

    def on_show(self):
        super().on_show()
        self.reload()

    def reload(self):
        names = {tid: tpl.get("name", tid) for tid, tpl in formats.load_templates().items()}
        self._saves = persistence.list_saves()
        rows, colors = [], {}
        for i, s in enumerate(self._saves):
            if s.get("error"):
                rows.append([s["name"], "", "", ("unreadable save", WARN), ""])
                continue
            if s.get("champion"):
                progress = (f"Won by {s['champion']}", GREEN)
            else:
                progress = f"Matchday {s['day'] + 1} of {s['last_day'] + 1}"
            rows.append([s["name"], names.get(s["template_id"], s["template_id"]),
                         ", ".join(s.get("humans") or []) or "—", progress,
                         (s.get("updated") or "").replace("T", " ")])
        self.table.set_rows(rows, keys=[s["id"] for s in self._saves], colors=colors)
        has = bool(self._saves)
        self.table.setVisible(has)
        self.empty.setVisible(not has)
        self.continue_btn.setEnabled(has)
        self.delete_btn.setEnabled(has)
        if has and self.table.currentRow() < 0:
            self.table.selectRow(0)

    def _selected(self):
        key = self.table.current_key()
        return next((s for s in self._saves if s["id"] == key), None)

    def _continue(self):
        s = self._selected()
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
        s = self._selected()
        if not s:
            return

        def done(role):
            if role == "ok":
                persistence.delete(s["id"])
                self.reload()
        ConfirmDialog(self, "Delete tournament?", f"“{s['name']}” and its progress will be lost.",
                      [("CANCEL", "neutral", "cancel"), ("DELETE", "danger", "ok")], done)
