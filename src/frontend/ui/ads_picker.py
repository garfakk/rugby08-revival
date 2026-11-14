"""ui/ads_picker.py — the match-setup stadium ads chooser: a dropdown of ad
sets (app/ad_sets.py) whose open list also loads a set from disk."""
import os

from PyQt5.QtWidgets import QFileDialog

from app import ad_sets
from ui.dropdown import DropdownRow, PopupList

LOAD_FILES, LOAD_FOLDER = "__ads_files__", "__ads_folder__"


class AdsRow(DropdownRow):
    """values are {"label", "path"} dicts; `path` "" is the mod's default set."""

    def __init__(self, label, get_choices, parent=None):
        super().__init__(label, display=lambda o: o["label"], parent=parent)
        self._get_choices = get_choices

    def refresh(self, path=None):
        """Reread the sets and select `path` (the current one when None)."""
        keep = self.current()["path"] if path is None and self.current() else path
        values = self._get_choices(keep)
        index = next((i for i, v in enumerate(values) if v["path"] == keep), 0)
        self.set_values(values, index=index)

    def _open_popup(self):
        screen = self.window()
        popup = PopupList(screen, width=max(300, self.width()), height=360,
                          own_keys=True, show_title=False)
        current = self.current()
        current_i = None
        for i, option in enumerate(self._values):
            popup.add_row(option["label"].upper(), option, selected=(option is current))
            if option is current:
                current_i = i
        popup.add_row("LOAD FROM DISK…", LOAD_FILES, subdued=True)
        popup.add_row("LOAD FOLDER FROM DISK…", LOAD_FOLDER, subdued=True)
        popup.size_to(len(self._values) + 2)
        popup.picked.connect(self._on_picked)
        popup.closed.connect(self._on_popup_closed)
        popup.open_at(self, screen, gap=0, own_toggle=True)
        if current_i is not None:
            popup.set_highlight(current_i, scroll=True)
        self._popup = popup
        self._popup_open = True
        self.update()

    def _on_picked(self, value):
        if value in (LOAD_FILES, LOAD_FOLDER):
            self._load(folder=value == LOAD_FOLDER)
            return
        super()._on_picked(value)

    def _load(self, folder):
        start = getattr(AdsRow, "last_dir", "") or os.path.expanduser("~")
        if folder:
            picked = QFileDialog.getExistingDirectory(self.window(), "Load ads folder", start)
            sources = [picked] if picked else []
        else:
            pattern = " ".join(f"*{e}" for e in ad_sets.EXTS)
            sources, _ = QFileDialog.getOpenFileNames(self.window(), "Load ads", start,
                                                      f"Ads ({pattern})")
        if not sources:
            return
        AdsRow.last_dir = os.path.dirname(os.path.normpath(sources[0]))
        try:
            path = ad_sets.load(sources)
        except OSError:
            path = ""
        if path:
            self.refresh(path)
            self.changed.emit()
