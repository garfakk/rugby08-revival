"""
app/roster_import/names.py — name conventions, compared and rewritten
======================================================================
Rosters spell the same player many ways: "A.Dupont", "A Dupont",
"Antoine Dupont", "DUPONT", "Dupont A.". `parse_name` reduces any of them to
(given-name initials, surname); `game_name` writes the mod's convention,
"A. Dupont".
"""
import re
import unicodedata

# Words that belong to the surname when they precede it ("du Plessis").
PARTICLES = {"de", "du", "des", "del", "della", "di", "da", "dos", "van", "von", "der", "den",
             "ten", "ter", "le", "la", "el", "al", "mac", "mc", "o", "st", "san"}
GAME_NAME_BYTES = 14


def strip_accents(text):
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(c for c in text if not unicodedata.combining(c))


def fold(text):
    """Lower case, no accents, letters and digits only."""
    return re.sub(r"[^a-z0-9]", "", strip_accents(text).lower())


class ParsedName:
    __slots__ = ("given", "surname", "surname_key", "initial", "star", "raw")

    def __init__(self, raw, given, surname, star):
        self.raw = raw
        self.given = given                     # given-name tokens as written
        self.surname = surname                 # surname as written ("du Plessis")
        self.surname_key = fold(surname)
        self.initial = fold(given[0])[:1] if given else ""
        self.star = star

    @property
    def last_token(self):
        tokens = self._tokens(self.surname)
        return fold(tokens[-1]) if tokens else ""

    @staticmethod
    def _tokens(text):
        return [t for t in re.split(r"[\s.\-_]+", text) if t]

    def __repr__(self):
        return f"ParsedName({self.initial or '?'} | {self.surname})"


def parse_name(raw):
    star = "^" in (raw or "")
    text = (raw or "").replace("^", " ").strip()
    if "," in text:                            # "Dupont, Antoine"
        surname, _, given = text.partition(",")
        text = f"{given.strip()} {surname.strip()}"
    # "A.Dupont" -> "A. Dupont"; keep hyphenated surnames whole
    text = re.sub(r"\b([A-Za-z]|[A-Z]{2,3})\.(?=\S)", r"\1. ", text)   # also "JM.Doussain"
    tokens = [t for t in re.split(r"\s+", text) if t]
    if not tokens:
        return ParsedName(raw or "", [], "", star)
    if len(tokens) == 1:
        return ParsedName(raw, [], tokens[0].rstrip("."), star)
    # trailing initial: "Dupont A." — only when the last token is a lone initial
    if len(tokens) == 2 and re.fullmatch(r"[A-Za-z]\.?", tokens[1]) and len(tokens[0]) > 2:
        return ParsedName(raw, [tokens[1]], tokens[0], star)
    # surname starts at the first particle after at least one given token,
    # otherwise at the last token
    start = len(tokens) - 1
    for i in range(len(tokens) - 1):
        if fold(tokens[i]) in PARTICLES:
            start = i
            break
    given = [t.rstrip(".") for t in tokens[:start]]
    return ParsedName(raw, given, " ".join(tokens[start:]), star)


def display_surname(parsed):
    """Surname as it should be shown: keep the writer's case unless the
    whole name is shouted ("DUPONT")."""
    s = parsed.surname.strip()
    if s.isupper() and len(s) > 3:
        s = " ".join(w if fold(w) in PARTICLES else w.capitalize() for w in s.lower().split())
        s = re.sub(r"(?<=[-'])([a-z])", lambda m: m.group(1).upper(), s)
    return s


def game_name(initial, surname, star=False, limit=GAME_NAME_BYTES, fit="truncate"):
    """The mod's in-game name: "A. Dupont". Too long for the game's 14
    bytes -> fit: "truncate" (cut the surname), "tight" (drop the space
    after the dot, then cut) or "keep" (untouched)."""
    initial = (initial or "").upper()
    prefix = "^" if star else ""
    head = f"{initial}. " if initial else ""
    name = f"{prefix}{head}{surname}"
    if fit == "keep" or len(name.encode("utf-8")) <= limit:
        return name
    if fit == "tight" and initial:
        tight = f"{prefix}{initial}.{surname}"
        if len(tight.encode("utf-8")) <= limit:
            return tight
        head = f"{initial}."
    raw = f"{prefix}{head}{surname}".encode("utf-8")[:limit]
    return raw.decode("utf-8", errors="ignore").rstrip()


def too_long(name, limit=GAME_NAME_BYTES):
    return len((name or "").encode("utf-8")) > limit


def record_names(record):
    """All parsed spellings a stored mod player answers to."""
    seen, out = set(), []
    first = (record.get("first_name") or "").strip()
    last = (record.get("last_name") or "").strip()
    candidates = [record.get("display_name") or ""]
    if last:
        candidates.append(f"{first} {last}".strip())
        if first:
            candidates.append(f"{first[0]}. {last}")
    for c in candidates:
        p = parse_name(c)
        key = (p.initial, p.surname_key)
        if p.surname_key and key not in seen:
            seen.add(key)
            out.append(p)
    return out


def name_score(roster_name, record, loose=False):
    """How well a roster spelling fits a mod player's names.
    -> (score, reason). score < 0 = different people. `loose` keeps a
    surname match whose initials differ (reason "initial differs"); the
    caller must then find other evidence that it is the same person."""
    rp = parse_name(roster_name)
    if not rp.surname_key:
        return -1, "no name"
    best = (-1, "surname differs")
    for mp in record_names(record):
        if mp.surname_key == rp.surname_key:
            s = 3
        elif mp.last_token and mp.last_token == rp.last_token:
            s = 2                              # "Plessis" vs "du Plessis"
        else:
            continue
        if rp.initial and mp.initial:
            if rp.initial != mp.initial:
                if not loose:
                    continue                   # A. Dupont is not B. Dupont
                if best[1] != "surname + initial" and s > best[0]:
                    best = (s, "initial differs")
                continue
            s += 2
        best = max(best, (s, "surname + initial" if rp.initial and mp.initial else "surname"))
    return best
