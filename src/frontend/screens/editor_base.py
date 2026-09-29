"""
screens/editor_base.py — behaviour shared by the team and player editors
==========================================================================
Layout comes from ui/editor_kit.EditorShell; this owns what the two editors
do the same way:

  * one EditSession per open record — every edit, undo, the "● N unsaved"
    count and the refresh go through it;
  * a field registry, so an issue can be shown on its field and `reveal(key)`
    can switch season/tab, focus and flash it;
  * the unsaved-changes guard (Save / Discard / Cancel) for every way of
    leaving a record, where Discard really reverts;
  * keys: mouse/keyboard shortcuts (Ctrl+S/Z/Y/F/N/D) plus the pad-style
    action layer, with an explicit order so a text edit, an open dialog or a
    popup always gets the keyboard before the screen does.
"""
from PyQt5.QtWidgets import QApplication, QLineEdit, QShortcut, QVBoxLayout, QHBoxLayout
from PyQt5.QtGui import QKeySequence
from PyQt5.QtCore import Qt, QTimer

from app.screen_base import Screen
from app.input import Action, KEYMAP
from app.edit_session import EditSession
from ui.dropdown import PopupList
from ui.editor_kit import (
    EditorShell, ConfirmDialog, FormDialog, FieldBase, TextField, NumberField, ChoiceField,
    FieldGrid, Note,
    open_issues_popover, worst,
    SEVERITY_COLOR, compact_button,
)
from ui.form import SearchList
from ui.widgets import StyledButton
from ui.theme import GREEN, DANGER_LITE, WARN, FG_SECONDARY, FG_TERTIARY, BTN_HEIGHT_SM


