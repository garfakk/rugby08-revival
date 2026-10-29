"""
app/updater/data.py — data pack updates: download only what changed.

A data release (tag data-<version>) carries data_manifest.json:

  {"format": 1, "data_version": "2026.10.24", "schema": 1, "min_program": "0.4",
   "source": {"repo": "owner/repo", "commit": "<sha>", "prefix": "data"},
   "files": {"teams/England/england.json": ["<sha256>", <size>], ...}}

The same manifest ships inside the data pack as mod_data/MANIFEST.json and
is rewritten by each data update: it is what this install has. Comparing the
two gives the plan without hashing the whole pack:

  fetch    new files, changed files, and listed files missing from disk or of
           the wrong size (a repair)
  remove   files the install's manifest lists that the new one doesn't

Files the manifest doesn't list (the user's own additions) are never
touched. An install without MANIFEST.json (older data installers) hashes
only the files that exist with the expected size, once.

The files come from the commit the manifest names (raw.githubusercontent.com,
or `source.base_url`), each verified against its sha256 into a staging
folder (user_data/updates/staging/<version>); a staged file that already
verifies is reused, so an interrupted update resumes where it stopped.
Only once everything is verified is it applied, through app/updates.py: the
files it replaces or removes are backed up and the update can be undone.

A data update is data: paths stay inside the data pack and executable or
script files are refused, whatever the manifest says.
"""
import json
import os
import re
import shutil
import threading
import urllib.parse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from app.user_edits import safe_rel

from . import net, releases

FORMAT = 1
LOCAL_MANIFEST = "MANIFEST.json"
VERSION_FILE = "VERSION"
RAW = "https://raw.githubusercontent.com"
WORKERS = 4
MAX_MANIFESTS = 5          # older releases looked at when the newest needs a newer program
# Never delivered by a data update, whatever the manifest says.
FORBIDDEN_EXT = {".exe", ".dll", ".bat", ".cmd", ".com", ".ps1", ".psm1", ".vbs", ".vbe", ".js",
                 ".jse", ".wsf", ".wsh", ".msi", ".msp", ".scr", ".pif", ".cpl", ".hta", ".lnk",
                 ".reg", ".sys", ".jar", ".py", ".pyc", ".pyw", ".sh"}
_SHA = re.compile(r"^[0-9a-f]{64}$")


class DataUpdateError(Exception):
    pass


# ── manifests ────────────────────────────────────────────────────────────
def allowed_path(path):
    """The manifest path as a clean relative path, or None when it may not be
    written by a data update."""
    rel = safe_rel(str(path))
    if not rel or rel in (LOCAL_MANIFEST, VERSION_FILE):
        return None
    if os.path.splitext(rel)[1].lower() in FORBIDDEN_EXT:
        return None
    return rel


def validate(manifest):
    """Raise DataUpdateError unless `manifest` is a usable data manifest."""
    if not isinstance(manifest, dict):
        raise DataUpdateError("the data manifest is not an object")
    if int(manifest.get("format") or 0) > FORMAT:
        raise DataUpdateError("this data release needs a newer version of the program")
    files = manifest.get("files")
    if not isinstance(files, dict) or not files:
        raise DataUpdateError("the data manifest lists no files")
    src = manifest.get("source") or {}
    if not (src.get("base_url") or (src.get("repo") and src.get("commit"))):
        raise DataUpdateError("the data manifest doesn't say where its files are")
    for path, entry in files.items():
        if (not isinstance(entry, (list, tuple)) or len(entry) != 2
                or not _SHA.match(str(entry[0]).lower()) or not isinstance(entry[1], int)):
            raise DataUpdateError(f"bad manifest entry for {path}")
    return manifest


def read_local(root):
    """This install's MANIFEST.json, or None."""
    try:
        with open(os.path.join(root, LOCAL_MANIFEST), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) and isinstance(data.get("files"), dict) else None
    except (OSError, ValueError):
        return None


