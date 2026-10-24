"""
screens/user_edits.py — My edits
=================================
Every team and player the user changed (app/user_edits.py), what changed,
and the conflicts a new data release left: for each, keep the user's value
or take the release's. A record's edit can be dropped (back to the release),
and a set of edits exported as a folder for the mod's maintainer — who, in
the maintainer's mode, imports edits and writes them into the data pack.
"""
import os
import zipfile
from datetime import datetime

from PyQt5.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QScrollArea, QFileDialog, QApplication,
)
from PyQt5.QtCore import Qt

from app.screen_base import Screen
from app.input import Action, KEYMAP
from app import game_data as G
from app.user_edits import MISSING, KINDS, changed_paths, get_path
from app.season import season_label
from shared.app_paths import user_data_directory
from shared.config import config
from shared.version import APP_VERSION
from ui.broadcast import HintBar, page_header
from ui.editor_kit import SectionCard, Note, SegmentField, compact_button, ConfirmDialog
from ui.form import SearchList
from ui.theme import (
    BG_BASE, GREEN, WARN, DANGER_LITE, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FONT_BODY,
    T_LABEL, T_VALUE,
)

STATUS = {"conflict": ("CONFLICT", DANGER_LITE), "new": ("NEW", GREEN),
          "deleted": ("DELETED", WARN), "edited": ("EDITED", FG_TERTIARY)}
MAX_ROWS = 120          # rows of changes/conflicts shown for one record


def short(value, limit=70):
    """A value in a few words, for a row of the comparison."""
    if value is MISSING or value is None:
        return "— (none)"
    if isinstance(value, dict):
        return f"{{{len(value)} fields}}"
    if isinstance(value, list):
        text = ", ".join(str(v) for v in value[:8]) + (" …" if len(value) > 8 else "")
        return f"[{len(value)}] {text}" if value else "[empty]"
    text = str(value) if value != "" else "“”"
    return text if len(text) <= limit else text[:limit - 1] + "…"


def path_label(kind, path):
    """("stats", "2024", "height") -> "2024-2025 · height"."""
    if not path:
        return "the whole record"
    parts = list(path)
    if kind == "players" and parts[0] == "stats" and len(parts) > 1:
        parts = [season_label(parts[1])] + parts[2:]
    elif kind == "teams" and str(parts[0]).isdigit():
        parts = [season_label(parts[0])] + parts[1:]
    return " · ".join(str(p).replace("_", " ") for p in parts)


