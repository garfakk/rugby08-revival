"""
ui — Design system package
===========================
Import from here for clean usage in screens:

    from ui import (
        APP_STYLESHEET,
        make_page_header, make_app_title_header, make_footer,
        make_label, make_separator, make_group,
        StyledButton, style_button, style_panel,
        HoverComboBox, ToggleRow, CycleRow, ChoiceRow, SliderRow, KitPreviewBox,
    )
    from ui.theme import ACCENT, BTN_HEIGHT   # direct token access
"""

from ui.stylesheet import APP_STYLESHEET
from ui.loading_pitch import PitchProgressBar
from ui.widgets import (
    # Button helpers
    style_button,
    StyledButton,
    BUTTON_VARIANTS,
    # Label factories
    make_label,
    # Layout building blocks
    make_page_header,
    make_app_title_header,
    make_footer,
    make_separator,
    make_group,
    style_panel,
    # Custom widget classes
    HoverComboBox,
    ToggleRow,
    CycleRow,
    ChoiceRow,
    SliderRow,
    KitPreviewBox,
)

__all__ = [
    "APP_STYLESHEET",
    "style_button",
    "StyledButton",
    "BUTTON_VARIANTS",
    "make_label",
    "make_page_header",
    "make_app_title_header",
    "make_footer",
    "make_separator",
    "make_group",
    "style_panel",
    "HoverComboBox",
    "ToggleRow",
    "CycleRow",
    "ChoiceRow",
    "SliderRow",
    "KitPreviewBox",
    "PitchProgressBar",
]
