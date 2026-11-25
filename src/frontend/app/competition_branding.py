"""
app/competition_branding.py — the competition textures the match-setup
"pitch logo" and "tournament logo" pickers offer, and a competition's whole
dressing applied to a match
=====================================================================
No Qt. A choice key is "<competition id>" for a seasonless competition and
"<competition id>:<season>" for one season of a seasonal competition (e.g.
"world_cup:2007"). A bare id of a seasonal competition still resolves, to
its first season. Only textures present on disk are offered.
"""
import os

from shared.config import config


def choice_key(tid: str, season: str) -> str:
    return f"{tid}:{season}" if season else tid


def resolve(ds, choice: str):
    """(competition id, branding dict) for a choice key; (None, {}) when the
    key names nothing loaded."""
    if not choice:
        return None, {}
    seasons = ds.tournaments.get(choice)
    if seasons:
        return choice, next(iter(seasons.values()))
    tid, _, season = choice.rpartition(":")
    info = ds.tournaments.get(tid, {}).get(season)
    return (tid, info) if info else (None, {})


def _on_disk(folder: str, relative: str) -> bool:
    if not folder or not relative:
        return False
    path = os.path.join(folder, relative)
    if "%" in path:
        return any(os.path.isfile(path.replace("%", str(i))) for i in (1, 2))
    return os.path.exists(path)          # a file, or a set folder (pads / posts / ads)


def label(ds, choice: str) -> str:
    """Display name of a choice key ("World Cup 2007"), the key itself when
    it names nothing loaded."""
    tid, info = resolve(ds, choice)
    if not tid:
        return choice
    season = choice[len(tid) + 1:] if choice != tid else ""
    name = info.get("name") or tid
    return f"{name} {season}" if season else name


def all_choices(ds) -> list:
    """Every competition season with at least one texture: [choice key]."""
    return [choice_key(tid, season) for tid, seasons in ds.tournaments.items() for season in seasons]


def apply(ds, cfg, choice: str, dressing: bool = True) -> bool:
    """Dress match `cfg` in a competition season's textures: tournament
    logo, pitch logo, ball and (`dressing`) its pads, posts and ads sets —
    each only when that season has it on disk, otherwise left as it was.
    False when `choice` names nothing loaded."""
    tid, info = resolve(ds, choice)
    if not tid:
        return False
    folder = ds.tournaments_folder_path.get(tid, "")
    if _on_disk(folder, (info.get("logo") or "").strip()):
        cfg.tournament_logo_choice = choice
    if _on_disk(folder, (info.get("pitch_logo") or "").strip()):
        cfg.pitch_logo_choice = choice
    if dressing:
        for key, attr in (("pads", "pads"), ("posts", "posts"), ("adboards", "adboards")):
            rel = (info.get(key) or "").strip()
            if _on_disk(folder, rel):
                setattr(cfg, attr, os.path.relpath(os.path.join(folder, rel),
                                                   config.mod_data_directory).replace("\\", "/"))
    trophy = info.get("trophy") or {}
    if (isinstance(trophy, dict) and trophy.get("ceremony")
            and all(_on_disk(folder, (trophy.get(k) or "").strip()) for k in ("model", "texture"))):
        # the competition's own trophy, lifted in that ceremony (match_data_builder)
        cfg.trophy = {"ceremony": str(trophy["ceremony"]),
                      **{k: os.path.relpath(os.path.join(folder, trophy[k].strip()),
                                            config.mod_data_directory).replace("\\", "/")
                         for k in ("model", "texture")}}
    ball = (info.get("ball") or "").strip()
    if _on_disk(folder, ball):
        cfg.ball_choice = {"source": "tournament", "team_id": tid, "path": ball}
    return True


def choices(ds, key: str) -> list:
    """[(choice key, label)] of every competition season whose `key` texture
    ("logo", "pitch_logo") exists on disk, e.g.
    ("world_cup:2023", "World Cup 2023")."""
    out = []
    for tid, seasons in ds.tournaments.items():
        folder = ds.tournaments_folder_path.get(tid, "")
        for season, info in seasons.items():
            if not _on_disk(folder, (info.get(key) or "").strip()):
                continue
            name = info.get("name") or tid
            out.append((choice_key(tid, season), f"{name} {season}" if season else name))
    return out


def _files_digest(folder: str, relative: str):
    """md5s of the file(s) a texture setting names (both frames of a "%"
    pattern), None when none can be read."""
    import hashlib
    paths = [relative.replace("%", str(i)) for i in (1, 2)] if "%" in relative else [relative]
    out = []
    for rel in paths:
        try:
            with open(os.path.join(folder, rel), "rb") as fh:
                out.append(hashlib.md5(fh.read()).hexdigest())
        except OSError:
            out.append("")
    return tuple(out) if any(out) else None


def unique_choices(ds, key: str) -> list:
    """choices(), with the seasons of a competition whose `key` textures are
    the same files merged into one entry: its first season's key, labelled
    with the competition's name alone when every season shares them, else
    with the span ("Six Nations 2019–2026")."""
    out = []
    for tid, seasons in ds.tournaments.items():
        folder = ds.tournaments_folder_path.get(tid, "")
        groups = {}                     # digest -> [season], first seen first
        for season, info in seasons.items():
            rel = (info.get(key) or "").strip()
            if not _on_disk(folder, rel):
                continue
            digest = _files_digest(folder, rel) or ("", season)
            groups.setdefault(digest, []).append(season)
        for members in groups.values():
            name = seasons[members[0]].get("name") or tid
            if not members[0]:
                label = name
            elif len(groups) == 1 and len(members) == len(seasons) > 1:
                label = name
            elif len(members) == 1:
                label = f"{name} {members[0]}"
            else:
                label = f"{name} {members[0]}–{members[-1]}"
            out.append((choice_key(tid, members[0]), label))
    return out
