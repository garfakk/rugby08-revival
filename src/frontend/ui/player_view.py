"""OpenGL preview of a Rugby 08 player: body model + kit/skin/boot textures,
animated with the crude rig in player_anim.py.

`PlayerRenderer` owns the GL objects and knows nothing about Qt widgets, so
the same code serves the on-screen widget (`PlayerView`) and the offscreen
screenshot path (`render_frames`) used by tools/player_preview.py.
"""
import ctypes
import time

import numpy as np
from OpenGL import GL
from PyQt5.QtCore import QTimer, QSize, Qt, pyqtSignal
from PyQt5.QtGui import (
    QOffscreenSurface, QOpenGLContext, QOpenGLFramebufferObject,
    QOpenGLFramebufferObjectFormat, QSurfaceFormat, QPainter,
)
from PyQt5.QtWidgets import QWidget
from PyQt5.QtGui import QColor, QFont

from ui.player_anim import JogAnimation, PlayerRig

VERT_SRC = """
#version 330 core
layout(location=0) in vec3 in_pos;
layout(location=1) in vec3 in_nrm;
layout(location=2) in vec2 in_uv;
uniform mat4 u_mvp;
uniform mat4 u_model;
out vec3 v_nrm;
out vec2 v_uv;
void main() {
    gl_Position = u_mvp * vec4(in_pos, 1.0);
    v_nrm = mat3(u_model) * in_nrm;
    v_uv = in_uv;
}
"""

FRAG_SRC = """
#version 330 core
in vec3 v_nrm;
in vec2 v_uv;
uniform sampler2D u_tex;
uniform vec3 u_light;
out vec4 frag;
void main() {
    vec4 tex = texture(u_tex, v_uv);
    if (tex.a < 0.35) discard;                 // number decals / finger tape
    vec3 n = normalize(v_nrm);
    float lambert = abs(dot(n, normalize(u_light)));   // two-sided: the game's
    float rim = pow(1.0 - abs(n.z), 3.0) * 0.18;       // meshes are one-sided
    vec3 col = tex.rgb * (0.42 + 0.72 * lambert) + rim;
    frag = vec4(col, 1.0);
}
"""


# ── Matrix helpers (column-major, fed to GL with transpose=True) ───────────────

from shared.log import get_logger

log = get_logger(__name__)


def _perspective(fovy_deg, aspect, near, far):
    f = 1.0 / np.tan(np.deg2rad(fovy_deg) / 2.0)
    m = np.zeros((4, 4), dtype=np.float32)
    m[0, 0] = f / aspect
    m[1, 1] = f
    m[2, 2] = (far + near) / (near - far)
    m[2, 3] = (2 * far * near) / (near - far)
    m[3, 2] = -1.0
    return m


def _look_at(eye, target, up=(0.0, 1.0, 0.0)):
    eye, target, up = (np.asarray(v, dtype=np.float32) for v in (eye, target, up))
    f = target - eye
    f /= np.linalg.norm(f)
    s = np.cross(f, up)
    s /= np.linalg.norm(s)
    u = np.cross(s, f)
    m = np.eye(4, dtype=np.float32)
    m[0, :3], m[1, :3], m[2, :3] = s, u, -f
    m[:3, 3] = -m[:3, :3] @ eye
    return m


def _rot_y(deg):
    c, s = np.cos(np.deg2rad(deg)), np.sin(np.deg2rad(deg))
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[0, 2], m[2, 0], m[2, 2] = c, s, -s, c
    return m


# The game scales every bone of the one player mesh from the roster's height and
# weight (reverse-engineered: FUN_006d6900 / FUN_006d6960):
#   s = 1 - (16 - h) * 0.01                  h = height byte, inches over 60
#   k = 0.85 + (w - 50) * 0.5 / 150 + (24 - h) * 0.3 / 24     w = weight byte, lbs - 100
#   bone scale = (S, ((k - 1) * T + 1) * S, ((k - 1) * T + 1) * S)   T = 0.12 or 0.06
# The model here is one rigid mesh per part, not 51 bones, so it is approximated by
# one uniform scale s plus a horizontal girth factor, planted on the feet. The
# real 51-bone rig spreads T=0.12 across the spine/chest/shoulder/arm bones
# individually; collapsing all of them into one shoulder-to-wrist mesh applies
# the full 0.12 to the whole silhouette at once; on a short, heavy build (high
# k) that reads as an oversized shoulder next to the head's own, gentler 0.06,
# so it's knocked down here to keep that gap from standing out.
_GIRTH_T_BODY = 0.08
_GIRTH_T_HEAD = 0.06


