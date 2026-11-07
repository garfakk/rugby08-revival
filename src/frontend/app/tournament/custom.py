"""
tournament/custom.py — Tournaments the user designs (Tools > Tournament editor).

The user never writes a template (stage ids, "pools:A1" refs, tie ids): the
editor edits a *design*, a plain description in the words of the screen, and
`compile_template` turns it into a normal template (formats.py) the engine
plays like any other. One file per tournament in user_data/custom_tournaments/
<id>.json: the compiled template, with the design kept under "design" so the
editor can open it again; formats.load_templates compiles the design afresh
when it reads the file, so a fix here reaches tournaments already made.

A design (DEFAULTS has every key):

  name, description
  format         "league"   one table, everyone plays everyone, optional play-offs
                 "groups"   pools, then a knockout bracket
                 "cup"      a straight knockout: the draw is the bracket
  teams_from     "pick" (the groups below) | "category" (a league of every club of a
                 data category, one edition per season; league format only)
  category       the category for "category"
  season         the squads' season ("2024": the 2023-24 squads)
  groups         [{"name": "Pool A", "teams": [team ids]}] — one for a league or a
                 cup (the cup's order is its draw), several for "groups"
  legs           1 (play each other once) | 2 (home and away)
  playoff_teams  league: 0 (none), 2 (a final), 4 (semis), 6 (top two get a bye), 8
  qualify        groups: teams per pool going through
  best_extra     groups: best of the next place across the pools also going through
                 (Heineken Cup: 5 pools, the winners + 3 best runners-up)
  seeding        how a bracket is drawn: "cross" (A1 v B2), "ranked" (best v worst),
                 "listed" (cup: pairs as listed in the draw)
  third_place    a bronze final
  venue          "home" (each team's ground) | "neutral" (the stadiums below, in turn)
  venues         stadium ids for neutral matches
  knockout_venue "home" (the better seed hosts) | "neutral"
  final_stadium  a stadium id for the final ("" = like the other knockout games)
  start, every   the first matchday ("MM-DD" in the season) and days between rounds
  points         {"preset": key of POINTS_PRESETS | "custom", win, draw, loss,
                  try_bonus: "none"|"4tries"|"3more", losing_bonus: margin (0 = none),
                  grand_slam: bonus points}
  tiebreakers    ordered keys of TIEBREAKERS
  discipline     key of DISCIPLINE_PRESETS
  knockout_draw  "tries_then_kicks" | "kicks" — a drawn knockout game
  match_type     the game's presentation (commentary, menus): gsv.match_type key
  branding       competition textures: a competition_branding choice key ("" = none)
  variant        competition squads and kits to use when a team has them ("" = none)
  trophy_lift    the winner lifts a trophy after the deciding match
  options        default match/squad settings (the wizard can change them)
"""
import copy
import json
import os
import random
import re

from shared.log import get_logger

log = get_logger(__name__)

SCHEMA = 1
ID_PREFIX = "my_"
FORMATS = ["league", "groups", "cup"]
FORMAT_LABELS = {"league": "League", "groups": "Pools + knockouts", "cup": "Knockout cup"}
FORMAT_BLURBS = {
    "league": "One table. Everyone plays everyone, then optional play-offs.",
    "groups": "Pools first, the best of each go through to a knockout bracket.",
    "cup": "Straight knockout from the first round. Lose and you're out.",
}
CUP_SIZES = [2, 4, 8, 16, 32]
LEAGUE_PLAYOFFS = [0, 2, 4, 6, 8]
PLAYOFF_LABELS = {0: "none", 2: "top 2: a final", 4: "top 4: semi-finals",
                  6: "top 6: top two get a bye", 8: "top 8: quarter-finals"}
SEEDINGS = {"cross": "pool winner v other pool's runner-up", "ranked": "best record v worst",
            "listed": "as listed in the draw"}

