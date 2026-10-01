"""
app/roster_import/plan.py — turn a game roster into mod JSON, selectively
===========================================================================
Nothing here writes until `apply_import`. The wizard builds an `ImportPlan`
(which teams, how each maps to an existing team, what to do with each
player, which field groups), shows `summary()` for review, then applies it.

Player matching is by name: the game's roster ids have nothing to do with
the mod's player ids. Every match is only a suggestion the user reviews.
"""
import calendar
import copy
import os
import re

from app import team_ops as T
from app.game_data import (
    ATTRIBUTES, ROLE_KEYS, new_player_season, new_team_season, save_team, _load_json,
    _write_json, SaveError, STARTING_XV,
)
from app.player_ops import allocate_player_id
from app.roster_import import names as N
from app.roster_import.reader import TENDENCIES, SKILL_BITS_1, SKILL_BITS_2

RATING_KEYS = [k for k, _ in ATTRIBUTES]
SKILL_KEYS = [f"ss_{k}" for k in SKILL_BITS_1 + SKILL_BITS_2]
EXTRA_RATING_KEYS = ["crashball", "gap_defense"]

# Field groups the user can tick, in wizard order: (key, label, default on)
GROUPS = [
    ("identity", "Identity — in-game name, birthdate, commentary id", True),
    ("positions", "Positions", True),
    ("physical", "Height, weight, stronger foot", True),
    ("ratings", "The 24 ratings", True),
    ("extras", "Extras — crashball, gap defence, tendency, special skills", True),
    ("appearance", "Appearance — skin tone, tapes, socks, gloves, boot style", True),
    ("nationality", "Nationality", True),
    ("faces", "Head — the game's stock face number", True),
    ("squads", "Squads, roles and set plays", True),
]

CREATE, UPDATE, SKIP = "create", "update", "skip"
MIN_HEIGHT = 151                       # the roster write fails below this


def norm_name(name):
    return N.fold((name or "").replace("^", ""))


def default_birth_offset(kind, season):
    """Patches keep player ages relative to 2007 by shifting birth years
    (TRF 2017 stores Dupont, born 1996, as 1986). A raw stock roster is
    exact. Only a fallback — `estimate_birth_offset` prefers the evidence."""
    try:
        year = int(season)
    except (TypeError, ValueError):
        return 0
    return max(0, year - 2007) if kind == "ros" else 0


# ── matching ─────────────────────────────────────────────────────────────
def build_name_index(players):
    """last word of the surname -> [pid]; every spelling a record answers to."""
    index = {}
    for pid, record in players.items():
        for parsed in N.record_names(record):
            if parsed.last_token:
                index.setdefault(parsed.last_token, []).append(pid)
    return {k: list(dict.fromkeys(v)) for k, v in index.items()}


def latest_block(record):
    stats = record.get("stats") or {}
    return stats[sorted(stats)[-1]] if stats else {}


def _birth_parts(text):
    m = re.match(r"^\s*(\d{4})[/-](\d{1,2})[/-](\d{1,2})", text or "")
    return tuple(int(x) for x in m.groups()) if m else None


def _mod_real_date(text):
    """(y, m, d) unless the mod only knows the year (stored as yyyy/01/01)."""
    parts = _birth_parts(text)
    return parts if parts and (parts[1], parts[2]) != (1, 1) else None


def initial_mismatch_ok(rp, record, season):
    """Different initials mean a different player, unless the main position
    is the same and the birth year fits the season shift (target season -
    2006, +/- 1 year)."""
    try:
        year = rp["birth"][0] + int(season) - 2006
    except (TypeError, ValueError):
        return False
    born = _birth_parts(record.get("birthdate"))
    block = latest_block(record)
    return bool(born and abs(born[0] - year) <= 1 and rp["positions"][0]
                and block.get("position1") == rp["positions"][0])


