"""
app/roster_import/plan.py — turn a game roster into mod JSON, selectively
===========================================================================
Nothing here writes until `apply_import`. The wizard builds an `ImportPlan`
(which teams, how each maps to an existing team, what to do with each
player, which field groups), shows `summary()` for review, then applies it.

Player matching is by name: the game's roster ids have nothing to do with
the mod's player ids. Every match is only a suggestion the user reviews.
"""
import copy
import os
import re
import unicodedata

from app import team_ops as T
from app.game_data import (
    ATTRIBUTES, ROLE_KEYS, new_player_season, new_team_season, save_team, _load_json,
    _write_json, SaveError, STARTING_XV,
)
from app.player_ops import allocate_player_id
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
    ("faces", "Face id (the game's own face numbers)", False),
    ("squads", "Squads, roles and set plays", True),
]

CREATE, UPDATE, SKIP = "create", "update", "skip"


def norm_name(name):
    name = unicodedata.normalize("NFKD", (name or "").replace("^", ""))
    name = "".join(c for c in name if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]", "", name.lower())


def default_birth_offset(kind, season):
    """Patches keep player ages relative to 2007 by shifting birth years
    (TRF 2017 stores Dupont, born 1996, as 1986). A raw stock roster is
    exact. Only a suggestion — the wizard lets the user change it."""
    try:
        year = int(season)
    except (TypeError, ValueError):
        return 0
    return max(0, year - 2007) if kind == "ros" else 0


# ── matching ─────────────────────────────────────────────────────────────
def build_name_index(players):
    index = {}
    for pid, record in players.items():
        for key in {norm_name(record.get("display_name")),
                    norm_name(f"{(record.get('first_name') or '')[:1]}.{record.get('last_name') or ''}")}:
            if key:
                index.setdefault(key, []).append(pid)
    return index


def match_player(rp, players, index, birth_offset):
    """-> (decision, pid or None, candidates, confidence)
    confidence: "exact" (one candidate, agreeing), "check" (ambiguous or
    disagreeing), "none"."""
    cands = list(dict.fromkeys(index.get(norm_name(rp["name"]), [])))
    if not cands:
        return CREATE, None, [], "none"

    year = rp["birth"][0] + birth_offset

    def score(pid):
        rec = players[pid]
        s = 0
        try:
            if abs(int((rec.get("birthdate") or "")[:4]) - year) <= 1:
                s += 2
        except ValueError:
            pass
        latest = (rec.get("stats") or {})
        block = latest[sorted(latest)[-1]] if latest else {}
        if block.get("position1") and block.get("position1") in rp["positions"]:
            s += 1
        return s

    ranked = sorted(cands, key=score, reverse=True)
    best = ranked[0]
    confident = len(ranked) == 1 and score(best) >= 1 or (len(ranked) > 1 and score(ranked[0]) > score(ranked[1]) and score(best) >= 2)
    return UPDATE, best, ranked, "exact" if confident else "check"


# ── building records ─────────────────────────────────────────────────────
def season_fields(rp, groups):
    out = {}
    if "positions" in groups:
        out.update({f"position{i + 1}": rp["positions"][i] for i in range(3)})
    if "physical" in groups:
        out["height"] = str(rp["height_cm"])
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
        out["gloves"] = "yes" if rp["gloves"] else ""
        out["boot_style"] = str(rp["boot_style"])
    if "nationality" in groups and rp["nationalities"]:
        out["nationality"] = rp["nationalities"][0]
    if "faces" in groups:
        out["face"] = str(rp["face_id"])
    return out


def identity_fields(rp, groups, birth_offset, strip_star):
    if "identity" not in groups:
        return {}
    y, m, d = rp["birth"]
    name = rp["name"].replace("^", "").strip() if strip_star else rp["name"]
    return {
        "display_name": name,
        "birthdate": f"{y + birth_offset:04d}/{max(1, m):02d}/{max(1, d):02d}",
        "commentary": str(rp["commentary"]) if rp["commentary"] else "",
    }


def new_record(rp, season, groups, birth_offset, strip_star):
    record = {"display_name": rp["name"], "first_name": "", "last_name": "", "birthdate": "",
              "commentary": "", "stats": {}}
    record.update(identity_fields(rp, groups | {"identity"}, birth_offset, strip_star))
    block = new_player_season()
    block.update(season_fields(rp, groups))
    record["stats"][str(season)] = block
    return record


def update_record(record, rp, season, groups, birth_offset, strip_star):
    record = copy.deepcopy(record)
    ident = identity_fields(rp, groups, birth_offset, strip_star)
    record.update(ident)
    stats = record.setdefault("stats", {})
    if str(season) not in stats:
        # Start from the player's nearest existing season so fields the
        # import leaves alone (appearance, say) carry over rather than reset.
        if stats:
            nearest = min(stats, key=lambda s: abs(int(s) - int(season)) if s.isdigit() else 999)
            stats[str(season)] = copy.deepcopy(stats[nearest])
        else:
            stats[str(season)] = new_player_season()
    stats[str(season)].update(season_fields(rp, groups))
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
    def __init__(self, rp, decision, pid, candidates, confidence):
        self.rp = rp
        self.decision = decision
        self.pid = pid
        self.candidates = candidates
        self.confidence = confidence


class ImportPlan:
    def __init__(self, roster, ds, season="2026"):
        self.roster = roster
        self.ds = ds
        self.season = str(season)
        self.birth_offset = default_birth_offset(roster["kind"], season)
        self.groups = {k for k, _, on in GROUPS if on}
        self.squad_size = 22
        self.strip_star = False
        self.players_file = self._default_players_file()
        self.scope = "squads"             # "squads" (players of chosen teams) or "all"
        self.teams = {tid: TeamChoice(t, self._suggest_team(t)) for tid, t in roster["teams"].items()}
        self._index = build_name_index(ds.players)
        self.players = {}
        self.rematch()

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
                                                               self.birth_offset))

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
        decisions = [self.players[r].decision for r in scope]
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
    for rid in scope:
        choice = plan.players[rid]
        if choice.decision == SKIP:
            continue
        if choice.decision == UPDATE and choice.pid in ds.players:
            record = update_record(ds.players[choice.pid], choice.rp, plan.season, groups,
                                   plan.birth_offset, plan.strip_star)
            path = ds.players_file_path[choice.pid]
            by_file.setdefault(path, {})[choice.pid] = record
            pid_for[rid] = choice.pid
            result["players_updated"].append(choice.pid)
        else:
            pid = str(next_id)
            next_id += 1
            record = new_record(choice.rp, plan.season, groups, plan.birth_offset, plan.strip_star)
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
