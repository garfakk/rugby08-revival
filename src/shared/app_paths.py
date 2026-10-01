"""Where things live. No side effects on import.

Everything belongs to ONE root folder. Released (PyInstaller) build, the folder
holding R08Revival.exe:

  R08Revival.exe, _internal/   the program (replaced when the program is updated)
  app_data/                    read-only: assets/, README, CREDITS, config.ini.example
  mod_data/                    the data pack: players, teams, kits, stadiums, tournaments
  user_data/                   config.ini, user_prefs.ini, game_profile.ini, logs
  game_files/                  the private copy of the game the mod works on

Nothing lives in %APPDATA% or anywhere else, so the root is written by the mod
and must be a folder the user can write to (not Program Files): the installer
refuses such folders and check_writable_or_exit() re-checks at startup.
A file named portable.txt beside the exe marks a portable copy (no installer:
first launch locates Rugby 08 itself).

Running from source, the repo root plays the same role, with the same layout:

  run.py                       the launcher (stands for R08Revival.exe)
  src/                         the program and its assets (app_data + _internal)
  data/                        the data pack (mod_data)
  user_data/                   config.ini, user_prefs.ini, ... (created at first launch)

A source checkout behaves like a portable copy: first launch locates Rugby 08 and
writes user_data/config.ini. There is no game_files/ copy, the game is used in place.
"""
import os
import sys
import uuid

FROZEN = getattr(sys, "frozen", False)

if FROZEN:
    APP_DATA, MOD_DATA = "app_data", "mod_data"
else:
    APP_DATA, MOD_DATA = "src", "data"
USER_DATA, GAME_FILES = "user_data", "game_files"


def app_directory():
    if FROZEN:
        return os.path.dirname(os.path.abspath(sys.executable))
    # <repo>/src/shared/app_paths.py -> <repo>
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def is_portable():
    """No installer to set things up: first launch locates Rugby 08 itself.
    Always the case running from source."""
    return not FROZEN or os.path.isfile(os.path.join(app_directory(), "portable.txt"))


def app_data_directory():
    return os.path.join(app_directory(), APP_DATA)


def mod_data_directory():
    return os.path.join(app_directory(), MOD_DATA)


def user_data_directory():
    return os.path.join(app_directory(), USER_DATA)


def game_files_directory():
    return os.path.join(app_directory(), GAME_FILES)


def assets_directory():
    """assets/ (models, static_files, templates, audio...). Released build: app_data/assets;
    running from source: src/assets."""
    return os.path.join(app_data_directory(), "assets")


def _writable(directory):
    try:
        os.makedirs(directory, exist_ok=True)
        probe = os.path.join(directory, f".write_test_{uuid.uuid4().hex}")
        with open(probe, "w") as f:
            f.write("x")
        os.remove(probe)
        return True
    except OSError:
        return False


def check_writable_or_exit():
    """Released exe only: user_data/ (and mod_data/ once installed) must be writable.
    Installed under Program Files, or copied somewhere read-only, the mod would fail in
    confusing ways later, so say so once and stop."""
    if not FROZEN:
        return
    bad = [d for d in (user_data_directory(), mod_data_directory())
           if (d == user_data_directory() or os.path.isdir(d)) and not _writable(d)]
    if not bad:
        return
    import tkinter as tk
    from tkinter import messagebox
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(
        "Rugby 08 Revival",
        "Rugby 08 Revival saves its settings and data next to the program, but it cannot "
        "write to:\n\n" + "\n".join(bad) + "\n\n"
        "This happens when it is installed in a protected folder such as Program Files. "
        "Reinstall it in a folder you can write to (for example Documents\\R08Revival), "
        "or change the folder's permissions.")
    root.destroy()
    sys.exit(1)
