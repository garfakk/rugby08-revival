"""
ui/skin_preview.py — the skin texture a player will wear, for the preview
==========================================================================
Builds what backend/game_files_processor writes into skins.fsh: the base
(custom skin image, or the stock tone read from skin.fsh) with every layer
alpha-composited on top, bottom first. The result is cached as a PNG keyed
by its inputs, so the 3D stage can load it like any other skin image.

The GL shader discards pixels with alpha < 0.35, so the composite is made
fully opaque before saving.
"""
import hashlib
import os
from pathlib import Path

from app import appearance as A
from shared.config import config

SIZE = (512, 256)


from shared.log import get_logger

log = get_logger(__name__)


def _stock_image(entry):
    from PIL import Image
    from shared.omodel import Fsh
    from ui.player_stage import generic_assets
    skin = generic_assets().get("skin")
    if not skin:
        return Image.new("RGBA", SIZE, (200, 160, 130, 255))
    fsh = Fsh(Path(skin).read_bytes())
    chosen = next((e for e in fsh.entries if e.name == entry), None)
    if chosen is None:
        return Image.new("RGBA", SIZE, (200, 160, 130, 255))
    return chosen.decode().convert("RGBA")


def _key(resolved):
    parts = [resolved["tone"], str(resolved["gloved"]), resolved["custom_skin"] or ""]
    parts += resolved["layers"]
    for p in [resolved["custom_skin"]] + resolved["layers"]:
        if p:
            try:
                parts.append(str(os.path.getmtime(p)))
            except OSError:
                pass
    return hashlib.sha1("|".join(parts).encode("utf-8")).hexdigest()[:20]


def compose(resolved, cache_dir, force=False):
    """(skin_path, skin_entry) for KitStage.update_kit. A plain stock tone
    needs no file: (None, entry) — unless `force`, which writes the stock
    tone out too (the flat strip under the stage wants an image either way).
    Otherwise the composited PNG path."""
    entry = A.stock_entry(resolved)
    if not force and not resolved["custom_skin"] and not resolved["layers"]:
        return None, entry
    os.makedirs(cache_dir, exist_ok=True)
    out = os.path.join(cache_dir, f"skin_{_key(resolved)}.png")
    if os.path.isfile(out):
        return out, entry
    from PIL import Image
    try:
        if resolved["custom_skin"]:
            base = Image.open(resolved["custom_skin"]).convert("RGBA")
        else:
            base = _stock_image(entry)
        if base.size != SIZE:
            base = base.resize(SIZE, Image.LANCZOS)
        for path in resolved["layers"]:
            layer = Image.open(path).convert("RGBA")
            if layer.size != base.size:
                layer = layer.resize(base.size, Image.LANCZOS)
            base = Image.alpha_composite(base, layer)
        base.putalpha(255)
        base.save(out)
    except Exception as e:
        log.warning(f"could not build skin preview: {e}")
        return None, entry
    return out, entry