def score_candidate(rp, pid, record, birth_offset, season=None):
    """-> (score, [reasons], conflict). Name decides who is a candidate;
    birth date, positions, nationality and build separate namesakes."""
    name_s, why = N.name_score(rp["name"], record, loose=season is not None)
    if name_s < 2:
        return -1, [], True
    if why == "initial differs" and not initial_mismatch_ok(rp, record, season):
        return -1, [], True
    score, reasons, conflict = name_s, [why], False
    year = rp["birth"][0] + birth_offset
    born = _birth_parts(record.get("birthdate"))
    if born:
        if born[0] == year:
            score += 3
            reasons.append("same birth year")
            if _mod_real_date(record.get("birthdate")) and (born[1], born[2]) == rp["birth"][1:]:
                score += 2
                reasons.append("same birth date")
        elif abs(born[0] - year) == 1:
            score += 1
            reasons.append("birth year ±1")
        else:
            score -= 3
            conflict = True
            reasons.append(f"born {born[0]}, file says {year}")
    block = latest_block(record)
    mod_pos = {block.get(k) for k in ("position1", "position2", "position3")} - {"", None}
    if mod_pos and rp["positions"][0]:
        if block.get("position1") == rp["positions"][0]:
            score += 1
            reasons.append("same position")
        elif mod_pos & set(rp["positions"]):
            reasons.append("shared position")
        else:
            score -= 1
            reasons.append("different position")
    if rp["nationalities"] and block.get("nationality") in rp["nationalities"]:
        score += 1
        reasons.append("same nationality")
    try:
        if rp["height_cm"] and abs(int(block.get("height")) - rp["height_cm"]) <= 3:
            score += 1
    except (TypeError, ValueError):
        pass
    return score, reasons, conflict


def rank_candidates(rp, players, index, birth_offset, season=None):
    """[(pid, score, reasons, conflict)] best first."""
    parsed = N.parse_name(rp["name"])
    pids = index.get(parsed.last_token, [])
    ranked = []
    for pid in pids:
        score, reasons, conflict = score_candidate(rp, pid, players[pid], birth_offset, season)
        if score >= 0:
            ranked.append((pid, score, reasons, conflict))
    ranked.sort(key=lambda r: -r[1])
    return ranked


def match_player(rp, players, index, birth_offset, season=None):
    """-> (decision, pid or None, candidates, confidence, reasons)
    confidence: "exact" (one clear winner, nothing disagrees), "check"
    (ambiguous, thin evidence or a disagreement), "none"."""
    ranked = rank_candidates(rp, players, index, birth_offset, season)
    if not ranked:
        return CREATE, None, [], "none", []
    best = ranked[0]
    pid, score, reasons, conflict = best
    clear = len(ranked) == 1 or score - ranked[1][1] >= 2
    strong = score >= 5 and not conflict
    return UPDATE, pid, [r[0] for r in ranked], ("exact" if strong and clear else "check"), reasons


def estimate_birth_offset(roster, players, index):
    """Year shift between the file and the mod, read from players both agree
    on by name. -> (offset, samples) or (None, 0) without a clear majority."""
    diffs = []
    for rp in roster["players"].values():
        ranked = rank_candidates(rp, players, index, 0)
        pool = [r for r in ranked if any("surname + initial" in x for x in r[2])] or []
        if len(pool) != 1:
            continue
        born = _birth_parts(players[pool[0][0]].get("birthdate"))
        if born and rp["birth"][0]:
            diffs.append(born[0] - rp["birth"][0])
    if len(diffs) < 4:
        return None, len(diffs)
    mode = max(set(diffs), key=diffs.count)
    if diffs.count(mode) / len(diffs) < 0.5 or not 0 <= mode <= 40:
        return None, len(diffs)
    return mode, len(diffs)


# ── things that cannot be imported as they are ───────────────────────────
# kind -> (title, explanation, [(option key, label)]); the first option is
# the default. The wizard asks the user; apply_import obeys the answer.
ISSUES = {
    "name_long": ("Names too long for the game",
                  "The game cuts in-game names at 14 bytes.",
                  [("truncate", "Cut the surname to fit  (A. Dupontelon)"),
                   ("tight", "Drop the space after the initial first  (A.Dupontelon)"),
                   ("keep", "Keep the full name anyway")]),
    "face_custom": ("Players who already have a custom head",
                    "The file has a stock face number, but the mod player uses a head file.",
                    [("keep", "Keep the custom head"),
                     ("replace", "Replace it with the stock face from the file")]),
    "face_unknown": ("Face number that is not a known stock face",
                     "The face id is 0 or not in the stock face catalogue.",
                     [("keep", "Leave the player's face alone"),
                      ("write", "Write the number anyway")]),
    "nat_multi": ("Players with several nationalities",
                  "The mod stores one nationality per player; the file lists more.",
                  [("first", "Use the first one listed"),
                   ("keep", "Keep the mod player's own nationality (first if new)")]),
    "height_low": ("Heights below 151 cm",
                   "The game's roster write fails under 151 cm.",
                   [("clamp", "Raise to 151 cm"),
                    ("keep", "Keep the mod player's height (151 if new)")]),
    "birth_invalid": ("Impossible birth dates",
                      "The file holds a month or day that does not exist.",
                      [("year", "Use the year with 01/01"),
                       ("keep", "Keep the mod player's date (year + 01/01 if new)")]),
    "no_position": ("New players without a position",
                    "Nothing to build a player from: the file gives no primary position.",
                    [("centre", "Create them as centres"),
                     ("skip", "Skip these players")]),
    "dup_target": ("Several file players matched the same mod player",
                   "Two entries of the file point at one existing player.",
                   [("first", "Only the first one updates; skip the others"),
                    ("new", "Create the others as new players"),
                    ("last", "Let the last one win")]),
}