def local_version(root):
    """The installed data version: MANIFEST.json, else the VERSION file."""
    local = read_local(root)
    if local and local.get("data_version"):
        return str(local["data_version"])
    try:
        with open(os.path.join(root, VERSION_FILE), encoding="utf-8") as fh:
            for line in fh:
                key, _, value = line.partition("=")
                if key.strip() == "data_version":
                    return value.strip()
    except OSError:
        pass
    return ""


def file_url(manifest, path):
    src = manifest["source"]
    quoted = "/".join(urllib.parse.quote(part) for part in path.split("/"))
    if src.get("base_url"):
        return src["base_url"].rstrip("/") + "/" + quoted
    prefix = str(src.get("prefix") or "").strip("/")
    return "/".join(x for x in (RAW, src["repo"], src["commit"], prefix, quoted) if x)


# ── checking ─────────────────────────────────────────────────────────────
@dataclass
class DataCheck:
    current: str = ""
    release: object = None          # releases.Release offered, or None
    manifest: dict = None
    blocked: str = ""               # a newer release needs a newer program: which

    @property
    def available(self):
        return self.release is not None


def check(source, root, schema, program_version):
    """The newest data release this program can use and that is newer than
    the installed data."""
    current = local_version(root)
    out = DataCheck(current=current)
    looked = 0
    for rel in releases.releases(source["repo"], source.get("tag_prefix", "data-")):
        if current and releases.version_key(rel.version) <= releases.version_key(current):
            break
        asset = rel.asset(source.get("manifest", "data_manifest.json"))
        if not asset:
            continue
        looked += 1
        if looked > MAX_MANIFESTS:
            break
        try:
            manifest = validate(json.loads(net.get_text(asset[0])))
        except ValueError as e:
            raise DataUpdateError(f"{rel.tag}: unreadable data manifest ({e})") from e
        needs = str(manifest.get("min_program") or "")
        if int(manifest.get("schema") or 0) != int(schema) or (
                needs and releases.version_key(program_version) < releases.version_key(needs)):
            out.blocked = out.blocked or (needs or "a newer version")
            continue
        out.release, out.manifest = rel, manifest
        break
    return out


# ── planning ─────────────────────────────────────────────────────────────
@dataclass
class DataPlan:
    manifest: dict
    fetch: list = field(default_factory=list)       # [(path, sha256, size)]
    remove: list = field(default_factory=list)      # [path]
    refused: list = field(default_factory=list)     # manifest paths a data update may not write

    @property
    def bytes(self):
        return sum(size for _p, _s, size in self.fetch)

    @property
    def empty(self):
        return not self.fetch and not self.remove

    def summary(self):
        parts = []
        if self.fetch:
            parts.append(f"{len(self.fetch)} file{'s' if len(self.fetch) != 1 else ''} to download "
                         f"({human_size(self.bytes)})")
        if self.remove:
            parts.append(f"{len(self.remove)} to remove")
        return ", ".join(parts) or "nothing to download"


def human_size(n):
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024


def plan(manifest, root, progress=None):
    """What it takes to bring the data pack at `root` to `manifest`.
    `progress(done, total)` reports the hashing an install without
    MANIFEST.json needs."""
    validate(manifest)
    local = (read_local(root) or {}).get("files") or {}
    out = DataPlan(manifest)
    unknown = []
    for raw_path, (sha, size) in manifest["files"].items():
        path = allowed_path(raw_path)
        if path is None:
            out.refused.append(raw_path)
            continue
        target = os.path.join(root, *path.split("/"))
        try:
            on_disk = os.path.getsize(target)
        except OSError:
            on_disk = None
        mine = local.get(path)
        if on_disk is None or on_disk != size:
            out.fetch.append((path, sha.lower(), size))               # new, or a repair
        elif mine is None:
            unknown.append((path, sha.lower(), size, target))         # same size, never recorded
        elif str(mine[0]).lower() != sha.lower():
            out.fetch.append((path, sha.lower(), size))               # changed
    for i, (path, sha, size, target) in enumerate(unknown, 1):
        if net.sha256_of(target) != sha:
            out.fetch.append((path, sha, size))
        if progress:
            progress(i, len(unknown))
    wanted = {allowed_path(p) for p in manifest["files"]}
    for path in local:
        rel = allowed_path(path)
        if rel and rel not in wanted and os.path.isfile(os.path.join(root, *rel.split("/"))):
            out.remove.append(rel)
    return out


