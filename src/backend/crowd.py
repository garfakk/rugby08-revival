"""The crowd of a match: how full the stands are, supporters in the teams'
colours, and a quieter atmosphere.

The game draws the crowd as flat panels over the seats: the meshes tagged
rwh0..rwh3 in a scene pack's Stadium.o (every stock stadium; the exe also
binds rwa0-3 and rwn0-3, never used). Each panel is its own 4-vertex quad,
textured with the 16 frames of the pack's Crowd.fsh (512x128 DXT5, lo00-03
seated, me01-02, hi00-09 cheering), animated by the game.

- size: a share of the panels is removed (its 4 vertices collapsed onto one
  point), the ends and upper tiers first, so the fans sit centre and low.
- colours: the clothes in all 16 frames repainted in patches of the home and
  away kits' colours (fixed in the texture, so they don't flicker as frames
  change); skin, hair and jeans are kept.
- mood "quiet": Xml/Sound/crowd.xml modifiers and crowdconst.xml excitement
  rates scaled down (loose copies next to the exe).
"""
import re
import struct

import numpy as np
from PIL import Image

from shared.log import get_logger
from shared.omodel.bigfile import BigArchive, pack_big

log = get_logger(__name__)

#: The crowd choices (quick match, tournament options), shown in expert mode
#: only (outside it: the game's own crowd in every match). False switches
#: them off for everyone.
OPTIONS_ENABLED = True

SIZES = {"full": 100, "busy": 75, "half": 50, "sparse": 25}   # % of the panels kept
MOODS = ("normal", "quiet")
CROWD_TAGS = ("rwh", "rwa", "rwn")
SOUND_EVENTS = "xml/sound/crowd.xml"
SOUND_CONSTANTS = "xml/sound/crowdconst.xml"

# share of fans in home colours / away colours (the rest keep their own)
HOME_SHARE, AWAY_SHARE = 0.55, 0.30
FAN_HALF_WIDTH = 12   # texels either side of a front-row fan's face he owns
SHIRT_ROWS = 24      # a front-row fan's shirt: rows under his face
MAX_PANEL = 1500.0   # longest edge of a crowd panel (game units, cm)


# ── kit colours ─────────────────────────────────────────────────────────────

def _common(im, n=8):
    """[(count, (r, g, b))] of `im`, most common first."""
    q = im.resize((64, 64)).quantize(n, method=Image.Quantize.MEDIANCUT)
    pal = q.getpalette()
    return [(c, tuple(pal[i * 3:i * 3 + 3])) for c, i in sorted(q.getcolors(), reverse=True)]


