"""One test per fixed bug, named after it, citing the commit that fixed it.
Bugs whose fix is better checked next to the feature are tested there; the
index at the bottom says where.

Rule: every bug fix adds its test here (or next to the feature) FIRST — it
must fail before the fix and pass after."""
import logging
import os
import re
import types

import pytest

from conftest import SRC


# ── 804d31ee: crash on slow PCs when loading took too long ──────────────
def test_804d31ee_silent_audio_loop_removed():
    """The zeroed loop written into Audio/aems.big crashed slow PCs: the
    patch and its template must stay gone."""
    assert not os.path.exists(os.path.join(SRC, "backend", "audio_patch.py"))
    assert not os.path.exists(os.path.join(SRC, "assets", "templates", "silent_loop.abk"))
    pattern = re.compile(r"audio_patch|silent_loop|aems\.big", re.I)
    hits = []
    for root, _dirs, files in os.walk(SRC):
        for name in files:
            if name.endswith(".py"):
                path = os.path.join(root, name)
                with open(path, encoding="utf-8", errors="replace") as f:
                    for n, line in enumerate(f, 1):
                        if pattern.search(line):
                            hits.append(f"{os.path.relpath(path, SRC)}:{n}")
    assert not hits, hits


def test_804d31ee_game_log_keeps_the_tail(tmp_path, caplog, monkeypatch):
    """A crash is logged last: a long game log must keep its end."""
    from backend import mod_utils
    monkeypatch.setattr(mod_utils, "logging_active", lambda: True)
    lines = ["old session"] + ["==== session 2"] + [f"line {i}" for i in range(300)] + ["CRASH 0xC0000005"]
    (tmp_path / "rugby08_patches.log").write_text("\n".join(lines))
    with caplog.at_level(logging.INFO):
        mod_utils.log_game_session(str(tmp_path), max_lines=100)
    text = caplog.text
    assert "CRASH 0xC0000005" in text
    assert "line 0" in text and "lines omitted" in text
    assert "old session" not in text


# ── e42a7b64: download missing menu music (source runs only) ────────────
def test_e42a7b64_no_music_download_offer_in_frozen_build(monkeypatch):
    import shared.app_paths as app_paths
    import ui.music as music
    from main import MainWindow
    called = []
    monkeypatch.setattr(music, "missing_downloads", lambda: called.append(1) or [])
    monkeypatch.setattr(app_paths, "FROZEN", True)
    MainWindow._offer_music_download(types.SimpleNamespace(_music_downloader=None))
    assert not called
    monkeypatch.setattr(app_paths, "FROZEN", False)
    MainWindow._offer_music_download(types.SimpleNamespace(_music_downloader=None))
    assert called


# ── a75d60ca: difficulty levels ─────────────────────────────────────────
def test_a75d60ca_boosted_levels_play_the_stock_elite_ai():
    from app import difficulty
    assert [difficulty.mission_difficulty(l) for l in ("legend", "immortal")] == [2, 2]


# ── match_data_builder: home_team_side was never passed to the .mis ─────
def test_home_team_side_reaches_the_mission_file(ds, game_dir):
    import xml.etree.ElementTree as ET
    from app.match_data_builder import build_match_data
    from backend import game_files_processor as GFP
    from backend import game_specific_variables as gsv
    from conftest import make_match_config
    GFP.create_mission_file(build_match_data(ds, make_match_config(ds, home_team_side="right")))
    root = ET.parse(os.path.join(game_dir, gsv.game_filenames["missionFile"])).getroot()
    assert root.get("side") == "right"


# ── match_data_builder: "pitch_logo" key never reached the graphics step ─
def test_pitch_logos_key_is_plural(ds):
    from app.match_data_builder import build_match_data
    from conftest import make_match_config
    md = build_match_data(ds, make_match_config(ds))
    assert "pitch_logos" in md and "pitch_logo" not in md


# ── team_ops.remove: an inheriting variant got an empty roles set ───────
def test_remove_from_inheriting_variant_creates_no_roles():
    from app import team_ops
    entry = {"players": ["a", "b"]}
    team_ops.remove(entry, 0)
    assert "roles" not in entry


# Covered next to the feature:
#   804d31ee  .mis always has <WIND> (no-wind crash)   files/test_game_files.py::test_wind_always_written
#   a75d60ca  custom face rendered as a strip          unit/test_codecs.py::test_triangles_detects_list_vs_strip,
#                                                      ::test_custom_head_parses_as_clean_surface
#   a75d60ca  crowd volume in the profile              unit/test_game_profile.py::test_vol_crowd_set_deploy_read
#   a75d60ca  difficulty mapping                       unit/test_difficulty.py
#   e0c4a86a  data parsed off the GUI thread           pipeline/test_match_pipeline.py::test_read_files_works_on_a_thread_without_qt
#   e0c4a86a  splash / early close                     qt/test_startup.py
#   e42a7b64  music download (.part, rename)           unit/test_music.py
#   R08_handler score was a 1-tuple                    unit/test_match_result.py::test_read_match_result
#   int("") on an empty squad slot                     pipeline/test_match_pipeline.py::test_empty_player_slots_skipped
#   save_team dropped disabled seasons                 files/test_json_and_import.py::test_save_team_keeps_disabled_seasons
#   challenge files saying "random" side/kick-off      unit/test_challenges.py::test_normalise_migrates_old_random
