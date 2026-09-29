"""Where things live for the released (PyInstaller) build. No side effects on import.

Everything belongs to ONE root folder (the folder holding R08Revival.exe):

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
"""
import os
import sys
import uuid

FROZEN = getattr(sys, "frozen", False)

APP_DATA, MOD_DATA, USER_DATA, GAME_FILES = "app_data", "mod_data", "user_data", "game_files"


def app_directory():
    return os.path.dirname(os.path.abspath(sys.executable))


def is_portable():
    return os.path.isfile(os.path.join(app_directory(), "portable.txt"))


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
    running from source: the repo's assets/."""
    if FROZEN:
        return os.path.join(app_data_directory(), "assets")
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


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
