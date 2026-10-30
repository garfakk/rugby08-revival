"""
tournament/persistence.py — Tournament saves.

One JSON file per tournament in config.directory_tournament_saves
(user_data/tournaments; never mod_data, which a data update replaces).
Beside it:
  <id>.undo.json      the state before the last recorded result(s), for
                      "undo last result"
  <id>.prematch.json  written just before the game is launched for a user
                      match; if the app dies mid-match it is still there
                      on the next start and the hub offers to resume.

Every write is atomic (temp file + os.replace). Older saves are upgraded by
MIGRATIONS, keyed by the version they upgrade *from*; additive features
need no migration (see model.py).
"""
import json
import os
from datetime import datetime

from shared.log import get_logger

from .model import SCHEMA_VERSION, Tournament

log = get_logger(__name__)

# from_version -> fn(dict) -> dict (for from_version + 1)
MIGRATIONS = {}


def saves_directory() -> str:
    from shared.config import config
    d = config.directory_tournament_saves
    os.makedirs(d, exist_ok=True)
    return d


def _path(tid, suffix="") -> str:
    return os.path.join(saves_directory(), f"{tid}{suffix}.json")


def _write(path, data) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, ensure_ascii=False, separators=(",", ":"))
    os.replace(tmp, path)


def migrate(data: dict) -> dict:
    version = int(data.get("schema_version", 0))
    while version < SCHEMA_VERSION:
        fn = MIGRATIONS.get(version)
        if fn is None:
            raise ValueError(f"no migration from tournament save version {version}")
        data = fn(data)
        version += 1
        data["schema_version"] = version
    if version > SCHEMA_VERSION:
        raise ValueError(f"save version {version} is newer than this build ({SCHEMA_VERSION})")
    return data


def _from_data(data) -> Tournament:
    t = Tournament.from_dict(migrate(data))
    # older saves labelled a one-league stage's fixtures "Table · Round 2"
    for stage in t.stages:
        if stage.kind == "round_robin" and len(stage.groups) == 1:
            prefix = f"{stage.groups[0].name} · "
            for f in t.fixtures:
                if f.stage_id == stage.id and f.label.startswith(prefix):
                    f.label = f.label[len(prefix):]
    return t


def save(t: Tournament) -> None:
    t.updated = datetime.now().isoformat(timespec="seconds")
    _write(_path(t.id), t.to_dict())


def load(tid: str) -> Tournament:
    with open(_path(tid), "r", encoding="utf-8") as fh:
        return _from_data(json.load(fh))


def delete(tid: str) -> None:
    for suffix in ("", ".undo", ".prematch"):
        try:
            os.remove(_path(tid, suffix))
        except FileNotFoundError:
            pass


def list_saves() -> list:
    """Summaries, most recently updated first: {id, name, template_id,
    season, day, last_day, updated, humans, human_ids [(id, season)],
    options, played, total, champion, champion_id, error}."""
    out = []
    d = saves_directory()
    for name in os.listdir(d):
        if not name.endswith(".json") or name.endswith((".undo.json", ".prematch.json", ".tmp")):
            continue
        tid = name[:-5]
        try:
            with open(os.path.join(d, name), "r", encoding="utf-8") as fh:
                data = json.load(fh)
            teams = data.get("teams", {})
            out.append({
                "id": tid, "name": data.get("name", tid), "template_id": data.get("template_id", ""),
                "season": data.get("season", ""), "day": data.get("day", 0),
                "last_day": max((f.get("day", 0) for f in data.get("fixtures", [])), default=0),
                "updated": data.get("updated", ""),
                "humans": [v.get("name", k) for k, v in teams.items() if v.get("human")],
                "human_ids": [(k, v.get("season", "")) for k, v in teams.items() if v.get("human")],
                "options": data.get("options", {}),
                "played": sum(1 for f in data.get("fixtures", []) if f.get("result")),
                "total": len(data.get("fixtures", [])),
                "champion_id": data.get("champion"),
                "champion": teams.get(data.get("champion"), {}).get("name") if data.get("champion") else None,
                "has_prematch": os.path.exists(_path(tid, ".prematch")),
            })
        except Exception as e:
            log.warning("unreadable tournament save %s: %s", name, e)
            out.append({"id": tid, "name": tid, "error": str(e)})
    out.sort(key=lambda s: s.get("updated", ""), reverse=True)
    return out


# ── undo / pre-match snapshots ────────────────────────────────────────────

def snapshot(t: Tournament, kind: str) -> None:
    _write(_path(t.id, f".{kind}"), t.to_dict())


def has_snapshot(tid: str, kind: str) -> bool:
    return os.path.exists(_path(tid, f".{kind}"))


def restore_snapshot(tid: str, kind: str) -> Tournament:
    with open(_path(tid, f".{kind}"), "r", encoding="utf-8") as fh:
        return _from_data(json.load(fh))


def drop_snapshot(tid: str, kind: str) -> None:
    try:
        os.remove(_path(tid, f".{kind}"))
    except FileNotFoundError:
        pass
