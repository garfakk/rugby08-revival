"""
shared/game_text.py — Text as the game can show it.

The game's fonts only have plain ASCII: an accented letter or a typographic
apostrophe in a player's in-game name ("display_name") shows as garbage. So
accents are dropped (é -> e, ă -> a, ț -> t), every kind of apostrophe
becomes ' (O'Connell, Fa'amausili) and anything else outside printable ASCII
goes.
"""
import unicodedata

APOSTROPHES = "’‘ʻʼ`´′"
# letters NFKD does not split into a base letter and an accent
SPECIAL = {"ß": "ss", "æ": "ae", "Æ": "AE", "ø": "o", "Ø": "O", "œ": "oe", "Œ": "OE",
           "ł": "l", "Ł": "L", "đ": "d", "Đ": "D", "ð": "d", "þ": "th", "ı": "i"}


def game_name(text) -> str:
    """`text` in characters the game can draw."""
    out = []
    for ch in str(text or ""):
        if ch in APOSTROPHES:
            out.append("'")
            continue
        if ch in SPECIAL:
            out.append(SPECIAL[ch])
            continue
        for c in unicodedata.normalize("NFKD", ch):
            if unicodedata.combining(c):
                continue
            if " " <= c <= "~":
                out.append(c)
    return "".join(out)


def is_game_safe(text) -> bool:
    return game_name(text) == str(text or "")
