"""
ui/stadium_view.py — a whole stadium in 3D (the stadium editor's preview)
==========================================================================
The scene pack's own models and textures (backend/stadium_scene.py) with
the dressing picked on top: pads, flags, posts and ad boards. Drawn through
the same offscreen GL path as the other previews (ui/player_view._GLSurface)
and only when something changes: the camera, the textures, the size.

Camera: an orbit around a target. Drag turns it, right / middle drag (or
Shift + drag) slides it, the wheel zooms; `set_view(name)` jumps to one of
VIEWS (pulled in when a stand is in the way). Environment sets the sky
(a gradient under the pack's own dome), the haze over distance, and how
bright the lamps of the pack's fx (Scene.lights) glow.
"""
import ctypes
import math

import numpy as np
from OpenGL import GL
from PyQt5.QtCore import QPoint, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter
from PyQt5.QtWidgets import QWidget

from backend.pitch_stripes import MASKS
from shared.log import get_logger
from ui.player_view import _GLSurface, _look_at, _perspective

log = get_logger(__name__)

VERT = """
#version 330 core
layout(location=0) in vec3 in_pos;
layout(location=1) in vec3 in_nrm;
layout(location=2) in vec2 in_uv;
layout(location=3) in vec4 in_col;
uniform mat4 u_mvp;
uniform vec3 u_eye;
out vec2 v_uv;
out vec4 v_col;
out float v_dist;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_uv = in_uv;
    v_col = in_col;
    v_dist = length(in_pos - u_eye);
}
"""

# The game's own lighting is baked into the vertex colours: a "Texture2x"
# material is texture * colour * 2 (a grey of 0x80 leaves the texture as it
# is), "Texture" texture * colour, "Gouraud" the colour * 2.
FRAG = """
#version 330 core
in vec2 v_uv;
in vec4 v_col;
in float v_dist;
uniform sampler2D u_tex;
uniform sampler2D u_mask;   // the pitch's mowing mask
uniform vec3 u_mow;         // x: 1 = mow the grass, y: stripe strength, z: grass gain
uniform vec4 u_colour;      // a = 0: use the texture, else this flat colour
uniform int u_mode;         // 0: texture * colour * 2, 1: texture * colour, 2: colour * 2
uniform float u_cut;        // alpha below this is dropped
uniform float u_alpha;      // 1: the picture's alpha is kept (blended passes)
uniform vec4 u_fog;         // rgb: the haze (or what leaves a blended layer as it is), a: density
out vec4 frag;
void main() {
    vec4 tex = u_colour.a > 0.0 ? u_colour : texture(u_tex, v_uv);
    if (u_mode == 2) tex = vec4(1.0);
    vec4 c = tex * v_col;
    if (c.a < u_cut) discard;
    vec3 rgb = c.rgb * (u_mode == 1 ? 1.0 : 2.0);
    if (u_mow.x > 0.5) {
        float band = clamp(texture(u_mask, v_uv).MASKCH / 0.74, 0.0, 1.0);
        rgb *= u_mow.z * (1.0 + u_mow.y * (band - 0.5));
    }
    float f = 1.0 - exp(-pow(v_dist * u_fog.a, 2.0));
    rgb = mix(rgb, u_fog.rgb, f);
    frag = vec4(rgb, u_alpha > 0.5 ? c.a : 1.0);
}
"""

MASK_CHANNEL = "r"          # the mowing mask's band channel
FRAG = FRAG.replace("MASKCH", MASK_CHANNEL)

# environment -> the sky under the dome (top, horizon), the haze (colour,
# density per unit) and how bright the lamps glow (the scene packs hold the rest)
ENVIRONMENTS = {
    "day": {"sky": ((0.26, 0.47, 0.80), (0.70, 0.80, 0.91)), "haze": ((0.72, 0.80, 0.90), 2.4e-5),
            "lamps": 0.0},
    "overcast": {"sky": ((0.50, 0.55, 0.61), (0.74, 0.76, 0.79)), "haze": ((0.70, 0.72, 0.75), 3.6e-5),
                 "lamps": 0.45},
    "night": {"sky": ((0.005, 0.01, 0.03), (0.06, 0.08, 0.14)), "haze": ((0.05, 0.07, 0.12), 2.6e-5),
              "lamps": 1.0},
    "cold": {"sky": ((0.55, 0.63, 0.74), (0.82, 0.85, 0.90)), "haze": ((0.80, 0.83, 0.88), 4.0e-5),
             "lamps": 0.45},
}
SKY = {env: e["sky"][1] for env, e in ENVIRONMENTS.items()}
# lamp kind -> (glow colour, core size, halo size) in world units
LAMPS = {"flood": ((0.86, 0.92, 1.0), 300.0, 1300.0), "pin": ((1.0, 0.86, 0.62), 100.0, 320.0)}

# name -> (yaw, pitch, distance, target): yaw 0 looks from +z (behind the
# posts at that end), -90 from -x (the main stand side)
VIEWS = {
    "broadcast": (-90.0, 24.0, 3400.0, (700.0, 0.0, 0.0)),
    "corner": (-142.0, 24.0, 3600.0, (0.0, 0.0, 0.0)),
    "posts": (180.0, 10.0, 2300.0, (0.0, 250.0, -2700.0)),
    "pitch": (-62.0, 3.0, 2300.0, (0.0, 160.0, -2000.0)),
    "aerial": (-90.0, 82.0, 10500.0, (0.0, 0.0, 0.0)),
}
VIEW_LABELS = {"broadcast": "Main stand", "corner": "Corner", "posts": "Behind posts",
               "pitch": "Pitch level", "aerial": "From above"}

