#!/usr/bin/env python3
"""Write assets/models/posts.npz, the model of the match-setup posts preview
(ui/posts_view.py): one goal (posts, crossbar, post pads, the small flags on
top) and one corner flag with its pole, cut out of a stock stadium's
Stadium.o (Twickenham). Run once by hand; needs the game (data.gob):

    python3 src/packaging/gen_posts_model.py

Each mesh is named after its texture (pada padb flag flgp post xbar): <tag>_pos,
<tag>_nrm, <tag>_uv, <tag>_tri, the goal centred on the origin, y up.
"""
import hashlib
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.dirname(HERE)
sys.path[:0] = [SRC]

from backend.mod_utils import extract_files_from_big_archive  # noqa: E402
from shared.config import config  # noqa: E402
from shared.omodel.bigfile import BigArchive  # noqa: E402
from shared.omodel.olib import parse_o  # noqa: E402

SCENE = "stadiums/twickenham.day"
TAGS = ("pada", "padb", "flag", "flgp", "post", "xbar")
GOAL_Z = 2627.0
CORNER = (1770.0, 3376.0)          # a corner flag (x, z) of that stadium
CORNER_AT = (300.0, 110.0)         # where the preview puts it, from the goal
CORNER_SCALE = 2.6                 # and larger than life, to be seen next to it


def _triangles(mesh, keep):
    """The triangles of `mesh` whose centroid passes `keep(x, y, z)`, as
    (positions, normals, uvs, tri) arrays with only the used vertices."""
    pos = np.asarray(mesh.positions, dtype=np.float32)
    nrm = np.asarray(mesh.normals, dtype=np.float32) if len(mesh.normals) == len(pos) \
        else np.tile(np.float32([0, 1, 0]), (len(pos), 1))
    uv = np.asarray(mesh.uvs, dtype=np.float32) if len(mesh.uvs) == len(pos) \
        else np.zeros((len(pos), 2), np.float32)
    tris = np.asarray(mesh.triangles, dtype=np.int64)
    if not len(tris):
        return None
    cent = pos[tris].mean(axis=1)
    tris = tris[[keep(*c) for c in cent]]
    if not len(tris):
        return None
    used, inverse = np.unique(tris.ravel(), return_inverse=True)
    return pos[used], nrm[used], uv[used], inverse.reshape(-1, 3)


def main():
    name = hashlib.md5(SCENE.encode()).hexdigest() + ".big"
    with tempfile.TemporaryDirectory() as tmp:
        extract_files_from_big_archive(config.R08_data_gob_filepath, name, tmp)
        meshes = parse_o(BigArchive.open(os.path.join(tmp, name)).read("Stadium.o"))
    parts = {t: [] for t in TAGS}

    def goal(x, y, z):
        return z > GOAL_Z - 200 and abs(x) < 400

    def corner(x, y, z):
        return abs(x - CORNER[0]) < 80 and abs(z - CORNER[1]) < 80

    for mesh in meshes:
        tag = mesh.shapename
        if tag not in parts:
            continue
        for keep, shift in ((goal, (0.0, 0.0, -GOAL_Z)),
                            (corner, (CORNER_AT[0] - CORNER[0], 0.0, CORNER_AT[1] - CORNER[1]))):
            cut = _triangles(mesh, keep)
            if cut is not None:
                p, n, u, t = cut
                if keep is corner:
                    base = np.float32([CORNER[0], 0.0, CORNER[1]])
                    p = (p - base) * np.float32(CORNER_SCALE) + base
                parts[tag].append((p + np.float32(shift), n, u, t))
    out = {}
    for tag, pieces in parts.items():
        if not pieces:
            continue
        pos, nrm, uv, tri, base = [], [], [], [], 0
        for p, n, u, t in pieces:
            pos.append(p); nrm.append(n); uv.append(u); tri.append(t + base)
            base += len(p)
        out[f"{tag}_pos"] = np.concatenate(pos).astype(np.float32)
        out[f"{tag}_nrm"] = np.concatenate(nrm).astype(np.float32)
        out[f"{tag}_uv"] = np.concatenate(uv).astype(np.float32)
        out[f"{tag}_tri"] = np.concatenate(tri).astype(np.uint16)
        print(tag, len(out[f"{tag}_pos"]), "vertices", len(out[f"{tag}_tri"]), "triangles")
    path = os.path.join(SRC, "assets", "models", "posts.npz")
    np.savez_compressed(path, **out)
    print("wrote", path)


if __name__ == "__main__":
    main()
