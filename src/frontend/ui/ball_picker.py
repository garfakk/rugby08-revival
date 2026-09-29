"""ui/ball_picker.py — the match-setup ball chooser: a dropdown whose open list
carries a spinning 3D preview of the ball under the cursor."""
from PyQt5.QtWidgets import QWidget, QVBoxLayout

from ui.dropdown import DropdownRow, PopupList
from ui.theme import DROPDOWN_BORDER

PREVIEW_H = 170


class BallRow(DropdownRow):
    """values are option dicts (see app/ball_options.py); `frames(option)` gives
    the image paths to preview for one."""

    def __init__(self, label, frames, parent=None):
        super().__init__(label, display=lambda o: o["label"], parent=parent)
        self._frames = frames

    def _open_popup(self):
        if not self._values:
            return
        from ui.ball_view import BallView      # GL stack only when actually opened
        screen = self.window()
        popup = PopupList(screen, width=max(300, self.width()), height=360 + PREVIEW_H,
                          own_keys=True, show_title=False, list_bg=DROPDOWN_BORDER)
        holder = QWidget()
        holder.setFixedHeight(PREVIEW_H)
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 4)
        view = BallView()
        v.addWidget(view)
        popup.set_toolbar_widget(holder)

        current = self.current()
        current_i = None
        for i, option in enumerate(self._values):
            popup.add_row(option["label"].upper(), option, selected=(option is current))
            if option is current:
                current_i = i
        popup.size_to(len(self._values))
        popup.hovered.connect(lambda option: view.show_paths(self._frames(option)))
        popup.picked.connect(self._on_picked)
        popup.open_at(self, screen, gap=0, own_toggle=True)
        if current_i is not None:
            popup.set_highlight(current_i, scroll=True)
        else:
            view.show_paths(self._frames(current))
        self._popup = popup
