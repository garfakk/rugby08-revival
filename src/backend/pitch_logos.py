"""
backend/pitch_logos.py — where the pitch logos are painted, and how many
=========================================================================
The game paints the pitch logos from one model, misc/logos/logos.o (data.gob,
the same for every stadium): a big logo on the halfway spot (shape "loga",
the competition's pitch_logo_1) and two smaller ones on the 22 m lines
(shape "logb", the two halves of pitch_logo_2). A loose file named after the
model's hash in the game folder replaces it, so a match can move, turn,
resize, remove or repeat the logos: `build(layout)` writes that model.

A layout is a list of logos, each {"kind", "x", "z", "size", "angle"}:
  kind   "centre" (pitch_logo_1), "side_a" / "side_b" (the top / bottom half
         of pitch_logo_2)
  x, z   metres from the halfway spot: x across the pitch (+ = far touch
         line seen from the main stand), z along it
  size   metres, the logo's long side
  angle  degrees, 0 = the long side along the pitch

The model (ELF .o, olib) keeps its vertex and index buffers in .data, bound
by relocated pointers with their counts beside them. `build` writes new
buffers at the end of .data, points every bind at them, sets the counts and
the bounds, and moves the sections that follow.
"""
import hashlib
import io
import math
import os
import struct

from shared.log import get_logger

log = get_logger(__name__)

GAME_PATH = "misc/logos/logos"
FILENAME = hashlib.md5(GAME_PATH.encode()).hexdigest() + ".o"        # 70fa1eff...o
UNITS_PER_M = 67.58             # the try lines are 50 m from halfway, 3379 units
KINDS = ("centre", "side_a", "side_b")
KIND_LABELS = {"centre": "Main logo", "side_a": "Side logo", "side_b": "Side logo"}
TYPES = ("centre", "side")      # what a user picks: the two halves of pitch_logo_2 are both "side"
MAX_LOGOS = 16
_VSTRIDE = 0x18                 # float3 position, u32 colour, float2 uv


# ── the stock model ──────────────────────────────────────────────────────
def stock_path():
    """logos.o extracted from data.gob into the temp folder, None when the
    game isn't there."""
    from backend import mod_utils as mu
    from shared.config import config
    folder = os.path.join(config.temp_directory, "pitch_logos")
    path = os.path.join(folder, FILENAME)
    if os.path.isfile(path):
        return path
    gob = config.R08_data_gob_filepath
    if not os.path.isfile(gob):
        return None
    try:
        got = mu.extract_files_from_big_archive(gob, [FILENAME], folder)
    except OSError as e:
        log.warning(f"pitch logos model: {e}")
        return None
    return path if got and got.get(FILENAME) and os.path.isfile(path) else None


class _Model:
    """The .o's .data with its relocations, and the two meshes' buffers."""

    def __init__(self, blob):
        from elftools.elf.elffile import ELFFile
        self.blob = blob
        elf = ELFFile(io.BytesIO(blob))
        sec = elf.get_section_by_name(".data")
        self.data_off, self.data_size = sec["sh_offset"], sec["sh_size"]
        self.data = bytearray(sec.data())
        syms = list(elf.get_section_by_name(".symtab").iter_symbols())
        self.rel = {}                       # site -> .data target (local relocations)
        for r in elf.get_section_by_name(".rel.data").iter_relocations():
            s = syms[r["r_info_sym"]]
            if s["st_shndx"] != "SHN_UNDEF":
                self.rel[r["r_offset"]] = s["st_value"] + self.u32(r["r_offset"])
        self.meshes = []                    # [(vptr, vcount, iptr, icount)] in symbol order
        for gp in sorted(s["st_value"] for s in syms if s.name.startswith("__geoprimdatabuffer_")):
            vb = ib = None
            for x in sorted(self.rel):
                if x < gp or x > gp + 0x500:
                    continue
                marker = self.u32(x - 16)
                if marker == 0x00070006 and ib is None:
                    ib = (self.rel[x], self.u32(x + 4))
                elif 4 <= marker <= 0x100 and vb is None:
                    vb = (self.rel[x], self.u32(x + 4))
            if vb is None or ib is None:
                raise ValueError("logos.o: a mesh without buffers")
            self.meshes.append((vb[0], vb[1], ib[0], ib[1]))

    def u32(self, off):
        return struct.unpack_from("<I", self.data, off)[0]

    def vertices(self, mesh):
        vptr, vcount = self.meshes[mesh][:2]
        out = []
        for i in range(vcount):
            o = vptr + i * _VSTRIDE
            x, y, z = struct.unpack_from("<3f", self.data, o)
            u, v = struct.unpack_from("<2f", self.data, o + 16)
            out.append((x, y, z, u, v))
        return out

    def strip(self, mesh):
        _v, _n, iptr, icount = self.meshes[mesh]
        return list(struct.unpack_from(f"<{icount}H", self.data, iptr))


