"""
app/user_stadiums.py — the user's own edits to stadiums
=========================================================
What the stadium editor sets on a stadium (its pads / posts / ads, the pitches
a match there may use, its default pitch, the pitch logos, the mowing stripes,
the environments and whether it is played at all) is kept apart from the data pack, in user_data/edits/stadiums/,
one small file per edited stadium:

    {"format": 1, "kind": "stadiums", "id": "twickenham_stoop",
     "mine": {"dressing": {...}, "pitches": [...], "pitch": "", "pitch_logos": null,
              "stripes": {...}, "environments": [], "enabled": true},
     "saved": "2026-11-17T09:00:00"}

At load those keys replace the pack's, key by key: a new data pack changes
everything else about the stadium and never erases the edit. `mine` always
holds every key; an empty one (no pitches, no default pitch, enabled...) gives
the pack's value back. An edit that equals the pack's values is not kept.
"""
import copy
import json
import os
from datetime import datetime

from shared.config import config
from shared.log import get_logger

log = get_logger(__name__)

FORMAT = 1
EDIT_KEYS = ("dressing", "pitches", "pitch", "pitch_logos", "stripes", "environments", "enabled")
_EMPTY = {"pitches": [], "environments": [], "dressing": {}, "stripes": {}, "pitch": "",
          "pitch_logos": None, "enabled": True}

#: {stadium id: {key: value}} of the editable keys as the data pack has them
#: (after the loader's defaults), taken by apply() before the edits: what an
#: empty value of an edit gives back
pack_values = {}


def directory():
    return os.path.join(config.directory_user_edits, "stadiums")


def _file(sid):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(sid))
    return os.path.join(directory(), f"{safe}.json")


def _empty(key, value):
    """Whether `value` of `key` means "the pack's own"."""
    if key == "pitch_logos":
        return value is None
    if key == "enabled":
        return value is None or value is True
    return not value


def normalise(values):
    """Every key of `values`, each in its stored form."""
    return {k: copy.deepcopy(values.get(k)) if not _empty(k, values.get(k)) else copy.deepcopy(_EMPTY[k])
            for k in EDIT_KEYS}


def pack_of(sid, info=None):
    """The pack's own values of stadium `sid` (`info` stands in when apply()
    hasn't seen it)."""
    if str(sid) in pack_values:
        return pack_values[str(sid)]
    return {k: copy.deepcopy(info[k]) for k in EDIT_KEYS if info and k in info}


def apply_one(info, mine, pack=None):
    """Lay the edit `mine` over the stadium `info` (a dict, changed in place);
    an empty value gives back `pack`'s (the pack's own values)."""
    pack = pack or {}
    for key in EDIT_KEYS:
        if key not in mine:
            continue
        value = mine[key] if not _empty(key, mine[key]) else pack.get(key)
        if value is None or (key == "enabled" and value is True):
            info.pop(key, None)
        else:
            info[key] = copy.deepcopy(value)
    if not info.get("environments"):        # the loader's default: the scenes it has
        info["environments"] = list(info.get("scenes") or [])
    return info


def enabled(info) -> bool:
    """False for a stadium switched off: not played (quick match, tournaments...)."""
    return info.get("enabled", True) is not False


def load():
    """{stadium id: mine} of every edit file; one that can't be read is left
    alone (set aside as .broken) and never blocks the start-up."""
    out = {}
    folder = directory()
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        path = os.path.join(folder, name)
        try:
            with open(path, encoding="utf-8") as fh:
                env = json.load(fh)
            if env.get("kind") != "stadiums" or "id" not in env or not isinstance(env.get("mine"), dict):
                raise ValueError("not a stadium edit file")
        except (OSError, ValueError, AttributeError) as e:
            log.error(f"user edit {path} unreadable ({e}), renamed to .broken")
            try:
                os.replace(path, path + ".broken")
            except OSError:
                pass
            continue
        out[str(env["id"])] = env["mine"]
    return out


def apply(stadiums, use=True):
    """Remember the pack's values of `stadiums` ({id: info}) and, with `use`
    (the user's edits turned on), lay every edit over them; the ids edited."""
    pack_values.clear()
    for sid, info in stadiums.items():
        if isinstance(info, dict):
            pack_values[str(sid)] = {k: copy.deepcopy(info[k]) for k in EDIT_KEYS if k in info}
    if not use:
        return []
    done = []
    for sid, mine in load().items():
        if sid in stadiums and isinstance(stadiums[sid], dict):
            apply_one(stadiums[sid], mine, pack_values.get(sid))
            done.append(sid)
    return done


def is_edited(sid):
    return os.path.isfile(_file(sid))


def save(sid, values, pack_values):
    """Keep `values` as the user's version of stadium `sid`; `pack_values`
    are the pack's own. Equal: the edit file is removed. Returns the path."""
    path = _file(sid)
    mine, theirs = normalise(values), normalise(pack_values)
    for key in EDIT_KEYS:
        if mine[key] == theirs[key]:          # the pack's own: kept as "the pack's"
            mine[key] = copy.deepcopy(_EMPTY[key])
    if mine == normalise({}):
        revert(sid)
        return path
    env = {"format": FORMAT, "kind": "stadiums", "id": str(sid), "mine": mine,
           "saved": datetime.now().isoformat(timespec="seconds")}
    os.makedirs(directory(), exist_ok=True)
    with open(path + ".tmp", "w", encoding="utf-8") as fh:
        json.dump(env, fh, indent=1, ensure_ascii=False)
        fh.write("\n")
    os.replace(path + ".tmp", path)
    return path


def revert(sid):
    try:
        os.remove(_file(sid))
    except FileNotFoundError:
        pass
