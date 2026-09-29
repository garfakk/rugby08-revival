"""
tournament_data_loader.py — Loads tournament data from disk.
"""
import os
import re
import json


from shared.log import get_logger

log = get_logger(__name__)


def _parse_relaxed_json(text: str):
    """Parse JSON that may contain trailing commas."""
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    return json.loads(cleaned)


class TournamentDataLoader:
    def __init__(self, tournaments_dir: str):
        self.tournaments_dir = tournaments_dir
        self.tournaments_folder_path: dict[str, str] = {}

    def load_tournaments(self) -> dict:
        """Return {tournament_id: {season: {...}}} for every tournament folder found."""
        tournaments = {}
        if not os.path.isdir(self.tournaments_dir):
            log.warning(f"tournaments directory not found: {self.tournaments_dir}")
            return tournaments

        for folder_name in os.listdir(self.tournaments_dir):
            folder_path = os.path.join(self.tournaments_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            json_filename = folder_name.lower().replace(" ", "_")
            json_path = os.path.join(folder_path, f"{json_filename}.json")
            if not os.path.exists(json_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    data = _parse_relaxed_json(fh.read())
                tournament_id = next(iter(data))
                self.tournaments_folder_path[tournament_id] = folder_path
                tournaments.update(data)
            except Exception as e:
                log.error(f"Error loading tournament '{folder_name}': {e}")

        return tournaments
