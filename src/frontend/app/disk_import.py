"""
app/disk_import.py — "Load from disk" in the editors' asset pickers
====================================================================
Files (or a folder of them) the user picks anywhere on disk are copied into
the data folder the editors list, under `root/subdir` (root: a team folder
or the data folder itself). The user's copy is kept in user_data/mod_data
(shared/mod_overlay.place_file), so no release erases it; the maintainer's
mode (save_edits_to = mod) writes the data folder itself.

A name already used there by another file is never replaced (a pack file
may be shared with other teams or players): the batch goes into a new
sub folder instead, or with `flatten` (heads: one flat folder) the file is
renamed. A file identical to the one there is just reused.
"""
import os
import shutil

from app import game_data as G
from shared import mod_overlay
from shared.app_paths import user_data_directory
from shared.config import config


def _same(a, b):
    try:
        if os.path.getsize(a) != os.path.getsize(b):
            return False
        with open(a, "rb") as fa, open(b, "rb") as fb:
            return fa.read() == fb.read()
    except OSError:
        return False


def _files(sources, exts, flatten):
    """[(source path, name relative to the batch)] of the picked files and
    folders (a folder keeps its own name unless `flatten`)."""
    out = []
    for src in sources:
        if os.path.isdir(src):
            base = os.path.basename(os.path.normpath(src))
            for top, dirs, names in os.walk(src):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for name in sorted(names):
                    if exts and not name.lower().endswith(exts):
                        continue
                    full = os.path.join(top, name)
                    rel = name if flatten else \
                        f"{base}/{os.path.relpath(full, src).replace(os.sep, '/')}"
                    out.append((full, rel))
        elif os.path.isfile(src) and (not exts or src.lower().endswith(exts)):
            out.append((src, os.path.basename(src)))
    return out


def _free_name(folder, name):
    stem, ext = os.path.splitext(name)
    candidate, n = name, 1
    while os.path.exists(os.path.join(folder, candidate)):
        n += 1
        candidate = f"{stem}_{n}{ext}"
    return candidate


def _free_folder(folder, name):
    candidate, n = name, 1
    while os.path.exists(os.path.join(folder, candidate)):
        n += 1
        candidate = f"{name} {n}"
    return candidate


def copy_into_data(src, dst):
    """shutil.copy2 for a file added under the data folder (`dst` inside
    config.mod_data_directory): the user's copy goes to their overlay."""
    rel = os.path.relpath(os.path.abspath(dst), os.path.abspath(config.mod_data_directory))
    if not G.saves_to_user_edits() or rel.startswith(".."):
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return
    mod_overlay.place_file(user_data_directory(), rel.replace(os.sep, "/"), src,
                           config.mod_data_directory, config.pack_directory)


def import_files(sources, root, subdir="", exts=(), flatten=False):
    """Copy the picked `sources` (files and/or folders) under root/subdir.
    Returns the paths relative to `root` ("/"), in order."""
    exts = tuple(e.lower() for e in exts)
    batch = _files(sources, exts, flatten)
    if not batch:
        return []
    folder = os.path.join(root, *[p for p in subdir.split("/") if p])
    clash = any(os.path.exists(os.path.join(folder, *rel.split("/")))
                and not _same(src, os.path.join(folder, *rel.split("/")))
                for src, rel in batch)
    if clash and flatten:
        renamed = []
        for src, rel in batch:
            dst = os.path.join(folder, rel)
            if os.path.exists(dst) and not _same(src, dst):
                rel = _free_name(folder, rel)
            renamed.append((src, rel))
        batch = renamed
    elif clash:
        first = os.path.dirname(batch[0][0])
        sub = _free_folder(folder, os.path.basename(first) or "imported")
        folder = os.path.join(folder, sub)
    out = []
    for src, rel in batch:
        dst = os.path.join(folder, *rel.split("/"))
        if not (os.path.isfile(dst) and _same(src, dst)):
            copy_into_data(src, dst)
        out.append(os.path.relpath(dst, root).replace(os.sep, "/"))
    return out