POINTS_PRESETS = {
    "bonus": {"label": "Bonus points (4-2-0, try and losing bonus)",
              "win": 4, "draw": 2, "loss": 0, "try_bonus": "4tries", "losing_bonus": 7, "grand_slam": 0},
    "bonus_french": {"label": "French bonus (3 more tries, lose by 5 or less)",
                     "win": 4, "draw": 2, "loss": 0, "try_bonus": "3more", "losing_bonus": 5,
                     "grand_slam": 0},
    "six_nations": {"label": "Six Nations (bonus points + Grand Slam 3)",
                    "win": 4, "draw": 2, "loss": 0, "try_bonus": "4tries", "losing_bonus": 7,
                    "grand_slam": 3},
    "classic": {"label": "Classic (2 for a win, 1 for a draw)",
                "win": 2, "draw": 1, "loss": 0, "try_bonus": "none", "losing_bonus": 0, "grand_slam": 0},
    "no_bonus": {"label": "4-2-0, no bonus points",
                 "win": 4, "draw": 2, "loss": 0, "try_bonus": "none", "losing_bonus": 0, "grand_slam": 0},
}
TRY_BONUS = {"none": "no try bonus", "4tries": "4 tries or more", "3more": "3 tries more than the opponent"}
TIEBREAKERS = {
    "head_to_head": "Head to head", "points_diff": "Points difference", "tries_diff": "Tries difference",
    "points_for": "Points scored", "tries_for": "Tries scored", "wins": "Matches won",
    "fewest_cards": "Fewest cards", "lots": "Drawing lots",
}
DISCIPLINE_PRESETS = {
    "standard": {"label": "Standard: red 1-3 games, 3 yellows = 1 game",
                 "rules": {"red_ban": [1, 3], "yellow_accumulation": 3, "yellow_ban": 1,
                           "citing_chance": 0.01}},
    "strict": {"label": "Strict: red 2-6 games, 2 yellows = 1 game, more citings",
               "rules": {"red_ban": [2, 6], "yellow_accumulation": 2, "yellow_ban": 1,
                         "citing_chance": 0.03}},
    "lenient": {"label": "Lenient: red 1-2 games, yellows never add up",
                "rules": {"red_ban": [1, 2], "yellow_accumulation": 0, "yellow_ban": 1,
                          "citing_chance": 0.0}},
}
KNOCKOUT_DRAWS = {"tries_then_kicks": "most tries, then a kicking contest",
                  "kicks": "a kicking contest"}
MATCH_TYPES = {"exhibition": "Standard", "world_cup": "World Cup", "six_nations": "Six Nations",
               "tri_nations": "Tri-Nations", "ten_nations": "Ten Nations", "european_cup": "European Cup",
               "super_14": "Super Rugby", "premiership": "Premiership"}

DEFAULTS = {
    "schema": SCHEMA, "name": "", "description": "", "format": "league",
    "teams_from": "pick", "category": "", "season": "",
    "groups": [{"name": "", "teams": []}],
    "legs": 1, "playoff_teams": 0, "qualify": 2, "best_extra": 0, "seeding": "cross",
    "third_place": False, "venue": "home", "venues": [], "knockout_venue": "home",
    "final_stadium": "", "start": "09-07", "every": 7,
    "points": dict(POINTS_PRESETS["bonus"], preset="bonus"),
    "tiebreakers": ["head_to_head", "points_diff", "tries_diff", "points_for", "tries_for",
                    "fewest_cards", "lots"],
    "discipline": "standard", "knockout_draw": "tries_then_kicks",
    "match_type": "exhibition", "branding": "", "variant": "", "trophy_lift": True,
    "options": {"halftime_length": "5m", "injuries": True, "fatigue": True, "suspensions": True},
}
DEFAULTS["points"].pop("label", None)


# ── the design ────────────────────────────────────────────────────────────

def new_design(fmt="league", **fields) -> dict:
    d = copy.deepcopy(DEFAULTS)
    d["format"] = fmt
    if fmt == "groups":
        d["groups"] = [{"name": "", "teams": []} for _ in range(4)]
    d.update(copy.deepcopy(fields))
    return normalize(d)


