"""
app/team_browse.py — how the match setup screen can let you reach a team.

The classic screen asks season -> category -> team. Settings > Quick Match
Picker offers other ways (STYLES), which all start from the team:

  team_first  the team name cycles through the teams of its kind; the season
              row only lists the seasons that team has
  browser     the same, and A / a click on the name opens a searchable list
              of every team, grouped by kind, with the season span of each
  timeline    team first, its seasons on a timeline (gaps visible)
  era         team first, plus an ERA in the match column: both teams from
              one season
  leagues     the browser with stable league names (Celtic League, Pro14 and
              URC are one group) and competition filters (Six Nations...)

Pure logic over the DataStore, no Qt: TeamIndex answers "what seasons does
this team have", "which teams are like it", "what group is it listed under".
"""
import re

from app.season import nearest_season, season_label

STYLES = [
    ("classic", "Classic: season, category, team"),
    ("team_first", "Team first, then its seasons"),
    ("browser", "Team browser with search"),
    ("timeline", "Team first, seasons on a timeline"),
    ("era", "Team first, with an era for both"),
    ("leagues", "Browser with leagues and competitions"),
]
STYLE_IDS = [s for s, _label in STYLES]
DEFAULT_STYLE = "classic"

# A league that changed its name keeps one group: the name of the latest one.
LEAGUE_FAMILIES = {"Celtic League": "URC", "Pro14": "URC", "URC": "URC",
                   "Super 14": "Super Rugby", "Super Rugby": "Super Rugby"}
# Competitions a team can be filtered by, from the tournament templates:
# template id prefix -> label.
COMPETITION_LABELS = {"six_nations": "Six Nations", "rwc": "World Cup"}


def family_of(category):
    return LEAGUE_FAMILIES.get(category, category or "Other")


def style_label(style):
    return dict(STYLES).get(style, dict(STYLES)[DEFAULT_STYLE])


def competitions(templates, participants_of):
    """{label: {team ids}} for the competitions teams can be filtered by:
    the teams of every edition of a template family (Six Nations, World
    Cup...). `participants_of(template)` gives {stage: {group: [team ids]}}."""
    out = {}
    for tid, tpl in (templates or {}).items():
        label = next((lab for prefix, lab in COMPETITION_LABELS.items() if tid.startswith(prefix)), None)
        if not label:
            continue
        try:
            parts = participants_of(tpl)
        except Exception:
            continue
        for groups in parts.values():
            for teams in groups.values():
                out.setdefault(label, set()).update(str(t) for t in teams)
    return out


class TeamIndex:
    """Seasons, kinds and groups of the teams of a DataStore (read live: the
    data can change under it, e.g. after the team editor)."""

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

    def category(self, tid, season=None):
        return self.info(tid, season).get("category", "")

    def group(self, tid, stable=False):
        """What the team is listed under: its latest category, or with
        `stable` the family of that league (URC for Pro14 / Celtic League)."""
        cat = self.category(tid)
        return family_of(cat) if stable else (cat or "Other")

    def span(self, tid):
        """"2007-2026 · 12 seasons" for the browser."""
        have = self.seasons(tid)
        if not have:
            return ""
        first, last = season_label(have[0]).split("-")[0], have[-1]
        return f"{first}–{last} · {len(have)} season{'s' if len(have) != 1 else ''}"

    # ── lists ──
    def all_teams(self):
        return sorted(self.ds.teams, key=lambda t: self.name(t).lower())

    def like(self, tid, stable=False, season=None):
        """The teams of the same kind as `tid` (same group), by name; with
        `season` only those that have that season."""
        group = self.group(tid, stable)
        out = [t for t in self.all_teams() if self.group(t, stable) == group
               and (not season or season in self.ds.teams[t])]
        return out

    def groups(self, team_ids, stable=False):
        """[(group, [tid])] in a stable order: international first, then by
        name; the teams by name within."""
        by = {}
        for t in team_ids:
            by.setdefault(self.group(t, stable), []).append(t)
        order = sorted(by, key=lambda g: (g.lower() != "international", g.lower()))
        return [(g, sorted(by[g], key=lambda t: self.name(t).lower())) for g in order]

    def filters(self, comps=None, stable=True):
        """[(label, predicate(tid))] for the browser's filter chips: ALL,
        the groups with at least a few teams, then the competitions."""
        out = [("ALL", lambda t: True)]
        groups = {}
        for t in self.ds.teams:
            groups.setdefault(self.group(t, stable), set()).add(t)
        for g in sorted(groups, key=lambda g: (g.lower() != "international", g.lower())):
            if len(groups[g]) >= 3:
                out.append((g.upper(), lambda t, s=groups[g]: t in s))
        for label, teams in sorted((comps or {}).items()):
            if teams & set(self.ds.teams):
                out.append((label.upper(), lambda t, s=teams: t in s))
        return out


def search_match(query, name):
    """Every word of the query starts a word of the name (accents and case
    ignored enough for team names): "all bl" finds "All Blacks"."""
    words = re.findall(r"\w+", str(query or "").lower())
    parts = re.findall(r"\w+", str(name or "").lower())
    return all(any(p.startswith(w) for p in parts) for w in words)
