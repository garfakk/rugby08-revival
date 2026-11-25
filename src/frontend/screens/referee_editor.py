"""
screens/referee_editor.py — Referee editor (Tools, expert mode)
=================================================================
The referees a match can have (app/referees.py): name, head and kit, tried on
the 3D view on the right. Saves go to the user's edits
(user_data/edits/referees.json). Quick match picks one in its expert rows,
a tournament in its settings (one for every match, or one drawn per match).
A match can also put any other kit on him (app/referees.py kits).
"""
import copy
import os

from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QPixmap
from PyQt5.QtWidgets import QSizePolicy

from app import referees as R
from backend import referee as backend_referee
from backend.mod_utils import stock_head_path, stock_portrait_path
from shared.config import config
from shared.log import get_logger
from ui.editor_kit import (LOAD_FILES, ChoiceField, FieldGrid, Note, SectionCard, TextField,
                           compact_button, load_from_disk)
from ui.face_picker import FacePicker
from ui.face_thumbs import face_thumbnail
from ui.theme import ACCENT, FG_SECONDARY, FG_TERTIARY

from .editor_base import EditorScreen

log = get_logger(__name__)

class RefereeEditorScreen(EditorScreen):
    TAB_TITLES = ["Referee"]
    RECORD_NOUN = "referee"
    LIST_PLACEHOLDER = "filter"
    PREVIEW_PANE = True
    SORTS = [("name", "name")]

    def __init__(self, ds, on_back):
        self._stage_key = None
        super().__init__(ds, on_back)
        sh = self.shell
        sh.list_pane.setFixedWidth(240)
        for w in (sh.tabs, sh.stack):
            w.setMaximumWidth(440)
            w.setMinimumWidth(340)
        sh.preview_pane.setMinimumWidth(300)
        sh.preview_pane.setMaximumWidth(16777215)
        sh.preview_pane.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        body = sh.right_layout.parent()
        if body is not None:
            body.setStretchFactor(sh.right_layout, 0)
            body.setStretchFactor(sh.preview_pane, 1)
        self.filters_toggle.hide()
        self.dup_btn.setText("COPY")
        self.del_btn = compact_button("DELETE")
        self.del_btn.clicked.connect(self.delete_record)
        sh.list_layout.itemAt(0).layout().addWidget(self.del_btn)
        self.focus.register(self.del_btn)
        self._build_form()
        self._build_preview()

    # ── layout ───────────────────────────────────────────────────────────
    def _build_form(self):
        page = self.shell.page(0).layout_
        card = SectionCard("Referee")
        grid = FieldGrid(columns=1)
        self.f_name = TextField("name", max_bytes=40)
        self.f_name.edited.connect(self._set_name)
        grid.add(self.f_name)
        self.register_field("name", self.f_name, 0)

        self.f_kit = ChoiceField("kit", allow_blank=False)
        self.f_kit.popup_title = "referee kit"
        self.f_kit.display = self._kit_label
        self.f_kit.off_list_badge = False
        self.f_kit.actions = (LOAD_FILES,)
        self.f_kit.section_for = lambda v: "" if v == LOAD_FILES else (
            "stock" if v in R.STOCK_KITS else "custom")
        self.f_kit.on_hover = lambda v: self.refresh_stage(kit=None if v == LOAD_FILES else v)
        self.f_kit.on_popup_closed = self.refresh_stage
        self.f_kit.edited.connect(self._set_kit)
        grid.add(self.f_kit)
        self.register_field("kit", self.f_kit, 0)
        card.add(grid)

        self.head_btn = compact_button("CHOOSE HEAD…")
        self.head_btn.clicked.connect(self._open_head_picker)
        self.focus.register(self.head_btn)
        card.add(self.head_btn)
        card.add(Note("Custom kit: a 512×512 image laid out like a player's front kit.",
                      color=FG_TERTIARY))
        page.addWidget(card)
        page.addStretch(1)

    def _build_preview(self):
        from ui.player_stage import KitStage
        self.stage = KitStage(default_yaw=15.0)
        self.shell.preview_layout.addWidget(self.stage, stretch=1)

    def borrow_stage(self, new_parent):
        self.shell.preview_layout.removeWidget(self.stage)
        self.stage.setParent(new_parent)
        self.stage.show()
        return self.stage

    def reclaim_stage(self):
        self.stage.setParent(self.shell.preview_pane)
        self.shell.preview_layout.addWidget(self.stage, stretch=1)

    # ── records ──────────────────────────────────────────────────────────
    @property
    def d(self):
        return self.session.working if self.session else {}

    def _all(self):
        refs = getattr(self.ds, "referees", None)
        if refs is None:
            refs = self.ds.referees = R.load()
        return refs

    def list_rows(self):
        pack = R.pack()
        rows = []
        for rid, r in self._all().items():
            name = r["name"] or rid
            tag = "NEW" if rid not in pack else "EDITED" if pack[rid] != r else ""
            rows.append({"id": rid, "text": name, "tag": tag, "color": ACCENT,
                         "search": name, "errors": 0, "issues": 0})
        return rows

    def load_record(self, record_id):
        r = self._all().get(record_id)
        return copy.deepcopy(r) if r else None

    def write_record(self):
        R.save(self.record_id, self.session.working)
        self._reload_store()
        return "Saved in your edits"

    def _reload_store(self):
        self.ds.referees = R.load()

    def collect_issues(self):
        return [("name", "the referee has no name", "warn")] if self.session and not self.d.get("name") else []

    def header_state(self):
        name = self.d.get("name") or str(self.record_id)
        return {"title": name, "eyebrow": "referee", "subtitle": "", "chips": [],
                "pixmap": self._face_pixmap(self.d.get("face")),
                "initials": "".join(w[0] for w in name.split()[:2]).upper() or "R"}

    def _refresh_chrome(self):
        super()._refresh_chrome()
        self.shell.header.issues_btn.setVisible(False)
        self.del_btn.setEnabled(self.session is not None)

    def refresh_view(self):
        self.f_name.set_value(self.d.get("name", ""))
        kits = R.kits()
        if self.d.get("kit") and self.d["kit"] not in kits:
            kits.append(self.d["kit"])
        self.f_kit.set_options(kits + [LOAD_FILES])
        self.f_kit.set_value(self.d.get("kit", "stock:a"))
        self.refresh_stage()

    # ── edits ────────────────────────────────────────────────────────────
    def _set_name(self, value):
        value = str(value or "").strip()
        if self.session is None or value == self.d.get("name"):
            return
        self.edit("name", lambda w: w.__setitem__("name", value))

    def _set_kit(self, value):
        if value == LOAD_FILES:
            self.refresh_view()

            def run():
                rels = load_from_disk(self, config.mod_data_directory, R.KIT_DIR, R.KIT_EXTS)
                if rels:
                    self._set_kit(rels[0])
            QTimer.singleShot(0, run)
            return
        if self.session is None or not value or value == self.d.get("kit"):
            return
        back = R.kit_back(value)          # its <name>_back image, if any

        def apply(w):
            w["kit"], w["kit_back"] = value, back
        self.edit("kit", apply)

    def _set_face(self, value):
        if self.session is None or str(value) == self.d.get("face"):
            return
        self.edit("head", lambda w: w.__setitem__("face", str(value)))

    def _open_head_picker(self):
        if self.session is None:
            return
        picker = FacePicker(self, current=self.d.get("face", ""),
                            on_preview=lambda v: self.refresh_stage(face=v),
                            on_cancel=self.refresh_stage, referees=True)
        picker.picked.connect(self._set_face)

    def new_record(self):
        def go():
            taken = set(self._all())
            rid = R.new_id("new referee", taken)
            R.save(rid, {"name": "New referee", "face": "45000", "kit": "stock:a"})
            self._reload_store()
            self.reload_list()
            self.open_record(rid)
            self.f_name.setFocus()
        self.guard_dirty(go)

    def duplicate_record(self):
        if self.session is None:
            return
        src = copy.deepcopy(self.session.working)

        def go():
            src["name"] = (src["name"] or "Referee") + " (copy)"
            rid = R.new_id(src["name"], set(self._all()))
            R.save(rid, src)
            self._reload_store()
            self.reload_list()
            self.open_record(rid)
        self.guard_dirty(go)

    def delete_record(self):
        if self.record_id is None:
            return
        name = self.d.get("name") or "this referee"

        def go():
            R.delete(self.record_id)
            self.record_id = None
            self.session = None
            self._reload_store()
            self.reload_list()
            if self.list.count():
                self.list.set_highlight(0)
                first = self.list.highlighted_data()
                if first is not None:
                    self.open_record(first)
            self.refresh_all()
            self.shell.footer.set_status("Deleted", FG_SECONDARY)
        self.confirm(f"Delete {name}?", "Matches that had this referee get the game's own.",
                     "DELETE", go)

    # ── preview ──────────────────────────────────────────────────────────
    def _face_pixmap(self, face):
        face = str(face or "")
        if face.isdigit():
            # the stock referees have no menu portrait: their head's own face then
            path = (stock_portrait_path(face, os.path.join(config.temp_directory, "stock_portraits"))
                    or stock_head_path(face, os.path.join(config.temp_directory, "stock_heads")))
        else:
            path = os.path.join(config.mod_data_directory, face) if face else None
        if not path:
            return QPixmap()
        return face_thumbnail(os.path.join(config.temp_directory, "head_thumbs"), path, size=96)

    def _kit_label(self, value):
        if value == LOAD_FILES:
            return "Load from disk…"
        return R.kit_label(value)

    def refresh_stage(self, face=None, kit=None):
        """The 3D view: the referee's head and kit, or a candidate of either
        (the head picker / kit list hovered) without touching the record."""
        if self.session is None:
            self.stage.set_placeholder("NO REFEREE")
            self._stage_key = None
            return
        face = str(face if face is not None else self.d.get("face") or "")
        kit = kit if kit is not None else self.d.get("kit") or "stock:a"
        back = self.d.get("kit_back", "") if kit == self.d.get("kit") else R.kit_back(kit)
        head, front, numbers = backend_referee.preview_files(face, kit, back)
        key = (front, numbers, head)
        if key == self._stage_key:
            return
        self._stage_key = key
        try:
            self.stage.update_kit(None, front, numbers, None, head_path=head or None)
        except Exception as e:
            log.warning(f"referee preview failed: {e}")

    def on_show(self):
        self._stage_key = None
        super().on_show()
