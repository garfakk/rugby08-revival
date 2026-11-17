"""The pitch logo model rebuilt with a layout: the logos where asked, as
many as asked, the rest of the model untouched. Needs the game's data.gob
(the model is the game's): skipped without it."""
import os

import pytest

GOB = "/home/thomas/.wine/drive_c/Program Files/EA SPORT/Rugby 08/Data/data.gob"


@pytest.fixture
def model(tmp_path, monkeypatch):
    from shared.config import config
    gob = os.environ.get("R08_DATA_GOB", GOB)
    if not os.path.isfile(gob):
        pytest.skip("the game's data.gob is not here")
    monkeypatch.setattr(config, "R08_data_gob_filepath", gob)
    monkeypatch.setattr(config, "temp_directory", str(tmp_path))
    from backend import pitch_logos
    pitch_logos._STOCK.clear()
    return pitch_logos


def _meshes(blob):
    from shared.omodel.olib import parse_o
    return {m.shapename: m for m in parse_o(blob)}


def test_stock_layout_rebuilds_the_stock_model(model):
    layout = model.stock_layout()
    assert [l["kind"] for l in layout] == ["centre", "side_a", "side_b"]
    assert abs(layout[1]["z"] - 28) < 0.5 and abs(layout[0]["size"] - 14) < 0.1
    with open(model.stock_path(), "rb") as fh:
        stock = _meshes(fh.read())
    rebuilt = _meshes(model.build(layout))
    for tag in ("loga", "logb"):
        assert len(rebuilt[tag].positions) == len(stock[tag].positions)
        assert rebuilt[tag].triangles == stock[tag].triangles
        assert max(abs(a - b) for p, q in zip(rebuilt[tag].positions, stock[tag].positions)
                   for a, b in zip(p, q)) < 1.0


def test_extra_logos_and_none(model):
    layout = model.stock_layout() + [{"kind": "side_b", "x": -20, "z": 0, "size": 10, "angle": 90}]
    m = _meshes(model.build(layout))
    assert len(m["logb"].positions) == 12 and len(m["logb"].triangles) == 6
    xs = [p[0] / model.UNITS_PER_M for p in m["logb"].positions[8:]]
    assert abs(sum(xs) / 4 + 20) < 0.1                        # where asked
    # no small logo: one with no area, the big one stays
    m = _meshes(model.build(layout[:1]))
    assert len(m["loga"].triangles) == 8
    assert all(abs(c) < 1e-3 for p in m["logb"].positions for c in (p[0], p[2]))


def test_layout_is_cleaned(model):
    got = model.clean([{"kind": "nope"}, {"kind": "centre", "x": "3", "angle": 350, "size": 999}, "x"])
    assert got == [{"kind": "centre", "x": 3.0, "z": 0.0, "size": 60.0, "angle": -10.0}]
