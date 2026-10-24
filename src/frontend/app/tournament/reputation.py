"""
tournament/reputation.py — How strong a side is beyond its players' ratings.

The data's player ratings hardly separate the nations (most squads average
within a few points of each other, and attack/defence sit at 99 for nearly
everyone), so a simulator driven by them alone lets Namibia beat the All
Blacks far too often. Each team therefore also has a *reputation*, on the
World Rugby rankings points scale (~60 for a tier-2 side, ~90 for the best
in the world), and the simulator gives the stronger reputation an edge on
top of what the selected XV's ratings say.

Where a team's reputation comes from, first found wins:
  1. "reputation" in the team's season block in the team data (lets a
     modder rate a custom side or re-rate a real one),
  2. the built-in table below, by team name and the era closest to the
     tournament season,
  3. the mean of the field's other reputations (an unknown side is treated
     as an average participant).

It is fixed for the tournament at creation (TeamEntry.components) so a
save keeps its balance; saves made before reputations get one on first use.
"""
import re
import unicodedata

# Team name -> {era year: rankings-style points}. The era closest to the
# tournament season's year is used. 2008: the end of the 2007 World Cup
# cycle (the original Rugby 08 rosters); 2010: the club seasons of that
# time; 2024: after the 2023 World Cup.
TABLE = {
    # nations
    "south africa": {2008: 91, 2024: 92},
    "new zealand": {2008: 90, 2024: 90},
    "ireland": {2008: 80, 2024: 91},
    "france": {2008: 84, 2024: 87},
    "england": {2008: 82, 2024: 84},
    "argentina": {2008: 85, 2024: 83},
    "scotland": {2008: 79, 2024: 82},
    "australia": {2008: 85, 2024: 80},
    "fiji": {2008: 77, 2024: 80},
    "italy": {2008: 76, 2024: 78},
    "wales": {2008: 79, 2024: 77},
    "georgia": {2008: 68, 2024: 76},
    "japan": {2008: 66, 2024: 74},
    "samoa": {2008: 73, 2024: 72},
    "tonga": {2008: 72, 2024: 71},
    "portugal": {2008: 62, 2024: 70},
    "spain": {2008: 61, 2024: 67},
    "uruguay": {2008: 62, 2024: 67},
    "usa": {2008: 64, 2024: 66},
    "united states": {2008: 64, 2024: 66},
    "romania": {2008: 66, 2024: 63},
    "chile": {2008: 58, 2024: 62},
    "russia": {2008: 64, 2024: 61},
    "canada": {2008: 69, 2024: 61},
    "namibia": {2008: 59, 2024: 61},
    # French clubs (Top 14 / European Cup)
    "toulouse": {2010: 87, 2024: 89},
    "bordeaux begles": {2010: 76, 2024: 87},
    "bordeaux": {2010: 76, 2024: 87},
    "toulon": {2010: 81, 2024: 84},
    "la rochelle": {2010: 72, 2024: 84},
    "racing 92": {2010: 80, 2024: 83},
    "racing metro": {2010: 80, 2024: 83},
    "clermont": {2010: 86, 2024: 81},
    "castres": {2010: 81, 2024: 81},
    "bayonne": {2010: 76, 2024: 81},
    "paris": {2010: 82, 2024: 80},
    "stade francais": {2010: 82, 2024: 80},
    "pau": {2010: 72, 2024: 80},
    "montpellier": {2010: 79, 2024: 79},
    "lyon": {2010: 73, 2024: 79},
    "perpignan": {2010: 84, 2024: 78},
    "biarritz": {2010: 82, 2024: 72},
    "brive": {2010: 77, 2024: 73},
    "agen": {2010: 74, 2024: 71},
    "oyonnax": {2010: 71, 2024: 75},
    "vannes": {2010: 66, 2024: 74},
}
DEFAULT = 75.0


def _key(name) -> str:
    text = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _year(season) -> int:
    m = re.search(r"\d{4}", str(season or ""))
    return int(m.group()) if m else 2024


def lookup(name, season):
    """The built-in reputation for `name` in `season`, or None."""
    eras = TABLE.get(_key(name))
    if not eras:
        return None
    year = _year(season)
    return float(eras[min(eras, key=lambda y: (abs(y - year), -y))])


def assign(ds, t) -> None:
    """Give every team of a new tournament its reputation (see the module
    docstring for the order)."""
    for tid, entry in t.teams.items():
        info = ds.team_season(tid, entry.season, entry.variant) if ds is not None else {}
        value = _number(info.get("reputation"))
        if value is None:
            value = lookup(entry.name, entry.season)
        if value is not None:
            entry.components["reputation"] = value
    _fill_unknown(t)


def _number(value):
    try:
        return max(0.0, min(100.0, float(value)))
    except (TypeError, ValueError):
        return None


def _fill_unknown(t) -> None:
    known = []
    for entry in t.teams.values():
        if "reputation" not in entry.components:
            value = lookup(entry.name, entry.season)
            if value is not None:
                entry.components["reputation"] = value
        if "reputation" in entry.components:
            known.append(entry.components["reputation"])
    mean = round(sum(known) / len(known), 1) if known else DEFAULT
    for entry in t.teams.values():
        entry.components.setdefault("reputation", mean)


def reputation(t, team_id) -> float:
    entry = t.teams.get(team_id)
    if entry is None:
        return DEFAULT
    if "reputation" not in entry.components:
        _fill_unknown(t)
    return float(entry.components["reputation"])
