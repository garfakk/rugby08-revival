"""
tournament/calendar.py — Real dates for the matchdays.

The scheduler numbers matchdays (Fixture.day); this gives each one a date
so the weather can follow the season (tournament/weather.py). A fixture
pinned to a date by its template (a historical tournament) keeps it; the
other days are spread over the window the template's "calendar" gives,
stage by stage:

  "calendar": {"start": "02-03", "offsets": [0, 7, 21, 35, 42]}
      matchday i of the stage on offsets[i] days after start's Saturday
  "calendar": {"start": "09-02", "end": "05-31"}
      the stage's matchdays spread evenly from start to end
  "calendar": {"start": "10-14", "every": 7}
      one matchday every `every` days (7 when nothing else is given)

A stage takes its own "calendar", else the template's applies to its first
stage; a stage without one starts a week after the previous stage. Dates
are "MM-DD" in the season: season "2024" is 2023-24, so July to December
fall in 2023 and January to June in 2024 (a World Cup in September 2023,
the Six Nations in February 2024). Weekly fixtures land on a Saturday.
"""
from datetime import date, timedelta

DEFAULT = {"start": "09-07", "every": 7}


def _season_year(season) -> int:
    digits = "".join(c for c in str(season or "") if c.isdigit())[:4]
    return int(digits) if len(digits) == 4 else date.today().year


def _md(text, season, after=None):
    """"MM-DD" in the season's calendar, never before `after`."""
    month, day = (int(x) for x in str(text).split("-")[:2])
    year = _season_year(season) - (1 if month >= 7 else 0)
    d = date(year, month, min(day, 28) if month == 2 else day)
    while after is not None and d < after:
        d = date(d.year + 1, d.month, d.day)
    return d


def _saturday(d):
    """The Saturday of d's week (Monday-Sunday)."""
    return d + timedelta(days=5 - d.weekday())


def _stage_dates(spec, n, season, after):
    """n dates for a stage's matchdays."""
    start = _md(spec["start"], season, after) if spec.get("start") else (
        (after or _md(DEFAULT["start"], season)) + timedelta(days=7))
    if after is not None and start <= after:
        start = after + timedelta(days=1)
    if spec.get("offsets"):
        start = _saturday(start)
        offsets = list(spec["offsets"])
        while len(offsets) < n:
            offsets.append(offsets[-1] + 7)
        return [start + timedelta(days=int(o)) for o in offsets[:n]]
    if spec.get("end") and n > 1:
        end = _md(spec["end"], season, start)
        step = (end - start).days / (n - 1)
        out = [start + timedelta(days=round(i * step)) for i in range(n)]
        if step >= 7:
            out = [_saturday(d) for d in out]
            for i in range(1, n):            # snapping must never merge two weeks
                if out[i] <= out[i - 1]:
                    out[i] = out[i - 1] + timedelta(days=7)
        return out
    every = int(spec.get("every", 7))
    first = _saturday(start) if every % 7 == 0 else start
    return [first + timedelta(days=i * every) for i in range(n)]


def assign_dates(t) -> None:
    """Fill in Fixture.date (ISO) for every fixture that has none."""
    tpl = t.template or {}
    pinned = {}
    for f in t.fixtures:
        if f.date:
            pinned.setdefault(f.day, f.date)
    after = None
    day_dates = {}
    for i, stage in enumerate(t.stages):
        days = sorted({f.day for f in t.fixtures if f.stage_id == stage.id})
        if not days:
            continue
        spec = stage.spec.get("calendar") or (tpl.get("calendar") if i == 0 else None) or (
            DEFAULT if i == 0 else {})
        free = [d for d in days if d not in pinned]
        generated = iter(_stage_dates(spec, len(free), t.season, after)) if free else iter(())
        for d in days:
            day_dates[d] = date.fromisoformat(pinned[d]) if d in pinned else next(generated)
        after = max(day_dates[d] for d in days)
    for f in t.fixtures:
        if not f.date and f.day in day_dates:
            f.date = day_dates[f.day].isoformat()


def fixture_date(t, f):
    """The fixture's date (a datetime.date), assigning the tournament's dates
    first if this save predates them."""
    if not f.date:
        assign_dates(t)
    try:
        return date.fromisoformat(f.date)
    except (TypeError, ValueError):
        return None


def short_date(d) -> str:
    """"Sat 8 Feb"."""
    return f"{d.strftime('%a')} {d.day} {d.strftime('%b')}" if d else ""
