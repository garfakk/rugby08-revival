"""Load a Rugby 08 player body model with its kit / skin / boot textures.

Turns the game's own files into plain numpy arrays plus RGBA texture bytes,
ready to hand to a renderer:

    model = load_player(PlayerAssets(
        model_o='<temp_directory>/player_assets/body.o',
        kit='<temp_directory>/player_assets/toul.away.big',        # .big or .fsh
        skin='<temp_directory>/player_assets/skin.fsh',
        boots='<temp_directory>/player_assets/boots.fsh',
        numbers='<temp_directory>/player_assets/toul.away.numbers.fsh',
    ))

The model ships every variant of every part at once (two shirt fits, three
collars, two sock sets…) and the engine shows one per set — drawing them all
z-fights, so `DEFAULT_VARIANTS` picks one of each. Textures are bound per
mesh through the material's SHAPENAME: 'clet' boots, 'skin' arms/legs,
'kit0' shirt+shorts+socks, 'jbck' the back-number decal.
"""
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

import numpy as np

from .bigfile import BigArchive
from .fshlib import Fsh
from .olib import parse_o

# Renderable groups the engine shows together. Groups within one variant set
# are coincident geometry, so exactly one of each must be drawn.
DEFAULT_VARIANTS = {
    'shirt':  ('02', '01'),
    'collar': ('03', '04', '05'),
    'socks':  ('06', '07'),
}
ALWAYS_ON = ('00',)

# Wrist tape ("08"/"09": a white band on each forearm) and thigh tape
# ("10"/"11": the band just below the shorts) are real geometry too, driven by
# the player's own wrist_tape / tight_tape stats. Model-left is +x, the same
# side as fingertapeLeft1Shape. Callers that don't say (the team kit previews)
# get the old look, both bands on.
WRIST_TAPE_GROUPS = {'none': (), 'left': ('09',), 'right': ('08',), 'both': ('08', '09')}
THIGH_TAPE_GROUPS = {'none': (), 'left': ('11',), 'right': ('10',), 'both': ('10', '11')}
# The two sock sets: '06' pulled up to the knee, '07' rolled down at the ankle
# (roster: bit 0x04 of record byte +0x59 = up).
SOCKS_GROUPS = {'up': '06', 'down': '07'}

# Finger tape is real geometry (not a texture like the other tapes), and
# unlike the shirt/collar/socks groups above it's two independent on/off
# toggles rather than a pick-one set — so it's driven by the player's own
# finger_tape stat ("none"/"left"/"right"/"both", matching backend
# game_specific_variables.tape_id) instead of DEFAULT_VARIANTS/ALWAYS_ON.
FINGERTAPE_GROUPS = {
    'none':  (),
    'left':  ('fingertapeLeft1Shape',),
    'right': ('fingertapeRight1Shape',),
    'both':  ('fingertapeLeft1Shape', 'fingertapeRight1Shape'),
}

# Skin tones present in skin.fsh, in the game's own naming: wk/lm/dm/dk =
# light, light-medium, dark-medium, dark. The 'sk' entries are bare hands,
# the 'sg' entries the same tone wearing gloves.
DEFAULT_SKIN_ENTRY = 'lmsk'

# Team-data-facing names for the shirt/collar variant groups above, so a
# team's kit JSON can say "loose"/"open" instead of the model's raw group
# ids. Confirmed by rendering each group combination: '02' hugs the torso
# and sleeves noticeably closer than '01'; '03' is the open, folded-over
# rugby collar, '04' a plain round crew neck, '05' a taller stand/raised
# collar closed at the front.
SHIRT_FITS = {'tight': '02', 'loose': '01'}
COLLAR_STYLES = {'open': '03', 'crew': '04', 'stand': '05'}
DEFAULT_FIT = 'tight'
DEFAULT_COLLAR = 'crew'


def variants_from_kit_config(cfg: dict | None, finger_tape: str | None = None,
                             wrist_tape: str | None = None, thigh_tape: str | None = None,
                             socks: str | None = None) -> dict:
    """Turn a kit's own `model3d` JSON block (`{"fit": ..., "collar": ...}`)
    into the group-id `variants` dict `load_player` expects (see
    DEFAULT_VARIANTS — only the first id of each entry is ever shown),
    falling back to the defaults for whichever key is missing or
    unrecognised. `finger_tape`, `wrist_tape`, `thigh_tape` ("none"/"left"/
    "right"/"both") and `socks` ("up"/"down") are the player's own stats, not
    part of the kit config — passed separately since they come from a
    different record. Left as None they keep the kit-preview defaults (both
    wrist and thigh bands, socks up)."""
    cfg = cfg or {}
    out = {'shirt': SHIRT_FITS.get(cfg.get('fit'), SHIRT_FITS[DEFAULT_FIT]),
           'collar': COLLAR_STYLES.get(cfg.get('collar'), COLLAR_STYLES[DEFAULT_COLLAR]),
           'fingertape': finger_tape if finger_tape in FINGERTAPE_GROUPS else 'none'}
    if wrist_tape is not None:
        out['wristtape'] = wrist_tape if wrist_tape in WRIST_TAPE_GROUPS else 'none'
    if thigh_tape is not None:
        out['thightape'] = thigh_tape if thigh_tape in THIGH_TAPE_GROUPS else 'none'
    if socks is not None:
        out['socks'] = SOCKS_GROUPS.get(socks, SOCKS_GROUPS['down'])
    return out