# untextured parts: tag -> colour (the rest a neutral grey)
FLAT = {"lina": (1.0, 1.0, 1.0, 1.0), "linb": (1.0, 1.0, 1.0, 1.0),
        "": (0.58, 0.58, 0.60, 1.0), "__grass__": (0.24, 0.42, 0.18, 1.0)}
# what each match fills with its teams (flags, banners): a neutral stand-in here
TEAM_TAGS = {"hflA", "hflB", "aflA", "aflB", "hbnA", "hbnB", "abnA", "abnB", "Baus", "Bwal"}
FLAT.update({t: (0.82, 0.84, 0.86, 1.0) for t in TEAM_TAGS})
# the teams' flags laid on the pitch (World Cup stadiums): only with a team's picture
PITCH_FLAGS = {"Baus", "Bwal"}
# untextured parts drawn anyway (the dressing gets its textures from the sets)
FLAT_KEEP = {"lina", "linb","pada", "padb", "flag", "flgp", "post", "xbar", "ads0", "ads1", "ads2", "ads3",
             "ads4", "ads5", "ads6", "ads7", "ads8"} | TEAM_TAGS
MIN_DIST, MAX_DIST = 400.0, 16000.0
_UNSET = object()
MODES = {"Texture2x": 0, "ScrollTexture2x": 0, "MowPattern": 0, "Texture": 1, "Gouraud": 2}
# the pitch layers drawn over the grass, in order: model -> blend function
DECALS = {"PitchDetail.o": (GL.GL_DST_COLOR, GL.GL_SRC_COLOR),     # detail tile: dst * src * 2
          "PitchShadow.o": (GL.GL_ZERO, GL.GL_SRC_COLOR),          # shadow: darkens
          "PitchLines.o": None}


class _Mesh:
    """One uploaded mesh and how it is drawn."""
    __slots__ = ("vao", "count", "tag", "bufs", "own", "model", "mode", "soft", "numbers")

    def __init__(self, vao, count, tag, bufs, own=False, model="", mode=0, soft=False):
        self.vao, self.count, self.tag, self.bufs = vao, count, tag, bufs
        self.own, self.model, self.mode, self.soft = own, model, mode, soft
        self.numbers = False


def _glow_picture(size):
    """RGBA bytes of a lamp's glow: white, alpha a soft round falloff with a
    faint four-point star."""
    r = (np.arange(size, dtype=np.float32) + 0.5) / size * 2.0 - 1.0
    x, y = np.meshgrid(r, r)
    d = np.sqrt(x * x + y * y)
    core = np.exp(-(d / 0.22) ** 2)
    soft = np.exp(-(d / 0.55) ** 2) * 0.45
    star = (np.exp(-(np.abs(x) / 0.025) ** 2) + np.exp(-(np.abs(y) / 0.025) ** 2)) * np.clip(1.0 - d, 0, 1) ** 2 * 0.35
    a = np.clip(core + soft + star, 0.0, 1.0) * np.clip((1.0 - d) * 4.0, 0.0, 1.0)
    rgba = np.empty((size, size, 4), np.uint8)
    rgba[..., :3] = 255
    rgba[..., 3] = (a * 255).astype(np.uint8)
    return rgba.tobytes()


CUT = 0.35          # alpha under which a cut-out picture (people, rails) shows nothing
CORE_CUT = 0.75     # a see-through picture's part solid enough to hide what is behind it


def _bleed(rgba):
    """`rgba` with the colour of its see-through texels taken from their
    opaque neighbours (they're black in the game's pictures: filtering
    mixed them in as dark fringes)."""
    out = rgba.astype(np.float32)
    solid = out[..., 3] > 8
    if solid.all() or not solid.any():
        return rgba
    rgb, have = out[..., :3] * solid[..., None], solid.astype(np.float32)
    for _ in range(16):
        if have.all():
            break
        acc, n = np.zeros_like(rgb), np.zeros_like(have)
        for dy, dx in ((0, 1), (0, -1), (1, 0), (-1, 0)):
            acc += np.roll(rgb * have[..., None], (dy, dx), (0, 1))
            n += np.roll(have, (dy, dx), (0, 1))
        grow = (have == 0) & (n > 0)
        rgb[grow] = acc[grow] / n[grow][:, None]
        have = np.maximum(have, grow.astype(np.float32))
    if not have.all():
        rgb[have == 0] = rgb[have > 0].mean(axis=0)
    out[..., :3] = np.where(solid[..., None], out[..., :3], rgb)
    return out.round().astype(np.uint8)


