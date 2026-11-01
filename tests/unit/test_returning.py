"""A player back from injury is nudged back into his old slot, not forced."""
import copy
from app.tournament import selection, returning
from app.tournament.effects import component


def _start(t, tid):
    return selection.auto_select(t, tid)


def test_nudge_only_for_remembered_slot(ds):
    from app.tournament.effects import MatchContext
    class P:  # minimal stand-in
        components = {"returning": {"slot": 3}}
    assert returning._weight(None, P, MatchContext(fixture=None, team_id="x", position="lock", slot=4)) == returning.REGAIN_NUDGE
    assert returning._weight(None, P, MatchContext(fixture=None, team_id="x", position="lock", slot=5)) == 1.0
    P.components = {}
    assert returning._weight(None, P, MatchContext(fixture=None, team_id="x", position="lock", slot=4)) == 1.0


def _mini(ds):
    from test_tournament import new, fixtures
    return new(ds), fixtures


def test_injured_starter_gets_a_nudge_back_but_a_better_man_keeps_the_shirt(ds):
    from app.tournament import engine, manual
    from app.tournament.model import Condition
    t, fixtures = _mini(ds)
    f = fixtures(t, "pools")[0]
    xv = t.teams[f.home].selection["players"]
    hurt = xv[3]
    result = manual.build_result(t, f, [{"pid": hurt, "kind": "injury", "type": "ankle sprain",
                                         "matches": 1}], [])
    engine.record_result(t, f, result)
    assert t.players[hurt].components["returning"]["slot"] == 3

    # fit again: back in the same shirt unless somebody is clearly better
    t.players[hurt].conditions = []
    t.players[hurt].components.pop("fatigue", None)      # rested, as after the weeks out
    again = selection.auto_select(t, f.home)["players"]
    assert again[3] == hurt

    # the nudge is small: make the stand-in far better and he keeps it
    pl = t.players[hurt]
    for k in ("tackling", "strength", "rucking", "defense", "attack", "handling"):
        if k in pl.base:
            pl.base[k] = 20
    assert selection.auto_select(t, f.home)["players"][3] != hurt

    # and playing again clears the memory
    pl.components["returning"]["slot"] = 3
    from app.tournament.model import PlayerLine
    returning._forget(t, f, type("R", (), {"home": type("S", (), {"players": [PlayerLine(pid=hurt)]})(),
                                           "away": type("S", (), {"players": []})()})(), None)
    assert "slot" not in pl.components["returning"]

