"""
backend/pitch_lines.py — the style of the pitch lines a stadium plays with
===========================================================================
The lines are each scene pack's PitchLines.o: two meshes painted with the
brush strokes "lina" and "linb" (a shared file of data.gob, no letters in
it). The numbers by the 10 m, 22 m and halfway lines are geometry too: small
glyphs, each a cluster of triangles sharing vertices, ~110 x 65 units, lying
just outside the 15 m dashes. The dashes, ticks and lines are 10 units wide.

Style "no_numbers" folds every glyph vertex onto one point of its glyph: the
triangles have no area left and nothing is drawn. The file keeps its size and
layout (positions are patched in place), so the scene pack is rewritten with
nothing else changed. A match writes it in its loose copy of the scene pack
(game_files_processor.deploy_stadium_files), removed after the match.

Stadium JSON "lines": "" = the game's lines, "no_numbers" = no numbers.
"""
import struct

import numpy as np

from shared.log import get_logger

log = get_logger(__name__)

MODEL = "PitchLines.o"
STYLES = ("", "no_numbers")
LABELS = {"": "lines with numbers", "no_numbers": "lines without numbers"}
# a glyph: a cluster of triangles with both sides at least this wide and no
# side longer than GLYPH_MAX (the dashes and ticks are ~10 units wide)
GLYPH_MIN, GLYPH_MAX = 30.0, 300.0


def clean(style):
    """A known style, "" (the game's) otherwise."""
    return style if style in STYLES else ""


def number_triangles(meshes):
    """[(mesh index, triangle index)] of the numbers among `meshes`, each a
    ((N, 3) positions, (T, 3) triangles) pair: the clusters of triangles
    (joined by shared vertex positions, across the meshes) the size of a
    glyph."""
    parent = {}

    def find(a):
        root = a
        while parent.setdefault(root, root) != root:
            root = parent[root]
        while parent[a] != root:
            parent[a], a = root, parent[a]
        return root

    tris = []
    for mi, (pos, tri) in enumerate(meshes):
        pos = np.asarray(pos, np.float64)
        for ti, t in enumerate(np.asarray(tri, np.int64).reshape(-1, 3)):
            keys = [(int(round(pos[i, 0])), int(round(pos[i, 2]))) for i in t]
            for k in keys[1:]:
                parent[find(keys[0])] = find(k)
            tris.append((mi, ti, keys))
    groups = {}
    for mi, ti, keys in tris:
        groups.setdefault(find(keys[0]), []).append((mi, ti, keys))
    out = []
    for members in groups.values():
        pts = np.array([k for _mi, _ti, keys in members for k in keys], np.float64)
        size = pts.max(axis=0) - pts.min(axis=0)
        if size.min() >= GLYPH_MIN and size.max() <= GLYPH_MAX:
            out += [(mi, ti) for mi, ti, _k in members]
    return out


def restyle_model(data, style):
    """PitchLines.o bytes with `style` applied (same size); unchanged for the
    game's style or when no number is found."""
    if clean(style) != "no_numbers":
        return data
    from shared.omodel.olib import parse_o
    meshes = [m for m in parse_o(data) if m.positions and m.triangles]
    pairs = [(np.asarray(m.positions, np.float32), np.asarray(m.triangles, np.int64)) for m in meshes]
    found = number_triangles(pairs)
    if not found:
        return data
    out = bytearray(data)
    by_mesh = {}
    for mi, ti in found:
        by_mesh.setdefault(mi, set()).update(int(v) for v in pairs[mi][1].reshape(-1, 3)[ti])
    moved = 0
    for mi, verts in by_mesh.items():
        m = meshes[mi]
        anchor = struct.unpack_from("<3f", out, m.vertex_offset + min(verts) * m.stride)
        for v in verts:
            struct.pack_into("<3f", out, m.vertex_offset + v * m.stride, *anchor)
            moved += 1
    log.debug(f"pitch lines: {len(found)} number triangles folded ({moved} vertices)")
    return bytes(out)


def apply(pack_path, style):
    """Rewrite the scene pack at `pack_path` with the lines of `style`; False
    when there is nothing to change."""
    if clean(style) != "no_numbers":
        return False
    from shared.omodel.bigfile import BigArchive, pack_big
    with open(pack_path, "rb") as fh:
        archive = BigArchive(fh.read())
    if MODEL not in archive:
        log.warning(f"pitch lines: {pack_path} has no {MODEL}")
        return False
    old = archive.read(MODEL)
    new = restyle_model(old, style)
    if new == old:
        return False
    entries = [(n, new if n == MODEL else archive.read(n)) for n in archive.entries]
    with open(pack_path, "wb") as fh:
        fh.write(pack_big(entries))
    return True
