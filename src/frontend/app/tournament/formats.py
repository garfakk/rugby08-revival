"""
tournament/formats.py — Competition templates.

A template is a JSON file describing a competition's structure and rules:

  {"id": "world_cup", "name": "World Cup",
   "match_type": "world_cup",          # game commentary flag (gsv.match_type)
   "branding": "default",              # competition id (data/competitions/<competition>/<competition>.json)
   "venue": "neutral" | "home",        # default for every stage
   "venues": ["70", ...],              # neutral venue rotation (stadium ids)
   "points": {...}, "tiebreakers": [...], "discipline": {...},
   "knockout_draw": "tries_then_kicks" | "kicks",
   "default_options": {...},
   "stages": [
     {"id": "pools", "name": "Pool stage", "kind": "round_robin", "legs": 1,
      "group_names": {"A": "Pool A"}},
     {"id": "ko", "name": "Knockouts", "kind": "knockout", "rounds": [
        {"id": "qf", "name": "Quarter-final", "match_subtype": "quarter_final",
         "ties": [["pools:A1", "pools:B2"], ...]},
        {"id": "final", "name": "Final", "match_subtype": "final", "final": true,
         "ties": [["W:sf1", "W:sf2"]]}]}],
   "participants": {"default": {"pools": {"A": ["1010", ...]}}, "2024": {...}},
   "season": "2024",                   # optional: the season the wizard preselects
   "variant": "world_cup",             # optional: competition squads/kits (app/variants.py)
   "team_variants": {"1004": ""}}      # optional per-team exception ("" = default)

Every team plays its season's `variant` squad when it has one, else its
default — so the generic world_cup template with season 2024 plays the RWC
2023 squads, with 2028 the RWC 2027 ones. Independently, each kit worn is
that kit's `variant` version (a tournament patch) when the kit has one.

Built-in templates ship as flat files in assets/data/competitions/; a data
pack can add or override them (same id) inside its competition definitions,
<mod data>/competitions/<competition>/<competition>.json — under "template"
for a seasonless competition, under "seasons" -> <year> -> "template" for a
seasonal one (see tournament_data_loader.py).
"""
import json
import os
import re

from shared.app_paths import assets_directory
from shared.log import get_logger

log = get_logger(__name__)


def _dirs():
    from shared.config import config
    return [os.path.join(assets_directory(), "data", "competitions"),
            os.path.join(config.mod_data_directory, "competitions")]


def _read(path):
    with open(path, "r", encoding="utf-8") as fh:
        return json.loads(re.sub(r",\s*([}\]])", r"\1", fh.read()))


def _templates_in(d):
    """(source name, template) for every template in directory `d`: its own
    .json files, then those in each <competition>/<competition>.json."""
    for name in sorted(os.listdir(d)):
        path = os.path.join(d, name)
        try:
            if name.endswith(".json") and os.path.isfile(path):
                tpl = _read(path)
                tpl.setdefault("id", os.path.splitext(name)[0])
                yield name, tpl
                continue
            root_json = os.path.join(path, f"{name}.json")
            if not os.path.isfile(root_json):
                continue
            definition = _read(root_json)
            entries = (definition.get("seasons", {}).items() if definition.get("seasonal")
                       else [("", definition)])
            for season, entry in entries:
                tpl = entry.get("template")
                if tpl:
                    tpl.setdefault("branding", str(definition.get("id", name)))
                    if season:
                        tpl.setdefault("branding_season", str(season))
                    tpl.setdefault("id", name)
                    yield name, tpl
        except Exception as e:
            log.error("competition template %s: %s", name, e)


def load_templates(dirs=None) -> dict:
    """{id: template}, later directories overriding earlier ones."""
    out = {}
    for d in dirs or _dirs():
        if not os.path.isdir(d):
            continue
        for _, tpl in _templates_in(d):
            out[tpl["id"]] = tpl
    return dict(sorted(out.items(), key=lambda kv: (kv[1].get("order", 100), kv[1].get("name", kv[0]))))


def stage_team_count(template, participants) -> int:
    return sum(len(teams) for groups in participants.values() for teams in groups.values())


def problems(ds, template, season, participants) -> list:
    """What would stop this template running with these participants."""
    from .engine import pick_season, usable_squad, entry_variant
    found = []
    seen = set()
    rr = [s for s in template.get("stages", []) if s.get("kind", "round_robin") == "round_robin"]
    if not rr:
        found.append("template has no round-robin stage to enter teams into")
    for spec in rr:
        groups = participants.get(spec["id"], {})
        if not groups:
            found.append(f"{spec.get('name', spec['id'])}: no teams")
        for gid, teams in groups.items():
            if len(teams) < 2:
                found.append(f"{spec.get('name', spec['id'])} {gid}: fewer than 2 teams")
            for tid in teams:
                if tid in seen:
                    found.append(f"team {tid} entered twice")
                seen.add(tid)
                if tid not in ds.teams:
                    found.append(f"team {tid} is not in the data")
                    continue
                s = pick_season(ds.teams[tid], str(season))
                variant = entry_variant(ds, template, tid, s)
                n = len(usable_squad(ds, tid, s, variant))
                if n < 22:
                    name = ds.team_season(tid, s, variant).get("name", tid)
                    squad = f" ({variant.replace('_', ' ')} squad)" if variant else ""
                    found.append(f"{name}{squad}: only {n} usable players (22 needed)")
    # refs must point at something that exists
    stage_ids = {s["id"]: s for s in template.get("stages", [])}
    tie_ids = set()
    for spec in template.get("stages", []):
        if spec.get("kind") != "knockout":
            continue
        for rnd in spec.get("rounds", []):
            for i, tie in enumerate(rnd.get("ties", [])):
                refs = tie.get("teams") if isinstance(tie, dict) else tie
                for ref in refs:
                    if ref.startswith(("W:", "L:")):
                        if ref[2:] not in tie_ids:
                            found.append(f"{ref}: refers to a later or unknown tie")
                    elif ":" in ref:
                        sid, rest = ref.split(":", 1)
                        if sid not in stage_ids:
                            found.append(f"{ref}: unknown stage")
                        elif not rest.startswith("P"):
                            gid = rest.rstrip("0123456789")
                            if gid not in participants.get(sid, {}):
                                found.append(f"{ref}: unknown group")
                tie_ids.add(tie.get("id") if isinstance(tie, dict) else f"{rnd['id']}{i + 1}")
    return found
