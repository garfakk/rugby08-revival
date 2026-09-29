"""
ui/player_stage.py — KitStage: the match-setup kit preview, in 3D when it can be
====================================================================================
Per the redesign plan's confirmed decision ("3D player model: Team-selection
only, replacing the kit image; settings toggle to revert"). The kit texture
loads from either a game-extracted .big/.fsh archive OR a plain image file
(PNG etc — the far more common case in the shipped team data; see
shared/omodel/player_model.py::_texture_from_path), so a per-kit fallback to
the flat preview still exists for whatever's genuinely unreadable (a missing
file, a corrupt one), independent of the user's own toggle.

KitStage exposes the same two calls TeamColumn already made on the flat
TransparentKitStage (`set_pixmap`, `set_placeholder`), plus `update_kit()`
which additionally takes the kit's own source path and decides — toggle on,
loadable — whether to show the 3D view or fall back.
"""
import os
import random
from pathlib import Path

from PyQt5.QtWidgets import QWidget, QStackedLayout

from shared.config import config
from shared.user_prefs import user_prefs
from ui.widgets import KitPreviewBox
from ui.broadcast import display_label
from ui.theme import FG_MUTED, BG_PANEL, BORDER
from PyQt5.QtGui import QFont, QPainter, QPixmap

# The generic body/skin/boots/head the 3D preview always uses — shared
# across every team, since only the kit is team-specific. Extracted on first
# use (backend.mod_utils.player_preview_assets), see tools/player_preview.py.
_ASSETS_TMP = Path(config.temp_directory) / "player_assets"
_assets = None       # None = not looked up yet, {} = unavailable, else the paths


def generic_assets():
    global _assets
    if _assets is None:
        from backend.mod_utils import player_preview_assets
        try:
            _assets = player_preview_assets(str(_ASSETS_TMP)) or {}
        except Exception as e:
            log.warning(f"3D preview assets: {e}")
            _assets = {}
    return _assets


_KIT_EXTS = (".big", ".fsh", ".png", ".jpg", ".jpeg", ".bmp", ".webp", ".gif", ".tga")


from shared.log import get_logger

log = get_logger(__name__)


def _usable(path) -> bool:
    return bool(path) and os.path.isfile(path) and os.path.splitext(path)[1].lower() in _KIT_EXTS


def _stamp(path):
    """(path, mtime, size) — a file's identity for "is this the same model"."""
    if not path:
        return path
    try:
        st = os.stat(path)
        return (path, st.st_mtime_ns, st.st_size)
    except OSError:
        return (path, None, None)


def _gl_unusable() -> bool:
    """True when 3D must not be used: switched off in Settings, or the app has
    established that no OpenGL 3.3 context can be created (see
    ui.player_view.warm_up_gl)."""
    from shared.user_prefs import user_prefs
    if not user_prefs.preview_3d:
        return True
    from ui import player_view
    return player_view.GL_AVAILABLE is False


