"""
backend/stadium_scene.py — a stadium's scene pack as meshes and pictures
=========================================================================
For the stadium editor's 3D preview. A scene pack (one per environment:
day, night, overcast, cold) is a BIGF archive holding Stadium.o (stands,
boards, posts, pads), the pitch models (PitchColour.o, PitchLines.o...) and
Textures.fsh. A custom stadium's packs are files of its data folder; a stock
stadium's are read from data.gob (gsv.STADIUM_SLOTS, cached in
temp_directory/stadium_scenes).

The dressing textures are not in the pack: pads, flags and posts (pada padb
flag flgp post xbar) come from the pads file, the ad boards (ads0..ads8) from
the ad file of the stadium's board layout. The preview puts the picked sets
on them (backend/stadium_dressing, backend/adboards). The pitch lines' paint
(lina, linb) is one file of data.gob every stadium shares (LINES_FILE).

The pack's fx.big holds the particle effects the game lays on the scene:
fx_floods* (the floodlight lamps) and fx_pin* (small lights) are point
emitters (their MESH chunk: a float count, then x y z per point), read as
Scene.lights for the preview's glows.
"""
import hashlib
import os
import struct

import numpy as np

from backend import mod_utils as mu
from shared.log import get_logger

log = get_logger(__name__)

# in the order the game draws them: grass, its detail and shadow, the lines, the stadium, the sky
MODELS = ("PitchColour.o", "PitchDetail.o", "PitchShadow.o", "PitchLines.o", "Stadium.o", "sky.o")
DRESSING_TAGS = ("pada", "padb", "flag", "flgp", "post", "xbar")


class Part:
    """One mesh: interleaved float32 (N, 12) pos/normal/uv/colour (RGBA: the
    baked lighting, white when the mesh has none), uint32 triangles, the
    texture tag it wears and its material (render method) name. `numbers`:
    the numbers' share of the pitch lines (backend/pitch_lines)."""

    __slots__ = ("tag", "material", "model", "buf", "tri", "numbers")

    def __init__(self, tag, material, model, buf, tri, numbers=False):
        self.tag, self.material, self.model, self.buf, self.tri = tag, material, model, buf, tri
        self.numbers = numbers


# the pitch lines' paint: lina (the lines), linb (the numbers), whit
LINES_FILE = "44dcaf5199156bee671d7707bd3c4a32.fsh"
# fx.big effect name prefix -> kind of light the preview glows
LIGHT_KINDS = (("fx_flood", "flood"), ("fx_pin", "pin"))


class Scene:
    def __init__(self, parts, textures, lights=None):
        self.parts = parts            # [Part]
        self.textures = textures      # {tag: PIL RGBA image} of the pack's own textures
        self.lights = lights or []    # [(kind, (N, 3) float32 points)]: "flood" | "pin"

    def tags(self):
        return {p.tag for p in self.parts}

    def ads_layout(self):
        """"wc" when the stadium's boards use the World Cup layout (a strip
        board ads6..ads8), "std" otherwise (backend/adboards.LAYOUTS)."""
        return "wc" if self.tags() & {"ads6", "ads7", "ads8"} else "std"

    def ray_hit(self, origin, direction):
        """(distance, normal) where the ray from `origin` along unit
        `direction` first meets the stadium (Stadium.o), (inf, None) when it
        meets nothing. The normal is the vertices' own (the side the face is
        lit from, pointing out of the stand). The pieces lying on the grass
        don't count."""
        tris = getattr(self, "_ray_tris", None)
        if tris is None:
            pos, nrm = [], []
            for p in self.parts:
                if p.model == "Stadium.o" and len(p.tri):
                    t = p.tri.reshape(-1, 3).astype(np.int64)
                    t = t[p.buf[:, 1][t].max(axis=1) > 30.0]     # not the decals on the grass
                    pos.append(p.buf[:, :3][t])
                    nrm.append(p.buf[:, 3:6][t].mean(axis=1))
            tris = (np.concatenate(pos).astype(np.float64), np.concatenate(nrm).astype(np.float64)) if pos \
                else (np.zeros((0, 3, 3)), np.zeros((0, 3)))
            self._ray_tris = tris
        tris, normals = tris
        if not len(tris):
            return float("inf"), None
        o, d = np.asarray(origin, np.float64), np.asarray(direction, np.float64)
        v0 = tris[:, 0]
        e1, e2 = tris[:, 1] - v0, tris[:, 2] - v0
        h = np.cross(d, e2)
        det = np.einsum("ij,ij->i", e1, h)
        ok = np.abs(det) > 1e-9
        inv = np.where(ok, 1.0 / np.where(ok, det, 1.0), 0.0)
        s = o - v0
        u = inv * np.einsum("ij,ij->i", s, h)
        q = np.cross(s, e1)
        v = inv * (q @ d)
        t = inv * np.einsum("ij,ij->i", e2, q)
        hit = ok & (u >= 0) & (v >= 0) & (u + v <= 1) & (t > 1e-3)
        if not hit.any():
            return float("inf"), None
        i = np.flatnonzero(hit)[np.argmin(t[hit])]
        return float(t[i]), normals[i]

    def bounds(self):
        pts = np.concatenate([p.buf[:, :3] for p in self.parts if p.model == "Stadium.o"] or
                             [p.buf[:, :3] for p in self.parts])
        return pts.min(0), pts.max(0)


