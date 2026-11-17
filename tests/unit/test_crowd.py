"""The crowd of a match (backend/crowd.py): emptier stands, fans in the
teams' colours, a quieter crowd."""
import os
import struct

import numpy as np
import pytest
from PIL import Image

from app.match_data_builder import _crowd
from app.state import MatchConfig
from backend import crowd
from backend import game_files_processor as GFP
from shared.config import config
from shared.omodel.bigfile import BigArchive, pack_big
from shared.omodel.fshlib import Fsh, dxt5_decode
from conftest import point_config


def _frame():
    """A 512x128 crowd frame: a grey shirt, a face, jeans, empty around."""
    a = np.zeros((128, 512, 4), np.uint8)
    a[40:90, 100:130] = (150, 150, 150, 255)       # shirt
    a[25:38, 108:122] = (205, 160, 130, 255)       # face
    a[90:128, 100:130] = (60, 80, 140, 255)        # jeans
    return a


def _fsh(frames):
    """SHPI bytes holding `frames` as DXT5 entries."""
    n = len(frames)
    head = 16 + 8 * n
    blobs, offs = [], []
    off = head
    for a in frames:
        px = crowd.dxt5_encode(a)
        block = struct.pack("<I", 0x62 | ((16 + len(px)) << 8)) + struct.pack("<HH", 512, 128) + bytes(8) + px
        offs.append(off)
        blobs.append(block)
        off += len(block)
    out = b"SHPI" + struct.pack("<II", off, n) + b"G264"
    out += b"".join(struct.pack("<4sI", f"fr{i:02d}".encode(), o) for i, o in enumerate(offs))
    return out + b"".join(blobs)


def test_dxt5_encoding_keeps_the_frame():
    a = _frame()
    back = np.frombuffer(dxt5_decode(crowd.dxt5_encode(a), 512, 128), np.uint8).reshape(128, 512, 4)
    assert (back[..., 3] == a[..., 3]).all()
    inside = (slice(44, 88), slice(104, 128))              # blocks of one colour only
    assert np.abs(back[inside].astype(int) - a[inside].astype(int)).max() <= 4


def test_fans_wear_the_teams_colours_but_keep_their_faces_and_jeans():
    blob = crowd.paint_crowd_fsh(_fsh([_frame(), _frame()]), [(200, 0, 0)], [(0, 0, 200)])
    frames = [np.array(e.decode()) for e in Fsh(blob).entries]
    assert len(blob) == len(_fsh([_frame(), _frame()]))
    shirt, face, jeans = frames[0][60, 115], frames[0][30, 115], frames[0][110, 115]
    assert shirt[3] > 200 and (shirt[0] > shirt[1] + 60 or shirt[2] > shirt[1] + 60 or abs(int(shirt[0]) - 150) < 12)
    assert abs(int(face[0]) - 205) < 12 and abs(int(jeans[2]) - 140) < 12
    assert (frames[0] == frames[1]).all()             # same fan, same colour in every frame
    assert (frames[0][:, :90, 3] == 0).all()          # nobody added


def test_kit_colours_main_then_a_different_one(tmp_path):
    im = Image.new("RGB", (256, 256), (20, 30, 120))
    im.paste((240, 240, 240), (0, 0, 256, 60))
    path = tmp_path / "kit.png"
    im.save(path)
    main, second = crowd.kit_colours(str(path))
    assert abs(main[2] - 120) < 16 and min(second) > 200
    assert crowd.kit_colours(str(tmp_path / "none.png")) == []


def test_a_quiet_crowd_reacts_less_and_calms_sooner():
    events = b'<event id="X" additive="0"><home use="1" modifier="1.0" /><away modifier="0.7" /></event>'
    assert crowd.quiet_events(events).count(b'modifier="0.50"') == 1
    assert b'modifier="0.35"' in crowd.quiet_events(events)
    const = (b'<crowdman name="m_rExciteRateDefault" value="0.6"></crowdman>'
             b'<crowdman name="m_rExciteDecay" value="0.03"></crowdman>'
             b'<crowdman name="m_rTurnoverDecayThreshold" value="7.0"></crowdman>'
             b'<ballhistory name="m_rBlowOutBonus" value="-0.1"></ballhistory>')
    out = crowd.quiet_constants(const)
    assert b'"m_rExciteRateDefault" value="0.3"' in out and b'"m_rExciteDecay" value="0.048"' in out
    assert b'value="7.0"' in out and b'value="-0.1"' in out


def test_the_match_data_names_the_scene_only_when_the_crowd_changes():
    cfg = MatchConfig()
    cfg.stadium = {"stadium_id": 49, "data": {"game_id": 49}}
    cfg.environment = "night"
    assert _crowd(cfg) is None
    cfg.crowd_size, cfg.crowd_colours = "half", True
    assert _crowd(cfg) == {"scene": "stadiums/auckland.night", "size": "half", "colours": True, "mood": "normal"}


def test_a_quiet_crowd_is_deployed_as_loose_sound_files(tmp_path, monkeypatch):
    game = tmp_path / "game"
    game.mkdir()
    for path, xml in ((crowd.SOUND_EVENTS, b'<a modifier="1.0"/>'),
                      (crowd.SOUND_CONSTANTS, b'<c name="m_rExciteDecay" value="0.03"/>')):
        (game / GFP.stadium_game_filename(path)).write_bytes(xml)
    point_config(monkeypatch, game_dir=str(game))
    spec = {"scene": "stadiums/auckland.night", "size": "full", "colours": False, "mood": "quiet"}
    assert GFP._deploy_crowd(spec, {}, str(game), []) == []      # already there: not ours to list
    assert b'modifier="0.50"' in (game / GFP.stadium_game_filename(crowd.SOUND_EVENTS)).read_bytes()


GOB = os.environ.get("R08_DATA_GOB", "/home/thomas/.wine/drive_c/Program Files/EA SPORT/Rugby 08/Data/data.gob")


@pytest.mark.skipif(not os.path.isfile(GOB), reason="the game's data.gob is not here")
def test_half_a_stadium_keeps_about_half_its_crowd(tmp_path, monkeypatch):
    from backend import stadium_scene
    from shared.omodel.olib import parse_o
    monkeypatch.setattr(config, "R08_data_gob_filepath", GOB)
    pack = stadium_scene.stock_pack_path("stadiums/twickenham.day")
    archive = BigArchive.open(pack)
    path = tmp_path / "s.big"
    path.write_bytes(pack_big([(n, archive.read(n)) for n in archive.entries]))
    assert crowd.apply(str(path), "half")
    thin = BigArchive.open(str(path))

    def area(blob):
        total = 0.0
        for m in parse_o(blob):
            if m.shapename.startswith("rw"):
                for a, b, c in m.triangles:
                    p = np.array([m.positions[a], m.positions[b], m.positions[c]])
                    total += np.linalg.norm(np.cross(p[1] - p[0], p[2] - p[0])) / 2
        return total
    before, after = area(archive.read("Stadium.o")), area(thin.read("Stadium.o"))
    assert 0.4 < after / before < 0.6
    assert thin.read("Crowd.fsh") == archive.read("Crowd.fsh")
    assert not crowd.apply(str(path), "full")
