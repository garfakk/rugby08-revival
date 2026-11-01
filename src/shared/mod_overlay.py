"""
shared/mod_overlay.py — The user's own mod data, kept in user_data/mod_data/
====================================================================================
user_data/mod_data/ has the same layout as the data pack (data/ from source,
mod_data/ when installed). A file put there REPLACES the pack's file at the
same path, and a file the pack doesn't have is ADDED:

    user_data/mod_data/players/heads/my_face.big         a new head
    user_data/mod_data/players/skins/baille.png          replaces a pack skin
    user_data/mod_data/teams/Agen/kits_2024/home_front.webp
    user_data/mod_data/teams/My Club/my_club.json        a new team (+ its kits, logos)

so the pack stays untouched and a new release never erases the user's work.

How it is applied: the program reads one folder. With nothing in the overlay
that folder is the pack itself. Otherwise `effective_directory()` mirrors the
pack into user_data/cache/mod_data (hard links, so no space is used) and puts
the overlay's files over it; the mirror is rebuilt only when the pack or the
overlay changed. A pack file is never written through the mirror.
"""
import hashlib
import os
import shutil

from shared.log import get_logger

log = get_logger(__name__)

OVERLAY_NAME = "mod_data"
CACHE_DIR = os.path.join("cache", "mod_data")
STAMP = ".overlay_stamp"
README_NAME = "README.txt"

# The folders created for the user (and by the installer, which must list the
# same ones: tests/unit/test_mod_overlay.py checks it). Paths from the root.
STRUCTURE = [
    "players",
    "players/baselayers",
    "players/boots",
    "players/gloves",
    "players/heads",
    "players/skins",
    "players/straps",
    "teams",
    "stadiums",
    "competitions",
    "challenges",
]

README = """\
YOUR OWN MOD DATA
=================

Put your own files here. This folder has the same layout as the data pack
(the "mod_data" folder of the install, "data" in a source checkout):

  a file that exists in both  ->  yours replaces the pack's
  a file only you have        ->  it is added

The pack itself is never touched, so a new release never erases your work.
Restart the program after adding or changing files.

players/
  baselayers/   body base layers (.png)
  boots/        boot textures (.png)
  gloves/       glove textures (.png)
  heads/        player heads (.big)
  skins/        player skins (.png)
  straps/       knee / arm straps and other skin overlays (.png)
  *.json        extra players, same format as the pack's player files

teams/
  <Team name>/                    one folder per team
    <team_name>.json              the team (lower case, spaces as "_")
    kits_<season>/                home_front.webp, home_back.webp, away_...
    logos_<n>/                    logo.png, logo_small.png, logo_left.png ...
  To change a pack team's kit, use the same folder name and file names.

stadiums/       stadiums.json, or one folder per stadium
competitions/   one folder per competition (<name>/<name>.json and assets/)
challenges/     challenge .json files

Anything you create with the editors is kept in the "edits" folder next to
this one. Keep the file names of the pack when you want to replace a file.
"""


def overlay_directory(user_data):
    return os.path.join(user_data, OVERLAY_NAME)


def ensure_structure(user_data):
    """Create user_data/mod_data/ with its sub folders and the README.
    Never fails the start-up: a read-only folder just leaves it out."""
    root = overlay_directory(user_data)
    try:
        for rel in STRUCTURE:
            os.makedirs(os.path.join(root, *rel.split("/")), exist_ok=True)
        readme = os.path.join(root, README_NAME)
        if not os.path.isfile(readme):
            with open(readme, "w", encoding="utf-8", newline="\r\n" if os.name == "nt" else "\n") as f:
                f.write(README)
    except OSError as e:
        log.warning("cannot create %s: %s", root, e)
    return root


def _files(root):
    """[(relative path with "/", absolute path)] of the user's files."""
    out = []
    for folder, _dirs, names in os.walk(root):
        for name in names:
            if name.startswith(".") or (folder == root and name == README_NAME):
                continue
            path = os.path.join(folder, name)
            out.append((os.path.relpath(path, root).replace(os.sep, "/"), path))
    return sorted(out)


def _stamp(pack, overlay_files):
    h = hashlib.sha1(pack.encode("utf-8", "replace"))
    for folder, dirs, _names in os.walk(pack):
        dirs.sort()
        try:
            h.update(f"{folder}|{os.stat(folder).st_mtime_ns}".encode("utf-8", "replace"))
        except OSError:
            pass
    try:
        with open(os.path.join(pack, "VERSION"), "rb") as f:
            h.update(f.read())
    except OSError:
        pass
    for rel, path in overlay_files:
        try:
            st = os.stat(path)
        except OSError:
            continue
        h.update(f"{rel}|{st.st_size}|{st.st_mtime_ns}".encode("utf-8", "replace"))
    return h.hexdigest()


def _link(src, dst):
    """A hard link when the volume allows it, else a copy."""
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def _build(pack, overlay_files, merged):
    if os.path.isdir(merged):
        shutil.rmtree(merged)
    for folder, dirs, names in os.walk(pack):
        rel = os.path.relpath(folder, pack)
        target = merged if rel == "." else os.path.join(merged, rel)
        os.makedirs(target, exist_ok=True)
        for name in names:
            _link(os.path.join(folder, name), os.path.join(target, name))
    for rel, path in overlay_files:
        dst = os.path.join(merged, *rel.split("/"))
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        if os.path.lexists(dst):
            os.remove(dst)          # unlink first: never write through a link into the pack
        shutil.copy2(path, dst)


def effective_directory(pack, user_data):
    """The folder the program reads its mod data from: `pack` when the user
    has no files of their own, else the mirror with those files laid over."""
    files = _files(overlay_directory(user_data)) if os.path.isdir(overlay_directory(user_data)) else []
    if not files or not os.path.isdir(pack):
        return pack
    merged = os.path.join(user_data, CACHE_DIR)
    stamp = _stamp(pack, files)
    stamp_file = os.path.join(merged, STAMP)
    try:
        with open(stamp_file, encoding="utf-8") as f:
            if f.read().strip() == stamp:
                return merged
    except OSError:
        pass
    try:
        _build(pack, files, merged)
        with open(stamp_file, "w", encoding="utf-8") as f:
            f.write(stamp)
        log.info("mod data: %d user file(s) laid over %s", len(files), pack)
        return merged
    except OSError as e:
        log.error("cannot apply the user's mod data (%s): using the pack alone", e)
        return pack
