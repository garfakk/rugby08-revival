"""The custom stadiums shipped in data/stadiums: each one loads, sits on a stock
slot, and has its files; the environments it offers either are the slot's or
come with a stadiuminfo that adds them."""
import os
import xml.etree.ElementTree as ET

import pytest

from backend.game_specific_variables import STADIUM_SLOTS
from conftest import REAL_DATA
from frontend.stadium_data_loader import StadiumDataLoader

pytestmark = pytest.mark.data

STADIUMS = os.path.join(REAL_DATA, "stadiums")
INFO = "xml/config/stadiuminfo.xml"


@pytest.fixture(scope="module")
def customs():
    stadiums = StadiumDataLoader(STADIUMS).load_stadiums()
    return {k: v for k, v in stadiums.items() if v.get("is_custom")}


def test_shipped_custom_stadiums_load(customs):
    assert len(customs) > 30
    for key, info in customs.items():
        assert info["game_id"] in STADIUM_SLOTS, key
        assert info["environments"] and set(info["scenes"]) == set(info["environments"]), key
        for rel in list(info["scenes"].values()) + list(info["files"].values()):
            assert os.path.isfile(os.path.join(REAL_DATA, rel)), (key, rel)


def test_environments_not_in_the_slot_come_with_a_stadiuminfo(customs):
    for key, info in customs.items():
        extra = [e for e in info["environments"] if e not in STADIUM_SLOTS[info["game_id"]]["scenes"]]
        rel = info["files"].get(INFO)
        if not rel:
            continue
        slot = next(s for s in ET.parse(os.path.join(REAL_DATA, rel)).getroot().iter("stadium")
                    if s.get("FileName").lower() == STADIUM_SLOTS[info["game_id"]]["file"].lower())
        have = {e.get("type") for e in slot.findall("environment")}
        assert set(info["environments"]) <= have, (key, extra)


def _stadium_refs(node, found):
    """Every "stadium" id of a competition (fixtures, ties) and its "venues"."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "stadium" and isinstance(value, (str, int)):
                found.add(str(value))
            elif key == "venues" and isinstance(value, list):
                found.update(str(v) for v in value)
            else:
                _stadium_refs(value, found)
    elif isinstance(node, list):
        for value in node:
            _stadium_refs(value, found)
    return found


def test_competitions_and_teams_name_stadiums_that_exist():
    import glob
    import json
    stadiums = set(StadiumDataLoader(STADIUMS).load_stadiums())
    for path in glob.glob(os.path.join(REAL_DATA, "competitions", "*", "*.json")):
        with open(path, encoding="utf-8") as fh:
            assert _stadium_refs(json.load(fh), set()) <= stadiums, path
    for path in glob.glob(os.path.join(REAL_DATA, "teams", "*", "*.json")):
        with open(path, encoding="utf-8") as fh:
            teams = json.load(fh)
        for seasons in teams.values():
            for info in (seasons.values() if isinstance(seasons, dict) else ()):
                ground = str(info.get("primaryStadium") or "") if isinstance(info, dict) else ""
                assert not ground or ground in stadiums, (path, ground)
