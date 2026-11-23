"""backend.game_files_processor.slot_team_names: the names written for the
match's two team slots never equal a stock team's that the game would find
first by name (empty player statistics in the pause menu)."""
from backend.game_files_processor import slot_team_names


def _names(home, away):
    return slot_team_names({"team_A": {"name": home}, "team_B": {"name": away}})


def test_plain_names_are_left_alone():
    assert _names("Bordeaux", "Toulon") == {"team_A": "Bordeaux", "team_B": "Toulon"}
    # stock teams after the slots never come first
    assert _names("Leinster", "Crusaders") == {"team_A": "Leinster", "team_B": "Crusaders"}


def test_a_stock_name_gets_a_trailing_space():
    assert _names("England", "france") == {"team_A": "England ", "team_B": "france "}
    # Perpignan (57) sits after the away slot (56) but before the home one (59)
    assert _names("Perpignan", "Perpignan2") == {"team_A": "Perpignan ", "team_B": "Perpignan2"}
    assert _names("Bath", "Perpignan") == {"team_A": "Bath ", "team_B": "Perpignan"}


def test_both_sides_with_one_name_stay_apart():
    names = _names("Toulon", "Toulon")
    assert names["team_B"] == "Toulon" and names["team_A"] == "Toulon "
    names = _names("Wales", "Wales")
    assert names == {"team_A": "Wales  ", "team_B": "Wales "}
