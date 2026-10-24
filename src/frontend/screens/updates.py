"""
screens/updates.py — Updates
=============================
Online (app/updater), two cards with their own versions:

  PROGRAM   the newest program release on GitHub: DOWNLOAD & INSTALL fetches
            the program-only installer, checks it against the release's
            SHA256SUMS, then (after a last confirmation) starts it on this
            folder and closes the mod; the installer opens it again.
            RELEASE PAGE opens the release in the browser instead.
  DATA      the newest data release this program can read: only the files
            that differ from this install are downloaded (verified, then
            applied with backups, so it can be undone below).

CHECK NOW asks GitHub again (the startup check does it once a day, see
main.py). Running from source, both are updated with git and only the check
is offered.

From a file (app/updates.py): install an update zip or folder of new and
replaced files, fixed team / player records; what it would change is shown
before anything is written; the last update installed (online data updates
included) can be undone. The data is re-read at the next start.
"""
import os
import time

from PyQt5.QtCore import Qt, QUrl
from PyQt5.QtGui import QDesktopServices
from PyQt5.QtWidgets import (QApplication, QFileDialog, QHBoxLayout, QScrollArea, QVBoxLayout,
                             QWidget)

from app.screen_base import Screen
from app.updater import data as data_update
from app.updater import program, schedule
from app.updates import UpdateError, default_updates
from ui.background import Job
from ui.broadcast import HintBar, display_label, page_header
from ui.editor_kit import ConfirmDialog, Note, SectionCard, compact_button
from ui.theme import (ACCENT, BG_BASE, DANGER_LITE, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FONT_BODY,
                      GREEN, T_LABEL, WARN)

RESTART = "Restart the mod to use it."


