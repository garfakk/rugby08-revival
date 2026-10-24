"""
app/updater/schedule.py — the once-a-day check, and checking both channels.

`check_all()` asks GitHub about the program and the data (both, one failing
doesn't stop the other) and remembers when, in user_data/updates/
last_check.json; `due()` says whether the startup check should run again
(once per CHECK_EVERY_H, and only with Settings > Check for updates on).
"""
import json
import os
import time
from dataclasses import dataclass

from . import data, program, sources

CHECK_EVERY_H = 24
STATE_FILE = "last_check.json"


@dataclass
class Result:
    program: object = None          # program.ProgramCheck
    data: object = None             # data.DataCheck
    program_error: str = ""
    data_error: str = ""
    checked_at: float = 0.0

    @property
    def anything(self):
        return bool((self.program and self.program.available) or (self.data and self.data.available))


def _state_path(updates_dir):
    return os.path.join(updates_dir, STATE_FILE)


def last_checked(updates_dir):
    try:
        with open(_state_path(updates_dir), encoding="utf-8") as fh:
            return float(json.load(fh).get("checked_at") or 0)
    except (OSError, ValueError, AttributeError):
        return 0.0


def due(updates_dir, now=None):
    now = time.time() if now is None else now
    return now - last_checked(updates_dir) >= CHECK_EVERY_H * 3600


def check_all(updates_dir, mod_data, program_version, schema, srcs=None, now=None):
    srcs = srcs or sources.load()
    res = Result(checked_at=time.time() if now is None else now)
    try:
        res.program = program.check(srcs["program"], program_version)
    except Exception as e:                    # network, GitHub, a bad release: say it, go on
        res.program_error = str(e)
    try:
        res.data = data.check(srcs["data"], mod_data, schema, program_version)
    except Exception as e:
        res.data_error = str(e)
    try:
        os.makedirs(updates_dir, exist_ok=True)
        with open(_state_path(updates_dir), "w", encoding="utf-8") as fh:
            json.dump({"checked_at": res.checked_at}, fh)
    except OSError:
        pass
    return res
