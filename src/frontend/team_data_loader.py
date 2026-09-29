"""
team_data_loader.py — Loads team and player data from disk.
"""
import os
import json


from shared.log import get_logger

log = get_logger(__name__)


class TeamDataLoader:
    def __init__(self, teams_dir: str, players_dir: str):
        self.teams_dir = teams_dir
        self.players_dir = players_dir
        self.teams_folder_path: dict[str, str] = {}
        # Which file each record was actually read from. Both directories can
        # hold several files defining the same ids (a team folder with a
        # "(copy)" beside its real json, two player files listing the same
        # roster), and the last one read wins — so an editor that wants to
        # write a record back has to be told where it came from rather than
        # guessing at a filename.
        self.teams_file_path: dict[str, str] = {}
        self.players_file_path: dict[str, str] = {}
        # Every file that defines each player id, in load order (the last
        # one is the one in effect). More than one entry means the same
        # player is defined twice and only the last copy is used.
        self.players_sources: dict[str, list] = {}
        # Every team id found in ANY *.json under a team folder, loaded or
        # not — a new team must not reuse an id an ignored file already has.
        self.team_json_ids: dict[str, list] = {}

    @staticmethod
    def team_json_name(folder_name: str) -> str:
        """The only file a team folder is loaded from."""
        return f"{folder_name.lower().replace(' ', '_')}.json"

    def load_teams(self) -> dict:
        """Return {team_id: {season: {...}}} for every team folder found."""
        teams = {}
        if not os.path.isdir(self.teams_dir):
            log.warning(f"teams directory not found: {self.teams_dir}")
            return teams

        for folder_name in sorted(os.listdir(self.teams_dir)):
            folder_path = os.path.join(self.teams_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            for fname in sorted(os.listdir(folder_path)):
                if not fname.endswith(".json"):
                    continue
                try:
                    with open(os.path.join(folder_path, fname), "r", encoding="utf-8") as fh:
                        ids = [str(k) for k in json.load(fh)]
                    self.team_json_ids[os.path.join(folder_path, fname)] = ids
                except Exception:
                    pass
            json_path = os.path.join(folder_path, self.team_json_name(folder_name))
            if not os.path.exists(json_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                team_id = next(iter(data))
                self.teams_folder_path[team_id] = folder_path
                self.teams_file_path[team_id] = json_path
                teams.update(data)
            except Exception as e:
                log.error(f"Error loading team '{folder_name}': {e}")

        return teams

    def load_players(self) -> dict:
        """Return {player_id: {...}} for every .json file in the players directory. Handles both dict and list formats."""
        players = {}
        if not os.path.isdir(self.players_dir):
            log.warning(f"players directory not found: {self.players_dir}")
            return players

        duplicates = 0
        # Sorted, so which duplicate wins is the same on every machine and
        # every run instead of whatever order the filesystem returns.
        for fname in sorted(os.listdir(self.players_dir)):
            if not fname.endswith(".json"):
                continue
            fpath = os.path.join(self.players_dir, fname)
            try:
                with open(fpath, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    entries = [(str(pid), pdata) for pid, pdata in data.items()]
                elif isinstance(data, list):
                    entries = [(str(p.get("id") or p.get("player_id") or p.get("display_name")
                                    or len(players) + 1), p) for p in data]
                else:
                    log.warning(f"Unexpected data format in '{fname}': {type(data)}")
                    continue
                for pid, pdata in entries:
                    if pid in players:
                        duplicates += 1
                    players[pid] = pdata
                    self.players_file_path[pid] = fpath
                    self.players_sources.setdefault(pid, []).append(fpath)
            except Exception as e:
                log.error(f"Error loading players file '{fname}': {e}")

        if duplicates:
            log.warning(f"{duplicates} player ids are defined in more than one file;"
                  f" the last file read wins.")
        return players