_STOCK = {}


def _stock_model(path=None):
    path = path or stock_path()
    if not path:
        return None
    key = (path, os.path.getmtime(path))
    if key not in _STOCK:
        with open(path, "rb") as fh:
            _STOCK.clear()
            _STOCK[key] = _Model(fh.read())
    return _STOCK[key]


def _templates(model):
    """kind -> (vertices relative to the logo's centre with the long side
    along z, strip, stock centre, stock angle, stock size)."""
    out = {}
    a = model.vertices(0)
    b = model.vertices(1)
    b_strip = model.strip(1)
    parts = {"centre": (a, model.strip(0)),
             "side_a": (b[:4], b_strip[:4]), "side_b": (b[4:8], [i - 4 for i in b_strip[-4:]])}
    for kind, (verts, strip) in parts.items():
        cx = sum(v[0] for v in verts) / len(verts)
        cz = sum(v[2] for v in verts) / len(verts)
        # the long side: the longest edge from the first vertex
        far = max(verts[1:], key=lambda v: math.hypot(v[0] - verts[0][0], v[2] - verts[0][2]))
        edges = sorted(((math.hypot(v[0] - verts[0][0], v[2] - verts[0][2]), v) for v in verts[1:]),
                       key=lambda t: t[0])
        long_edge = edges[1][1] if len(verts) == 4 else far        # a quad: the second-shortest edge
        size = edges[1][0] if len(verts) == 4 else max(v[2] for v in verts) - min(v[2] for v in verts)
        if len(verts) == 4:
            dx, dz = long_edge[0] - verts[0][0], long_edge[2] - verts[0][2]
            angle = math.degrees(math.atan2(dx, dz))
            angle = (angle + 90) % 180 - 90                         # the axis, either way along it
        else:
            angle = 0.0
        rel = [(_rot(v[0] - cx, v[2] - cz, -angle), v[1], v[3], v[4]) for v in verts]
        out[kind] = ([(p[0], y, p[1], u, v) for p, y, u, v in rel], strip, (cx, cz), angle, size)
    return out


def _rot(x, z, degrees):
    c, s = math.cos(math.radians(degrees)), math.sin(math.radians(degrees))
    return x * c + z * s, -x * s + z * c


# ── layouts ──────────────────────────────────────────────────────────────
def stock_layout(path=None):
    """The game's own three logos as a layout ([] when the model can't be read)."""
    model = _stock_model(path)
    if model is None:
        return []
    out = []
    for kind, (_v, _s, (cx, cz), angle, size) in _templates(model).items():
        out.append({"kind": kind, "x": round(cx / UNITS_PER_M, 2), "z": round(cz / UNITS_PER_M, 2),
                    "size": round(size / UNITS_PER_M, 2), "angle": round(angle, 1)})
    return out


def type_of(kind):
    """"centre" or "side" of a layout kind."""
    return "centre" if kind == "centre" else "side"


def kind_for(logo_type, layout, skip=None):
    """The layout kind of a new logo of `logo_type` ("centre" | "side"): side
    logos take the two halves of pitch_logo_2 in turn, so a competition whose
    halves differ shows both. `skip` = the index of a logo to leave out of
    the count (the one being changed)."""
    if logo_type == "centre":
        return "centre"
    a = sum(1 for i, l in enumerate(layout) if i != skip and l["kind"] == "side_a")
    b = sum(1 for i, l in enumerate(layout) if i != skip and l["kind"] == "side_b")
    return "side_a" if a <= b else "side_b"


