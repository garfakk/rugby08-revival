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
    # dumps, not dump: only the one-shot encoder runs in C (dump streams
    # through the pure-Python one, ~8x slower on a tournament save)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write(text)
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
    _remember(t)


def load(tid: str) -> Tournament:
    with open(_path(tid), "r", encoding="utf-8") as fh:
        return _from_data(json.load(fh))


def delete(tid: str) -> None:
    for suffix in ("",) + _SNAPSHOTS:
        try:
            os.remove(_path(tid, suffix))
        except FileNotFoundError:
            pass


# Snapshots beside a save, never listed as saves of their own.
_SNAPSHOTS = (".undo", ".prematch", ".last_match")

# Summaries of the saves, kept in a small file beside them so the hub
# doesn't parse every (multi-MB) save each time it opens. An entry is good
# while its save's mtime and size match; save() refreshes its own entry.
_INDEX_NAME = "summaries.cache"
_INDEX_VERSION = 1
_index = None            # {"dir": path, "entries": {tid: {"stamp": [mtime_ns, size], "summary": {...}}}}


def _stamp(path):
    st = os.stat(path)
    return [st.st_mtime_ns, st.st_size]


def _load_index(d) -> dict:
    global _index
    if _index is not None and _index["dir"] == d:
        return _index["entries"]
    entries = {}
    try:
        with open(os.path.join(d, _INDEX_NAME), "r", encoding="utf-8") as fh:
            data = json.load(fh)
        if data.get("version") == _INDEX_VERSION:
            entries = data.get("entries") or {}
    except FileNotFoundError:
        pass
    except Exception as e:
        log.warning("tournament summaries cache unreadable, rebuilding: %s", e)
    _index = {"dir": d, "entries": entries}
    return entries


def _store_index(d) -> None:
    try:
        _write(os.path.join(d, _INDEX_NAME), {"version": _INDEX_VERSION, "entries": _index["entries"]})
    except OSError as e:
        log.warning("tournament summaries cache not written: %s", e)


def summarize(t: Tournament) -> dict:
    """What the hub shows of a save, without the save."""
    from . import report
    template = t.template or {}
    human = [(k, v) for k, v in t.teams.items() if v.human]
    return {
        "id": t.id, "name": t.name or t.id, "template_id": t.template_id,
        "season": t.season, "day": t.day,
        "last_day": max((f.day for f in t.fixtures), default=0),
        "updated": t.updated,
        "humans": [v.name or k for k, v in human],
        "human_ids": [(k, v.season) for k, v in human],
        "options": t.options,
        "played": sum(1 for f in t.fixtures if f.played),
        "total": len(t.fixtures),
        "champion_id": t.champion,
        "champion": (t.teams[t.champion].name if t.champion in t.teams else None) if t.champion else None,
        # the template's look only (the card's emblem and competition name)
        "template": {k: template[k] for k in ("name", "branding", "branding_season") if k in template},
        "where": report.where_now(t),
    }


def _remember(t: Tournament) -> None:
    d = saves_directory()
    entries = _load_index(d)
    try:
        entries[t.id] = {"stamp": _stamp(_path(t.id)), "summary": summarize(t)}
    except Exception as e:
        log.warning("tournament %s summary: %s", t.id, e)
        entries.pop(t.id, None)
    _store_index(d)


def list_saves() -> list:
    """Summaries, most recently updated first: {id, name, template_id,
    season, day, last_day, updated, humans, human_ids [(id, season)],
    options, played, total, champion, champion_id, template (name,
    branding, branding_season), where, has_prematch, error}."""
    out = []
    d = saves_directory()
    entries = _load_index(d)
    seen, changed = set(), False
    for name in os.listdir(d):
        if not name.endswith(".json"):
            continue
        tid = name[:-5]
        if tid.endswith(_SNAPSHOTS):
            continue
        seen.add(tid)
        path = os.path.join(d, name)
        try:
            stamp = _stamp(path)
            hit = entries.get(tid)
            if hit and hit.get("stamp") == stamp:
                summary = dict(hit["summary"])
            else:
                with open(path, "r", encoding="utf-8") as fh:
                    summary = summarize(_from_data(json.load(fh)))
                summary["id"] = tid
                entries[tid] = {"stamp": stamp, "summary": summary}
                changed = True
                summary = dict(summary)
            summary["human_ids"] = [tuple(x) for x in summary.get("human_ids") or []]
            summary["has_prematch"] = os.path.exists(_path(tid, ".prematch"))
            out.append(summary)
        except Exception as e:
            log.warning("unreadable tournament save %s: %s", name, e)
            out.append({"id": tid, "name": tid, "error": str(e)})
    for tid in set(entries) - seen:
        del entries[tid]
        changed = True
    if changed:
        _store_index(d)
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
