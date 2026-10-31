#!/usr/bin/env python3
"""
packaging/pack_kit_textures.py — pack the kit textures of the data folder.

    python3 pack_kit_textures.py [--data <data folder>] [--team <folder>]... [--dry-run]

Every back-number series a team or challenge json names (a folder of 22
PNG files, kits_2024/home_back/home_back_%.png) becomes one lossless WebP
strip in the kit's folder (kits_2024/home_back.webp, see
shared/kit_files.py), and every .png kit front a lossless .webp. Each
packed file is decoded again and compared with its source, pixel for pixel
(RGBA); only then are the json paths rewritten (as text: the files keep
their layout) and the sources deleted. A source some other path still names
is kept. Series with missing shirts are left alone and reported. A strip
still in the older one-column layout is laid out again as a grid, in place.

Run it after adding PNG kits to the pack; packed kits are skipped.
"""
import argparse
import glob
import json
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path[:0] = [os.path.join(SRC, "frontend"), SRC]      # same import roots as run.py

import numpy as np                                       # noqa: E402
from PIL import Image                                    # noqa: E402

from shared import kit_files                             # noqa: E402

KIT_REF = re.compile(r'"(frontKitFile|backKitFile)"(\s*:\s*)"([^"]+)"')


def _rgba(path_or_image):
    im = path_or_image if isinstance(path_or_image, Image.Image) else Image.open(path_or_image)
    return np.asarray(im.convert("RGBA"))


def pack_back(job):
    """(pattern, strip, error) — writes and verifies one strip."""
    pattern, strip = job
    sources = [pattern.replace("%", str(n), 1) for n in range(1, kit_files.BACK_COUNT + 1)]
    try:
        images = [Image.open(p) for p in sources]
        tmp = strip + ".tmp.webp"
        kit_files.write_strip(images, tmp)
        frames = kit_files.strip_frames(tmp)
        if len(frames) != len(sources) or any(
                not np.array_equal(_rgba(f), _rgba(im)) for f, im in zip(frames, images)):
            os.remove(tmp)
            return pattern, strip, "decoded strip differs from its sources"
        os.replace(tmp, strip)
        return pattern, strip, None
    except Exception as e:                   # one bad series must not stop the run
        return pattern, strip, str(e)


def relayout_strip(path):
    """(path, path, error) — rewrites an older one-column strip as a grid."""
    try:
        frames = kit_files.strip_frames(path)
        tmp = path + ".tmp.webp"
        kit_files.write_strip(frames, tmp)
        again = kit_files.strip_frames(tmp)
        if len(again) != len(frames) or any(
                not np.array_equal(_rgba(a), _rgba(b)) for a, b in zip(again, frames)):
            os.remove(tmp)
            return path, path, "decoded grid differs from the strip"
        os.replace(tmp, path)
        return path, path, None
    except Exception as e:
        return path, path, str(e)


def pack_front(job):
    """(png, webp, error) — writes and verifies one front."""
    png, webp = job
    try:
        src = Image.open(png)
        src.load()
        rgba = _rgba(src)
        opaque = bool((rgba[..., 3] == 255).all())
        tmp = webp + ".tmp.webp"
        Image.fromarray(rgba[..., :3] if opaque else rgba).save(
            tmp, "WEBP", lossless=True, quality=100, method=5, exact=True)
        if not np.array_equal(_rgba(tmp), rgba):
            os.remove(tmp)
            return png, webp, "decoded image differs from its source"
        os.replace(tmp, webp)
        return png, webp, None
    except Exception as e:
        return png, webp, str(e)


