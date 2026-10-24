"""backend/match_memory.py + R08_handler.read_match_result: decoding the match
from the MatchSetup block (no game needed: the block is synthetic, built at
the documented offsets)."""
import struct

import pytest

from backend import R08_handler as RH
from backend import match_memory as mm
from shared.config import config


def put(d, team, slot, offset, value, size=1):
    pos = mm.player_offset(team, slot) + offset
    d[pos:pos + size] = value.to_bytes(size, "little")


@pytest.fixture
def block():
    d = bytearray(mm.SETUP_SIZE)

    def player(team, slot, rid, name, **fields):
        put(d, team, slot, 0x00, rid, 2)
        d[mm.player_offset(team, slot) + 4:mm.player_offset(team, slot) + 4 + len(name)] = name.encode("latin-1")
        offsets = {"penalties_scored": (0x3E, 1), "penalties_attempted": (0x3F, 1),
                   "conversions_scored": (0x40, 1), "conversions_attempted": (0x41, 1),
                   "drop_goals": (0x42, 1), "yellow_cards": (0x44, 1), "red_cards": (0x45, 1),
                   "man_of_the_match": (0x46, 1), "tries": (0x48, 2), "tackles": (0x4A, 2),
                   "injury": (0x61, 1)}
        for key, n in fields.items():
            off, size = offsets[key]
            put(d, team, slot, off, n, size)

    player("team_A", 0, 101, "A.Prop", tries=1, tackles=300)
    player("team_A", 9, 110, "A.Flyhalf", conversions_scored=1, conversions_attempted=2,
           penalties_scored=3, penalties_attempted=4, drop_goals=1)
    player("team_B", 13, 214, "B.Wing", tries=2, yellow_cards=1, injury=1)
    put(d, "team_B", 13, 0x50, 3)                       # kick style byte: not an injury
    # team tail: db id, captain, substitution log, set-piece counters
    base = mm.TEAM_RECORDS["team_A"]
    d[base + 0xBB8:base + 0xBBC] = (42).to_bytes(4, "little")
    d[base + 0xBBC:base + 0xBBE] = (110).to_bytes(2, "little")
    struct.pack_into("<HHf", d, base + 0xBFC, 101, 0, 3125.0)
    struct.pack_into("<HHf", d, base + 0xBFC + 8, 103, 0, 4000.5)
    struct.pack_into("<6H", d, base + 0xC54, 5, 2, 9, 3, 4, 1)
    return d


def test_players(block):
    rows = mm.read_players(block, "team_A")
    assert len(rows) == mm.SQUAD_SIZE
    assert rows[9]["name"] == "A.Flyhalf" and rows[9]["id"] == 110
    assert (rows[9]["conversions_attempted"], rows[9]["penalties_attempted"]) == (2, 4)
    assert rows[0]["tackles"] == 300                    # u16
    wing = mm.read_player(block, "team_B", 13)
    assert wing["injury"] == 1 and wing["yellow_cards"] == 1


def test_injury_is_not_the_kick_style_byte(block):
    put(block, "team_B", 13, 0x61, 0)
    assert mm.read_player(block, "team_B", 13)["injury"] == 0


def test_names_are_latin1_and_end_at_the_first_nul():
    d = bytearray(mm.SETUP_SIZE)
    pos = mm.player_offset("team_A", 3) + 4
    d[pos:pos + 12] = "Pérez\0junk!!".encode("latin-1")
    assert mm.read_player(d, "team_A", 3)["name"] == "Pérez"


def test_team_tail(block):
    assert mm.read_team_info(block, "team_A") == {"team_db_id": 42, "captain_id": 110}
    assert mm.read_sub_log(block, "team_A") == [{"off_id": 101, "clock": 3125.0},
                                                {"off_id": 103, "clock": 4000.5}]
    assert mm.read_sub_log(block, "team_B") == []
    assert mm.read_team_stats(block, "team_A") == {
        "scrums_won": 5, "scrums_lost": 2, "lineouts_won": 9, "lineouts_lost": 3,
        "ruck_turnovers_won": 4, "ruck_turnovers_lost": 1}


def test_score_block(block):
    pos = mm.SCORE_BLOCKS["team_B"]
    block[pos:pos + 5] = bytes([3, 2, 1, 2, 7])
    assert mm.read_score(block, "team_B") == {"tries": 3, "conversions": 2, "drop_goals": 1,
                                              "penalties": 2, "kicks_attempted": 7,
                                              "points": 15 + 4 + 3 + 6}


def test_man_of_the_match(block):
    assert mm.man_of_the_match(block) is None
    put(block, "team_B", 20, 0x46, 1)
    assert mm.man_of_the_match(block) == ("team_B", 20)


def test_record_slot():
    setup = config.memory_addresses["match_setup"]
    assert mm.record_slot(setup, setup + 9 * 100) == ("team_A", 9)
    assert mm.record_slot(setup, setup + 0xC60 + 29 * 100) == ("team_B", 29)
    assert mm.record_slot(setup, setup + 5) is None
    assert mm.record_slot(setup, 0) is None


@pytest.fixture
def handler(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "simulation_mode", False)
    monkeypatch.setattr(config, "temp_directory", str(tmp_path))
    return RH.R08_handler()


def test_read_match_result(handler, block):
    result = handler.read_match_result(block)
    a, b = result["team_A"], result["team_B"]
    assert len(a["players"]) == 22 and len(b["players"]) == 22
    # without a read during the match the score is summed from the players
    assert a["score"] == {"points": 5 + 2 + 9 + 3, "tries": 1, "conversions": 1, "penalties": 3,
                          "drop_goals": 1, "yellow_cards": 0, "red_cards": 0, "tackles": 300}
    assert b["score"]["points"] == 10 and b["score"]["yellow_cards"] == 1
    assert a["substitutions"][0] == {"off_id": 101, "clock": 3125.0}
    assert a["stats"]["scrums_won"] == 5 and a["captain_id"] == 110
    # nothing was read during the match
    assert result["events"] is None and result["lineup_events"] is None
    assert result["man_of_the_match"] is None and result["minute"] is None


def test_read_match_result_prefers_the_live_team_score(handler, block):
    handler.live_score = {"team_A": {"tries": 2, "conversions": 1, "drop_goals": 1, "penalties": 3,
                                     "kicks_attempted": 6, "points": 24}}
    result = handler.read_match_result(block)
    assert result["team_A"]["score"]["points"] == 24 and result["team_A"]["score"]["tackles"] == 300
    assert result["team_B"]["score"]["points"] == 10


def test_read_match_result_none(handler):
    assert handler.read_match_result(None) is None
    assert handler.read_match_result(b"\0" * 0x200) is None


def test_scoring_snapshot_agrees_with_result(handler, block):
    snap = mm.scoring_snapshot(block)
    assert len(snap) == 44
    assert snap[("team_A", 9)] == (110, {"try": 0, "conversion": 1, "penalty": 3, "drop_goal": 1})
    assert snap[("team_B", 13)][1]["try"] == 2
    result = handler.read_match_result(block)
    for (team, slot), (rid, counts) in snap.items():
        row = result[team]["players"][slot]
        assert rid == row["id"]
        assert counts == {"try": row["tries"], "conversion": row["conversions_scored"],
                          "penalty": row["penalties_scored"], "drop_goal": row["drop_goals"]}