def _alpha_mipmaps(rgba, cut):
    """(picture, [mip levels]) of an (H, W, 4) uint8 picture with see-through
    parts. Colours are averaged by their alpha (no dark fringes). With `cut`
    (a cut-out picture) each level's alpha is scaled so as much of it stays
    over `cut` as in the picture: averaged alpha alone turns distant people
    into solid boxes or makes them vanish."""
    base = _bleed(rgba)
    a0 = base[..., 3].astype(np.float32) / 255.0
    cover = float((a0 >= cut).mean()) if cut is not None else 0.0
    levels = []
    cur = base.astype(np.float32) / 255.0
    while cur.shape[0] > 1 or cur.shape[1] > 1:
        fy, fx = (2 if cur.shape[0] > 1 else 1), (2 if cur.shape[1] > 1 else 1)
        h, w = cur.shape[0] // fy, cur.shape[1] // fx
        c = cur[:h * fy, :w * fx].reshape(h, fy, w, fx, 4)
        a = c[..., 3].mean(axis=(1, 3))
        # colour weighted by alpha, so see-through texels don't pull it to black
        rgb = (c[..., :3] * c[..., 3:4]).mean(axis=(1, 3)) / np.maximum(a[..., None], 1e-4)
        rgb = np.where(a[..., None] > 1e-4, rgb, c[..., :3].mean(axis=(1, 3)))
        cur = np.concatenate([rgb, a[..., None]], axis=-1)
        out = cur.copy()
        if cut is not None and cover > 0.0:
            lo, hi = 0.0, 8.0
            for _ in range(14):
                mid = (lo + hi) / 2
                if float((np.clip(a * mid, 0, 1) >= cut).mean()) < cover:
                    lo = mid
                else:
                    hi = mid
            # a little over the smallest scale, so the edge isn't on the cut
            out[..., 3] = np.clip(a * hi * 1.1, 0.0, 1.0)
        levels.append((np.clip(out, 0, 1) * 255).round().astype(np.uint8))
    return base, levels


