"""
app/referees.py — the referees a match can have
================================================
The data pack lists them in referees/referees.json:

    {"victor_scholtz": {"name": "Victor Scholtz", "face": "45000",
                        "kit": "stock:a", "kit_back": "", "rules": {}}}

- face: a stock head id (digits) or a head .big in mod data, as for players
- kit: "stock:a" (orange) / "stock:d" (green), or a kit .png in mod data laid
  out like a player's front kit (referees/kits/<file>.png)
- kit_back: "" (the stock back) or a 256x256 back .png
- rules: reR08 ref_* .mis keys (backend/referee.py); no editor for them yet

The referee editor's changes are the user's, in user_data/edits/referees.json
({id: record, or null for a pack referee removed}), laid over the pack's at
load: a new data pack never erases them.

Any kit goes with any referee: a match can put another kit on him
(MatchConfig.referee_kit: one kit, or AUTO = the kit of `kits` that stands out
most from both teams' kits), and a tournament lists the kits its referees wear
(option "referee_kits"), the best one picked for each match.

Only in expert mode: outside it every match has the game's own referee.
"""
import copy
import json
import os
import random
import re

from shared.config import config
from shared.log import get_logger

log = get_logger(__name__)

STOCK = ""          # MatchConfig.referee: the game's own referee
RANDOM = "random"   # one drawn from all referees
STOCK_KITS = {"stock:a": "orange", "stock:d": "green"}
STOCK_KIT_COLOURS = {"stock:a": (232, 120, 30), "stock:d": (60, 150, 70)}
KIT_DIR = "referees/kits"
KIT_EXTS = (".png", ".jpg", ".jpeg", ".webp")
OWN_KIT = ""        # MatchConfig.referee_kit: the referee's own kit
AUTO_KIT = "auto"   # the kit that stands out most from both teams'
_colour_cache = {}
FIELDS = ("name", "face", "kit", "kit_back", "rules")


def pack_file():
    return os.path.join(config.mod_data_directory, "referees", "referees.json")


def edits_file():
    return os.path.join(config.directory_user_edits, "referees.json")


def _read(path):
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError) as e:
        log.warning(f"{path}: {e}")
        return {}


def normalise(record):
    record = record if isinstance(record, dict) else {}
    out = {
        "name": str(record.get("name") or "").strip(),
        "face": str(record.get("face") or ""),
        "kit": str(record.get("kit") or "stock:a"),
        "kit_back": str(record.get("kit_back") or ""),
        "rules": copy.deepcopy(record.get("rules")) if isinstance(record.get("rules"), dict) else {},
    }
    return out


def pack():
    return {rid: normalise(r) for rid, r in _read(pack_file()).items() if isinstance(r, dict)}


def load():
    """{id: record} of every referee (pack + the user's edits), by name."""
    out = pack()
    for rid, record in _read(edits_file()).items():
        if record is None:
            out.pop(rid, None)
        elif isinstance(record, dict):
            out[rid] = normalise(record)
    return dict(sorted(out.items(), key=lambda kv: (kv[1]["name"].lower(), kv[0])))


