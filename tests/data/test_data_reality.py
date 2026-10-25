"""Reality mode on the real data: every edition with real results, played
with nobody managed, ends exactly as it really did (the champion, the table,
the pool places), and every real event names a player of the team's squad."""
import copy

import pytest

from app.tournament import engine, formats, reality, standings
from conftest import REAL_DATA, point_config

pytestmark = pytest.mark.data


@pytest.fixture(scope="module")
def real_ds(real_raw):
    from app.state import DataStore
    return DataStore(copy.deepcopy(real_raw))


@pytest.fixture(scope="module")
def templates():
    mp = pytest.MonkeyPatch()
    point_config(mp, data_dir=REAL_DATA)
    try:
        return formats.load_templates()
    finally:
        mp.undo()


def _editions(templates, ds=None):
    return sorted(tid for tid, tpl in templates.items()
                  if reality.available(tpl, known_teams=ds.teams if ds else None)[0])


def test_editions_with_real_results_are_offered(templates):
    offered = _editions(templates)
    assert any(t.startswith("rwc_") for t in offered) and len(offered) >= 15
    for tid, tpl in templates.items():
        if tid not in offered:
            assert not any("real_score" in str(s) for s in tpl.get("stages", [])) or \
                reality.available(tpl)[1], tid


@pytest.mark.parametrize("tid", ["rwc_2007", "rwc_2015", "rwc_2019", "rwc_2023", "six_nations_2008",
                                 "six_nations_2015", "six_nations_2023", "six_nations_2026"])
def test_reality_replays_history(real_ds, templates, tid):
    tpl = templates.get(tid)
    if tpl is None:
        pytest.skip(f"{tid} not in the data")
    ok, why = reality.available(tpl, known_teams=real_ds.teams)
    if not ok:
        pytest.skip(f"{tid}: {why}")
    t = engine.create_tournament(real_ds, copy.deepcopy(tpl), str(tpl.get("season") or ""),
                                 options={"reality": True}, seed=3)
    engine.simulate_to_end(t)
    real = [f for f in t.fixtures if f.result and f.result.source == "real"]
    assert len(real) == len(t.fixtures), [f.id for f in t.fixtures if f.result.source != "real"]
    for f in real:
        e = t.components["reality"][f.id]
        assert [f.result.home.points, f.result.away.points] == e["score"], f.id
    hist = tpl.get("history") or {}
    if hist.get("champion"):
        assert t.champion == hist["champion"]
    if hist.get("table"):
        stage = t.stages[0]
        assert [r.team_id for r in standings.group_table(t, stage, stage.groups[0])][:2] == hist["table"][:2]


def test_real_events_name_squad_players(real_ds, templates):
    missing = []
    for tid in _editions(templates, real_ds):
        tpl = templates[tid]
        if "real_events" not in str(tpl.get("stages")):
            continue
        t = engine.create_tournament(real_ds, copy.deepcopy(tpl), str(tpl.get("season") or ""),
                                     options={"reality": True}, seed=3)
        for fid, e in t.components["reality"].items():
            for ev in e["events"]:
                if not reality.find_player(t, str(ev.get("team")), ev):
                    missing.append((tid, fid, ev.get("team"), ev.get("player")))
    assert not missing