def _try_load_model(kit_path: str, numbers_path: str = None, model3d_cfg: dict = None,
                    head_path: str = None, boots_path: str = None, skin_entry: str = None,
                    skin_path: str = None, finger_tape: str = None, boots_index: int = None,
                    wrist_tape: str = None, thigh_tape: str = None, socks: str = None):
    """None if `kit_path` can't be used as a 3D kit texture — missing,
    malformed, or an extension neither an image nor an FSH/BIG. Never
    raises: this is a capability probe, not a required load. `numbers_path`
    is the kit's own back-panel texture (the team JSON's backKitFile,
    "jbck" shape) — without it that panel falls back to plain white, which
    reads as a missing back of the shirt. `model3d_cfg` is the kit's own
    `model3d` block ({"fit": ..., "collar": ...}) — see
    shared/omodel/player_model.py::variants_from_kit_config for the
    defaults used when it's absent or only partly filled in. `finger_tape`
    is the player's own stat ("none"/"left"/"right"/"both") — the only tape
    stat with real 3D geometry, so it rides along with the kit variants.
    `boots_index` (0-9) picks which stock style out of boots.fsh's 10
    same-named entries — ignored when `boots_path` is a custom image.
    `wrist_tape`, `thigh_tape` (same values as finger_tape) and `socks`
    ("up"/"down") are the other player stats with geometry on the model; None
    keeps the kit-preview defaults."""
    assets = generic_assets()
    if not assets or not _usable(kit_path):
        return None
    try:
        from shared.omodel import PlayerAssets, load_player, variants_from_kit_config
        # A player's own head (.big holding model.o + textures.fsh) replaces
        # the generic one; boots may be a custom image instead of boots.fsh,
        # and the skin a composited image (ui/skin_preview) instead of skin.fsh.
        custom_head = head_path if head_path and os.path.isfile(head_path) else assets.get("head")
        extra = {"skin_entry": skin_entry} if skin_entry else {}
        return load_player(PlayerAssets(
            model_o=assets["body"], kit=kit_path,
            skin=skin_path if _usable(skin_path) else assets["skin"],
            boots=boots_path if _usable(boots_path) else assets["boots"],
            boots_index=boots_index,
            numbers=numbers_path if _usable(numbers_path) else None,
            head=custom_head,
            **extra,
        ), variants=variants_from_kit_config(model3d_cfg, finger_tape, wrist_tape, thigh_tape, socks))
    except Exception as e:
        log.warning(f"3D kit preview unavailable for {kit_path}: {e}")
        return None