class Issue:
    def __init__(self, kind, rids):
        self.kind = kind
        self.title, self.detail, self.options = ISSUES[kind]
        self.rids = rids


def _existing_face_is_custom(block):
    face = str(block.get("face") or "").strip()
    return bool(face) and not face.isdigit()


def _stock_face_ids():
    from app.stock_faces import load_stock_faces
    return {int(f["id"]) for f in load_stock_faces()}


def find_issues(plan):
    """[Issue] for the players the import would actually touch."""
    found = {k: [] for k in ISSUES}
    stock = _stock_face_ids() if "faces" in plan.groups else set()
    targets = {}
    for rid in plan.players_in_scope():
        c = plan.players[rid]
        if c.decision == SKIP:
            continue
        rp = c.rp
        existing = plan.ds.players.get(c.pid) if c.decision == UPDATE else None
        block = latest_block(existing) if existing else {}
        if c.decision == UPDATE and c.pid in plan.ds.players:
            targets.setdefault(c.pid, []).append(rid)
        if "identity" in plan.groups:
            initial, surname = plan.name_parts(c)
            if N.too_long(N.game_name(initial, surname, plan.keep_star(rp))):
                found["name_long"].append(rid)
            _, bad = birthdate_for(rp, existing, plan.birth_offset, "year")
            if bad:
                found["birth_invalid"].append(rid)
        if "faces" in plan.groups:
            if rp["face_id"] not in stock:
                found["face_unknown"].append(rid)
            elif existing and _existing_face_is_custom(block):
                found["face_custom"].append(rid)
        if "nationality" in plan.groups and len(rp["nationalities"]) > 1:
            found["nat_multi"].append(rid)
        if "physical" in plan.groups and 0 < rp["height_cm"] < MIN_HEIGHT:
            found["height_low"].append(rid)
        if "positions" in plan.groups and not rp["positions"][0] and not existing:
            found["no_position"].append(rid)
    for pid, rids in targets.items():
        if len(rids) > 1:
            found["dup_target"].extend(rids)
    return [Issue(k, r) for k, r in found.items() if r]


def resolved_decisions(plan):
    """rid -> (decision, pid) after the user's answers to dup_target and
    no_position."""
    dup = plan.resolutions.get("dup_target", "first")
    nopos = plan.resolutions.get("no_position", "centre")
    out, by_target = {}, {}
    for rid in plan.players_in_scope():
        c = plan.players[rid]
        decision, pid = c.decision, c.pid
        if decision == UPDATE and pid not in plan.ds.players:
            decision, pid = CREATE, None
        if decision == UPDATE:
            by_target.setdefault(pid, []).append(rid)
        out[rid] = (decision, pid)
    for pid, rids in by_target.items():
        if len(rids) < 2:
            continue
        winner = rids[-1] if dup == "last" else rids[0]
        for rid in rids:
            if rid != winner:
                out[rid] = (CREATE, None) if dup == "new" else (SKIP, None)
    if nopos == "skip" and "positions" in plan.groups:
        for rid, (decision, _) in list(out.items()):
            if decision == CREATE and not plan.players[rid].rp["positions"][0]:
                out[rid] = (SKIP, None)
    return out


# ── building records ─────────────────────────────────────────────────────
def birthdate_for(rp, existing, offset, invalid_res):
    """-> ("yyyy/mm/dd", invalid). Year gets the offset; a placeholder
    01/01 in the file never overwrites a real date the mod already has."""
    y, m, d = rp["birth"]
    y += offset
    kept = _birth_parts((existing or {}).get("birthdate"))
    m, d = m or 1, d or 1              # a missing part reads as 1
    invalid = not (y > 0 and 1 <= m <= 12 and 1 <= d <= calendar.monthrange(y, m)[1])
    if invalid:
        if invalid_res == "keep" and kept:
            return f"{kept[0]:04d}/{kept[1]:02d}/{kept[2]:02d}", True
        m = d = 1
    elif (m, d) == (1, 1) and kept and kept[0] == y and (kept[1], kept[2]) != (1, 1):
        m, d = kept[1], kept[2]
    return f"{y:04d}/{m:02d}/{d:02d}", invalid


