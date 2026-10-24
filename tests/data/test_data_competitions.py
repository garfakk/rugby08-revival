"""Competition templates (bundled + data pack) can run with their default
entrants on the real data, and competition branding assets exist."""
import glob
import os

import pytest

from app.tournament import engine, formats
from conftest import REAL_DATA, SRC

from realdata import HAS_DATA, load_json, store

pytestmark = pytest.mark.data

TEMPLATE_DIRS = [os.path.join(SRC, "assets", "data", "competitions"),
                 os.path.join(REAL_DATA, "competitions")]


def _templates():
    if not HAS_DATA:
        return []
    return [pytest.param(tpl, id=tid) for tid, tpl in formats.load_templates(TEMPLATE_DIRS).items()]


@pytest.mark.parametrize("tpl", _templates())
def test_template_runs_with_default_entrants(tpl, known_issue):
    season = tpl.get("season", "")
    participants = engine.default_participants(tpl, season)
    known_issue(formats.problems(store(), tpl, season, participants))


def _branding_files():
    return [pytest.param(p, id=os.path.relpath(os.path.dirname(p), REAL_DATA))
            for p in sorted(glob.glob(os.path.join(REAL_DATA, "competitions", "*", "*.json")))]


def _asset_paths(node):
    if isinstance(node, dict):
        for k, v in node.items():
            if k not in ("template", "logo_frontend"):     # the menu logo is optional
                yield from _asset_paths(v)
    elif isinstance(node, list):
        for v in node:
            yield from _asset_paths(v)
    elif isinstance(node, str) and node.lower().endswith((".png", ".fsh", ".big")):
        yield node


@pytest.mark.parametrize("path", _branding_files())
def test_branding_assets_exist(path, known_issue):
    root = os.path.dirname(path)
    missing = []
    for rel in sorted(set(_asset_paths(formats._read(path)))):
        frames = [rel.replace("%", str(i)) for i in range(1, 5)] if "%" in rel else [rel]
        if not any(os.path.isfile(os.path.join(root, f)) for f in frames):
            missing.append(rel)
    known_issue([f"{rel} not found" for rel in missing])
