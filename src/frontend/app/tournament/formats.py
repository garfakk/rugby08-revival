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
   "season": "2024",                   # a historical edition: the season its squads are for
   "category": "Top 14",               # a club league: one edition per season of the data,
                                       # with the clubs of that category that season
                                       # (or a list of categories, e.g. a league's old names)
   "from_season": "2022", "to_season": "2019",   # optional: the seasons of the data it covers
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


# ── editions: what the wizard offers ──────────────────────────────────────

class Edition:
    """One playable edition of a competition: the template to create the
    tournament from, its season and its draw.

      id            the template id, or "<template id>@<season>" for a season
                    of a club league built from the data
      family        the competition it belongs to (family_of)
      label         "2015" (a real edition), "2023-24" (a club season)
      missing       team ids of the real draw the data doesn't have: they
                    are left out, never replaced
    """

    def __init__(self, id, family, template, season, participants, label, missing=()):
        self.id, self.family, self.template = id, family, template
        self.season, self.participants, self.label = str(season), participants, label
        self.missing = list(missing)

    def team_count(self) -> int:
        return sum(len(ts) for groups in self.participants.values() for ts in groups.values())


def family_of(tid, tpl) -> str:
    """The competition a template belongs to: its branding's (the RWC 2015
    template is a "world_cup"), else its own id."""
    return str(tpl.get("branding") or tid)


def is_real_edition(tpl) -> bool:
    return bool(tpl.get("season") or tpl.get("branding_season"))


def _short_season(season) -> str:
    """"2024" -> "2023-24"."""
    try:
        year = int(season)
    except (TypeError, ValueError):
        return str(season)
    return f"{year - 1}-{str(year)[2:]}"


def needed_per_group(template) -> int:
    """The fewest teams a pool needs for the template's knockout refs
    ("league:A6" needs six) — two at least."""
    need = 2
    for spec in template.get("stages", []):
        for rnd in spec.get("rounds", []) if spec.get("kind") == "knockout" else []:
            for tie in rnd.get("ties", []):
                for ref in (tie.get("teams") if isinstance(tie, dict) else tie) or []:
                    rest = ref.split(":", 1)[1] if ":" in ref and not ref.startswith(("W:", "L:")) else ""
                    if rest and not rest.startswith("P"):
                        pos = rest[len(rest.rstrip("0123456789")):]
                        need = max(need, int(pos) if pos else 0)
    return need


def playable_teams(ds, template, season) -> set:
    """Team ids with a squad of 22 usable players for `season` (their
    nearest one) in this template's variant."""
    from .engine import entry_variant, pick_season, usable_squad
    out = set()
    for tid, seasons in ds.teams.items():
        s = pick_season(seasons, str(season))
        if len(usable_squad(ds, tid, s, entry_variant(ds, template, tid, s))) >= 22:
            out.add(tid)
    return out


def _real_edition(ds, tid, tpl, usable_for):
    from .engine import default_participants
    season = str(tpl.get("season") or "")
    usable = usable_for(tpl, season)
    parts = default_participants(tpl, season)
    missing = sorted({t for groups in parts.values() for ts in groups.values() for t in ts} - usable)
    parts = {sid: {gid: [t for t in ts if t in usable] for gid, ts in groups.items()}
             for sid, groups in parts.items()}
    need = needed_per_group(tpl)
    if not parts or any(len(ts) < need for groups in parts.values() for ts in groups.values()):
        return None
    return Edition(tid, family_of(tid, tpl), tpl, season, parts,
                   str(tpl.get("branding_season") or season or tpl.get("name", tid)), missing)


def _league_editions(ds, tid, tpl, usable_for):
    """One edition per season the data has enough clubs of the template's
    "category" for (their category that very season, a full squad)."""
    import copy
    cats = tpl["category"] if isinstance(tpl["category"], (list, tuple)) else [tpl["category"]]
    cats = {str(c) for c in cats}
    first, last = str(tpl.get("from_season") or ""), str(tpl.get("to_season") or "")
    rr = next((s for s in tpl.get("stages", []) if s.get("kind", "round_robin") == "round_robin"), None)
    if not rr:
        return []
    gid = next(iter(rr.get("group_names") or {"A": ""}))
    need = needed_per_group(tpl)
    seasons = sorted({s for ss in ds.teams.values() for s in ss}, reverse=True)
    out = []
    for season in seasons:
        if (first and season < first) or (last and season > last):
            continue
        clubs = [t for t, ss in ds.teams.items()
                 if isinstance(ss.get(season), dict) and ss[season].get("category") in cats]
        if len(clubs) < need:
            continue
        edition = copy.deepcopy(tpl)
        edition["season"] = season
        edition["name"] = f"{tpl.get('name', tid)} {_short_season(season)}"
        usable = usable_for(edition, season)
        short = sorted(t for t in clubs if t not in usable)        # no full squad that season
        clubs = sorted((t for t in clubs if t in usable),
                       key=lambda t: str(ds.teams[t][season].get("name", t)).lower())
        if len(clubs) < need:
            continue
        out.append(Edition(f"{tid}@{season}", family_of(tid, tpl), edition, season,
                           {rr["id"]: {gid: clubs}}, _short_season(season), short))
    return out


def editions(ds, templates=None, default_season="") -> dict:
    """{family: [Edition]} of every competition that can be played with the
    data, newest edition first: a historical template's real draw (less
    the teams the data doesn't have), each season of a club league
    ("category"), or — for a competition with neither — a seasonless
    template whose whole draw is in the data. Nothing is ever filled in
    with another team."""
    from .engine import default_participants
    templates = load_templates() if templates is None else templates
    cache = {}

    def usable_for(tpl, season):
        key = (str(tpl.get("variant") or ""), repr(sorted((tpl.get("team_variants") or {}).items())), season)
        if key not in cache:
            cache[key] = playable_teams(ds, tpl, season)
        return cache[key]

    out = {}
    open_templates = []
    for tid, tpl in templates.items():
        fam = family_of(tid, tpl)
        if is_real_edition(tpl):
            e = _real_edition(ds, tid, tpl, usable_for)
            if e:
                out.setdefault(fam, []).append(e)
        elif tpl.get("category"):
            out.setdefault(fam, []).extend(_league_editions(ds, tid, tpl, usable_for))
        else:
            open_templates.append((tid, tpl))
    for tid, tpl in open_templates:
        fam = family_of(tid, tpl)
        if out.get(fam):
            continue
        parts = default_participants(tpl, default_season)
        teams = {t for groups in parts.values() for ts in groups.values() for t in ts}
        if teams and teams <= usable_for(tpl, default_season):
            out[fam] = [Edition(tid, fam, tpl, default_season, parts, "")]
    for eds in out.values():
        eds.sort(key=lambda e: e.season, reverse=True)
    order = {family_of(tid, tpl): (tpl.get("order", 100), i) for i, (tid, tpl) in enumerate(templates.items())}
    return {fam: eds for fam, eds in sorted(out.items(), key=lambda kv: order.get(kv[0], (100, 0))) if eds}
