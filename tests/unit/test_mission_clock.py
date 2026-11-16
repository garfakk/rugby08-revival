"""<MODE time period> stays consistent: a clock past its period's end, or a
late start with the period left blank, freezes extra time at 80:00."""
import pytest

from backend.game_files_processor import mission_mode_clock as clock


@pytest.mark.parametrize("time_, period, expected", [
    (None, None, ("", "")),
    (None, 0, ("", "0")),
    (4680, 1, ("4680", "1")),
    (4680, None, ("4680", "1")),       # blank period would be the 1st half: snaps to 40:00
    (4680, 0, ("4680", "1")),          # too early a period is raised
    (2400, None, ("2400", "0")),       # an exact end belongs to the half it closes
    (1200, 1, ("1200", "1")),          # explicit later period kept
    (4800, 1, ("4800", "1")),
    (5000, 1, ("5000", "2")),          # past 80:00 = extra time
    (5000, 2, ("5000", "2")),          # extra time kept
    (5700, 2, ("5700", "3")),          # past its period end: next period
    (9999, 2, ("6600", "4")),           # nothing after sudden death: capped
])
def test_mode_clock(time_, period, expected):
    assert clock(time_, period) == expected