def body_scale(height_cm, weight_kg):
    """(s, k) the game derives from a roster height (cm) and weight (kg), using
    the same conversions the roster writer applies; (1.0, 1.0) when either is
    missing or not a number."""
    try:
        h = int(float(height_cm) / 2.54 - 59.21259842519685)
        w = int(float(weight_kg) / 0.453 - 100)
    except (TypeError, ValueError):
        return 1.0, 1.0
    s = 1.0 - (16 - h) * 0.01
    k = 0.85 + (w - 50) * 0.5 / 150 + (24 - h) * 0.3 / 24
    return s, k


def _body_matrix(s, k, t, feet_y):
    g = (k - 1.0) * t + 1.0
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[1, 1], m[2, 2] = s * g, s, s * g
    m[1, 3] = feet_y * (1.0 - s)          # scale about the feet, so they stay on the ground
    return m


class _PartGL:
    __slots__ = ('vao', 'vbo', 'ebo', 'count', 'tex', 'part', 'weights')


class PlayerRenderer:
    """Uploads a PlayerModel to GL and draws it, animated, from any angle."""

    def __init__(self, model, animation=None, transparent=False):
        self.model = model
        self.rig = PlayerRig(model.parts)
        self.anim = animation or JogAnimation(self.rig)
        self.parts: list[_PartGL] = []
        self.program = None
        self.white = None
        self.yaw = 205.0            # start with the player facing the camera
        self.pan_y = 0.0            # vertical scroll: world-space offset of the framed centre, +up
        self.zoom = 1.0
        self.body = (1.0, 1.0)      # (s, k) from body_scale(); (1, 1) = the mesh as modelled
        self.animate = True
        self.transparent = transparent   # clear alpha 0 — no boxed panel behind the model
        self.yaw_target = None           # set by turn_to(); eased in step_turn()
        self._turn_rate = 0.16
        self._t0 = time.time()

    # ── Orientation ───────────────────────────────────────────────────────────

    def now(self) -> float:
        """The animation clock the current pose is being sampled at — what a
        blend needs as its start time."""
        return time.time() - self._t0

    def turn_to(self, yaw: float, rate: float = 0.16):
        """Ease round to `yaw` instead of snapping. The player may have been
        rotated by hand to any angle, so a walk-off can't just assign the
        heading it wants — that would flick the model round in one frame."""
        self.yaw_target = float(yaw)
        self._turn_rate = rate

    def step_turn(self):
        if self.yaw_target is None:
            return
        # Shortest way round, so turning from 350° to 10° goes forwards 20°
        # rather than backwards 340°.
        delta = (self.yaw_target - self.yaw + 180.0) % 360.0 - 180.0
        if abs(delta) < 0.5:
            self.yaw, self.yaw_target = self.yaw_target, None
            return
        self.yaw += delta * self._turn_rate

    # ── Setup ─────────────────────────────────────────────────────────────────

    def initialize(self):
        self.program = self._build_program()
        textures = {name: self._upload_texture(*tex)
                    for name, tex in self.model.textures.items()}
        self.white = self._upload_texture(1, 1, bytes([255, 255, 255, 255]))

        for part, weights in zip(self.model.parts, self.rig.weights):
            g = _PartGL()
            g.part, g.weights = part, weights
            g.tex = textures.get(part.shape, self.white)
            g.count = part.indices.size

            g.vao = GL.glGenVertexArrays(1)
            GL.glBindVertexArray(g.vao)
            g.vbo = GL.glGenBuffers(1)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, g.vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, self._interleave(part.positions, part.normals, part.uvs),
                            GL.GL_DYNAMIC_DRAW)
            stride = 8 * 4
            for loc, size, offset in ((0, 3, 0), (1, 3, 12), (2, 2, 24)):
                GL.glEnableVertexAttribArray(loc)
                GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, GL.GL_FALSE,
                                         stride, ctypes.c_void_p(offset))
            g.ebo = GL.glGenBuffers(1)
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, g.ebo)
            GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER,
                            part.indices.astype(np.uint32).tobytes(), GL.GL_STATIC_DRAW)
            GL.glBindVertexArray(0)
            self.parts.append(g)

        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)      # the model's winding is not uniform

    @staticmethod
    def _interleave(pos, nrm, uv):
        buf = np.empty((len(pos), 8), dtype=np.float32)
        buf[:, 0:3] = pos
        buf[:, 3:6] = nrm
        buf[:, 6:8] = uv
        return buf.tobytes()

    def _build_program(self):
        def compile_shader(src, kind):
            sid = GL.glCreateShader(kind)
            GL.glShaderSource(sid, src)
            GL.glCompileShader(sid)
            if not GL.glGetShaderiv(sid, GL.GL_COMPILE_STATUS):
                raise RuntimeError(GL.glGetShaderInfoLog(sid).decode())
            return sid

        vs = compile_shader(VERT_SRC, GL.GL_VERTEX_SHADER)
        fs = compile_shader(FRAG_SRC, GL.GL_FRAGMENT_SHADER)
        prog = GL.glCreateProgram()
        GL.glAttachShader(prog, vs)
        GL.glAttachShader(prog, fs)
        GL.glLinkProgram(prog)
        if not GL.glGetProgramiv(prog, GL.GL_LINK_STATUS):
            raise RuntimeError(GL.glGetProgramInfoLog(prog).decode())
        GL.glDeleteShader(vs)
        GL.glDeleteShader(fs)
        return prog

    @staticmethod
    def _upload_texture(w, h, rgba):
        tex = GL.glGenTextures(1)
        GL.glBindTexture(GL.GL_TEXTURE_2D, tex)
        GL.glTexImage2D(GL.GL_TEXTURE_2D, 0, GL.GL_RGBA, w, h, 0,
                        GL.GL_RGBA, GL.GL_UNSIGNED_BYTE, rgba)
        GL.glGenerateMipmap(GL.GL_TEXTURE_2D)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_S, GL.GL_REPEAT)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_WRAP_T, GL.GL_REPEAT)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MIN_FILTER, GL.GL_LINEAR_MIPMAP_LINEAR)
        GL.glTexParameteri(GL.GL_TEXTURE_2D, GL.GL_TEXTURE_MAG_FILTER, GL.GL_LINEAR)
        return tex

    # ── Drawing ───────────────────────────────────────────────────────────────

    def draw(self, width, height, t=None):
        t = (time.time() - self._t0) if t is None else t
        # Frame the whole model, not the rig's bounds — the rig measures the
        # body alone, so framing on it would crop the head.
        lo, hi = self.model.bounds
        # `pan_y` slides the framed centre up/down the body — toward the
        # head (+) or the feet (-) — without rotating anything, so it reads
        # as scrolling the view rather than orbiting the camera.
        centre = np.array([0.0, (lo[1] + hi[1]) * 0.5 + self.pan_y, 0.0], dtype=np.float32)
        size = float(hi[1] - lo[1])

        GL.glViewport(0, 0, width, height)
        if self.transparent:
            GL.glClearColor(0.0, 0.0, 0.0, 0.0)
        else:
            GL.glClearColor(0.055, 0.06, 0.08, 1.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glEnable(GL.GL_DEPTH_TEST)

        eye = centre + np.array([0.0, size * 0.06, size * 1.55 / self.zoom], dtype=np.float32)
        proj = _perspective(38.0, max(1e-3, width / max(1, height)), size * 0.05, size * 8.0)
        view = _look_at(eye, centre)
        rot = _rot_y(self.yaw)
        body_s, body_k = self.body
        feet_y = float(lo[1])

        GL.glUseProgram(self.program)
        loc_mvp = GL.glGetUniformLocation(self.program, 'u_mvp')
        loc_model = GL.glGetUniformLocation(self.program, 'u_model')
        GL.glUniform3f(GL.glGetUniformLocation(self.program, 'u_light'), 0.35, 0.75, 0.9)
        GL.glUniform1i(GL.glGetUniformLocation(self.program, 'u_tex'), 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)

        for g in self.parts:
            girth_t = _GIRTH_T_HEAD if getattr(g.part, 'is_head', False) else _GIRTH_T_BODY
            model_m = rot @ _body_matrix(body_s, body_k, girth_t, feet_y)
            GL.glUniformMatrix4fv(loc_mvp, 1, GL.GL_TRUE, proj @ view @ model_m)
            GL.glUniformMatrix4fv(loc_model, 1, GL.GL_TRUE, model_m)
            if self.animate:
                pos, nrm = self.anim.pose(g.part, g.weights, t)
            else:
                pos, nrm = g.part.positions, g.part.normals
            GL.glBindVertexArray(g.vao)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, g.vbo)
            GL.glBufferSubData(GL.GL_ARRAY_BUFFER, 0,
                               self._interleave(pos, nrm, g.part.uvs))
            GL.glBindTexture(GL.GL_TEXTURE_2D, g.tex)
            GL.glDrawElements(GL.GL_TRIANGLES, g.count, GL.GL_UNSIGNED_INT, None)
        GL.glBindVertexArray(0)


