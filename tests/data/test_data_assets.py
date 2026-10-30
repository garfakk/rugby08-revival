"""Every asset a team season points at exists: ball, banners, logos, pads and
each kit (front, back numbers, preview), kit variants included. Checked with
the team editor's own asset_status / ASSET_SPECS. Kit textures ship packed
(shared/kit_files.py, packaging/pack_kit_textures.py)."""
import os

import pytest

from app import game_data as G
from app import variants as V
from ui.editor_kit import asset_status

from realdata import raw, team_seasons

pytestmark = pytest.mark.data

BAD = {"missing", "partial", "outside"}


def _assets(info):
    """(label, spec key, relative path) for every asset of a season block."""
    for key in ("ball", "banners", "pads"):
        yield key, key, info.get(key, "")
    for key, rel in (info.get("logos") or {}).items():
        yield f"logos.{key}", f"logos.{key}", rel
    for kit_id, kit in (info.get("kits") or {}).items():
        for variant in [V.DEFAULT] + V.kit_variant_ids(kit):
            resolved = V.resolve_kit(kit, variant)
            where = f"kits.{kit_id}" + (f"[{variant}]" if variant else "")
            for key in ("frontKitFile", "backKitFile", "previewFile"):
                yield f"{where}.{key}", key, resolved.get(key, "")


def _status(tid, season):
    info, root = raw()[0][tid][season], raw()[2][tid]
    for label, spec, rel in _assets(info):
        state, detail, _ = asset_status(root, rel, G.ASSET_SPECS.get(spec), check_size=True)
        yield label, rel, state, detail


@pytest.mark.parametrize("tid,season", team_seasons())
def test_team_assets_exist(tid, season, known_issue):
    known_issue([f"{label}: {rel} ({detail})"
                 for label, rel, state, detail in _status(tid, season) if state in BAD])


@pytest.mark.parametrize("tid,season", team_seasons())
def test_team_asset_sizes(tid, season, known_issue):
    """Wrong-sized images are resized by the mod (quality loss), so this is
    reported separately from missing files."""
    known_issue([f"{label}: {rel} is {detail}"
                 for label, rel, state, detail in _status(tid, season) if state == "size"])


@pytest.mark.parametrize("tid,season", team_seasons())
def test_kit_textures_are_packed(tid, season):
    """Back numbers as one .webp strip and fronts as .webp, not loose PNGs
    (22 near-identical PNGs per kit made the pack several GB): run
    packaging/pack_kit_textures.py after adding a PNG kit."""
    loose = [f"{label}: {rel}" for label, key, rel in _assets(raw()[0][tid][season])
             if key in ("frontKitFile", "backKitFile") and rel.lower().endswith(".png")]
    assert not loose, loose
