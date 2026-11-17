"""
ui/stadium_view.py — a whole stadium in 3D (the stadium editor's preview)
==========================================================================
The scene pack's own models and textures (backend/stadium_scene.py) with
the dressing picked on top: pads, flags, posts and ad boards. Drawn through
the same offscreen GL path as the other previews (ui/player_view._GLSurface)
and only when something changes: the camera, the textures, the size.

Camera: an orbit around a target. Drag turns it, right / middle drag (or
Shift + drag) slides it, the wheel zooms; `set_view(name)` jumps to one of
VIEWS. Environment sets the light and the sky (day, overcast, night, cold).
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
out vec2 v_uv;
out vec4 v_col;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_uv = in_uv;
    v_col = in_col;
}
"""

# The game's own lighting is baked into the vertex colours: a "Texture2x"
# material is texture * colour * 2 (a grey of 0x80 leaves the texture as it
# is), "Texture" texture * colour, "Gouraud" the colour * 2.
FRAG = """
#version 330 core
in vec2 v_uv;
in vec4 v_col;
uniform sampler2D u_tex;
uniform sampler2D u_mask;   // the pitch's mowing mask
uniform vec3 u_mow;         // x: 1 = mow the grass, y: stripe strength, z: grass gain
uniform vec4 u_colour;      // a = 0: use the texture, else this flat colour
uniform int u_mode;         // 0: texture * colour * 2, 1: texture * colour, 2: colour * 2
uniform float u_cut;        // alpha below this is dropped
uniform float u_alpha;      // 1: the picture's alpha is kept (blended passes)
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
    frag = vec4(rgb, u_alpha > 0.5 ? c.a : 1.0);
}
"""

MASK_CHANNEL = "r"          # the mowing mask's band channel
FRAG = FRAG.replace("MASKCH", MASK_CHANNEL)

# environment -> the sky colour under the dome (the scene packs hold the rest)
SKY = {"day": (0.52, 0.70, 0.90), "overcast": (0.62, 0.66, 0.70), "night": (0.02, 0.03, 0.07),
       "cold": (0.74, 0.79, 0.86)}

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
# untextured parts drawn anyway (the dressing gets its textures from the sets)
FLAT_KEEP = {"pada", "padb", "flag", "flgp", "post", "xbar", "ads0", "ads1", "ads2", "ads3",
             "ads4", "ads5", "ads6", "ads7", "ads8"} | TEAM_TAGS
MIN_DIST, MAX_DIST = 400.0, 16000.0
_UNSET = object()
MODES = {"Texture2x": 0, "ScrollTexture2x": 0, "MowPattern": 0, "Texture": 1, "Gouraud": 2}
# the pitch layers drawn over the grass, with the depth nudge that keeps them
# above it: tag -> (blend function, polygon-offset units)
DECALS = {"PitchDetail.o": ((GL.GL_DST_COLOR, GL.GL_SRC_COLOR), -2.0),    # detail tile: dst * src * 2
          "PitchShadow.o": ((GL.GL_ZERO, GL.GL_SRC_COLOR), -4.0),          # shadow: darkens
          "PitchLines.o": (None, -6.0)}


