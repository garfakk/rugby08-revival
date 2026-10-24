"""screens/updates.py, Online: the program and data cards against a fake
GitHub (net.opener), from check to applied data update and to the program
installer being started (stubbed) with the mod closing."""
import hashlib
import io
import json
import time
import urllib.error

import pytest

from app.updater import data as data_update
from app.updater import net, program, releases

pytestmark = pytest.mark.qt
REPO = "owner/game"


def sha(b):
    return hashlib.sha256(b).hexdigest()


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


@pytest.fixture
def github(monkeypatch):
    routes = {}

    def opener(request, timeout):
        value = routes.get(request.full_url)
        if value is None:
            raise urllib.error.HTTPError(request.full_url, 404, "Not Found", {}, None)
        return _Resp(value)
    monkeypatch.setattr(net, "opener", opener)
    monkeypatch.setattr(net, "BACKOFF_S", 0)
    return routes


def _asset(tag, name):
    return {"name": name, "size": 10, "browser_download_url": f"https://github.com/{REPO}/releases/download/{tag}/{name}"}


@pytest.fixture
def screen(qapp, tmp_path, github):
    from app.updates import Updates
    from screens.updates import UpdatesScreen
    mod = tmp_path / "mod_data"
    (mod / "teams").mkdir(parents=True)
    (mod / "teams" / "a.json").write_bytes(b"v1")
    old = {"format": 1, "data_version": "2026.01.01", "schema": 1,
           "source": {"repo": REPO, "commit": "c1", "prefix": "data"},
           "files": {"teams/a.json": [sha(b"v1"), 2]}}
    (mod / "MANIFEST.json").write_text(json.dumps(old))
    new_files = {"teams/a.json": b"v2!", "teams/b.png": b"png"}
    new = dict(old, data_version="2026.02.01",
               source={"repo": REPO, "commit": "c2", "prefix": "data"},
               files={p: [sha(b), len(b)] for p, b in new_files.items()})
    exe = b"MZ installer"
    github[f"{releases.API}/repos/{REPO}/releases?per_page=50"] = json.dumps([
        {"tag_name": "v0.5", "body": "## Better things\n- faster", "html_url": "https://x/v0.5",
         "assets": [_asset("v0.5", "R08Revival_0.5_program_only.exe"), _asset("v0.5", "SHA256SUMS")]},
        {"tag_name": "data-2026.02.01", "body": "New season", "assets": [_asset("data-2026.02.01",
                                                                                 "data_manifest.json")]},
    ]).encode()
    base = f"https://github.com/{REPO}/releases/download/"
    github[base + "v0.5/R08Revival_0.5_program_only.exe"] = exe
    github[base + "v0.5/SHA256SUMS"] = f"{sha(exe)}  R08Revival_0.5_program_only.exe\n".encode()
    github[base + "data-2026.02.01/data_manifest.json"] = json.dumps(new).encode()
    for p, b in new_files.items():
        github[data_update.file_url(new, p)] = b

    quits = []
    s = UpdatesScreen(lambda: None, Updates({"mod_data": str(mod), "app_data": str(tmp_path / "app")},
                                            str(tmp_path / "updates"), "0.4"),
                      on_quit=lambda: quits.append(True))
    s.quits, s.mod = quits, mod
    s.program_version, s.schema = "0.4", 1
    s.program_supported = s.data_supported = True
    s.sources = {"program": {"repo": REPO, "tag_prefix": "v",
                             "installer": "R08Revival_{version}_program_only.exe", "checksums": "SHA256SUMS"},
                 "data": {"repo": REPO, "tag_prefix": "data-", "manifest": "data_manifest.json"}}
    s.resize(1500, 900)
    s.show()
    s.on_show()
    yield s
    s.close()


def _until(qapp, predicate, timeout=5.0):
    end = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < end, "timed out"
        qapp.processEvents()
        time.sleep(0.01)


def _buttons(card):
    return [b.text() for b in card.buttons if b.isVisible()]


def test_check_then_update_data(qapp, screen):
    assert "Not checked yet" in screen.data_card.detail.text()
    screen.check_now()
    _until(qapp, lambda: "UPDATE DATA" in _buttons(screen.data_card))
    assert "2026.01.01" in screen.data_card.headline.text() and "2026.02.01" in screen.data_card.headline.text()
    assert "2 files to download" in screen.data_card.detail.text()
    assert "0.4" in screen.program_card.headline.text() and "0.5" in screen.program_card.headline.text()
    assert "Better things" in screen.program_card.detail.text()            # release notes, marks dropped
    screen.data_card.buttons[0].click()
    _until(qapp, lambda: "Installed" in screen.data_card.detail.text())
    assert (screen.mod / "teams" / "a.json").read_bytes() == b"v2!"
    assert (screen.mod / "teams" / "b.png").read_bytes() == b"png"
    assert data_update.local_version(str(screen.mod)) == "2026.02.01"
    assert screen.undo_btn.isEnabled()                                      # undo, as for any update


def test_program_update_downloads_verifies_and_hands_over(qapp, screen, monkeypatch):
    launched = []
    monkeypatch.setattr(program, "launch", lambda path, app_dir: launched.append((path, app_dir)))
    screen.check_now()
    _until(qapp, lambda: "DOWNLOAD && INSTALL" in _buttons(screen.program_card))
    screen.program_card.buttons[0].click()
    _until(qapp, lambda: screen._dialog is not None)
    screen._dialog.choose("ok")
    assert launched and launched[0][0].endswith("R08Revival_0.5_program_only.exe")
    assert screen.quits == [True]


def test_from_source_only_points_to_git(qapp, screen):
    screen.program_supported = screen.data_supported = False
    screen.check_now()
    _until(qapp, lambda: "git" in screen.data_card.detail.text())
    assert "git" in screen.program_card.detail.text()
    assert _buttons(screen.program_card) == ["RELEASE PAGE"]
    assert _buttons(screen.data_card) == []


def test_offline_says_so(qapp, screen, github):
    github.clear()
    screen.check_now()
    _until(qapp, lambda: "Couldn't check" in screen.data_card.detail.text())
    assert "Couldn't check" in screen.program_card.detail.text()
    assert screen.check_btn.isEnabled()


def test_startup_notice(qapp, screen):
    from app.updater import schedule
    from ui.update_notice import UpdateNotice
    res = schedule.check_all(screen.updates.journal_dir, str(screen.mod), "0.4", 1, srcs=screen.sources)
    notice = UpdateNotice(screen)
    notice.set_result(res)
    assert notice.has_news and "PROGRAM 0.5" in notice._line and "DATA 2026.02.01" in notice._line
    notice.set_result(schedule.Result())
    assert not notice.has_news
