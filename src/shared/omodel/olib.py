"""Model (.o) reader/writer, based on the reR08 project's omodel tools.
Local change: per-vertex bone indices are kept (Mesh.bones) so the player
preview can animate limbs without a skeleton evaluator.
"""
#!/usr/bin/env python3
"""Rugby 08 (EAGL) .o model parser.

.o = ELF32 relocatable (PS2-toolchain heritage) with all model data in .data,
pointers wired by .rel.data, and every structure named in .symtab:

  __Model:::<name>                         model root
  __geoprimdatabuffer_<i>_<n>_<name>       geoprim descriptor (command stream)
  __RenderMethod:::__GPRenderMethod_<name>_<i>   material instance
  __Bone:::<name>.<bone> / __Skeleton:::   rig (ignored here)

Geoprim descriptor = dword command stream.  The two commands that matter:

  004b000c  ... stride ?  -1 -1  PTR  vcount 1 ...     vertex-buffer bind
  00070006  2 -1 -1  PTR  icount                       index-buffer bind (u16)

classified per reloc site X inside the descriptor:
  u32[X-16] == 0x00070006          -> index buffer  {ptr=reloc(X), count=u32[X+4]}
  u32[X-16] in 4..0x100 (stride)   -> vertex buffer {ptr, stride=u32[X-16], count=u32[X+4]}

Vertex layout (stride 0x28 confirmed on head models):
  +0x00 float3 position, +0x0c u32 bone, +0x10 float3 normal,
  +0x1c u32 rgba, +0x20 float2 uv
Stride 0x30 adds a SECOND uv set at +0x28: a material binds a base texture
plus a shared "dirt" overlay, and each has its own uv channel.  The layout is
never declared in the descriptor, so it is classified from the data instead
(see _find_normal / _find_uv) and the base texture's uv set -- the first one --
is the one returned.

Indices = triangle strip (PT_TRIANGLESTRIP in GeoPrimState), degenerates dropped.

Texture link: RenderMethod struct relocs -> __EAGL::TAR:::RUNTIME_ALLOC::...
SHAPENAME=<id>,... = the SHPI shape id inside the companion .fsh.
"""
import struct, re, io, math
from elftools.elf.elffile import ELFFile


class Mesh:
    def __init__(self, name, mat, shape, group=''):
        self.name, self.material, self.shapename = name, mat, shape
        self.group = group    # renderable-group name (part the engine toggles)
        self.positions = []   # (x,y,z)
        self.normals = []     # (x,y,z)
        self.uvs = []         # (u,v)
        self.triangles = []   # (a,b,c)
        self.bones = []       # per-vertex bone index (0 when the layout has none)
        self.stride = 0       # source vertex stride, for diagnostics


def _tristrip_to_tris(idx):
    tris = []
    for i in range(len(idx) - 2):
        a, b, c = idx[i], idx[i + 1], idx[i + 2]
        if a == b or b == c or a == c:
            continue                       # degenerate (strip restart)
        tris.append((a, c, b) if i & 1 else (a, b, c))
    return tris


