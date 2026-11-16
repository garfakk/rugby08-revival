"""OpenGL preview of the stadium dressing: one goal (posts, crossbar, post
pads) and a corner flag, cut from a stock stadium (assets/models/posts.npz,
packaging/gen_posts_model.py), wearing the pads and posts sets picked.

Renders through the same offscreen path as the ball and player previews
(ui/player_view.py::_GLSurface).
"""
import ctypes
from pathlib import Path

import numpy as np
from OpenGL import GL
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QWidget

from shared.app_paths import assets_directory
from shared.log import get_logger
from ui.player_view import PlayerRenderer, _GLSurface, _perspective, _look_at, _rot_y, FRAME_MS

log = get_logger(__name__)

_MODEL = Path(assets_directory()) / "models" / "posts.npz"
TAGS = ("pada", "padb", "flag", "flgp", "post", "xbar")
_CENTRE = np.array([140.0, 270.0, 40.0], dtype=np.float32)
_DISTANCE = 1050.0


def _load_meshes():
    data = np.load(_MODEL)
    meshes = {}
    for tag in TAGS:
        if f"{tag}_pos" not in data.files:
            continue
        buf = np.concatenate([data[f"{tag}_pos"], data[f"{tag}_nrm"], data[f"{tag}_uv"]], axis=1)
        meshes[tag] = (buf.astype(np.float32), data[f"{tag}_tri"].astype(np.uint32).ravel())
    return meshes


def _translate(v):
    m = np.eye(4, dtype=np.float32)
    m[:3, 3] = v
    return m


class PostsRenderer:
    """GL side (initialize()/draw(w, h), the contract _GLSurface drives)."""

    def __init__(self):
        self.yaw = 0.0
        self.transparent = True
        self._pending = None            # {tag: PIL image} waiting for the GL context
        self._tex = {}
        self._program = None
        self._gl = {}

    def set_textures(self, images):
        self._pending = dict(images)

    def initialize(self):
        self._program = PlayerRenderer._build_program(self)
        for tag, (buf, tri) in _load_meshes().items():
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
            self._gl[tag] = (vao, tri.size)
        self._white = PlayerRenderer._upload_texture(1, 1, bytes([235, 235, 235, 255]))
        GL.glEnable(GL.GL_DEPTH_TEST)
        GL.glDisable(GL.GL_CULL_FACE)

    def _upload_pending(self):
        if self._pending is None:
            return
        images, self._pending = self._pending, None
        for tex in self._tex.values():
            GL.glDeleteTextures([tex])
        self._tex = {}
        for tag, img in images.items():
            if img is None:
                continue
            rgba = img.convert("RGBA")
            self._tex[tag] = PlayerRenderer._upload_texture(rgba.width, rgba.height, rgba.tobytes())

    def draw(self, width, height, t=None):
        self._upload_pending()
        GL.glViewport(0, 0, width, height)
        GL.glClearColor(0.0, 0.0, 0.0, 0.0)
        GL.glClear(GL.GL_COLOR_BUFFER_BIT | GL.GL_DEPTH_BUFFER_BIT)
        GL.glEnable(GL.GL_DEPTH_TEST)
        eye = np.array([0.0, -60.0, _DISTANCE], dtype=np.float32)
        proj = _perspective(32.0, max(1e-3, width / max(1, height)), 20.0, 8000.0)
        model = _rot_y(self.yaw) @ _translate(-_CENTRE)
        mvp = proj @ _look_at(eye, (0.0, 0.0, 0.0)) @ model
        GL.glUseProgram(self._program)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._program, 'u_mvp'), 1, GL.GL_TRUE, mvp)
        GL.glUniformMatrix4fv(GL.glGetUniformLocation(self._program, 'u_model'), 1, GL.GL_TRUE, model)
        GL.glUniform3f(GL.glGetUniformLocation(self._program, 'u_light'), 0.35, 0.75, 0.9)
        GL.glUniform1i(GL.glGetUniformLocation(self._program, 'u_tex'), 0)
        GL.glActiveTexture(GL.GL_TEXTURE0)
        for tag, (vao, count) in self._gl.items():
            GL.glBindVertexArray(vao)
            GL.glBindTexture(GL.GL_TEXTURE_2D, self._tex.get(tag, self._white))
            GL.glDrawElements(GL.GL_TRIANGLES, count, GL.GL_UNSIGNED_INT, None)
        GL.glBindVertexArray(0)


class PostsView(QWidget):
    """The goal, swaying slowly; drag to turn it."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.renderer = PostsRenderer()
        self._surface = _GLSurface(self.renderer, True)
        self._image = None
        self._drag_x = None
        self._phase = 0.0
        self._timer = QTimer(self)
        self._timer.setTimerType(Qt.PreciseTimer)
        self._timer.timeout.connect(self._frame)

    def show_images(self, images):
        """Preview {tag: PIL image} (backend stadium_dressing.preview_images)."""
        self.renderer.set_textures(images)
        if self.isVisible():
            self._frame()

    def _target_size(self):
        ratio = self.devicePixelRatioF()
        return max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio))

    def _frame(self):
        if self._drag_x is None:
            self._phase += 0.02
            self.renderer.yaw = 32.0 * np.sin(self._phase)
        self._image = self._surface.render_image(*self._target_size())
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
        if self._image is not None and (self._image.width(), self._image.height()) != self._target_size():
            self._image = self._surface.render_image(*self._target_size())
        if self._image is not None:
            QPainter(self).drawImage(self.rect(), self._image)

    def mousePressEvent(self, event):
        self._drag_x = event.x()

    def mouseMoveEvent(self, event):
        if self._drag_x is not None:
            self.renderer.yaw += (event.x() - self._drag_x) * 0.6
            self._drag_x = event.x()
            self._frame()

    def mouseReleaseEvent(self, event):
        self._drag_x = None
