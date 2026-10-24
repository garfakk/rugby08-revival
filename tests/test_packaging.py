"""Release preflight checks (packaging/release.sh) that need no build."""
import json
import os
import re

from conftest import SRC

MUSIC = os.path.join(SRC, "assets", "audio", "menu")
MANIFEST = os.path.join(SRC, "packaging", "audio_manifest.sha256")


def test_version_readable_by_release_script():
    """release.sh reads both values with sed: keep them simple assignments."""
    with open(os.path.join(SRC, "shared", "version.py"), encoding="utf-8") as f:
        text = f.read()
    assert re.search(r'^APP_VERSION = "[^"]+"$', text, re.M)
    assert re.search(r"^DATA_SCHEMA *= *[0-9]+$", text, re.M)


def test_every_menu_track_downloadable_and_in_manifest():
    with open(os.path.join(MUSIC, "tracks.json"), encoding="utf-8") as f:
        tracks = json.load(f)
    tracks = tracks.get("tracks", tracks) if isinstance(tracks, dict) else tracks
    with open(MANIFEST, encoding="utf-8") as f:
        listed = {line.split()[-1].lstrip("*") for line in f if line.strip()}
    problems = []
    for t in tracks:
        name = t.get("file") or t.get("filename") or ""
        if not t.get("download_url") or not t.get("download_size"):
            problems.append(f"{name}: no download_url/download_size")
        if name not in listed:
            problems.append(f"{name}: not in audio_manifest.sha256")
    assert not problems, problems


def test_bundled_dlls_present():
    for name in ("d3d8.dll", "rugby08patches.dll"):
        assert os.path.isfile(os.path.join(SRC, "assets", "static_files", name)), name
