"""A kit front is checked against the texture the game draws (512x512): that
size or a whole multiple scales down cleanly; anything else is "size"."""
from PIL import Image

from app.game_data import ASSET_SPECS
from ui.editor_kit import asset_status


def test_front_sizes(tmp_path):
    spec = ASSET_SPECS["frontKitFile"]
    for (w, h), state in {(512, 512): "ok", (1024, 1024): "ok", (2048, 2048): "ok",
                          (768, 768): "size", (1024, 2048): "size", (256, 256): "size"}.items():
        Image.new("RGB", (w, h)).save(tmp_path / f"f{w}x{h}.webp", lossless=True)
        assert asset_status(str(tmp_path), f"f{w}x{h}.webp", spec, check_size=True)[0] == state, (w, h)