class _Mesh:
    """One uploaded mesh and how it is drawn."""
    __slots__ = ("vao", "count", "tag", "bufs", "own", "model", "mode", "soft")

    def __init__(self, vao, count, tag, bufs, own=False, model="", mode=0, soft=False):
        self.vao, self.count, self.tag, self.bufs = vao, count, tag, bufs
        self.own, self.model, self.mode, self.soft = own, model, mode, soft


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

    # ── data in ─────────────────────────────────────────────────────────
    def set_scene(self, scene):
        self._scene_pending = scene

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

    @staticmethod
    def _upload(w, h, rgba):
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0, GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, rgba)
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        for k, v in ((GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT), (GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT),
                     (GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR),
                     (GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)):
            GL.glTexParameteri(GL.GL_TEXTURE_2D, k, v)
        return tex

    def _upload_image(self, tag, img):
        old = self._tex.pop(tag, None)
        self._soft.discard(tag)
        if old:
            GL.glDeleteTextures([old])
        if img is not None:
            rgba = img.convert("RGBA")
            alpha = np.asarray(rgba.getchannel("A"))
            if ((alpha > 8) & (alpha < 247)).mean() > 0.01:
                self._soft.add(tag)           # leaves, fences, nets: blended, not cut out
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
                soft = mode == 2 or part.tag in self._soft
                self._parts.append(self._make_part(part.buf, part.tri, part.tag, own, part.model, mode, soft))
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
        GL.glClearColor(*SKY.get(self.environment, SKY["day"]), 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        if not self._parts:
            return
        GL.glDisable(GL.GL_CULL_FACE)
        proj, view = self.matrices(width, height)
        prog = self._program
        GL.glUseProgram(prog)
        loc = lambda name: GL.glGetUniformLocation(prog, name)
        self._u = {n: loc(n) for n in ("u_mvp", "u_colour", "u_mode", "u_cut", "u_alpha", "u_mow")}
        GL.glUniform1i(loc("u_tex"), 0)
        GL.glUniform1i(loc("u_mask"), 1)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        GL.glBlendFuncSeparate(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ZERO, GL.GL_ONE)
        mvp = proj @ view
        own = not self._pitch_parts            # the scene's own grass unless a pitch is laid
        sky = [m for m in self._parts if m.model == "sky.o"]
        decals = {k: [m for m in self._parts if m.model == k] for k in DECALS}
        rest = [m for m in self._parts if m.model != "sky.o" and m.model not in DECALS
                and not (m.own and not own)]
        # sky: a dome around the eye, behind everything
        if sky:
            dome = view.copy()
            dome[:3, 3] = 0.0
            GL.glDisable(GL.GL_DEPTH_TEST)
            GL.glUniformMatrix4fv(self._u["u_mvp"], 1, GL.GL_TRUE, proj @ dome)
            for m in sky:
                self._draw_part(m)
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glUniformMatrix4fv(self._u["u_mvp"], 1, GL.GL_TRUE, mvp)
        # the solid parts: the laid pitch, the scene
        for m in self._pitch_parts:
            self._draw_part(m, grass=True)
        for m in rest:
            if not m.soft:
                self._draw_part(m, grass=m.own)
        # the layers over the grass
        GL.glEnable(GL.GL_BLEND)
        GL.glDepthMask(GL.GL_FALSE)
        GL.glEnable(GL.GL_POLYGON_OFFSET_FILL)
        for key, (func, units) in DECALS.items():
            GL.glPolygonOffset(0.0, units)
            if func:
                GL.glBlendFunc(*func)
            else:
                GL.glBlendFuncSeparate(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ZERO, GL.GL_ONE)
            for m in decals[key]:
                self._draw_part(m, layer=key)
        GL.glDisable(GL.GL_POLYGON_OFFSET_FILL)
        GL.glBlendFuncSeparate(GL.GL_SRC_ALPHA, GL.GL_ONE_MINUS_SRC_ALPHA, GL.GL_ZERO, GL.GL_ONE)
        for m in self._logo_parts:
            if m.tag in self._tex:
                self._draw_part(m, layer="logo")
        # the see-through parts (leaves, fences, nets)
        for m in rest:
            if m.soft:
                self._draw_part(m, layer="soft")
        GL.glDepthMask(GL.GL_TRUE)
        GL.glDisable(GL.GL_BLEND)
        GL.glBindVertexArray(0)

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
            if layer in ("PitchDetail.o", "PitchShadow.o"):
                return                      # a layer without its picture has nothing to show
            GL.glUniform4f(u["u_colour"], *(self._ground if tag == "__grass__"
                                            else FLAT.get(tag, (0.55, 0.56, 0.58, 1.0))))
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._grey)
        else:
            GL.glUniform4f(u["u_colour"], 0.0, 0.0, 0.0, 0.0)
            GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glUniform1i(u["u_mode"], m.mode)
        GL.glUniform1f(u["u_alpha"], 1.0 if layer in ("logo", "soft", "PitchLines.o") else 0.0)
        GL.glUniform1f(u["u_cut"], 0.02 if layer in ("logo", "soft", "PitchLines.o") else 0.35)
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
