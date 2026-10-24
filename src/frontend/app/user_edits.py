"""
app/user_edits.py — the user's own edits to teams and players
===============================================================
The data pack (mod_data/) belongs to the release: installing a new one
replaces its files. What the user changes in the team and player editors is
kept apart, in user_data/edits/, one small JSON file per edited record:

    user_data/edits/players/<id>.json
    user_data/edits/teams/<id>.json

    {"format": 1, "kind": "players", "id": "10072",
     "home": "players/players.json",      # the pack file the record belongs to
     "base": {...},                        # the record in the pack when first edited
     "mine": {...},                        # the user's record (null: deleted)
     "data_version": "2026.1", "saved": "2026-10-18T17:20:00"}

At load the user's record replaces the pack's (`mine` wins). `base` is what
makes a new release safe: when the pack record no longer equals it, the
release changed that record too, and the three are merged field by field
(merge3). What only one side changed is taken from that side; a field both
changed differently is a conflict the user settles (see screens/user_edits.py)
— until then the user's value is used.

A team record is the whole {season: block} map as stored in its file,
disabled seasons included. Lists (a squad, a skin layer stack) are merged as
one value: a squad both sides changed is a conflict, never a mix of the two.

A whole set of edits can be exported as a folder (the edit files and the
image files they added, see EditStore.export) and imported by the maintainer,
who merges them into the pack like any other edit and writes them there
(promote). The same edit files can go into an update (app/updates.py).
"""
import copy
import json
import os
import random
import shutil
import zipfile
from datetime import datetime

from shared.log import get_logger

log = get_logger(__name__)

FORMAT = 1
KINDS = ("teams", "players")
MISSING = type("Missing", (), {"__repr__": lambda self: "MISSING", "__bool__": lambda self: False})()

#: ids of records the user creates come from a block of this install's own
#: (see IdBlocks), far above the pack's: two users creating a player
#: each never hand the maintainer the same id.
USER_ID_START = 10_000_000
ID_BLOCK = 100_000
ID_BLOCKS = 19_900          # the last id stays below 2**31


# ── three-way merge ──────────────────────────────────────────────────────
class Conflict:
    """One value both sides changed differently. `path` is the key path
    inside the record (() = the whole record: deleted on one side, changed
    on the other, or created on both); MISSING = the key isn't there."""
    __slots__ = ("path", "base", "mine", "theirs")

    def __init__(self, path, base, mine, theirs):
        self.path, self.base, self.mine, self.theirs = tuple(path), base, mine, theirs

    def __repr__(self):
        return f"Conflict({'/'.join(map(str, self.path)) or '<record>'})"


def merge3(base, mine, theirs, path=()):
    """(merged, [Conflict]) of two versions of `base`. Dicts merge key by key;
    any other value (lists included) is taken whole. At a conflict `merged`
    holds the user's value. MISSING stands for an absent key or record."""
    if mine == theirs:
        return mine, []
    if base == mine:
        return theirs, []
    if base == theirs:
        return mine, []
    if isinstance(mine, dict) and isinstance(theirs, dict) and (base is MISSING or isinstance(base, dict)):
        b = base if isinstance(base, dict) else {}
        merged, conflicts = {}, []
        for key in list(mine) + [k for k in theirs if k not in mine]:
            value, found = merge3(b.get(key, MISSING), mine.get(key, MISSING),
                                  theirs.get(key, MISSING), path + (key,))
            if value is not MISSING:
                merged[key] = value
            conflicts += found
        return merged, conflicts
    return mine, [Conflict(path, base, mine, theirs)]


def _m(record):
    return MISSING if record is None else record


def _u(value):
    return None if value is MISSING else value


def set_path(record, path, value):
    """`record` with the value at `path` replaced (MISSING removes it)."""
    if not path:
        return value
    record = record if isinstance(record, dict) else {}
    node = record
    for key in path[:-1]:
        if not isinstance(node.get(key), dict):
            node[key] = {}
        node = node[key]
    if value is MISSING:
        node.pop(path[-1], None)
    else:
        node[path[-1]] = copy.deepcopy(value)
    return record


