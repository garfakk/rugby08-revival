"""app/updater: online updates from GitHub. A fake server (net.opener)
stands for api.github.com, release assets and raw.githubusercontent.com.

Data: only what changed is downloaded, each file verified, applied through
app/updates.py (backups, undo), user files left alone, binaries and paths
leaving the pack refused, releases for another data schema not offered.
Program: the newest v-release, its installer verified against SHA256SUMS
before it may run."""
import hashlib
import io
import json
import os
import urllib.error

import pytest

from app.updater import data, net, program, releases, schedule, sources
from app.updates import Updates

REPO = "owner/game"


def sha(b):
    return hashlib.sha256(b).hexdigest()


class FakeServer:
    """url -> bytes (or an exception to raise). Counts requests."""

    def __init__(self):
        self.routes, self.hits = {}, []

    def __call__(self, request, timeout):
        url = request.full_url
        self.hits.append(url)
        value = self.routes.get(url)
        if value is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
        if isinstance(value, Exception):
            raise value
        return _Resp(value)


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture
def server(monkeypatch):
    s = FakeServer()
    monkeypatch.setattr(net, "opener", s)
    monkeypatch.setattr(net, "BACKOFF_S", 0)
    return s


def release(tag, assets=(), draft=False, prerelease=False):
    return {"tag_name": tag, "name": tag, "draft": draft, "prerelease": prerelease, "body": "notes",
            "html_url": f"https://github.com/{REPO}/releases/tag/{tag}",
            "assets": [{"name": n, "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/{n}",
                        "size": 10} for n in assets]}


def serve_releases(server, items):
    server.routes[f"{releases.API}/repos/{REPO}/releases?per_page=50"] = json.dumps(items).encode()


# ── data ────────────────────────────────────────────────────────────────
FILES_V1 = {"teams/a.json": b'{"a": 1}', "teams/a/kit.png": b"kit-v1", "players/p.json": b"{}",
            "old/gone.png": b"gone"}
FILES_V2 = {"teams/a.json": b'{"a": 2}', "teams/a/kit.png": b"kit-v1", "players/p.json": b"{}",
            "teams/b/new kit.png": b"new"}


def manifest_for(files, version, commit="c2", schema=1, min_program=""):
    return {"format": 1, "data_version": version, "schema": schema, "min_program": min_program,
            "source": {"repo": REPO, "commit": commit, "prefix": "data"},
            "files": {p: [sha(b), len(b)] for p, b in files.items()}}


@pytest.fixture
def install(tmp_path):
    """A data pack at version 1 with its MANIFEST.json, plus a user file."""
    root = tmp_path / "mod_data"
    for p, b in FILES_V1.items():
        f = root / p
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b)
    (root / "MANIFEST.json").write_text(json.dumps(manifest_for(FILES_V1, "2026.01.01", "c1")))
    (root / "teams" / "mine.png").write_bytes(b"user's own file")
    updates = Updates({"mod_data": str(root), "app_data": str(tmp_path / "app")},
                      str(tmp_path / "user_data" / "updates"), "0.4")
    return root, updates


def serve_data_release(server, files, version="2026.02.01", commit="c2", **kw):
    m = manifest_for(files, version, commit, **kw)
    tag = f"data-{version}"
    serve_releases(server, [release(tag, ["data_manifest.json"]), release("v9.9", ["x.exe"])])
    server.routes[f"https://github.com/{REPO}/releases/download/{tag}/data_manifest.json"] = json.dumps(m).encode()
    for p, b in files.items():
        server.routes[data.file_url(m, p)] = b
    return m


def test_data_plan_downloads_only_what_changed(server, install):
    root, _ = install
    m = serve_data_release(server, FILES_V2)
    found = data.check({"repo": REPO, "tag_prefix": "data-"}, str(root), 1, "0.4")
    assert found.available and found.current == "2026.01.01" and found.release.version == "2026.02.01"
    p = data.plan(found.manifest, str(root))
    assert sorted(x[0] for x in p.fetch) == ["teams/a.json", "teams/b/new kit.png"]
    assert p.remove == ["old/gone.png"]                       # listed before, gone now
    assert "teams/mine.png" not in p.remove                    # never listed: the user's
    assert p.bytes == len(FILES_V2["teams/a.json"]) + len(FILES_V2["teams/b/new kit.png"])
    assert m["files"]