def _write_edits(edits):
    path = edits_file()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(edits, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


def save(rid, record):
    """Keep `record` as referee `rid` (the user's edit; dropped when it
    equals the pack's)."""
    record = normalise(record)
    edits = _read(edits_file())
    if pack().get(rid) == record:
        edits.pop(rid, None)
    else:
        edits[rid] = record
    _write_edits(edits)


def delete(rid):
    edits = _read(edits_file())
    if rid in pack():
        edits[rid] = None
    else:
        edits.pop(rid, None)
    _write_edits(edits)


def new_id(name, taken):
    base = re.sub(r"[^a-z0-9]+", "_", (name or "referee").lower()).strip("_") or "referee"
    rid, n = base, 2
    while rid in taken:
        rid, n = f"{base}_{n}", n + 1
    return rid


def pick(referees, choice, rng=None):
    """The referee id `choice` (an id, RANDOM, or STOCK) stands for, among
    `referees`; None = the game's own."""
    if not choice or not referees:
        return None
    if choice == RANDOM:
        return (rng or random).choice(sorted(referees))
    return choice if choice in referees else None


def draw(pool, referees, seed):
    """One referee id from `pool` ("all" / None, or a list of ids) for a
    tournament fixture, the same every time for the same `seed`; None when
    no referee is left."""
    ids = sorted(referees) if pool in (None, "all") else [r for r in pool if r in referees]
    if not ids:
        return None
    return random.Random(str(seed)).choice(sorted(ids))


def match_data(referees, rid, kit=None):
    """match_data["referee"] for referee `rid` (backend/referee.py) wearing
    `kit` (None: his own); {} = the game's own referee in his own kit. The
    game's own referee (no `rid`) can wear another kit too."""
    record = referees.get(rid) if rid else None
    if not record:
        if not kit:
            return {}
        return {"id": "", "name": "", "face": "", "kit_front": kit, "kit_back": kit_back(kit),
                "rules": {}}
    face = record["face"]
    return {
        "id": rid,
        "name": record["name"],
        "face": int(face) if face.isdigit() else face,
        "kit_front": kit or record["kit"],
        "kit_back": kit_back(kit) if kit else record["kit_back"],
        "rules": copy.deepcopy(record["rules"]),
    }


# ── kits ─────────────────────────────────────────────────────────────────

def kits():
    """Every referee kit: the stock ones, then the kit images in mod data
    (referees/kits/, a "<name>_back.png" being a kit's back, not a kit)."""
    root = os.path.join(config.mod_data_directory, KIT_DIR)
    try:
        names = sorted(os.listdir(root))
    except OSError:
        names = []
    return list(STOCK_KITS) + [f"{KIT_DIR}/{n}" for n in names
                               if n.lower().endswith(KIT_EXTS) and "_back." not in n.lower()]


def kit_label(kit):
    if kit in STOCK_KITS:
        return STOCK_KITS[kit]
    return os.path.splitext(os.path.basename(str(kit)))[0].replace("_", " ")


def kit_back(kit):
    """The back image that goes with custom kit `kit` (<name>_back.<ext>
    next to it), "" for none (the stock back)."""
    if not kit or kit in STOCK_KITS:
        return ""
    stem, _ext = os.path.splitext(kit)
    for ext in KIT_EXTS:
        if os.path.isfile(os.path.join(config.mod_data_directory, stem + "_back" + ext)):
            return stem + "_back" + ext
    return ""


def kit_colour(kit):
    """(r, g, b): the main colour of referee kit `kit`; None when unknown."""
    if kit in STOCK_KIT_COLOURS:
        return STOCK_KIT_COLOURS[kit]
    path = os.path.join(config.mod_data_directory, str(kit or ""))
    try:
        key = (path, os.path.getmtime(path))
    except OSError:
        return None
    if key not in _colour_cache:
        from backend.crowd import kit_colours
        found = kit_colours(path)
        _colour_cache[key] = tuple(found[0]) if found else None
    return _colour_cache[key]


def _rgb(colour):
    if isinstance(colour, (tuple, list)) and len(colour) >= 3:
        return tuple(int(c) for c in colour[:3])
    text = str(colour or "").lstrip("#")
    if len(text) == 6:
        try:
            return tuple(int(text[i:i + 2], 16) for i in (0, 2, 4))
        except ValueError:
            return None
    return None


def _distance(a, b):
    # "redmean": closer to how far apart two colours look than plain RGB
    r = (a[0] + b[0]) / 2
    dr, dg, db = a[0] - b[0], a[1] - b[1], a[2] - b[2]
    return ((2 + r / 256) * dr * dr + 4 * dg * dg + (2 + (255 - r) / 256) * db * db) ** 0.5


def best_kit(candidates, team_colours, rng=None):
    """The kit of `candidates` that stands out most from every team colour
    (the "#rrggbb" or (r, g, b) of each team's kit): the one whose closest
    team colour is the farthest; a draw among those as good (within 10%).
    None when there's no candidate."""
    candidates = [k for k in candidates or [] if k]
    if not candidates:
        return None
    teams = [c for c in (_rgb(t) for t in team_colours or []) if c]
    if not teams:
        return (rng or random).choice(candidates) if len(candidates) > 1 else candidates[0]
    scored = []
    for kit in candidates:
        colour = kit_colour(kit)
        scored.append((min(_distance(colour, t) for t in teams) if colour else 0.0, kit))
    top = max(score for score, _kit in scored)
    best = [kit for score, kit in scored if score >= top * 0.9]
    return best[0] if len(best) == 1 else (rng or random).choice(best)


def resolve_kit(choice, team_colours, rng=None):
    """The kit MatchConfig.referee_kit `choice` stands for: None = the
    referee's own, AUTO = the best of all kits, a list = the best of those."""
    if not choice:
        return None
    if choice == AUTO_KIT:
        return best_kit(kits(), team_colours, rng)
    if isinstance(choice, (list, tuple)):
        return best_kit(choice, team_colours, rng)
    return choice
