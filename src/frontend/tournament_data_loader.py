"""
tournament_data_loader.py — Loads competition branding packs (ball, logo, pads, pitch logos) from disk.
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


def _read(path: str):
    with open(path, "r", encoding="utf-8") as fh:
        return _parse_relaxed_json(fh.read())


# Branding fields holding a path (relative to the competition folder).
_ASSET_KEYS = ("ball", "pads", "logo", "pitch_logo", "adboards")


class TournamentDataLoader:
    def __init__(self, tournaments_dir: str):
        self.tournaments_dir = tournaments_dir
        self.tournaments_folder_path: dict[str, str] = {}

    def load_tournaments(self) -> dict:
        """Return {tournament_id: {season: {...}}} for every competition found.

        Each competition folder has a single definition at its root,
        <competitions>/<competition>/<competition>.json:

          {"id": "5002", "name": "Top 14", "seasonal": false,
           "ball": "...", "pads": "...", "logo": "...", "pitch_logo": "...",
           "adboards": "...",                    # optional FSH, relative to competition folder
           "template": {...}}                       # optional, app/tournament/formats.py

          {"id": "world_cup", "name": "World Cup", "seasonal": true,
           "seasons": {"2023": {"ball": "...", "logo": "...", "template": {...}}}}

        A seasonless competition has a single entry under the season "". A
        seasonal one has an entry per season, its fields overriding the root
        ones. Asset paths are relative to the competition folder
        (tournaments_folder_path).
        """
        tournaments = {}
        if not os.path.isdir(self.tournaments_dir):
            log.warning(f"competitions directory not found: {self.tournaments_dir}")
            return tournaments

        for folder_name in sorted(os.listdir(self.tournaments_dir)):
            folder_path = os.path.join(self.tournaments_dir, folder_name)
            json_path = os.path.join(folder_path, f"{folder_name.lower().replace(' ', '_')}.json")
            if not os.path.isfile(json_path):
                continue
            try:
                seasons = self._load_competition(folder_path, _read(json_path))
            except Exception as e:
                log.error(f"Error loading competition '{folder_name}': {e}")
                continue
            if seasons:
                tournament_id = seasons.pop("_id")
                self.tournaments_folder_path[tournament_id] = folder_path
                tournaments[tournament_id] = seasons

        return tournaments

    @staticmethod
    def _load_competition(folder_path: str, definition: dict) -> dict:
        """{"_id": id, season: branding} for one competition definition;
        seasons without any branding asset are left out."""
        base = {k: v for k, v in definition.items()
                if k not in ("id", "seasonal", "seasons", "template")}
        base.setdefault("name", os.path.basename(folder_path))
        if definition.get("seasonal", False):
            seasons = {str(year): {**base, **{k: v for k, v in info.items() if k != "template"}}
                       for year, info in sorted(definition.get("seasons", {}).items())}
        else:
            seasons = {"": base}
        seasons = {s: info for s, info in seasons.items()
                   if any(info.get(k) for k in _ASSET_KEYS)}
        if seasons:
            seasons["_id"] = str(definition.get("id") or os.path.basename(folder_path))
        return seasons
