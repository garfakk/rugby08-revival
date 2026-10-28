"""Screen ratio: the picture ratio kept inside the window, the black-bar
rectangle, and the Settings rows that set them."""
import pytest

from shared.user_prefs import user_prefs, nearest_screen_ratio
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


@pytest.mark.parametrize("size,expected", [
    ((1024, 768), "4:3"),
    ((1280, 1024), "4:3"),                # 5:4: closest is 4:3
    ((1920, 1200), "16:10"),
    ((2880, 1800), "16:10"),
    ((1920, 1080), "16:9"),
    ((1366, 768), "16:9"),
    ((2560, 1080), "21:9"),
    ((3440, 1440), "21:9"),
    ((5120, 1440), "21:9"),               # 32:9: the widest preset
    ((0, 0), "4:3"),                      # unknown screen
])
def test_nearest_screen_ratio(size, expected):
    assert nearest_screen_ratio(*size) == expected


@pytest.mark.parametrize("label,widescreen,picture", [
    ("4:3", False, 4 / 3),
    ("16:9", True, 16 / 9),
    ("21:9", True, 21 / 9),
    ("Auto", True, None),
])
def test_set_screen_ratio(monkeypatch, label, widescreen, picture):
    monkeypatch.setattr(user_prefs, "save", lambda: None)
    for attr in ("widescreen", "widescreen_aspect", "screen_ratio_set"):
        monkeypatch.setattr(user_prefs, attr, getattr(user_prefs, attr))
    user_prefs.screen_ratio_set = False
    user_prefs.set_screen_ratio(label)
    assert user_prefs.screen_ratio_set
    assert user_prefs.widescreen is widescreen
    assert user_prefs.screen_ratio_label() == label
    assert user_prefs.picture_ratio() == (pytest.approx(picture) if picture else None)


def test_unset_ratio_not_saved(monkeypatch, tmp_path):
    """Until a ratio is chosen it stays out of user_prefs.ini, so a save of
    any other preference doesn't stop the first-launch detection."""
    import configparser
    import shared.user_prefs as prefs_module
    prefs_file = tmp_path / "user_prefs.ini"
    monkeypatch.setattr(prefs_module, "_PREFS_FILE", str(prefs_file))
    prefs = prefs_module.UserPrefs()
    assert not prefs.screen_ratio_set
    prefs.save()
    cp = configparser.ConfigParser()
    cp.read(prefs_file)
    assert not cp.has_option("prefs", "widescreen_aspect")
    assert not prefs_module.UserPrefs().screen_ratio_set
    prefs.set_screen_ratio("16:10")
    reloaded = prefs_module.UserPrefs()
    assert reloaded.screen_ratio_set and reloaded.screen_ratio_label() == "16:10"
