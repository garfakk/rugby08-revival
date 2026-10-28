"""
app/display.py — what the screen the app runs on suggests
===========================================================
The game resolution and screen ratio matching the primary screen: picked at
the first launch (main.MainWindow) and what Settings > Display resets to.
"""
from PyQt5.QtWidgets import QApplication

from shared.game_profile import resolution_choices
from shared.user_prefs import nearest_screen_ratio


def screen_pixels():
    """The primary screen's size in physical pixels."""
    screen = QApplication.primaryScreen()
    ratio = screen.devicePixelRatio()
    return round(screen.size().width() * ratio), round(screen.size().height() * ratio)


def native_resolution():
    """The screen's own resolution, or the closest one offered."""
    return resolution_choices(*screen_pixels())[1]


def native_screen_ratio():
    """The Screen Ratio preset closest to the screen's shape."""
    return nearest_screen_ratio(*screen_pixels())
