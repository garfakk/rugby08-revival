"""
ui/kit_preview.py — a kit's preview image, rendered from the 3D player
========================================================================
The menus' flat kit picture (a kit's previewFile) is the 3D player wearing
the kit, standing still and facing the camera, on a transparent background —
the same model, textures and renderer as the live preview (ui/player_stage,
ui/player_view), so the picture matches what the 3D view shows.

Needs a QGuiApplication, an OpenGL 3.3 context and the generic player assets
extracted from the game's data.gob (backend.mod_utils.player_preview_assets).
Driven by packaging/gen_kit_previews.py.
"""
import os

from PyQt5.QtCore import Qt

from shared.log import get_logger

log = get_logger(__name__)

# One mannequin for every preview, so they read as a set: a stock face with
# no headgear and the light skin that goes with it (see match_setup's
# MANNEQUIN_POOL).
FACE_ID = 4966          # Andrew Farrell
SKIN_ENTRY = "wksk"
SIZE = 512
# Rendered this many times larger, then scaled down: the edges come out
# smooth, which a single-sampled render doesn't give.
SUPERSAMPLE = 2
FACING_CAMERA = 0.0     # yaw: the player looks straight down the camera axis


def render_kit_preview(front, back="", model3d=None, size=SIZE):
    """QImage (ARGB32, size x size, transparent background) of the player
    wearing the kit, or None when the kit or the generic assets can't be
    loaded."""
    from backend.mod_utils import stock_head_path
    from shared.config import config
    from ui.player_anim import IdleAnimation
    from ui.player_stage import _try_load_model
    from ui.player_view import render_frames

    head = stock_head_path(FACE_ID, os.path.join(config.temp_directory, "stock_heads"))
    model = _try_load_model(front, back or None, model3d, head_path=head, skin_entry=SKIN_ENTRY)
    if model is None:
        return None
    big = size * SUPERSAMPLE
    # t=0 of the idle: standing square, arms down, no glance to the side
    image = render_frames(model, size=(big, big), times=(0.0,), yaw=FACING_CAMERA,
                          animation=IdleAnimation, transparent=True)[0]
    return image.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
