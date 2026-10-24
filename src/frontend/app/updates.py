"""
app/updates.py — updates for this install: new and replaced files, fixed records
=================================================================================
An update is a zip (or a folder) laid out like the mod's own folder, so its
author just puts each file where it goes:

    update.json                       {"format": 1, "name": "Kits 2026",
                                       "version": "1", "description": "...",
                                       "min_program": "0.2"}       (optional)
    mod_data/<path>                   a data pack file to add or replace
                                      (kits, logos, heads, a whole team file...)
    app_data/assets/<path>            a program asset to add or replace
                                      (assets/static_files/rugby08patches.dll...)
    edits/players/<id>.json           one record written into the data pack,
    edits/teams/<id>.json             in the format of an edits export
                                      (app/user_edits.py): {"kind", "id",
                                      "home": its pack file, "mine": the record,
                                      null = delete}

Running from source, mod_data is data/ and app_data is src/. Anything else in
the archive (user_data, game_files, the program itself, paths leaving the
folder, links) is ignored and listed.

Installing backs up every file it replaces into user_data/updates/backups/
first, and keeps a journal (user_data/updates/installed.json), so the last
update installed can be undone. The user's own edits are not touched: a
record an update changes is merged with the user's edit at the next start,
as for a new data release. The data is re-read at the next start.
"""
import json
import os
import re
import shutil
import stat
from datetime import datetime

from app.user_edits import KINDS, open_bundle, safe_rel
from shared.log import get_logger

log = get_logger(__name__)

FORMAT = 1
MANIFEST = "update.json"
MAX_TOTAL = 2 * 1024 ** 3        # bytes, all files together


class UpdateError(Exception):
    pass


def _version(text):
    return tuple(int(n) for n in re.findall(r"\d+", str(text))) or (0,)


class Plan:
    """What an update would do here. `files`: [(name, target, action)],
    `records`: [(name, kind, id, target, action)] with action "add",
    "replace", "same" (files) / "add", "replace", "delete" (records);
    `ignored`: names left out."""

    def __init__(self, manifest):
        self.manifest = manifest
        self.files, self.records, self.ignored = [], [], []

    @property
    def name(self):
        return str(self.manifest.get("name") or "Update")

    @property
    def version(self):
        return str(self.manifest.get("version") or "")

    def count(self, action, kind="files"):
        return sum(1 for item in getattr(self, kind) if item[-1] == action)

    def summary(self):
        parts = []
        for action, word in (("add", "new"), ("replace", "replaced")):
            if self.count(action):
                parts.append(f"{self.count(action)} {word} file(s)")
        changed = len(self.records)
        if changed:
            parts.append(f"{changed} team / player record(s)")
        if self.count("same"):
            parts.append(f"{self.count('same')} file(s) already up to date")
        if self.ignored:
            parts.append(f"{len(self.ignored)} ignored")
        return ", ".join(parts) or "nothing to change"


