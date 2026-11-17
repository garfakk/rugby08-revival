"""
app/user_stadiums.py — the user's own edits to stadiums
=========================================================
What the stadium editor sets on a stadium (its pads / posts / ads, the pitches
a match there may use, the pitch logos, the mowing stripes and the
environments) is kept apart from the data pack, in user_data/edits/stadiums/,
one small file per edited stadium:

    {"format": 1, "kind": "stadiums", "id": "twickenham_stoop",
     "mine": {"dressing": {...}, "pitches": [...], "pitch_logos": null,
              "stripes": {...}, "environments": []},
     "saved": "2026-11-17T09:00:00"}

At load those keys replace the pack's, key by key: a new data pack changes
everything else about the stadium and never erases the edit. `mine` always
holds all five keys (an empty one is the user's "none"). An edit that equals
the pack's values is not kept.
"""
import copy
import json
import os
from datetime import datetime

from shared.config import config
from shared.log import get_logger

log = get_logger(__name__)

FORMAT = 1
EDIT_KEYS = ("dressing", "pitches", "pitch_logos", "stripes", "environments")


def directory():
    return os.path.join(config.directory_user_edits, "stadiums")


def _file(sid):
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(sid))
    return os.path.join(directory(), f"{safe}.json")


def _empty(key, value):
    """Whether `value` of `key` means "none" (the key is then left out)."""
    return value is None if key == "pitch_logos" else not value


def normalise(values):
    """The five keys of `values`, each in its stored form."""
    return {k: copy.deepcopy(values.get(k)) if not _empty(k, values.get(k))
            else ([] if k in ("pitches", "environments") else {} if k in ("dressing", "stripes") else None)
            for k in EDIT_KEYS}


def apply_one(info, mine):
    """Lay the edit `mine` over the stadium `info` (a dict, changed in place)."""
    for key in EDIT_KEYS:
        if key not in mine:
            continue
        value = mine[key]
        if _empty(key, value):
            info.pop(key, None)
        else:
            info[key] = copy.deepcopy(value)
    if not info.get("environments"):        # the loader's default: the scenes it has
        info["environments"] = list(info.get("scenes") or [])
    return info


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


def apply(stadiums):
    """Lay every edit over `stadiums` ({id: info}); the ids edited."""
    done = []
    for sid, mine in load().items():
        if sid in stadiums and isinstance(stadiums[sid], dict):
            apply_one(stadiums[sid], mine)
            done.append(sid)
    return done


def is_edited(sid):
    return os.path.isfile(_file(sid))


def save(sid, values, pack_values):
    """Keep `values` as the user's version of stadium `sid`; `pack_values`
    are the pack's own. Equal: the edit file is removed. Returns the path."""
    path = _file(sid)
    mine, theirs = normalise(values), normalise(pack_values)
    if mine == theirs:
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
