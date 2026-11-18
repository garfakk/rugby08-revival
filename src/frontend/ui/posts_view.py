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
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QPainter
from PyQt5.QtWidgets import QWidget

from shared.app_paths import assets_directory
from shared.log import get_logger
from ui.player_view import PlayerRenderer, _GLSurface, _perspective, _look_at, _rot_y

log = get_logger(__name__)

_MODEL = Path(assets_directory()) / "models" / "posts.npz"
TAGS = ("pada", "padb", "flag", "flgp", "post", "xbar")
# camera per view: (look-at centre, distance, eye height, yaw)
_FRAMES = {
    # the whole goal and the corner flag
    "posts": ((140.0, 270.0, 40.0), 1050.0, -60.0, 22.0),
    # close on one post pad and the corner flag (the posts' set shows on
    # the post rising out of the frame and the end of the crossbar)
    "pads": ((200.0, 108.0, 0.0), 430.0, 30.0, 18.0),
}
# "pads": the corner flag brought next to the post (it stands far off)
_FLAG_SHIFT = np.array([-75.0, 0.0, -105.0], dtype=np.float32)


def _keep_pads_corner(pos, tri):
    """Triangles of the right-hand post and the corner flag, below the
    crossbar: the left post and the flags on top go (the crossbar stays,
    running out of the frame)."""
    t = tri.reshape(-1, 3)
    v = pos[t]                                   # (n, 3 corners, xyz)
    keep = (v[:, :, 0] > 100).all(axis=1) & ~((v[:, :, 1] > 600).all(axis=1))
    return t[keep].ravel()


def _load_meshes(view="posts"):
    data = np.load(_MODEL)
    meshes = {}
    for tag in TAGS:
        if f"{tag}_pos" not in data.files:
            continue
        pos = data[f"{tag}_pos"]
        buf = np.concatenate([pos, data[f"{tag}_nrm"], data[f"{tag}_uv"]], axis=1)
        tri = data[f"{tag}_tri"].astype(np.uint32).ravel()
        if view == "pads":
            if tag in ("flag", "flgp"):
                buf[:, :3] += _FLAG_SHIFT
            if tag != "xbar":
                tri = _keep_pads_corner(pos, tri)
            if not tri.size:
                continue
        meshes[tag] = (buf.astype(np.float32), tri)
    return meshes


def _translate(v):
    m = np.eye(4, dtype=np.float32)
    m[:3, 3] = v
    return m


class PostsRenderer:
    """GL side (initialize()/draw(w, h), the contract _GLSurface drives)."""

    def __init__(self, view="posts"):
        self.view = view
        centre, self._distance, self._eye_y, self.yaw = _FRAMES[view]
        self._centre = np.array(centre, dtype=np.float32)
        self.transparent = True
        self._pending = None            # {tag: PIL image} waiting for the GL context
        self._tex = {}
        self._program = None
        self._gl = {}

    def set_textures(self, images):
        self._pending = dict(images)

    def initialize(self):
        self._program = PlayerRenderer._build_program(self)
        for tag, (buf, tri) in _load_meshes(self.view).items():
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
        eye = np.array([0.0, self._eye_y, self._distance], dtype=np.float32)
        proj = _perspective(32.0, max(1e-3, width / max(1, height)), 20.0, 8000.0)
        model = _rot_y(self.yaw) @ _translate(-self._centre)
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
    """The goal, seen from a fixed three-quarter angle (it does not move);
    drawn again only when the textures or the size change. `view` "pads":
    close on one post pad and the corner flag instead of the whole goal."""

    def __init__(self, parent=None, view="posts"):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TranslucentBackground, True)
        self.renderer = PostsRenderer(view)
        self._surface = _GLSurface(self.renderer, True)
        self._image = None

    def show_images(self, images):
        """Preview {tag: PIL image} (backend stadium_dressing.preview_images)."""
        self.renderer.set_textures(images)
        self._render()

    def _target_size(self):
        ratio = self.devicePixelRatioF()
        return max(1, int(self.width() * ratio)), max(1, int(self.height() * ratio))

    def _render(self):
        if self.isVisible():
            self._image = self._surface.render_image(*self._target_size())
            self.update()

    def showEvent(self, event):
        super().showEvent(event)
        self._render()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._render()

    def paintEvent(self, event):
        if self._image is None or (self._image.width(), self._image.height()) != self._target_size():
            self._image = self._surface.render_image(*self._target_size())
        if self._image is not None:
            QPainter(self).drawImage(self.rect(), self._image)
