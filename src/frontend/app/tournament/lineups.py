"""
tournament/lineups.py — A human team's default lineup, its saved lineups
and the lineups it actually played.

    entry.components["lineups"] = {
        "auto":    bool,          # the best 22 is picked before every match
        "default": lineup,        # what every match starts from otherwise
        "saved":   [lineup + {"name"}],
        "source":  name,          # the saved lineup the default came from
        "played":  {fixture id: lineup},
    }

`source` outlives edits: a default that no longer matches its saved
lineup is that lineup "edited", which can be written back (update) or
thrown away (use it again).
    lineup = {"players": [22 pids], "positions": [...], "roles": {...},
              "set_plays": {...}}

`entry.selection` stays what the engine and the game bridge read: the 22
of the match about to be played. selection.prepare() re-makes it from the
default before each match (covering anyone unavailable), so a change made
for one match only (match setup's squad editor) never reaches the default,
and an injury never rewrites it either.
"""
import copy

from .events import on

KEYS = ("players", "positions", "roles", "set_plays")


def _store(entry) -> dict:
    return entry.components.setdefault("lineups", {})


def clean(sel) -> dict:
    return {k: copy.deepcopy(sel[k]) for k in KEYS if sel.get(k) is not None}


def same(a, b) -> bool:
    return all((a or {}).get(k) == (b or {}).get(k) for k in ("players", "roles", "set_plays"))


# ── the default ──────────────────────────────────────────────────────────
def default(entry) -> dict:
    """The default lineup ({} when there is none). A save from before this
    module adopts the selection the user had picked."""
    st = _store(entry)
    if not st.get("default") and entry.selection.get("manual") and entry.selection.get("players"):
        st["default"] = clean(entry.selection)
    return st.get("default") or {}


def set_default(entry, sel):
    st = _store(entry)
    st["default"] = clean(sel)
    st["auto"] = False


def is_auto(entry) -> bool:
    """Picked automatically before each match: asked for, or never set."""
    return bool(_store(entry).get("auto")) or not default(entry).get("players")


def set_auto(entry, on=True):
    _store(entry)["auto"] = bool(on)


def source(entry):
    """Index of the saved lineup the default was taken from (edited since
    or not), or None."""
    name = _store(entry).get("source")
    if not name:
        return None
    return next((i for i, item in enumerate(saved(entry))
                 if item.get("name", "").lower() == name.lower()), None)


def set_source(entry, name):
    st = _store(entry)
    if name:
        st["source"] = name
    else:
        st.pop("source", None)


# ── saved lineups ────────────────────────────────────────────────────────
def saved(entry) -> list:
    return _store(entry).setdefault("saved", [])


def save_as(entry, name, sel) -> int:
    """Save `sel` under `name` (replacing a lineup of the same name).
    Returns its index."""
    name = name.strip()
    lineups = saved(entry)
    item = dict(clean(sel), name=name)
    set_source(entry, name)
    for i, other in enumerate(lineups):
        if other.get("name", "").lower() == name.lower():
            lineups[i] = item
            return i
    lineups.append(item)
    return len(lineups) - 1


def rename(entry, index, name):
    lineups = saved(entry)
    if 0 <= index < len(lineups) and name.strip():
        if source(entry) == index:
            set_source(entry, name.strip())
        lineups[index]["name"] = name.strip()


def delete(entry, index):
    lineups = saved(entry)
    if 0 <= index < len(lineups):
        if source(entry) == index:
            set_source(entry, None)
        del lineups[index]


def matching(entry, sel):
    """Index of the saved lineup `sel` is, or None."""
    return next((i for i, item in enumerate(saved(entry)) if same(item, sel)), None)


# ── played lineups ───────────────────────────────────────────────────────
def played(t, team_id) -> list:
    """[(fixture, lineup)] of the team's played matches, latest first. A
    match recorded before this module existed falls back to its result's
    players when they are a full 22 in shirt order."""
    entry = t.teams[team_id]
    known = _store(entry).get("played", {})
    out = []
    for f in sorted((f for f in t.fixtures if f.played and f.involves(team_id)),
                    key=lambda f: f.day, reverse=True):
        sel = known.get(f.id)
        if sel is None:
            side = f.result.home if f.result.home.team_id == team_id else f.result.away
            pids = [line.pid for line in side.players if line.pid in t.players]
            if len(pids) == 22 and len(set(pids)) == 22 and all(line.started for line in side.players[:15]):
                sel = {"players": pids}
        if sel and sel.get("players"):
            out.append((f, sel))
    return out


@on("match_completed", priority=20)
def _remember(t, fixture, result, rng):
    for tid in (fixture.home, fixture.away):
        entry = t.teams.get(tid)
        if entry and entry.human and entry.selection.get("players"):
            _store(entry).setdefault("played", {})[fixture.id] = clean(entry.selection)