def _samples(count, n=48):
    step = max(1, count // n)
    return range(0, count, step)


def _find_normal(data, vptr, stride, count):
    """Offset of the unit-length float3 field, or None (pos-only layouts)."""
    best, best_score = None, 0.0
    for off in (0x0c, 0x10):
        if off + 12 > stride:
            continue
        hits = tot = 0
        for i in _samples(count):
            x, y, z = struct.unpack_from('<3f', data, vptr + i * stride + off)
            if not all(map(math.isfinite, (x, y, z))):
                break
            tot += 1
            if 0.9 <= math.sqrt(x * x + y * y + z * z) <= 1.1:
                hits += 1
        score = hits / tot if tot else 0.0
        if score > best_score:
            best, best_score = off, score
    return best if best_score > 0.9 else None


def _find_uv(data, vptr, stride, count, start):
    """Offset of the FIRST texture-coordinate float2 at or after `start`.

    Colour/bone dwords are rejected because they decode to non-finite or
    wildly out-of-range floats; a constant field is rejected as padding.
    """
    for off in range(start, stride - 8 + 1, 4):
        vals, ok = set(), True
        for i in _samples(count):
            u, v = struct.unpack_from('<2f', data, vptr + i * stride + off)
            if not (math.isfinite(u) and math.isfinite(v)) or \
               not (-8.0 <= u <= 8.0 and -8.0 <= v <= 8.0):
                ok = False
                break
            vals.add((u, v))
        if ok and len(vals) > 1:
            return off
    return None


def _cstr(data, off):
    end = data.find(b'\0', off)
    return data[off:end if end >= 0 else len(data)].decode('latin-1')


def _parse_groups(data, rel, syms, u32, rm_geo):
    """Map geoprim offset -> renderable-group name.

    The __Model::: struct carries the part table (layout as
    used by the shirt-model builder):
        +0x9c  u32  group count N (the root group is extra, not counted)
        +0xa0  ptr  array of N name-string pointers
        +0xcc  ptr  group table: N+1 records of {u32 count, ptr x count},
                    root first, then the N named groups; each ptr is a
                    RenderMethod offset + 0x38.
    Toggling a group on/off is exactly what the engine does to swap shirt
    fit and collar variants, so expose it per mesh.
    """
    out = {}
    models = [s['st_value'] for s in syms if s.name.startswith('__Model:::')]
    if not models:
        return out
    base = min(models)
    try:
        n = u32(base + 0x9c)
        if not (0 < n < 256):
            return out
        name_arr = rel.get(base + 0xa0, u32(base + 0xa0))
        grp_tab = rel.get(base + 0xcc, u32(base + 0xcc))
        names = [_cstr(data, rel.get(name_arr + i * 4, u32(name_arr + i * 4)))
                 for i in range(n)]
        o = grp_tab
        for gi in range(n + 1):
            cnt = u32(o); o += 4
            if cnt > 4096:
                break
            label = 'root' if gi == 0 else names[gi - 1]
            for _ in range(cnt):
                rv = rel.get(o, u32(o)) - 0x38     # members point at RM+0x38
                gp = rm_geo.get(rv)
                if gp is not None:
                    out[gp] = label
                o += 4
    except (struct.error, IndexError, ValueError):
        return {}
    return out


def parse_o(blob):
    """Parse .o bytes -> list[Mesh].  Raises on non-model .o (no __Model)."""
    f = ELFFile(io.BytesIO(blob))
    data = f.get_section_by_name('.data').data()
    syms = list(f.get_section_by_name('.symtab').iter_symbols())
    relsec = f.get_section_by_name('.rel.data')
    rel = {}          # off -> .data target (section-relative relocs)
    relsym = {}       # off -> external symbol name (UND-symbol relocs)
    if relsec:
        for r in relsec.iter_relocations():
            off = r['r_offset']
            s = syms[r['r_info_sym']]
            addend = struct.unpack_from('<I', data, off)[0]
            if s['st_shndx'] == 'SHN_UNDEF' and s.name:
                relsym[off] = s.name
            else:
                rel[off] = s['st_value'] + addend if s.name else addend

    def u32(o): return struct.unpack_from('<I', data, o)[0]

    geoms = sorted([(s['st_value'], s.name) for s in syms
                    if s.name.startswith('__geoprimdatabuffer_')])
    if not geoms:
        raise ValueError('no geoprim buffers (not a model .o)')
    model = [s.name.split(':::', 1)[1] for s in syms if s.name.startswith('__Model:::')]
    mname = model[0] if model else '?'

    # sort all symbol starts to bound each descriptor
    starts = sorted(s['st_value'] for s in syms if s['st_size'] or s.name)
    def region_end(v):
        after = [x for x in starts if x > v]
        return min(after) if after else len(data)

    # RenderMethod structs -> (geoprim ptr, base method name, TAR shapename)
    rms = [(s['st_value'], s.name) for s in syms
           if s.name.startswith('__RenderMethod:::__GPRenderMethod_')]
    rm_info = {}                      # geoprim desc offset -> (material, shapename)
    rm_geo = {}                       # RenderMethod offset -> geoprim desc offset
    for rv, rn in rms:
        end = region_end(rv)
        mat, shape, gp = '', '', None
        for X in sorted(set(rel) | set(relsym)):
            if not (rv <= X < end):
                continue
            nm = relsym.get(X, '')
            if nm.startswith('ParentRM_'):
                mat = nm[len('ParentRM_'):]
            elif '::TAR:::' in nm and not shape:
                # A material carries two TAR texture slots: the base texture
                # (lowest reloc offset, e.g. clet/skin/kit0/jbck) and a shared
                # "dirt" detail overlay (higher offset).  rel/relsym are walked
                # in ascending offset, so the FIRST TAR is the base -- take it
                # and ignore the overlay (which is identical across materials).
                m = re.search(r'SHAPENAME=([^,;]+)', nm)
                if m: shape = m.group(1)
            elif X in rel:
                tgt = rel[X]
                for g in geoms:
                    if g[0] <= tgt < g[0] + 8:   # RM points at desc or desc+4
                        gp = g[0]
                        break
        rm_info[gp] = (mat, shape)
        rm_geo[rv] = gp

    groups = _parse_groups(data, rel, syms, u32, rm_geo)

    meshes = []
    for gval, gname in geoms:
        end = region_end(gval)
        vbs, ibs = set(), set()
        for X in sorted(rel):
            if not (gval <= X < end):
                continue
            marker = u32(X - 16)
            ptr, cnt = rel[X], u32(X + 4)
            if marker == 0x00070006:
                ibs.add((ptr, cnt))
            elif 4 <= marker <= 0x100:
                vbs.add((ptr, marker, cnt))
        if not vbs or not ibs:
            continue
        vptr, stride, vcount = sorted(vbs)[0]
        iptr, icount = sorted(ibs)[0]

        mat, shape = rm_info.get(gval, ('', ''))
        # embedded material name at descriptor tail (ascii, NUL-padded) fallback
        if not mat:
            tail = data[end - 0x40:end]
            runs = [r for r in tail.split(b'\0') if len(r) >= 4 and all(32 <= c < 127 for c in r)]
            if runs:
                mat = runs[-1].decode()

        m = Mesh(f'{mname}_{gname.split("_")[3]}', mat, shape,
                 groups.get(gval, ''))
        # Layout is not declared anywhere in the descriptor, so classify the
        # vertex fields from the data.  Position is always float3 @0; the normal
        # is the unit-length float3 that follows; colour dwords read back as
        # non-finite floats.  A material can carry several textures (base +
        # "dirt" overlay), each with its OWN uv set (stride 0x30 = uv0 @0x20,
        # uv1 @0x28) -- the base texture uses the FIRST one, so taking
        # `stride - 8` picks the overlay's uvs and smears the mapping.
        m.stride = stride
        norm_off = _find_normal(data, vptr, stride, vcount)
        has_norm = norm_off is not None
        uv_off = _find_uv(data, vptr, stride, vcount,
                          (norm_off + 12) if has_norm else 0x0c)
        m.has_uv = uv_off is not None and 'Gouraud' not in mat
        # Skinned layouts (stride 0x28 / 0x30) carry a bone index at +0x0c,
        # right before the normal.  Kept so callers can move body parts around
        # without a skeleton of their own.
        bone_off = 0x0c if (has_norm and norm_off >= 0x10 and stride >= 0x28) else None
        for i in range(vcount):
            o = vptr + i * stride
            if bone_off is not None:
                m.bones.append(struct.unpack_from('<I', data, o + bone_off)[0])
            else:
                m.bones.append(0)
            m.positions.append(struct.unpack_from('<3f', data, o))
            m.normals.append(struct.unpack_from('<3f', data, o + norm_off) if has_norm else (0, 0, 1))
            m.uvs.append(struct.unpack_from('<2f', data, o + uv_off) if m.has_uv else (0.0, 0.0))
        idx = struct.unpack_from(f'<{icount}H', data, iptr)
        m.triangles = [t for t in _tristrip_to_tris(idx)
                       if max(t) < vcount]     # guard multi-batch descriptors
        meshes.append(m)
    return meshes


def sanity(meshes):
    """Return dict of quality metrics for validation."""
    import math
    nv = sum(len(m.positions) for m in meshes)
    nt = sum(len(m.triangles) for m in meshes)
    uv_ok = norm_ok = pos_ok = nuv = 0
    for m in meshes:
        if getattr(m, 'has_uv', True):
            nuv += len(m.uvs)
            for u, v in m.uvs:
                if -4.0 <= u <= 4.0 and -4.0 <= v <= 4.0: uv_ok += 1
        for n in m.normals:
            l = math.sqrt(sum(c * c for c in n))
            if 0.5 <= l <= 1.5: norm_ok += 1
        for p in m.positions:
            if all(abs(c) < 1e5 for c in p): pos_ok += 1
    return dict(meshes=len(meshes), verts=nv, tris=nt,
                uv_ok=uv_ok / nuv if nuv else 1.0, norm_ok=norm_ok / max(nv, 1),
                pos_ok=pos_ok / max(nv, 1))
