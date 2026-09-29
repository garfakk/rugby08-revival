"""
app/stock_faces.py — the game's built-in ("stock") player faces
===================================================================
No Qt. A static catalog (assets/data/stock_faces.json) of every stock face
id the game ships in data.gob, with the real player name it was modelled on
where known. Built once from the modding community's file list by hashing
md5("players/heads/<id>") and matching against data.gob's own directory —
the same scheme backend.mod_utils.stock_head_path uses to extract one, which
is why the id alone (no hash) is enough to fetch it.
"""
import json
import os
import xml.etree.ElementTree as ET

from shared.app_paths import assets_directory

_CATALOG_PATH = os.path.join(assets_directory(), "data", "stock_faces.json")
_ATTR_PATH = os.path.join(assets_directory(), "data", "stock_face_attributes.xml")

_cache = None
_attr_cache = None


def load_stock_faces():
    """[{"id": int, "name": str}], sorted by id. Read once per process;
    an unreadable/missing catalog just yields an empty browse list rather
    than an error, same as a missing data.gob does elsewhere."""
    global _cache
    if _cache is None:
        try:
            with open(_CATALOG_PATH, "r", encoding="utf-8") as fh:
                _cache = json.load(fh)
        except (OSError, ValueError):
            _cache = []
    return _cache


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
    """{face_id: {attr_name: value}}, read once per process from the static
    XML catalog (assets/data/stock_face_attributes.xml) — hand-maintained,
    not derived from data.gob, since nothing in the game's own files
    describes a stock face's skin tone/headgear/hair colour/beard etc.
    Empty (not an error) when the file is missing, unparsable, or just
    hasn't been filled in yet for any face."""
    global _attr_cache
    if _attr_cache is None:
        _attr_cache = {}
        try:
            root = ET.parse(_ATTR_PATH).getroot()
            for face_el in root.findall("face"):
                fid = int(face_el.get("id"))
                attrs = {a.get("name"): (a.text or "").strip()
                        for a in face_el.findall("attr") if a.get("name") and (a.text or "").strip()}
                if attrs:
                    _attr_cache[fid] = attrs
        except (OSError, ET.ParseError, ValueError, TypeError):
            pass
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