# Antialiasing/sharpness comes from supersampling in paintGL — rendering at
# SS_FACTOR times the widget's own pixel size, into an offscreen FBO, then
# downsampling with a filtered glBlitFramebuffer — rather than from native
# MSAA. The model is a few thousand triangles behind a one-tap shader, so
# the extra fragment work is negligible, and it sidesteps a real MSAA
# problem: the multisample-resolve step QOpenGLWidget performs internally
# does not reliably carry an alpha-0 clear through on every driver (the
# "transparent" kit stage can come out opaque black instead of showing the
# card behind it). A supersampled blit has no such resolve step — it is a
# plain filtered copy of an already single-sampled colour texture, so it
# stays correct with or without transparency and this is why both stages
# now share one code path instead of the transparent one dropping AA
# entirely.
SS_FACTOR = 2.0
# Half the vertical field of view (see the 38° fovy passed to _perspective
# in PlayerRenderer.draw) — needed to convert a drag distance in pixels to
# world units so the model tracks the cursor 1:1 regardless of zoom, and to
# work out how far `pan_y` is allowed to travel (see PlayerView._pan_limit).
_HALF_FOVY_TAN = np.tan(np.deg2rad(38.0 / 2.0))
# The "1.55" PlayerRenderer.draw uses to turn model height into camera
# distance — kept alongside it here so the pan-limit maths below tracks it
# instead of drifting out of sync with a copy of the same constant.
_EYE_DIST_FACTOR = 1.55
#: zoom == 1.0 is the default framing (the whole body fits on screen) and
#: also the closest to "zoomed out" the camera goes — see wheelEvent.
MIN_ZOOM, MAX_ZOOM = 1.0, 4.0