def _cache_dir():
    from shared.config import config
    return os.path.join(config.temp_directory, "stadium_scenes")


def stock_pack_path(game_path):
    """A stock scene pack ("stadiums/twickenham.day") extracted from data.gob
    into the cache, None when the game is not there."""
    return _cached_gob_file(hashlib.md5(game_path.lower().encode()).hexdigest() + ".big")


def pack_path(info, env, data_dir=None):
    """The scene pack of stadium `info` (a ds.stadiums entry) for `env`:
    its own file when it is a custom stadium, else the stock slot's."""
    from backend.game_specific_variables import STADIUM_SLOTS
    from shared.config import config
    own = (info.get("scenes") or {}).get(env)
    if own:
        path = own if os.path.isabs(own) else os.path.join(data_dir or config.mod_data_directory, own)
        if os.path.isfile(path):
            return path
    try:
        slot = STADIUM_SLOTS.get(int(info.get("game_id")))
    except (TypeError, ValueError):
        slot = None
    game_path = (slot or {}).get("scenes", {}).get(env)
    return stock_pack_path(game_path) if game_path else None


def environments(info):
    """The environments the stadium has a scene for, in the usual order."""
    from backend.game_specific_variables import STADIUM_SLOTS
    order = ("day", "overcast", "night", "cold")
    have = set(info.get("environments") or [])
    have |= set((info.get("scenes") or {}))
    try:
        have |= set((STADIUM_SLOTS.get(int(info.get("game_id"))) or {}).get("scenes", {}))
    except (TypeError, ValueError):
        pass
    return [e for e in order if e in have]


def _cached_gob_file(name):
    """A file of data.gob (by its hashed name) extracted into the cache,
    None when the game is not there."""
    from shared.config import config
    path = os.path.join(_cache_dir(), name)
    if os.path.isfile(path):
        return path
    gob = config.R08_data_gob_filepath
    if not os.path.isfile(gob):
        return None
    try:
        got = mu.extract_files_from_big_archive(gob, [name], _cache_dir())
    except OSError as e:
        log.warning(f"{name}: {e}")
        return None
    return path if got and got.get(name) and os.path.isfile(path) else None


_LINES = {}


def line_textures():
    """{"lina", "linb"}: the paint of the pitch lines, from the game ({} when
    it is not found)."""
    if "tex" not in _LINES:
        _LINES["tex"] = {}
        path = _cached_gob_file(LINES_FILE)
        if path:
            try:
                with open(path, "rb") as f:
                    data = f.read()
                if mu.is_refpack(data):
                    data = mu.refpack_decompress(data)
                for tag, block in mu.fsh_entries(data):
                    if tag in ("lina", "linb"):
                        _LINES["tex"][tag] = _bright_paint(mu.fsh_entry_image(block))
            except (OSError, ValueError) as e:
                log.warning(f"pitch lines: {e}")
    return dict(_LINES["tex"])


def _bright_paint(img):
    """The line paint as the game shows it: the file is a mid grey at ~60%
    alpha (soft brushed edges), drawn white and near solid on the grass."""
    a = np.asarray(img.convert("RGBA"), dtype=np.float32)
    top = max(1.0, float(np.percentile(a[..., :3], 99)))
    a[..., :3] = np.clip(a[..., :3] * (255.0 / top), 0, 255)
    a[..., 3] = np.clip(a[..., 3] * 1.7, 0, 255)
    from PIL import Image
    return Image.fromarray(a.astype(np.uint8), "RGBA")