class _FrozenImage(QWidget):
    """A finished render, scaled to whatever size the widget is.

    Held as a QPixmap (converted once, in the native premultiplied format) so
    the per-frame paint during a geometry animation is a plain blit, not a
    format conversion plus a software resample of a 2K image. Bilinear
    filtering only when shrinking well below the source: that is where
    aliasing shows, and the destination is small there so it is cheap. Near
    1:1 a plain blit looks the same and costs far less."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("frozenImage")
        self.setStyleSheet("QWidget#frozenImage { background: transparent; }")
        self._pixmap = None

    def set_image(self, image):
        self._pixmap = QPixmap.fromImage(image) if image is not None else None
        self.update()

    def paintEvent(self, _event):
        pm = self._pixmap
        if pm is None:
            return
        p = QPainter(self)
        target = self.rect()
        src_w = pm.width() / max(1.0, pm.devicePixelRatio())
        p.setRenderHint(QPainter.SmoothPixmapTransform,
                        src_w / max(1, target.width()) > 1.25)
        p.drawPixmap(target, pm)


class _CenteredPage(QWidget):
    """Holds one child at the largest size its own cap allows, centred."""

    def __init__(self, child):
        super().__init__()
        self.setStyleSheet("background: transparent;")
        self._child = child
        child.setParent(self)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        c = self._child
        w = max(1, min(self.width(), c.maximumWidth()))
        h = max(1, min(self.height(), c.maximumHeight()))
        c.setGeometry((self.width() - w) // 2, (self.height() - h) // 2, w, h)


class KitStage(QWidget):
    """Flat pixmap by default; swaps to a live, orbitable 3D model when the
    setting is on and the current kit's texture source supports it."""

    def __init__(self, parent=None, default_yaw=0.0):
        super().__init__(parent)
        # The app-wide QSS paints every QWidget with BG_BASE, which is
        # darker than the card — that's what drew a box behind the player.
        # Scoped by object name so it doesn't cascade onto children (an
        # unscoped rule set on a container does).
        self.setObjectName("kitStage")
        self.setStyleSheet("QWidget#kitStage { background: transparent; }")
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)

        self._flat = KitPreviewBox()
        self._flat.setStyleSheet(f"border: none; background: transparent; color: {FG_MUTED}; font-size: 9pt;")
        # The box caps its own size, and a stacked layout pins a capped widget
        # to the top-left: seat it in a page that centres it.
        self._flat_page = _CenteredPage(self._flat)
        self._stack.addWidget(self._flat_page)

        self._frozen = _FrozenImage()
        self._stack.addWidget(self._frozen)
        self._player_view = None   # created lazily, only if 3D is ever used
        self._model_key = None     # (kit_path,) — avoids rebuilding on every repaint
        # Dead-on (0°) by default per the mockups; a column can offset this
        # (see TeamColumn — home/away angle slightly toward each other
        # rather than both staring straight at the camera). Carried across
        # kit/team changes and restored by reset_yaw() — see _load_3d.
        self._default_yaw = default_yaw
        self._yaw = default_yaw
        self._pan_y = 0.0

        # The setting alone can't guarantee 3D — most kits are still a flat
        # PNG the model can't texture with. Without this, "on but showing
        # flat anyway" reads as the toggle simply not working.
        self._badge = display_label("3D UNAVAILABLE FOR THIS KIT", 8, QFont.DemiBold,
                                    track=1.0, color=FG_MUTED)
        self._badge.setStyleSheet(
            self._badge.styleSheet() + f" background: {BG_PANEL}; border: 1px solid {BORDER};"
            " padding: 2px 6px;")
        self._badge.setParent(self)
        self._badge.adjustSize()
        self._badge.hide()

    @property
    def player_view(self):
        """The live 3D view, or None if the stage is currently flat. Used
        by the match-setup kickoff sequence to swap in a walk-off animation
        on the same renderer rather than rebuilding it."""
        return self._player_view

    def reset_yaw(self):
        """Back to this column's own default orientation (not necessarily
        dead-on — see `default_yaw`) and scrolled back to the whole-body
        framing — used after the kickoff run-off."""
        self._yaw = self._default_yaw
        self._pan_y = 0.0
        if self._player_view is not None:
            self._player_view.renderer.yaw = self._yaw
            self._player_view.renderer.pan_y = self._pan_y

    # ── flat-preview passthrough (unchanged TeamColumn call sites) ────────
    def set_pixmap(self, pixmap):
        self._flat.set_pixmap(pixmap)

    def set_placeholder(self, text: str = "NO PREVIEW"):
        self._flat.set_placeholder(text)

    # ── the actual decision point ───────────────────────────────────────
    def update_kit(self, flat_pixmap, kit_source_path: str = None, numbers_source_path: str = None,
                    model3d_cfg: dict = None, head_path: str = None, boots_path: str = None,
                    skin_entry: str = None, skin_path: str = None, finger_tape: str = None,
                    boots_index: int = None, load_3d: bool = True,
                    wrist_tape: str = None, thigh_tape: str = None, socks: str = None):
        """`load_3d=False` only sets the flat preview and leaves the 3D decision
        to a later call — the screen is built at start-up, long before anyone
        looks at it, and loading two models there is what made start-up slow."""
        if flat_pixmap:
            self.set_pixmap(flat_pixmap)
        else:
            self.set_placeholder()

        if not user_prefs.player_3d_preview:
            self._badge.hide()
            self._show_flat()
            return
        if not load_3d:
            return

        if _gl_unusable():
            # No usable OpenGL: the flat kit picture (the kit's previewFile)
            # is all there is, so show it rather than a dead 3D view.
            self._badge.hide()
            self._show_flat()
            return

        # Same inputs as the model already on show: nothing to load. The files
        # are part of the identity (their mtime/size), so a kit edited in the
        # team editor and saved under the same name is still picked up.
        key = (_stamp(kit_source_path), _stamp(numbers_source_path),
               (model3d_cfg or {}).get('fit'), (model3d_cfg or {}).get('collar'),
               _stamp(head_path), _stamp(boots_path), skin_entry, _stamp(skin_path),
               finger_tape, boots_index, wrist_tape, thigh_tape, socks)
        if key == self._model_key and self._player_view is not None:
            self._badge.hide()
            self._show_3d()
            return

        model = _try_load_model(kit_source_path, numbers_source_path, model3d_cfg,
                                head_path, boots_path, skin_entry, skin_path, finger_tape,
                                boots_index, wrist_tape, thigh_tape, socks)
        if model is None:
            self._badge.move(6, 6)
            self._badge.show()
            self._badge.raise_()
            self._show_flat()
            return

        self._badge.hide()
        self._model_key = key
        self._load_3d(model)
        self._show_3d()

    # ── 3D view lifecycle ────────────────────────────────────────────────
    def set_body(self, height_cm, weight_kg):
        """Scale the 3D player like the game does from the roster's height and
        weight (see ui.player_view.body_scale). The model is not reloaded."""
        from ui.player_view import body_scale
        self._body = body_scale(height_cm, weight_kg)
        if self._player_view is not None:
            self._player_view.renderer.body = self._body
            self._player_view.update()

    def _load_3d(self, model):
        from ui.player_view import PlayerView
        from ui.player_anim import IdleAnimation

        # Recreated rather than reusing the GL context across models: the
        # renderer uploads its buffers once in initializeGL, and deleting
        # the widget is the simplest correct way to release them (Qt tears
        # down the widget's own GL context with it) rather than tracking
        # every glDelete* by hand.
        if self._player_view is not None:
            # A team/kit change shouldn't spin the model back to face-on —
            # only carry the orientation forward if the viewer actually
            # rotated it away from that default themselves is unnecessary
            # to distinguish: either way this IS the current orientation,
            # default or user-set, and that's what should persist.
            self._yaw = self._player_view.renderer.yaw
            self._pan_y = self._player_view.renderer.pan_y
            self._stack.removeWidget(self._player_view)
            self._player_view.pause()
            self._player_view.deleteLater()
            self._player_view = None

        # A stale frozen still (kickoff animation interrupted) would keep
        # _show_3d() from ever revealing the new view.
        if self._stack.currentWidget() is self._frozen:
            self._frozen.set_image(None)
            self._stack.setCurrentWidget(self._flat_page)

        view = PlayerView(model, spin=False, transparent=True)
        view.unavailable.connect(self._on_3d_unavailable)
        view.renderer.anim = IdleAnimation(view.renderer.rig)
        view.renderer.yaw = self._yaw
        view.renderer.pan_y = self._pan_y
        view.renderer.body = getattr(self, "_body", (1.0, 1.0))
        # Two players sharing one wall-clock origin breathe and shift in
        # lockstep — reads as robotic. Backdating t0 by a random offset
        # within the loop desyncs them without needing per-frame state.
        view.renderer._t0 -= random.uniform(0.0, IdleAnimation.LOOP)
        self._player_view = view
        self._stack.addWidget(view)

    def _on_3d_unavailable(self):
        """The GL surface failed while rendering: drop to the flat picture.
        Not sticky — the next model load builds a fresh view and tries again."""
        if self.sender() is self._player_view:
            self._show_flat()

    def freeze(self, scale=1.0):
        """Swap the live 3D view for one still image of it, rendered once at
        `scale` times its current size. For animating the stage's geometry
        (zoom, slide): a live view would re-skin and re-render at every
        intermediate size on the GUI thread, which is what made those
        animations stutter; scaling a finished image costs next to nothing.
        Returns False (and changes nothing) if there is nothing to freeze."""
        view = self._player_view
        if view is None or self._stack.currentWidget() is not view:
            return False
        ratio = view.devicePixelRatioF()
        w = max(1, int(view.width() * scale * ratio))
        h = max(1, int(view.height() * scale * ratio))
        if max(w, h) > 2048:
            k = 2048 / max(w, h)
            w, h = max(1, int(w * k)), max(1, int(h * k))
        image = view._surface.render_image(w, h)
        if image is None:
            return False
        view.pause()
        self._frozen.set_image(image)
        self._stack.setCurrentWidget(self._frozen)
        return True

    def unfreeze(self):
        """Back to the live view after freeze()."""
        if self._stack.currentWidget() is self._frozen:
            self._frozen.set_image(None)
            if self._player_view is not None:
                self._stack.setCurrentWidget(self._player_view)
                if self.isVisible():
                    self._player_view.resume()
            else:
                self._stack.setCurrentWidget(self._flat_page)

    def _show_3d(self):
        if self._player_view is not None and self._stack.currentWidget() is not self._frozen:
            self._stack.setCurrentWidget(self._player_view)

    def _show_flat(self):
        self._stack.setCurrentWidget(self._flat_page)
        if self._player_view is not None:
            self._player_view.pause()

    def hideEvent(self, event):
        if self._player_view is not None:
            self._player_view.pause()
        super().hideEvent(event)

    def showEvent(self, event):
        if self._player_view is not None and self._stack.currentWidget() is self._player_view:
            self._player_view.resume()
        super().showEvent(event)