class _GLSurface:
    """The GL context + render targets behind a `PlayerView` / `BallView`: a
    plain `QOpenGLContext` on a `QOffscreenSurface`, rendering into private
    FBOs and handing back QImages. There is deliberately no QOpenGLWidget in
    here (an earlier version used a hidden one): its context is created
    through the widget stack (top-level window, shared context of a different
    profile) rather than the plain path `warm_up_gl()` vets, and on Windows
    that route can fail or come back blank on machines where the plain context
    works. Painting the grabbed QImage with QPainter also sidesteps the
    unreliable native compositing of an alpha GL widget (opaque black or a
    hole to the desktop on some compositors)."""

    def __init__(self, renderer, transparent):
        self.renderer = renderer
        self._transparent = transparent
        self._surface = None
        self._ctx = None
        self._ss_fbo = None
        self._out_fbo = None
        self.failed = False
        self.ss = SS_FACTOR

    def _fail(self, reason):
        global GL_ERROR
        self.failed = True
        GL_ERROR = GL_ERROR or reason
        log.warning(f"3D preview disabled: {reason}")

    def _create_context(self):
        fmt = QSurfaceFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(24)
        if self._transparent:
            fmt.setAlphaBufferSize(8)
        surface = QOffscreenSurface()
        surface.setFormat(fmt)
        surface.create()
        ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        if not ctx.create() or not ctx.makeCurrent(surface):
            got = f"{ctx.format().majorVersion()}.{ctx.format().minorVersion()}" if ctx.isValid() else "none"
            raise RuntimeError(f"could not create an OpenGL 3.3 core context (got {got})")
        self._surface, self._ctx = surface, ctx
        try:
            self.renderer.initialize()
        finally:
            ctx.doneCurrent()

    @staticmethod
    def _fbo(fbo, w, h):
        if fbo is not None and fbo.size() == QSize(w, h):
            return fbo
        fmt = QOpenGLFramebufferObjectFormat()
        fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
        return QOpenGLFramebufferObject(w, h, fmt)

    def render_image(self, w, h):
        """One frame at w x h pixels as a QImage (None if there is no GL).
        Rendered supersampled into a private FBO and filtered down into a
        second one of exactly w x h, so any size works from one frame to the
        next. A failure is logged once and disables this surface; the owning
        widget then shows its placeholder instead of raising every frame."""
        if self.failed:
            return None
        try:
            if self._ctx is None:
                self._create_context()
            if not self._ctx.makeCurrent(self._surface):
                raise RuntimeError("makeCurrent failed")
        except Exception as e:
            self._fail(f"{type(e).__name__}: {e}")
            return None
        try:
            limit = min(int(GL.glGetIntegerv(GL.GL_MAX_TEXTURE_SIZE)),
                        int(GL.glGetIntegerv(GL.GL_MAX_RENDERBUFFER_SIZE)))
            w, h = max(1, min(w, limit)), max(1, min(h, limit))
            ss = min(self.ss, limit / w, limit / h)
            sw, sh = max(1, int(w * ss)), max(1, int(h * ss))
            self._ss_fbo = self._fbo(self._ss_fbo, sw, sh)
            self._out_fbo = self._fbo(self._out_fbo, w, h)

            self._ss_fbo.bind()
            self.renderer.draw(sw, sh)
            self._ss_fbo.release()

            GL.glBindFramebuffer(GL.GL_READ_FRAMEBUFFER, self._ss_fbo.handle())
            GL.glBindFramebuffer(GL.GL_DRAW_FRAMEBUFFER, self._out_fbo.handle())
            GL.glBlitFramebuffer(0, 0, sw, sh, 0, 0, w, h, GL.GL_COLOR_BUFFER_BIT, GL.GL_LINEAR)
            GL.glBindFramebuffer(GL.GL_FRAMEBUFFER, 0)
            return self._out_fbo.toImage()
        except Exception as e:
            self._fail(f"render failed: {type(e).__name__}: {e}")
            return None
        finally:
            self._ctx.doneCurrent()