def _jdi_points(data):
    """The emitter points of an effect (.jdi): its MESH chunk is an 80-byte
    picture path, a float count, then count x y z floats."""
    if data[:4] != b"YMUD":
        return None
    for i in range(16, min(len(data), 0x100), 16):
        if data[i:i + 4][::-1] != b"MESH":
            continue
        off = struct.unpack_from("<I", data, i + 12)[0] + 0x50
        if off + 4 > len(data):
            return None
        count = struct.unpack_from("<f", data, off)[0]
        if not (0 < count < 5000) or count != int(count) or off + 4 + int(count) * 12 > len(data):
            return None
        pts = np.frombuffer(data, np.float32, int(count) * 3, off + 4).reshape(-1, 3)
        ok = np.isfinite(pts).all(axis=1) & (np.abs(pts).max(axis=1) < 40000)
        return pts[ok].copy()
    return None


def read_lights(big):
    """[(kind, points)] of the pack's lamps (fx.big), [] when it has none."""
    from shared.omodel.bigfile import BigArchive
    name = big.find("fx.big")
    if not name:
        return []
    try:
        fx = BigArchive(big.read(name))
    except ValueError:
        return []
    out = []
    for entry in fx.entries:
        low = entry.lower()
        kind = next((k for prefix, k in LIGHT_KINDS if low.startswith(prefix.lower())), None)
        if kind is None or not low.endswith(".jdi"):
            continue
        pts = _jdi_points(fx.read(entry))
        # points around 0 0 0 hang on a node the preview can't place; the
        # ones on the grass are glows on the pitch, not lamps
        if pts is None or not len(pts) or np.abs(pts).max() < 1000.0:
            continue
        pts = pts[pts[:, 1] > 300.0]
        if len(pts):
            out.append((kind, pts))
    return out


def _long_edges(pos, tris, limit=1500.0):
    if not len(tris):
        return 0
    t = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    edges = [np.linalg.norm(pos[t[:, i]] - pos[t[:, (i + 1) % 3]], axis=1) for i in range(3)]
    return int((np.max(edges, axis=0) > limit).sum())


def _best_triangles(mesh, pos):
    """The mesh's triangles, as a list or as a strip: stadium meshes are
    mostly plain lists (0 1 2 3 4 5...), which read as a strip give long
    streaks joining unrelated faces. The reading with fewer very long
    triangles wins."""
    strip = np.asarray(mesh.triangles, dtype=np.uint32)
    idx = getattr(mesh, "indices", None)
    if idx is None or len(idx) % 3:
        return strip.ravel()
    lst = np.asarray(idx, dtype=np.int64).reshape(-1, 3)
    lst = lst[(lst.max(axis=1) < len(pos)) & (lst[:, 0] != lst[:, 1]) & (lst[:, 1] != lst[:, 2])
              & (lst[:, 0] != lst[:, 2])]
    best = lst if _long_edges(pos, lst) < _long_edges(pos, strip) else strip.astype(np.int64)
    return _drop_streaks(pos, best).astype(np.uint32).ravel()


def _drop_streaks(pos, tris, factor=8.0, floor=2500.0):
    """Triangles far longer than the mesh's usual ones are strips of two
    batches joined end to end: dropped."""
    t = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(t) < 8:
        return t
    longest = np.max([np.linalg.norm(pos[t[:, i]] - pos[t[:, (i + 1) % 3]], axis=1)
                      for i in range(3)], axis=0)
    return t[longest <= max(floor, factor * float(np.median(longest)))]


# the grass and its detail: regular grids of equal tiles, where a strip's
# join (the pitch packs' tp03 has one across a third of the field) stands out
GRID_MODELS = ("PitchColour.o", "PitchDetail.o")


def _split_numbers(parts):
    """The pitch lines' parts split in two: the lines, and the numbers
    (Part.numbers), so a style without them can leave them out."""
    from backend import pitch_lines
    lines = [p for p in parts if p.model == pitch_lines.MODEL and len(p.tri)]
    found = pitch_lines.number_triangles([(p.buf[:, :3], p.tri) for p in lines])
    if not found:
        return parts
    picked = {}
    for mi, ti in found:
        picked.setdefault(mi, []).append(ti)
    out = [p for p in parts if not (p.model == pitch_lines.MODEL and len(p.tri))]
    for mi, p in enumerate(lines):
        t = p.tri.reshape(-1, 3)
        mask = np.zeros(len(t), bool)
        mask[picked.get(mi, [])] = True
        if (~mask).any():
            out.append(Part(p.tag, p.material, p.model, p.buf, t[~mask].ravel()))
        if mask.any():
            out.append(Part(p.tag, p.material, p.model, p.buf, t[mask].ravel(), numbers=True))
    return out


