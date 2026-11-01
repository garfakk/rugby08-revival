"""
ui/sound_preview.py — play a short WAV clip on demand
=========================================================
QSoundEffect wants a file, so each clip is written once to a per-session
temp folder and replayed from there. Safe to call when the platform has no
working audio: play() then just does nothing.
"""
import os
import shutil
import tempfile
import atexit

from PyQt5.QtCore import QObject, QUrl

from shared.log import get_logger

log = get_logger(__name__)

try:
    from PyQt5.QtMultimedia import QSoundEffect
except ImportError:                     # no QtMultimedia in this build
    QSoundEffect = None


class SoundPreview(QObject):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._dir = None
        self._effect = None

    def _folder(self):
        if self._dir is None:
            self._dir = tempfile.mkdtemp(prefix="r08_clips_")
            atexit.register(shutil.rmtree, self._dir, True)
        return self._dir

    def play(self, key, make_wav):
        """Play the clip cached as `key`; `make_wav()` gives its WAV bytes
        (or None) the first time."""
        if QSoundEffect is None:
            return False
        path = os.path.join(self._folder(), f"{key}.wav")
        if not os.path.isfile(path):
            data = make_wav()
            if not data:
                return False
            try:
                with open(path, "wb") as f:
                    f.write(data)
            except OSError as e:
                log.warning("sound preview: cannot write %s: %s", path, e)
                return False
        if self._effect is not None:
            self._effect.stop()
            self._effect.deleteLater()
        self._effect = QSoundEffect(self)
        self._effect.setSource(QUrl.fromLocalFile(path))
        self._effect.play()
        return True

    def stop(self):
        if self._effect is not None:
            self._effect.stop()