#: Idle-preview frame interval. Skinning the pose (python/numpy) and the
#: offscreen render + readback cost roughly the same again per frame, so this
#: is the main lever on what a VISIBLE preview costs. Lowering it does not help
#: a machine where one frame already takes longer than this to produce —
#: measured on a 2-core Haswell: ~25-30 ms per frame either way.
FRAME_MS = 33
#: Smoothed per-frame cost above which supersampling is switched off, and the
#: slowest the timer is ever stretched to (see PlayerView._adapt).
SLOW_FRAME_MS = 16.0
MAX_FRAME_MS = 100


class PlayerView(QWidget):
    """Spinning, jogging player. Horizontal drag spins the model, vertical
    drag scrolls the view up/down the body (head <-> feet), wheel zooms.

    A plain QWidget, not a QOpenGLWidget — see `_GLSurface` for why. This
    widget only ever paints a QImage grabbed from that hidden surface."""

    #: Emitted once, when the GL surface turns out to be unusable (no context,
    #: or a render error). Owners fall back to a flat picture.
    unavailable = pyqtSignal()

    def __init__(self, model, parent=None, spin=True, transparent=False):
        super().__init__(parent)
        if transparent:
            # Otherwise the app-wide QSS's blanket `QWidget { background-color }`
            # rule paints an opaque BG_BASE fill behind our own paintEvent —
            # same auto-fill trap as Card/TeamColumn (see broadcast.py's Card).
            self.setObjectName("playerView")
            self.setStyleSheet("QWidget#playerView { background: transparent; }")
        self.renderer = PlayerRenderer(model, transparent=transparent)
        self._surface = _GLSurface(self.renderer, transparent)
        self._image = None
        self._frames = 0
        self._cost_ms = None    # smoothed cost of one _frame(); see _frame()
        self._unavailable_sent = False
        self.spin = spin
        self._drag = None
        self._drag_axis = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)   # CoarseTimer's slack is
        # visible as jitter at this 33 ms interval, same fix as the loading ring.
        self._timer.timeout.connect(self._frame)
        # Deliberately NOT started here — showEvent() starts it. A view built
        # before it is ever displayed (the match-setup kit stages are built
        # with every other screen at start-up) never gets a hideEvent to pause
        # it, so starting the timer here left two 3D players being posed and
        # rendered 30x a second behind the menus: ~50% CPU while idle, and the
        # menu animations dropping a third of their frames.

    def pause(self):
        """Stop redrawing — call when the widget isn't visible. A hidden
        QOpenGLWidget still costs a GPU frame per tick otherwise."""
        self._timer.stop()

    def resume(self):
        if not self._timer.isActive():
            self._timer.start(FRAME_MS)

    def render_first_frame(self):
        """Render one frame now, hidden — creates the GL context and uploads the
        model ahead of the first time the view is shown."""
        if self._image is None:
            self._frame()

    def _frame(self):
        t0 = time.perf_counter()
        if self.spin:
            self.renderer.yaw += 0.6
        self.renderer.step_turn()
        ratio = self.devicePixelRatioF()
        self._image = self._surface.render_image(
            max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio)))
        if self._image is None and self._surface.failed and not self._unavailable_sent:
            self._unavailable_sent = True
            self._timer.stop()
            self.unavailable.emit()
        self.update()
        self._adapt((time.perf_counter() - t0) * 1000.0)

    def _adapt(self, cost_ms):
        """Keep a slow machine usable. Everything here runs on the GUI thread
        (skinning, render, readback), so a frame that takes long starves the
        rest of the UI — other animations, the loading screen, mouse drags.
        Track a smoothed frame cost; when it is high, first drop the
        supersampling (4x fewer pixels, the bulk of a software-GL frame),
        then stretch the timer so the GUI thread keeps most of its time free."""
        self._frames += 1
        if self._frames <= 3:       # context creation + model upload, not steady state
            return
        c = self._cost_ms
        self._cost_ms = cost_ms if c is None else c * 0.8 + cost_ms * 0.2
        if self._cost_ms > SLOW_FRAME_MS and self._surface.ss > 1.0:
            self._surface.ss = 1.0
            self._cost_ms = None
            log.info(f"3D preview: frame cost {cost_ms:.0f} ms, supersampling off")
            return
        if self._cost_ms is not None:
            interval = int(min(MAX_FRAME_MS, max(FRAME_MS, self._cost_ms * 2.5)))
            if interval != self._timer.interval() and self._timer.isActive():
                self._timer.setInterval(interval)

    def resizeEvent(self, event):
        # Redraw at the new size right away: the timer's next frame may be a
        # while off, and the old image would be stretched to the new rect meanwhile.
        super().resizeEvent(event)
        if self._timer.isActive():
            self._frame()

    def paintEvent(self, event):
        if self._image is not None:
            QPainter(self).drawImage(self.rect(), self._image)
        elif GL_AVAILABLE is False or self._surface.failed:
            # warm_up_gl() already found GL unusable (see its docstring):
            # say so instead of leaving the widget an unexplained blank box.
            p = QPainter(self)
            p.fillRect(self.rect(), QColor("#12140f"))
            p.setPen(QColor("#8a8f86"))
            p.setFont(QFont(self.font().family(), 9))
            p.drawText(self.rect(), Qt.AlignCenter | Qt.TextWordWrap,
                      "3D preview unavailable\n(no usable graphics driver)"
                      + (f"\n{GL_ERROR[:140]}" if GL_ERROR else ""))

    def _pan_limit(self):
        """How far `pan_y` may slide the framed centre off the model's own
        mid-height, in world units, at the renderer's current zoom.

        Chosen so that at the limit, the window's edge lands exactly where
        it sits in the *default* (zoom == 1) framing — i.e. the far end
        (head or feet) can be scrolled up to just inside the edge of the
        screen, the same amount of "just inside" the default view already
        leaves it, never dead centre and never all the way to the edge.
        Zero at zoom == 1 itself, since the whole body already fits on
        screen there and there is nothing to scroll to.
        """
        lo, hi = self.renderer.model.bounds
        model_size = float(hi[1] - lo[1])
        zoom = max(self.renderer.zoom, 1e-3)
        half_default_h = model_size * _EYE_DIST_FACTOR * _HALF_FOVY_TAN
        return half_default_h * (1.0 - 1.0 / zoom)

    def _reclamp_pan(self):
        limit = self._pan_limit()
        self.renderer.pan_y = float(np.clip(self.renderer.pan_y, -limit, limit))

    def mousePressEvent(self, event):
        self._drag = event.pos()
        self._drag_axis = None    # locked to 'yaw' or 'pan' once the drag is decisive
        self.spin = False

    def mouseMoveEvent(self, event):
        if self._drag is None:
            return
        dx, dy = event.x() - self._drag.x(), event.y() - self._drag.y()

        if self._drag_axis is None:
            # Below this many pixels either delta could just be hand
            # tremor, so hold off committing to an axis rather than
            # picking one from noise — the first decisive move (whichever
            # axis is larger) locks it for the rest of this drag, so one
            # gesture is only ever a rotate or only ever a scroll, never a
            # bit of both.
            if max(abs(dx), abs(dy)) < 3:
                return
            # At the default framing the whole body already fits on screen,
            # so there is nothing to scroll to — vertical drag only starts
            # doing anything once the user has zoomed in past that point.
            zoomed_in = self._pan_limit() > 1e-6
            self._drag_axis = 'yaw' if (not zoomed_in or abs(dx) >= abs(dy)) else 'pan'

        if self._drag_axis == 'yaw':
            self.renderer.yaw += dx * 0.5
        else:
            # Convert the drag distance to world units so the body tracks
            # the cursor 1:1 (accounting for zoom) instead of scrolling at
            # an arbitrary speed, then clamp to _pan_limit() so the far end
            # can't be scrolled past the edge it sits just inside of in the
            # default view.
            lo, hi = self.renderer.model.bounds
            model_size = float(hi[1] - lo[1])
            dist = model_size * _EYE_DIST_FACTOR / self.renderer.zoom
            world_per_px = (2.0 * dist * _HALF_FOVY_TAN) / max(1, self.height())
            self.renderer.pan_y += dy * world_per_px
            self._reclamp_pan()

        self._drag = event.pos()
        self.update()

    def mouseReleaseEvent(self, _event):
        self._drag = None
        self._drag_axis = None

    def wheelEvent(self, event):
        self.renderer.zoom *= 1.0 + event.angleDelta().y() / 1800.0
        # Never zoom out past the default framing — see MIN_ZOOM.
        self.renderer.zoom = float(np.clip(self.renderer.zoom, MIN_ZOOM, MAX_ZOOM))
        # The pan boundary tightens as zoom drops (see _pan_limit) — down to
        # exactly 0 at the default zoom — so any existing scroll needs
        # re-clamping every time zoom changes, not just when it hits the
        # bottom.
        self._reclamp_pan()
        self.update()

    def hideEvent(self, event):
        # QStackedLayout hides the widget it swaps away from, so this alone
        # is enough to stop a backgrounded 3D view from costing a GPU frame
        # every tick — no caller needs to remember to call pause().
        self.pause()
        super().hideEvent(event)

    def showEvent(self, event):
        self.resume()
        super().showEvent(event)