def normalize(design) -> dict:
    """Every key present and of the right kind; unknown values put back to
    the default, so a hand-edited file never breaks the editor."""
    d = copy.deepcopy(DEFAULTS)
    for k, v in (design or {}).items():
        if k in d or k == "id":
            d[k] = copy.deepcopy(v)
    if d["format"] not in FORMATS:
        d["format"] = "league"
    if d["teams_from"] not in ("pick", "category") or d["format"] != "league":
        d["teams_from"] = "pick"
    groups = [g for g in d["groups"] if isinstance(g, dict)] or [{"name": "", "teams": []}]
    d["groups"] = [{"name": str(g.get("name") or ""),
                    "teams": [str(t) for t in g.get("teams") or [] if t]} for g in groups]
    if d["format"] != "groups":
        # one table / one draw: everything in the first group
        d["groups"] = [{"name": d["groups"][0]["name"],
                        "teams": [t for g in d["groups"] for t in g["teams"]]}]
    d["legs"] = 2 if str(d["legs"]) == "2" else 1
    d["playoff_teams"] = _int(d["playoff_teams"], 0) if _int(d["playoff_teams"], 0) in LEAGUE_PLAYOFFS else 0
    d["qualify"] = max(1, min(8, _int(d["qualify"], 2)))
    d["best_extra"] = max(0, min(16, _int(d["best_extra"], 0)))
    d["every"] = max(1, min(60, _int(d["every"], 7)))
    if d["seeding"] not in SEEDINGS:
        d["seeding"] = "cross"
    if not re.fullmatch(r"\d\d-\d\d", str(d["start"])):
        d["start"] = DEFAULTS["start"]
    d["venues"] = [str(v) for v in d["venues"] or []]
    d["final_stadium"] = str(d["final_stadium"] or "")
    for key, allowed in (("venue", ("home", "neutral")), ("knockout_venue", ("home", "neutral")),
                         ("discipline", DISCIPLINE_PRESETS), ("knockout_draw", KNOCKOUT_DRAWS),
                         ("match_type", MATCH_TYPES)):
        if d[key] not in allowed:
            d[key] = DEFAULTS[key]
    pts = dict(DEFAULTS["points"], **(d["points"] if isinstance(d["points"], dict) else {}))
    if pts.get("preset") in POINTS_PRESETS:
        pts.update({k: v for k, v in POINTS_PRESETS[pts["preset"]].items() if k != "label"})
    else:
        pts["preset"] = "custom"
    for k in ("win", "draw", "loss", "losing_bonus", "grand_slam"):
        pts[k] = max(0, min(20, _int(pts.get(k), 0)))
    if pts.get("try_bonus") not in TRY_BONUS:
        pts["try_bonus"] = "none"
    d["points"] = pts
    tbs = [t for t in d["tiebreakers"] if t in TIEBREAKERS]
    d["tiebreakers"] = list(dict.fromkeys(tbs)) or list(DEFAULTS["tiebreakers"])
    d["options"] = dict(DEFAULTS["options"], **(d["options"] if isinstance(d["options"], dict) else {}))
    d["trophy_lift"] = bool(d["trophy_lift"])
    d["third_place"] = bool(d["third_place"])
    for k in ("name", "description", "category", "season", "branding", "variant"):
        d[k] = str(d[k] or "")
    return d


def _int(v, default):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def group_id(i) -> str:
    """"A".."Z", then "AA".. — a pool's id in the template."""
    s = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def group_name(design, i) -> str:
    g = design["groups"][i]
    if g.get("name"):
        return g["name"]
    if design["format"] == "league":
        return "Table"
    if design["format"] == "cup":
        return "The draw"
    return f"Pool {group_id(i)}"


def all_teams(design) -> list:
    return [t for g in design["groups"] for t in g["teams"]]


def qualifiers(design) -> int:
    """How many teams the knockout bracket starts with (0 = none)."""
    fmt = design["format"]
    if fmt == "league":
        return design["playoff_teams"]
    if fmt == "groups":
        return design["qualify"] * len(design["groups"]) + design["best_extra"]
    return len(all_teams(design))


def _power_of_two(n) -> bool:
    return n >= 2 and n & (n - 1) == 0


# ── compiling to a template ───────────────────────────────────────────────

ROUND_NAMES = {2: ("final", "Final", "final"), 4: ("sf", "Semi-final", "semi_final"),
               8: ("qf", "Quarter-final", "quarter_final")}


def _round_info(teams):
    if teams in ROUND_NAMES:
        return ROUND_NAMES[teams]
    return f"r{teams}", f"Round of {teams}", "none"


def bracket_order(n) -> list:
    """Seed numbers (1-based) in bracket order: 1 and 2 can only meet in the
    final, 1-4 in the semis... (8: 1 8 4 5 2 7 3 6)."""
    order = [1]
    size = 1
    while size < n:
        size *= 2
        order = [x for s in order for x in (s, size + 1 - s)]
    return order


def _first_round_pairs(design, seeds):
    """The first knockout round as [(ref, ref)], the better seed first (it
    hosts when the knockouts are at home grounds)."""
    q = len(seeds)
    if design["seeding"] == "listed":
        return [(seeds[i], seeds[i + 1]) for i in range(0, q - 1, 2)]
    order = bracket_order(q)
    return [(seeds[order[i] - 1], seeds[order[i + 1] - 1]) for i in range(0, q, 2)]


def _cross_pairs(stage_id, n_groups):
    """Pool winners against another pool's runner-up, A1 and B1 in opposite
    halves: (A1 B2) (C1 D2) (B1 A2) (D1 C2)."""
    ids = [group_id(i) for i in range(n_groups)]
    pairs_top, pairs_bottom = [], []
    for i in range(0, n_groups, 2):
        a, b = ids[i], ids[i + 1]
        pairs_top.append((f"{stage_id}:{a}1", f"{stage_id}:{b}2"))
        pairs_bottom.append((f"{stage_id}:{b}1", f"{stage_id}:{a}2"))
    return pairs_top + pairs_bottom


