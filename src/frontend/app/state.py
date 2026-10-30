"""
app/state.py — DataStore + MatchConfig
=========================================
DataStore loads teams/players/stadiums/tournaments ONCE, at startup, instead
of synchronously inside the old TeamSelectionWidget.__init__. MatchConfig is
the single source of truth the match-setup screen edits; match_data_builder
consumes it to produce the backend dict.
"""
import os
import random
from dataclasses import dataclass, field
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

from app import variants as V
from app import game_data as G
from app.user_edits import EditStore, KINDS
from shared.user_prefs import user_prefs
from team_data_loader import TeamDataLoader
from stadium_data_loader import StadiumDataLoader
from tournament_data_loader import TournamentDataLoader
from shared.config import config
from shared import kit_files

# Order of the category list in match setup. Internal, not exposed to the
# user. Categories not listed here follow, alphabetically.
CATEGORY_ORDER = [
    "International",
    "European Cup",
    "Top 14",
    "Pro D2",
    "Premiership",
    "Championship",
    "URC",
    "Pro14",
    "Pro12",
    "Celtic League",
    "Super Rugby",
    "Super 14",
]


def _category_key(category):
    try:
        return (0, CATEGORY_ORDER.index(category), "")
    except ValueError:
        return (1, 0, category)


class DataEvents(QObject):
    """Broadcast when a record is saved, created or deleted, so every screen
    showing it (the other editor, match setup) can refresh instead of
    displaying what was true when it was last opened."""
    team_changed = pyqtSignal(str)
    team_removed = pyqtSignal(str)
    player_changed = pyqtSignal(str)
    player_removed = pyqtSignal(str)


def _apply_edits(loader, teams, players, edits):
    """Lay the user's edits over what the loader read from the pack, and
    register where the records the user created belong."""
    for tid in edits.reconcile("teams", loader.teams_raw, loader.teams_file_path):
        seasons = loader.teams_raw.get(tid)
        live = TeamDataLoader.enabled_seasons(seasons or {})
        if live:
            teams[tid] = live
        else:
            teams.pop(tid, None)
        if seasons is not None and tid not in loader.teams_file_path:
            path = edits.pack.abspath(edits.get("teams", tid)["home"])
            loader.teams_file_path[tid] = path
            loader.teams_folder_path[tid] = os.path.dirname(path)
            loader.team_json_ids.setdefault(path, []).append(tid)
    for pid in edits.reconcile("players", players, loader.players_file_path):
        if pid not in players:
            loader.players_file_path.pop(pid, None)
            loader.players_sources.pop(pid, None)
        elif pid not in loader.players_file_path:
            path = edits.pack.abspath(edits.get("players", pid)["home"])
            loader.players_file_path[pid] = path
            loader.players_sources[pid] = [path]