def clean(layout):
    """`layout` with only well-formed logos (at most MAX_LOGOS)."""
    out = []
    for logo in layout or []:
        if not isinstance(logo, dict) or logo.get("kind") not in KINDS:
            continue
        try:
            out.append({"kind": logo["kind"], "x": float(logo.get("x", 0)), "z": float(logo.get("z", 0)),
                        "size": max(0.5, min(60.0, float(logo.get("size", 8)))),
                        "angle": (float(logo.get("angle", 0)) + 180) % 360 - 180})
        except (TypeError, ValueError):
            continue
    return out[:MAX_LOGOS]


def quads(layout, path=None):
    """{"loga" | "logb": [(positions [(x, y, z)], uvs [(u, v)], triangles)]}
    of `layout` in game units: what the stadium editor draws."""
    model = _stock_model(path)
    if model is None:
        return {}
    meshes = _meshes(model, clean(layout))
    out = {}
    for tag, (verts, strip) in zip(("loga", "logb"), meshes):
        tris = []
        for i in range(len(strip) - 2):
            a, b, c = strip[i], strip[i + 1], strip[i + 2]
            if a == b or b == c or a == c:
                continue
            tris.append((a, b, c) if i % 2 == 0 else (b, a, c))
        out[tag] = ([v[:3] for v in verts], [v[3:] for v in verts], tris)
    return out


def _meshes(model, layout):
    """[(vertices, strip)] for the model's two meshes (loga, logb)."""
    tpl = _templates(model)
    groups = ([l for l in layout if l["kind"] == "centre"],
              [l for l in layout if l["kind"] != "centre"])
    out = []
    for logos, hidden_kind in zip(groups, ("centre", "side_a")):
        if not logos:
            # a mesh can't be empty: one logo with no area
            logos = [{"kind": hidden_kind, "x": 0.0, "z": 0.0, "size": 0.0, "angle": 0.0}]
        verts, strip = [], []
        for logo in logos:
            t_verts, t_strip, _c, _a, t_size = tpl[logo["kind"]]
            scale = (logo["size"] * UNITS_PER_M) / t_size if t_size else 0.0
            x0, z0 = logo["x"] * UNITS_PER_M, logo["z"] * UNITS_PER_M
            base = len(verts)
            for x, y, z, u, v in t_verts:
                rx, rz = _rot(x * scale, z * scale, logo["angle"])
                verts.append((x0 + rx, y, z0 + rz, u, v))
            part = [base + i for i in t_strip]
            if strip:
                if len(strip) % 2:
                    strip.append(strip[-1])            # keep the winding of the next part
                strip += [strip[-1], part[0]]
            strip += part
        out.append((verts, strip))
    return out


# ── the game file ────────────────────────────────────────────────────────
def build(layout, path=None) -> bytes:
    """logos.o with `layout`'s logos (the stock model when the layout is
    the stock one is fine too: rebuilt the same way)."""
    model = _stock_model(path)
    if model is None:
        raise OSError("the game's logos model is not found (data.gob)")
    meshes = _meshes(model, clean(layout))
    data = bytearray(model.data)
    old_bounds = _bounds([v for m in range(len(model.meshes)) for v in model.vertices(m)])
    new_bounds = _bounds([v for verts, _s in meshes for v in verts])
    for m, (verts, strip) in enumerate(meshes):
        vptr, vcount, iptr, icount = model.meshes[m]
        while len(data) % 16:
            data.append(0)
        new_v = len(data)
        for x, y, z, u, v in verts:
            data += struct.pack("<3fI2f", x, y, z, 0xFFFFFFFF, u, v)
        while len(data) % 16:
            data.append(0)
        new_i = len(data)
        data += struct.pack(f"<{len(strip)}H", *strip)
        for site, target in model.rel.items():
            if target == vptr:
                _repoint(data, site, new_v, vcount, len(verts))
            elif target == iptr:
                _repoint(data, site, new_i, icount, len(strip))
        # the buffer's own header, just before its vertices: indices, vertices, triangles
        head = vptr - 0x14
        if struct.unpack_from("<3I", model.data, head) == (icount, vcount, icount - 2):
            struct.pack_into("<3I", data, head, len(strip), len(verts), len(strip) - 2)
    _replace_bounds(data, old_bounds, new_bounds, len(model.data))
    return _with_data(model, bytes(data))


