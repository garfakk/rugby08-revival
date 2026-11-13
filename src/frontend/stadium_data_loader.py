"""
stadium_data_loader.py — Loads stadium data from disk.

stadiums/stadiums.json holds the stock stadiums. A folder next to it adds
custom stadiums (or replaces stock ones), like the teams:

    stadiums/Eden Park/eden_park.json
        {"eden_park": {"name": "Eden Park", "country": "New Zealand",
                       "game_id": 49,
                       "scenes": {"day": "eden_park.day.big",
                                  "night": "eden_park.night.big"},
                       "files": {"frontend/textures/stadiums/auckland.d.fsh": "preview.fsh"}}}

game_id = the stock stadium the custom one overwrites in the game (its
slot): for that match its scene packs ("scenes", one per environment, the
stadium's own .big) and any other game file ("files", game path -> file) are
put over the slot's (backend game_files_processor.deploy_stadium_files), and
its name replaces the slot's. "environments" defaults to the scenes'. A key
that is also in stadiums.json replaces that stadium in the lists; a new key
adds one.
"""
import os
import json

from backend.game_specific_variables import STADIUM_SLOTS
from shared.log import get_logger

log = get_logger(__name__)

ENVIRONMENTS = ("day", "night", "overcast", "cold")


def _custom(sid, info, folder, folder_rel):
    """`info` checked and completed (is_custom, environments, paths relative
    to the mod data folder), or None when it can't be played."""
    try:
        game_id = int(info.get("game_id"))
    except (TypeError, ValueError):
        game_id = None
    if game_id not in STADIUM_SLOTS:
        log.warning(f"stadium {sid}: game_id {info.get('game_id')!r} is not a stock stadium, skipped")
        return None
    scenes, files = {}, {}
    for env, name in (info.get("scenes") or {}).items():
        if env not in ENVIRONMENTS:
            log.warning(f"stadium {sid}: unknown environment {env!r}, skipped")
        elif not os.path.isfile(os.path.join(folder, name)):
            log.warning(f"stadium {sid}: {name} not found, {env} skipped")
        else:
            scenes[env] = f"{folder_rel}/{name}"
    for game_path, name in (info.get("files") or {}).items():
        if os.path.isfile(os.path.join(folder, name)):
            files[game_path] = f"{folder_rel}/{name}"
        else:
            log.warning(f"stadium {sid}: {name} not found, skipped")
    if not scenes and not files:
        # name / country only: the stock stadium as it is
        return dict(info, game_id=game_id, is_custom=False)
    envs = [e for e in (info.get("environments") or list(scenes)) if e in ENVIRONMENTS]
    if not envs:
        envs = list(STADIUM_SLOTS[game_id]["scenes"])
    return dict(info, game_id=game_id, is_custom=True, environments=envs,
                scenes=scenes, files=files)


class StadiumDataLoader:
    def __init__(self, stadiums_dir: str):
        self.stadiums_dir = stadiums_dir

    def load_stadiums(self) -> dict:
        """{stadium_id: {...}}: stadiums.json, then the stadium folders."""
        stadiums = {}

        if not os.path.isdir(self.stadiums_dir):
            log.warning(f"stadiums directory not found: {self.stadiums_dir}")
            return stadiums

        stadiums_file = os.path.join(self.stadiums_dir, "stadiums.json")
        if os.path.exists(stadiums_file):
            try:
                with open(stadiums_file, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
                if isinstance(data, dict):
                    stadiums.update(data)
            except Exception as e:
                log.error(f"Error loading stadiums from {stadiums_file}: {e}")

        root = os.path.basename(os.path.normpath(self.stadiums_dir))
        for folder_name in sorted(os.listdir(self.stadiums_dir)):
            folder_path = os.path.join(self.stadiums_dir, folder_name)
            if not os.path.isdir(folder_path):
                continue
            json_path = os.path.join(folder_path, f"{folder_name.lower().replace(' ', '_')}.json")
            if not os.path.exists(json_path):
                continue
            try:
                with open(json_path, "r", encoding="utf-8") as fh:
                    data = json.load(fh)
            except Exception as e:
                log.error(f"Error loading stadium '{folder_name}': {e}")
                continue
            for sid, info in (data.items() if isinstance(data, dict) else ()):
                if not isinstance(info, dict):
                    continue
                checked = _custom(str(sid), info, folder_path, f"{root}/{folder_name}")
                if checked:
                    stadiums[str(sid)] = checked
                    log.debug(f"stadium {sid}: {checked.get('name')} "
                              f"(slot {checked['game_id']}{', custom' if checked['is_custom'] else ''})")

        log.debug(f"Total stadiums loaded: {len(stadiums)}")
        return stadiums