class Updates:
    """The updates of this install. `roots`: {"mod_data": the data pack
    folder, "app_data": the program's app_data folder}; `journal_dir`:
    user_data/updates."""

    def __init__(self, roots, journal_dir, program_version=""):
        self.roots = roots
        self.journal_dir = journal_dir
        self.program_version = program_version

    # ── journal ─────────────────────────────────────────────────────────
    @property
    def _journal(self):
        return os.path.join(self.journal_dir, "installed.json")

    def installed(self):
        """Installed updates, oldest first."""
        try:
            with open(self._journal, encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, list) else []
        except (OSError, ValueError):
            return []

    def _save_journal(self, entries):
        os.makedirs(self.journal_dir, exist_ok=True)
        tmp = self._journal + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(entries, fh, indent=1, ensure_ascii=False)
        os.replace(tmp, self._journal)

    # ── reading ─────────────────────────────────────────────────────────
    def _target(self, name):
        """The file of this install an archive member stands for, or None."""
        root, _, rest = name.partition("/")
        rel = safe_rel(rest)
        if not rel:
            return None
        if root == "mod_data":
            return os.path.join(self.roots["mod_data"], *rel.split("/"))
        if root == "app_data" and rel.startswith("assets/"):
            return os.path.join(self.roots["app_data"], *rel.split("/"))
        return None

    def read(self, path):
        """The Plan of the update at `path` (zip or folder). Raises
        UpdateError when it is not an update or not for this program."""
        try:
            with open_bundle(path) as bundle:
                return self._read(bundle)
        except (OSError, ValueError) as e:
            raise UpdateError(str(e)) from e

    def _read(self, bundle):
        names = bundle.namelist()
        if MANIFEST not in names:
            raise UpdateError(f"not an update (no {MANIFEST})")
        try:
            manifest = json.loads(bundle.read(MANIFEST).decode("utf-8"))
        except ValueError as e:
            raise UpdateError(f"{MANIFEST}: {e}") from e
        if not isinstance(manifest, dict):
            raise UpdateError(f"{MANIFEST} is not an object")
        if int(manifest.get("format") or FORMAT) > FORMAT:
            raise UpdateError("this update needs a newer version of the program")
        needed = manifest.get("min_program")
        if needed and self.program_version and _version(self.program_version) < _version(needed):
            raise UpdateError(f"this update needs the program {needed} or later "
                              f"(this one is {self.program_version})")
        plan = Plan(manifest)
        infos = {i.filename: i for i in bundle.infolist()} if hasattr(bundle, "infolist") else {}
        total = 0
        for name in names:
            if name == MANIFEST or name.endswith("/"):
                continue
            info = infos.get(name)
            if info is not None:
                if stat.S_ISLNK(info.external_attr >> 16):
                    plan.ignored.append(name)
                    continue
                total += info.file_size
                if total > MAX_TOTAL:
                    raise UpdateError("the update is too big")
            if name.startswith("edits/"):
                record = self._read_record(bundle, name)
                if record is None:
                    plan.ignored.append(name)
                else:
                    plan.records.append(record)
                continue
            target = self._target(name)
            if target is None:
                plan.ignored.append(name)
                continue
            data = bundle.read(name)
            if info is None:
                total += len(data)
                if total > MAX_TOTAL:
                    raise UpdateError("the update is too big")
            if os.path.isfile(target):
                with open(target, "rb") as fh:
                    action = "same" if fh.read() == data else "replace"
            else:
                action = "add"
            plan.files.append((name, target, action))
        return plan

    def _read_record(self, bundle, name):
        try:
            env = json.loads(bundle.read(name).decode("utf-8"))
        except ValueError:
            return None
        if not isinstance(env, dict):
            return None
        kind, rid, home = env.get("kind"), str(env.get("id") or ""), safe_rel(env.get("home"))
        if kind not in KINDS or not rid or not home or "mine" not in env:
            return None
        if env["mine"] is not None and not isinstance(env["mine"], dict):
            return None
        target = os.path.join(self.roots["mod_data"], *home.split("/"))
        exists = rid in _load_map(target) if os.path.isfile(target) else False
        action = "delete" if env["mine"] is None else ("replace" if exists else "add")
        return (name, kind, rid, target, action)

    # ── installing ──────────────────────────────────────────────────────
    def install(self, path):
        """Install the update at `path`. Returns its journal entry."""
        try:
            with open_bundle(path) as bundle:
                plan = self._read(bundle)
                stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
                entry = {"id": f"{stamp}_{_slug(plan.name)}", "name": plan.name,
                         "version": plan.version,
                         "description": str(plan.manifest.get("description") or ""),
                         "source": os.path.basename(os.path.normpath(path)),
                         "installed": datetime.now().isoformat(timespec="seconds"),
                         "summary": plan.summary(), "created": [], "replaced": []}
                backups = os.path.join(self.journal_dir, "backups", entry["id"])
                try:
                    for name, target, action in plan.files:
                        if action != "same":
                            self._keep_original(entry, backups, target)
                            _write_bytes(target, bundle.read(name))
                    for name, kind, rid, target, action in plan.records:
                        env = json.loads(bundle.read(name).decode("utf-8"))
                        self._keep_original(entry, backups, target)
                        _write_record(kind, rid, target, env["mine"])
                except Exception:
                    self._restore(entry)
                    shutil.rmtree(backups, ignore_errors=True)
                    raise
        except (OSError, ValueError) as e:
            raise UpdateError(str(e)) from e
        self._save_journal(self.installed() + [entry])
        log.info(f"Installed update {entry['name']} {entry['version']}: {entry['summary']}")
        return entry

    def _keep_original(self, entry, backups, target):
        """Before `target` is first written: copy it to the backups (or note
        it is new), once per update."""
        if target in entry["created"] or any(r["path"] == target for r in entry["replaced"]):
            return
        if os.path.isfile(target):
            backup = os.path.join(backups, f"{len(entry['replaced']):05d}_{os.path.basename(target)}")
            os.makedirs(backups, exist_ok=True)
            shutil.copy2(target, backup)
            entry["replaced"].append({"path": target, "backup": backup})
        else:
            entry["created"].append(target)

    @staticmethod
    def _restore(entry):
        for path in entry["created"]:
            try:
                os.remove(path)
            except OSError:
                pass
        for item in entry["replaced"]:
            os.makedirs(os.path.dirname(item["path"]), exist_ok=True)
            shutil.copy2(item["backup"], item["path"])

    def undo_last(self):
        """Put back what the last installed update replaced and remove what
        it added. Returns its entry, None when no update is installed."""
        entries = self.installed()
        if not entries:
            return None
        entry = entries[-1]
        try:
            self._restore(entry)
        except OSError as e:
            raise UpdateError(f"could not undo {entry['name']}: {e}") from e
        shutil.rmtree(os.path.join(self.journal_dir, "backups", entry["id"]), ignore_errors=True)
        self._save_journal(entries[:-1])
        log.info(f"Undid update {entry['name']} {entry['version']}")
        return entry


def _slug(text):
    return re.sub(r"[^A-Za-z0-9]+", "_", text).strip("_")[:40] or "update"


def _write_bytes(target, data):
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, target)


def _load_map(path):
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{os.path.basename(path)} is not a map of records")
    return data


def _write_record(kind, rid, target, record):
    """Set (or, record None, remove) one record in its pack file; the file is
    made for a new one. Other records of the file stay as they are. A team
    file left empty is removed (the loader reads one team per file)."""
    data = _load_map(target) if os.path.isfile(target) else {}
    if record is None:
        data.pop(rid, None)
    else:
        data[rid] = record
    if kind == "teams" and not data:
        if os.path.isfile(target):
            os.remove(target)
        return
    os.makedirs(os.path.dirname(target), exist_ok=True)
    tmp = target + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, target)


def default_updates():
    """The updates of this install (the real folders)."""
    from shared.app_paths import user_data_directory
    from shared.config import config
    from shared.version import APP_VERSION
    return Updates({"mod_data": config.mod_data_directory, "app_data": config.mod_src_directory},
                   os.path.join(user_data_directory(), "updates"), APP_VERSION)