# ── downloading ──────────────────────────────────────────────────────────
def staging_dir(base, manifest):
    version = re.sub(r"[^0-9A-Za-z._-]+", "_", str(manifest.get("data_version") or "next"))
    return os.path.join(base, "staging", f"data-{version}")


def download(the_plan, staging, progress=None, cancel=None, workers=WORKERS):
    """Fetch every planned file into `staging`/mod_data, verified.
    `progress(files_done, files_total, bytes_done, bytes_total)`; `cancel()`
    True stops (net.Cancelled). Raises DataUpdateError if a file can't be had."""
    items = list(the_plan.fetch)
    total_bytes = the_plan.bytes
    os.makedirs(staging, exist_ok=True)
    free = shutil.disk_usage(staging).free
    if free < total_bytes * 2:
        raise DataUpdateError(f"not enough free disk space: {human_size(total_bytes * 2)} needed, "
                              f"{human_size(free)} free")
    lock = threading.Lock()
    state = {"files": 0, "bytes": 0}
    stop = threading.Event()

    def report(files_inc, bytes_inc):
        with lock:
            state["files"] += files_inc
            state["bytes"] += bytes_inc
            snap = (state["files"], len(items), state["bytes"], total_bytes)
        if progress:
            progress(*snap)

    def cancelled():
        return stop.is_set() or bool(cancel and cancel())

    def one(item):
        path, sha, size = item
        dest = os.path.join(staging, "mod_data", *path.split("/"))
        if os.path.isfile(dest) and os.path.getsize(dest) == size and net.sha256_of(dest) == sha:
            report(1, size)                       # already staged by an earlier run
            return
        seen = [0]

        def on_bytes(n):
            report(0, n - seen[0])
            seen[0] = n
        net.download(file_url(the_plan.manifest, path), dest, sha256=sha, progress=on_bytes,
                     cancel=cancelled)
        report(1, 0)

    errors = []
    with ThreadPoolExecutor(max_workers=max(1, workers)) as pool:
        futures = {pool.submit(one, item): item for item in items}
        for fut in as_completed(futures):
            try:
                fut.result()
            except net.Cancelled:
                stop.set()
            except net.NetError as e:
                errors.append(f"{futures[fut][0]}: {e}")
                stop.set()
    if cancel and cancel():
        raise net.Cancelled()
    if errors:
        raise DataUpdateError(errors[0] + (f" (and {len(errors) - 1} more)" if len(errors) > 1 else ""))


# ── applying ─────────────────────────────────────────────────────────────
def apply(the_plan, staging, updates):
    """Install the staged files through app/updates.py (backups, undo):
    the planned files, the removals, the new MANIFEST.json and VERSION.
    Returns the journal entry; the staging folder is removed."""
    m = the_plan.manifest
    for path, _sha, _size in the_plan.fetch:
        if not os.path.isfile(os.path.join(staging, "mod_data", *path.split("/"))):
            raise DataUpdateError(f"{path} was not downloaded")
    mod = os.path.join(staging, "mod_data")
    os.makedirs(mod, exist_ok=True)
    with open(os.path.join(mod, LOCAL_MANIFEST), "w", encoding="utf-8") as fh:
        json.dump(m, fh, separators=(",", ":"))
    with open(os.path.join(mod, VERSION_FILE), "w", encoding="utf-8") as fh:
        fh.write(f"data_version={m.get('data_version', '')}\nschema={m.get('schema', '')}\n")
    with open(os.path.join(staging, "update.json"), "w", encoding="utf-8") as fh:
        json.dump({"format": 1, "kind": "data", "name": "Data",
                   "version": str(m.get("data_version") or ""),
                   "description": "online data update", "min_program": m.get("min_program") or "",
                   "remove": [f"mod_data/{p}" for p in the_plan.remove]}, fh, indent=1)
    from app.updates import UpdateError
    try:
        entry = updates.install(staging)
    except UpdateError as e:
        raise DataUpdateError(str(e)) from e
    shutil.rmtree(staging, ignore_errors=True)
    return entry
