"""Build tests/fixtures/data/: a small, stable data pack cut from the real data/.

The logic, file-writer and pipeline tests run against this pack instead of the
real data, so they don't change every time the season data does (and keep
working once data/ lives in its own repo). Re-run only to change the fixture,
then review the diff and update the golden files (pytest --update-golden).

    python3 tests/fixtures/make_fixture_data.py [path/to/real/data]

Contents: 4 teams (England, France, South Africa, New Zealand) in seasons 2007
(disabled in the real data), 2008 and 2024; the players they and the challenges
refer to (stats trimmed to those seasons); stadiums.json; the default and
world_cup competitions; the challenges that only use those teams. Every image
is replaced by an 8x8 single-colour placeholder; small binaries (.fsh, .big)
are copied as they are, except custom heads, of which only the two smallest are
kept (the other players get a stock face).
"""
import glob
import hashlib
import json
import os
import re
import shutil
import sys

from PIL import Image

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(os.path.dirname(HERE))
OUT = os.path.join(HERE, "data")

TEAMS = ["England", "France", "South_Africa", "New_Zealand"]
SEASONS = {"2007", "2008", "2024"}
PLAYER_SEASONS = SEASONS | {"2023"}           # 2023 = previous season of 2024
CHALLENGES = ["rwc2007_fra_nz", "rwc2007_final_rsa_eng", "rwc2023_sf_rsa_eng"]
COMPETITIONS = ["default", "world_cup"]
CUSTOM_HEADS = 2
STOCK_FACE = "1"
MAX_BINARY = 2 * 1024 * 1024
IMAGE_EXT = (".png", ".jpg", ".jpeg")
ASSET_EXT = IMAGE_EXT + (".fsh", ".big")
# frame counts for "%" patterns with no file on disk (see game_data.ASSET_SPECS)
FRAMES = {"ball": 2, "banners": 4, "backKitFile": 22}


def placeholder(dst):
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    rgb = tuple(hashlib.sha256(os.path.basename(dst).encode()).digest()[:3])
    Image.new("RGBA", (8, 8), rgb + (255,)).save(dst, optimize=False)


def copy_asset(src_root, rel, dst_root):
    src, dst = os.path.join(src_root, rel), os.path.join(dst_root, rel)
    if os.path.exists(dst):
        return
    if rel.lower().endswith(IMAGE_EXT):
        placeholder(dst)
    elif os.path.isfile(src) and os.path.getsize(src) <= MAX_BINARY:
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)


def expand(src_root, rel, key):
    """Files a path stands for: itself, or every frame of a "%" pattern."""
    if "%" not in rel:
        return [rel]
    rx = re.compile(re.escape(rel).replace("%", r"(\d+)") + "$")
    found = sorted(os.path.relpath(f, src_root).replace(os.sep, "/")
                   for f in glob.glob(os.path.join(src_root, rel.replace("%", "*"))))
    found = [f for f in found if rx.match(f)]
    return found or [rel.replace("%", str(i)) for i in range(1, FRAMES.get(key, 22) + 1)]


def asset_paths(node, key=""):
    """(key, path) for every asset path in a JSON tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            yield from asset_paths(v, k)
    elif isinstance(node, list):
        for v in node:
            yield from asset_paths(v, key)
    elif isinstance(node, str) and node.lower().endswith(ASSET_EXT):
        yield key, node


def squad_ids(entry):
    ids = set(map(str, entry.get("players") or []))
    for v in (entry.get("variant") or {}).values():
        ids |= set(map(str, v.get("players") or []))
    return ids


def main(data):
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    wanted_players = set()

    for team in TEAMS:
        folder = os.path.join(data, "teams", team)
        name = f"{team.lower()}.json"
        with open(os.path.join(folder, name), encoding="utf-8") as f:
            doc = json.load(f)
        cut = {tid: {s: e for s, e in seasons.items() if s in SEASONS}
               for tid, seasons in doc.items()}
        out_folder = os.path.join(OUT, "teams", team)
        os.makedirs(out_folder)
        with open(os.path.join(out_folder, name), "w", encoding="utf-8") as f:
            json.dump(cut, f, indent=1, ensure_ascii=False)
        for seasons in cut.values():
            for entry in seasons.values():
                wanted_players |= squad_ids(entry)
                for key, rel in asset_paths(entry):
                    for r in expand(folder, rel, key):
                        copy_asset(folder, r, out_folder)

    os.makedirs(os.path.join(OUT, "challenges"))
    for cid in CHALLENGES:
        src = os.path.join(data, "challenges", f"{cid}.json")
        with open(src, encoding="utf-8") as f:
            doc = json.load(f)
        for side in ("home", "away"):
            wanted_players |= set(map(str, (doc[side].get("squad") or {}).get("players") or []))
        shutil.copyfile(src, os.path.join(OUT, "challenges", f"{cid}.json"))

    with open(os.path.join(data, "players", "players.json"), encoding="utf-8") as f:
        all_players = json.load(f)
    players = {}
    for pid in sorted(wanted_players, key=int):
        rec = all_players.get(pid)
        if rec is None:
            continue
        rec = dict(rec)
        rec["stats"] = {s: st for s, st in (rec.get("stats") or {}).items() if s in PLAYER_SEASONS}
        players[pid] = rec

    heads = sorted({st["face"] for p in players.values() for st in p["stats"].values()
                    if str(st.get("face", "")).endswith(".big")
                    and os.path.isfile(os.path.join(data, st["face"]))},
                   key=lambda h: (os.path.getsize(os.path.join(data, h)), h))
    keep_heads = set(heads[:CUSTOM_HEADS])
    for p in players.values():
        for st in p["stats"].values():
            if str(st.get("face", "")).endswith(".big") and st["face"] not in keep_heads:
                st["face"] = STOCK_FACE
    os.makedirs(os.path.join(OUT, "players"))
    with open(os.path.join(OUT, "players", "players.json"), "w", encoding="utf-8") as f:
        json.dump(players, f, indent=1, ensure_ascii=False)
    for key, rel in asset_paths(players):
        copy_asset(data, rel, OUT)

    os.makedirs(os.path.join(OUT, "stadiums"))
    shutil.copyfile(os.path.join(data, "stadiums", "stadiums.json"),
                    os.path.join(OUT, "stadiums", "stadiums.json"))

    for comp in COMPETITIONS:
        src_root = os.path.join(data, "competitions", comp)
        for path in sorted(glob.glob(os.path.join(src_root, "**", "*"), recursive=True)):
            if os.path.isfile(path):
                rel = os.path.relpath(path, data)
                if rel.endswith(".json"):
                    os.makedirs(os.path.dirname(os.path.join(OUT, rel)), exist_ok=True)
                    shutil.copyfile(path, os.path.join(OUT, rel))
                else:
                    copy_asset(data, rel, OUT)

    sys.path[:0] = [os.path.join(ROOT, "src")]
    from shared.version import DATA_SCHEMA
    with open(os.path.join(OUT, "VERSION"), "w", encoding="utf-8") as f:
        f.write(f"data_version=fixture\nschema={DATA_SCHEMA}\n")

    size = sum(os.path.getsize(os.path.join(d, n)) for d, _, ns in os.walk(OUT) for n in ns)
    print(f"{OUT}: {len(players)} players, {len(TEAMS)} teams, {size // 1024} KB")


if __name__ == "__main__":
    main(os.path.abspath(sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "data")))
