"""OpenGL preview of a Rugby 08 ball: the game's own ball mesh (converted to
assets/models/ball.npz by tools/extract_ball_model.py), spinning, wearing the
ball's texture frame.

Renders through the same offscreen path as the player preview (see
ui/player_view.py::_GLSurface), so it composes correctly over the popup.
"""
import ctypes
from pathlib import Path

import numpy as np
from OpenGL import GL
from PIL import Image
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QWidget

from shared.app_paths import assets_directory
from ui.player_view import (
    PlayerRenderer, _GLSurface, _perspective, _look_at, _rot_y, FRAME_MS,
)

_MODEL = Path(assets_directory()) / "models" / "ball.npz"
_TILT_DEG = 62.0
# The stock model is two meshes, "bala" and "balb": the two halves of the ball,
# each wearing one texture frame (ball_1 / ball_2 = the .fsh entries bala / balb).
_MESHES = ("bala", "balb")


from shared.log import get_logger

log = get_logger(__name__)


def _rot_x(deg):
    c, s = np.cos(np.deg2rad(deg)), np.sin(np.deg2rad(deg))
    m = np.eye(4, dtype=np.float32)
    m[1, 1], m[1, 2], m[2, 1], m[2, 2] = c, -s, s, c
    return m


def _rot_z(deg):
    c, s = np.cos(np.deg2rad(deg)), np.sin(np.deg2rad(deg))
    m = np.eye(4, dtype=np.float32)
    m[0, 0], m[0, 1], m[1, 0], m[1, 1] = c, -s, s, c
    return m


def _load_meshes():
    """{name: (interleaved pos/nrm/uv float32 (N, 8), uint32 triangle indices)} from
    the converted stock model (tools/extract_ball_model.py)."""
    data = np.load(_MODEL)
    meshes = {}
    for name in _MESHES:
        buf = np.concatenate([data[f"{name}_pos"], data[f"{name}_nrm"], data[f"{name}_uv"]], axis=1)
        meshes[name] = (buf.astype(np.float32), data[f"{name}_tri"].astype(np.uint32).ravel())
    return meshes


class BallRenderer:
    """GL side, no Qt widgets — same initialize()/draw(w, h) contract as
    PlayerRenderer, which is what _GLSurface drives."""

    def __init__(self):
        self.yaw = 20.0
        self.transparent = True
        self._pending = None            # (frame images) waiting for the GL context
        self._tex = {}
        self._program = None
        self._gl = {}                   # mesh name -> (vao, count)

    def set_frames(self, frames):
        """PIL images, one per mesh in _MESHES (missing = plain). Uploaded at the next draw."""
        self._pending = list(frames)

    def initialize(self):
        self._program = PlayerRenderer._build_program(self)
        for name, (buf, tri) in _load_meshes().items():
            vao = GL.glGenVertexArrays(1)
            GL.glBindVertexArray(vao)
            vbo = GL.glGenBuffers(1)
            GL.glBindBuffer(GL.GL_ARRAY_BUFFER, vbo)
            GL.glBufferData(GL.GL_ARRAY_BUFFER, buf.tobytes(), GL.GL_STATIC_DRAW)
            for loc, size, offset in ((0, 3, 0), (1, 3, 12), (2, 2, 24)):
                GL.glEnableVertexAttribArray(loc)
                GL.glVertexAttribPointer(loc, size, GL.GL_FLOAT, GL.GL_FALSE, 32, ctypes.c_void_p(offset))
            ebo = GL.glGenBuffers(1)
            GL.glBindBuffer(GL.GL_ELEMENT_ARRAY_BUFFER, ebo)
            GL.glBufferData(GL.GL_ELEMENT_ARRAY_BUFFER, tri.tobytes(), GL.GL_STATIC_DRAW)
            GL.glBindVertexArray(0)
            self._gl[name] = (vao, tri.size)
        self._white = PlayerRenderer._upload_texture(1, 1, bytes([235, 235, 235, 255]))
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)

    def _upload_pending(self):
        if self._pending is None:
            return
        frames, self._pending = self._pending, None
        for tex in self._tex.values():
            GL.glDeleteTextures([tex])
        self._tex = {}
        for name, img in zip(_MESHES, frames):
            if img is not None:
                rgba = img.convert("RGBA").resize((256, 128))
                self._tex[name] = PlayerRenderer._upload_texture(256, 128, rgba.tobytes())

    def draw(self, width, height, t=None):
        self._upload_pending()
        GL.glViewport(0, 0, width, height)
        GL.glClearColor(0.0, 0.0, 0.0, 0.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glEnable(GL.GL_DEPTH_TEST)

        # The model is ~16 units long (Y axis): frame it with room to tumble.
        eye = np.array([0.0, 0.0, 26.0], dtype=np.float32)
        proj = _perspective(34.0, max(1e-3, width / max(1, height)), 1.0, 200.0)
        # Long axis tipped over towards horizontal, then spun around the vertical.
        model = _rot_x(-14.0) @ _rot_y(self.yaw) @ _rot_z(_TILT_DEG)
        mvp = proj @ _look_at(eye, (0.0, 0.0, 0.0)) @ model

        GL.glUseProgram(self._program)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._program, 'u_mvp'), 1, GL.GL_TRUE, mvp)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._program, 'u_model'), 1, GL.GL_TRUE, model)
        GL.glUniform3f(GL.glGetUniformLocation(self._program, 'u_light'), 0.35, 0.75, 0.9)
        GL.glUniform1i(GL.glGetUniformLocation(self._program, 'u_tex'), 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        for name in _MESHES:
            vao, count = self._gl[name]
            GL.glBindVertexArray(vao)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex.get(name, self._white))
            GL.glDrawElements(GL.GL_TRIANGLES, count, GL.GL_UNSIGNED_INT, None)
        GL.glBindVertexArray(0)


class BallView(QWidget):
    """The spinning ball. Timer runs only while visible; drag to spin it by hand."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.renderer = BallRenderer()
        self._surface = _GLSurface(self.renderer, True)
        self._image = None
        self._drag_x = None
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)   # see PlayerView._timer
        self._timer.timeout.connect(self._frame)

    def show_paths(self, paths):
        """Preview the ball whose frame images are `paths` (0-2 files)."""
        imgs = []
        for p in list(paths)[:len(_MESHES)]:
            try:
                imgs.append(Image.open(p))
            except Exception as e:
                log.warning(f"Ball preview: cannot read {p}: {e}")
        self.renderer.set_frames(imgs)
        if self.isVisible():
            self._frame()

    def _frame(self):
        if self._drag_x is None:
            self.renderer.yaw = (self.renderer.yaw + 1.1) % 360.0
        ratio = self.devicePixelRatioF()
        self._image = self._surface.render_image(
            max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio)))
        self.update()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._timer.isActive():
            self._timer.start(FRAME_MS)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self._timer.isActive():
            self._frame()

    def paintEvent(self, event):
        if self._image is not None:
            QPainter(self).drawImage(self.rect(), self._image)

    def mousePressEvent(self, event):
        self._drag_x = event.x()

    def mouseMoveEvent(self, event):
        if self._drag_x is not None:
            self.renderer.yaw = (self.renderer.yaw + (event.x() - self._drag_x) * 0.8) % 360.0
            self._drag_x = event.x()
            self._frame()

    def mouseReleaseEvent(self, event):
        self._drag_x = None
