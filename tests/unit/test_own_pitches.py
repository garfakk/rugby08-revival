"""The mod's own pitches (backend/pitches.py, data/pitches): packs of the
game's layout, a match on one points the scene at it and keeps the stadium's
dirt at the lowest."""
import os

from app.match_data_builder import _own_pitch
from app.state import MatchConfig
from backend import game_files_processor as GFP
from backend import pitches
from shared.omodel.bigfile import BigArchive, pack_big
from conftest import point_config

XML = (b'<Project><stadium Index="1" FileName="auckland" Country="1">\n'
       b'<environment breath="off" type="day" DirtType="Grass" ProbabilityDirt="Medium" ProbabilityPrecipitation="None"/>\n'
       b'<environment type="night" ProbabilityDirt="High"/></stadium>\n'
       b'<stadium Index="2" FileName="other"><environment type="day" ProbabilityDirt="High"/></stadium></Project>')


def test_own_packs_are_in_the_repo_and_have_the_game_layout(monkeypatch):
    here = os.path.join(os.path.dirname(__file__), "..", "..", "data")
    point_config(monkeypatch, data_dir=here)
    for name in pitches.OWN:
        archive = BigArchive.open(pitches.pack_path(name))
        assert {"Textures.fsh", "PitchColour.o"} <= set(archive.entries), name
        assert name in pitches.NAMES and pitches.region_of(name) == "Synthetic & hybrid"


def test_dirt_is_set_for_that_stadium_and_environment_only():
    out = pitches.set_dirt(XML, "Auckland", "night")
    assert b'type="night" ProbabilityDirt="Very_Low"' in out
    assert b'ProbabilityDirt="Medium"' in out and b'ProbabilityDirt="High"/></stadium></Project>' in out
    assert pitches.set_dirt(XML, "auckland", "cold") is None and pitches.set_dirt(XML, "nowhere", "day") is None


def test_set_line_points_the_scene_at_the_pitch(tmp_path):
    path = tmp_path / "s.big"
    path.write_bytes(pack_big([("Config2.bin", b"\x16pitches\\Reg2_08_Norm_n"), ("Stadium.o", b"m")]))
    assert pitches.set_line(str(path), "Mod_08_hybrid_d")
    got = BigArchive.open(str(path))
    assert got.read("Config2.bin") == bytes([len("pitches\\Mod_08_hybrid_d")]) + b"pitches\\Mod_08_hybrid_d"
    assert got.read("Stadium.o") == b"m"


def test_a_match_on_an_own_pitch_is_deployed(tmp_path, monkeypatch):
    cfg = MatchConfig()
    cfg.stadium = {"stadium_id": 49, "data": {"game_id": 49}}
    cfg.environment, cfg.pitch_texture = "night", "Mod_08_synthetic_n"
    own = _own_pitch(cfg, {})
    assert own["scene"] == "stadiums/auckland.night" and own["pack"].endswith("mod_08_synthetic_n.big")
    cfg.pitch_texture = "Reg2_08_best_d"
    assert _own_pitch(cfg, {}) is None
    data, game = tmp_path / "data", tmp_path / "game"
    (data / "pitches").mkdir(parents=True)
    game.mkdir()
    (data / own["pack"]).write_bytes(pack_big([("Textures.fsh", b"x")]))
    scene = game / GFP.stadium_game_filename("stadiums/auckland.night")
    scene.write_bytes(pack_big([("Config2.bin", b"\x03abc")]))
    xml = game / GFP.stadium_game_filename("xml/config/stadiuminfo.xml")
    xml.write_bytes(XML)
    point_config(monkeypatch, data_dir=str(data), game_dir=str(game))
    put = GFP._deploy_own_pitch(own, str(game))
    assert GFP.stadium_game_filename("stadiums/pitches/mod_08_synthetic_n") in put
    assert (game / put[0]).is_file()
    assert b"Mod_08_synthetic_n" in BigArchive.open(str(scene)).read("Config2.bin")
    assert b'type="night" ProbabilityDirt="Very_Low"' in xml.read_bytes()


def test_pitch_conditions_are_named_simply_and_numbered_when_they_clash():
    """The quick match list names pitches by condition; the game has several of
    one condition (day / night, other regions): those are numbered."""
    from backend import pitches
    names = sorted(pitches.NAMES, key=pitches.condition_order)
    labels = pitches.simple_labels(names)
    assert len(set(labels.values())) == len(names)            # every pitch has its own name
    assert labels[next(n for n in names if pitches.condition_label(n) == "Dry")] == "Dry"
    hard = [labels[n] for n in names if pitches.condition_label(n) == "Hard"]
    assert hard == [f"Hard {i}" for i in range(1, len(hard) + 1)] and len(hard) > 1
    one = [n for n in names if pitches.condition_label(n) == "Muddy"][:1]
    assert pitches.simple_labels(one) == {one[0]: "Muddy"}    # no clash on offer: no number
    assert [pitches.condition_order(n) for n in names] == sorted(pitches.condition_order(n) for n in names)
