#!/usr/bin/env python3
"""
packaging/update_lab.py — try the online update feature without GitHub.

A throw-away install of the mod (a sandbox) plus a fake GitHub on localhost,
so program and data releases can be published, changed and withdrawn at will
and the real updater (app/updater) checks, downloads, verifies and applies
them. Your repo's data/ and user_data/ are never touched: the sandbox's data
pack is a tree of symlinks to them, and an update replaces a link with the
file, never writes through it.

    python src/packaging/update_lab.py setup            # once (and to start over: --force)
    python src/packaging/update_lab.py edit teams/England/england.json   # change the "upstream" data
    python src/packaging/update_lab.py publish-data 2026.11.10 --notes "England squad"
    python src/packaging/update_lab.py publish-program 0.4
    python src/packaging/update_lab.py run              # fake GitHub + the mod, on the sandbox

In the mod: the main menu shows UPDATE AVAILABLE, Tools > Updates > Online
downloads and applies the data update (then Undo puts it back).

The lab lives in ../rugby08-update-lab (--lab DIR or R08_UPDATE_LAB):

    root/        the sandbox install (run.py, src -> the repo's, data/, user_data/)
    upstream/    "what the data repository holds": a tree of links to data/;
                 `edit` makes real files of the ones you change
    server/      releases.json, the files of each release (blobs/, assets/)

Releases are snapshots: publish-data records upstream's files as they are
now, so editing upstream afterwards changes nothing already published.

Commands
    setup [--force]              build the lab (baseline = the data as it is now)
    edit PATH [--text T | --from FILE | --delete]   change, replace or delete an upstream file
                                 (default: append a newline, a harmless change of one file)
    add PATH [--text T]          a new upstream file
    publish-data VERSION         a data release of upstream's current state
        [--notes T] [--min-program V] [--schema N]
        [--corrupt PATH]         serve PATH damaged: the checksum check must refuse it
    publish-program VERSION      a program release with its installer and SHA256SUMS
        [--notes T] [--no-installer] [--bad-sums]
    unpublish TAG                withdraw a release (tags: data-<version>, v<version>)
    status                       installed versions, published releases, pending upstream changes
    serve [--port N]             the fake GitHub only
    run [--port N] [-- ARGS]     the fake GitHub and the mod on the sandbox (forces a check)
    reset                        back to the baseline: sandbox data, journal and releases

The program part of the mod updates itself only as the released Windows
build: here its card shows the release, and the installer is not run.
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path[:0] = [os.path.join(REPO_ROOT, "src", "frontend"), os.path.join(REPO_ROOT, "src")]

DEFAULT_PORT = 18765
SKIP = {"MANIFEST.json", "VERSION"}
OWNER = "garfakk/rugby08-revival"


def lab_dir(args):
    return os.path.abspath(args.lab or os.environ.get("R08_UPDATE_LAB")
                           or os.path.join(os.path.dirname(REPO_ROOT), "rugby08-update-lab"))


class Lab:
    def __init__(self, path):
        self.path = path
        self.root = os.path.join(path, "root")
        self.upstream = os.path.join(path, "upstream", "data")
        self.server = os.path.join(path, "server")
        self.releases_file = os.path.join(self.server, "releases.json")
        self.cache_file = os.path.join(path, "hashcache.json")
        self._cache = None

    # ── hashing (cached by size and mtime: the pack is 1.4 GB) ──────────
    def sha(self, path):
        if self._cache is None:
            try:
                with open(self.cache_file) as f:
                    self._cache = json.load(f)
            except (OSError, ValueError):
                self._cache = {}
        real = os.path.realpath(path)
        st = os.stat(real)
        key = f"{real}|{st.st_size}|{st.st_mtime_ns}"
        if key not in self._cache:
            h = hashlib.sha256()
            with open(real, "rb") as f:
                for chunk in iter(lambda: f.read(1 << 20), b""):
                    h.update(chunk)
            self._cache[key] = h.hexdigest()
        return self._cache[key]

    def save_cache(self):
        if self._cache is not None:
            with open(self.cache_file, "w") as f:
                json.dump(self._cache, f)

    def files_of(self, tree):
        out = {}
        for base, _dirs, names in os.walk(tree):
            for n in names:
                full = os.path.join(base, n)
                rel = os.path.relpath(full, tree).replace(os.sep, "/")
                if rel not in SKIP:
                    out[rel] = [self.sha(full), os.path.getsize(full)]
        self.save_cache()
        return dict(sorted(out.items()))

    # ── state ───────────────────────────────────────────────────────────
    def releases(self):
        try:
            with open(self.releases_file, encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return []

    def save_releases(self, items):
        os.makedirs(self.server, exist_ok=True)
        with open(self.releases_file, "w", encoding="utf-8") as f:
            json.dump(items, f, indent=1)

    def installed_manifest(self):
        try:
            with open(os.path.join(self.root, "data", "MANIFEST.json"), encoding="utf-8") as f:
                return json.load(f)
        except (OSError, ValueError):
            return {}

    def last_data_manifest(self):
        """The newest published data manifest, else the sandbox's baseline."""
        data = [r for r in self.releases() if r["kind"] == "data"]
        if data:
            with open(os.path.join(self.server, "assets", data[-1]["tag"], "data_manifest.json"),
                      encoding="utf-8") as f:
                return json.load(f)
        return self.installed_manifest()