class DataStore:
    """Loads once; every screen reads through this instead of re-loading."""

    def __init__(self, raw=None):
        """`raw` is what read_files() returned, possibly from another thread:
        the JSON parsing is the slow part and needs no Qt, so start-up does
        it behind the splash without stalling its animation."""
        (self.teams, self.players, self.teams_folder_path, self.teams_file_path,
         self.players_file_path, self.players_sources, self.team_json_ids,
         self.stadiums, self.tournaments, self.tournaments_folder_path,
         self.edits) = raw or self.read_files()
        # saves go to the user's edits (or, maintainer, to the pack files)
        G.set_edit_store(self.edits, into_pack=config.save_edits_to == "mod")
        self.events = DataEvents()

    @staticmethod
    def read_files():
        """Every data file parsed; touches no Qt object, so it can run on a
        worker thread."""
        loader = TeamDataLoader(config.directory_teams, config.directory_players)
        teams = loader.load_teams()
        players = loader.load_players()
        edits = EditStore(config.directory_user_edits, config.mod_data_directory,
                          config.data_version).load()
        edits.enabled = user_prefs.use_edits
        if edits.enabled:
            _apply_edits(loader, teams, players, edits)
        # older squad variants could carry kits: they now live in the kit;
        # edits made before the kits were packed name the old .png files
        for tid, seasons in teams.items():
            for info in seasons.values():
                V.migrate_season(info)
                kit_files.migrate_kit_files(info, loader.teams_folder_path.get(tid, ""))
        stadiums = StadiumDataLoader(config.directory_stadiums).load_stadiums()
        tournament_loader = TournamentDataLoader(config.directory_competitions)
        tournaments = tournament_loader.load_tournaments()
        # Where each record came from, so the editors can write it back to
        # the file it was actually read from (see TeamDataLoader).
        return (teams, players, loader.teams_folder_path, loader.teams_file_path,
                loader.players_file_path, loader.players_sources, loader.team_json_ids,
                stadiums, tournaments, tournament_loader.tournaments_folder_path, edits)

    # ── the user's edits (app/user_edits.py) ──────────────────────────────
    def promote_edits(self, keys):
        """Write the edits `keys` [(kind, id)] into the data pack files (the
        maintainer integrating them); each then leaves the user's edits.
        Records with conflicts are skipped. Returns how many were written."""
        written = 0
        with G.writing_pack():
            for kind, rid in keys:
                env = self.edits.get(kind, rid)
                if env is None or (kind, rid) in self.edits.conflicts:
                    continue
                path = self.edits.pack.abspath(env["home"])
                if not path:
                    raise G.SaveError(f"{kind} {rid}: no data pack file recorded")
                # the user's record merged with the pack as installed (an
                # imported edit's base can be an older release)
                mine = self.edits.effective(kind, rid)
                exists = os.path.isfile(path)
                if kind == "players":
                    if mine is None:
                        if exists:
                            G.delete_player(path, rid)
                    elif exists:
                        G.save_player(path, rid, mine)
                    else:
                        raise G.SaveError(f"player {rid}: {env['home']} is not in the data pack")
                elif mine is None:
                    if exists:
                        G.delete_team(path, rid)
                elif exists:
                    G.save_team(path, rid, mine)
                else:
                    os.makedirs(os.path.dirname(path), exist_ok=True)
                    G.create_team_file(path, rid, mine)
                self.edits._drop(kind, rid)
                self.refresh_record(kind, rid, home=env["home"])    # as written (edits off too)
                written += 1
        return written

    def set_edits_enabled(self, on):
        """Use the user's edits or not (kept either way), from now on and at
        the next starts: every edited record is re-read and the screens told."""
        on = bool(on)
        user_prefs.use_edits = on
        user_prefs.save()
        if on == self.edits.enabled:
            return
        self.edits.enabled = on
        self.edits.conflicts.clear()
        for kind in KINDS:
            for rid in list(self.edits.envelopes[kind]):
                if on:
                    self.edits._recheck(kind, rid)
                self.refresh_record(kind, rid)

    def refresh_record(self, kind, rid, home=""):
        """Re-read one team or player as it is now (pack + the user's edit),
        after its edit was resolved, reverted or imported, and tell the
        screens. `home`: its pack file (pack-relative), when the edit that
        knew it is gone."""
        rid = str(rid)
        env = self.edits.get(kind, rid)
        home = home or (env["home"] if env else "")
        if not self.edits.enabled:
            env = None              # edits off: the pack's record
        if kind == "players":
            path = self.players_file_path.get(rid) or self.edits.pack.abspath(home)
            record = (self.edits.effective(kind, rid) if env else
                      self.edits.pack.record(self.edits.pack.relpath(path), rid))
            if record is None:
                if rid in self.players:
                    self.unregister_player(rid)
            else:
                self.register_player(rid, record, path)
            return
        path = self.teams_file_path.get(rid) or self.edits.pack.abspath(home)
        record = (self.edits.effective(kind, rid) if env else
                  self.edits.pack.record(self.edits.pack.relpath(path), rid))
        live = TeamDataLoader.enabled_seasons(record or {})
        if not live:
            if rid in self.teams:
                self.unregister_team(rid)
            return
        for info in live.values():
            V.migrate_season(info)
            kit_files.migrate_kit_files(info, os.path.dirname(path))
        self.register_team(rid, live, os.path.dirname(path), path)

    # ── registry updates made by the editors ──────────────────────────────
    def players_files(self) -> list:
        d = config.directory_players
        if not os.path.isdir(d):
            return []
        return [os.path.join(d, f) for f in sorted(os.listdir(d)) if f.endswith(".json")]

    def register_team(self, tid, seasons, folder, json_path):
        self.teams[tid] = seasons
        self.teams_folder_path[tid] = folder
        self.teams_file_path[tid] = json_path
        self.team_json_ids.setdefault(json_path, [])
        if tid not in self.team_json_ids[json_path]:
            self.team_json_ids[json_path].append(tid)
        self.events.team_changed.emit(tid)

    def unregister_team(self, tid):
        path = self.teams_file_path.pop(tid, None)
        self.teams.pop(tid, None)
        self.teams_folder_path.pop(tid, None)
        if path:
            self.team_json_ids.pop(path, None)
        self.events.team_removed.emit(tid)

    def register_player(self, pid, record, path):
        self.players[pid] = record
        self.players_file_path[pid] = path
        sources = self.players_sources.setdefault(pid, [])
        if path not in sources:
            sources.append(path)
        self.events.player_changed.emit(pid)

    def unregister_player(self, pid):
        self.players.pop(pid, None)
        self.players_file_path.pop(pid, None)
        self.players_sources.pop(pid, None)
        self.events.player_removed.emit(pid)

    def memberships(self, pid, with_variants=False) -> list:
        """[(team_id, team name, season, shirt)] for every squad listing
        `pid`. The squad list IS the shirt assignment, so index+1 is the
        number he wears. `with_variants` adds a 5th item, the variant id
        ("" = the season's default squad), and lists variant squads too."""
        found = []
        for tid, seasons in self.teams.items():
            for season, info in seasons.items():
                for variant in [V.DEFAULT] + (V.variant_ids(info) if with_variants else []):
                    if variant and "players" not in V.overrides(info, variant):
                        continue          # same squad as the default: listed once
                    block = V.resolve(info, variant) if variant else info
                    for index, listed in enumerate(str(p) for p in block.get("players", [])):
                        if listed == str(pid):
                            entry = (tid, block.get("name", tid), season, index + 1)
                            found.append(entry + (variant,) if with_variants else entry)
        return sorted(found, key=lambda e: (e[2], e[1]), reverse=True)

    # ── resolved team blocks (default squad or a competition variant) ─────
    def team_season(self, team_id, season, variant=V.DEFAULT, exact=True) -> dict:
        """Season block as `variant` sees it — a copy; see app/variants.py.
        `exact` (default): {} when the team has no such season."""
        return V.team_season(self.teams, team_id, season, variant, exact=exact)

    def variants_of(self, team_id, season) -> list:
        """Variant ids the team has in `season` (no default)."""
        return V.variant_ids(self.teams.get(str(team_id), {}).get(str(season), {}))

    # ── convenience lookups shared by every screen that touches teams ──────
    def seasons(self) -> list:
        return sorted({s for t in self.teams.values() for s in t})

    def all_categories(self) -> list:
        return sorted({info.get("category", "") for t in self.teams.values()
                       for info in t.values() if info.get("category")})

    def categories_for(self, season: str) -> list:
        return sorted({
            info[season]["category"]
            for info in self.teams.values() if season in info
        }, key=_category_key)

    def teams_in_season(self, season: str) -> list:
        """[(team_id, name)] for every team that exists in `season`, across
        all categories, sorted by name — the match-setup team picker doesn't
        expose a separate category control, so this ignores category."""
        if not season:
            return []
        return sorted(
            ((tid, info[season]["name"]) for tid, info in self.teams.items() if season in info),
            key=lambda t: t[1],
        )

    def teams_for(self, season: str, category: str) -> dict:
        return {
            tid: info[season]
            for tid, info in self.teams.items()
            if season in info and info[season]["category"] == category
        }

    def random_team(self, season: str) -> tuple:
        cats = self.categories_for(season)
        if not cats:
            return None, None
        cat = random.choice(cats)
        teams = self.teams_for(season, cat)
        if not teams:
            return None, None
        tid = random.choice(list(teams.keys()))
        return tid, cat

    def get_players(self, player_ids: list, season: str) -> dict:
        result = {}
        for pid in player_ids:
            if pid not in self.players:
                continue
            p = self.players[pid]
            if "stats" not in p:
                continue
            use_season = (
                season if season in p["stats"]
                else str(min((int(y) for y in p["stats"]), key=lambda y: abs(y - int(season))))
            )
            flat = {k: v for k, v in p.items() if k != "stats"}
            flat.update(p["stats"][str(use_season)])
            result[int(pid)] = flat
        return result

    def get_lineup(self, team_id: str, season: str, variant: str = V.DEFAULT) -> dict:
        team = self.team_season(team_id, season, variant)
        return {"players_id": team["players"], "roles": team["roles"], "set_plays": team["setPlays"]}


