"""Screen ratio: the picture ratio kept inside the window, the black-bar
rectangle, and the Settings rows that set them."""
import pytest

from shared.user_prefs import user_prefs
from screens.ingame import fit_rect

pytestmark = pytest.mark.qt


@pytest.mark.parametrize("widescreen,aspect,expected", [
    (False, "auto", 4 / 3),               # stock game: 4:3
    (True, "4:3", 4 / 3),
    (True, "16:10", 1.6),
    (True, "21:9", 21 / 9),
    (True, "1.7777778", 1.7777778),
    (True, "auto", None),                 # follows the window: nothing to keep
])
def test_picture_ratio(monkeypatch, widescreen, aspect, expected):
    monkeypatch.setattr(user_prefs, "widescreen", widescreen)
    monkeypatch.setattr(user_prefs, "widescreen_aspect", aspect)
    assert user_prefs.picture_ratio() == (pytest.approx(expected) if expected else None)


def test_fit_rect():
    assert fit_rect(0, 0, 1920, 1080, None) == (0, 0, 1920, 1080)
    assert fit_rect(0, 0, 1920, 1080, 4 / 3) == (240, 0, 1440, 1080)          # pillarbox
    assert fit_rect(0, 0, 1920, 1200, 16 / 9) == (0, 60, 1920, 1080)          # letterbox
    assert fit_rect(100, 50, 2520, 1080, 21 / 9) == (100, 50, 2520, 1080)     # already that ratio
    assert fit_rect(1920, 0, 1920, 1080, 4 / 3) == (2160, 0, 1440, 1080)      # second monitor
