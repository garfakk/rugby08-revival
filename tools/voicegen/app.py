"""
voicegen/app.py — make commentary name clips in the stock commentator's voice
==============================================================================
A list of the surnames the players have no clip for (the most used first),
and for the one picked: takes made in the stock voice, played as the game
will play them, and the one to keep. "Make all" goes down the list on its
own and keeps the best take of each (marked "auto" so it can be checked).

The clips go to the data pack, <data>/commentary/<id>_<Name>.dat; the mod
adds them to the game before a match and gives them to the players whose
surname they say (see src/shared/commentary.py, src/backend/commentary_deploy.py).

    tools/voicegen/.venv/bin/python tools/voicegen/app.py
"""
import collections
import contextlib
import io
import json
import os
import sys
import tempfile
import traceback

import engine                                   # sets up the mod's import paths
from shared import commentary
from shared.config import config

from PySide6.QtCore import QObject, QThread, Qt, QUrl, Signal, Slot
from PySide6.QtGui import QFont
from PySide6.QtMultimedia import QSoundEffect
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QProgressBar, QPushButton,
                               QVBoxLayout, QWidget)

FOLDER = os.path.join(config.pack_directory, commentary.CUSTOM_FOLDER)
TAKES = 3


def _key(name):
    return commentary._key(name)


def surnames():
    """[(surname, players, current clip ids)] of the players' surnames,
    from players.json."""
    path = os.path.join(config.directory_players, "players.json")
    with open(path, encoding="utf-8") as f:
        players = json.load(f)
    groups = {}
    for p in players.values():
        last = (p.get("last_name") or "").strip()
        if not _key(last):
            continue
        g = groups.setdefault(_key(last), [collections.Counter(), 0, collections.Counter()])
        g[0][last] += 1
        g[1] += 1
        c = str(p.get("commentary") or "")
        g[2][int(c) if c.isdigit() else 0] += 1
    return [(g[0].most_common(1)[0][0], g[1], g[2]) for g in groups.values()]


# ── the worker: one thread owns the model ────────────────────────────────
class Worker(QObject):
    status = Signal(str)
    takes = Signal(str, list)                 # name, [Take]
    saved = Signal(str, int)                  # name, id
    progress = Signal(int, int)               # done, total
    failed = Signal(str)
    finished_batch = Signal()

    def __init__(self):
        super().__init__()
        self.engine = engine.Engine()
        self.stop = False

    def _load(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.engine.load(self.status.emit)

    @Slot(str, str, int)
    def make(self, name, say_as, first_seed):
        try:
            self._load()
            self.status.emit(f"Making {name}…")
            with contextlib.redirect_stdout(io.StringIO()):
                takes = self.engine.make(name, say_as, TAKES, first_seed)
            self.takes.emit(name, takes)
            self.status.emit("")
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e))

    @Slot(list)
    def batch(self, names):
        self.stop = False
        try:
            self._load()
            for i, name in enumerate(names):
                if self.stop:
                    break
                self.progress.emit(i, len(names))
                self.status.emit(f"Making {name}…")
                with contextlib.redirect_stdout(io.StringIO()):
                    takes = self.engine.make(name, "", 2)
                cid, _ = engine.save(takes[0], name, FOLDER)
                notes = engine.read_notes(FOLDER)
                notes[str(cid)]["auto"] = True
                engine.write_notes(FOLDER, notes)
                self.saved.emit(name, cid)
            self.progress.emit(len(names), len(names))
        except Exception as e:
            traceback.print_exc()
            self.failed.emit(str(e))
        self.status.emit("")
        self.finished_batch.emit()