_warmed = False

# None = not yet determined (warm_up_gl() hasn't run), True/False after. Read
# by PlayerView.paintEvent() to show a placeholder instead of an empty box
# once GL is known not to work (see warm_up_gl()'s docstring for why it can
# fail: a VM/RDP session with no real GPU, stuck on a driver too old for the
# GL 3.3 core context the shaders need).
GL_AVAILABLE = None
# Why GL is unusable (short), shown under the placeholder so a screenshot of the
# empty preview is enough to diagnose it even with logging off.
GL_ERROR = ""


def warm_up_gl():
    """Pay the one-off GL costs — importing PyOpenGL, loading the driver,
    creating the first context, compiling the shader — at a moment of our
    choosing (start-up, behind the intro) instead of when the first 3D preview
    is shown, where they showed up as ~0.2 s of blank previews. Any later
    context (each PlayerView has its own) is much cheaper once the driver is
    warm.

    Also doubles as the capability check: a context can `create()`
    successfully yet still not be a real GL 3.3 core context — a VM or RDP
    session with no GPU passthrough commonly hands out a Direct3D/ANGLE
    context Qt reports as "valid" but that can't compile our #version 330
    shaders — so the only reliable test is compiling them for real. Sets
    GL_AVAILABLE and returns it; callers can use that to fall back to Qt's
    bundled software rasterizer (QT_OPENGL=software) and retry."""
    global _warmed, GL_AVAILABLE, GL_ERROR
    if _warmed:
        return GL_AVAILABLE
    _warmed = True
    ctx = None
    try:
        fmt = QSurfaceFormat.defaultFormat()
        fmt.setVersion(3, 3)
        fmt.setProfile(QSurfaceFormat.CoreProfile)
        fmt.setDepthBufferSize(24)
        surface = QOffscreenSurface()
        surface.setFormat(fmt)
        surface.create()
        ctx = QOpenGLContext()
        ctx.setFormat(fmt)
        if not ctx.create() or not ctx.makeCurrent(surface):
            raise RuntimeError("could not create an OpenGL context")
        try:
            prog = PlayerRenderer._build_program(None)
            fbo_fmt = QOpenGLFramebufferObjectFormat()
            fbo_fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
            fbo = QOpenGLFramebufferObject(64, 64, fbo_fmt)
            fbo.bind()
            GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
            fbo.release()
            GL.glDeleteProgram(prog)
        finally:
            ctx.doneCurrent()
        GL_AVAILABLE = True
    except Exception as e:
        GL_AVAILABLE = False
        GL_ERROR = f"{type(e).__name__}: {e}"
        got = f"{ctx.format().majorVersion()}.{ctx.format().minorVersion()}" if ctx is not None and ctx.isValid() else "none"
        log.warning(f"3D preview disabled: no usable OpenGL 3.3 core context (got version {got}): {e}. "
                   "Common cause: running in a VM/RDP session with no GPU passthrough; set the "
                   "environment variable QT_OPENGL=software to use Qt's bundled software renderer instead.")
    return GL_AVAILABLE