@dataclass
class PlayerAssets:
    model_o: str
    kit: str | None = None
    skin: str | None = None
    boots: str | None = None
    numbers: str | None = None
    skin_entry: str = DEFAULT_SKIN_ENTRY
    #: which of boots.fsh's 10 stock styles to use — every entry shares the
    #: name 'clet' (unlike skin.fsh's per-tone names), so style is picked by
    #: position, not name. None/absent selects the first (style 0).
    boots_index: int | None = None
    #: a head_<id>.big (model.o + textures.fsh), or a bare head .o
    head: str | None = None
    #: face texture, when `head` is a bare .o rather than an archive
    head_textures: str | None = None


@dataclass
class Part:
    name: str
    group: str
    shape: str                    # SHAPENAME -> texture key
    positions: np.ndarray         # (V,3) float32
    normals: np.ndarray           # (V,3) float32
    uvs: np.ndarray               # (V,2) float32
    indices: np.ndarray           # (T,3) uint32
    bones: np.ndarray             # (V,) uint32, per-mesh palette index
    #: heads are authored in the body's own space but sit above it; the rig
    #: must not fold them into its bind-pose measurements (they would stretch
    #: the model's height and drag every landmark fraction up with it)
    is_head: bool = False


@dataclass
class PlayerModel:
    parts: list[Part] = field(default_factory=list)
    textures: dict[str, tuple[int, int, bytes]] = field(default_factory=dict)

    @property
    def bounds(self):
        allpos = np.concatenate([p.positions for p in self.parts])
        return allpos.min(0), allpos.max(0)

    def stats(self):
        return dict(parts=len(self.parts),
                    verts=sum(len(p.positions) for p in self.parts),
                    tris=sum(len(p.indices) for p in self.parts),
                    textures=sorted(self.textures))


def _fsh_from(path: str) -> Fsh:
    """Read a .fsh, either standalone or as the first .fsh in a .big."""
    blob = Path(path).read_bytes()
    if blob[:4] == b'BIGF':
        arc = BigArchive(blob)
        name = arc.find('.fsh')
        if name is None:
            raise ValueError(f'{path}: no .fsh inside the archive')
        blob = arc.read(name)
    return Fsh(blob)


def _rgba(fsh: Fsh, entry: str | int | None) -> tuple[int, int, bytes] | None:
    """Decode one FSH entry to (w, h, RGBA bytes). A string `entry` matches
    by name, falling back to the first entry when absent (skin.fsh repeats
    names per tone). An int selects positionally instead — boots.fsh gives
    every one of its 10 stock styles the SAME name ('clet'), so style can
    only be told apart by position."""
    entries = fsh.entries
    if not entries:
        return None
    chosen = None
    if isinstance(entry, int):
        if 0 <= entry < len(entries):
            chosen = entries[entry]
    elif entry:
        chosen = next((e for e in entries if e.name == entry), None)
    if chosen is None:
        chosen = entries[0]
    img = chosen.decode().convert('RGBA')
    return img.width, img.height, img.tobytes()


_IMAGE_EXTS = {'.png', '.jpg', '.jpeg', '.bmp', '.webp', '.gif', '.tga'}


@lru_cache(maxsize=4)
def _parse_o_blob(blob: bytes):
    """parse_o() memoised on the file contents. Both kit previews are built
    from the same body model, and the screen rebuilds them on every team, kit
    or season change — parsing is the slowest part of that. The meshes are only
    ever read (callers copy them into numpy arrays), so sharing them is safe."""
    return tuple(parse_o(blob))


@lru_cache(maxsize=32)
def _texture_cached(path: str, entry: str | int | None, stamp: tuple):
    return _texture_from_path_uncached(path, entry)


def _texture_from_path(path: str, entry: str | int | None) -> tuple[int, int, bytes] | None:
    """Cached by file identity; decoding a kit/skin/boot texture costs real
    time (DXT decode + PIL) and the same files come back again and again."""
    try:
        st = Path(path).stat()
        return _texture_cached(path, entry, (st.st_mtime_ns, st.st_size))
    except OSError:
        return _texture_from_path_uncached(path, entry)


