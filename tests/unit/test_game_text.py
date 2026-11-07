"""In-game names in characters the game can draw (shared/game_text.py)."""
import json
import os

from shared.game_text import game_name, is_game_safe
from conftest import REAL_DATA


def test_game_name():
    assert game_name("O.Jégou") == "O.Jegou"
    assert game_name("E.Căpățân") == "E.Capatan"
    assert game_name("K.Leʻaupepe") == "K.Le'aupepe"
    assert game_name("P.Fa’amuasil") == "P.Fa'amuasil"
    assert game_name("F.Trinh-Duc") == "F.Trinh-Duc"
    assert game_name("H.Brüssow") == "H.Brussow" and game_name("Ø.Strøm") == "O.Strom"
    assert is_game_safe("P.O'Connell") and not is_game_safe("M.Viñals")


def test_pack_display_names_are_game_safe():
    path = os.path.join(REAL_DATA, "players", "players.json")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as fh:
        players = json.load(fh)
    bad = {pid: r["display_name"] for pid, r in players.items()
           if not is_game_safe(r.get("display_name", ""))}
    assert not bad, bad