def _repoint(data, site, new_ptr, old_count, new_count):
    """Point the bind at `site` at the new buffer and set its count: after
    the pointer in a geoprim command, before it in a render method."""
    struct.pack_into("<I", data, site, new_ptr)
    marker = struct.unpack_from("<I", data, site - 16)[0]
    for at in ((site + 4, site - 4) if (marker == 0x00070006 or 4 <= marker <= 0x100) else (site - 4, site + 4)):
        if struct.unpack_from("<I", data, at)[0] == old_count:
            struct.pack_into("<I", data, at, new_count)
            return
    raise ValueError(f"logos.o: no count beside the bind at {site:#x}")


def _bounds(verts):
    """(min, max, radius about the origin)"""
    xs, ys, zs = [v[0] for v in verts], [v[1] for v in verts], [v[2] for v in verts]
    radius = max(math.sqrt(v[0] ** 2 + v[1] ** 2 + v[2] ** 2) for v in verts)
    return (min(xs), min(ys), min(zs)), (max(xs), max(ys), max(zs)), radius


def _replace_bounds(data, old, new, end):
    """The model's boxes and spheres (written by the exporter after the
    meshes) keep the culling right: each stock value is replaced."""
    (ominx, ominy, ominz), (omaxx, omaxy, omaxz), o_rad = old
    (nminx, nminy, nminz), (nmaxx, nmaxy, nmaxz), n_rad = new
    o_size = (omaxx - ominx, omaxy - ominy, omaxz - ominz)
    n_size = (nmaxx - nminx, nmaxy - nminy, nmaxz - nminz)
    pairs = [((ominx, ominy, ominz), (nminx, nminy, nminz)), ((omaxx, omaxy, omaxz), (nmaxx, nmaxy, nmaxz)),
             (tuple(s * 2 for s in o_size), tuple(s * 2 for s in n_size)), (o_size, n_size)]
    f32 = lambda v: struct.unpack("<f", struct.pack("<f", v))[0]
    for off in range(0, end - 12, 4):
        trip = struct.unpack_from("<3f", data, off)
        for was, now in pairs:
            if all(abs(a - f32(b)) <= max(1e-3, abs(b) * 1e-5) for a, b in zip(trip, was)):
                struct.pack_into("<3f", data, off, *now)
                break
        else:
            (r,) = struct.unpack_from("<f", data, off)
            if abs(r - o_rad) < 0.05 and o_rad > 100:
                struct.pack_into("<f", data, off, max(n_rad, 1.0))


def _with_data(model, data):
    """The ELF with its .data replaced by `data` (longer): every section and
    the section table after it moved along."""
    blob = bytearray(model.blob)
    grow = len(data) - model.data_size
    grow += (-grow) % 16
    data = data + b"\0" * (grow - (len(data) - model.data_size))
    end = model.data_off + model.data_size
    e_shoff, = struct.unpack_from("<I", blob, 0x20)
    e_shentsize, e_shnum = struct.unpack_from("<HH", blob, 0x2E)
    out = bytearray(blob[:model.data_off]) + data + blob[end:]
    if e_shoff >= end:
        e_shoff += grow
    struct.pack_into("<I", out, 0x20, e_shoff)
    for i in range(e_shnum):
        sh = e_shoff + i * e_shentsize
        off, size = struct.unpack_from("<II", out, sh + 0x10)
        if off == model.data_off and size == model.data_size:
            struct.pack_into("<I", out, sh + 0x14, len(data))
        elif off >= end:
            struct.pack_into("<I", out, sh + 0x10, off + grow)
    return bytes(out)