def season_fields(rp, groups, res=None, existing=None):
    res = res or {}
    existing = existing or {}
    out = {}
    if "positions" in groups:
        if rp["positions"][0] or not existing.get("position1"):
            out.update({f"position{i + 1}": rp["positions"][i] for i in range(3)})
            if not out["position1"]:
                out["position1"] = "centre"
    if "physical" in groups:
        h = rp["height_cm"]
        if h < MIN_HEIGHT:
            h = int(existing.get("height") or MIN_HEIGHT) if res.get("height_low") == "keep" \
                and str(existing.get("height") or "").isdigit() and int(existing["height"]) >= MIN_HEIGHT \
                else MIN_HEIGHT
        out["height"] = str(h)
        out["weight"] = str(rp["weight_kg"])
        out["foot"] = rp["foot"]
    if "ratings" in groups:
        out.update({k: str(min(99, rp["ratings"][k])) for k in RATING_KEYS})
    if "extras" in groups:
        out.update({k: str(min(99, rp["ratings"][k])) for k in EXTRA_RATING_KEYS})
        out["special_ability"] = str(rp["tendency"])
        skills = set(rp["skills"])
        out.update({f"ss_{k}": ("yes" if k in skills else "") for k in SKILL_BITS_1 + SKILL_BITS_2})
    if "appearance" in groups:
        out["skin_tone"] = rp["skin_tone"]
        out["wrist_tape"] = rp["wrist_tape"]
        out["tight_tape"] = rp["thigh_tape"]
        out["finger_tape"] = rp["finger_tape"]
        out["socks"] = rp["socks"]
        out["boot_style"] = str(rp["boot_style"])
        # a custom glove image or skin is the mod's own artwork: only the
        # stock flag is the file's to set
        if not (existing.get("gloves") and existing["gloves"] not in ("yes", "")):
            out["gloves"] = "yes" if rp["gloves"] else ""
        if existing.get("skin") and str(existing["skin"]).lower().endswith(
                (".png", ".bmp", ".jpg", ".jpeg")):
            out.pop("skin_tone")
    if "nationality" in groups and rp["nationalities"]:
        if not (len(rp["nationalities"]) > 1 and res.get("nat_multi") == "keep"
                and existing.get("nationality")):
            out["nationality"] = rp["nationalities"][0]
    if "faces" in groups:
        face = rp["face_id"]
        custom = _existing_face_is_custom(existing)
        if face in _stock_face_ids():
            if not (custom and res.get("face_custom", "keep") == "keep"):
                out["face"] = str(face)
        elif res.get("face_unknown") == "write" and face:
            out["face"] = str(face)
    return out


def identity_fields(plan, choice, existing):
    groups = plan.groups
    if "identity" not in groups:
        return {}
    rp = choice.rp
    initial, surname = plan.name_parts(choice)
    res = plan.resolutions
    parsed = N.parse_name(rp["name"])
    out = {"display_name": N.game_name(initial, surname, plan.keep_star(rp),
                                       fit=res.get("name_long", "truncate"))}
    date, _ = birthdate_for(rp, existing, plan.birth_offset, res.get("birth_invalid", "year"))
    out["birthdate"] = date
    if rp["commentary"]:
        out["commentary"] = str(rp["commentary"])
    elif not existing:
        out["commentary"] = ""
    if not (existing or {}).get("last_name"):
        out["last_name"] = N.display_surname(parsed)
    if not (existing or {}).get("first_name") and len(parsed.given) and len(parsed.given[0]) > 1:
        out["first_name"] = parsed.given[0]
    return out


def new_record(plan, choice, season):
    rp = choice.rp
    record = {"display_name": rp["name"], "first_name": "", "last_name": "", "birthdate": "",
              "commentary": "", "stats": {}}
    record.update(identity_fields(plan, choice, None))
    block = new_player_season()
    block.update(season_fields(rp, plan.groups, plan.resolutions))
    record["stats"][str(season)] = block
    return record


