"""Star indicator hidden (player key hide_star): no star over the head in
game and no star marking the player in the mod's lists either."""
from ui.team_sheet import is_star


def test_star_player_is_marked():
    assert is_star({"star_attribute": "12"})


def test_hidden_indicator_is_not_marked():
    assert not is_star({"star_attribute": "12", "hide_star": "yes"})
    assert not is_star({"star_attribute": "12", "hide_star": True})
    assert is_star({"star_attribute": "12", "hide_star": ""})
    assert is_star({"star_attribute": "12", "hide_star": False})