def _texture_from_path_uncached(path: str, entry: str | int | None) -> tuple[int, int, bytes] | None:
    """Load one kit/skin/boot/number texture from either an FSH/BIG archive
    (the game's own format) or a plain image file — mod team data ships
    kit textures as PNGs far more often than as extracted game archives,
    so a kit source needs to work either way."""
    from PIL import Image
    if Path(path).suffix.lower() in _IMAGE_EXTS:
        img = Image.open(path).convert('RGBA')
        return img.width, img.height, img.tobytes()
    return _rgba(_fsh_from(path), entry)


def load_player(assets: PlayerAssets, variants: dict | None = None) -> PlayerModel:
    meshes = _parse_o_blob(Path(assets.model_o).read_bytes())

    variants = dict(variants) if variants else {}
    finger_tape = variants.pop('fingertape', 'none')
    wrist_tape = variants.pop('wristtape', None)
    thigh_tape = variants.pop('thightape', None)
    picks = dict(DEFAULT_VARIANTS)
    picks.update(variants)
    shown = set(ALWAYS_ON)
    for options in picks.values():
        shown.add(options[0] if isinstance(options, tuple) else options)
    shown.update(FINGERTAPE_GROUPS.get(finger_tape, ()))
    shown.update(WRIST_TAPE_GROUPS['both'] if wrist_tape is None else WRIST_TAPE_GROUPS.get(wrist_tape, ()))
    shown.update(THIGH_TAPE_GROUPS['both'] if thigh_tape is None else THIGH_TAPE_GROUPS.get(thigh_tape, ()))

    model = PlayerModel()
    for mesh in meshes:
        if mesh.group not in shown or not mesh.triangles:
            continue
        model.parts.append(Part(
            name=mesh.name,
            group=mesh.group,
            shape=mesh.shapename,
            positions=np.asarray(mesh.positions, dtype=np.float32),
            normals=np.asarray(mesh.normals, dtype=np.float32),
            uvs=np.asarray(mesh.uvs, dtype=np.float32),
            indices=np.asarray(mesh.triangles, dtype=np.uint32),
            bones=np.asarray(mesh.bones, dtype=np.uint32),
        ))

    sources = {
        'kit0': (assets.kit, None),
        'skin': (assets.skin, assets.skin_entry),
        'clet': (assets.boots, assets.boots_index),
        'jbck': (assets.numbers, None),
    }
    for shape, (path, entry) in sources.items():
        if not path:
            continue
        tex = _texture_from_path(path, entry)
        if tex:
            model.textures[shape] = tex

    if assets.head:
        _add_head(model, assets.head, assets.head_textures)
    return model


def _add_head(model: PlayerModel, head: str, head_textures: str | None = None):
    """Attach a head. Heads are authored in the body's own coordinate space —
    they already sit on the neck — so they only need loading, not placing.

    `head` is normally a head_<id>.big holding `model.o` plus its
    `textures.fsh`; a bare .o with a separate .fsh works too. Every group in
    the file is drawn: a head carries no variant sets, unlike the body.
    """
    blob = Path(head).read_bytes()
    tex_blob = Path(head_textures).read_bytes() if head_textures else None
    if blob[:4] == b'BIGF':
        arc = BigArchive(blob)
        o_name = arc.find('.o')
        if o_name is None:
            raise ValueError(f'{head}: no .o inside the archive')
        if tex_blob is None:
            fsh_name = arc.find('.fsh')
            tex_blob = arc.read(fsh_name) if fsh_name else None
        blob = arc.read(o_name)

    for mesh in _parse_o_blob(blob):
        if not mesh.triangles:
            continue
        model.parts.append(Part(
            name=mesh.name,
            group=mesh.group,
            shape=mesh.shapename,
            positions=np.asarray(mesh.positions, dtype=np.float32),
            normals=np.asarray(mesh.normals, dtype=np.float32),
            uvs=np.asarray(mesh.uvs, dtype=np.float32),
            indices=np.asarray(mesh.triangles, dtype=np.uint32),
            bones=np.asarray(mesh.bones, dtype=np.uint32),
            is_head=True,
        ))

    if tex_blob is not None:
        # A head's FSH entries are named for the very shapes its meshes bind
        # ('face', 'hair', 'eyes', 'teup'…), so bind them by name. Not every
        # head has a 'face': a hooded or headgear head may carry only 'hair'
        # plus its own shapes, and forcing the first entry to 'face' would
        # leave those meshes untextured.
        for entry in Fsh(tex_blob).entries:
            img = entry.decode().convert('RGBA')
            model.textures[entry.name] = (img.width, img.height, img.tobytes())
