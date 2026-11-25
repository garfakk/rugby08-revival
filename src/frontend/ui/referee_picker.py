"""ui/referee_picker.py — the match-setup referee rows (referee, referee kit):
arrows step through the choices as on any row, and a click opens the list
with the referee under the cursor shown in 3D above it."""
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from shared.log import get_logger
from ui.broadcast import SelectorRow
from ui.theme import DROPDOWN_BORDER

log = get_logger(__name__)

PREVIEW_H = 260


class RefereeRow(SelectorRow):
    """`preview(value)` gives the (head, front, back) files to show for a
    value (backend.referee.preview_files), or None for nothing to show (a
    referee drawn at random)."""

    def __init__(self, label, preview, display=lambda v: v[1], parent=None):
        super().__init__(label, display=display, parent=parent)
        self._preview = preview
        self.set_force_popup(True)

    def _open_popup(self):
        if self._mirror or self._disabled or not self._values or self._free_text is not None:
            return
        from ui.dropdown import PopupList          # deferred: ui.dropdown imports ui.broadcast
        from ui.player_stage import KitStage       # GL stack only when actually opened
        screen = self.window()
        popup = PopupList(screen, width=max(300, self.width()), height=340 + PREVIEW_H,
                          own_keys=True, show_title=False, list_bg=DROPDOWN_BORDER)
        holder = QWidget()
        holder.setFixedHeight(PREVIEW_H)
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 4)
        stage = KitStage(default_yaw=15.0)
        v.addWidget(stage)
        popup.set_toolbar_widget(holder)
        shown = [None]

        def show(value):
            files = self._preview(value) if value is not None else None
            if files == shown[0]:
                return
            shown[0] = files
            if not files or not files[1]:
                stage.set_placeholder("RANDOM" if files is None else "NO PREVIEW")
                stage._show_flat()
                return
            head, front, back = files
            try:
                stage.update_kit(None, front, back, None, head_path=head or None)
            except Exception as e:
                log.warning(f"referee preview failed: {e}")

        current = self.current()
        current_i = None
        for i, value in enumerate(self._values):
            popup.add_row(self._display(value).upper(), value, selected=(value == current))
            if value == current:
                current_i = i
        popup.size_to(len(self._values))
        popup.hovered.connect(show)
        popup.picked.connect(self._on_popup_picked)
        popup.closed.connect(self._on_popup_closed)
        popup.open_at(self, screen, gap=0, own_toggle=True)
        if current_i is not None:
            popup.set_highlight(current_i, scroll=True)
        show(current)
        self._popup = popup
        self._popup_open = True
        self.update()
