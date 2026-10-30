"""app/team_browse.py and season.nearest_season: the logic of the groups
Quick Match picker."""
from app.season import nearest_season
from app.team_browse import GROUPS, OTHER_GROUP, TeamIndex, group_label


def test_nearest_season():
    assert nearest_season(["2019", "2023", "2025"], "2023") == "2023"
    assert nearest_season(["2019", "2023", "2025"], "2021") == "2023"      # tie: the later
    assert nearest_season(["2019", "2023"], "2030") == "2023"
    assert nearest_season([], "2020") == ""
    assert nearest_season(["2019"], "x") == "2019"


class _Ds:
    def __init__(self, teams):
        self.teams = teams


def test_group_from_the_file_else_from_the_category():
    ix = TeamIndex(_Ds({
        "1": {"2009": {"name": "Benetton", "category": "Italy", "group": "other_european"},
              "2024": {"name": "Benetton", "category": "URC", "group": "other_european"}},
        "2": {"2024": {"name": "Toulon", "category": "Top 14"}},          # no group yet
        "3": {"2024": {"name": "Odd", "category": "Nowhere"}},
        "4": {"2024": {"name": "Custom", "group": "germany"}},
    }))
    assert ix.group("1") == "other_european"                 # the same whatever the season
    assert ix.group("2") == "france"
    assert ix.group("3") == OTHER_GROUP
    assert ix.groups() == [g for g in GROUPS if g in ("other_european", "france")] + ["germany"]
    assert ix.in_group("other_european") == ["1", "3"]
    assert group_label("france") == "France" and group_label("germany") == "germany"
    assert ix.span("1") == "2008–2024 · 2 seasons"
    assert ix.info("nope") == {}

