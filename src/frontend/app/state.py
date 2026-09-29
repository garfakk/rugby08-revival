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

from team_data_loader import TeamDataLoader
from stadium_data_loader import StadiumDataLoader
from tournament_data_loader import TournamentDataLoader
from shared.config import config


class DataEvents(QObject):
    """Broadcast when a record is saved, created or deleted, so every screen
    showing it (the other editor, match setup) can refresh instead of
    displaying what was true when it was last opened."""
    team_changed = pyqtSignal(str)
    team_removed = pyqtSignal(str)
    player_changed = pyqtSignal(str)
    player_removed = pyqtSignal(str)


class DataStore:
    """Loads once; every screen reads through this instead of re-loading."""

    def __init__(self):
        loader = TeamDataLoader(config.directory_teams, config.directory_players)
        self.teams = loader.load_teams()
        self.players = loader.load_players()
        self.teams_folder_path = loader.teams_folder_path
        # Where each record came from, so the editors can write it back to
        # the file it was actually read from (see TeamDataLoader).
        self.teams_file_path = loader.teams_file_path
        self.players_file_path = loader.players_file_path
        self.players_sources = loader.players_sources
        self.team_json_ids = loader.team_json_ids
        self.events = DataEvents()

        stadium_loader = StadiumDataLoader(config.directory_stadiums)
        self.stadiums = stadium_loader.load_stadiums()

        tournament_loader = TournamentDataLoader(config.directory_tournaments)
        self.tournaments = tournament_loader.load_tournaments()
        self.tournaments_folder_path = tournament_loader.tournaments_folder_path

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

    def memberships(self, pid) -> list:
        """[(team_id, team name, season, shirt)] for every squad listing
        `pid`. The squad list IS the shirt assignment, so index+1 is the
        number he wears."""
        found = []
        for tid, seasons in self.teams.items():
            for season, info in seasons.items():
                for index, listed in enumerate(str(p) for p in info.get("players", [])):
                    if listed == str(pid):
                        found.append((tid, info.get("name", tid), season, index + 1))
        return sorted(found, key=lambda e: (e[2], e[1]), reverse=True)

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
        })

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

    def get_lineup(self, team_id: str, season: str) -> dict:
        team = self.teams[team_id][season]
        return {"players_id": team["players"], "roles": team["roles"], "set_plays": team["setPlays"]}


@dataclass
class TeamSlot:
    """One side's in-progress selection."""
    team_id: Optional[str] = None
    season: Optional[str] = None
    kit_index: int = 0
    lineup: dict = field(default_factory=dict)
    players: dict = field(default_factory=dict)


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

    difficulty: str = "elite"  # club, pro, elite — matches backend gsv.difficulty / stock game's 3 levels
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
    controllers: dict = field(default_factory=dict)

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
    wind_power: Optional[int] = None       # 0..10, reR08 ENABLE_WIND band
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

    def controller_counts(self):
        home = sum(1 for c in self.controllers.values() if c["zone"] == "home")
        away = sum(1 for c in self.controllers.values() if c["zone"] == "away")
        return home, away

    def is_ready(self) -> bool:
        home, away = self.controller_counts()
        return bool(self.home.team_id and self.away.team_id and (home + away) >= 1)