def _knockout_rounds(design, first_pairs, byes=()):
    """Rounds from the first one's pairs. `byes`: seeds waiting for the
    second round, matched with the first round's winners in order (the
    league's top-6 play-off)."""
    rounds = []
    pairs = list(first_pairs)
    teams = 2 * len(pairs) + len(byes)
    rid, name, sub = _round_info(2 * len(pairs)) if not byes else ("po", "Play-off", "none")
    rounds.append({"id": rid, "name": name, "match_subtype": sub, "ties": [list(p) for p in pairs]})
    winners = [f"W:{rid}{i + 1}" for i in range(len(pairs))]
    if byes:
        # the best seed meets the lowest surviving one
        winners = [x for pair in zip(byes, reversed(winners)) for x in pair]
        teams = len(winners)
    else:
        teams = len(winners)
    while teams >= 2:
        rid, name, sub = _round_info(teams)
        ties = [[winners[i], winners[i + 1]] for i in range(0, teams - 1, 2)]
        rounds.append({"id": rid, "name": name, "match_subtype": sub, "ties": ties})
        winners = [f"W:{rid}{i + 1}" for i in range(len(ties))]
        teams = len(winners)
        if teams == 1:
            break
    # name the rounds by what they are once the bracket is known
    final = rounds[-1]
    final["final"] = True
    if design["third_place"] and len(rounds) >= 2 and len(rounds[-2]["ties"]) == 2:
        sf = rounds[-2]["id"]
        rounds.insert(len(rounds) - 1, {"id": "bronze", "name": "Bronze final", "match_subtype": "none",
                                        "ties": [[f"L:{sf}1", f"L:{sf}2"]]})
    venue = design["knockout_venue"]
    for rnd in rounds:
        rnd["venue"] = venue
    if design["final_stadium"]:
        final["venue"] = "neutral"
        final["ties"] = [{"id": f"{final['id']}1", "teams": final["ties"][0],
                          "stadium": design["final_stadium"]}]
    return rounds


def compile_template(design, tid=None, _describe=True) -> dict:
    """The template (formats.py) the design describes."""
    d = normalize(design)
    tid = tid or d.get("id") or "my_tournament"
    p = d["points"]
    points = {"win": p["win"], "draw": p["draw"], "loss": p["loss"]}
    if p["try_bonus"] == "4tries":
        points["try_bonus"] = {"tries": 4}
    elif p["try_bonus"] == "3more":
        points["try_bonus"] = {"margin": 3}
    if p["losing_bonus"]:
        points["losing_bonus"] = {"margin": p["losing_bonus"]}
    if p["grand_slam"]:
        points["grand_slam"] = p["grand_slam"]
    tpl = {
        "id": tid, "custom": True, "name": d["name"] or "My tournament",
        "description": d["description"] or (describe_short(d) if _describe else ""),
        "order": 1, "match_type": d["match_type"], "venue": d["venue"],
        "venues": list(d["venues"]), "points": points, "tiebreakers": list(d["tiebreakers"]),
        "discipline": copy.deepcopy(DISCIPLINE_PRESETS[d["discipline"]]["rules"]),
        "knockout_draw": d["knockout_draw"], "trophy_lift": d["trophy_lift"],
        "default_options": dict(d["options"], difficulty="pro", cards=True, sim_variance=1.0,
                                injury_rate=1.0, injury_duration=1.0),
    }
    if d["branding"]:
        brand, _, season = d["branding"].partition(":")
        tpl["branding"] = brand
        if season:
            tpl["branding_season"] = season
    if d["variant"]:
        tpl["variant"] = d["variant"]
    calendar = {"start": d["start"], "every": d["every"]}
    later = {"every": d["every"]}
    stages, parts = [], {}
    fmt = d["format"]
    if fmt in ("league", "groups"):
        sid = "league" if fmt == "league" else "pools"
        names = {group_id(i): group_name(d, i) for i in range(len(d["groups"]))}
        stages.append({"id": sid, "name": "League" if fmt == "league" else "Pool stage",
                       "kind": "round_robin", "legs": d["legs"], "venue": d["venue"],
                       "match_subtype": "none" if fmt == "league" else "pool",
                       "group_names": names, "calendar": calendar})
        parts[sid] = {group_id(i): list(g["teams"]) for i, g in enumerate(d["groups"])}
        rounds = None
        if fmt == "league" and d["playoff_teams"] == 6:
            rounds = _knockout_rounds(d, [(f"{sid}:A3", f"{sid}:A6"), (f"{sid}:A4", f"{sid}:A5")],
                                      byes=(f"{sid}:A1", f"{sid}:A2"))
        elif fmt == "league" and d["playoff_teams"]:
            seeds = [f"{sid}:A{i}" for i in range(1, d["playoff_teams"] + 1)]
            rounds = _knockout_rounds(d, _first_round_pairs(dict(d, seeding="ranked"), seeds))
        elif fmt == "groups" and _power_of_two(qualifiers(d)):
            n = len(d["groups"])
            if d["seeding"] == "cross" and d["qualify"] == 2 and not d["best_extra"] and n % 2 == 0:
                pairs = _cross_pairs(sid, n)
            elif d["qualify"] == 1 and not d["best_extra"] and n == 2:
                pairs = [(f"{sid}:A1", f"{sid}:B1")]
            else:
                seeds = [f"{sid}:P{pos}#{k}" for pos in range(1, d["qualify"] + 1)
                         for k in range(1, n + 1)]
                seeds += [f"{sid}:P{d['qualify'] + 1}#{k}" for k in range(1, d["best_extra"] + 1)]
                pairs = _first_round_pairs(dict(d, seeding="ranked"), seeds)
            rounds = _knockout_rounds(d, pairs)
        if rounds:
            stages.append({"id": "knockouts", "name": "Play-offs" if fmt == "league" else "Knockouts",
                           "kind": "knockout", "calendar": later, "rounds": rounds})
    else:
        teams = all_teams(d)
        seeds = [f"cup:S{i}" for i in range(1, len(teams) + 1)]
        rounds = _knockout_rounds(d, _first_round_pairs(d, seeds)) if _power_of_two(len(teams)) else []
        stages.append({"id": "cup", "name": "Cup", "kind": "knockout", "calendar": calendar,
                       "rounds": rounds, "group_names": {"A": group_name(d, 0)}})
        parts["cup"] = {"A": list(teams)}
    tpl["stages"] = stages
    if d["teams_from"] == "category" and fmt == "league":
        tpl["category"] = d["category"]
    else:
        tpl["season"] = d["season"]
        tpl["participants"] = {"default": parts}
    tpl["design"] = dict(d, id=tid)
    return tpl


