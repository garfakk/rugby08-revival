"""
app/stock_faces.py — the game's built-in ("stock") player faces
===================================================================
No Qt. A static catalog (assets/stock_game/faces.json) of every stock face
id the game ships in data.gob, with the real player name it was modelled on
where known, and the attributes the face picker filters on (skin_tone,
headgear, hair_color, hair_length, tape, beard) — hand-classified, since
nothing in the game's own files describes them; edit an entry to correct it.
The ids were found once from the modding community's file list by hashing
md5("players/heads/<id>") and matching against data.gob's own directory —
the same scheme backend.mod_utils.stock_head_path uses to extract one, which
is why the id alone (no hash) is enough to fetch it.
"""
import json
import os

from shared.app_paths import assets_directory

_CATALOG_PATH = os.path.join(assets_directory(), "stock_game", "faces.json")

_cache = None
_faces = None
_attr_cache = None


def _load_catalog():
    """Every catalog entry as in the file, sorted by id. Read once per process;
    an unreadable/missing catalog just yields an empty browse list rather
    than an error, same as a missing data.gob does elsewhere."""
    global _cache
    if _cache is None:
        try:
            with open(_CATALOG_PATH, "r", encoding="utf-8") as fh:
                _cache = sorted(json.load(fh), key=lambda f: f["id"])
        except (OSError, ValueError, KeyError, TypeError):
            _cache = []
    return _cache


def load_stock_faces():
    """[{"id": int, "name": str}], sorted by id."""
    global _faces
    if _faces is None:
        _faces = [{"id": f["id"], "name": f.get("name", "")} for f in _load_catalog()]
    return _faces


def search_stock_faces(query, filters=None):
    """Entries matching `query`: a numeric query matches an id PREFIX first
    (so "12" surfaces 12, 120, 1234... before any name containing "12"),
    falling back to a name substring match either way. Blank query returns
    the full catalog, in id order. `filters`, if given, is {attr_name:
    value} — see load_face_attributes(); a face with no value recorded for
    a filtered attribute doesn't match (there's nothing to confirm it does)."""
    query = (query or "").strip()
    faces = load_stock_faces()
    if query:
        q = query.lower()
        if query.isdigit():
            by_id = [f for f in faces if str(f["id"]).startswith(query)]
            seen = {f["id"] for f in by_id}
            by_name = [f for f in faces if f["id"] not in seen and q in f["name"].lower()]
            faces = by_id + by_name
        else:
            faces = [f for f in faces if q in f["name"].lower()]
    active = {k: v for k, v in (filters or {}).items() if v}
    if active:
        attrs = load_face_attributes()
        faces = [f for f in faces
                if all(attrs.get(f["id"], {}).get(k) == v for k, v in active.items())]
    return faces


def load_face_attributes():
    """{face_id: {attr_name: value}} for every face with at least one
    attribute filled in — the catalog's fields other than id and name."""
    global _attr_cache
    if _attr_cache is None:
        _attr_cache = {}
        for f in _load_catalog():
            attrs = {k: str(v).strip() for k, v in f.items()
                     if k not in ("id", "name") and str(v or "").strip()}
            if attrs:
                _attr_cache[f["id"]] = attrs
    return _attr_cache


def available_attributes():
    """{attr_name: [sorted distinct values]} across every tagged face — what
    the face picker's filter row builds its dropdowns from. An attribute
    with no face tagged for it yet just doesn't appear (no dead dropdown)."""
    values = {}
    for attrs in load_face_attributes().values():
        for name, value in attrs.items():
            values.setdefault(name, set()).add(value)
    return {name: sorted(vs) for name, vs in values.items()}