def json_files(data, only):
    """(json path, team folder for each kit path in it) — team jsons use their
    own folder, challenge jsons their sides' team folders."""
    teams = os.path.join(data, "teams")
    folders = sorted(d for d in glob.glob(os.path.join(teams, "*")) if os.path.isdir(d))
    if only:
        wanted = {o.lower() for o in only}
        folders = [d for d in folders if os.path.basename(d).lower() in wanted]
    out, by_id = [], {}
    for d in folders:
        for path in sorted(glob.glob(os.path.join(d, "*.json"))):
            out.append((path, [d]))
            try:
                for tid in json.load(open(path, encoding="utf-8")):
                    by_id[str(tid)] = d
            except (OSError, ValueError, AttributeError):
                pass
    for path in sorted(glob.glob(os.path.join(data, "challenges", "*.json"))):
        try:
            data_ = json.load(open(path, encoding="utf-8"))
        except (OSError, ValueError):
            continue
        roots = [by_id[str(data_[s].get("team_id"))] for s in ("home", "away")
                 if isinstance(data_.get(s), dict) and str(data_[s].get("team_id")) in by_id]
        if roots:
            out.append((path, roots))
    return out


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--data", default=os.path.join(os.path.dirname(SRC), "data"),
                        help="data folder (default: the repository's data folder)")
    parser.add_argument("--team", action="append", help="team folder name (repeatable)")
    parser.add_argument("--dry-run", action="store_true", help="list what would be packed")
    parser.add_argument("--jobs", type=int, default=os.cpu_count())
    args = parser.parse_args(argv)

    files = json_files(args.data, args.team)
    backs, fronts, problems, columns = {}, {}, [], set()
    for path, roots in files:
        text = open(path, encoding="utf-8").read()
        for key, _, rel in KIT_REF.findall(text):
            if key == "backKitFile" and kit_files.is_strip(rel):
                for root in roots:
                    full = os.path.normpath(os.path.join(root, rel))
                    if os.path.isfile(full):
                        with Image.open(full) as im:
                            if kit_files.is_column(im.size):
                                columns.add(full)
            new = kit_files.packed_rel(rel)
            if new == rel:
                continue
            for root in roots:
                src, dst = os.path.join(root, rel), os.path.join(root, new)
                if key == "backKitFile" and "%" in rel:
                    present = [os.path.isfile(src.replace("%", str(n), 1))
                               for n in range(1, kit_files.BACK_COUNT + 1)]
                    if all(present):
                        backs[src] = dst
                        break
                    if any(present):
                        problems.append(f"{os.path.relpath(src, args.data)}: "
                                        f"{sum(present)}/{len(present)} shirts, not packed")
                elif key == "frontKitFile" and os.path.isfile(src):
                    fronts[src] = dst
                    break
    print(f"{len(backs)} back-number series, {len(fronts)} fronts to pack, "
          f"{len(columns)} one-column strips to lay out as grids")
    for p in problems:
        print("  SKIPPED", p)
    if args.dry_run:
        return 0

    done, failed = {}, []
    with ProcessPoolExecutor(args.jobs) as pool:
        for i, (src, _, err) in enumerate(pool.map(relayout_strip, sorted(columns), chunksize=4), 1):
            if err:
                failed.append(f"{os.path.relpath(src, args.data)}: {err}")
            if i % 100 == 0 or i == len(columns):
                print(f"  relayout_strip: {i}/{len(columns)}", flush=True)
        work = [(pack_back, sorted(backs.items())), (pack_front, sorted(fronts.items()))]
        for fn, jobs in work:
            for i, (src, dst, err) in enumerate(pool.map(fn, jobs, chunksize=4), 1):
                if err:
                    failed.append(f"{os.path.relpath(src, args.data)}: {err}")
                else:
                    done[src] = dst
                if i % 100 == 0 or i == len(jobs):
                    print(f"  {fn.__name__}: {i}/{len(jobs)}", flush=True)

    # point the jsons at what was packed
    for path, roots in files:
        text = open(path, encoding="utf-8").read()

        def swap(m):
            key, sep, rel = m.groups()
            new = kit_files.packed_rel(rel)
            if any(os.path.join(root, rel) in done for root in roots):
                return f'"{key}"{sep}"{new}"'
            return m.group(0)
        new_text = KIT_REF.sub(swap, text)
        if new_text != text:
            with open(path, "w", encoding="utf-8", newline="") as fh:
                fh.write(new_text)

    # delete the sources no json names any more
    still = set()
    for path, roots in files:
        for _, _, rel in KIT_REF.findall(open(path, encoding="utf-8").read()):
            still.update(os.path.normpath(os.path.join(root, rel)) for root in roots)
    removed = 0
    for src in done:
        if os.path.normpath(src) in still:
            continue
        for p in ([src.replace("%", str(n), 1) for n in range(1, kit_files.BACK_COUNT + 1)]
                  if "%" in src else [src]):
            os.remove(p)
            removed += 1
        folder = os.path.dirname(src)
        if "%" in src and not os.listdir(folder):
            os.rmdir(folder)            # the series' own folder, now empty
    print(f"packed {len(done)}, removed {removed} source files")
    for f in failed:
        print("  FAILED", f)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