@dataclass
class TeamSlot:
    """One side's in-progress selection. `variant` picks a competition
    squad/look inside the season ("" = the season's default) — every read of
    the team goes through `info()`, never ds.teams[...] directly.
    `kit_variant` is a variant of the picked kit itself (a tournament patch…,
    "" = the plain kit), independent of the squad variant; a kit without it
    is worn plain."""
    team_id: Optional[str] = None
    season: Optional[str] = None
    variant: str = ""
    kit_index: int = 0
    kit_variant: str = ""
    # Kit file fields (frontKitFile/backKitFile/previewFile, team-folder relative)
    # replacing the picked kit's — a challenge's own kit, see app/challenges.
    kit_override: dict = field(default_factory=dict)
    lineup: dict = field(default_factory=dict)
    players: dict = field(default_factory=dict)

    def info(self, ds) -> dict:
        """The resolved team block for this slot ({} when unset)."""
        if not (self.team_id and self.season):
            return {}
        return ds.team_season(self.team_id, self.season, self.variant)

    def kits(self, ds) -> dict:
        """The kits `kit_index` picks from ({} when unset), as stored."""
        return self.info(ds).get("kits", {})

    def kit_key(self, ds) -> str:
        keys = list(self.kits(ds))
        return keys[self.kit_index % len(keys)] if keys else ""

    def kit(self, ds) -> dict:
        """The picked kit with `kit_variant` and `kit_override` applied ({}
        when none)."""
        kits = self.kits(ds)
        kit = V.resolve_kit(kits[self.kit_key(ds)], self.kit_variant) if kits else {}
        kit.update(self.kit_override or {})
        return kit