class StadiumRenderer:
    """GL side (initialize()/draw(w, h), the contract _GLSurface drives)."""

    def __init__(self):
        self.yaw, self.pitch, self.dist = VIEWS["broadcast"][:3]
        self.target = np.array(VIEWS["broadcast"][3], dtype=np.float32)
        self.environment = "day"
        self.transparent = False
        self.bare = False                # no stadium: only the pitch laid with set_pitch
        self._scene = None
        self._scene_pending = None
        self._tex_pending = {}
        self._pitch_pending = _UNSET
        self._program = None
        self._parts = []                 # [_Mesh] of the scene
        self._pitch_parts = []           # the picked pitch texture's, tags "pitch:tp01"...
        self.stripes = None              # (strength, gain) of the mowing, None = plain
        self._logo_pending = _UNSET
        self._logo_parts = []            # the pitch logos, tags "logo:loga" / "logo:logb"
        self._ground = FLAT["__grass__"]
        self._tex = {}                   # tag -> GL texture
        self._soft = set()               # tags of textures with soft (partial) alpha
        self._grey = None
        self._glow = None                # the lamps' glow picture
        self._lamp_vao = None            # their billboards, rebuilt each frame
        self.scene = None                # the scene shown (camera fits, lamps)
        self.line_style = ""             # backend/pitch_lines style
        self._sky_mesh = None
        self._haze = (0.0, 0.0, 0.0, 0.0)

    # ── data in ─────────────────────────────────────────────────────────
    def set_scene(self, scene):
        self._scene_pending = scene
        self.scene = scene if getattr(scene, "parts", None) else None

    def fit_camera(self):
        """Bring the eye out of a stand: while the first face it sees, toward
        the target or along the bottom of the picture, is a back face (the
        eye is behind or inside the stand, or behind a board), move the eye
        forward past that face."""
        if self.scene is None or not hasattr(self.scene, "ray_hit"):
            return
        for _ in range(8):
            eye = self.eye()
            offset = self.target - eye
            length = float(np.linalg.norm(offset))
            if length < MIN_DIST:
                return
            forward = offset / length
            right = np.cross(forward, (0.0, 1.0, 0.0))
            right /= max(float(np.linalg.norm(right)), 1e-6)
            down = np.cross(right, forward)
            step = 0.0
            for tilt in (0.0, -0.33):                  # the centre, near the bottom edge
                d = forward + down * tilt
                d /= float(np.linalg.norm(d))
                hit, normal = self.scene.ray_hit(eye, d)
                along = hit * float(np.dot(d, forward))
                if along < length and normal is not None and float(np.dot(normal, d)) > 0.1:
                    step = max(step, along + 120.0)
            if not step:
                return
            self.dist = max(MIN_DIST * 0.5, self.dist - step)

    def set_textures(self, images):
        """{tag: PIL image} over the scene's own (dressing)."""
        self._tex_pending.update(images)

    def set_logos(self, quads, images):
        """The pitch logos: backend/pitch_logos.quads() and {"loga" | "logb":
        PIL image}; None = none."""
        self._logo_pending = (quads, images) if quads else None

    def set_pitch(self, pitch):
        """The pitch texture (backend/pitches.scene) laid instead of the
        scene's own grass; None = the scene's own."""
        self._pitch_pending = pitch

    def set_stripes(self, stripes):
        """(strength, gain) of the grass' mowing (backend/pitch_stripes.contrast);
        None = no stripes, the grass as its tiles are."""
        self.stripes = stripes

    # ── GL ──────────────────────────────────────────────────────────────
    def initialize(self):
        def shader(src, kind):
            sid = GL.glCreateShader(kind)
            GL.glShaderSource(sid, src)
            GL.glCompileShader(sid)
            if not GL.glGetShaderiv(sid, GL.GL_COMPILE_STATUS):
                raise RuntimeError(GL.glGetShaderInfoLog(sid).decode())
            return sid
        vs, fs = shader(VERT, GL.GL_VERTEX_SHADER), shader(FRAG, GL.GL_FRAGMENT_SHADER)
        prog = GL.glCreateProgram()
        GL.glAttachShader(prog, vs)
        GL.glAttachShader(prog, fs)
        GL.glLinkProgram(prog)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            raise RuntimeError(GL.glGetProgramInfoLog(prog).decode())
        self._program = prog
        self._grey = self._upload(1, 1, bytes([150, 150, 150, 255]))
        self._glow = self._upload(64, 64, _glow_picture(64))
        self._lamp_vao = (GL.glGenVertexArrays(1), *GL.glGenBuffers(2))

    @staticmethod
    def _upload(w, h, rgba, levels=None):
        """A texture of `rgba` bytes; `levels`: its own mipmaps (RGBA arrays,
        largest first after the picture), else GL's."""
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, rgba)
        if levels is None:
            GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        else:
            for i, level in enumerate(levels, 1):
                GL.glTexImage2D(GL.GL_TEXTURE_2D, i, GL.GL_RGBA, level.shape[1], level.shape[0], 0,
                                GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, np.ascontiguousarray(level).tobytes())
            GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAX_LEVEL, len(levels))
        for k, v in ((GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT), (GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT),
                     (GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR),
                     (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, k, v)
        try:            # sharp grass and lines at a low angle
            GL.glTexParameterf(GL.GL_TEXTURE_2D, 0x84FE, 8.0)    # GL_TEXTURE_MAX_ANISOTROPY
            GL.glGetError()
        except GL.GLError:
            pass
        return tex

    def _upload_image(self, tag, img):
        old = self._tex.pop(tag, None)
        self._soft.discard(tag)
        if old:
            GL.glDeleteTextures([old])
        if img is not None:
            rgba = img.convert("RGBA")
            alpha = np.asarray(rgba.getchannel("A"))
            soft = ((alpha > 8) & (alpha < 247)).mean() > 0.01
            if soft:
                self._soft.add(tag)           # leaves, fences, nets: blended, not cut out
            if alpha.min() < 247:
                pixels, levels = _alpha_mipmaps(np.asarray(rgba), None if soft else CUT)
                self._tex[tag] = self._upload(rgba.width, rgba.height, pixels.tobytes(), levels)
            else:
                self._tex[tag] = self._upload(rgba.width, rgba.height, rgba.tobytes())

    def _sync(self):
        if self._scene_pending is not None:
            scene, self._scene_pending = self._scene_pending, None
            self._free(self._parts)
            self._parts = []
            for tag in [t for t in self._tex if not t.startswith("pitch:")]:
                self._upload_image(tag, None)
            for tag, img in scene.textures.items():
                self._upload_image(tag, img)
            for part in scene.parts:
                if (part.tag not in scene.textures and part.tag not in FLAT_KEEP
                        and part.buf[:, 1].max() < 12.0 and part.model not in DECALS
                        and part.model != "sky.o"):
                    continue          # an untextured decal on the grass (team names, base quad)
                own = part.model == "PitchColour.o" and part.material == "MowPattern"
                mode = MODES.get(part.material, 0)
                if not part.tag and part.model == "Stadium.o":
                    mode = 1          # untagged (the big screen, painted per match): a dark grey
                soft = mode == 2 or part.tag in self._soft
                mesh = self._make_part(part.buf, part.tri, part.tag, own, part.model, mode, soft)
                mesh.numbers = getattr(part, "numbers", False)
                self._parts.append(mesh)
            if scene.parts or self.bare:
                self._parts.insert(0, self._grass())
            self._scene = scene
        if self._logo_pending is not _UNSET:
            pending, self._logo_pending = self._logo_pending, _UNSET
            self._free(self._logo_parts)
            self._logo_parts = []
            quads, images = pending or ({}, {})
            for tag, (pos, uv, tris) in quads.items():
                if not tris:
                    continue
                buf = np.array([[x, y + 1.5, z, 0, 1, 0, u, v, 1, 1, 1, 1] for (x, y, z), (u, v) in zip(pos, uv)],
                               dtype=np.float32)
                tri = np.array(tris, dtype=np.uint32).ravel()
                self._logo_parts.append(self._make_part(buf, tri, "logo:" + tag, mode=1, soft=True))
            for tag in ("loga", "logb"):
                self._upload_image("logo:" + tag, images.get(tag))
        if self._pitch_pending is not _UNSET:
            pitch, self._pitch_pending = self._pitch_pending, _UNSET
            self._free(self._pitch_parts)
            self._pitch_parts = []
            for tag in [t for t in self._tex if t.startswith("pitch:")]:
                self._upload_image(tag, None)
            self._ground = FLAT["__grass__"]
            if pitch is not None:
                for part in pitch.parts:
                    if part.model == "PitchColour.o":
                        self._pitch_parts.append(self._make_part(part.buf, part.tri, "pitch:" + part.tag,
                                                                 model=part.model))
                    elif part.model == "PitchDetail.o":
                        # the playing surface's detail (the scene's covers the surround only)
                        self._pitch_parts.append(self._make_part(part.buf, part.tri, "pitch:" + part.tag,
                                                                 model=part.model, mode=1))
                for tag, img in pitch.textures.items():
                    self._upload_image("pitch:" + tag, img)
                main = pitch.textures.get("tp02") or next(iter(pitch.textures.values()), None)
                if main is not None:
                    rgb = np.asarray(main.convert("RGB").resize((8, 8)), dtype=np.float32).reshape(-1, 3).mean(0) / 255
                    self._ground = (*(rgb * 0.9), 1.0)
        if self._tex_pending:
            pending, self._tex_pending = self._tex_pending, {}
            for tag, img in pending.items():
                self._upload_image(tag, img)

    @staticmethod
    def _make_part(buf, tri, tag, own=False, model="", mode=0, soft=False):
        if buf.shape[1] == 8:                         # no vertex colours: white
            buf = np.concatenate([buf, np.ones((len(buf), 4), np.float32)], axis=1)
        buf = np.ascontiguousarray(buf, dtype=np.float32)
        vao = GL.glGenVertexArrays(1)
        GL.glBindVertexArray(vao)
        vbo, ebo = GL.glGenBuffers(2)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, buf.tobytes(), GL.GL_STATIC_DRAW)
        for loc, size, off in ((0, 3, 0), (1, 3, 12), (2, 2, 24), (3, 4, 32)):
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, GL.GL_FALSE, 48, ctypes.c_void_p(off))
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ebo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, tri.tobytes(), GL.GL_STATIC_DRAW)
        GL.glBindVertexArray(0)
        return _Mesh(vao, int(tri.size), tag, [vbo, ebo], own, model, mode, soft)

    @staticmethod
    def _free(parts):
        for m in parts:
            GL.glDeleteVertexArrays(1, [m.vao])
            GL.glDeleteBuffers(len(m.bufs), m.bufs)

    def _grass(self):
        """A plain grass field under the pitch: stock stadiums take theirs
        from separate pitch packs the scene doesn't hold."""
        x, z, y = 2600.0, 4300.0, -2.0
        buf = np.array([[-x, y, -z, 0, 1, 0, 0, 0], [x, y, -z, 0, 1, 0, 1, 0],
                        [x, y, z, 0, 1, 0, 1, 1], [-x, y, z, 0, 1, 0, 0, 1]], dtype=np.float32)
        return self._make_part(buf, np.array([0, 1, 2, 0, 2, 3], dtype=np.uint32), "__grass__", mode=1)

    def eye(self):
        y, p = math.radians(self.yaw), math.radians(self.pitch)
        offset = np.array([math.cos(p) * math.sin(y), math.sin(p), math.cos(p) * math.cos(y)],
                          dtype=np.float32) * self.dist
        return self.target + offset

    def matrices(self, width, height):
        up = (0.0, 0.0, -1.0) if self.pitch > 80 else (0.0, 1.0, 0.0)
        view = _look_at(self.eye(), self.target, up)
        proj = _perspective(42.0, max(1e-3, width / max(1, height)), 30.0, 60000.0)
        return proj, view

    def ground_at(self, fx, fy, width, height):
        """(x, z) of the grass under the point (fx, fy) of the picture
        (fractions of its width and height), None above the horizon."""
        proj, view = self.matrices(width, height)
        inv = np.linalg.inv(proj @ view)
        nx, ny = fx * 2.0 - 1.0, 1.0 - fy * 2.0
        near = inv @ np.array([nx, ny, -1.0, 1.0])
        far = inv @ np.array([nx, ny, 1.0, 1.0])
        near, far = near[:3] / near[3], far[:3] / far[3]
        d = far - near
        if abs(d[1]) < 1e-6:
            return None
        t = -near[1] / d[1]
        if t <= 0:
            return None
        p = near + d * t
        return float(p[0]), float(p[2])

    def draw(self, width, height, t=None):
        self._sync()
        GL.glViewport(0, 0, width, height)
        env = ENVIRONMENTS.get(self.environment, ENVIRONMENTS["day"])
        GL.glClearColor(*env["sky"][1], 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        if not self._parts:
            return
        GL.glDisable(GL.GL_CULL_FACE)
        proj, view = self.matrices(width, height)
        prog = self._program
        GL.glUseProgram(prog)
        loc = lambda name: GL.glGetUniformLocation(prog, name)
        self._u = {n: loc(n) for n in ("u_mvp", "u_colour", "u_mode", "u_cut", "u_alpha", "u_mow",
                                       "u_fog", "u_eye")}
        self._haze = (*env["haze"][0], 0.0 if self.bare else env["haze"][1])
        eye = self.eye()
        GL.glUniform3f(self._u["u_eye"], *(float(v) for v in eye))
        GL.glUniform1i(loc("u_tex"), 0)
        GL.glUniform1i(loc("u_mask"), 1)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBlendFuncSeparate(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ZERO, GL.GL_ONE)
        mvp = proj @ view
        own = not self._pitch_parts            # the scene's own grass unless a pitch is laid
        sky = [m for m in self._parts if m.model == "sky.o"]
        decals = {k: [m for m in self._parts + self._pitch_parts if m.model == k] for k in DECALS}
        rest = [m for m in self._parts if m.model != "sky.o" and m.model not in DECALS
                and not (m.own and not own)]
        # sky: a gradient, the pack's dome around the eye, behind everything
        GL.glDisable(GL.GL_DEPTH_TEST)
        GL.glUniform4f(self._u["u_fog"], 0.0, 0.0, 0.0, 0.0)
        self._draw_sky_gradient(proj, view, env["sky"])
        if sky:
            dome = view.copy()
            dome[:3, 3] = 0.0
            GL.glUniform3f(self._u["u_eye"], 0.0, 0.0, 0.0)
            GL.glUniformMatrix4fv(self._u["u_mvp"], 1, GL.GL_TRUE, proj @ dome)
            for m in sky:
                self._draw_part(m)
            GL.glUniform3f(self._u["u_eye"], *(float(v) for v in eye))
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glUniformMatrix4fv(self._u["u_mvp"], 1, GL.GL_TRUE, mvp)
        GL.glUniform4f(self._u["u_fog"], *self._haze)
        # the grass: the laid pitch (or the scene's own), the field under it
        ground = [m for m in rest if m.own or m.tag == "__grass__" or m.model == "PitchColour.o"]
        for m in self._pitch_parts:
            if m.model not in DECALS:
                self._draw_part(m, grass=True)
        for m in ground:
            if not m.soft:
                self._draw_part(m, grass=m.own)
        # the layers on the grass, laid as the game does: right after it,
        # without depth (the shadows dip under the grass in places), the
        # stadium drawn over them after
        GL.glEnable(GL.GL_BLEND)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glDisable(GL.GL_DEPTH_TEST)
        for key, func in DECALS.items():
            if func:
                GL.glBlendFunc(*func)
            else:
                GL.glBlendFuncSeparate(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ZERO, GL.GL_ONE)
            # the haze fades a multiplying layer to what leaves the grass as it is
            neutral = {"PitchDetail.o": 0.5, "PitchShadow.o": 1.0}.get(key)
            if neutral is not None:
                GL.glUniform4f(self._u["u_fog"], neutral, neutral, neutral, self._haze[3])
            for m in decals[key]:
                if not (m.numbers and self.line_style == "no_numbers"):
                    self._draw_part(m, layer=key)
            GL.glUniform4f(self._u["u_fog"], *self._haze)
        GL.glBlendFuncSeparate(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ZERO, GL.GL_ONE)
        for m in self._logo_parts:
            if m.tag in self._tex:
                self._draw_part(m, layer="logo")
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)
        # the stadium
        for m in rest:
            if not m.soft and m not in ground:
                self._draw_part(m)
        GL.glEnable(GL.GL_BLEND)
        GL.glDepthMask(GL.GL_FALSE)
        # the see-through parts (leaves, fences, nets, the crowd's edges):
        # their solid middle first, hiding what is behind it, then the
        # soft edges blended over what is left
        soft = [m for m in rest if m.soft]
        GL.glDepthMask(GL.GL_TRUE)
        for m in soft:
            self._draw_part(m, layer="core")
        GL.glDepthMask(GL.GL_FALSE)
        GL.glDepthFunc(GL.GL_LESS)          # the middles drawn already fail: equal depth
        for m in soft:
            self._draw_part(m, layer="soft")
        self._draw_lamps(view, eye, env["lamps"])
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)
        GL.glBindVertexArray(0)

    def _draw_sky_gradient(self, proj, view, colours):
        """Top colour overhead to the horizon colour at eye level: a quad
        over the whole picture, coloured by where each corner looks."""
        inv = np.linalg.inv(proj @ view)
        top, horizon = np.array(colours[0]), np.array(colours[1])
        rows = []
        for nx, ny in ((-1, -1), (1, -1), (1, 1), (-1, 1)):
            far = inv @ np.array([nx, ny, 1.0, 1.0])
            d = far[:3] / far[3] - self.eye()
            up = max(0.0, float(d[1] / (np.linalg.norm(d) or 1.0)))
            col = horizon + (top - horizon) * min(1.0, up * 1.6) ** 0.7
            rows.append([nx, ny, 0.9999, 0, 0, 1, 0, 0, *(col * 0.5), 1.0])
        if self._sky_mesh is None:
            self._sky_mesh = self._make_part(np.array(rows, np.float32), np.array([0, 1, 2, 0, 2, 3], np.uint32),
                                             "__sky__", mode=2)
        else:
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, self._sky_mesh.bufs[0])
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0, np.array(rows, np.float32).tobytes())
        GL.glUniformMatrix4fv(self._u["u_mvp"], 1, GL.GL_TRUE, np.eye(4, dtype=np.float32))
        GL.glUniform4f(self._u["u_colour"], 1.0, 1.0, 1.0, 1.0)
        GL.glUniform1i(self._u["u_mode"], 2)
        GL.glUniform1f(self._u["u_cut"], -1.0)
        GL.glUniform1f(self._u["u_alpha"], 0.0)
        GL.glUniform3f(self._u["u_mow"], 0.0, 0.0, 1.0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._grey)
        GL.glBindVertexArray(self._sky_mesh.vao)
        GL.glDrawElements(GL.GL_TRIANGLES, 6, GL.GL_UNSIGNED_INT, None)

    def _draw_lamps(self, view, eye, strength):
        """The pack's lamps (Scene.lights) as glows facing the eye: a bright
        core and a wide soft halo each, added to the picture."""
        lights = getattr(self.scene, "lights", None) if self.scene is not None else None
        if not lights or strength <= 0.0 or self._lamp_vao is None:
            return
        right, up = view[0, :3], view[1, :3]
        corners = ((-1, -1, 0, 1), (1, -1, 1, 1), (1, 1, 1, 0), (-1, 1, 0, 0))
        blocks = []
        for kind, pts in lights:
            colour, core, halo = LAMPS[kind]
            toward = eye[None, :] - pts
            toward /= np.maximum(np.linalg.norm(toward, axis=1, keepdims=True), 1e-3)
            centre = pts + toward * 160.0          # in front of the lamp's own housing
            for size, gain in ((halo, 0.22), (core, 1.0)):
                col = [*(np.array(colour) * strength * gain), 1.0]
                quad = np.zeros((len(pts), 4, 12), np.float32)     # point, corner, vertex
                for k, (cx, cy, u, v) in enumerate(corners):
                    quad[:, k, :3] = centre + (right * cx + up * cy) * size
                    quad[:, k, 3:12] = [0, 1, 0, u, v, *col]
                blocks.append(quad.reshape(-1, 12))
        buf = np.ascontiguousarray(np.concatenate(blocks), np.float32)
        count = len(buf) // 4
        tri = (np.arange(count, dtype=np.uint32)[:, None] * 4
               + np.array([0, 1, 2, 0, 2, 3], np.uint32)[None, :]).ravel()
        vao, vbo, ebo = self._lamp_vao
        GL.glBindVertexArray(vao)
        GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
        GL.glBufferData(GL.GL_ARRAY_BUFFER, buf.tobytes(), GL.GL_STREAM_DRAW)
        for loc, size, off in ((0, 3, 0), (1, 3, 12), (2, 2, 24), (3, 4, 32)):
            GL.glEnableVertexAttribArray(loc)
            GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, GL.GL_FALSE, 48, ctypes.c_void_p(off))
        GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ebo)
        GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, tri.tobytes(), GL.GL_STREAM_DRAW)
        u = self._u
        GL.glEnable(GL.GL_BLEND)
        GL.glBlendFunc(GL.GL_SRC_ALPHA, GL.GL_ONE)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glUniform4f(u["u_fog"], 0.0, 0.0, 0.0, self._haze[3] * 0.5)
        GL.glUniform4f(u["u_colour"], 0.0, 0.0, 0.0, 0.0)
        GL.glUniform1i(u["u_mode"], 1)
        GL.glUniform1f(u["u_cut"], 0.0)
        GL.glUniform1f(u["u_alpha"], 1.0)
        GL.glUniform3f(u["u_mow"], 0.0, 0.0, 1.0)
        GL.glBindTexture(GL.GL_TEXTURE_2D, self._glow)
        GL.glDrawElements(GL.GL_TRIANGLES, int(tri.size), GL.GL_UNSIGNED_INT, None)
        GL.glBlendFuncSeparate(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ZERO, GL.GL_ONE)
        GL.glUniform4f(u["u_fog"], *self._haze)

    def _draw_part(self, m, grass=False, layer=""):
        u = self._u
        tag = m.tag
        if layer == "PitchDetail.o":
            tag = "pitch:dtil" if "pitch:dtil" in self._tex else tag
        tex = self._tex.get(tag)
        mask = None
        if grass and self.stripes is not None and tex is not None:
            prefix, _, tile = tag.rpartition(":")
            mask = self._tex.get(prefix + (":" if prefix else "") + MASKS.get(tile, ""))
        if mask is not None:
            GL.glActiveTexture(GL.GL_TEXTURE1)
            GL.glBindTexture(GL.GL_TEXTURE_2D, mask)
            GL.glActiveTexture(GL.GL_TEXTURE0)
            GL.glUniform3f(u["u_mow"], 1.0, *self.stripes)
        else:
            GL.glUniform3f(u["u_mow"], 0.0, 0.0, 1.0)
        if tex is None:
            if layer in ("PitchDetail.o", "PitchShadow.o") or tag in PITCH_FLAGS:
                return                      # nothing to show without its picture
            GL.glUniform4f(u["u_colour"], *(self._ground if tag == "__grass__"
                                            else FLAT.get(tag, (0.55, 0.56, 0.58, 1.0))))
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._grey)
        else:
            GL.glUniform4f(u["u_colour"], 0.0, 0.0, 0.0, 0.0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glUniform1i(u["u_mode"], m.mode)
        GL.glUniform1f(u["u_alpha"], 1.0 if layer in ("logo", "soft", "core", "PitchLines.o") else 0.0)
        GL.glUniform1f(u["u_cut"], CORE_CUT if layer == "core"
                       else 0.02 if layer in ("logo", "soft", "PitchLines.o") else CUT)
        GL.glBindVertexArray(m.vao)
        GL.glDrawElements(GL.GL_TRIANGLES, m.count, GL.GL_UNSIGNED_INT, None)


class StadiumView(QWidget):
    """The stadium, drawn on demand. Drag to turn, right drag / Shift +
    drag to slide, wheel to zoom. `view_changed(name)` when a preset is
    left by moving the camera ("" then)."""

    view_changed = pyqtSignal(str)
    unavailable = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 220)
        self.renderer = StadiumRenderer()
        self._surface = _GLSurface(self.renderer, False)
        self._image = None
        self._drag = None
        self._message = ""
        self.view_name = "broadcast"
        # an object with press(x, z) -> bool, move(x, z), release(): a left
        # drag that starts on something of its own on the grass moves it
        self.ground_handler = None
        self._fine = QTimer(self)                   # full quality once the camera rests
        self._fine.setSingleShot(True)
        self._fine.timeout.connect(lambda: self._render(fast=False))

    # ── content ─────────────────────────────────────────────────────────
    def set_scene(self, scene):
        self.renderer.set_scene(scene)
        self._message = "" if scene is not None else self._message
        self._render()

    def set_textures(self, images):
        self.renderer.set_textures(images)
        self._render()

    def set_pitch(self, pitch):
        self.renderer.set_pitch(pitch)
        self._render()

    def set_stripes(self, stripes, fast=False):
        self.renderer.set_stripes(stripes)
        self._render(fast=fast)

    def set_logos(self, quads, images, fast=False):
        self.renderer.set_logos(quads, images)
        self._render(fast=fast)

    def set_environment(self, env):
        self.renderer.environment = env
        self._render()

    def set_line_style(self, style):
        """The pitch lines' style (backend/pitch_lines): "no_numbers" leaves
        the numbers out."""
        self.renderer.line_style = style or ""
        self._render()

    def set_message(self, text):
        """Shown instead of the stadium (no scene: the game isn't found...)."""
        self._message = text
        if text:
            self.renderer.set_scene(type("Empty", (), {"parts": [], "textures": {}})())
        self._render()

    # ── camera ──────────────────────────────────────────────────────────
    def set_view(self, name):
        if name not in VIEWS:
            return
        yaw, pitch, dist, target = VIEWS[name]
        r = self.renderer
        r.yaw, r.pitch, r.dist, r.target = yaw, pitch, dist, np.array(target, dtype=np.float32)
        r.fit_camera()
        self.view_name = name
        self._render()

    def zoom(self, factor):
        r = self.renderer
        r.dist = max(MIN_DIST, min(MAX_DIST, r.dist * factor))
        self._moved()

    def orbit(self, dyaw, dpitch):
        r = self.renderer
        r.yaw = (r.yaw + dyaw) % 360.0
        r.pitch = max(-5.0, min(89.0, r.pitch + dpitch))
        self._moved()

    def pan(self, dx, dy):
        r = self.renderer
        y = math.radians(r.yaw)
        right = np.array([math.cos(y), 0.0, -math.sin(y)], dtype=np.float32)
        forward = np.array([-math.sin(y), 0.0, -math.cos(y)], dtype=np.float32)
        scale = r.dist / 900.0
        r.target = r.target + (-dx * right + dy * forward) * scale
        r.target[0] = max(-6000.0, min(6000.0, r.target[0]))
        r.target[2] = max(-7000.0, min(7000.0, r.target[2]))
        self._moved()

    def _moved(self):
        if self.view_name:
            self.view_name = ""
            self.view_changed.emit("")
        self._render(fast=True)

    # ── rendering ───────────────────────────────────────────────────────
    def _target_size(self):
        ratio = self.devicePixelRatioF()
        return max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio))

    def _render(self, fast=False):
        if not self.isVisible():
            return
        self._surface.ss = 1.0 if fast else 2.0
        self._image = self._surface.render_image(*self._target_size())
        if self._surface.failed:
            self.unavailable.emit()
        if fast:
            self._fine.start(160)
        self.update()

    def render_now(self):
        """A full-quality frame right away (tests, screenshots)."""
        self._render()
        return self._image

    def showEvent(self, event):
        super().showEvent(event)
        self._render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render(fast=True)

    def paintEvent(self, event):
        p = QPainter(self)
        if self._image is not None:
            p.drawImage(self.rect(), self._image)
        else:
            p.fillRect(self.rect(), QColor(10, 14, 12))
        if self._message:
            p.fillRect(self.rect(), QColor(8, 12, 10, 200))
            p.setPen(QColor(200, 205, 200))
            f = QFont(self.font())
            f.setPointSize(12)
            p.setFont(f)
            p.drawText(self.rect().adjusted(20, 20, -20, -20), Qt.AlignCenter | Qt.TextWordWrap,
                       self._message)

    # ── mouse / keys ────────────────────────────────────────────────────
    def ground_at(self, pos):
        """(x, z) on the grass under widget point `pos`, or None."""
        if self.width() <= 0 or self.height() <= 0:
            return None
        return self.renderer.ground_at(pos.x() / self.width(), pos.y() / self.height(),
                                       self.width(), self.height())

    def mousePressEvent(self, event):
        self.setFocus()
        pan = event.button() in (Qt.RightButton, Qt.MiddleButton) or event.modifiers() & Qt.ShiftModifier
        if not pan and event.button() == Qt.LeftButton and self.ground_handler is not None:
            point = self.ground_at(event.pos())
            if point is not None and self.ground_handler.press(*point):
                self._drag = (event.pos(), "ground")
                self.setCursor(Qt.ClosedHandCursor)
                return
        self._drag = (event.pos(), "pan" if pan else "orbit")

    def mouseMoveEvent(self, event):
        if not self._drag:
            return
        last, mode = self._drag
        d = event.pos() - last
        self._drag = (event.pos(), mode)
        if mode == "ground":
            point = self.ground_at(event.pos())
            if point is not None:
                self.ground_handler.move(*point)
        elif mode == "orbit":
            self.orbit(-d.x() * 0.35, d.y() * 0.25)
        else:
            self.pan(d.x(), d.y())

    def mouseReleaseEvent(self, event):
        if self._drag and self._drag[1] == "ground" and self.ground_handler is not None:
            self.ground_handler.release()
            self.unsetCursor()
        self._drag = None

    def wheelEvent(self, event):
        steps = event.angleDelta().y() / 120.0
        self.zoom(0.88 ** steps)

    def keyPressEvent(self, event):
        k = event.key()
        moves = {Qt.Key_Left: (6, 0), Qt.Key_Right: (-6, 0), Qt.Key_Up: (0, 4), Qt.Key_Down: (0, -4)}
        if k in moves:
            self.orbit(*moves[k])
        elif k in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_PageUp):
            self.zoom(0.85)
        elif k in (Qt.Key_Minus, Qt.Key_PageDown):
            self.zoom(1 / 0.85)
        else:
            super().keyPressEvent(event)
            return
        event.accept()
