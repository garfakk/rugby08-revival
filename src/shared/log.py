"""shared/log.py — logging for the whole mod.

    from shared.log import get_logger
    log = get_logger(__name__)
    log.info("Launched process %s", pid)

Levels, from most to least verbose:
  DEBUG    traces for diagnosing a problem: per-player writes, memory reads, the
           loading-bar trace, file-by-file copies. Off by default.
  INFO     milestones a user of the mod would want in a bug report: match
           launched, game screens reached, result read, files prepared.
  WARNING  something is wrong but the mod carried on with a fallback (missing
           image, invalid value replaced by a default).
  ERROR    an operation failed (file write, process start, archive read).
  OFF      nothing is logged.

Set the level with, in order of priority: `setup_logging(level)` (the
`--log-level` command-line option of the entry points), the R08_LOG_LEVEL
environment variable, `log_level` in config.ini's [Options], else INFO (OFF in the released exe).
`log_file` in [Options] additionally writes a rotating log file. Output goes to
stderr; the released exe redirects that to R08Revival.log (see frontend/main.py),
keeping the previous run's as R08Revival.prev.log.
"""
import logging
import logging.handlers
import os
import sys

ROOT = "r08"
OFF = logging.CRITICAL + 10
logging.addLevelName(OFF, "OFF")
# Released exe: nothing logged until the user picks a level in Settings. Source runs keep INFO.
DEFAULT_LEVEL = "OFF" if getattr(sys, "frozen", False) else "INFO"
LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
          "WARNING": logging.WARNING, "WARN": logging.WARNING,
          "ERROR": logging.ERROR, "CRITICAL": logging.CRITICAL, "OFF": OFF}
FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-7s %(short)-28s %(message)s"
DATE_FORMAT = "%H:%M:%S"

_handlers = []


class _ShortName(logging.Filter):
    """`short`: the logger name without the "r08." root, for the log line."""

    def filter(self, record):
        name = record.name
        record.short = name[len(ROOT) + 1:] if name.startswith(ROOT + ".") else name
        return True


def get_logger(name="app"):
    """The mod's logger for module `name` (pass __name__)."""
    name = str(name or "app")
    if name == "__main__":
        name = "main"
    return logging.getLogger(f"{ROOT}.{name}")


def parse_level(value, default=DEFAULT_LEVEL):
    """A logging level from a name ("debug"), a number or None -> `default`."""
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    text = str(value or "").strip().upper()
    if text.isdigit():
        return int(text)
    return LEVELS.get(text, LEVELS[default])


def _configured_level():
    """log_level / log_file from config.ini, when the config is already loaded
    (this module never triggers loading it: shared.config imports us)."""
    config_module = sys.modules.get("shared.config")
    config = getattr(config_module, "config", None)
    return getattr(config, "log_level", None), getattr(config, "log_file", None)


def setup_logging(level=None, log_file=None, stream=None):
    """Attach the console (and optional file) handlers and set the level.
    Safe to call again, e.g. once early with the environment only and once
    after the config is loaded, or with a command-line override."""
    cfg_level, cfg_file = _configured_level()
    chosen = parse_level(level or os.environ.get("R08_LOG_LEVEL") or cfg_level)
    path = log_file or os.environ.get("R08_LOG_FILE") or cfg_file

    root = logging.getLogger(ROOT)
    root.propagate = False
    for handler in _handlers:
        root.removeHandler(handler)
        handler.close()
    _handlers.clear()

    formatter = logging.Formatter(FORMAT, DATE_FORMAT)
    console = logging.StreamHandler(stream or sys.stderr)
    console.setFormatter(formatter)
    console.addFilter(_ShortName())
    _handlers.append(console)
    if path:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                path, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
            file_handler.setFormatter(formatter)
            file_handler.addFilter(_ShortName())
            _handlers.append(file_handler)
        except OSError as e:
            console.handle(logging.LogRecord(ROOT, logging.WARNING, __file__, 0,
                                             f"cannot open log file {path}: {e}", None, None))
    for handler in _handlers:
        root.addHandler(handler)
    root.setLevel(chosen)
    return chosen


def logging_active():
    """True when the mod logs anything (level below OFF). The game-side DLLs'
    logs (proxy + patches) are switched on and off with it at every launch."""
    return logging.getLogger(ROOT).getEffectiveLevel() < OFF