def changed_paths(base, mine, path=()):
    """Key paths where `mine` differs from `base` (dicts walked, other values whole)."""
    if base == mine:
        return []
    if isinstance(base, dict) and isinstance(mine, dict):
        out = []
        for key in list(base) + [k for k in mine if k not in base]:
            out += changed_paths(base.get(key, MISSING), mine.get(key, MISSING), path + (key,))
        return out
    return [tuple(path)]


def get_path(record, path):
    node = record
    for key in path:
        if not isinstance(node, dict) or key not in node:
            return MISSING
        node = node[key]
    return node


# ── the pack files ───────────────────────────────────────────────────────
class PackFiles:
    """Reads records straight from the data pack's files (what `base` and
    `theirs` are), each file parsed once while it is unchanged on disk."""

    def __init__(self, root):
        self.root = root
        self._cache = {}

    def abspath(self, home):
        return os.path.join(self.root, *home.split("/")) if home else ""

    def relpath(self, path):
        if not path:
            return ""
        try:
            rel = os.path.relpath(os.path.abspath(path), os.path.abspath(self.root))
        except ValueError:          # another drive (Windows)
            return ""
        return "" if rel.startswith("..") else rel.replace(os.sep, "/")

    def load(self, path):
        try:
            stamp = os.stat(path)
        except OSError:
            return None
        key = (stamp.st_mtime_ns, stamp.st_size)
        hit = self._cache.get(path)
        if hit and hit[0] == key:
            return hit[1]
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            log.warning(f"{path}: {e}")
            return None
        if isinstance(data, list):      # old players file format
            data = {str(p.get("id") or p.get("player_id") or p.get("display_name")): p for p in data}
        self._cache[path] = (key, data)
        return data

    def record(self, home, rid):
        """The pack's record `rid` in file `home` (None: not in the pack).
        A copy: callers keep it as `base`."""
        data = self.load(self.abspath(home)) if home else None
        value = (data or {}).get(str(rid)) if isinstance(data, dict) else None
        return copy.deepcopy(value)

    def forget(self, path):
        self._cache.pop(path, None)


# ── ids for the records the user creates ─────────────────────────────────
class IdBlocks:
    """This install's own id block, picked at random once (ids.json):
    USER_ID_START + block * ID_BLOCK onwards, the next free one each time."""

    def __init__(self, root):
        self.path = os.path.join(root, "ids.json")

    def start(self):
        try:
            with open(self.path, encoding="utf-8") as fh:
                return int(json.load(fh)["start"])
        except (OSError, ValueError, KeyError, TypeError):
            pass
        start = USER_ID_START + random.randrange(ID_BLOCKS) * ID_BLOCK
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            _write_json(self.path, {"start": start})
        except OSError as e:
            log.warning(f"could not save the id block: {e}")
        return start

    def next_id(self, used):
        """One past the largest id of the block in `used` (a set of ints),
        so ids taken in a row from it (roster import) stay free."""
        start = self.start()
        return str(max([start - 1] + [u for u in used if start <= u < start + ID_BLOCK]) + 1)


def safe_rel(rel):
    """`rel` as a clean pack-relative path ("a/b.png"), or "" when it could
    leave the pack root (absolute, a drive, "..") — an edits export or an
    update is someone else's file."""
    if not isinstance(rel, str):
        return ""
    rel = rel.replace("\\", "/")
    parts = rel.split("/")
    if not rel or rel.startswith("/") or ":" in rel or any(p in ("", ".", "..") for p in parts):
        return ""
    return rel


def _write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path)


