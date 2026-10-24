"""
ui/background.py — run one slow job (network, disk) off the GUI thread.

    job = Job(lambda report, cancelled: work(report, cancelled), parent)
    job.progress.connect(...)      # whatever `report(*args)` was called with
    job.done.connect(...)          # the job's return value
    job.failed.connect(...)        # the exception, as text (or "" when cancelled)
    job.start(); job.cancel()

The job gets `report(*args)` to send progress and `cancelled()` to poll.
Signals are emitted from the worker thread; Qt queues them to the
receiver's thread, as ui/music.py's MusicDownloader does.
"""
import threading

from PyQt5.QtCore import QObject, pyqtSignal

from shared.log import get_logger

log = get_logger(__name__)


class Job(QObject):
    progress = pyqtSignal(tuple)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, fn, parent=None, name="job"):
        super().__init__(parent)
        self._fn, self._name = fn, name
        self._cancel = threading.Event()
        self.running = False

    def start(self):
        self.running = True
        threading.Thread(target=self._run, name=self._name, daemon=True).start()

    def cancel(self):
        self._cancel.set()

    def cancelled(self):
        return self._cancel.is_set()

    def _run(self):
        try:
            result = self._fn(lambda *a: self.progress.emit(a), self.cancelled)
        except Exception as e:            # reported to the screen, never raised into Qt
            self.running = False
            if self.cancelled():
                self.failed.emit("")
            else:
                log.warning(f"{self._name}: {e}")
                self.failed.emit(str(e) or e.__class__.__name__)
            return
        self.running = False
        self.done.emit(result)