def test_data_update_apply_and_undo(server, install, tmp_path):
    root, updates = install
    serve_data_release(server, FILES_V2)
    found = data.check({"repo": REPO, "tag_prefix": "data-"}, str(root), 1, "0.4")
    p = data.plan(found.manifest, str(root))
    staging = data.staging_dir(updates.journal_dir, found.manifest)
    seen = []
    data.download(p, staging, progress=lambda *a: seen.append(a))
    assert seen[-1][0] == seen[-1][1] == 2
    assert not any("kit.png" in h and "teams/a/" in h for h in server.hits)   # unchanged: not fetched
    entry = data.apply(p, staging, updates)
    assert entry["kind"] == "data"
    assert (root / "teams" / "a.json").read_bytes() == b'{"a": 2}'
    assert (root / "teams" / "b" / "new kit.png").read_bytes() == b"new"
    assert not (root / "old" / "gone.png").exists()
    assert (root / "teams" / "mine.png").exists()
    assert data.local_version(str(root)) == "2026.02.01"
    assert "data_version=2026.02.01" in (root / "VERSION").read_text()
    assert not os.path.exists(staging)
    # nothing left to do
    assert data.plan(found.manifest, str(root)).empty
    # undo puts version 1 back, removed file included
    updates.undo_last()
    assert (root / "teams" / "a.json").read_bytes() == b'{"a": 1}'
    assert (root / "old" / "gone.png").read_bytes() == b"gone"
    assert not (root / "teams" / "b" / "new kit.png").exists()
    assert data.local_version(str(root)) == "2026.01.01"


def test_missing_or_damaged_files_are_repaired(server, install):
    root, _ = install
    serve_data_release(server, FILES_V2)
    (root / "players" / "p.json").unlink()                         # missing
    (root / "teams" / "a" / "kit.png").write_bytes(b"truncated")   # wrong size
    m = data.check({"repo": REPO, "tag_prefix": "data-"}, str(root), 1, "0.4").manifest
    fetch = {x[0] for x in data.plan(m, str(root)).fetch}
    assert {"players/p.json", "teams/a/kit.png"} <= fetch


def test_install_without_manifest_hashes_once(server, install):
    root, _ = install
    (root / "MANIFEST.json").unlink()
    (root / "VERSION").write_text("data_version=2026.01.01\nschema=1\n")
    serve_data_release(server, FILES_V2)
    m = data.check({"repo": REPO, "tag_prefix": "data-"}, str(root), 1, "0.4").manifest
    hashed = []
    p = data.plan(m, str(root), progress=lambda i, n: hashed.append((i, n)))
    assert sorted(x[0] for x in p.fetch) == ["teams/a.json", "teams/b/new kit.png"]
    assert hashed and hashed[-1][0] == hashed[-1][1]
    assert p.remove == []                   # without a record of what was installed, nothing is removed


def test_checksum_mismatch_applies_nothing(server, install):
    root, updates = install
    m = serve_data_release(server, FILES_V2)
    server.routes[data.file_url(m, "teams/a.json")] = b"tampered"
    p = data.plan(m, str(root))
    staging = data.staging_dir(updates.journal_dir, m)
    with pytest.raises(data.DataUpdateError, match="checksum"):
        data.download(p, staging)
    assert (root / "teams" / "a.json").read_bytes() == b'{"a": 1}'
    assert not os.path.exists(os.path.join(staging, "mod_data", "teams", "a.json"))


def test_resume_reuses_verified_staged_files(server, install):
    root, updates = install
    m = serve_data_release(server, FILES_V2)
    p = data.plan(m, str(root))
    staging = data.staging_dir(updates.journal_dir, m)
    data.download(p, staging)
    server.hits.clear()
    data.download(p, staging)                    # second run: all already staged
    assert server.hits == []


def test_cancel_stops_the_download(server, install):
    root, updates = install
    m = serve_data_release(server, FILES_V2)
    p = data.plan(m, str(root))
    with pytest.raises(net.Cancelled):
        data.download(p, data.staging_dir(updates.journal_dir, m), cancel=lambda: True)
    assert (root / "teams" / "a.json").read_bytes() == b'{"a": 1}'


@pytest.mark.parametrize("path", ["../outside.json", "/abs.png", "C:/x.png", "tools/run.exe",
                                  "lib/hook.dll", "x/script.PS1", "MANIFEST.json"])
def test_data_update_never_writes_binaries_or_outside(server, install, path):
    root, _ = install
    files = dict(FILES_V2)
    files[path] = b"evil"
    m = serve_data_release(server, files)
    p = data.plan(m, str(root))
    assert path in p.refused
    assert all(x[0] != path for x in p.fetch)


def test_newer_schema_release_is_not_offered(server, install):
    root, _ = install
    serve_data_release(server, FILES_V2, schema=2, min_program="0.5")
    found = data.check({"repo": REPO, "tag_prefix": "data-"}, str(root), 1, "0.4")
    assert not found.available and found.blocked == "0.5"


def test_up_to_date_data(server, install):
    root, _ = install
    serve_data_release(server, FILES_V1, version="2026.01.01", commit="c1")
    assert not data.check({"repo": REPO, "tag_prefix": "data-"}, str(root), 1, "0.4").available


def test_file_urls_follow_the_manifest_source():
    m = manifest_for({"teams/b/new kit.png": b"x"}, "1", commit="abc")
    assert data.file_url(m, "teams/b/new kit.png") == \
        f"https://raw.githubusercontent.com/{REPO}/abc/data/teams/b/new%20kit.png"
    m["source"] = {"repo": "owner/data-only", "commit": "abc", "prefix": ""}     # after a repo split
    assert data.file_url(m, "teams/x.png") == "https://raw.githubusercontent.com/owner/data-only/abc/teams/x.png"
    m["source"] = {"base_url": "https://mirror.example/data/"}
    assert data.file_url(m, "teams/x.png") == "https://mirror.example/data/teams/x.png"