class Window(QMainWindow):
    ask_make = Signal(str, str, int)
    ask_batch = Signal(list)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Commentary voices")
        self.resize(900, 600)
        self._tmp = tempfile.mkdtemp(prefix="voicegen-")
        self._sound = QSoundEffect(self)
        self._sound.setVolume(0.9)
        self._takes = []
        self._seed = 0
        self._busy = False

        self.stock_names = {c: n for c, n in commentary.names().items()
                            if c < commentary.CUSTOM_BASE}
        self.stock_keys = {_key(n) for n in self.stock_names.values()}
        self.rows = surnames()

        root = QWidget()
        self.setCentralWidget(root)
        lay = QHBoxLayout(root)

        # left: the names
        left = QVBoxLayout()
        lay.addLayout(left, 2)
        self.search = QLineEdit(placeholderText="Search")
        self.search.textChanged.connect(self.refill)
        left.addWidget(self.search)
        tabs = QHBoxLayout()
        self.tab_todo = QPushButton("To make", checkable=True, checked=True)
        self.tab_done = QPushButton("Made", checkable=True)
        for b in (self.tab_todo, self.tab_done):
            b.clicked.connect(self._tab)
            tabs.addWidget(b)
        left.addLayout(tabs)
        self.list = QListWidget()
        self.list.currentItemChanged.connect(self.pick)
        left.addWidget(self.list)
        bottom = QHBoxLayout()
        self.make_all = QPushButton("Make all")
        self.make_all.clicked.connect(self.batch)
        self.bar = QProgressBar(visible=False)
        bottom.addWidget(self.make_all)
        bottom.addWidget(self.bar, 1)
        left.addLayout(bottom)

        # right: the picked name
        right = QVBoxLayout()
        lay.addLayout(right, 3)
        self.title = QLabel()
        f = QFont()
        f.setPointSize(20)
        f.setBold(True)
        self.title.setFont(f)
        right.addWidget(self.title)
        self.now = QHBoxLayout()
        right.addLayout(self.now)
        say = QHBoxLayout()
        self.say_as = QLineEdit()
        self.say_as.setToolTip("Spell it the way it sounds, e.g. Ntamack -> Un-ta-mack")
        self.say_as.returnPressed.connect(self.make)
        self.make_btn = QPushButton("Make takes")
        self.make_btn.clicked.connect(self.make)
        say.addWidget(QLabel("Say it as"))
        say.addWidget(self.say_as, 1)
        say.addWidget(self.make_btn)
        right.addLayout(say)
        self.takes_box = QVBoxLayout()
        right.addLayout(self.takes_box)
        right.addStretch(1)
        self.status = QLabel()
        self.status.setStyleSheet("color: gray")
        right.addWidget(self.status)

        # the model's thread
        self.thread = QThread(self)
        self.worker = Worker()
        self.worker.moveToThread(self.thread)
        self.ask_make.connect(self.worker.make)
        self.ask_batch.connect(self.worker.batch)
        self.worker.status.connect(self.status.setText)
        self.worker.takes.connect(self.got_takes)
        self.worker.saved.connect(self.got_saved)
        self.worker.progress.connect(self.got_progress)
        self.worker.failed.connect(self.got_failed)
        self.worker.finished_batch.connect(self.batch_done)
        self.thread.start()

        self.refill()

    # ── list ─────────────────────────────────────────────────────────────
    def made(self):
        return {_key(n): (c, n) for c, (n, _) in commentary.custom_clips(FOLDER).items()}

    def todo(self):
        made = self.made()
        rows = [r for r in self.rows if _key(r[0]) not in self.stock_keys and _key(r[0]) not in made]
        rows.sort(key=lambda r: (-r[1], r[0].lower()))
        return rows

    def _tab(self):
        done = self.sender() is self.tab_done
        self.tab_done.setChecked(done)
        self.tab_todo.setChecked(not done)
        self.refill()

    def refill(self):
        cur = self.list.currentItem().data(Qt.UserRole) if self.list.currentItem() else None
        self.list.blockSignals(True)
        self.list.clear()
        q = self.search.text().strip().lower()
        if self.tab_done.isChecked():
            notes = engine.read_notes(FOLDER)
            rows = sorted(((n, c) for c, (n, _) in commentary.custom_clips(FOLDER).items()),
                          key=lambda r: r[0].lower())
            for name, cid in rows:
                if q and q not in name.lower():
                    continue
                auto = notes.get(str(cid), {}).get("auto")
                it = QListWidgetItem(name + ("   · auto" if auto else ""))
                it.setData(Qt.UserRole, name)
                self.list.addItem(it)
        else:
            for name, count, _ in self.todo():
                if q and q not in name.lower():
                    continue
                it = QListWidgetItem(f"{name}   · {count}" if count > 1 else name)
                it.setData(Qt.UserRole, name)
                self.list.addItem(it)
        row = next((i for i in range(self.list.count())
                    if self.list.item(i).data(Qt.UserRole) == cur), 0)
        if self.list.count():
            self.list.setCurrentRow(row)
        self.list.blockSignals(False)
        self.pick(self.list.currentItem())

    # ── picked name ──────────────────────────────────────────────────────
    def name(self):
        it = self.list.currentItem()
        return it.data(Qt.UserRole) if it else ""

    def pick(self, item, _prev=None):
        name = item.data(Qt.UserRole) if item else ""
        self.title.setText(name)
        notes = engine.read_notes(FOLDER)
        made = self.made().get(_key(name))
        self.say_as.setText(notes.get(str(made[0]), {}).get("say_as", "") if made else "")
        self.say_as.setPlaceholderText(name)
        self._takes = []
        self._seed = 0
        self._show_now(name)
        self._show_takes()

    def _clear(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.setParent(None)
                w.deleteLater()
            elif item.layout():
                self._clear(item.layout())

    def _show_now(self, name):
        self._clear(self.now)
        if not name:
            return
        made = self.made().get(_key(name))
        if made:
            self.now.addWidget(QLabel("In game"))
            self.now.addWidget(self._play_btn(lambda: commentary.wav_bytes(made[0], FOLDER)))
            rm = QPushButton("Remove")
            rm.clicked.connect(lambda: self.remove(made[0]))
            self.now.addWidget(rm)
        else:
            row = next((r for r in self.rows if _key(r[0]) == _key(name)), None)
            used = [c for c, _ in row[2].most_common() if c in self.stock_names] if row else []
            if used:
                self.now.addWidget(QLabel(f"Now says “{self.stock_names[used[0]]}”"))
                self.now.addWidget(self._play_btn(lambda: commentary.wav_bytes(used[0])))
            else:
                self.now.addWidget(QLabel("Now says nothing"))
        self.now.addStretch(1)

    def _play_btn(self, wav):
        b = QPushButton("▶")
        b.setFixedWidth(40)
        b.clicked.connect(lambda: self.play(wav()))
        return b

    def play(self, data):
        if not data:
            return
        self._sound.stop()
        path = os.path.join(self._tmp, f"p{id(data)}.wav")
        with open(path, "wb") as f:
            f.write(data)
        self._sound.setSource(QUrl.fromLocalFile(path))
        self._sound.play()

    def _show_takes(self):
        self._clear(self.takes_box)
        for i, take in enumerate(self._takes):
            row = QHBoxLayout()
            row.addWidget(self._play_btn(lambda t=take: t.wav_bytes()))
            row.addWidget(QLabel(f"Take {i + 1}" + ("   · best match" if i == 0 else "")))
            row.addStretch(1)
            use = QPushButton("Use")
            use.clicked.connect(lambda _=False, t=take: self.use(t))
            row.addWidget(use)
            self.takes_box.addLayout(row)
        if self._takes:
            more = QPushButton("More takes")
            more.clicked.connect(self.make)
            self.takes_box.addWidget(more, 0, Qt.AlignLeft)

    def make(self):
        name = self.name()
        if not name or self._busy:
            return
        self._busy = True
        self.make_btn.setEnabled(False)
        self.ask_make.emit(name, self.say_as.text().strip(), self._seed)
        self._seed += TAKES

    @Slot(str, list)
    def got_takes(self, name, takes):
        self._busy = False
        self.make_btn.setEnabled(True)
        if name != self.name():
            return
        self._takes = sorted(self._takes + takes, key=lambda t: -t.score)
        self._show_takes()
        if self._takes:
            self.play(self._takes[0].wav_bytes())

    def use(self, take):
        name = self.name()
        engine.save(take, name, FOLDER, self.say_as.text().strip())
        self._takes = []
        self.refill()

    def remove(self, cid):
        engine.delete(cid, FOLDER)
        self.refill()

    # ── make all ─────────────────────────────────────────────────────────
    def batch(self):
        if self.make_all.text() == "Stop":
            self.worker.stop = True
            return
        names = [r[0] for r in self.todo()]
        if not names or self._busy:
            return
        self._busy = True
        self.make_all.setText("Stop")
        self.bar.setVisible(True)
        self.ask_batch.emit(names)

    @Slot(str, int)
    def got_saved(self, name, cid):
        pass

    @Slot(int, int)
    def got_progress(self, done, total):
        self.bar.setMaximum(total)
        self.bar.setValue(done)
        self.bar.setFormat(f"{done} / {total}")

    @Slot()
    def batch_done(self):
        self._busy = False
        self.make_all.setText("Make all")
        self.bar.setVisible(False)
        self.refill()

    @Slot(str)
    def got_failed(self, text):
        self._busy = False
        self.make_btn.setEnabled(True)
        self.status.setText("Failed: " + text)

    def closeEvent(self, e):
        self.worker.stop = True
        self.thread.quit()
        self.thread.wait(3000)
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    w = Window()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