def _drop_huge(pos, tri, limit=2500.0):
    """A few-triangle untextured piece is often a misread one: triangles
    spanning half the stadium across unrelated corners. Dropped."""
    t = np.asarray(tri, dtype=np.int64).reshape(-1, 3)
    if not len(t):
        return np.asarray(tri, dtype=np.uint32)
    longest = np.max([np.linalg.norm(pos[t[:, i]] - pos[t[:, (i + 1) % 3]], axis=1) for i in range(3)], axis=0)
    return t[longest <= limit].astype(np.uint32).ravel()


def _drop_over_pitch(pos, tri):
    """Nothing of the stadium hangs low over the field but the posts and the
    flags laid on it (all short): a long triangle there is a misread one,
    two corners of the ground joined across the grass."""
    t = np.asarray(tri, dtype=np.int64).reshape(-1, 3)
    if not len(t):
        return np.asarray(tri, dtype=np.uint32)
    p = pos[t]
    longest = np.max([np.linalg.norm(p[:, i] - p[:, (i + 1) % 3], axis=1) for i in range(3)], axis=0)
    c = p.mean(axis=1)
    bad = (longest > 1500.0) & (np.abs(c[:, 0]) < 2200.0) & (np.abs(c[:, 2]) < 4300.0) & (c[:, 1] < 1500.0)
    return t[~bad].astype(np.uint32).ravel()


def _colours(mesh, count):
    """(N, 4) float RGBA of the mesh's vertex colours (0xAARRGGBB), white
    when it has none."""
    raw = getattr(mesh, "colors", None)
    if not raw or len(raw) != count:
        return np.ones((count, 4), np.float32)
    c = np.asarray(raw, dtype=np.uint32)
    return np.stack([(c >> 16) & 255, (c >> 8) & 255, c & 255, c >> 24], axis=1).astype(np.float32) / 255.0


_SCENES = {}


def load(path):
    """The Scene of the pack at `path` (memoised by path and mtime)."""
    key = (path, os.path.getmtime(path))
    if key in _SCENES:
        return _SCENES[key]
    scene = read(path)
    _SCENES.clear()                        # one scene at a time is plenty
    _SCENES[key] = scene
    return scene


def read(path):
    """The Scene of the pack at `path`, not kept."""
    from shared.omodel.bigfile import BigArchive
    from shared.omodel.olib import parse_o
    big = BigArchive.open(path)
    parts = []
    for name in MODELS:
        if name not in big:
            continue
        try:
            meshes = parse_o(big.read(name))
        except ValueError:
            continue                       # no geometry (PitchFinal.o, a bare root)
        for m in meshes:
            if not m.positions or not m.triangles:
                continue
            pos = np.asarray(m.positions, dtype=np.float32)
            nrm = np.asarray(m.normals, dtype=np.float32) if len(m.normals) == len(m.positions) \
                else np.tile(np.array([0, 1, 0], np.float32), (len(pos), 1))
            uv = np.asarray(m.uvs, dtype=np.float32) if len(m.uvs) == len(m.positions) \
                else np.zeros((len(pos), 2), np.float32)
            col = _colours(m, len(pos))
            buf = np.concatenate([pos, nrm, uv, col], axis=1).astype(np.float32)
            if name == "sky.o":
                # the dome: one strip of big triangles, which the long-edge
                # judging below would take for streaks
                tri = np.asarray(m.triangles, dtype=np.uint32).ravel()
            else:
                tri = _best_triangles(m, pos)
            if name in GRID_MODELS:
                tri = _drop_streaks(pos, tri, factor=2.5, floor=0.0).astype(np.uint32).ravel()
            if not m.shapename and len(tri) < 8 * 3:
                tri = _drop_huge(pos, tri)
            if name == "Stadium.o":
                tri = _drop_over_pitch(pos, tri)
            parts.append(Part(m.shapename or "", m.material or "", name, buf, tri))
    parts = _split_numbers(parts)
    textures = {}
    fsh = big.find("Textures.fsh")
    if fsh:
        for tag, block in mu.fsh_entries(big.read(fsh)):
            try:
                textures[tag] = mu.fsh_entry_image(block).convert("RGBA")
            except ValueError as e:
                log.debug(f"scene texture {tag}: {e}")
    for tag, img in line_textures().items():
        textures.setdefault(tag, img)
    crowd = big.find("Crowd.fsh")
    if crowd:
        # the crowd is drawn by the game on the seating (rwh0..rwh3): its
        # pictures stand in for it here
        pics = dict(mu.fsh_entries(big.read(crowd)))
        for i, src in enumerate(("me01", "me02", "hi01", "hi02")):
            if src in pics and f"rwh{i}" not in textures:
                try:
                    textures[f"rwh{i}"] = mu.fsh_entry_image(pics[src]).convert("RGBA")
                except ValueError:
                    pass
    return Scene(parts, textures, read_lights(big))


