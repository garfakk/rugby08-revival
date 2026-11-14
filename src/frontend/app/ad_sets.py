"""
app/ad_sets.py — the ad sets the quick match "stadium ads" picker offers
=========================================================================
No Qt. A set is what backend/adboards.py reads: a .fsh, an image or a folder
of images (see there). Offered: the mod's default, the sets the player loaded
(mod data `adboards/`: one entry per .fsh, image file or folder) and each
competition season's own.
"""
import os

from app import competition_branding, disk_import
from backend.adboards import IMAGE_EXTS
from shared.config import config

SUBDIR = "adboards"
EXTS = (".fsh",) + IMAGE_EXTS


def _label(name):
    return os.path.splitext(name)[0].replace("_", " ")


def loaded_sets():
    """[{"label", "path"}] of the sets under mod data `adboards/`, path
    relative to the mod data."""
    root = os.path.join(config.mod_data_directory, SUBDIR)
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root), key=str.lower):
        full = os.path.join(root, name)
        if name.startswith(".") or ".deleted-" in name:
            continue
        if os.path.isdir(full) or name.lower().endswith(EXTS):
            out.append({"label": _label(name), "path": f"{SUBDIR}/{name}"})
    return out


def competition_sets(ds):
    out = []
    for key, label in competition_branding.choices(ds, "adboards"):
        tid, info = competition_branding.resolve(ds, key)
        folder = ds.tournaments_folder_path.get(tid, "")
        full = os.path.join(folder, (info.get("adboards") or "").strip())
        out.append({"label": label, "path": os.path.relpath(full, config.mod_data_directory)
                    .replace("\\", "/")})
    return out


def choices(ds, current=None):
    """The picker's options, default first; `current` (a path) is added when
    it is none of them (a competition's, set by the match's branding)."""
    out = [{"label": "default", "path": ""}] + loaded_sets() + competition_sets(ds)
    if current and not any(o["path"] == current for o in out):
        out.append({"label": _label(os.path.basename(current.rstrip("/"))), "path": current})
    return out


def load(sources):
    """Copy the picked files / folder into the mod data and return the path
    of the set they make ("" when nothing usable was picked). Several files
    become one set (a folder named after the first); one file is a set by
    itself."""
    sources = [s for s in sources if s]
    if not sources:
        return ""
    if len(sources) == 1 and os.path.isdir(sources[0]):
        rels = disk_import.import_files(sources, config.mod_data_directory, SUBDIR, EXTS)
        return os.path.dirname(rels[0]) if rels else ""
    if len(sources) == 1:
        rels = disk_import.import_files(sources, config.mod_data_directory, SUBDIR, EXTS)
        return rels[0] if rels else ""
    stem = os.path.splitext(os.path.basename(sources[0]))[0]
    rels = disk_import.import_files(sources, config.mod_data_directory, f"{SUBDIR}/{stem}", EXTS)
    return os.path.dirname(rels[0]) if rels else ""