def kit_colours(path):
    """[(r, g, b), (r, g, b)]: the main colour of the kit texture at `path`
    (front of the shirt = its lower half) and the next clearly different one
    of the whole kit (shorts, trims); [] when it can't be read."""
    try:
        im = Image.open(path).convert("RGB")
    except (OSError, ValueError):
        return []
    w, h = im.size
    main = _common(im.crop((0, h // 2, w, h)))[0][1]
    for _n, c in _common(im):
        if sum((a - b) ** 2 for a, b in zip(c, main)) > 100 ** 2:
            return [main, c]
    return [main]


# ── frames ──────────────────────────────────────────────────────────────────

def _dxt5_alpha_blocks(alpha):
    """alpha: (n, 16) uint8 -> (n, 8) bytes of DXT5 alpha blocks."""
    a0 = alpha.max(1).astype(np.int32)
    a1 = alpha.min(1).astype(np.int32)
    lut = np.empty((len(alpha), 8), np.int32)
    lut[:, 0], lut[:, 1] = a0, a1
    for k in range(1, 7):
        lut[:, k + 1] = ((7 - k) * a0 + k * a1) // 7
    flat = a0 == a1
    lut[flat] = a0[flat, None]
    idx = np.abs(alpha[:, :, None].astype(np.int32) - lut[:, None, :]).argmin(2).astype(np.uint64)
    bits = (idx << (np.arange(16, dtype=np.uint64) * 3)).sum(1, dtype=np.uint64)
    out = np.zeros((len(alpha), 8), np.uint8)
    out[:, 0], out[:, 1] = a0, a1
    for b in range(6):
        out[:, 2 + b] = (bits >> np.uint64(8 * b)) & np.uint64(255)
    return out


def _565(c):
    c = c.astype(np.int32)
    return ((c[..., 0] >> 3) << 11) | ((c[..., 1] >> 2) << 5) | (c[..., 2] >> 3)


def _un565(v):
    r = (v >> 11) & 31
    g = (v >> 5) & 63
    b = v & 31
    return np.stack([(r << 3) | (r >> 2), (g << 2) | (g >> 4), (b << 3) | (b >> 2)], -1)


def _dxt_colour_blocks(rgb):
    """rgb: (n, 16, 3) uint8 -> (n, 8) bytes of 4-colour DXT blocks."""
    px = rgb.astype(np.int32)
    lum = px @ np.array([3, 6, 1])
    hi = px[np.arange(len(px)), lum.argmax(1)]
    lo = px[np.arange(len(px)), lum.argmin(1)]
    c0, c1 = _565(hi), _565(lo)
    swap = c0 < c1
    c0, c1 = np.where(swap, c1, c0), np.where(swap, c0, c1)
    e0, e1 = _un565(c0), _un565(c1)
    cols = np.stack([e0, e1, (2 * e0 + e1) // 3, (e0 + 2 * e1) // 3], 1)      # (n, 4, 3)
    d = ((px[:, :, None, :] - cols[:, None, :, :]) ** 2).sum(3)                # (n, 16, 4)
    idx = d.argmin(2).astype(np.uint32)
    idx[c0 == c1] = 0
    bits = (idx << (np.arange(16, dtype=np.uint32) * 2)).sum(1, dtype=np.uint32)
    out = np.zeros((len(px), 8), np.uint8)
    out[:, 0:2] = np.frombuffer(c0.astype("<u2").tobytes(), np.uint8).reshape(-1, 2)
    out[:, 2:4] = np.frombuffer(c1.astype("<u2").tobytes(), np.uint8).reshape(-1, 2)
    out[:, 4:8] = np.frombuffer(bits.astype("<u4").tobytes(), np.uint8).reshape(-1, 4)
    return out


def dxt5_encode(rgba):
    """(h, w, 4) uint8 -> DXT5 bytes (blocks row by row, as the game reads)."""
    h, w = rgba.shape[:2]
    blocks = rgba.reshape(h // 4, 4, w // 4, 4, 4).transpose(0, 2, 1, 3, 4).reshape(-1, 16, 4)
    out = np.concatenate([_dxt5_alpha_blocks(blocks[:, :, 3]), _dxt_colour_blocks(blocks[:, :, :3])], 1)
    return out.tobytes()


def _masks(rgba):
    """(seen, skin, hair) bool maps of a frame."""
    r, g, b = (rgba[..., i].astype(np.int32) for i in range(3))
    lum = 0.3 * r + 0.59 * g + 0.11 * b
    seen = rgba[..., 3] > 100
    skin = seen & (r - g >= 18) & (r - b >= 35) & (g - b >= -5) & (lum > 50)
    hair = seen & (lum < 30)
    return seen, skin, hair


def _rows(skin):
    """(back row, front row) face lines of a frame: where skin peaks."""
    s = np.convolve(skin.sum(1).astype(float), np.ones(5) / 5, mode="same")
    back = 8 + int(np.argmax(s[8:48]))
    lo = back + 16
    return back, lo + int(np.argmax(s[lo:back + 34]))


def _label(rgba, mask, tol=40, iters=200):
    """Connected regions of `mask` whose neighbouring texels are of one
    colour (sum of channel differences < tol): (h, w) int labels, -1 off it."""
    h, w = mask.shape
    col = rgba[..., :3].astype(np.int32)
    lab = np.where(mask, np.arange(h * w).reshape(h, w), h * w)
    joins = []
    for dy, dx in ((0, 1), (1, 0)):
        a = (slice(0, h - dy), slice(0, w - dx))
        b = (slice(dy, h), slice(dx, w))
        ok = mask[a] & mask[b] & (np.abs(col[a] - col[b]).sum(-1) < tol)
        joins.append((a, b, ok))
    for _ in range(iters):
        before = lab.copy()
        for a, b, ok in joins:
            m = np.minimum(lab[a], lab[b])
            lab[a] = np.where(ok, m, lab[a])
            lab[b] = np.where(ok, m, lab[b])
        if (lab == before).all():
            break
    return np.where(mask, lab, -1)


class _Fan:
    """One fan of a frame, found by his face: centre x, face box, row."""
    def __init__(self, cx, y0, y1, front):
        self.cx, self.y0, self.y1, self.front = cx, y0, y1, front


def _faces(skin, top, bottom, front):
    """[_Fan] of the face-sized skin blobs between rows top and bottom."""
    h, w = skin.shape
    band = np.zeros_like(skin)
    band[max(0, top):min(h, bottom)] = skin[max(0, top):min(h, bottom)]
    lab = _label(np.zeros(skin.shape + (3,), np.uint8), band, tol=1)
    out = []
    for value in np.unique(lab[lab >= 0]):
        ys, xs = np.nonzero(lab == value)
        bw, bh = xs.max() - xs.min() + 1, ys.max() - ys.min() + 1
        if 4 <= bw <= 13 and 5 <= bh <= 16 and len(ys) >= 16:
            out.append(_Fan(float(xs.mean()), int(ys.min()), int(ys.max()), front))
    out.sort(key=lambda f: f.cx)
    merged = []
    for f in out:                                  # one face cut in two
        if merged and abs(f.cx - merged[-1].cx) < 5:
            continue
        merged.append(f)
    return merged


def fans(rgba):
    """(owner, [_Fan]) of a frame: every texel's fan (index in the list,
    -1 none). A front-row fan owns his column from his face down; the back
    row shares the rest by nearest face."""
    seen, skin, hair = _masks(rgba)
    back, front = _rows(skin)
    h, w = skin.shape
    found = _faces(skin, back - 12, back + 8, False) + _faces(skin, front - 7, front + 7, True)
    owner = np.full((h, w), -1, np.int32)
    xs = np.arange(w)
    backs = [i for i, f in enumerate(found) if not f.front]
    if backs:
        cx = np.array([found[i].cx for i in backs])
        owner[:] = np.array(backs)[np.abs(xs[:, None] - cx[None, :]).argmin(1)][None, :]
    for i, f in enumerate(found):
        if f.front:
            cols = np.abs(xs - f.cx) <= FAN_HALF_WIDTH
            owner[max(0, f.y0 - 3):, cols] = i
    owner[~seen] = -1
    return owner, found


def _match(found, ref):
    """For each fan, the fan of the reference frame (same row, nearest face
    within 8 texels; -1 none): the same fan through an animation."""
    out = []
    for f in found:
        best = [(abs(r.cx - f.cx), j) for j, r in enumerate(ref) if r.front == f.front and abs(r.cx - f.cx) <= 8]
        out.append(min(best)[1] if best else -1)
    return out


def _shirt_colour(rgba, fan):
    """The fan's shirt colour: the median of a patch right under his face
    (None when there is nothing there)."""
    x0, x1 = int(round(fan.cx)) - 3, int(round(fan.cx)) + 4
    patch = rgba[fan.y1 + 3:fan.y1 + 9, max(0, x0):x1]
    patch = patch[patch[..., 3] > 100][:, :3]
    return np.median(patch, 0) if len(patch) >= 6 else None


def _like(rgba, ref):
    """(h, w) bool: texels of the colour `ref`, light or dark (same hue and
    saturation, brightness within a factor of about two)."""
    px = rgba[..., :3].astype(np.float32) + 8
    ref = np.asarray(ref, np.float32) + 8
    chroma = px / px.sum(-1, keepdims=True)
    ref_chroma = ref / ref.sum()
    ratio = px.sum(-1) / ref.sum()
    return (np.abs(chroma - ref_chroma).sum(-1) < 0.09) & (ratio > 0.45) & (ratio < 2.2)


def _shade(rgba):
    r, g, b = (rgba[..., i].astype(np.float32) for i in range(3))
    return np.clip((0.3 * r + 0.59 * g + 0.11 * b) / 150.0, 0.3, 1.5)[..., None]


def paint_frame(rgba, owner, roles, home, away):
    """The frame with each fan's clothes in his team's colours. roles: per
    fan (team 0 home / 1 away / 2 own clothes, second colour?, removed?,
    fan); removed fans are taken out of the picture."""
    out = rgba.copy()
    seen, skin, hair = _masks(rgba)
    shade = _shade(rgba)
    h = rgba.shape[0]
    ys = np.arange(h)[:, None]
    fronts = [f.y0 for _t, _a, _g, f in roles if f.front]
    front_line = int(np.median(fronts)) + 4 if fronts else h
    for i, (team, alt, gone, fan) in enumerate(roles):
        mine = owner == i
        if gone:
            out[..., 3] = np.where(mine & (ys >= fan.y0 - 4), 0, out[..., 3])
            continue
        colours = home if team == 0 else away if team == 1 else None
        if not colours:
            continue
        # the shirt: under the face, above the legs (front row) or the front
        # row's faces (back row), and of the colour found right under the face
        last = fan.y1 + SHIRT_ROWS if fan.front else front_line
        body = (ys > fan.y1) & (ys <= last)
        ref = _shirt_colour(rgba, fan)
        if ref is None:
            continue
        m = mine & body & ~skin & ~hair & _like(rgba, ref)
        col = np.array(colours[1] if alt and len(colours) > 1 else colours[0], np.float32)
        out[..., :3] = np.where(m[..., None], np.clip(col * shade, 0, 255), out[..., :3]).astype(np.uint8)
    return out


SETS = ("lo", "me", "hi")      # the frames of one animation (same fans)


def paint_crowd_fsh(blob, home, away, keep=1.0, seed=8):
    """Crowd.fsh bytes with the fans in the teams' colours (home/away =
    [main, second] colours; a side with none keeps its fans' own clothes)
    and only `keep` of them left. A fan keeps his colours and his seat all
    through his animation (lo / me / hi frames)."""
    from shared.omodel.fshlib import Fsh
    fsh = Fsh(blob)
    rng = np.random.default_rng(seed)
    refs = {}                                   # set -> (labels, roles)
    entries = sorted((e for e in fsh.entries if e.code == 0x62), key=lambda e: e.name)
    for e in entries:
        rgba = np.array(e.decode())
        owner, found = fans(rgba)
        key = e.name[:2]
        if key not in refs:
            roles = []
            for fan in found:
                r = rng.random()
                team = 0 if r < HOME_SHARE else 1 if r < HOME_SHARE + AWAY_SHARE else 2
                roles.append((team, rng.random() < 0.25, rng.random() >= keep, fan))
            # an empty front seat empties the back-row seat behind it too
            for i, (t, a_, gone, fan) in enumerate(roles):
                if not gone and not fan.front and any(
                        g and f.front and abs(f.cx - fan.cx) < FAN_HALF_WIDTH for _t, _a, g, f in roles):
                    roles[i] = (t, a_, True, fan)
            refs[key] = roles
            mine = roles
        else:
            ref = refs[key]
            mine = []
            for fan, m in zip(found, _match(found, [r[3] for r in ref])):
                t, a_, gone = ref[m][:3] if m >= 0 else (2, False, False)
                mine.append((t, a_, gone, fan))
        if not (home or away) and keep >= 1.0:
            continue
        enc = dxt5_encode(paint_frame(rgba, owner, mine, home, away))
        if len(enc) != e.pixlen:
            raise ValueError(f"crowd frame {e.name}: encoded size {len(enc)} != {e.pixlen}")
        fsh.blob[e.pixofs:e.pixofs + e.pixlen] = enc
    return bytes(fsh.blob)


# ── stands ──────────────────────────────────────────────────────────────────

def _quads(mesh):
    """Lists of vertex indices, one per crowd panel (vertices joined by a
    triangle)."""
    parent = list(range(len(mesh.positions)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i
    pos = np.array(mesh.positions, np.float32)
    for a, b, c in mesh.triangles:
        # the strip's joins between panels: one long thin triangle, no panel
        if max(np.linalg.norm(pos[a] - pos[b]), np.linalg.norm(pos[b] - pos[c]),
               np.linalg.norm(pos[a] - pos[c])) > MAX_PANEL:
            continue
        ra, rb, rc = find(a), find(b), find(c)
        parent[rb] = ra
        parent[rc] = ra
    groups = {}
    for i in range(len(parent)):
        groups.setdefault(find(i), []).append(i)
    return [g for g in groups.values() if len(g) >= 3]


def _pitch_axes(meshes):
    """(half length, half width, length axis 0=x/2=z) of the pitch, from the
    crowd's own spread when the stadium has no pitch mesh here."""
    pts = np.array([p for m in meshes for p in m.positions], np.float32)
    ex, ez = np.abs(pts[:, 0]).max(), np.abs(pts[:, 2]).max()
    return (ez, ex, 2) if ez >= ex else (ex, ez, 0)


def thin_stadium(blob, keep_pct, seed=5):
    """Stadium.o bytes with only `keep_pct` % of the crowd panels left (by
    area): the panels far from halfway and high up go first."""
    from shared.omodel.olib import parse_o
    if keep_pct >= 100:
        return blob
    meshes = [m for m in parse_o(blob) if (m.shapename or "")[:3] in CROWD_TAGS]
    if not meshes:
        return blob
    half_len, half_wid, axis = _pitch_axes(meshes)
    other = 0 if axis == 2 else 2
    ys = np.array([p[1] for m in meshes for p in m.positions], np.float32)
    ymin, ymax = float(ys.min()), float(max(ys.max(), ys.min() + 1))
    rng = np.random.default_rng(seed)
    panels = []
    for m in meshes:
        for q in _quads(m):
            pts = np.array([m.positions[i] for i in q], np.float32)
            c = pts.mean(0)
            span = np.ptp(pts, 0)
            area = float(max(span[axis], span[other]) * max(span[1], 1.0))
            along = abs(c[axis]) / max(half_len, 1.0)
            height = (c[1] - ymin) / (ymax - ymin)
            # the ends: further along the pitch than the posts' side of it
            score = 0.65 * along + 0.35 * height + 0.25 * rng.random()
            panels.append((score, area, m, q))
    panels.sort(key=lambda p: p[0])
    total = sum(p[1] for p in panels) or 1.0
    data = bytearray(blob)
    kept = 0.0
    for score, area, m, q in panels:
        if kept + area <= total * keep_pct / 100.0 or kept == 0.0:
            kept += area
            continue
        x, y, z = m.positions[q[0]]
        for i in q:
            struct.pack_into("<3f", data, m.vertex_offset + i * m.stride, x, y, z)
    return bytes(data)


# ── scene pack ──────────────────────────────────────────────────────────────

def apply(path, size="full", home=None, away=None):
    """Rewrite the scene pack at `path`: its stands `size` (SIZES) full and,
    given the teams' colours, the fans in them. False when nothing changed."""
    keep = SIZES.get(size, 100)
    if keep >= 100 and not (home or away):
        return False
    with open(path, "rb") as fh:
        archive = BigArchive(fh.read())
    changed = {}
    if keep < 100:
        name = archive.find("Stadium.o")
        if name:
            changed[name] = thin_stadium(archive.read(name), keep)
    if home or away:
        name = archive.find("Crowd.fsh")
        if name:
            changed[name] = paint_crowd_fsh(archive.read(name), home or [], away or [])
    if not changed:
        return False
    entries = [(n, changed.get(n) or archive.read(n)) for n in archive.entries]
    with open(path, "wb") as fh:
        fh.write(pack_big(entries))
    return True


# ── sound ───────────────────────────────────────────────────────────────────

QUIET = 0.5          # crowd reactions at half strength
QUIET_DECAY = 1.6    # and dying away faster


def quiet_events(xml):
    """crowd.xml bytes with every reaction's modifier scaled by QUIET."""
    def scale(m):
        return m.group(1) + f"{float(m.group(2)) * QUIET:.2f}".encode() + m.group(3)
    return re.sub(rb'(modifier=")([0-9.]+)(")', scale, xml)


def quiet_constants(xml):
    """crowdconst.xml bytes: excitement builds slower and decays faster."""
    def scale(m):
        name, value = m.group(2).decode(), float(m.group(4))
        if name.startswith("m_rExciteRate") or name.endswith("Bonus") and value > 0:
            value *= QUIET
        elif "Decay" in name and "Threshold" not in name:
            value *= QUIET_DECAY
        else:
            return m.group(0)
        return m.group(1) + m.group(2) + m.group(3) + f"{value:.4g}".encode() + m.group(5)
    return re.sub(rb'(name=")([A-Za-z_]+)(" value=")([-0-9.]+)(")', scale, xml)
