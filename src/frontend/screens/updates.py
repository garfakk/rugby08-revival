"""
screens/updates.py — Updates
=============================
Install an update (app/updates.py): a zip or folder of new and replaced
files for this install (data pack, program assets such as a patches DLL)
and fixed team / player records. What it would change is shown before
anything is written; the last update installed can be undone. The data is
re-read at the next start.
"""
import os

from PyQt5.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog, QScrollArea
from PyQt5.QtCore import Qt

from app.screen_base import Screen
from app.updates import UpdateError, default_updates
from ui.broadcast import HintBar, page_header
from ui.editor_kit import SectionCard, Note, compact_button, ConfirmDialog
from ui.theme import BG_BASE, GREEN, WARN, DANGER_LITE, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FONT_BODY, T_LABEL

RESTART = "Restart the mod to use it."


class UpdatesScreen(Screen):
    def __init__(self, on_back, updates=None):
        super().__init__(on_back=on_back)
        self.updates = updates or default_updates()
        self._dialog = None
        self._build()

    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(page_header("Updates", breadcrumb="tools", on_back=self.on_back_cb))

        body = QWidget()
        body.setObjectName("updatesBody")
        body.setStyleSheet(f"QWidget#updatesBody {{ background: {BG_BASE}; }}")
        h = QHBoxLayout(body)
        h.setContentsMargins(28, 20, 28, 14)
        h.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.install_btn = compact_button("INSTALL AN UPDATE…", "primary")
        self.install_btn.clicked.connect(self._pick)
        self.undo_btn = compact_button("UNDO THE LAST UPDATE…", "danger")
        self.undo_btn.clicked.connect(self._undo)
        for b in (self.install_btn, self.undo_btn):
            left.addWidget(b)
            self.focus.register(b)
        left.addStretch(1)
        left_w = QWidget()
        left_w.setLayout(left)
        left_w.setFixedWidth(430)
        h.addWidget(left_w)

        self.card = SectionCard("installed")
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        scroll.viewport().setStyleSheet("background: transparent;")
        self.rows = QWidget()
        self.rows.setObjectName("updateRows")
        self.rows.setStyleSheet("QWidget#updateRows { background: transparent; }")
        self.rows_v = QVBoxLayout(self.rows)
        self.rows_v.setContentsMargins(0, 4, 8, 4)
        self.rows_v.setSpacing(10)
        scroll.setWidget(self.rows)
        self.card.add(scroll, stretch=1)
        h.addWidget(self.card, stretch=1)
        root.addWidget(body, stretch=1)

        self.status = Note("", color=FG_SECONDARY, size=T_LABEL)
        self.status.setContentsMargins(28, 0, 28, 4)
        root.addWidget(self.status)
        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "choose"), ("B", "back")])
        root.addWidget(self.hintbar)

    def on_show(self):
        super().on_show()
        self.reload()

    def reload(self):
        while self.rows_v.count():
            item = self.rows_v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = list(reversed(self.updates.installed()))
        self.undo_btn.setEnabled(bool(entries))
        if not entries:
            self.rows_v.addWidget(Note("No update installed.", color=FG_TERTIARY, size=T_LABEL))
        for i, e in enumerate(entries):
            title = f"{e.get('name', '')} {e.get('version', '')}".strip()
            when = str(e.get("installed", "")).replace("T", " ")
            self.rows_v.addWidget(Note(title + ("   (last)" if i == 0 else ""),
                                       color=FG_PRIMARY, size=T_LABEL))
            text = f"{when} · {e.get('summary', '')}"
            if e.get("description"):
                text += f"\n{e['description']}"
            self.rows_v.addWidget(Note(text, color=FG_SECONDARY, size=T_LABEL))
        self.rows_v.addStretch(1)

    def _say(self, text, colour=FG_SECONDARY):
        self.status.setStyleSheet(f"color: {colour}; background: transparent;"
                                  f" font-family: '{FONT_BODY}'; font-size: {T_LABEL}pt;")
        self.status.setText(text)

    # ── install ─────────────────────────────────────────────────────────
    def _pick(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select the update file",
            os.path.expanduser("~"), "Update (*.zip update.json)")
        if path:
            self.offer(path)

    def offer(self, path):
        """Show what the update at `path` would change; install on OK."""
        try:
            plan = self.updates.read(path)
        except UpdateError as e:
            self._say(f"Cannot install this update: {e}", DANGER_LITE)
            return
        text = plan.summary() + "."
        if plan.manifest.get("description"):
            text = f"{plan.manifest['description']}\n\n{text}"
        if plan.ignored:
            shown = ", ".join(plan.ignored[:5]) + (" …" if len(plan.ignored) > 5 else "")
            text += f"\nIgnored (not files this mod uses): {shown}"

        def done(role):
            self._dialog = None
            if role == "ok":
                self._install(path)
        self._dialog = ConfirmDialog(
            self, f"Install {plan.name} {plan.version}?".replace("  ", " "), text,
            [("CANCEL", "neutral", "cancel"), ("INSTALL", "primary", "ok")], done)

    def _install(self, path):
        try:
            entry = self.updates.install(path)
        except UpdateError as e:
            self._say(f"The update failed, nothing was changed: {e}", DANGER_LITE)
            return
        self._say(f"Installed {entry['name']} ({entry['summary']}). {RESTART}", GREEN)
        self.reload()

    # ── undo ────────────────────────────────────────────────────────────
    def _undo(self):
        entries = self.updates.installed()
        if not entries:
            return
        last = entries[-1]

        def done(role):
            self._dialog = None
            if role != "ok":
                return
            try:
                entry = self.updates.undo_last()
            except UpdateError as e:
                self._say(str(e), DANGER_LITE)
                return
            self._say(f"Uninstalles {entry['name']}. {RESTART}", WARN)
            self.reload()
        self._dialog = ConfirmDialog(
            self, f"Undo {last['name']} {last.get('version', '')}?".replace("  ", " "),
            "Revert the changes made by the last update",
            [("CANCEL", "neutral", "cancel"), ("UNDO", "danger", "ok")], done)

    def keyPressEvent(self, event):
        if self._dialog is not None:
            return
        super().keyPressEvent(event)
