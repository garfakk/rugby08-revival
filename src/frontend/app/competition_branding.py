"""
app/competition_branding.py — the competition textures the match-setup
"pitch logo", "tournament logo" and "stadium graphics" pickers offer
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
    return os.path.isfile(path)


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


def apply(ds, cfg, choice: str) -> bool:
    """Dress match `cfg` in a competition season's textures: tournament
    logo, stadium graphics ("pads"), pitch logo, adboards and ball — each only when
    that season has the file on disk, otherwise left as it was. False when
    `choice` names nothing loaded."""
    tid, info = resolve(ds, choice)
    if not tid:
        return False
    folder = ds.tournaments_folder_path.get(tid, "")
    if _on_disk(folder, (info.get("logo") or "").strip()):
        cfg.tournament_logo_choice = choice
    if _on_disk(folder, (info.get("pads") or "").strip()):
        cfg.stadium_graphics_choice = choice
    if _on_disk(folder, (info.get("pitch_logo") or "").strip()):
        cfg.pitch_logo_choice = choice
    adboards = (info.get("adboards") or "").strip()
    if _on_disk(folder, adboards):
        cfg.adboards = os.path.relpath(os.path.join(folder, adboards),
                                       config.mod_data_directory).replace("\\", "/")
    ball = (info.get("ball") or "").strip()
    if _on_disk(folder, ball):
        cfg.ball_choice = {"source": "tournament", "team_id": tid, "path": ball}
    return True


def choices(ds, key: str) -> list:
    """[(choice key, label)] of every competition season whose `key` texture
    ("logo", "pads", "pitch_logo") exists on disk, e.g.
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
