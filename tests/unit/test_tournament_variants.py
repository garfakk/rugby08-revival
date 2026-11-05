"""Which squad and kit versions a tournament plays: the template's own id
first (a variant named after the edition, e.g. rwc_2023), then its
"variant"(s) (the competition's, e.g. world_cup), else the defaults."""
import copy

from app.tournament import bridge, engine
from app.tournament.session import TournamentSession

TEAMS = ["10002", "10001", "1015", "1010"]
RWC = {
    "id": "rwc_2023", "name": "Mini RWC", "venue": "neutral", "season": "2024",
    "match_type": "world_cup", "variant": "world_cup",
    "stages": [{"id": "pools", "name": "Pool", "kind": "round_robin", "legs": 1}],
    "participants": {"default": {"pools": {"A": TEAMS}}},
}


def test_choices_most_specific_first():
    assert engine.variant_choices(RWC, "10001") == ["rwc_2023", "world_cup"]
    assert engine.variant_choices(dict(RWC, variant=["rwc", "world_cup"]), "1") == \
        ["rwc_2023", "rwc", "world_cup"]
    assert engine.variant_choices({"id": "six_nations_2024"}, "1") == ["six_nations_2024"]
    # a per-team exception replaces the lot
    tpl = dict(RWC, team_variants={"1004": "", "1015": ["springboks"]})
    assert engine.variant_choices(tpl, "1004") == []
    assert engine.variant_choices(tpl, "1015") == ["springboks"]


def test_first_one_the_team_has():
    assert engine.first_variant(["rwc_2023", "world_cup"], ["world_cup"]) == "world_cup"
    assert engine.first_variant(["rwc_2023", "world_cup"], ["world_cup", "rwc_2023"]) == "rwc_2023"
    assert engine.first_variant(["rwc_2023"], ["six_nations"]) == ""
    kit = {"frontKitFile": "a.png", "variants": {"rwc_2023": {"frontKitFile": "b.png"}}}
    assert engine.kit_variant(RWC, "10001", kit) == "rwc_2023"
    assert engine.kit_variant({"id": "rwc_2019", "variant": "world_cup"}, "10001", kit) == ""


def test_an_edition_squad_beats_the_competition_one(ds):
    info = ds.teams["10001"]["2024"]
    info["variant"]["rwc_2023"] = {"label": "RWC 2023 (edition)", "players": info["players"][:30]}
    assert engine.entry_variant(ds, RWC, "10001", "2024") == "rwc_2023"
    assert engine.entry_variant(ds, dict(RWC, id="rwc_2027"), "10001", "2024") == "world_cup"


def test_a_tournament_match_wears_the_patched_kit(ds, data_dir):
    """France 2024 (fixture): a "world_cup" squad, "rwc_2023" kit patches —
    both reach the match."""
    session = TournamentSession.new(ds, copy.deepcopy(RWC), "2024", humans=["10001"], seed=3)
    assert session.t.teams["10001"].variant == "world_cup"
    f = next(f for f in session.t.fixtures if "10001" in (f.home, f.away))
    cfg = bridge.to_match_config(ds, session.t, f)
    slot = cfg.home if f.home == "10001" else cfg.away
    assert slot.variant == "world_cup" and slot.kit_variant == "rwc_2023"
    kit = ds.teams["10001"]["2024"]["kits"][slot.kit_key(ds)]
    assert slot.kit(ds)["frontKitFile"] == kit["variants"]["rwc_2023"]["frontKitFile"]
