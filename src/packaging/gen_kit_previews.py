#!/usr/bin/env python3
"""Generate every kit preview image (each kit's previewFile) from the 3D
player model, overwriting the existing ones. A kit without a previewFile gets
one (written into its team file, see app/kit_previews.py). Run by release.sh
at every build, or by hand:

    python3 src/packaging/gen_kit_previews.py                   # all teams of data/
    python3 src/packaging/gen_kit_previews.py --team England --team France
    python3 src/packaging/gen_kit_previews.py --data /path/to/data --dry-run

Needs the game (its data.gob holds the generic body, skin and boots textures:
the Rugby 08 folder set in user_data/config.ini) and an OpenGL 3.3 context
(a desktop session; without a display it tries Qt's offscreen platform).
Exit code 1 when a preview could not be rendered.
"""
import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(SRC, "frontend"), SRC]      # same import roots as run.py


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", help="data folder (default: the app's mod data folder)")
    parser.add_argument("--team", action="append", help="team folder name (repeatable)")
    parser.add_argument("--size", type=int, default=None, help="image size in pixels (default 512)")
    parser.add_argument("--dry-run", action="store_true", help="list the previews, render nothing")
    parser.add_argument("-v", "--verbose", action="store_true", help="list every kit skipped")
    args = parser.parse_args(argv)

    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY") and sys.platform != "win32":
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from shared.config import config
    from shared.log import setup_logging
    setup_logging("WARNING")
    from app import kit_previews

    data = os.path.abspath(args.data or config.mod_data_directory)
    jobs, assignments, problems = kit_previews.plan(os.path.join(data, "teams"), args.team)
    print(f"{len(jobs)} kit previews in {data}, {len(assignments)} new previewFile entries")
    if problems:
        print(f"  {len(problems)} kits skipped (no usable front texture)"
              + ("" if args.verbose else ", -v to list them"))
    if args.verbose:
        for p in problems:
            print(f"  skipped: {p}")
    if args.dry_run:
        for job in jobs:
            print(f"  {job.label}: {os.path.relpath(job.preview, data)}")
        for a in assignments:
            print(f"  new previewFile: {os.path.relpath(a.team_file, data)} {a.season} {a.kit}"
                  f"{' [' + a.variant + ']' if a.variant else ''} -> {a.preview}")
        return 0
    if not jobs:
        return 0

    from PyQt5.QtGui import QGuiApplication, QSurfaceFormat
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)
    app = QGuiApplication(sys.argv[:1])          # noqa: F841  (GL needs it alive)

    from ui import kit_preview
    from ui.player_stage import generic_assets
    if not generic_assets():
        print(f"ERROR: the generic player assets could not be read from the game "
              f"({config.R08_data_gob_filepath}): set the Rugby 08 folder in user_data/config.ini",
              file=sys.stderr)
        return 1

    size = args.size or kit_preview.SIZE
    failed, start = [], time.monotonic()
    for i, job in enumerate(jobs, 1):
        image = kit_preview.render_kit_preview(job.front, job.back, job.model3d, size)
        rel = os.path.relpath(job.preview, data)
        if image is None or image.isNull():
            failed.append(job.label)
            print(f"  FAILED {job.label} ({rel})")
            continue
        os.makedirs(os.path.dirname(job.preview), exist_ok=True)
        tmp = job.preview + ".tmp.png"
        if not image.save(tmp, "PNG"):
            failed.append(job.label)
            print(f"  FAILED to write {rel}")
            continue
        os.replace(tmp, job.preview)
        if i % 25 == 0 or i == len(jobs):
            print(f"  {i}/{len(jobs)} ({time.monotonic() - start:.0f} s)")
    # Only now that the images exist do the team files point at them.
    done = [a for a in assignments
            if os.path.isfile(os.path.join(os.path.dirname(a.team_file), a.preview))]
    for path in kit_previews.assign_previews(done):
        print(f"  previewFile added to {os.path.relpath(path, data)}")
    print(f"{len(jobs) - len(failed)} written, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