# ── reading it back for people ────────────────────────────────────────────

def round_robin_matches(n, legs) -> int:
    return n * (n - 1) // 2 * legs


def structure(design) -> list:
    """The tournament as blocks for the editor's diagram:
    [{"title", "detail", "matches", "kind"}], in playing order."""
    d = normalize(design)
    out = []
    fmt = d["format"]
    legs_txt = "home and away" if d["legs"] == 2 else "once"
    if fmt == "league":
        n = len(all_teams(d))
        out.append({"kind": "table", "title": "League",
                    "detail": f"{n} teams, everyone plays everyone {legs_txt}",
                    "matches": round_robin_matches(n, d["legs"])})
    elif fmt == "groups":
        sizes = [len(g["teams"]) for g in d["groups"]]
        same = len(set(sizes)) == 1
        size_txt = f"{len(sizes)} pools of {sizes[0]}" if same else f"{len(sizes)} pools"
        go = f"top {d['qualify']} go through" if d["qualify"] > 1 else "the winners go through"
        if d["best_extra"]:
            place = {1: "runners-up", 2: "thirds", 3: "fourths"}.get(d["qualify"], "next")
            go += f" + the {d['best_extra']} best {place}"
        out.append({"kind": "table", "title": "Pool stage",
                    "detail": f"{size_txt}, played {legs_txt}; {go}",
                    "matches": sum(round_robin_matches(s, d["legs"]) for s in sizes)})
    tpl = compile_template(d, "preview", _describe=False)
    for spec in tpl["stages"]:
        if spec.get("kind") != "knockout":
            continue
        for rnd in spec.get("rounds", []):
            ties = rnd.get("ties", [])
            detail = (f"{len(ties)} games" if len(ties) > 1 else "1 game")
            if rnd.get("final") and d["final_stadium"]:
                detail += " · at a set stadium"
            elif rnd.get("venue") == "neutral":
                detail += " · neutral ground"
            elif ties:
                detail += " · the better seed at home"
            out.append({"kind": "final" if rnd.get("final") else "round", "title": rnd["name"],
                        "detail": detail, "matches": len(ties)})
    return out


def match_count(design) -> int:
    return sum(b["matches"] for b in structure(design))


def matchdays(design) -> int:
    """Rounds of matches: the longest pool's rounds plus one per knockout round."""
    d = normalize(design)
    n = 0
    if d["format"] in ("league", "groups"):
        sizes = [len(g["teams"]) for g in d["groups"]] or [0]
        biggest = max(sizes)
        n += (biggest - 1 + biggest % 2) * d["legs"] if biggest >= 2 else 0
    n += sum(1 for b in structure(d) if b["kind"] in ("round", "final"))
    return n


def describe_short(design) -> str:
    d = normalize(design)
    teams = len(all_teams(d))
    blocks = [b["title"] for b in structure(d)]
    if d["teams_from"] == "category":
        lead = f"Every {d['category'] or 'club'} club"
    else:
        lead = f"{teams} teams" if teams else "No teams yet"
    return lead + ": " + " → ".join(dict.fromkeys(blocks)) + "." if blocks else lead + "."


# ── checking it ───────────────────────────────────────────────────────────

