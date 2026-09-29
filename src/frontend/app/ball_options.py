"""
app/ball_options.py — the balls the match-setup "ball" picker offers
=====================================================================
No Qt. The match uses ONE ball, the home team's own unless the player picks
another: any team's ball, or a tournament's. An option carries the
`ball_choice` dict app/match_data_builder.py understands (None = the home
team's own) plus the ball pattern on disk ("ball/ball_%.png": 2 frames,
256x128) so the picker can preview it.
"""
import os


def _frames(pattern_path: str) -> list:
    """Existing frame images for a ball pattern. A ".fsh" ball is a ready-made
    texture file the picker cannot draw: no frames."""
    if not pattern_path or pattern_path.lower().endswith(".fsh"):
        return []
    if "%" in pattern_path:
        found = [pattern_path.replace("%", str(i)) for i in (1, 2)]
    else:
        found = [pattern_path]
    return [p for p in found if os.path.isfile(p)]


def _team_pattern(ds, team_id, relative):
    root = ds.teams_folder_path.get(team_id, "")
    return os.path.join(root, relative) if root and relative else ""


def _team_option(ds, slot, side, choice_for_own):
    """The ball of the team in `slot`, labelled with its name and side; None
    when no team is picked. The home team's stays listed even without a ball
    file on disk (it is what the match uses by default; the preview is just
    empty), the away team's only when there is something to pick."""
    if not (slot.team_id and slot.season):
        return None
    info = ds.teams.get(slot.team_id, {}).get(slot.season, {})
    rel = (info.get("ball") or "").strip()
    pattern = _team_pattern(ds, slot.team_id, rel)
    if not choice_for_own and not (_frames(pattern) or pattern.lower().endswith(".fsh")):
        return None
    return {"key": side, "label": f"{info.get('name') or slot.team_id} ({side})",
            "pattern": pattern,
            "choice": None if choice_for_own else
            {"source": "teams_json", "team_id": slot.team_id, "path": rel}}


def list_ball_options(ds, cfg) -> list:
    """[{"key", "label", "choice", "pattern"}]: the home team's ball (first, so
    the default; choice None = what the match uses anyway), the away team's,
    then each tournament's. Entries whose ball is not on disk are left out —
    picking them would only fail at kick-off."""
    options = [o for o in (_team_option(ds, cfg.home, "home", True),
                           _team_option(ds, cfg.away, "away", False)) if o]
    for tid, seasons in ds.tournaments.items():
        folder = ds.tournaments_folder_path.get(tid, "")
        for season in sorted(seasons):
            rel = (seasons[season].get("ball") or "").strip()
            pattern = os.path.join(folder, rel) if folder and rel else ""
            if not (_frames(pattern) or pattern.lower().endswith(".fsh")):
                continue
            options.append({"key": f"tournament:{tid}:{season}",
                            "label": f"{seasons[season].get('name') or tid} (tournament)",
                            "pattern": pattern,
                            "choice": {"source": "tournament", "team_id": tid, "path": rel}})
    return options


def frames_for(option) -> list:
    """Frame image paths to preview for `option`."""
    return _frames(option.get("pattern", "")) if option else []
