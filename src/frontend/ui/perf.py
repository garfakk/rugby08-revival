"""
ui/perf.py — frame-stall monitor, for finding what makes animations stutter.

Opt-in: R08_PERF=1 (or perf.start()). A 16 ms heartbeat timer runs on the GUI
thread; a watchdog thread notices when it stops beating (the event loop is
busy) and samples the GUI thread's Python stack every few ms meanwhile. Each
stall over STALL_MS is logged with its length and the frames it spent most
samples in, so a lag reads as "120 ms in team_sheet.py:_rebuild".
"""
import collections
import logging
import os
import sys
import threading
import time

from PyQt5.QtCore import QTimer

log = logging.getLogger("perf")

STALL_MS = 34                 # two frames at 60 Hz
SAMPLE_MS = 2

_monitor = None


class _Monitor:
    def __init__(self, sink=None):
        self.sink = sink or (lambda line: log.warning(line))
        self.beat = time.perf_counter()
        self.gui_thread = threading.get_ident()
        self.stalls = []                       # [(ms, [(frame, n)])]
        self._timer = QTimer()
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._on_beat)
        self._timer.start()
        self._stop = False
        threading.Thread(target=self._watch, name="perf-watch", daemon=True).start()

    def _on_beat(self):
        self.beat = time.perf_counter()

    def _sample(self):
        frame = sys._current_frames().get(self.gui_thread)
        if frame is None:
            return None
        # a plain frame walk: traceback.extract_stack reads source lines, and
        # the time it holds the GIL would show up as the GUI's own stall
        out = []
        while frame is not None and len(out) < 40:
            code = frame.f_code
            fn = code.co_filename
            if "site-packages" not in fn and "/lib/python" not in fn and not fn.startswith("<"):
                out.append(f"{os.path.basename(fn)}:{frame.f_lineno} {code.co_name}")
            frame = frame.f_back
        out.reverse()
        return tuple(out[-14:])

    def _watch(self):
        samples = collections.Counter()
        start = None
        while not self._stop:
            time.sleep(SAMPLE_MS / 1000)
            beat = self.beat
            gap = (time.perf_counter() - beat) * 1000
            if gap > 20:
                if start is None:
                    start = beat
                    samples.clear()
                s = self._sample()
                if s:
                    samples[s] += 1
            elif start is not None:
                ms = (self.beat - start) * 1000 - 16
                if ms >= STALL_MS:
                    self._report(ms, samples)
                start = None

    def _report(self, ms, samples):
        # the deepest frames shared by most samples tell where the time went
        leaf = collections.Counter()
        for stack, n in samples.items():
            for f in set(stack):
                leaf[f] += n
        total = sum(samples.values()) or 1
        top = samples.most_common(1)[0][0] if samples else ()
        self.stalls.append((ms, top, leaf.most_common(12), total))
        self.sink(f"STALL {ms:.0f} ms  (samples {total})")
        for line in top[-8:]:
            self.sink(f"    {line}")

    def stop(self):
        self._stop = True
        self._timer.stop()


def start(sink=None):
    global _monitor
    if _monitor is None:
        _monitor = _Monitor(sink)
    return _monitor


def start_if_requested():
    if os.environ.get("R08_PERF"):
        return start()
    return None