def problems(ds, design) -> list:
    """[(key, message, severity)] — "error" stops it being played, "warn"
    plays but not as designed, "info" is worth knowing. Keys name the
    editor's fields (custom.FIELD_TABS)."""
    from . import formats
    from .engine import pick_season, usable_squad
    d = normalize(design)
    out = []
    fmt = d["format"]
    if not d["name"].strip():
        out.append(("name", "Give the tournament a name", "error"))
    if d["teams_from"] == "category":
        if not d["category"]:
            out.append(("category", "Choose the category whose clubs play", "error"))
        else:
            seasons = {s for ss in ds.teams.values() for s, info in ss.items()
                       if isinstance(info, dict) and info.get("category") == d["category"]}
            if not seasons:
                out.append(("category", f"No club is in the category {d['category']}", "error"))
        return out + _bracket_problems(d)
    if not d["season"]:
        out.append(("season", "Choose the season whose squads play", "error"))
    teams = all_teams(d)
    seen = set()
    for t in teams:
        if t in seen:
            out.append(("groups", f"{_name(ds, t, d['season'])} is in the tournament twice", "error"))
        seen.add(t)
        if t not in ds.teams:
            out.append(("groups", f"Team {t} is not in the data", "error"))
            continue
        s = pick_season(ds.teams[t], d["season"] or "0")
        if len(usable_squad(ds, t, s)) < 22:
            out.append(("groups", f"{_name(ds, t, d['season'])} has no full squad for "
                                  f"{d['season'] or 'that season'}: it will be left out", "warn"))
    if fmt in ("league", "groups"):
        for i, g in enumerate(d["groups"]):
            if len(g["teams"]) < 2:
                where = "The league" if fmt == "league" else group_name(d, i)
                out.append(("groups", f"{where} needs at least 2 teams", "error"))
        if fmt == "groups":
            if len(d["groups"]) < 2:
                out.append(("groups", "Groups + knockouts needs at least 2 pools "
                                      "(or choose the League format)", "error"))
            sizes = [len(g["teams"]) for g in d["groups"]]
            if sizes and max(sizes) - min(sizes) > 1:
                out.append(("groups", "Pools differ by more than one team: the bigger pools "
                                      "play more games", "warn"))
    else:
        if len(teams) not in CUP_SIZES:
            nearest = min(CUP_SIZES, key=lambda n: (abs(n - len(teams)), n))
            out.append(("groups", f"A knockout cup needs 2, 4, 8, 16 or 32 teams "
                                  f"({len(teams)} now; {nearest} is closest)", "error"))
    out += _bracket_problems(d)
    if d["venue"] == "neutral" and not d["venues"] and fmt != "cup":
        out.append(("venues", "No stadium chosen for neutral games: every stadium is used in turn",
                    "info"))
    if not out or all(sev != "error" for _k, _m, sev in out):
        tpl = compile_template(d, "check")
        from .engine import default_participants
        parts = default_participants(tpl, d["season"])
        for msg in formats.problems(ds, tpl, d["season"], parts):
            if "usable players" not in msg:
                out.append(("format", msg, "error"))
    return out


def _bracket_problems(d) -> list:
    out = []
    fmt = d["format"]
    if fmt == "league":
        n = len(all_teams(d)) if d["teams_from"] == "pick" else None
        if n is not None and d["playoff_teams"] > n:
            out.append(("playoff_teams", f"Play-offs for {d['playoff_teams']} teams, "
                                         f"but only {n} play", "error"))
    elif fmt == "groups":
        sizes = [len(g["teams"]) for g in d["groups"]]
        q = qualifiers(d)
        if sizes and d["qualify"] > min(sizes):
            out.append(("qualify", f"{d['qualify']} teams go through from each pool, "
                                   f"but a pool has only {min(sizes)}", "error"))
        if d["best_extra"] and sizes and d["qualify"] + 1 > min(sizes):
            out.append(("best_extra", "Every pool needs a team in the place the best of the "
                                      "rest are taken from", "error"))
        if d["best_extra"] >= len(sizes) and d["best_extra"]:
            out.append(("best_extra", f"Only {len(sizes)} pools: at most {len(sizes) - 1} best "
                                      f"of the rest can go through", "error"))
        if not _power_of_two(q):
            out.append(("qualify", f"{q} teams go through: the knockouts need 2, 4, 8, 16 or 32 "
                                   f"({_qualify_hint(len(sizes))})", "error"))
    if d["seeding"] == "listed" and fmt != "cup":
        out.append(("seeding", "\"As listed\" only applies to a cup's draw", "info"))
    if d["third_place"] and qualifiers(d) < 4:
        out.append(("third_place", "A bronze final needs semi-finals", "info"))
    return out


def _qualify_hint(n_groups) -> str:
    combos = []
    for k in range(1, 5):
        for x in range(0, n_groups):
            if _power_of_two(k * n_groups + x):
                combos.append(f"top {k}" + (f" + {x} best" if x else ""))
                break
    return "with " + str(n_groups) + " pools: " + ", ".join(combos[:3]) if combos else "change the pools"


