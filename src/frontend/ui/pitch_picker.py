"""ui/pitch_picker.py — the match-setup pitch conditions chooser
=================================================================
A dropdown of the pitches a match may use (named by condition: dry, hard 2,
muddy...); the open list shows the pitch under the cursor in 3D, the grass of
that pitch texture seen from pitch level (drag to turn, wheel to zoom)."""
from PyQt5.QtWidgets import QVBoxLayout, QWidget

from shared.log import get_logger
from ui.dropdown import DropdownRow, PopupList
from ui.theme import DROPDOWN_BORDER

log = get_logger(__name__)

PREVIEW_H = 220
# pitch level, a little across the grass: its texture fills the picture
VIEW = (-35.0, 40.0, 1100.0, (0.0, 0.0, -300.0))


def _own_text(option):
    return "The stadium's own pitch"


class PitchView:
    """A StadiumView without a stadium: only the pitch laid on grass."""

    def __new__(cls, parent=None):
        from ui.stadium_view import StadiumView
        view = StadiumView(parent)
        view.renderer.bare = True
        view.setMinimumSize(100, 100)
        r = view.renderer
        r.yaw, r.pitch, r.dist = VIEW[:3]
        r.target[:] = VIEW[3]
        view.view_name = ""
        view.set_scene(type("Bare", (), {"parts": [], "textures": {}})())
        return view


class PitchRow(DropdownRow):
    """values are (pitch name, label); "default" = the stadium's own."""

    def __init__(self, label, parent=None):
        super().__init__(label, display=lambda t: t[1], parent=parent)

    def _make_preview(self):
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 4)
        view = PitchView()
        holder.setFixedHeight(PREVIEW_H)
        v.addWidget(view)

        def show(option):
            from backend import pitches
            name = option[0] if option else "default"
            if name == "default" and len(option) > 2 and option[2]:
                name = option[2]                      # the stadium's default pitch
            try:
                scene = pitches.scene(name) if name != "default" else None
                view.set_message("" if scene is not None else
                                 (_own_text(option) if name == "default" else "Pitch not found"))
                view.set_pitch(scene)
            except Exception as e:              # a broken pack must not break the list
                log.warning(f"pitch preview {name}: {e}")
        return holder, show

    def _open_popup(self):
        if not self._values:
            return
        screen = self.window()
        popup = PopupList(screen, width=max(340, self.width()), height=300 + PREVIEW_H,
                          own_keys=True, show_title=False, list_bg=DROPDOWN_BORDER)
        holder, show = self._make_preview()
        popup.set_toolbar_widget(holder)
        current = self.current()
        for v in self._values:
            popup.add_row(self._display(v).upper(), v, selected=(v == current))
        popup.size_to(len(self._values))
        popup.hovered.connect(lambda option: show(option) if isinstance(option, tuple) else None)
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
