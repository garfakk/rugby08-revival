"""
stadium_data_loader.py — Loads stadium data from disk.
"""
import os
import json


from shared.log import get_logger

log = get_logger(__name__)


class StadiumDataLoader:
    def __init__(self, stadiums_dir: str):
        self.stadiums_dir = stadiums_dir

    def load_stadiums(self) -> dict:
        """
        Return {stadium_id: {...}} from stadiums.json file or from individual stadium folders.
        
        Supports two formats:
        1. Single file: stadiums_dir/stadiums.json
        2. Folder structure: stadiums_dir/Stadium_Name/stadium_name.json
        """
        stadiums = {}
        
        if not os.path.isdir(self.stadiums_dir):
            log.warning(f"stadiums directory not found: {self.stadiums_dir}")
            log.debug(f"  Looking for: {self.stadiums_dir}")
            return stadiums

        log.debug(f"Loading stadiums from: {self.stadiums_dir}")

        # Try to load from single stadiums.json file first
        stadiums_file = os.path.join(self.stadiums_dir, "stadiums.json")
        log.debug(f"Checking for stadiums.json at: {stadiums_file}")
        log.debug(f"File exists: {os.path.exists(stadiums_file)}")
        
        if os.path.exists(stadiums_file):
            try:
                with open(stadiums_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                    if isinstance(data, dict):
                        stadiums.update(data)
                        log.debug(f"Loaded {len(stadiums)} stadiums from stadiums.json")
                        return stadiums
            except Exception as e:
                log.error(f"Error loading stadiums from {stadiums_file}: {e}")

        # Fall back to folder-based structure (like teams)
        log.debug(f"No stadiums.json found, checking folder structure in {self.stadiums_dir}")
        items = os.listdir(self.stadiums_dir)
        log.debug(f"Items in stadiums directory: {items}")
        
        for folder_name in items:
            folder_path = os.path.join(self.stadiums_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            stadium_filename = folder_name.lower().replace(" ", "_")
            json_path = os.path.join(folder_path, f"{stadium_filename}.json")
            if not os.path.exists(json_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                stadiums.update(data)
            except Exception as e:
                log.error(f"Error loading stadium '{folder_name}': {e}")

        log.debug(f"Total stadiums loaded: {len(stadiums)}")
        return stadiums