def _name(ds, tid, season):
    from .engine import pick_season
    seasons = ds.teams.get(tid) or {}
    if not seasons:
        return tid
    return seasons[pick_season(seasons, season or "0")].get("name", tid)


# ── helpers for the editor ────────────────────────────────────────────────

def known_variants(ds) -> list:
    """Every competition squad/kit variant id in the data, most used first."""
    from app import variants as V
    count = {}
    for seasons in ds.teams.values():
        for info in seasons.values():
            if not isinstance(info, dict):
                continue
            for vid in V.variant_ids(info):
                count[vid] = count.get(vid, 0) + 1
            for kit in (info.get("kits") or {}).values():
                for vid in V.kit_variant_ids(kit):
                    count[vid] = count.get(vid, 0) + 1
    return sorted(count, key=lambda v: (-count[v], v))


def categories(ds) -> list:
    """Data categories with clubs in them (not "International"), by size."""
    count = {}
    for seasons in ds.teams.values():
        for info in seasons.values():
            if isinstance(info, dict) and info.get("category"):
                c = str(info["category"])
                count[c] = count.get(c, 0) + 1
    return sorted(count, key=lambda c: (-count[c], c))


TEAM_SOURCES = {"internationals": "International teams", "clubs": "Club teams", "all": "Every team"}


def teams_from_source(ds, source, season) -> list:
    """Team ids with a full squad for `season`: internationals, clubs, every
    team, or one data category ("cat:Top 14")."""
    from .engine import pick_season, usable_squad
    out = []
    for tid, seasons in ds.teams.items():
        if not seasons:
            continue
        s = pick_season(seasons, season or "0")
        info = seasons.get(s) or {}
        kind = str(info.get("type") or "").lower()
        if source == "internationals" and kind != "international":
            continue
        if source == "clubs" and kind == "international":
            continue
        if source.startswith("cat:") and info.get("category") != source[4:]:
            continue
        if len(usable_squad(ds, tid, s)) >= 22:
            out.append(tid)
    return out


def auto_fill(ds, design, source, size, rng=None) -> dict:
    """The design with its groups topped up to `size` teams each (a league
    or cup: `size` in all) from `source`, at random, never a team twice."""
    d = normalize(design)
    rng = rng or random.Random()
    taken = set(all_teams(d))
    pool = [t for t in teams_from_source(ds, source, d["season"]) if t not in taken]
    rng.shuffle(pool)
    for g in d["groups"]:
        while len(g["teams"]) < size and pool:
            g["teams"].append(pool.pop())
    return d


def shuffle_draw(design, rng=None) -> dict:
    """The same teams, drawn again into the same pool sizes (or a new cup order)."""
    d = normalize(design)
    rng = rng or random.Random()
    teams = all_teams(d)
    rng.shuffle(teams)
    i = 0
    for g in d["groups"]:
        n = len(g["teams"])
        g["teams"] = teams[i:i + n]
        i += n
    return d


def set_group_count(design, n) -> dict:
    """`n` pools; teams of removed pools move to the others in turn."""
    d = normalize(design)
    n = max(1, min(16, int(n)))
    groups = d["groups"]
    if n > len(groups):
        groups += [{"name": "", "teams": []} for _ in range(n - len(groups))]
    elif n < len(groups):
        spare = [t for g in groups[n:] for t in g["teams"]]
        del groups[n:]
        for i, t in enumerate(spare):
            groups[i % n]["teams"].append(t)
    return d


def change_format(design, fmt) -> dict:
    """Same teams, another format: a league or cup puts every team in one
    list, "groups" deals them into 4 pools (or 2 for 8 teams or fewer)."""
    d = normalize(design)
    teams = all_teams(d)
    d["format"] = fmt
    if fmt == "groups":
        n = 2 if len(teams) <= 8 else 4
        d["groups"] = [{"name": "", "teams": teams[i::n]} for i in range(n)]
        if d["seeding"] == "listed":
            d["seeding"] = "cross"
    else:
        d["groups"] = [{"name": "", "teams": teams}]
        if fmt == "cup":
            d["seeding"] = "ranked" if d["seeding"] == "cross" else d["seeding"]
    if fmt != "league":
        d["teams_from"] = "pick"
    return normalize(d)


# ── starting points ───────────────────────────────────────────────────────

def _by_names(ds, names, season):
    from .engine import pick_season
    want = {n.lower(): n for n in names}
    found = {}
    for tid, seasons in ds.teams.items():
        if not seasons:
            continue
        info = seasons.get(pick_season(seasons, season or "0")) or {}
        name = str(info.get("name") or "").lower()
        if name in want and str(info.get("type") or "").lower() == "international":
            found.setdefault(name, tid)
    return [found[n.lower()] for n in names if n.lower() in found]