def _ago(stamp):
    if not stamp:
        return "never"
    mins = int((time.time() - stamp) // 60)
    if mins < 1:
        return "just now"
    if mins < 60:
        return f"{mins} min ago"
    hours = mins // 60
    return f"{hours} h ago" if hours < 48 else time.strftime("%d %b %Y", time.localtime(stamp))


class _Bar(QWidget):
    """A thin progress bar (0..1), hidden when idle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(6)
        self._v = 0.0
        self.hide()

    def set_value(self, v):
        self._v = max(0.0, min(1.0, v))
        self.show()
        self.update()

    def paintEvent(self, event):
        from PyQt5.QtGui import QColor, QPainter
        p = QPainter(self)
        p.fillRect(self.rect(), QColor("#10200c"))
        p.fillRect(0, 0, int(self.width() * self._v), self.height(), QColor(ACCENT))


class _ChannelCard(SectionCard):
    """One online channel: title, version line, detail line, progress, buttons."""

    def __init__(self, title, screen):
        super().__init__(title)
        self.headline = display_label("", 15, track=0.6, color=FG_PRIMARY, upper=False)
        self.detail = Note("", color=FG_SECONDARY, size=T_LABEL)
        self.bar = _Bar()
        self.add(self.headline)
        self.add(self.detail)
        self.add(self.bar)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.buttons = []
        for _ in range(2):
            b = compact_button("", "primary")
            b.hide()
            row.addWidget(b)
            screen.focus.register(b)
            self.buttons.append(b)
        row.addStretch(1)
        holder = QWidget()
        holder.setObjectName("chanButtons")
        holder.setStyleSheet("QWidget#chanButtons { background: transparent; }")
        holder.setLayout(row)
        self.add(holder)

    def show_state(self, headline, detail="", colour=FG_SECONDARY, buttons=()):
        """buttons: [(label, variant, callback)], at most two."""
        self.headline.setText(headline)
        self.detail.setText(detail)
        self.detail.setStyleSheet(f"color: {colour}; background: transparent;"
                                  f" font-family: '{FONT_BODY}'; font-size: {T_LABEL}pt;")
        self.detail.setVisible(bool(detail))
        for b in self.buttons:
            try:
                b.clicked.disconnect()
            except TypeError:
                pass
            b.hide()
        for b, (label, variant, cb) in zip(self.buttons, buttons):
            from ui.widgets import style_button
            b.setText(label.replace("&", "&&"))          # a lone & would be a shortcut marker
            style_button(b, variant)
            b.setStyleSheet(b.styleSheet() + "QPushButton { padding: 4px 14px; letter-spacing: 1px; }")
            b.clicked.connect(cb)
            b.show()
        self.bar.hide()


class UpdatesScreen(Screen):
    def __init__(self, on_back, updates=None, on_quit=None):
        super().__init__(on_back=on_back)
        self.updates = updates or default_updates()
        self.on_quit = on_quit or (lambda: QApplication.instance().quit())
        self._dialog = None
        self._job = None
        self.result = None                    # schedule.Result of the last check
        self._data_plan = None
        # what this install can do online (tests replace them)
        from shared.app_paths import FROZEN, app_directory
        from shared.version import APP_VERSION, DATA_SCHEMA
        self.program_supported = program.supported()
        self.data_supported = FROZEN or os.environ.get("R08_DATA_UPDATES") == "1"
        self.app_dir = app_directory()
        self.program_version, self.schema = APP_VERSION, DATA_SCHEMA
        self.sources = None                   # None: app/updater/sources.load()
        self._build()

    # ── layout ──────────────────────────────────────────────────────────
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
        left.setSpacing(12)
        top = QHBoxLayout()
        self.check_btn = compact_button("CHECK NOW", "neutral")
        self.check_btn.clicked.connect(self.check_now)
        self.focus.register(self.check_btn)
        top.addWidget(self.check_btn)
        self.checked_note = Note("", color=FG_TERTIARY, size=T_LABEL)
        top.addWidget(self.checked_note, stretch=1)
        left.addLayout(top)
        self.program_card = _ChannelCard("program", self)
        self.data_card = _ChannelCard("data", self)
        left.addWidget(self.program_card)
        left.addWidget(self.data_card)

        left.addSpacing(6)
        left.addWidget(Note("FROM A FILE", color=FG_TERTIARY, size=T_LABEL))
        self.install_btn = compact_button("INSTALL AN UPDATE…", "neutral")
        self.install_btn.clicked.connect(self._pick)
        self.undo_btn = compact_button("UNDO THE LAST UPDATE…", "danger")
        self.undo_btn.clicked.connect(self._undo)
        for b in (self.install_btn, self.undo_btn):
            left.addWidget(b)
            self.focus.register(b)
        left.addStretch(1)
        left_w = QWidget()
        left_w.setObjectName("updatesLeft")
        left_w.setStyleSheet("QWidget#updatesLeft { background: transparent; }")
        left_w.setLayout(left)
        left_w.setFixedWidth(470)
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
        self._say("")
        self.hintbar = HintBar()
        self.hintbar.set_hints([("A", "choose"), ("B", "back")])
        root.addWidget(self.hintbar)
        self._show_result()

    def on_show(self):
        super().on_show()
        self.reload()
        self._show_result()

    def reload(self):
        while self.rows_v.count():
            item = self.rows_v.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        entries = list(reversed(self.updates.installed()))
        self.undo_btn.setEnabled(bool(entries) and not self._busy())
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

    # ── online: checking ────────────────────────────────────────────────
    def _busy(self):
        return self._job is not None and self._job.running

    def _run(self, fn, done, failed, progress=None, name="updates"):
        self._job = Job(fn, self, name)
        self._job.done.connect(done)
        self._job.failed.connect(failed)
        if progress:
            self._job.progress.connect(progress)
        self._job.start()
        self.check_btn.setEnabled(False)
        self.undo_btn.setEnabled(False)

    def _idle(self):
        self._job = None
        self.check_btn.setEnabled(True)
        self.undo_btn.setEnabled(bool(self.updates.installed()))

    def set_result(self, result):
        """A check made elsewhere (the startup check in main.py)."""
        self.result = result
        self._data_plan = None
        self._show_result()

    def check_now(self):
        if self._busy():
            return
        self.program_card.show_state("Checking…")
        self.data_card.show_state("Checking…")
        updates_dir, mod_data = self.updates.journal_dir, self.updates.roots["mod_data"]

        def work(_report, _cancelled):
            return schedule.check_all(updates_dir, mod_data, self.program_version, self.schema,
                                      srcs=self.sources)

        def done(result):
            self._idle()
            self.set_result(result)

        def failed(err):
            self._idle()
            self.program_card.show_state("Couldn't check", err, DANGER_LITE)
            self.data_card.show_state("Couldn't check", err, DANGER_LITE)
        self._run(work, done, failed, name="update-check")

    def _show_result(self):
        r = self.result
        self.checked_note.setText(
            f"Last checked {_ago(r.checked_at) if r else _ago(schedule.last_checked(self.updates.journal_dir))}")
        if r is None:
            self.program_card.show_state(f"Version {self.program_version}", "Not checked yet.")
            current = data_update.local_version(self.updates.roots["mod_data"]) or "unknown"
            self.data_card.show_state(f"Version {current}", "Not checked yet.")
            return
        self._show_program(r)
        self._show_data(r)

    def _show_program(self, r):
        card, c = self.program_card, r.program
        if r.program_error:
            card.show_state(f"Version {self.program_version}", f"Couldn't check: {r.program_error}", DANGER_LITE)
            return
        if not c or not c.available:
            card.show_state(f"Version {self.program_version}", "Up to date.", GREEN)
            return
        head = f"{c.current}  →  {c.release.version} available"
        page = ("RELEASE PAGE", "neutral", lambda: QDesktopServices.openUrl(QUrl(c.release.url)))
        notes = _first_lines(c.release.notes)
        if not self.program_supported:
            card.show_state(head, (notes + "\n" if notes else "") + "Running from source: update with git.",
                            WARN, [page])
        elif c.problem:
            card.show_state(head, c.problem, WARN, [page])
        else:
            size = data_update.human_size(c.installer[2]) if c.installer[2] else ""
            card.show_state(head, notes + (f"\nInstaller: {size}" if size else ""), FG_SECONDARY,
                            [("DOWNLOAD & INSTALL", "primary", self._program_update), page])

    def _show_data(self, r):
        card, c = self.data_card, r.data
        if r.data_error:
            card.show_state("Data", f"Couldn't check: {r.data_error}", DANGER_LITE)
            return
        current = (c.current if c else "") or "unknown"
        if not c or not c.available:
            blocked = (f"A newer data release needs program {c.blocked} or later: update the program first."
                       if c and c.blocked else "Up to date.")
            card.show_state(f"Version {current}", blocked, WARN if c and c.blocked else GREEN)
            return
        head = f"{current}  →  {c.release.version} available"
        notes = _first_lines(c.release.notes)
        if not self.data_supported:
            card.show_state(head, (notes + "\n" if notes else "") + "Running from source: update with git.", WARN)
            return
        if self._data_plan is not None and self._data_plan.manifest is c.manifest:
            p = self._data_plan
            if p.empty:
                card.show_state(head, "Your data already has every file of this release.", GREEN,
                                [("MARK AS UPDATED", "neutral", self._data_update)])
            else:
                card.show_state(head, (notes + "\n" if notes else "") + p.summary() + ".", FG_SECONDARY,
                                [("UPDATE DATA", "primary", self._data_update)])
            return
        card.show_state(head, "Comparing with your data…")
        self._plan_data(c)

    # ── online: data ────────────────────────────────────────────────────
    def _plan_data(self, c):
        if self._busy():
            return
        root = self.updates.roots["mod_data"]

        def work(report, _cancelled):
            return data_update.plan(c.manifest, root, progress=lambda i, n: report(i, n))

        def progress(args):
            i, n = args
            self.data_card.bar.set_value(i / max(1, n))
            self.data_card.detail.setText(f"Checking your data files… {i} / {n}")
            self.data_card.detail.show()

        def done(the_plan):
            self._idle()
            self._data_plan = the_plan
            self._show_data(self.result)

        def failed(err):
            self._idle()
            self.data_card.show_state("Data", f"Couldn't compare: {err}", DANGER_LITE)
        self._run(work, done, failed, progress, name="data-plan")

    def _data_update(self):
        if self._busy() or self._data_plan is None:
            return
        the_plan, card = self._data_plan, self.data_card
        staging = data_update.staging_dir(self.updates.journal_dir, the_plan.manifest)
        updates = self.updates

        def work(report, cancelled):
            data_update.download(the_plan, staging, progress=lambda *a: report(*a), cancel=cancelled)
            report("apply")
            return data_update.apply(the_plan, staging, updates)

        def progress(args):
            if args == ("apply",):
                card.detail.setText("Installing…")
                return
            files, nfiles, done_b, total_b = args
            card.bar.set_value(done_b / max(1, total_b))
            card.detail.setText(f"{files} / {nfiles} files · {data_update.human_size(done_b)} of "
                                f"{data_update.human_size(total_b)}")

        def done(entry):
            self._idle()
            self._data_plan = None
            v = the_plan.manifest.get("data_version", "")
            card.show_state(f"Version {v}", f"Installed. {RESTART}", GREEN)
            self._say(f"Data {v} installed ({entry['summary']}). {RESTART}", GREEN)
            self.reload()

        def failed(err):
            self._idle()
            if not err:
                self._show_data(self.result)
                self._say("Data update cancelled: nothing was changed. It resumes where it stopped.", WARN)
            else:
                self._show_data(self.result)
                self._say(f"The data update failed, nothing was changed: {err}", DANGER_LITE)
        card.show_state(card.headline.text(), "Starting…", FG_SECONDARY,
                        [("CANCEL", "neutral", lambda: self._job and self._job.cancel())])
        card.bar.set_value(0)
        self._run(work, done, failed, progress, name="data-update")

    # ── online: program ─────────────────────────────────────────────────
    def _program_update(self):
        c = self.result.program if self.result else None
        if self._busy() or not c or not c.installer:
            return
        card = self.program_card
        dest = os.path.join(self.updates.journal_dir, "downloads")

        def work(report, cancelled):
            return program.download(c, dest, progress=lambda n, total: report(n, total), cancel=cancelled)

        def progress(args):
            n, total = args
            card.bar.set_value(n / max(1, total))
            card.detail.setText(f"Downloading… {data_update.human_size(n)} of {data_update.human_size(total)}")

        def done(path):
            self._idle()
            self._show_program(self.result)
            self._confirm_install(c, path)

        def failed(err):
            self._idle()
            self._show_program(self.result)
            if err:
                self._say(f"The program update could not be downloaded: {err}", DANGER_LITE)
        card.show_state(card.headline.text(), "Starting…", FG_SECONDARY,
                        [("CANCEL", "neutral", lambda: self._job and self._job.cancel())])
        card.bar.set_value(0)
        self._run(work, done, failed, progress, name="program-download")

    def _confirm_install(self, c, path):
        def go(role):
            self._dialog = None
            if role != "ok":
                return
            try:
                program.launch(path, self.app_dir)
            except program.ProgramUpdateError as e:
                self._say(str(e), DANGER_LITE)
                return
            self.on_quit()
        self._dialog = ConfirmDialog(
            self, f"Install version {c.release.version}?",
            "The installer is downloaded and verified. The mod closes now, the installer updates it "
            "(your data, settings and tournaments are kept), then opens it again.",
            [("LATER", "neutral", "cancel"), ("INSTALL NOW", "primary", "ok")], go)

    # ── from a file ─────────────────────────────────────────────────────
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
        if not entries or self._busy():
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
            self._say(f"Uninstalled {entry['name']}. {RESTART}", WARN)
            self._data_plan = None
            self.reload()
            self._show_result()
        self._dialog = ConfirmDialog(
            self, f"Undo {last['name']} {last.get('version', '')}?".replace("  ", " "),
            "Revert the changes made by the last update",
            [("CANCEL", "neutral", "cancel"), ("UNDO", "danger", "ok")], done)

    def keyPressEvent(self, event):
        if self._dialog is not None:
            return
        super().keyPressEvent(event)


def _first_lines(text, n=3, width=300):
    """The release notes' first lines, for the card (markdown marks dropped)."""
    lines = [ln.strip().lstrip("#*- ").strip() for ln in str(text or "").splitlines()]
    lines = [ln for ln in lines if ln][:n]
    out = "\n".join(lines)
    return out if len(out) <= width else out[:width - 1] + "…"