class EditorScreen(Screen):
    TAB_TITLES = []
    RECORD_NOUN = "record"
    LIST_PLACEHOLDER = "filter"
    MID_PANE = False          # a screen sets this to add EditorShell's optional mid pane
    COMPACT_HEADER = False    # a screen with no per-record header content sets this
    IDENTITY_PANE = False     # a screen sets this to add EditorShell's optional identity strip
    PREVIEW_PANE = False      # a screen sets this to add EditorShell's optional preview pane

    def __init__(self, ds, on_back):
        super().__init__(on_back=on_back)
        self.ds = ds
        self.session = None
        self.record_id = None
        self.fields = {}          # key -> (tab_index, widget)
        self.issues = []          # [(key, message, severity)]
        self._dialog = None
        self._refresh_pending = False

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        self.shell = EditorShell(self.TAB_TITLES, mid_pane=self.MID_PANE,
                                 compact_header=self.COMPACT_HEADER,
                                 identity_pane=self.IDENTITY_PANE,
                                 preview_pane=self.PREVIEW_PANE)
        root.addWidget(self.shell)

        self._build_list_pane()
        self.shell.header.back_clicked.connect(self.request_leave)
        self.shell.header.issues_clicked.connect(self.open_issues)
        self.shell.footer.save_clicked.connect(self.save)
        self.shell.footer.revert_clicked.connect(self.confirm_revert)
        self.shell.tabs.changed.connect(self._on_tab_changed)
        self.focus.register(self.shell.tabs)

        for seq, slot in (("Ctrl+S", self.save), ("Ctrl+Z", self.undo),
                          ("Ctrl+Shift+Z", self.redo), ("Ctrl+Y", self.redo),
                          ("Ctrl+F", self.focus_filter), ("Ctrl+N", self.new_record),
                          ("Ctrl+D", self.duplicate_record),
                          ("Ctrl+PgUp", lambda: self.switch_tab(-1)),
                          ("Ctrl+PgDown", lambda: self.switch_tab(1))):
            sc = QShortcut(QKeySequence(seq), self)
            sc.setContext(Qt.WidgetWithChildrenShortcut)
            sc.activated.connect(lambda s=slot: None if self._dialog else s())

        QApplication.instance().focusChanged.connect(self._on_focus_changed)

    # ── list pane ────────────────────────────────────────────────────────
    def _build_list_pane(self):
        lay = self.shell.list_layout
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.new_btn = compact_button("+ NEW")
        self.new_btn.clicked.connect(self.new_record)
        self.dup_btn = compact_button("DUPLICATE")
        self.dup_btn.clicked.connect(self.duplicate_record)
        bar.addWidget(self.new_btn)
        bar.addWidget(self.dup_btn)
        self.tools_btn = compact_button("MORE ▾")
        self.tools_btn.clicked.connect(self.open_bulk_menu)
        bar.addWidget(self.tools_btn)
        lay.addLayout(bar)

        # Show/group/sort stay collapsed by default — a filter box below
        # (typed narrowing, always visible) covers most browsing, and the
        # three of these together took as much vertical room as the list
        # itself on a short list. FILTERS ▾ reveals them for the rest.
        self.filters_toggle = compact_button("FILTERS ▾")
        self.filters_toggle.clicked.connect(self._toggle_filters)
        lay.addWidget(self.filters_toggle)

        self._filters_panel = FieldGrid(columns=1, v_spacing=4)
        self.show_filter = ChoiceField("Show", ["issues", "errors"], allow_blank=True,
                                       blank_label="all", display=lambda v: {
                                           "issues": "with issues", "errors": "with errors"}.get(v, v))
        self.show_filter.label_width = 60
        self.group_filter = ChoiceField(self.GROUP_LABEL, allow_blank=True, blank_label="all")
        self.group_filter.label_width = 60
        self.sort_choice = ChoiceField("Sort", [k for k, _ in self.SORTS], allow_blank=False,
                                       display=lambda v: dict(self.SORTS).get(v, v))
        self.sort_choice.label_width = 60
        self.sort_choice.set_value(self.SORTS[0][0])
        for f in (self.show_filter, self.group_filter, self.sort_choice):
            f.edited.connect(lambda _v: self.reload_list())
            self._filters_panel.add(f)
        lay.addWidget(self._filters_panel)
        self._filters_panel.hide()

        self.list = SearchList(self.LIST_PLACEHOLDER)
        self.list.activated.connect(self.request_open)
        lay.addWidget(self.list, stretch=1)
        self.count_note = Note("", color=FG_TERTIARY)
        lay.addWidget(self.count_note)
        for w in (self.new_btn, self.dup_btn, self.tools_btn, self.filters_toggle, self.show_filter,
                  self.group_filter, self.sort_choice, self.list):
            self.focus.register(w)

    GROUP_LABEL = "Group"
    SORTS = [("name", "name"), ("issues", "most issues")]

    def list_rows(self):
        """[{id, text, tag, color, search, errors, issues, group, sort:{key: value}}]"""
        return []

    def list_items(self):
        rows = self.list_rows()
        groups = sorted({r.get("group") for r in rows if r.get("group")})
        self.group_filter.set_options(groups)
        if self.group_filter.value() and self.group_filter.value() not in groups:
            self.group_filter.set_value("")
        show = self.show_filter.value()
        group = self.group_filter.value()
        if show == "issues":
            rows = [r for r in rows if r.get("issues")]
        elif show == "errors":
            rows = [r for r in rows if r.get("errors")]
        if group:
            rows = [r for r in rows if r.get("group") == group
                    or group in (r.get("groups") or ())]
        sort = self.sort_choice.value() or "name"
        if sort == "name":
            rows.sort(key=lambda r: r["text"].lower())
        elif sort == "issues":
            rows.sort(key=lambda r: (-r.get("errors", 0), -r.get("issues", 0), r["text"].lower()))
        else:
            rows.sort(key=lambda r: (-(r.get("sort", {}).get(sort) or -1), r["text"].lower()))
        self.count_note.setText(f"{len(rows)} shown")
        items = [(r["id"], r["text"], r.get("tag", ""), r.get("color"), False) for r in rows]
        return items, [r.get("search", "") for r in rows]

    def _toggle_filters(self):
        showing = self._filters_panel.isVisible()
        self._filters_panel.setVisible(not showing)
        self.filters_toggle.setText("FILTERS ▴" if not showing else "FILTERS ▾")

    def open_bulk_menu(self):
        actions = self.bulk_actions()
        popup = PopupList(self, width=440, height=300, own_keys=True)
        popup.set_title("more")
        if self.on_import is not None:
            popup.add_row("Import a Rugby 08 roster (.ros / .rdf)…", "__import__",
                          subtitle="teams and players")
        for key, label, count in actions:
            popup.add_row(label, key if count else None, tag=str(count),
                          tag_color=WARN if count else FG_SECONDARY, disabled=not count)
        if not actions:
            popup.add_row("nothing to fix", None, disabled=True)
        popup.size_to(max(1, len(actions) + 1))
        popup.picked.connect(self._on_more_picked)
        popup.open_at(self.tools_btn, self)

    on_import = None

    def _on_more_picked(self, key):
        if key == "__import__":
            self.guard_dirty(self.on_import)
        elif key:
            self.run_bulk_action(key)

    def bulk_actions(self):
        """[(key, label, count)]"""
        return []

    def run_bulk_action(self, key):
        pass

    def reload_list(self):
        items, search = self.list_items()
        self.list.set_items(items, keep_data=self.record_id, search_text=search)
        if self.record_id is not None:
            self.list.set_selected(self.record_id)

    # ── subclass contract ────────────────────────────────────────────────
    def load_record(self, record_id):
        """Return the record (deep-copied by the session) or None."""
        raise NotImplementedError

    def refresh_view(self):
        """Push `self.session.working` into every widget."""

    def collect_issues(self):
        return []

    def write_record(self):
        """Persist `self.session.working`. Return a status string."""
        raise NotImplementedError

    def header_state(self):
        """dict(title, eyebrow, subtitle, chips, pixmap, initials, target)"""
        return {}

    def tab_hints(self, focused):
        return []

    def tab_for_issue(self, key):
        entry = self._field_for_key(key)
        return entry[0] if entry else 0

    def apply_view_hint(self, hint):
        """Bring the season/tab a change belongs to into view."""
        if hint and hint.get("tab") is not None:
            self.shell.tabs.set_index(hint["tab"])

    def new_record(self):
        pass

    def duplicate_record(self):
        pass

    # ── fields / issues ──────────────────────────────────────────────────
    def register_field(self, key, widget, tab):
        widget.key = key
        self.fields[key] = (tab, widget)
        self.focus.register(widget)
        return widget

    def _field_for_key(self, key):
        if key in self.fields:
            return self.fields[key]
        parts = key.split(".")
        while len(parts) > 1:
            parts = parts[:-1]
            k = ".".join(parts)
            if k in self.fields:
                return self.fields[k]
        return None

    def apply_issues(self):
        per_field = {}
        for key, msg, sev in self.issues:
            entry = self._field_for_key(key)
            if entry:
                per_field.setdefault(id(entry[1]), (entry[1], []))[1].append((sev, msg))
        for _, (tab, w) in self.fields.items():
            if isinstance(w, FieldBase):
                found = per_field.get(id(w))
                if found:
                    sev = worst(s for s, _ in found[1])
                    msg = "\n".join(m for _, m in found[1])
                    w.set_issue(sev, msg)
                elif w.issue():
                    w.set_issue(None)
        counts = {}
        for key, msg, sev in self.issues:
            tab = self.tab_for_issue(key)
            counts.setdefault(tab, []).append(sev)
        for i in range(len(self.TAB_TITLES)):
            sevs = counts.get(i, [])
            self.shell.tabs.set_count(i, len(sevs), worst(sevs))
        self.shell.header.set_issues(self.issues)

    def reveal(self, key):
        entry = self._field_for_key(key)
        tab = entry[0] if entry else self.tab_for_issue(key)
        self.shell.tabs.set_index(tab)
        if entry:
            w = entry[1]
            QTimer.singleShot(0, lambda: self._focus_and_flash(w))

    def _focus_and_flash(self, w):
        page = self.shell.page(self.shell.tabs.index())
        if page.isAncestorOf(w):
            page.ensureWidgetVisible(w, 0, 80)
        w.setFocus()
        if hasattr(w, "flash"):
            w.flash()

    def open_issues(self):
        open_issues_popover(self, self.shell.header.issues_btn, self.issues, self.reveal)

    # ── session / refresh ────────────────────────────────────────────────
    def open_record(self, record_id):
        record = self.load_record(record_id)
        if record is None:
            return False
        if self.session is not None:
            self.session.changed.disconnect(self._on_session_changed)
            self.session.deleteLater()
        self.record_id = record_id
        self.session = EditSession(record, self)
        self.session.changed.connect(self._on_session_changed)
        self.list.set_selected(record_id, scroll=True)
        self.on_record_opened()
        self.refresh_all()
        return True

    def on_record_opened(self):
        pass

    def edit(self, label, mutate, coalesce_key=None, view_hint=None):
        if self.session is None:
            return False
        if view_hint is None:
            view_hint = self.current_view_hint()
        return self.session.apply(label, mutate, coalesce_key, view_hint)

    def current_view_hint(self):
        return {"tab": self.shell.tabs.index()}

    def _on_session_changed(self, label, hint):
        if label.startswith(("undo", "redo")):
            self.apply_view_hint(hint)
        self.schedule_refresh()

    def schedule_refresh(self):
        if not self._refresh_pending:
            self._refresh_pending = True
            QTimer.singleShot(0, self.refresh_all)

    def refresh_all(self):
        self._refresh_pending = False
        if self.session is None:
            self.issues = []
            self.apply_issues()
            self._refresh_chrome()
            return
        self.refresh_view()
        self.issues = self.collect_issues()
        self.apply_issues()
        self._refresh_chrome()

    def _refresh_chrome(self):
        head = self.header_state() if self.session else {}
        h = self.shell.header
        h.title.setText(head.get("title", "—"))
        h.eyebrow.setText(head.get("eyebrow", "").upper())
        h.subtitle.setText(head.get("subtitle", ""))
        h.set_chips(head.get("chips", []))
        pix = head.get("pixmap")
        if pix is not None and not pix.isNull():
            h.avatar.set_pixmap(pix)
        else:
            h.avatar.set_initials(head.get("initials", "?"))
        n = self.session.change_count() if self.session else 0
        h.set_dirty(n)
        f = self.shell.footer
        f.save_btn.setEnabled(bool(n))
        f.revert_btn.setEnabled(bool(n))
        f.save_btn.setText(f"SAVE  ({n})" if n else "SAVE")
        f.target.setText(head.get("target", ""))
        self.dup_btn.setEnabled(self.session is not None)
        self._update_hints()

    # ── save / revert / undo ─────────────────────────────────────────────
    def save(self):
        if self.session is None or not self.session.is_dirty():
            return True
        try:
            message = self.write_record()
        except Exception as e:     # SaveError and anything unexpected from disk
            self.shell.footer.set_status(f"Save failed: {e}", DANGER_LITE)
            return False
        self.session.mark_saved()
        self.after_save()
        self.reload_list()
        self.refresh_all()
        self.shell.footer.set_status(message or "Saved", GREEN)
        return True

    def after_save(self):
        pass

    def confirm_revert(self):
        if self.session is None or not self.session.is_dirty():
            return
        n = self.session.change_count()
        self.show_dialog(ConfirmDialog(
            self, "Revert all changes?",
            f"{n} unsaved change{'s' if n != 1 else ''} to this {self.RECORD_NOUN} will be lost.",
            [("CANCEL", "neutral", "cancel"), ("REVERT", "danger", "revert")],
            self._on_revert_choice))

    def _on_revert_choice(self, role):
        self._dialog = None
        if role == "revert" and self.session is not None:
            self.session.revert()
            self.shell.footer.set_status("Reverted to the saved file", FG_SECONDARY)

    def undo(self):
        if self.session is not None:
            entry = self.session.undo()
            self.shell.footer.set_status(f"Undid {entry.label}" if entry else "Nothing to undo",
                                         FG_SECONDARY)

    def redo(self):
        if self.session is not None:
            entry = self.session.redo()
            self.shell.footer.set_status(f"Redid {entry.label}" if entry else "Nothing to redo",
                                         FG_SECONDARY)

    # ── leaving a record ─────────────────────────────────────────────────
    def guard_dirty(self, then):
        if self.session is None or not self.session.is_dirty():
            then()
            return
        n = self.session.change_count()

        def choice(role):
            self._dialog = None
            if role == "save":
                if self.save():
                    then()
            elif role == "discard":
                self.session.revert()
                then()
            else:
                self.focus_list_or_content()

        self.show_dialog(ConfirmDialog(
            self, "Unsaved changes",
            f"{n} change{'s' if n != 1 else ''} to this {self.RECORD_NOUN} "
            f"{'have' if n != 1 else 'has'} not been saved.",
            [("CANCEL", "neutral", "cancel"), ("DISCARD", "danger", "discard"),
             ("SAVE", "primary", "save")],
            choice))

    def request_open(self, record_id):
        if record_id == self.record_id:
            return
        previous = self.record_id

        def go():
            self.open_record(record_id)

        if self.session is not None and self.session.is_dirty():
            self.list.set_selected(previous)
        self.guard_dirty(go)

    def request_leave(self):
        self.guard_dirty(lambda: self.on_back_cb() if self.on_back_cb else None)

    def ask_text(self, title, label, default, on_ok, hint=None):
        field = TextField(label)
        field.set_value(default or "")

        def done(role):
            self._dialog = None
            if role == "ok":
                value = field.value().strip()
                if value:
                    on_ok(value)

        self.show_dialog(FormDialog(self, title, hint or "", {"value": field},
                                    [("CANCEL", "neutral", "cancel"), ("OK", "primary", "ok")], done))
        QTimer.singleShot(0, field.begin_edit)

    def ask_number(self, title, label, default, on_ok, lo=0, hi=65535, hint=None):
        field = NumberField(label, lo, hi, allow_blank=False)
        field.set_value(default or "")

        def done(role):
            self._dialog = None
            if role == "ok" and field.value():
                on_ok(field.value())

        self.show_dialog(FormDialog(self, title, hint or "Type the number, then Enter.",
                                    {"value": field},
                                    [("CANCEL", "neutral", "cancel"), ("OK", "primary", "ok")], done))

    def confirm(self, title, text, button, on_ok):
        def done(role):
            self._dialog = None
            if role == "ok":
                on_ok()
        self.show_dialog(ConfirmDialog(self, title, text,
                                       [("CANCEL", "neutral", "cancel"), (button, "danger", "ok")],
                                       done))

    def show_dialog(self, dialog):
        self._dialog = dialog
        self._update_hints()

    def focus_list_or_content(self):
        self.list.setFocus()

    def focus_filter(self):
        self.list.begin_filter()

    # ── tabs / focus / hints ─────────────────────────────────────────────
    def switch_tab(self, delta):
        self.shell.tabs.set_index(self.shell.tabs.index() + delta)

    def _on_tab_changed(self, index):
        self._update_hints()

    def pane(self):
        w = QApplication.focusWidget()
        if w is not None and self.shell.list_pane.isAncestorOf(w):
            return "list"
        return "content"

    def _on_focus_changed(self, old, new):
        if new is not None and self.isAncestorOf(new):
            self._update_hints()
            page = self.shell.page(self.shell.tabs.index())
            if page.isAncestorOf(new) and new is not page.widget():
                page.ensureWidgetVisible(new, 0, 40)

    def _update_hints(self):
        if self._dialog is not None:
            hints = [("↕", "move"), ("A", "choose"), ("B", "cancel")]
        elif self.pane() == "list":
            hints = [("↕", f"browse"), ("A", "open"), ("/", "filter"),
                     ("→", "edit"), ("B", "back")]
        else:
            focused = QApplication.focusWidget()
            hints = self.tab_hints(focused) or [("↕←→", "move"), ("A", "edit")]
            hints = hints + [("Q E", "tabs"), ("B", "list")]
        self.shell.footer.hints.set_hints(hints)

    def on_show(self):
        self.refresh_from_store()
        if self.record_id is None and self.list.count():
            self.list.set_highlight(0)
            first = self.list.highlighted_data()
            if first is not None:
                self.open_record(first)
        self.list.setFocus()
        self._update_hints()

    def refresh_from_store(self):
        """Pick up saves made elsewhere (the other editor) while this screen
        was hidden: rebuild the list and, if nothing is unsaved here, reload
        the open record from the store."""
        self.reload_list()
        if self.record_id is not None and (self.session is None or not self.session.is_dirty()):
            if self.load_record(self.record_id) is None:
                self.record_id = None
                self.session = None
            else:
                self.open_record_keep_view(self.record_id)
        else:
            self.refresh_all()

    def open_record_keep_view(self, record_id):
        tab = self.shell.tabs.index()
        self.open_record(record_id)
        self.shell.tabs.set_index(tab)

    # ── keys ─────────────────────────────────────────────────────────────
    def keyPressEvent(self, event):
        focused = QApplication.focusWidget()
        # 1. a text edit owns the keyboard
        if isinstance(focused, QLineEdit):
            super(Screen, self).keyPressEvent(event)
            return
        # 2. an open dialog or popup (they consume their own keys; anything
        #    that still reaches us must not act on the screen behind them)
        if self._dialog is not None or PopupList.any_open():
            event.accept()
            return
        if isinstance(focused, FieldBase) and focused.is_editing():
            super(Screen, self).keyPressEvent(event)
            return

        action = KEYMAP.get(event.key())
        if event.modifiers() & Qt.ControlModifier:
            super(Screen, self).keyPressEvent(event)
            return

        if action in (Action.TAB_PREV, Action.TAB_NEXT):
            self.switch_tab(-1 if action == Action.TAB_PREV else 1)
            self._focus_first_in_tab()
        elif action == Action.BACK:
            if self.pane() == "content":
                self.list.setFocus()
            else:
                self.request_leave()
        elif action == Action.ADVANCED:
            self.open_issues()
        elif action == Action.ALT and self.alt_action(focused):
            pass
        elif action == Action.AUX and self.aux_action(focused):
            pass
        elif action == Action.NAV_RIGHT and focused is self.list:
            self._focus_first_in_tab()
        elif action in (Action.NAV_UP, Action.NAV_DOWN, Action.NAV_LEFT, Action.NAV_RIGHT):
            self.focus.move(action)
        elif action == Action.CONFIRM:
            super().keyPressEvent(event)
            return
        else:
            super(Screen, self).keyPressEvent(event)
            return
        event.accept()

    def _focus_first_in_tab(self):
        page = self.shell.page(self.shell.tabs.index())
        self.focus.focus_first(within=page)

    def alt_action(self, focused):
        if focused is self.list:
            self.list.begin_filter()
            return True
        if hasattr(focused, "begin_text_edit"):
            focused.begin_text_edit()
            return True
        return False

    def aux_action(self, focused):
        return False