STARTERS = [
    ("blank", "Blank", "Start from nothing"),
    ("six_nations", "Six-team championship", "Six nations, once each, bonus points and a Grand Slam"),
    ("world_cup", "World Cup", "20 teams in 4 pools, quarter-finals, bronze final"),
    ("club_league", "Club league + play-offs", "12 clubs home and away, top 4 to the semi-finals"),
    ("champions_cup", "European cup", "5 pools of 4: the winners and the 3 best runners-up"),
    ("knockout", "Knockout cup", "8 teams, seeded, one game each round"),
]


def starter(ds, key, season) -> dict:
    """A design to start from (the teams the data has, the rest to fill)."""
    if key == "six_nations":
        teams = _by_names(ds, ["England", "France", "Ireland", "Italy", "Scotland", "Wales"], season)
        return new_design("league", name="My Six Nations", season=season, match_type="six_nations",
                          groups=[{"name": "", "teams": teams}], start="02-03",
                          points=dict(POINTS_PRESETS["six_nations"], preset="six_nations"))
    if key == "world_cup":
        return new_design("groups", name="My World Cup", season=season, match_type="world_cup",
                          groups=[{"name": "", "teams": []} for _ in range(4)], qualify=2,
                          seeding="cross", third_place=True, venue="neutral", knockout_venue="neutral",
                          start="09-08", tiebreakers=["head_to_head", "points_diff", "tries_diff",
                                                      "points_for", "tries_for", "lots"])
    if key == "club_league":
        return new_design("league", name="My club league", season=season, legs=2, playoff_teams=4,
                          match_type="premiership", start="09-15",
                          tiebreakers=["wins", "points_diff", "points_for", "head_to_head", "lots"])
    if key == "champions_cup":
        return new_design("groups", name="My European cup", season=season, match_type="european_cup",
                          groups=[{"name": "", "teams": []} for _ in range(5)], qualify=1,
                          best_extra=3, seeding="ranked", start="10-14", legs=2)
    if key == "knockout":
        return new_design("cup", name="My knockout cup", season=season, seeding="ranked",
                          start="05-04")
    return new_design("league", season=season)


def starter_fill_target(key) -> tuple:
    """(source, teams per group) the AUTO-FILL of a starter suggests."""
    return {"six_nations": ("internationals", 6), "world_cup": ("internationals", 5),
            "club_league": ("clubs", 12), "champions_cup": ("clubs", 4),
            "knockout": ("all", 8)}.get(key, ("all", 8))


# ── storage ───────────────────────────────────────────────────────────────

def directory() -> str:
    from shared.config import config
    return config.directory_custom_tournaments


def path_of(tid) -> str:
    return os.path.join(directory(), f"{tid}.json")


def load_all() -> dict:
    """{id: design} of every saved tournament, by name."""
    out = {}
    folder = directory()
    if not os.path.isdir(folder):
        return out
    for name in sorted(os.listdir(folder)):
        if not name.endswith(".json"):
            continue
        tid = name[:-5]
        try:
            with open(os.path.join(folder, name), "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError) as e:
            log.warning("custom tournament %s: %s", name, e)
            continue
        design = data.get("design") if isinstance(data, dict) else None
        if isinstance(design, dict):
            out[tid] = dict(normalize(design), id=tid)
    return dict(sorted(out.items(), key=lambda kv: kv[1]["name"].lower()))


def unique_id(name, taken) -> str:
    slug = re.sub(r"[^a-z0-9]+", "_", (name or "").lower()).strip("_")[:40] or "tournament"
    base = ID_PREFIX + slug
    tid, n = base, 2
    while tid in taken:
        tid, n = f"{base}_{n}", n + 1
    return tid


def save(design, tid=None) -> str:
    """Write the design (compiled) and return its id."""
    d = normalize(design)
    tid = tid or d.get("id") or unique_id(d["name"], set(load_all()))
    os.makedirs(directory(), exist_ok=True)
    tpl = compile_template(d, tid)
    tmp = path_of(tid) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(tpl, fh, indent=1, ensure_ascii=False)
    os.replace(tmp, path_of(tid))
    return tid


def delete(tid) -> None:
    try:
        os.remove(path_of(tid))
    except FileNotFoundError:
        pass


def template_from_file(tpl) -> dict:
    """A custom tournament's file as read by formats.load_templates: compiled
    again from its design (a fix in this module reaches old files)."""
    design = tpl.get("design") if isinstance(tpl, dict) else None
    if not isinstance(design, dict):
        return tpl
    try:
        return compile_template(design, tpl.get("id"))
    except Exception as e:      # never lose a tournament to a compile bug
        log.warning("custom tournament %s: %s", tpl.get("id"), e)
        return tpl