# The game's four input devices, as (slot_id, kind, label). Slot n becomes the
# .mis c(n-1) attribute (backend.game_files_processor.create_mission_file) the
# reR08 controllers patch applies to device n-1: the keyboard is device 0, the
# gamepads follow in the order the game finds them.
CONTROLLER_SLOTS = (
    (1, "kbd", "KEYBOARD"),
    (2, "pad", "GAMEPAD 1"),
    (3, "pad", "GAMEPAD 2"),
    (4, "pad", "GAMEPAD 3"),
)


@dataclass
class MatchConfig:
    """The in-progress match selection — the single source of truth the
    match-setup screen edits, and what match_data_builder consumes."""
    home: TeamSlot = field(default_factory=TeamSlot)
    away: TeamSlot = field(default_factory=TeamSlot)

    # Backend only takes one competition for the whole match (tournament
    # logo/pads/pitch overlay are match-wide) — mirrors the home card's own
    # competition picker; see MatchSetupScreen.on_team_changed.
    shared_tournament: Optional[dict] = None

    stadium: Optional[dict] = None
    ball_choice: Optional[dict] = None
    adboards: Optional[str] = None  # optional FSH path relative to mod data

    difficulty: str = "elite"  # club, pro, elite (stock levels), legend, immortal — see app/difficulty.py
    halftime_length: str = "5m"  # 2m, 5m, 10m, 20m, 40m — matches backend gsv.halftime_length / stock game's 5 levels
    home_team_side: str = "random"  # random, left, right — resolved to left/right at kick-off
    kick_off: str = "random"
    match_type: str = "exhibition"  # matches backend gsv.match_type
    match_subtype: str = "none"  # matches backend gsv.match_subtype
    environment: str = "day"  # day, night, overcast, cold — reR08 ENABLE_ENVIRONMENT;
                              # actual default is the selected stadium's first listed one
                              # (see MatchSetupScreen._sync_environment_choices)
    # "default" = the stadium's own pitch, unmodified (reR08 patches_dll
    # treats any non-whitelisted value as "stock behaviour", so this needs
    # no special-casing downstream).
    pitch_texture: str = "default"  # a gsv.pitch_textures name, e.g. Reg2_08_muddy_n — reR08 ENABLE_PITCH
    rain: bool = False  # reR08 ENABLE_WEATHER (precipitation on/off)
    pitch_logo_choice: str = "none"  # tournament id, or "none"
    # Tournament id whose logo fills the tournament logo slot (scoreboard,
    # menus); "" = none chosen, the home team's crest is used
    tournament_logo_choice: str = ""
    # Tournament id whose pads fill the stadium graphics slot; "" = none chosen,
    # the home team's pads are used
    stadium_graphics_choice: str = ""

    # slot_id -> {"kind": "kbd"|"pad", "label": str, "zone": "home"|"away"|"none"}
    # (slot ids: CONTROLLER_SLOTS)
    controllers: dict = field(default_factory=dict)
    # In the game, no device can join a team given no human above (reR08
    # controller_lock: the pause-menu controller screen can't move anyone to
    # the opponent). Tournament and challenge matches; quick match leaves it off.
    lock_controllers: bool = False

    # ── Advanced/.mis fields (config.advanced_user) ─────────────────────
    # Only reachable from the ADVANCED pane's extra sections, which only
    # exist when config.advanced_user is True — see
    # screens/match_setup.py::MatchSetupScreen._build_advanced_panel and
    # backend/game_specific_variables.py for the verified value lists.
    # Every field here defaults to a "stock" sentinel (None / "stock" /
    # False / empty) that match_data_builder + game_files_processor treat
    # as "omit the .mis attribute entirely" — so a match built with
    # advanced_user off, or with the advanced panel never opened, produces
    # the exact same mission file as before these fields existed.
    wind_power: Optional[int] = None       # 0..10, reR08 ENABLE_WIND band; None = stock random wind, rolled by the backend
    wind_dir_deg: float = 0.0              # compass bearing; only used when wind_power is set
    precip_mode: str = "stock"             # stock, none, rain, snow — overrides `rain` above when set
    snow_intensity: Optional[float] = None  # 0..26, reR08 ENABLE_SNOWFX
    breath: Optional[bool] = None          # None=stock, reR08 ENABLE_BREATH otherwise
    anthem: str = "stock"                  # stock, home, away — reR08 ENABLE_ANTHEM
    haka_home: bool = False                # reR08 ENABLE_HAKA
    haka_away: bool = False
    trophy_lift: str = "stock"             # stock, off, on, <trophy name> — reR08 ENABLE_TROPHY_LIFT
    stadium_flags: Optional[bool] = None   # None=stock, reR08 ENABLE_STADIUM_FLAGS otherwise
    kick_assist: bool = False              # reR08 ENABLE_EASY_GOALKICK (needs wind)

    # Hand-authored mission state — EXPERIMENTAL (see the writer's own
    # comment in game_files_processor.create_mission_file): the schema is
    # verified against 93 stock .mis files, the runtime behaviour of
    # anything but a plain kickoff dropped into an exhibition match is not.
    mission_mode_name: str = ""            # "", "KICK OFF", "FORMATION", "LINE OUT", "PEN K", "FREE"
    mission_mode_time: Optional[int] = None    # seconds into the half
    mission_mode_period: Optional[int] = None
    # Restart position(s) that go with the start mode above (scrum/lineout/
    # penalty placement) — stock missions carry 0-2 of these.
    # [{"script_name": "", "controller": 0, "team": "home", "player": 0,
    #   "angle": None, "x": None, "y": None, "z": None}, ...]
    mission_nis: list = field(default_factory=list)
    # [{"type": "SS_TRY", "team": "home", "player": 11, "time": 310}, ...]
    score_events: list = field(default_factory=list)
    # [{"type": "WinGame", "mustpass": True, "stringid": "",
    #   "parameters": [{"name": "amount", "value": 1}, ...]}, ...]
    objectives: list = field(default_factory=list)
    # Referee cards at set minutes (reR08 ENABLE_CARDS, .mis <EVENTS><CARD>):
    # [{"team": "home", "jersey": 12, "type": "yellow", "minute": 46}, ...]
    cards: list = field(default_factory=list)

    def controller_counts(self):
        home = sum(1 for c in self.controllers.values() if c["zone"] == "home")
        away = sum(1 for c in self.controllers.values() if c["zone"] == "away")
        return home, away

    def is_ready(self) -> bool:
        # No controller assigned is fine: CPU vs CPU.
        return bool(self.home.team_id and self.away.team_id)
