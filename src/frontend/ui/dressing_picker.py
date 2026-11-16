"""ui/dressing_picker.py — the match-setup stadium dressing choosers (pads,
posts, ads; app/dressing.py). Two collapsible sections: the sets suggested
for this match (the stadium's own, its teams' competitions') and all the
others; the open list previews the option under the cursor: pads and posts
on a 3D goal, ads as a strip of boards."""
from PIL import Image
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from shared.log import get_logger
from ui.dropdown import DropdownRow, PopupList
from ui.theme import DROPDOWN_BORDER

log = get_logger(__name__)

PREVIEW_H = 190
STRIP_H = 96
SUGGESTED, OTHERS = "Suggested", "All others"
GROUPS = (SUGGESTED, OTHERS)


def _group(option):
    return SUGGESTED if option.get("suggested") else OTHERS


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
        self.group_open = (SUGGESTED,)

    @staticmethod
    def _label_of(option):
        detail = option.get("detail")
        return f"{option['label']} · {detail}" if detail else option["label"]

    def refresh(self, ref=None):
        """Reread the options and select `ref` (the current one when None)."""
        keep = (self.current() or {}).get("ref", "") if ref is None else ref
        values = self._get_choices(keep)
        index = next((i for i, v in enumerate(values) if v["ref"] == keep), 0)
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
        popup.hovered.connect(lambda option: show(option) if isinstance(option, dict) else None)
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
