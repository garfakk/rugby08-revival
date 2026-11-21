"""Competition templates (bundled + data pack) can run with their default
entrants on the real data, and competition branding assets exist."""
import glob
import os

import pytest

from app.tournament import engine, formats
from conftest import REAL_DATA

from realdata import HAS_DATA, load_json, store

pytestmark = pytest.mark.data

TEMPLATE_DIRS = [os.path.join(REAL_DATA, "competitions")]


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


@pytest.mark.parametrize("path", _branding_files())
def test_dressing_sets_are_complete(path):
    """Each "pads" / "posts" set a competition names is one picture of its
    kind's shape, each "adboards" a folder with something in it
    (app/dressing.py)."""
    from PIL import Image
    from backend.stadium_dressing import PADS_SIZE, POSTS_SIZE
    root = os.path.dirname(path)
    data = formats._read(path)
    entries = [data] + list((data.get("seasons") or {}).values())
    problems = []
    for entry in entries:
        for key, size in (("pads", PADS_SIZE), ("posts", POSTS_SIZE), ("adboards", None)):
            rel = entry.get(key)
            if not rel:
                continue
            full = os.path.join(root, rel)
            if size:
                if not os.path.isfile(full):
                    problems.append(f"{key}: {rel} is not a picture")
                    continue
                with Image.open(full) as im:
                    if im.width * size[1] != im.height * size[0]:
                        problems.append(f"{key}: {rel} is {im.size}, not {size[0]}:{size[1]}")
            elif not os.path.isdir(full) or not os.listdir(full):
                problems.append(f"{key}: {rel} is not a set folder")
    assert not problems, problems


# 50/22 from August 2021; the 22m pass-back law (no gain when the kicking team
# took the ball back into its 22) from the 2008-09 ELVs; a penalty kicked to
# touch after time keeps its lineout from the 2017 global trial (southern
# hemisphere from January, northern from the 2017-18 season)
LAWS = {"rwc_2007": (False, False, False), "six_nations_2008": (False, False, False),
        "heineken_cup_2008": (False, False, False), "six_nations_2009": (False, True, False),
        "tri_nations_2008": (False, True, False), "six_nations_2017": (False, True, False),
        "rugby_championship_2017": (False, True, True),
        "six_nations_2018": (False, True, True), "six_nations_2021": (False, True, True),
        "rugby_championship_2021": (True, True, True),
        "six_nations_2022": (True, True, True), "rwc_2023": (True, True, True)}
KEYS = ("law_5022", "law_22m", "law_penalty_touch")


def test_templates_set_the_laws_of_their_time():
    if not HAS_DATA:
        pytest.skip("no data pack")
    templates = formats.load_templates(TEMPLATE_DIRS)
    for tid, tpl in templates.items():
        opts = tpl.get("default_options") or {}
        assert all(isinstance(opts.get(k), bool) for k in KEYS), tid
    for tid, laws in LAWS.items():
        opts = templates[tid]["default_options"]
        assert tuple(opts[k] for k in KEYS) == laws, tid
