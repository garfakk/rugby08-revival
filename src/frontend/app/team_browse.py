"""
app/team_browse.py — how the match setup screen can let you reach a team.

Settings > Quick Match Picker offers two ways (STYLES):

  classic  season -> category -> team: the season's own competitions
  groups   group -> team -> season: the team's group (its "group" in the
           team file: France, Celtic, Tier 1 Nations...), which stays the
           same whatever the season, then only the seasons the team has

Pure logic over the DataStore, no Qt: TeamIndex answers "what seasons does
this team have", "what group is it in", "which teams are in that group".
"""
from app.season import nearest_season, season_label

STYLES = [
    ("classic", "Season, category, team"),
    ("groups", "Group, team, season"),
]
STYLE_IDS = [s for s, _label in STYLES]
DEFAULT_STYLE = "classic"

# The groups, in the order the picker cycles them: the id a team file names
# in "group" (the same whatever the picker) and the name this picker shows.
# A group id a team file names that isn't here comes after these, by id,
# shown as it is.
GROUP_LABELS = {
    "international": "International",
    "england": "England",
    "france": "France",
    "other_european": "Other European",
    "southern_hemisphere": "Southern Hemisphere",
}
GROUPS = list(GROUP_LABELS)
# A team file without a "group" (one made before groups existed): its
# latest category says where it goes. The categories themselves stay as the
# classic picker shows them.
CATEGORY_GROUPS = {
    "International": "international",
    "Premiership": "england", "Championship": "england",
    "Top 14": "france", "Pro D2": "france",
    "Celtic League": "other_european", "Pro12": "other_european", "Pro14": "other_european",
    "URC": "other_european", "Italy": "other_european",
    "Super 14": "southern_hemisphere", "Super Rugby": "southern_hemisphere",
}
OTHER_GROUP = "other_european"


def group_label(group):
    """The name the picker shows for a group id."""
    return GROUP_LABELS.get(group, group)


def style_label(style):
    return dict(STYLES).get(style, dict(STYLES)[DEFAULT_STYLE])


class TeamIndex:
    """Seasons and groups of the teams of a DataStore (read live: the data
    can change under it, e.g. after the team editor)."""

    def __init__(self, ds):
        self.ds = ds

    # ── one team ──
    def seasons(self, tid):
        """The team's seasons, oldest first."""
        return sorted(self.ds.teams.get(tid, {}))

    def info(self, tid, season=None):
        """The team block of `season` (the nearest one it has, the latest
        without `season`): {} for an unknown team."""
        have = self.seasons(tid)
        if not have:
            return {}
        return self.ds.teams[tid][nearest_season(have, season) if season else have[-1]]

    def name(self, tid, season=None):
        return self.info(tid, season).get("name", tid)

    def group(self, tid):
        """The team's group: its latest season's "group", else the one of
        its category."""
        info = self.info(tid)
        return (info.get("group") or CATEGORY_GROUPS.get(info.get("category", ""))
                or OTHER_GROUP)

    def span(self, tid):
        """"2007-2026 · 12 seasons" under the team's name."""
        have = self.seasons(tid)
        if not have:
            return ""
        first, last = season_label(have[0]).split("-")[0], have[-1]
        return f"{first}–{last} · {len(have)} season{'s' if len(have) != 1 else ''}"

    # ── lists ──
    def groups(self):
        """Every group with a team, in GROUPS order (others after, by name)."""
        have = {self.group(t) for t in self.ds.teams}
        return [g for g in GROUPS if g in have] + sorted(have - set(GROUPS))

    def in_group(self, group):
        """The group's teams, by name."""
        return sorted((t for t in self.ds.teams if self.group(t) == group),
                      key=lambda t: self.name(t).lower())