def link_tree(src, dst):
    """dst mirrors src: directories made, files symlinked."""
    for base, _dirs, names in os.walk(src):
        target = os.path.join(dst, os.path.relpath(base, src))
        os.makedirs(target, exist_ok=True)
        for n in names:
            os.symlink(os.path.join(base, n), os.path.join(target, n))


def make_real(path):
    """A symlinked file becomes a real copy (so editing never writes through)."""
    if os.path.islink(path):
        real = os.path.realpath(path)
        os.remove(path)
        shutil.copy2(real, path)


# ── setup / reset ───────────────────────────────────────────────────────
def build_sandbox(lab, baseline_version):
    shutil.rmtree(lab.root, ignore_errors=True)
    os.makedirs(lab.root)
    shutil.copy(os.path.join(REPO_ROOT, "run.py"), os.path.join(lab.root, "run.py"))
    os.symlink(os.path.join(REPO_ROOT, "src"), os.path.join(lab.root, "src"))
    link_tree(os.path.join(REPO_ROOT, "data"), os.path.join(lab.root, "data"))
    user = os.path.join(lab.root, "user_data")
    os.makedirs(user)
    for name in ("config.ini", "user_prefs.ini", "game_profile.ini"):
        src = os.path.join(REPO_ROOT, "user_data", name)
        if os.path.isfile(src):
            shutil.copy(src, os.path.join(user, name))
    files = lab.files_of(os.path.join(lab.root, "data"))
    manifest = {"format": 1, "data_version": baseline_version, "schema": 1, "min_program": "",
                "source": {"base_url": f"http://127.0.0.1:{DEFAULT_PORT}/data/{baseline_version}"},
                "files": files}
    with open(os.path.join(lab.root, "data", "MANIFEST.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f, separators=(",", ":"))
    with open(os.path.join(lab.root, "data", "VERSION"), "w", encoding="utf-8") as f:
        f.write(f"data_version={baseline_version}\nschema=1\n")
    return manifest


def cmd_setup(args):
    lab = Lab(lab_dir(args))
    if os.path.exists(lab.path) and not args.force:
        sys.exit(f"{lab.path} exists: use --force to rebuild it, or `reset` to go back to the baseline")
    shutil.rmtree(lab.path, ignore_errors=True)
    os.makedirs(lab.path)
    print(f"building the lab in {lab.path} (hashing the data pack once)...")
    manifest = build_sandbox(lab, args.baseline)
    with open(os.path.join(lab.path, "baseline.txt"), "w") as f:
        f.write(args.baseline)
    shutil.rmtree(os.path.dirname(lab.upstream), ignore_errors=True)
    link_tree(os.path.join(REPO_ROOT, "data"), lab.upstream)
    lab.save_releases([])
    print(f"ready: {len(manifest['files'])} files, data version {args.baseline}, program {program_version()}")
    print("next: `edit` some upstream file, `publish-data <version>`, then `run`")


def cmd_reset(args):
    lab = need_lab(args)
    try:
        with open(os.path.join(lab.path, "baseline.txt")) as f:
            base = f.read().strip()
    except OSError:
        base = "2026.11.01"
    shutil.rmtree(lab.server, ignore_errors=True)
    build_sandbox(lab, base)
    shutil.rmtree(os.path.dirname(lab.upstream), ignore_errors=True)
    link_tree(os.path.join(REPO_ROOT, "data"), lab.upstream)
    lab.save_releases([])
    print("back to the baseline: sandbox data, journal and releases reset")


def need_lab(args):
    lab = Lab(lab_dir(args))
    if not os.path.isdir(lab.root):
        sys.exit(f"no lab in {lab.path}: run `setup` first")
    return lab


def program_version():
    from shared.version import APP_VERSION
    return APP_VERSION


# ── upstream edits ──────────────────────────────────────────────────────
def _upstream_path(lab, rel):
    rel = rel.strip("/")
    if ".." in rel.split("/"):
        sys.exit("path must stay inside the data folder")
    return os.path.join(lab.upstream, *rel.split("/"))


def cmd_edit(args):
    lab = need_lab(args)
    path = _upstream_path(lab, args.path)
    if args.delete:
        if not os.path.lexists(path):
            sys.exit(f"{args.path} is not in upstream")
        os.remove(path)
        print(f"upstream: {args.path} deleted")
        return
    if not os.path.lexists(path):
        sys.exit(f"{args.path} is not in upstream (use `add`)")
    make_real(path)
    if args.from_file:
        shutil.copy(args.from_file, path)
    elif args.text is not None:
        with open(path, "ab") as f:
            f.write(args.text.encode())
    else:
        with open(path, "ab") as f:
            f.write(b"\n")
    print(f"upstream: {args.path} changed ({os.path.getsize(path)} bytes)")


def cmd_add(args):
    lab = need_lab(args)
    path = _upstream_path(lab, args.path)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if os.path.lexists(path):
        os.remove(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write(args.text if args.text is not None else f"added by the update lab {time.ctime()}\n")
    print(f"upstream: {args.path} added")


# ── publishing ──────────────────────────────────────────────────────────
def _release_item(kind, tag, version, name, notes, assets):
    return {"kind": kind, "tag": tag, "version": version, "name": name, "body": notes,
            "assets": assets, "published": time.strftime("%Y-%m-%d %H:%M")}


def _check_new(lab, tag):
    if any(r["tag"] == tag for r in lab.releases()):
        sys.exit(f"{tag} is already published (`unpublish {tag}` first)")


def cmd_publish_data(args):
    lab = need_lab(args)
    tag = f"data-{args.version}"
    _check_new(lab, tag)
    files = lab.files_of(lab.upstream)
    before = lab.last_data_manifest().get("files") or {}
    changed = [p for p, v in files.items() if before.get(p, [None])[0] != v[0]]
    removed = [p for p in before if p not in files]
    blobs = os.path.join(lab.server, "blobs")
    os.makedirs(blobs, exist_ok=True)
    for p in changed:                                       # the snapshot: this release's new files
        dest = os.path.join(blobs, files[p][0])
        if not os.path.isfile(dest):
            shutil.copy(os.path.join(lab.upstream, *p.split("/")), dest)
    if args.corrupt:
        if args.corrupt not in files:
            sys.exit(f"--corrupt: {args.corrupt} is not in upstream")
        with open(os.path.join(blobs, files[args.corrupt][0]), "wb") as f:
            f.write(b"this is not the file the manifest promised")
    manifest = {"format": 1, "data_version": args.version, "schema": args.schema,
                "min_program": args.min_program or "",
                "source": {"base_url": f"http://127.0.0.1:{args.port}/data/{args.version}"},
                "files": files}
    adir = os.path.join(lab.server, "assets", tag)
    os.makedirs(adir, exist_ok=True)
    with open(os.path.join(adir, "data_manifest.json"), "w", encoding="utf-8") as f:
        json.dump(manifest, f)
    items = lab.releases() + [_release_item("data", tag, args.version, f"Data {args.version}",
                                            args.notes or "", ["data_manifest.json"])]
    lab.save_releases(items)
    size = sum(files[p][1] for p in changed)
    print(f"published {tag}: {len(changed)} new/changed file(s) ({size} bytes), {len(removed)} removed")
    if args.corrupt:
        print(f"  {args.corrupt} is served damaged on purpose")


def cmd_publish_program(args):
    lab = need_lab(args)
    tag = f"v{args.version}"
    _check_new(lab, tag)
    adir = os.path.join(lab.server, "assets", tag)
    os.makedirs(adir, exist_ok=True)
    names = []
    if not args.no_installer:
        name = f"R08Revival_{args.version}_program_only.exe"
        blob = f"not a real installer: update lab, program {args.version}\n".encode() * 64
        with open(os.path.join(adir, name), "wb") as f:
            f.write(blob)
        digest = hashlib.sha256(blob).hexdigest()
        if args.bad_sums:
            digest = hashlib.sha256(b"something else").hexdigest()
        with open(os.path.join(adir, "SHA256SUMS"), "w") as f:
            f.write(f"{digest}  {name}\n")
        names = [name, "SHA256SUMS"]
    lab.save_releases(lab.releases() + [_release_item(
        "program", tag, args.version, f"Rugby 08 Revival {args.version}", args.notes or "", names)])
    print(f"published {tag}" + (" (without installer)" if args.no_installer else ""))


def cmd_unpublish(args):
    lab = need_lab(args)
    items = lab.releases()
    keep = [r for r in items if r["tag"] != args.tag]
    if len(keep) == len(items):
        sys.exit(f"no release {args.tag}")
    lab.save_releases(keep)
    shutil.rmtree(os.path.join(lab.server, "assets", args.tag), ignore_errors=True)
    print(f"{args.tag} withdrawn")


def cmd_status(args):
    lab = need_lab(args)
    inst = lab.installed_manifest()
    print(f"lab: {lab.path}")
    print(f"sandbox: program {program_version()}, data {inst.get('data_version', '?')}")
    journal = os.path.join(lab.root, "user_data", "updates", "installed.json")
    try:
        with open(journal, encoding="utf-8") as f:
            for e in json.load(f):
                print(f"  installed: {e['name']} {e['version']} - {e['summary']}")
    except (OSError, ValueError):
        print("  no update installed yet")
    print("published:")
    for r in lab.releases() or []:
        print(f"  {r['tag']:<22} {r['published']}  {r['body'] or ''}")
    if not lab.releases():
        print("  (none)")
    files = lab.files_of(lab.upstream)
    ref = lab.last_data_manifest().get("files") or {}
    new = [p for p in files if ref.get(p, [None])[0] != files[p][0]]
    gone = [p for p in ref if p not in files]
    print(f"upstream vs the last data release: {len(new)} changed/new, {len(gone)} removed")
    for p in new[:10] + [f"(removed) {g}" for g in gone[:10]]:
        print(f"  {p}")


# ── the fake GitHub ─────────────────────────────────────────────────────
def make_handler(lab):
    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.0"

        def log_message(self, fmt, *a):
            print(f"[github] {self.command} {self.path} -> {a[1] if len(a) > 1 else ''}", flush=True)

        def _send(self, code, body=b"", ctype="application/octet-stream"):
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _file(self, path):
            if not os.path.isfile(path):
                return self._send(404, b"not found")
            self._send(200, open(path, "rb").read())

        def do_GET(self):
            path = self.path.split("?")[0]
            base = f"http://127.0.0.1:{self.server.server_address[1]}"
            parts = [p for p in path.split("/") if p]
            if len(parts) == 4 and parts[0] == "repos" and parts[3] == "releases":
                items = [{"tag_name": r["tag"], "name": r["name"], "body": r["body"],
                          "draft": False, "prerelease": False,
                          "html_url": f"{base}/releases/{r['tag']}",
                          "assets": [{"name": n, "size": _size(lab, r["tag"], n),
                                      "browser_download_url": f"{base}/assets/{r['tag']}/{n}"}
                                     for n in r["assets"]]}
                         for r in reversed(lab.releases())]
                return self._send(200, json.dumps(items).encode(), "application/json")
            if len(parts) == 3 and parts[0] == "assets":
                return self._file(os.path.join(lab.server, "assets", parts[1], parts[2]))
            if len(parts) >= 3 and parts[0] == "data":
                return self._data(parts[1], "/".join(parts[2:]))
            self._send(404, b"not found")

        def _data(self, version, rel):
            from urllib.parse import unquote
            rel = unquote(rel)
            mpath = os.path.join(lab.server, "assets", f"data-{version}", "data_manifest.json")
            if not os.path.isfile(mpath):
                return self._send(404, b"no such data release")
            with open(mpath, encoding="utf-8") as f:
                entry = json.load(f)["files"].get(rel)
            if not entry:
                return self._send(404, b"not in the manifest")
            blob = os.path.join(lab.server, "blobs", entry[0])
            if os.path.isfile(blob):
                return self._file(blob)
            up = os.path.join(lab.upstream, *rel.split("/"))
            if os.path.exists(up) and lab.sha(up) == entry[0]:
                return self._file(up)
            self._send(410, b"this file is no longer available")
    return Handler


def _size(lab, tag, name):
    try:
        return os.path.getsize(os.path.join(lab.server, "assets", tag, name))
    except OSError:
        return 0


def start_server(lab, port):
    srv = ThreadingHTTPServer(("127.0.0.1", port), make_handler(lab))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


def cmd_serve(args):
    lab = need_lab(args)
    start_server(lab, args.port)
    print(f"fake GitHub on http://127.0.0.1:{args.port} (Ctrl+C to stop)\n"
          f"run the mod with R08_UPDATE_API=http://127.0.0.1:{args.port} R08_DATA_UPDATES=1")
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        pass


def cmd_run(args):
    lab = need_lab(args)
    start_server(lab, args.port)
    try:
        os.remove(os.path.join(lab.root, "user_data", "updates", "last_check.json"))   # check at start
    except OSError:
        pass
    env = dict(os.environ, R08_UPDATE_API=f"http://127.0.0.1:{args.port}", R08_DATA_UPDATES="1")
    print(f"fake GitHub on :{args.port}; starting the mod on the sandbox {lab.root}")
    extra = [a for a in args.app_args if a != "--"]
    subprocess.call([sys.executable, os.path.join(lab.root, "run.py"), *extra], cwd=lab.root, env=env)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lab", help="lab folder (default ../rugby08-update-lab, or R08_UPDATE_LAB)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def cmd(name, fn, **kw):
        p = sub.add_parser(name, **kw)
        p.set_defaults(fn=fn)
        return p
    p = cmd("setup", cmd_setup)
    p.add_argument("--force", action="store_true")
    p.add_argument("--baseline", default="2026.11.01", help="data version the sandbox starts at")
    cmd("reset", cmd_reset)
    p = cmd("edit", cmd_edit)
    p.add_argument("path")
    p.add_argument("--text")
    p.add_argument("--from", dest="from_file")
    p.add_argument("--delete", action="store_true")
    p = cmd("add", cmd_add)
    p.add_argument("path")
    p.add_argument("--text")
    p = cmd("publish-data", cmd_publish_data)
    p.add_argument("version")
    p.add_argument("--notes")
    p.add_argument("--min-program")
    p.add_argument("--schema", type=int, default=1)
    p.add_argument("--corrupt")
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p = cmd("publish-program", cmd_publish_program)
    p.add_argument("version")
    p.add_argument("--notes")
    p.add_argument("--no-installer", action="store_true")
    p.add_argument("--bad-sums", action="store_true")
    p = cmd("unpublish", cmd_unpublish)
    p.add_argument("tag")
    cmd("status", cmd_status)
    p = cmd("serve", cmd_serve)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p = cmd("run", cmd_run)
    p.add_argument("--port", type=int, default=DEFAULT_PORT)
    p.add_argument("app_args", nargs=argparse.REMAINDER)
    args = ap.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