def render_frames(model, size=(480, 640), times=(0.0,), yaw=205.0, animation=None, transparent=False):
    """Render the model offscreen; returns a list of QImage. Used by the
    preview tool so the animation can be checked without a display.

    `animation` defaults to the jog; pass e.g. an `IdleAnimation` for another.
    """
    fmt = QSurfaceFormat()
    fmt.setVersion(3, 3)
    fmt.setProfile(QSurfaceFormat.CoreProfile)
    fmt.setDepthBufferSize(24)
    if transparent:
        fmt.setAlphaBufferSize(8)

    surface = QOffscreenSurface()
    surface.setFormat(fmt)
    surface.create()
    ctx = QOpenGLContext()
    ctx.setFormat(fmt)
    if not ctx.create() or not ctx.makeCurrent(surface):
        raise RuntimeError('could not create an OpenGL 3.3 context')

    fbo_fmt = QOpenGLFramebufferObjectFormat()
    fbo_fmt.setAttachment(QOpenGLFramebufferObject.CombinedDepthStencil)
    fbo = QOpenGLFramebufferObject(size[0], size[1], fbo_fmt)
    fbo.bind()

    renderer = PlayerRenderer(model, transparent=transparent)
    if animation is not None:
        renderer.anim = animation(renderer.rig) if callable(animation) else animation
    renderer.yaw = yaw
    renderer.initialize()
    images = []
    for t in times:
        renderer.draw(size[0], size[1], t)
        GL.glFinish()
        img = fbo.toImage()
        images.append(img.convertToFormat(img.Format_ARGB32) if transparent else img)
    fbo.release()
    ctx.doneCurrent()
    return images
