#!/usr/bin/env python3
"""
packaging/gen_data_manifest.py — the data manifest online data updates use.

    python3 gen_data_manifest.py <staged data pack> <out dir> --data <data folder>
            --version 2026.10.24 --schema 1 [--min-program 0.4] [--repo owner/name]

Lists every file of the staged data pack (release.sh's rsync of the data
folder, so the same exclusions) with its sha256 and size, and the commit of
the data folder's git repository that holds them; the program downloads a
changed file from raw.githubusercontent.com/<repo>/<commit>/<prefix>/<path>
(app/updater/data.py).

So the manifest can never point at something that isn't there, it refuses
(exit 1) when a staged file isn't exactly the file of that commit: computed
git blob ids are compared with `git ls-tree`, so uncommitted or unpushed
data is caught here, not by users. Commit and push the data first.

Writes <stage>/MANIFEST.json (ships in the data pack: what an install has)
and <out>/data_manifest.json (the release asset), the same content.
--repo defaults to the data repository's GitHub origin; --prefix to the data
folder's path inside it ("data" today, "" once the data has its own repo).
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys

SKIP = {"MANIFEST.json", "VERSION"}


def git(cwd, *args):
    return subprocess.run(["git", "-C", cwd, *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def github_repo(cwd):
    url = git(cwd, "remote", "get-url", "origin")
    m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?/?$", url)
    if not m:
        sys.exit(f"origin is not a GitHub repository ({url}): pass --repo owner/name")
    return m.group(1)


def hashes(path):
    """(sha256, git blob sha1, size) of one file."""
    with open(path, "rb") as fh:
        data = fh.read()
    blob = hashlib.sha1(b"blob %d\0" % len(data) + data).hexdigest()
    return hashlib.sha256(data).hexdigest(), blob, len(data)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("stage")
    ap.add_argument("out")
    ap.add_argument("--data", required=True, help="the data folder (inside its git repository)")
    ap.add_argument("--version", required=True)
    ap.add_argument("--schema", type=int, required=True)
    ap.add_argument("--min-program", default="")
    ap.add_argument("--repo", default="")
    ap.add_argument("--prefix", default=None)
    ap.add_argument("--allow-mismatch", action="store_true",
                    help="write it anyway (local tests only: users would get checksum errors)")
    a = ap.parse_args(argv)

    data = os.path.abspath(a.data)
    commit = git(data, "rev-parse", "HEAD")
    prefix = git(data, "rev-parse", "--show-prefix").strip("/") if a.prefix is None else a.prefix.strip("/")
    repo = a.repo or github_repo(data)
    tree = {}
    for line in git(data, "ls-tree", "-r", "--full-name", commit, ".").splitlines():
        meta, _, path = line.partition("\t")
        mode, kind, obj = meta.split()
        if kind == "blob":
            rel = path[len(prefix) + 1:] if prefix and path.startswith(prefix + "/") else path
            tree[rel] = obj

    files, problems = {}, []
    for dirpath, dirnames, names in os.walk(a.stage):
        dirnames.sort()
        for name in sorted(names):
            full = os.path.join(dirpath, name)
            rel = os.path.relpath(full, a.stage).replace(os.sep, "/")
            if rel in SKIP:
                continue
            sha256, blob, size = hashes(full)
            if tree.get(rel) != blob:
                problems.append(rel + ("  (not in the commit)" if rel not in tree else "  (differs from the commit)"))
            files[rel] = [sha256, size]
    if not files:
        print(f"nothing staged in {a.stage}", file=sys.stderr)
        return 1
    if problems:
        print(f"{len(problems)} staged file(s) are not the files of commit {commit[:10]}:", file=sys.stderr)
        for p in problems[:20]:
            print("   " + p, file=sys.stderr)
        if len(problems) > 20:
            print(f"   … and {len(problems) - 20} more", file=sys.stderr)
        if not a.allow_mismatch:
            print("Commit (and push) the data, then build again.", file=sys.stderr)
            return 1

    manifest = {"format": 1, "data_version": a.version, "schema": a.schema, "min_program": a.min_program,
                "source": {"repo": repo, "commit": commit, "prefix": prefix},
                "files": files}
    text = json.dumps(manifest, separators=(",", ":"), sort_keys=True)
    os.makedirs(a.out, exist_ok=True)
    for dest in (os.path.join(a.stage, "MANIFEST.json"), os.path.join(a.out, "data_manifest.json")):
        with open(dest, "w", encoding="utf-8") as fh:
            fh.write(text)
    size = sum(s for _h, s in files.values())
    print(f"data manifest: {len(files)} files, {size / 1024 ** 2:.0f} MB, {repo}@{commit[:10]}/{prefix}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