# ── releases / program ──────────────────────────────────────────────────
def test_latest_release_by_prefix(server):
    serve_releases(server, [release("v0.10"), release("v0.9"), release("v1.0", draft=True),
                            release("v0.11", prerelease=True), release("data-2027.01.01"),
                            release("video-1")])
    assert releases.latest(REPO, "v").version == "0.10"           # numbers, not text
    assert releases.latest(REPO, "v", current="0.10") is None
    assert releases.latest(REPO, "data-").version == "2027.01.01"


def test_program_installer_verified_before_it_can_run(server, tmp_path):
    exe = b"MZ installer bytes"
    name = "R08Revival_0.5_program_only.exe"
    serve_releases(server, [release("v0.5", [name, "SHA256SUMS"])])
    base = f"https://github.com/{REPO}/releases/download/v0.5/"
    server.routes[base + name] = exe
    server.routes[base + "SHA256SUMS"] = f"{sha(exe)}  {name}\n{sha(b'x')} *other.zip\n".encode()
    src = sources.DEFAULTS["program"] | {"repo": REPO}
    found = program.check(src, "0.4")
    assert found.available and found.installer[0] == name
    path = program.download(found, str(tmp_path))
    assert open(path, "rb").read() == exe
    calls = []
    program.launch(path, "C:/Games/R08Revival", popen=lambda args, **kw: calls.append(args))
    assert calls[0][0] == path and "/DIR=C:/Games/R08Revival" in calls[0] and "/RELAUNCH=1" in calls[0]
    # a tampered installer is refused
    os.remove(path)
    server.routes[base + name] = b"MZ something else"
    with pytest.raises(net.NetError, match="checksum"):
        program.download(found, str(tmp_path))
    assert not os.path.exists(path)


def test_program_installer_missing_from_sums_is_never_downloaded(server, tmp_path):
    name = "R08Revival_0.5_program_only.exe"
    serve_releases(server, [release("v0.5", [name, "SHA256SUMS"])])
    server.routes[f"https://github.com/{REPO}/releases/download/v0.5/SHA256SUMS"] = b""
    found = program.check(sources.DEFAULTS["program"] | {"repo": REPO}, "0.4")
    with pytest.raises(program.ProgramUpdateError):
        program.download(found, str(tmp_path))


def test_release_without_installer_points_to_its_page(server):
    serve_releases(server, [release("v0.5", ["notes.txt"])])
    found = program.check(sources.DEFAULTS["program"] | {"repo": REPO}, "0.4")
    assert found.available and found.problem and found.installer is None


def test_rate_limit_is_explained(server):
    server.routes[f"{releases.API}/repos/{REPO}/releases?per_page=50"] = urllib.error.HTTPError(
        "u", 403, "Forbidden", {"X-RateLimit-Remaining": "0", "X-RateLimit-Reset": "0"}, None)
    with pytest.raises(net.NetError, match="limit"):
        releases.latest(REPO, "v")


# ── sources / schedule ──────────────────────────────────────────────────
def test_sources_shipped_file_then_config_overrides(tmp_path):
    (tmp_path / "update_sources.json").write_text(json.dumps({"data": {"repo": "owner/shipped"}}))
    ini = tmp_path / "config.ini"
    ini.write_text("[Updates]\ndata_tag_prefix = season-\nprogram_repo = owner/prog\n")
    s = sources.load(str(tmp_path), str(ini))
    assert s["data"]["repo"] == "owner/shipped" and s["data"]["tag_prefix"] == "season-"
    assert s["program"]["repo"] == "owner/prog" and s["program"]["installer"]


def test_once_a_day(server, install, tmp_path):
    root, updates = install
    serve_data_release(server, FILES_V2)
    d = updates.journal_dir
    assert schedule.due(d)
    srcs = {"program": sources.DEFAULTS["program"] | {"repo": REPO},
            "data": sources.DEFAULTS["data"] | {"repo": REPO}}
    res = schedule.check_all(d, str(root), "0.4", 1, srcs=srcs, now=1000.0)
    assert res.data.available and res.anything
    assert res.program.release.version == "9.9" and res.program.problem      # no installer in it
    assert not schedule.due(d, now=1000.0 + 3600)
    assert schedule.due(d, now=1000.0 + 25 * 3600)


def test_one_channel_failing_does_not_hide_the_other(server, install):
    root, updates = install
    serve_data_release(server, FILES_V2)
    srcs = {"program": sources.DEFAULTS["program"] | {"repo": "owner/missing"},
            "data": sources.DEFAULTS["data"] | {"repo": REPO}}
    res = schedule.check_all(updates.journal_dir, str(root), "0.4", 1, srcs=srcs)
    assert res.program_error and res.data.available