def update_record(plan, choice, record, season):
    record = copy.deepcopy(record)
    record.update(identity_fields(plan, choice, record))
    stats = record.setdefault("stats", {})
    if str(season) not in stats:
        # Start from the player's nearest existing season so fields the
        # import leaves alone (appearance, say) carry over rather than reset.
        if stats:
            nearest = min(stats, key=lambda s: abs(int(s) - int(season)) if s.isdigit() else 999)
            stats[str(season)] = copy.deepcopy(stats[nearest])
        else:
            stats[str(season)] = new_player_season()
    block = stats[str(season)]
    block.update(season_fields(choice.rp, plan.groups, plan.resolutions, block))
    record["stats"] = dict(sorted(stats.items()))
    return record


# ── the plan ─────────────────────────────────────────────────────────────
class TeamChoice:
    def __init__(self, team, link=None):
        self.team = team                  # reader team dict
        self.include = False
        self.name = team["name"]
        self.type = team["type"] or "club"
        self.category = ""
        self.link = link or "new"         # "new" or an existing team id


class PlayerChoice:
    def __init__(self, rp, decision, pid, candidates, confidence, reasons=()):
        self.rp = rp
        self.decision = decision
        self.pid = pid
        self.candidates = candidates
        self.confidence = confidence
        self.reasons = list(reasons)


class ImportPlan:
    def __init__(self, roster, ds, season="2026"):
        self.roster = roster
        self.ds = ds
        self.season = str(season)
        self.birth_offset = default_birth_offset(roster["kind"], season)
        self.offset_evidence = 0          # players the offset was read from
        self.resolutions = {}             # issue kind -> chosen option key
        self.groups = {k for k, _, on in GROUPS if on}
        self.squad_size = 22
        self.strip_star = False
        self.players_file = self._default_players_file()
        self.scope = "squads"             # "squads" (players of chosen teams) or "all"
        self.teams = {tid: TeamChoice(t, self._suggest_team(t)) for tid, t in roster["teams"].items()}
        self._index = build_name_index(ds.players)
        estimate, self.offset_evidence = estimate_birth_offset(roster, ds.players, self._index)
        if estimate is not None:
            self.birth_offset = estimate
        self.players = {}
        self.rematch()

    def keep_star(self, rp):
        return "^" in rp["name"] and not self.strip_star

    def name_parts(self, choice):
        """(initial, surname) for the in-game name. A file that only gives a
        surname borrows the initial of the player it matched."""
        parsed = N.parse_name(choice.rp["name"])
        initial = parsed.initial
        record = self.ds.players.get(choice.pid) if choice.decision == UPDATE else None
        if not initial and record:
            first = (record.get("first_name") or "").strip()
            known = [p.initial for p in N.record_names(record) if p.initial]
            initial = first[:1].upper() if first else (known[0].upper() if known else "")
        return initial, N.display_surname(parsed)

    def _default_players_file(self):
        files = self.ds.players_files()
        counts = {}
        for path in self.ds.players_file_path.values():
            counts[path] = counts.get(path, 0) + 1
        return max(files, key=lambda f: counts.get(f, 0)) if files else ""

    def _suggest_team(self, team):
        key = norm_name(team["name"])
        for tid, seasons in self.ds.teams.items():
            names = {norm_name(info.get("name")) for info in seasons.values()}
            if key and key in names:
                return tid
        return "new"

    def rematch(self):
        """(Re)compute a suggestion for every player — keeps choices the user
        already made for players still in scope."""
        previous = self.players
        self.players = {}
        for rid, rp in self.roster["players"].items():
            if rid in previous:
                self.players[rid] = previous[rid]
                continue
            self.players[rid] = PlayerChoice(rp, *match_player(rp, self.ds.players, self._index,
                                                               self.birth_offset, self.season))

    def selected_teams(self):
        return [c for c in self.teams.values() if c.include]

    def players_in_scope(self):
        if self.scope == "all":
            return list(self.players)
        seen = []
        for choice in self.selected_teams():
            for rid in choice.team["squad"][:self.squad_size]:
                if rid in self.players and rid not in seen:
                    seen.append(rid)
        return seen

    # ── outcome ──────────────────────────────────────────────────────────
    def summary(self):
        scope = self.players_in_scope()
        final = resolved_decisions(self)
        decisions = [final[r][0] for r in scope]
        teams = self.selected_teams()
        return {
            "players_create": decisions.count(CREATE),
            "players_update": decisions.count(UPDATE),
            "players_skip": decisions.count(SKIP),
            "players_to_check": sum(1 for r in scope if self.players[r].decision == UPDATE
                                    and self.players[r].confidence == "check"),
            "teams_new": sum(1 for t in teams if t.link == "new"),
            "teams_update": sum(1 for t in teams if t.link != "new"),
            "squads": "squads" in self.groups,
        }


