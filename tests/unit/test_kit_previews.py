"""app/kit_previews.py: which preview images the generator writes, and the
previewFile entries it adds to team files. The rendering itself needs the
game's data.gob and OpenGL: check it by hand on a copy,
`python3 src/packaging/gen_kit_previews.py --data <copy> --team England`."""
import json
import os

import pytest

from app import kit_previews as K
from app.state import DataStore
from conftest import FIXTURE_DATA


def _team(tmp_path, kits, season="2024", folder="Testland", tid="9001"):
    root = tmp_path / "teams" / folder
    (root / "kits").mkdir(parents=True)
    for name in ("a_front.png", "b_front.png", "wc_front.png"):
        (root / "kits" / name).write_bytes(b"png")
    path = root / f"{folder.lower()}.json"
    path.write_text(json.dumps({tid: {season: {"name": folder, "kits": kits}}}))
    return str(tmp_path / "teams"), str(path)


def test_existing_preview_overwritten_missing_one_assigned(tmp_path):
    teams, path = _team(tmp_path, {
        "home": {"frontKitFile": "kits/a_front.png", "backKitFile": "kits/back_%.png",
                 "previewFile": "kits/home_preview.png"},
        "away": {"frontKitFile": "kits/b_front.png", "previewFile": ""},
    })
    jobs, assignments, problems = K.plan(teams)
    assert problems == []
    by_label = {j.label: j for j in jobs}
    home = by_label["Testland 2024 home"]
    assert home.preview.endswith(os.path.join("kits", "home_preview.png"))
    assert home.back.endswith(os.path.join("kits", "back_%.png"))     # resolved when rendered
    assert [(a.kit, a.preview) for a in assignments] == [("away", "kits/away_preview.png")]


def test_variant_with_own_shirt_gets_own_preview(tmp_path):
    teams, path = _team(tmp_path, {
        "home": {"frontKitFile": "kits/a_front.png", "previewFile": "kits/home_preview.png",
                 "variants": {"rwc_2023": {"label": "RWC", "frontKitFile": "kits/wc_front.png"},
                              "patch": {"label": "same shirt", "color": "red"}}},
    })
    jobs, assignments, _ = K.plan(teams)
    assert [(a.variant, a.preview) for a in assignments] == [("rwc_2023", "kits/home_rwc_2023_preview.png")]
    assert len(jobs) == 2                        # the "patch" variant shares the plain picture
    K.assign_previews(assignments)
    kit = json.load(open(path))["9001"]["2024"]["kits"]["home"]
    assert kit["variants"]["rwc_2023"]["previewFile"] == "kits/home_rwc_2023_preview.png"
    assert kit["previewFile"] == "kits/home_preview.png"
    assert "previewFile" not in kit["variants"]["patch"]
    assert K.plan(teams)[1] == []                # second run: nothing new


def test_preview_shared_by_different_shirts_split(tmp_path):
    teams, _ = _team(tmp_path, {
        "home": {"frontKitFile": "kits/a_front.png", "previewFile": "kits/p.png"},
        "home WC": {"frontKitFile": "kits/b_front.png", "previewFile": "kits/p.png"},
        "home2": {"frontKitFile": "kits/a_front.png", "previewFile": "kits/p.png"},   # same shirt
    })
    jobs, assignments, _ = K.plan(teams)
    assert [(a.kit, a.preview) for a in assignments] == [("home WC", "kits/home_wc_preview.png")]
    assert sorted(os.path.basename(j.preview) for j in jobs) == ["home_wc_preview.png", "p.png"]


def test_unrenderable_kits_reported(tmp_path):
    teams, _ = _team(tmp_path, {"home": {"frontKitFile": "", "previewFile": "x.png"},
                                "away": {"frontKitFile": "kits/missing.png"}})
    jobs, assignments, problems = K.plan(teams)
    assert jobs == [] and assignments == []
    assert len(problems) == 2


def test_disabled_seasons_and_team_filter(tmp_path):
    teams, path = _team(tmp_path, {"home": {"frontKitFile": "kits/a_front.png"}})
    data = json.load(open(path))
    data["9001"]["2024"]["enabled"] = False
    json.dump(data, open(path, "w"))
    assert len(K.plan(teams)[0]) == 1            # disabled seasons ship too
    assert K.plan(teams, only=["testland"])[0]
    assert K.plan(teams, only=["Other"])[0] == []


def test_assign_keeps_rest_of_file_and_loads(data_dir):
    jobs, assignments, _ = K.plan(os.path.join(data_dir, "teams"))
    assert jobs
    before = {p: json.load(open(p)) for p in {a.team_file for a in assignments}}
    for a in assignments:      # pretend they were rendered
        target = os.path.join(os.path.dirname(a.team_file), a.preview)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        open(target, "wb").close()
    K.assign_previews(assignments)
    for path, old in before.items():
        new = json.load(open(path))
        assert new.keys() == old.keys()
        for tid in old:
            assert new[tid].keys() == old[tid].keys()            # disabled seasons kept
    ds = DataStore()
    for tid, seasons in ds.teams.items():
        for info in seasons.values():
            for kit in (info.get("kits") or {}).values():
                if (kit.get("frontKitFile") or "") and os.path.isfile(
                        os.path.join(ds.teams_folder_path[tid], kit["frontKitFile"])):
                    assert kit.get("previewFile")


@pytest.mark.parametrize("front,kit,variant,expected", [
    ("kits_2024/home_front.png", "home", "", "kits_2024/home_preview.png"),
    ("kits_2024/home_wc_front.png", "home", "rwc_2023", "kits_2024/home_rwc_2023_preview.png"),
    ("front.png", "Home WC", "", "home_wc_preview.png"),
])
def test_default_preview_path(front, kit, variant, expected):
    assert K.default_preview_path(front, kit, variant) == expected

