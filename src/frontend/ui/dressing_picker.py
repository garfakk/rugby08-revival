"""ui/dressing_picker.py — the match-setup stadium dressing choosers (pads,
posts, ads; app/dressing.py). Options sit under collapsible headers (stadium,
library, competitions, stock); the open list previews the option under the
cursor: pads and posts on a 3D goal, ads as a strip of boards."""
import os

from PIL import Image
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QFileDialog, QLabel, QVBoxLayout, QWidget

from shared.log import get_logger
from ui.dropdown import DropdownRow, PopupList, _GROUP
from ui.theme import DROPDOWN_BORDER

log = get_logger(__name__)

PREVIEW_H = 190
STRIP_H = 96
LOAD_FILES, LOAD_FOLDER = "__ads_files__", "__ads_folder__"
GROUPS = ("Stadium", "Library", "Competitions", "Stock")


def _group(option):
    if option.get("action"):
        return "Library"
    ref = option.get("ref") or ""
    if not ref:
        return "Stadium"
    if ref.startswith("stock:"):
        return "Stock"
    if ref.startswith("stadiums/"):
        return "Library"
    return "Competitions"


def _pixmap(image):
    image = image.convert("RGBA")
    q = QImage(image.tobytes(), image.width, image.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(q.copy())


class DressingRow(DropdownRow):
    """values are {"label", "ref"} option dicts (app/dressing.choices).
    `preview(option)` gives what to show for one: {tag: image} for a 3D
    goal (kind "pads"/"posts"), a PIL image strip for "ads"."""

    def __init__(self, label, kind, get_choices, preview, parent=None):
        super().__init__(label, display=self._label_of, parent=parent)
        self.kind = kind
        self._get_choices = get_choices
        self._preview = preview
        self.group = _group
        self.group_order = GROUPS

    @staticmethod
    def _label_of(option):
        detail = option.get("detail")
        return f"{option['label']} · {detail}" if detail else option["label"]

    def refresh(self, ref=None):
        """Reread the options and select `ref` (the current one when None)."""
        keep = (self.current() or {}).get("ref", "") if ref is None else ref
        values = self._get_choices(keep)
        if self.kind == "ads":
            values += [{"label": "Load from disk…", "ref": "", "action": LOAD_FILES},
                       {"label": "Load folder from disk…", "ref": "", "action": LOAD_FOLDER}]
        index = next((i for i, v in enumerate(values) if v["ref"] == keep and not v.get("action")), 0)
        self.set_values(values, index=index)

    def current_ref(self):
        return (self.current() or {}).get("ref", "")

    def effective_ref(self, option=None):
        """The set `option` (the current one) stands for: "Stadium default"
        resolves to the stadium's own."""
        option = option or self.current() or {}
        return option.get("ref") or option.get("default_ref", "")

    # ── popup ──────────────────────────────────────────────────────────────
    def _make_preview(self):
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 4)
        if self.kind == "ads":
            view = QLabel()
            view.setAlignment(Qt.AlignCenter)
            view.setFixedHeight(STRIP_H + 8)
            holder.setFixedHeight(STRIP_H + 12)

            def show(option):
                try:
                    strip = self._preview(option)
                except Exception as e:          # a broken set must not break the list
                    log.warning(f"ads preview: {e}")
                    strip = None
                view.setPixmap(_pixmap(strip) if strip is not None else QPixmap())
        else:
            from ui.posts_view import PostsView     # GL stack only when opened
            view = PostsView()
            holder.setFixedHeight(PREVIEW_H)

            def show(option):
                try:
                    view.show_images(self._preview(option))
                except Exception as e:
                    log.warning(f"{self.kind} preview: {e}")
        v.addWidget(view)
        return holder, show

    def _open_popup(self):
        if not self._values:
            return
        screen = self.window()
        extra = STRIP_H + 12 if self.kind == "ads" else PREVIEW_H
        popup = PopupList(screen, width=max(340, self.width()), height=380 + extra,
                          own_keys=True, show_title=False, list_bg=DROPDOWN_BORDER)
        holder, show = self._make_preview()
        popup.set_toolbar_widget(holder)
        current = self.current()
        self._fill_grouped(popup, current)
        popup.hovered.connect(lambda option: show(option)
                              if isinstance(option, dict) and not option.get("action") else None)
        popup.picked.connect(self._on_picked)
        popup.closed.connect(self._on_popup_closed)
        popup.open_at(self, screen, gap=0, own_toggle=True)
        current_i = next((i for i, r in enumerate(popup._rows) if r.data is current), None)
        if current_i is not None:
            popup.set_highlight(current_i, scroll=True)
        if current is not None:
            show(current)
        self._popup = popup
        self._popup_open = True
        self.update()

    def _on_picked(self, value):
        if isinstance(value, tuple) and value and value[0] == _GROUP:
            return
        if isinstance(value, dict) and value.get("action"):
            self._load(folder=value["action"] == LOAD_FOLDER)
            return
        super()._on_picked(value)

    def _load(self, folder):
        from app import dressing
        start = getattr(DressingRow, "last_dir", "") or os.path.expanduser("~")
        if folder:
            picked = QFileDialog.getExistingDirectory(self.window(), "Load ads folder", start)
            sources = [picked] if picked else []
        else:
            from backend.adboards import IMAGE_EXTS
            pattern = " ".join(f"*{e}" for e in (".fsh",) + IMAGE_EXTS)
            sources, _ = QFileDialog.getOpenFileNames(self.window(), "Load ads", start,
                                                      f"Ads ({pattern})")
        if not sources:
            return
        DressingRow.last_dir = os.path.dirname(os.path.normpath(sources[0]))
        try:
            ref = dressing.load_ads(sources)
        except OSError:
            ref = ""
        if ref:
            self.refresh(ref)
            self.changed.emit()


def ads_strip(ref, height=STRIP_H, boards=4):
    """A preview strip (PIL) of the first `boards` ad sheets of set `ref`."""
    from backend import adboards
    ad_set = adboards.load_ref(ref) if ref else None
    if ad_set is None:
        return None
    images = [b.image().convert("RGBA") for b in ad_set.sheets[:boards]]
    if not images:
        return None
    scaled = [im.resize((max(1, round(im.width * height / im.height)), height), Image.LANCZOS)
              for im in images]
    gap = 6
    out = Image.new("RGBA", (sum(i.width for i in scaled) + gap * (len(scaled) - 1), height), (0, 0, 0, 0))
    x = 0
    for im in scaled:
        out.paste(im, (x, 0))
        x += im.width + gap
    return out