def dressing_textures(scene, pads_ref, posts_ref, ads_ref):
    """{tag: PIL image} the picked sets put on the stadium: pads, flags,
    posts, and the boards of its layout. A set that can't be read keeps the
    stock World Cup pictures; no ads set = the mod's own World Cup boards."""
    out = pads_textures(pads_ref, posts_ref)
    out.update(ads_textures(scene, ads_ref))
    return out


def pads_textures(pads_ref, posts_ref):
    from backend import stadium_dressing
    try:
        return stadium_dressing.preview_images(pads_ref, posts_ref)
    except Exception as e:                 # a broken set must not break the preview
        log.warning(f"pads preview: {e}")
        return {}


def ads_textures(scene, ads_ref):
    """The boards of `ads_ref` on the stadium's layout, as a match maps them
    (adboards.build), without encoding the game file."""
    from backend import adboards
    ad_set = None
    if ads_ref:
        try:
            ad_set = adboards.load_ref(ads_ref)
        except Exception as e:
            log.warning(f"ads preview {ads_ref}: {e}")
    if ad_set is None:
        wc, _std = _ads_templates()
        if wc is None:
            return {}
        ad_set = adboards.from_fsh(wc)
    layout = scene.ads_layout() if scene is not None else "wc"
    spec = adboards.LAYOUTS[layout]
    out = {}
    try:
        for i, tag in enumerate(spec["sheets"]):
            out[tag] = adboards._pick(ad_set.sheets, i).image().convert("RGBA")
        for j, tag in enumerate(spec["strips"]):
            src = ad_set.strips[j] if ad_set.layout == "wc" and j < len(ad_set.strips) \
                else adboards._strip_from_sheet(adboards._pick(ad_set.sheets, j))
            out[tag] = src.image().convert("RGBA")
        if ad_set.frame is not None and ad_set.layout == layout:
            out[spec["frame"]] = ad_set.frame.image().convert("RGBA")
        else:
            stock = _ads_templates()[0 if layout == "wc" else 1]
            frame = adboards.from_fsh(stock).frame if stock else None
            if frame is not None:
                out[spec["frame"]] = frame.image().convert("RGBA")
    except Exception as e:
        log.warning(f"ads preview: {e}")
    return out


def _ads_templates():
    """(World Cup, Standard) ad files every set is built over, as a match
    does (game_files_processor._adboard_templates); (None, None) if missing."""
    try:
        from backend.game_files_processor import _adboard_templates
        return _adboard_templates()
    except OSError as e:
        log.warning(f"ads preview: {e}")
        return None, None


# a team banners file's pictures, in order, and the stadium tags each one
# dresses for the home (h) / away (a) side; the pitch flag (Baus home, Bwal
# away) is the second flag, as a match builds its "_wcb" (mod_utils.complete_banners)
BANNER_TAGS = (("fl", "A"), ("fl", "B"), ("bn", "A"), ("bn", "B"))


def team_textures(home, away):
    """{tag: PIL image} of the teams' flags and banners on the stadium:
    `home` / `away` are a team's banners (a "banner_%.png" pattern or an
    .fsh, absolute), "" for none."""
    out = {}
    for side, flag, ref in (("h", "Baus", home), ("a", "Bwal", away)):
        pics = _banner_pictures(ref) if ref else []
        for (kind, letter), img in zip(BANNER_TAGS, pics):
            if img is not None:
                out[f"{side}{kind}{letter}"] = img
        if len(pics) > 1 and pics[1] is not None:
            out[flag] = pics[1]
    return out


def _banner_pictures(ref):
    from PIL import Image
    pics = []
    try:
        if ref.lower().endswith(".fsh"):
            with open(ref, "rb") as f:
                pics = [mu.fsh_entry_image(b).convert("RGBA") for _t, b in mu.fsh_entries(f.read())[:4]]
        else:
            for i in range(1, 5):
                path = ref.replace("%", str(i))
                pics.append(Image.open(path).convert("RGBA") if os.path.isfile(path) else None)
    except (OSError, ValueError) as e:
        log.warning(f"banners {ref}: {e}")
    return pics
