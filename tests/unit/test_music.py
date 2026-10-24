"""ui/music.py download of the menu music missing from a source checkout
(e42a7b64): only missing files with a URL are offered, and a download is
written to <name>.part and renamed only once complete."""
import io
import json
import os

import pytest

from shared.config import config
from ui import music


@pytest.fixture
def music_dir(tmp_path, monkeypatch):
    manifest = {"tracks": [
        {"file": "a.mp3", "title": "A", "download_url": "http://x/a.mp3", "download_size": 3},
        {"file": "b.mp3", "title": "B", "download_url": "http://x/b.mp3"},
        {"file": "c.mp3", "title": "C"},                                    # no URL
    ], "loading_track": {"file": "load.mp3", "title": "L", "download_url": "http://x/l.mp3"}}
    (tmp_path / "tracks.json").write_text(json.dumps(manifest))
    (tmp_path / "b.mp3").write_bytes(b"already here")
    monkeypatch.setattr(config, "menu_music_directory", str(tmp_path))
    return tmp_path


def test_missing_downloads(music_dir):
    items = music.missing_downloads()
    assert [i["file"] for i in items] == ["a.mp3", "load.mp3"]
    assert items[0]["size"] == 3 and items[0]["dest"] == str(music_dir / "a.mp3")


def test_missing_downloads_unreadable_manifest(music_dir, monkeypatch):
    (music_dir / "tracks.json").write_text("{broken")
    assert music.missing_downloads() == []
    monkeypatch.setattr(config, "menu_music_directory", str(music_dir / "nope"))
    assert music.missing_downloads() == []


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def test_downloader_part_then_rename(music_dir, monkeypatch):
    seen_parts = []

    def fake_urlopen(req, timeout):
        assert req.get_header("User-agent") == music.DOWNLOAD_UA
        if "l.mp3" in req.full_url:
            raise OSError("HTTP 404")
        seen_parts.append(os.listdir(music_dir))
        return _Resp(b"MP3DATA")

    monkeypatch.setattr(music.urllib.request, "urlopen", fake_urlopen)
    results = []
    dl = music.MusicDownloader(music.missing_downloads())
    dl.finished.connect(lambda done, failed: results.append((done, failed)))
    dl._run()                                               # synchronously
    done, failed = results[0]
    assert done == ["a.mp3"]
    assert failed == [("L", "HTTP 404")]
    assert (music_dir / "a.mp3").read_bytes() == b"MP3DATA"
    assert not any(n.endswith(".part") for n in os.listdir(music_dir))
    assert not (music_dir / "load.mp3").exists()


def test_bundled_manifest_tracks_are_downloadable():
    """Every bundled track has a URL and a size, loading loop included."""
    with open(os.path.join(config.menu_music_directory, "tracks.json"), encoding="utf-8") as f:
        manifest = json.load(f)
    entries = manifest["tracks"] + ([manifest["loading_track"]] if manifest.get("loading_track") else [])
    assert entries
    for e in entries:
        assert e.get("download_url") and e.get("download_size"), e.get("file")