class UserEditsScreen(Screen):
    def __init__(self, ds, on_back, open_team=None, open_player=None):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.open_team_cb = open_team
        self.open_player_cb = open_player
        self.current = None         # (kind, id)
        self.choices = {}           # conflict path -> SegmentField
        self.bulk = "mine"          # choice for the conflicts past MAX_ROWS (no row)
        self._dialog = None
        self._build()

    @property
    def edits(self):
        return self.ds.edits

    # ── layout ───────────────────────────────────────────────────────────
    def _build(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.header = page_header("My edits", breadcrumb="tools", on_back=self.on_back_cb)
        root.addWidget(self.header)

        body = QWidget()
        body.setObjectName("editsBody")
        body.setStyleSheet(f"QWidget#editsBody {{ background: {BG_BASE}; }}")
        h = QHBoxLayout(body)
        h.setContentsMargins(28, 20, 28, 14)
        h.setSpacing(20)

        left = QVBoxLayout()
        left.setSpacing(8)
        self.enabled_field = SegmentField("Use my edits", ["on", "off"],
                                          display=lambda v: v.upper())
        self.enabled_field.setFixedWidth(430)
        self.enabled_field.edited.connect(self._toggle_enabled)
        self.focus.register(self.enabled_field)
        left.addWidget(self.enabled_field)
        self.summary = Note("", color=FG_SECONDARY, size=T_LABEL)
        left.addWidget(self.summary)
        self.list = SearchList("name, id")
        self.list.setFixedWidth(430)
        self.list.activated.connect(self._show)
        self.focus.register(self.list)
        left.addWidget(self.list, stretch=1)
        actions = QVBoxLayout()
        actions.setSpacing(6)
        self.export_btn = compact_button("EXPORT MY EDITS…")
        self.export_btn.clicked.connect(self._export)
        actions.addWidget(self.export_btn)
        self.import_btn = self.promote_btn = None
        if self._maintainer():
            self.import_btn = compact_button("IMPORT EDITS…")
            self.import_btn.clicked.connect(self._import)
            actions.addWidget(self.import_btn)
            self.promote_btn = compact_button("WRITE ALL INTO THE DATA PACK…", "primary")
            self.promote_btn.clicked.connect(self._promote_all)
            actions.addWidget(self.promote_btn)
        for b in (self.export_btn, self.import_btn, self.promote_btn):
            if b is not None:
                self.focus.register(b)
        left.addLayout(actions)
        h.addLayout(left)

        self.card = SectionCard("edit")
        self.title = Note("", color=FG_PRIMARY, size=T_VALUE)
        self.card.add(self.title)
        buttons = QHBoxLayout()
        buttons.setSpacing(8)
        self.mine_btn = compact_button("KEEP ALL MINE")
        self.mine_btn.clicked.connect(lambda: self._set_all("mine"))
        self.theirs_btn = compact_button("TAKE ALL FROM THE RELEASE")
        self.theirs_btn.clicked.connect(lambda: self._set_all("theirs"))
        self.apply_btn = compact_button("APPLY MY CHOICES", "primary")
        self.apply_btn.clicked.connect(lambda: self._apply())
        self.revert_btn = compact_button("DELETE…", "danger")
        self.revert_btn.clicked.connect(self._revert)
        self.open_btn = compact_button("OPEN IN THE EDITOR")
        self.open_btn.clicked.connect(self._open)
        self.write_btn = compact_button("WRITE INTO THE DATA PACK") if self._maintainer() else None
        if self.write_btn is not None:
            self.write_btn.clicked.connect(lambda: self._promote([self.current]))
        for b in (self.mine_btn, self.theirs_btn, self.apply_btn, self.open_btn, self.write_btn,
                  self.revert_btn):
            if b is not None:
                buttons.addWidget(b)
                self.focus.register(b)
        buttons.addStretch(1)
        self.card.add_layout(buttons)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.scroll.setStyleSheet("QScrollArea { background: transparent; border: none; }")
        self.rows = QWidget()
        self.rows.setObjectName("editRows")
        self.rows.setStyleSheet("QWidget#editRows { background: transparent; }")
        self.scroll.viewport().setStyleSheet("background: transparent;")
        self.rows_v = QVBoxLayout(self.rows)
        self.rows_v.setContentsMargins(0, 4, 8, 4)
        self.rows_v.setSpacing(4)
        self.scroll.setWidget(self.rows)
        self.card.add(self.scroll, stretch=1)
        h.addWidget(self.card, stretch=1)
        root.addWidget(body, stretch=1)

        self.status = Note("", color=FG_SECONDARY, size=T_LABEL)
        self.status.setContentsMargins(28, 0, 28, 4)
        root.addWidget(self.status)
        self.hintbar = HintBar()
        self.hintbar.set_hints([("↕", "browse"), ("A", "choose"), ("B", "back")])
        root.addWidget(self.hintbar)

    @staticmethod
    def _maintainer():
        return config.save_edits_to == "mod" or config.developper_mode

    # ── content ──────────────────────────────────────────────────────────
    def on_show(self):
        super().on_show()
        self.reload()

    def _name(self, kind, rid):
        env = self.edits.get(kind, rid)
        record = (env["mine"] if env and env["mine"] is not None else
                  (env["base"] if env else None)) or {}
        if kind == "players":
            return record.get("display_name") or rid
        latest = record.get(sorted(record)[-1]) if record else {}
        return (latest or {}).get("name") or rid

    def reload(self, keep=None):
        items, keys = [], []
        order = {"conflict": 0, "new": 1, "edited": 2, "deleted": 3}
        rows = []
        for kind in KINDS:
            for rid in self.edits.envelopes[kind]:
                status = self.edits.status(kind, rid)
                rows.append((order[status], kind, self._name(kind, rid).lower(), rid, status))
        for _o, kind, _n, rid, status in sorted(rows):
            tag, colour = STATUS[status]
            label = ("team · " if kind == "teams" else "") + self._name(kind, rid)
            items.append(((kind, rid), label, tag, colour, status == "deleted"))
            keys.append(rid)
        self.list.set_items(items, keep_data=keep or self.current, search_text=keys)
        conflicts = len(self.edits.conflicts)
        n = self.edits.count()
        on = self.edits.enabled
        self.enabled_field.set_value("on" if on else "off")
        self.summary.setText(
            (f"{n} record{'s' if n != 1 else ''} edited" if n else "No edits yet")
            + (f" · {conflicts} with conflicts to settle" if conflicts else "")
            + ("" if on else " · TURNED OFF"))
        self.export_btn.setEnabled(bool(n))
        if self.promote_btn is not None:
            self.promote_btn.setEnabled(bool(n))
        if not items or self.current is None:
            self.current = None
            self._show(None)

    def _clear_rows(self):
        while self.rows_v.count():
            item = self.rows_v.takeAt(0)
            w = item.widget()
            if w is not None:
                if w in self.choices.values():
                    self.focus.unregister(w)
                w.setParent(None)
                w.deleteLater()
        self.choices = {}
        self.bulk = "mine"

    def _show(self, key):
        self._clear_rows()
        self.current = key
        self.list.set_selected(key)
        env = self.edits.get(*key) if key else None
        for b in (self.mine_btn, self.theirs_btn, self.apply_btn, self.revert_btn, self.open_btn,
                  self.write_btn):
            if b is not None:
                b.setVisible(env is not None)
        if env is None:
            self.title.setText("Nothing selected")
            return
        kind, rid = key
        status = self.edits.status(kind, rid)
        conflicts = self.edits.conflicts.get(key, [])
        self.title.setText(f"{'Team' if kind == 'teams' else 'Player'} {self._name(kind, rid)}"
                           f"  ·  id {rid}")
        for b in (self.mine_btn, self.theirs_btn, self.apply_btn):
            b.setVisible(bool(conflicts))
        self.open_btn.setVisible(env["mine"] is not None)
        if self.write_btn is not None:
            self.write_btn.setVisible(not conflicts)
        if conflicts:
            for c in conflicts[:MAX_ROWS]:
                self._conflict_row(kind, c)
            if len(conflicts) > MAX_ROWS:
                self.rows_v.addWidget(Note(f"… and {len(conflicts) - MAX_ROWS} more: yours are "
                                           "kept unless you TAKE ALL FROM THE RELEASE",
                                           color=FG_TERTIARY))
        else:
            paths = changed_paths(MISSING if env["base"] is None else env["base"],
                                  MISSING if env["mine"] is None else env["mine"])
            if env["base"] is None or env["mine"] is None:
                paths = []
            for path in paths[:MAX_ROWS]:
                self.rows_v.addWidget(Note(
                    f"{path_label(kind, path)}:   {short(get_path(env['base'], path))}   →   "
                    f"{short(get_path(env['mine'], path))}", color=FG_SECONDARY, size=T_LABEL))
            if len(paths) > MAX_ROWS:
                self.rows_v.addWidget(Note(f"… and {len(paths) - MAX_ROWS} more changes",
                                           color=FG_TERTIARY))
        self.rows_v.addStretch(1)

    def _conflict_row(self, kind, c):
        self.rows_v.addWidget(Note(
            f"{path_label(kind, c.path)}\n   release: {short(c.theirs)}\n   yours:    "
            f"{short(c.mine)}\n   (before: {short(c.base)})", color=FG_SECONDARY, size=T_LABEL))
        field = SegmentField("Keep", ["mine", "theirs"],
                             display=lambda v: "yours" if v == "mine" else "release")
        field.set_value("mine")
        field.setMaximumWidth(460)
        self.focus.register(field)
        self.rows_v.addWidget(field)
        self.choices[c.path] = field

    # ── actions ──────────────────────────────────────────────────────────
    def _say(self, text, colour=FG_SECONDARY):
        self.status.setStyleSheet(f"color: {colour}; background: transparent;"
                                  f" font-family: '{FONT_BODY}'; font-size: {T_LABEL}pt;")
        self.status.setText(text)

    def _toggle_enabled(self, value):
        on = value == "on"
        if on == self.edits.enabled:
            return
        self.ds.set_edits_enabled(on)
        n = self.edits.count()
        #self._say(f"Your edits are used again ({n} record{'s' if n != 1 else ''})" if on else
        #          "Your edits are turned off: the data pack alone is used. They are kept.",
        #          GREEN if on else WARN)
        self.reload(keep=self.current)
        #self._show(self.current if self.current and self.edits.get(*self.current) else None)

    def _set_all(self, choice):
        """Set every choice (rows and the ones past MAX_ROWS); APPLY saves."""
        for f in self.choices.values():
            f.set_value(choice)
        self.bulk = choice
        self._say(f"Every conflict set to {'yours' if choice == 'mine' else 'the release'}"
                  " — APPLY MY CHOICES to save.")

    def _apply(self):
        if not self.current:
            return
        kind, rid = self.current
        conflicts = self.edits.conflicts.get(self.current, [])
        choices = {c.path: (self.choices[c.path].value() if c.path in self.choices
                            else self.bulk) for c in conflicts}
        try:
            self.edits.resolve(kind, rid, choices)
        except OSError as e:
            self._say(f"Could not save: {e}", DANGER_LITE)
            return
        self.ds.refresh_record(kind, rid)
        self._say(f"Settled {len(choices)} conflict(s) of {self._name(kind, rid)}")
        self.reload(keep=self.current)
        self._show(self.current if self.edits.get(kind, rid) else None)

    def _revert(self):
        if not self.current:
            return
        kind, rid = self.current
        env = self.edits.get(kind, rid)
        name = self._name(kind, rid)
        what = ("It exists only in your edits: it is removed." if env["base"] is None else
                "The data pack's version is used again.")

        def done(role):
            self._dialog = None
            if role != "ok":
                return
            home = env["home"]
            self.edits.revert(kind, rid)
            self.ds.refresh_record(kind, rid, home=home)
            self._say(f"Deleted your edit of {name}")
            self.current = None
            self.reload()
        self._dialog = ConfirmDialog(self, f"Delete your edit of {name}?", what,
                                     [("CANCEL", "neutral", "cancel"),
                                      ("DELETE", "danger", "ok")], done)

    def _open(self):
        if not self.current:
            return
        kind, rid = self.current
        if kind == "teams" and self.open_team_cb and rid in self.ds.teams:
            self.open_team_cb(rid)
        elif kind == "players" and self.open_player_cb and rid in self.ds.players:
            self.open_player_cb(rid)

    def _export(self):
        """Into a new folder my_edits_<date> inside the folder picked."""
        parent = os.path.join(user_data_directory(), "exported_edits")
        os.makedirs(parent, exist_ok=True)
        parent = QFileDialog.getExistingDirectory(self, "Export my edits into…", parent)
        if not parent:
            return
        folder = os.path.join(parent, f"my_edits_{datetime.now():%Y%m%d-%H%M%S}")
        try:
            records, files = self.edits.export(folder, program_version=APP_VERSION)
        except OSError as e:
            self._say(f"Export failed: {e}", DANGER_LITE)
            return
        self._say(f"Exported {records} record(s) and {files} image file(s) into {folder}", GREEN)

    def _import(self):
        """An edits export: its manifest.json (the folder), or a zip of it."""
        path, _ = QFileDialog.getOpenFileName(self, "Import edits — pick the export's manifest.json",
                                              os.path.join(user_data_directory(), "exported_edits"),
                                              "Edits export (manifest.json *.zip)")
        if not path:
            return
        try:
            out = self.edits.import_bundle(path)
        except (OSError, ValueError, zipfile.BadZipFile) as e:
            self._say(f"Import failed: {e}", DANGER_LITE)
            return
        for kind, rid in out["records"]:
            # the merge with the pack as installed here, as at start-up
            self.edits.conflicts.pop((kind, rid), None)
            self.edits._recheck(kind, rid)
            self.ds.refresh_record(kind, rid)
        text = f"Imported {len(out['records'])} record(s), {out['files']} file(s)"
        if out["skipped"]:
            text += (f"; {len(out['skipped'])} left out (you already edit them: write or drop "
                     "your edit first)")
        if out["file_clashes"]:
            text += f"; {len(out['file_clashes'])} file(s) already present with other content kept"
        self._say(text, GREEN if not out["skipped"] else WARN)
        self.reload()

    def _promote_all(self):
        keys = [(k, rid) for k in KINDS for rid in self.edits.envelopes[k]
                if (k, rid) not in self.edits.conflicts]
        blocked = len(self.edits.conflicts)

        def done(role):
            self._dialog = None
            if role == "ok":
                self._promote(keys)
        self._dialog = ConfirmDialog(
            self, "Write the edits into the data pack?",
            f"{len(keys)} record(s) are written into the data pack files and leave My edits."
            + (f" {blocked} with conflicts are left out: settle them first." if blocked else ""),
            [("CANCEL", "neutral", "cancel"), ("WRITE", "primary", "ok")], done)

    def _promote(self, keys):
        keys = [k for k in keys if k and k not in self.edits.conflicts]
        try:
            written = self.ds.promote_edits(keys)
        except G.SaveError as e:
            self._say(f"Writing into the data pack failed: {e}", DANGER_LITE)
            self.reload()
            return
        self._say(f"Wrote {written} record(s) into the data pack", GREEN)
        self.current = None
        self.reload()

    def keyPressEvent(self, event):
        if self._dialog is not None:
            return
        action = KEYMAP.get(event.key())
        if action == Action.CONFIRM and QApplication.focusWidget() is self.list:
            self._show(self.list.highlighted_data())
            event.accept()
            return
        super().keyPressEvent(event)