# ── the store ────────────────────────────────────────────────────────────
class EditStore:
    """Every edit of this user, one envelope per record (see the module doc).
    Pure data, no Qt: DataStore applies it to what the loader read."""

    def __init__(self, root, pack_root, data_version=""):
        self.root = root
        self.pack = PackFiles(pack_root)
        self.data_version = data_version
        self.ids = IdBlocks(root)
        self.envelopes = {k: {} for k in KINDS}
        #: (kind, id) -> [Conflict] still waiting for the user's choice
        self.conflicts = {}
        #: False: the edits are kept but not used (the pack alone is loaded,
        #: saves are refused), user_prefs.use_edits
        self.enabled = True
        #: what the last reconcile did on its own: [(what, kind, id)] with
        #: what = "merged" (release + user changes combined) or "integrated"
        #: (the release now holds exactly the user's record: edit dropped)
        self.notes = []

    # ── files ────────────────────────────────────────────────────────────
    def _file(self, kind, rid):
        safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in str(rid))
        return os.path.join(self.root, kind, f"{safe}.json")

    def load(self):
        for kind in KINDS:
            self.envelopes[kind] = {}
            folder = os.path.join(self.root, kind)
            if not os.path.isdir(folder):
                continue
            for name in sorted(os.listdir(folder)):
                if not name.endswith(".json"):
                    continue
                path = os.path.join(folder, name)
                try:
                    with open(path, encoding="utf-8") as fh:
                        env = json.load(fh)
                    if env.get("kind") != kind or "id" not in env or "mine" not in env:
                        raise ValueError("not an edit file")
                except (OSError, ValueError, AttributeError) as e:
                    # never block the start-up on one bad file: set it aside
                    log.error(f"user edit {path} unreadable ({e}), renamed to .broken")
                    try:
                        os.replace(path, path + ".broken")
                    except OSError:
                        pass
                    continue
                env["id"] = str(env["id"])
                self.envelopes[kind][env["id"]] = env
        return self

    def _write(self, env):
        path = self._file(env["kind"], env["id"])
        os.makedirs(os.path.dirname(path), exist_ok=True)
        _write_json(path, env)

    def _drop(self, kind, rid):
        self.envelopes[kind].pop(str(rid), None)
        self.conflicts.pop((kind, str(rid)), None)
        try:
            os.remove(self._file(kind, rid))
        except FileNotFoundError:
            pass

    # ── queries ──────────────────────────────────────────────────────────
    def get(self, kind, rid):
        return self.envelopes[kind].get(str(rid))

    def count(self):
        return sum(len(v) for v in self.envelopes.values())

    def is_edited(self, kind, rid):
        return str(rid) in self.envelopes[kind]

    def status(self, kind, rid):
        """"conflict", "new", "deleted", "edited" or None (not edited)."""
        env = self.get(kind, rid)
        if env is None:
            return None
        if (kind, str(rid)) in self.conflicts:
            return "conflict"
        if env["mine"] is None:
            return "deleted"
        return "new" if env["base"] is None else "edited"

    def theirs(self, kind, rid):
        """The record in the pack as installed now."""
        env = self.get(kind, rid)
        return self.pack.record(env["home"], rid) if env else None

    # ── load: lay the edits over the pack ────────────────────────────────
    def reconcile(self, kind, records, homes):
        """Apply this kind's edits to `records` (id -> record as read from
        the pack, changed in place). `homes` (id -> pack file) tells where a
        pack record lives. Returns the ids whose record is the user's."""
        self.notes = [n for n in self.notes if n[1] != kind]
        applied = []
        for rid, env in list(self.envelopes[kind].items()):
            self.conflicts.pop((kind, rid), None)
            theirs = records.get(rid)
            base, mine = env["base"], env["mine"]
            # the release may have moved the record to another file
            moved = self.pack.relpath(homes.get(rid, ""))
            moved = moved if moved and moved != env["home"] else ""
            if moved:
                env["home"] = moved
            if theirs == base:
                effective = mine
                if moved:
                    self._write(env)
            elif theirs == mine:
                # the release already has exactly this: nothing left to keep
                self._drop(kind, rid)
                self.notes.append(("integrated", kind, rid))
                continue
            else:
                merged, conflicts = merge3(_m(base), _m(mine), _m(theirs))
                effective = _u(merged)
                if conflicts:
                    self.conflicts[(kind, rid)] = conflicts
                    if moved:
                        self._write(env)
                elif effective == theirs:
                    self._drop(kind, rid)
                    self.notes.append(("integrated", kind, rid))
                    continue
                else:
                    self.notes.append(("merged", kind, rid))
                    env.update(base=copy.deepcopy(theirs), mine=copy.deepcopy(effective),
                               data_version=self.data_version)
                    self._write(env)
            if effective is None:
                records.pop(rid, None)
            else:
                records[rid] = copy.deepcopy(effective)
            applied.append(rid)
        return applied

    # ── editing ──────────────────────────────────────────────────────────
    def save(self, kind, rid, record, home_path):
        """Keep `record` (None: deleted) as the user's version of `rid`,
        whose pack file is `home_path`. Returns the envelope, or None when
        the record is back to the pack's version (edit file removed)."""
        rid = str(rid)
        env = self.get(kind, rid)
        if env is None:
            home = self.pack.relpath(home_path)
            env = {"format": FORMAT, "kind": kind, "id": rid, "home": home,
                   "base": self.pack.record(home, rid), "mine": None,
                   "data_version": self.data_version}
        env["mine"] = copy.deepcopy(record)
        env["saved"] = datetime.now().isoformat(timespec="seconds")
        if env["mine"] == env["base"]:
            self._drop(kind, rid)
            return None
        self.envelopes[kind][rid] = env
        self._write(env)
        if (kind, rid) in self.conflicts:
            self._recheck(kind, rid)
        return env

    def _recheck(self, kind, rid):
        env = self.get(kind, rid)
        theirs = self.pack.record(env["home"], rid)
        if theirs == env["base"]:
            self.conflicts.pop((kind, rid), None)
            return
        _merged, conflicts = merge3(_m(env["base"]), _m(env["mine"]), _m(theirs))
        if conflicts:
            self.conflicts[(kind, rid)] = conflicts
        else:
            self.conflicts.pop((kind, rid), None)

    def effective(self, kind, rid):
        """The record as it is used now: the user's merged with the release
        (user's values at conflicts). None when deleted / unknown."""
        env = self.get(kind, rid)
        if env is None:
            return None
        theirs = self.pack.record(env["home"], rid)
        if theirs == env["base"]:
            return copy.deepcopy(env["mine"])
        merged, _ = merge3(_m(env["base"]), _m(env["mine"]), _m(theirs))
        return copy.deepcopy(_u(merged))

    def resolve(self, kind, rid, choices):
        """Settle the conflicts of `rid`: `choices` maps each conflict path
        (tuple) to "mine" or "theirs" (unlisted: mine). The release becomes
        the new base. Returns the resulting record (None: deleted)."""
        rid = str(rid)
        env = self.get(kind, rid)
        if env is None:
            return None
        theirs = self.pack.record(env["home"], rid)
        merged, conflicts = merge3(_m(env["base"]), _m(env["mine"]), _m(theirs))
        result = copy.deepcopy(merged)
        for c in conflicts:
            if choices.get(c.path) == "theirs":
                result = set_path(result, c.path, c.theirs)
        result = _u(result)
        self.conflicts.pop((kind, rid), None)
        env.update(base=theirs, data_version=self.data_version)
        self.save(kind, rid, result, self.pack.abspath(env["home"]))
        return result

    def revert(self, kind, rid):
        """Forget the user's edit: the pack's record is used again (returned,
        None when the record exists only as the user's)."""
        env = self.get(kind, rid)
        theirs = self.pack.record(env["home"], rid) if env else None
        self._drop(kind, rid)
        return theirs

    # ── export / import ──────────────────────────────────────────────────
    def export(self, folder, keys=None, program_version=""):
        """Write the edits into `folder` (made; must be new or empty):
        manifest.json, edits/<kind>/<id>.json (all, or `keys` [(kind, id)])
        and files/<pack path> for every image file they reference that their
        base doesn't. Returns (records, files) counts."""
        if os.path.isdir(folder) and os.listdir(folder):
            raise OSError(f"{folder} is not empty")
        keys = keys or [(k, rid) for k in KINDS for rid in self.envelopes[k]]
        assets, written = set(), 0
        for kind, rid in keys:
            env = self.get(kind, rid)
            if env is None:
                continue
            dest = os.path.join(folder, "edits", kind, os.path.basename(self._file(kind, rid)))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            _write_json(dest, env)
            assets |= self._new_assets(env)
            written += 1
        for rel in sorted(assets):
            dest = os.path.join(folder, "files", *rel.split("/"))
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(self.pack.abspath(rel), dest)
        _write_json(os.path.join(folder, "manifest.json"), {
            "format": FORMAT, "data_version": self.data_version,
            "program_version": program_version,
            "created": datetime.now().isoformat(timespec="seconds"),
            "records": written, "files": len(assets)})
        return written, len(assets)

    def _new_assets(self, env):
        """Pack-relative paths of the files `mine` references and `base`
        doesn't, that exist under the pack root."""
        team_dir = os.path.dirname(env["home"]) if env["kind"] == "teams" else ""
        old = set(_strings(env["base"]))
        out = set()
        for s in _strings(env["mine"]):
            if s in old or "." not in s[-6:] or len(s) > 260:
                continue
            for rel in ([f"{team_dir}/{s}"] if team_dir else []) + [s]:
                rel = rel.replace("\\", "/")
                if os.path.isfile(self.pack.abspath(rel)):
                    out.add(rel)
                    break
        return out

    def import_bundle(self, path):
        """Take an edits export's edits in as this user's own (the pack merge
        then runs as for a release). `path`: the export folder, its
        manifest.json, or a zip of it. Records this user already edits are
        left out, files already present with other content too.
        Returns {"records": [(kind, id)], "skipped": [(kind, id)], "files": n,
        "file_clashes": [rel]}."""
        out = {"records": [], "skipped": [], "files": 0, "file_clashes": []}
        with open_bundle(path) as z:
            names = z.namelist()
            if "manifest.json" not in names:
                raise ValueError("not an edits export (no manifest.json)")
            for name in names:
                if not (name.startswith("edits/") and name.endswith(".json")):
                    continue
                try:
                    env = json.loads(z.read(name).decode("utf-8"))
                except ValueError:
                    continue
                if not isinstance(env, dict):
                    continue
                kind, rid = env.get("kind"), str(env.get("id", ""))
                home = safe_rel(env.get("home"))
                if kind not in KINDS or not rid or "mine" not in env or not home:
                    continue
                env.update(format=FORMAT, home=home, base=env.get("base"))
                if self.get(kind, rid) is not None:
                    out["skipped"].append((kind, rid))
                    continue
                env["id"] = rid
                self.envelopes[kind][rid] = env
                self._write(env)
                out["records"].append((kind, rid))
            for name in names:
                if not name.startswith("files/") or name.endswith("/"):
                    continue
                rel = safe_rel(name[len("files/"):])
                if not rel:
                    continue
                dest = self.pack.abspath(rel)
                data = z.read(name)
                if os.path.isfile(dest):
                    with open(dest, "rb") as fh:
                        if fh.read() != data:
                            out["file_clashes"].append(rel)
                    continue
                os.makedirs(os.path.dirname(dest), exist_ok=True)
                with open(dest, "wb") as fh:
                    fh.write(data)
                out["files"] += 1
        return out


class _FolderBundle:
    """A folder read like a ZipFile (namelist / read, "/" names). Symlinks
    are not followed: the folder is someone else's."""

    def __init__(self, root):
        self.root = root

    def namelist(self):
        names = []
        for top, dirs, files in os.walk(self.root):
            dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(top, d))]
            for f in files:
                full = os.path.join(top, f)
                if not os.path.islink(full):
                    names.append(os.path.relpath(full, self.root).replace(os.sep, "/"))
        return sorted(names)

    def read(self, name):
        with open(os.path.join(self.root, *name.split("/")), "rb") as fh:
            return fh.read()

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def open_bundle(path):
    """An edits export or an update to read: a folder (or a file inside it,
    such as its manifest.json) or a zip of it."""
    if os.path.isfile(path) and zipfile.is_zipfile(path):
        return zipfile.ZipFile(path)
    if os.path.isfile(path):
        path = os.path.dirname(path)
    if not os.path.isdir(path):
        raise ValueError(f"{path}: not a folder or a zip file")
    return _FolderBundle(path)


def _strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _strings(v)


def default_root():
    from shared.app_paths import user_data_directory
    return os.path.join(user_data_directory(), "edits")
