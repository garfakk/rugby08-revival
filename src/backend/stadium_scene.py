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
on them (backend/stadium_dressing, backend/adboards).
"""
import hashlib
import os

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
    texture tag it wears and its material (render method) name."""

    __slots__ = ("tag", "material", "model", "buf", "tri")

    def __init__(self, tag, material, model, buf, tri):
        self.tag, self.material, self.model, self.buf, self.tri = tag, material, model, buf, tri


class Scene:
    def __init__(self, parts, textures):
        self.parts = parts            # [Part]
        self.textures = textures      # {tag: PIL RGBA image} of the pack's own textures

    def tags(self):
        return {p.tag for p in self.parts}

    def ads_layout(self):
        """"wc" when the stadium's boards use the World Cup layout (a strip
        board ads6..ads8), "std" otherwise (backend/adboards.LAYOUTS)."""
        return "wc" if self.tags() & {"ads6", "ads7", "ads8"} else "std"

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
    from shared.config import config
    name = hashlib.md5(game_path.lower().encode()).hexdigest() + ".big"
    path = os.path.join(_cache_dir(), name)
    if os.path.isfile(path):
        return path
    gob = config.R08_data_gob_filepath
    if not os.path.isfile(gob):
        return None
    try:
        got = mu.extract_files_from_big_archive(gob, [name], _cache_dir())
    except OSError as e:
        log.warning(f"stadium scene {game_path}: {e}")
        return None
    return path if got and got.get(name) and os.path.isfile(path) else None


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


def _drop_streaks(pos, tris):
    """Triangles far longer than the mesh's usual ones are strips of two
    batches joined end to end: dropped."""
    t = np.asarray(tris, dtype=np.int64).reshape(-1, 3)
    if len(t) < 8:
        return t
    longest = np.max([np.linalg.norm(pos[t[:, i]] - pos[t[:, (i + 1) % 3]], axis=1)
                      for i in range(3)], axis=0)
    return t[longest <= max(2500.0, 8.0 * float(np.median(longest)))]


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
            tri = _best_triangles(m, pos)
            parts.append(Part(m.shapename or "", m.material or "", name, buf, tri))
    textures = {}
    fsh = big.find("Textures.fsh")
    if fsh:
        for tag, block in mu.fsh_entries(big.read(fsh)):
            try:
                textures[tag] = mu.fsh_entry_image(block).convert("RGBA")
            except ValueError as e:
                log.debug(f"scene texture {tag}: {e}")
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
    return Scene(parts, textures)


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
