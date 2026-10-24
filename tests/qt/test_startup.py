"""Start-up (e0c4a86a "fix slow app startup"): the data is built behind the
intro splash in its still moments, the splash waits for it, and the window
survives being closed or resized before it is done."""
import os
import subprocess
import sys
import time

import pytest

from conftest import ROOT, TESTS

pytestmark = pytest.mark.qt


class _Clock:
    def __init__(self, t):
        self.t = t

    def elapsed(self):
        return self.t


@pytest.mark.parametrize("t,ms,quiet", [
    (0, 300, True), (100, 400, False),            # first still window: 0-400 ms
    (1500, 400, True), (1000, 100, False),
    (3900, 1700, True), (3900, 1800, False),
    (6000, 5000, True),                           # fading out: the app holds it
])
def test_splash_quiet_windows(qapp, t, ms, quiet):
    from ui.intro import IntroSplash
    s = IntroSplash()
    s._clock = _Clock(t)
    assert s.quiet_for(ms) is quiet
    s._skipped = True
    assert s.quiet_for(10 ** 6)                   # skipped: nothing to protect
    s.deleteLater()


def test_splash_waits_until_ready(qapp, qtbot):
    from ui.intro import IntroSplash
    s = IntroSplash()
    qtbot.addWidget(s)
    ready = {"v": False}
    s.ready = lambda: ready["v"]
    finished = []
    s.finished.connect(lambda: finished.append(True))
    s._fade_out_when_ready()                      # end of the held beat
    qtbot.wait(100)
    assert not finished                           # still building behind it
    assert s._curtain_fx.opacity() == 0.0         # title still up, no blank screen
    assert s.quiet_for(10 ** 6)                   # held: build steps may block
    ready["v"] = True
    qtbot.waitUntil(lambda: bool(finished), timeout=2000)


def test_close_and_resize_before_boot(qapp):
    """track_medal is None and screen_ingame doesn't exist yet."""
    from main import MainWindow
    w = MainWindow()
    w.resize(1100, 700)
    qapp.processEvents()
    w.close()
    deadline = time.monotonic() + 60
    while not w._boot_done and time.monotonic() < deadline:   # let the boot finish cleanly
        qapp.processEvents()
        time.sleep(0.005)
    w.deleteLater()
    qapp.processEvents()


@pytest.mark.slow
def test_selftest_subprocess():
    """`--selftest` (the release smoke test) builds the whole UI and exits 0,
    run in the same isolated config as the tests."""
    env = dict(os.environ, QT_QPA_PLATFORM="offscreen")
    proc = subprocess.run([sys.executable, os.path.join(TESTS, "qt", "selftest_launcher.py"),
                           "--selftest", "--log-level", "ERROR"],
                          cwd=ROOT, env=env, capture_output=True, text=True, timeout=150)
    out = proc.stdout + proc.stderr
    assert proc.returncode == 0, out[-3000:]
    assert "SELFTEST OK" in out and "Traceback" not in out
