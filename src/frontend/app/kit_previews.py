"""
app/kit_previews.py — which kit preview images to (re)generate
==================================================================
A kit's `previewFile` is the picture the menus show when the live 3D player
is off or unavailable. They are generated from the 3D model itself (see
ui/kit_preview.py and packaging/gen_kit_previews.py), so they always match
the kit as it is worn in game.

This module only works out the jobs, with no Qt: every kit of every season of
every team file (disabled seasons included — they ship in the data pack), and
every kit variant. An existing previewFile is overwritten. A kit without one,
or a kit variant that changes the shirt but would show the plain kit's
picture, gets its own path, next to its front texture:

    kits_2024/home_front.png            -> kits_2024/home_preview.png
    kits_2024/home_wc_front.png  [wc]   -> kits_2024/home_wc_preview.png

and that path is written into the team file (`assign_previews`). Several kits
pointing at the same preview with the same shirt are rendered once; a kit
whose shirt differs from the one already rendered there gets its own path the
same way (otherwise it would show another kit's picture).
"""
import json
import os
import re
from dataclasses import dataclass

from app import variants as V
from team_data_loader import TeamDataLoader


@dataclass
class PreviewJob:
    preview: str                # absolute path of the image to write
    front: str                  # absolute path of the kit texture (frontKitFile)
    back: str = ""              # back numbers (strip or %-pattern), "" if none
    model3d: dict = None        # the kit's "model3d" block (fit, collar)
    label: str = ""             # "England 2024 home", for reports


@dataclass
class Assignment:
    """A previewFile to write into a team file for a kit that has none of its own."""
    team_file: str
    team_id: str
    season: str
    kit: str
    variant: str                # "" = the plain kit
    preview: str                # relative to the team folder, as stored


def _label(name, season, kit, variant):
    return f"{name} {season} {kit}" + (f" [{variant}]" if variant else "")


def _slug(text):
    return re.sub(r"[^a-z0-9]+", "_", str(text).lower()).strip("_") or "kit"


def default_preview_path(front, kit_id, variant=""):
    """Where a generated preview goes: beside the front texture."""
    folder = os.path.dirname(front.replace("\\", "/"))
    stem = _slug(f"{kit_id}_{variant}" if variant else kit_id)
    name = f"{stem}_preview.png"
    return f"{folder}/{name}" if folder else name


def plan(teams_dir, only=None):
    """(jobs, assignments, problems) for every team folder under `teams_dir`.
    `only` limits it to the team folders named (case-insensitive). `problems`
    are the kits that cannot be rendered (no front texture) or files that
    cannot be read."""
    jobs, assignments, problems = {}, [], []
    if not os.path.isdir(teams_dir):
        return [], [], [f"no teams folder: {teams_dir}"]
    wanted = {o.lower() for o in only} if only else None
    for folder in sorted(os.listdir(teams_dir)):
        root = os.path.join(teams_dir, folder)
        path = os.path.join(root, TeamDataLoader.team_json_name(folder))
        if not os.path.isfile(path) or (wanted and folder.lower() not in wanted):
            continue
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError) as e:
            problems.append(f"{os.path.relpath(path, teams_dir)}: {e}")
            continue
        for team_id, seasons in data.items():
            for season, info in sorted((seasons or {}).items()):
                if not isinstance(info, dict):
                    continue
                name = info.get("name") or folder
                for kit_id, stored in (info.get("kits") or {}).items():
                    plain = V.resolve_kit(stored)
                    for variant in [V.DEFAULT] + V.kit_variant_ids(stored):
                        kit = V.resolve_kit(stored, variant)
                        label = _label(name, season, kit_id, variant)
                        front = (kit.get("frontKitFile") or "").strip()
                        if not front or not os.path.isfile(os.path.join(root, front)):
                            problems.append(f"{label}: front texture not found ({front or 'not set'})")
                            continue
                        preview = (kit.get("previewFile") or "").strip()
                        own = "previewFile" in V.kit_overrides(stored, variant)
                        if variant and not own and front != (plain.get("frontKitFile") or "").strip():
                            preview = ""        # would show the plain kit's picture
                        front_path = os.path.join(root, front)
                        target = os.path.normpath(os.path.join(root, preview)) if preview else ""
                        if not preview or (target in jobs and jobs[target].front != front_path):
                            preview = _free_path(root, default_preview_path(front, kit_id, variant),
                                                 front_path, jobs)
                            assignments.append(Assignment(path, team_id, season, kit_id, variant, preview))
                            target = os.path.normpath(os.path.join(root, preview))
                        if target in jobs:
                            continue                # same shirt, already rendered
                        back = (kit.get("backKitFile") or "").strip()
                        jobs[target] = PreviewJob(
                            preview=target, front=front_path,
                            back=os.path.join(root, back) if back else "",
                            model3d=kit.get("model3d"), label=label)
    return list(jobs.values()), assignments, problems


def _free_path(root, preview, front_path, jobs):
    """`preview`, or preview_2.png, _3... when it is taken by another shirt."""
    stem, ext = os.path.splitext(preview)
    candidate, n = preview, 2
    while True:
        job = jobs.get(os.path.normpath(os.path.join(root, candidate)))
        if job is None or job.front == front_path:
            return candidate
        candidate, n = f"{stem}_{n}{ext}", n + 1


def assign_previews(assignments):
    """Write each Assignment's previewFile into its team file (the plain kit,
    or the kit variant's own overrides). Every other key and season of the
    file is kept as it is. Returns the files changed."""
    from app.game_data import _load_json, _write_json
    by_file = {}
    for a in assignments:
        by_file.setdefault(a.team_file, []).append(a)
    changed = []
    for path, items in by_file.items():
        data = _load_json(path)
        for a in items:
            kit = data[a.team_id][a.season]["kits"][a.kit]
            if a.variant:
                kit.setdefault(V.KIT_VARIANTS_KEY, {}).setdefault(a.variant, {})["previewFile"] = a.preview
            else:
                kit["previewFile"] = a.preview
        _write_json(path, data)
        changed.append(path)
    return changed