def _team_season_from(choice, pid_for, plan):
    """squad / roles / set plays for one team, in mod ids."""
    squad = []
    for rid in choice.team["squad"]:
        pid = pid_for.get(rid)
        if pid and pid not in squad:
            squad.append(pid)
        if len(squad) >= plan.squad_size:
            break
    info = {"players": squad, "setPlays": dict(choice.team["set_plays"]), "roles": {}}
    starters = squad[:STARTING_XV]
    for key in ROLE_KEYS:
        pid = pid_for.get(choice.team["roles"].get(key))
        info["roles"][key] = pid if pid in starters else ""
    for key in ROLE_KEYS:
        if not info["roles"][key] and starters:
            info["roles"][key] = T.best_for_role(info, plan.ds.players, plan.season, key)
    return info


def apply_import(plan, progress=None):
    """Write everything the plan describes. Returns a result dict. Player
    files are each written once; teams one file each."""
    ds = plan.ds
    result = {"players_created": [], "players_updated": [], "teams_created": [],
              "teams_updated": [], "files": set(), "warnings": []}
    scope = plan.players_in_scope()
    groups = plan.groups

    # ── players ──────────────────────────────────────────────────────────
    pid_for = {}
    by_file = {}
    next_id = int(allocate_player_id(ds.players_files(), ds.players))
    final = resolved_decisions(plan)
    for rid in scope:
        choice = plan.players[rid]
        decision, target = final[rid]
        if decision == SKIP:
            continue
        if decision == UPDATE:
            record = update_record(plan, choice, ds.players[target], plan.season)
            path = ds.players_file_path[target]
            by_file.setdefault(path, {})[target] = record
            pid_for[rid] = target
            if target not in result["players_updated"]:
                result["players_updated"].append(target)
        else:
            pid = str(next_id)
            next_id += 1
            record = new_record(plan, choice, plan.season)
            by_file.setdefault(plan.players_file, {})[pid] = record
            pid_for[rid] = pid
            result["players_created"].append(pid)
    for rid, choice in plan.players.items():
        if rid not in pid_for and choice.decision == UPDATE and choice.pid in ds.players:
            pid_for[rid] = choice.pid       # existing player referenced by a squad

    for path, records in by_file.items():
        if not path:
            raise SaveError("no players file chosen for new players")
        data = _load_json(path)
        if not isinstance(data, dict):
            raise SaveError(f"{os.path.basename(path)} is a list, not a player map")
        data.update(records)
        _write_json(path, data)
        result["files"].add(path)
        for pid, record in records.items():
            ds.register_player(pid, record, path)
        if progress:
            progress(f"wrote {os.path.basename(path)}")

    # ── teams ────────────────────────────────────────────────────────────
    if "squads" in groups:
        for choice in plan.selected_teams():
            squad_info = _team_season_from(choice, pid_for, plan)
            if choice.link == "new":
                seasons = {plan.season: new_team_season(choice.name, choice.type, choice.category)}
                seasons[plan.season].update(squad_info)
                teams_dir = _teams_dir()
                folder = T.safe_folder_name(choice.name, teams_dir)
                tid = T.allocate_team_id(choice.type, ds.team_json_ids, ds.teams)
                json_path, _ = T.create_team(teams_dir, folder, tid, seasons)
                ds.register_team(tid, seasons, os.path.join(teams_dir, folder), json_path)
                result["teams_created"].append(tid)
                result["files"].add(json_path)
            else:
                tid = choice.link
                seasons = copy.deepcopy(ds.teams[tid])
                if plan.season not in seasons:
                    latest = sorted(seasons)[-1] if seasons else None
                    T.add_season(seasons, plan.season, latest, choice.name, choice.type, choice.category)
                info = seasons[plan.season]
                info.update(squad_info)
                info["name"] = choice.name
                save_team(ds.teams_file_path[tid], tid, seasons)
                ds.teams[tid] = seasons
                ds.events.team_changed.emit(tid)
                result["teams_updated"].append(tid)
                result["files"].add(ds.teams_file_path[tid])
            if len(squad_info["players"]) < 22:
                result["warnings"].append(
                    f"{choice.name}: {len(squad_info['players'])} players after skips — the game needs 22")
            if progress:
                progress(f"team {choice.name}")
    return result


def _teams_dir():
    from shared.config import config
    return config.directory_teams
