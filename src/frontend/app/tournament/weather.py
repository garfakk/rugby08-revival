"""
tournament/weather.py — The conditions a fixture is played in.

forecast(t, fixture) rolls, from the fixture's date (tournament/calendar.py)
and its ground's climate, the temperature, rain or snow, the kick-off (day
or evening) and from those:
  * the lighting environment — one the stadium actually has (stadiums.json
    "environments": day / night / overcast / cold),
  * the pitch texture (a gsv.pitch_textures name: hard and dry in a warm
    dry spell, worn and muddy in a wet winter, frosty or snow-covered in a
    freeze), in the light variant that matches the environment,
  * cold breath, and how many players would wear baselayers or gloves
    (worked out, not applied to players yet).
It is seeded per fixture (engine.fixture_rng), so a fixture always gets the
same weather, before and after it is played.

The bridge applies it to the game's match (to_match_config), the simulator
reads it (wet ball: fewer tries, harder kicks) and the dashboard shows it.
"""
import math

from . import calendar

# Monthly match-time temperature (°C) and chance of rain during a match,
# January first.
CLIMATES = {
    "uk": ([6, 6, 9, 12, 15, 18, 20, 20, 17, 13, 9, 7],
           [.38, .32, .32, .28, .27, .25, .27, .28, .28, .34, .38, .38]),
    "celtic": ([6, 6, 8, 11, 14, 16, 18, 18, 16, 12, 8, 6],
               [.45, .40, .40, .35, .33, .33, .35, .38, .38, .43, .45, .47]),
    "scotland": ([5, 5, 7, 10, 13, 15, 17, 17, 15, 11, 7, 5],
                 [.45, .40, .40, .33, .30, .30, .33, .36, .38, .43, .45, .47]),
    "france": ([7, 8, 12, 15, 19, 22, 25, 25, 21, 16, 11, 8],
               [.30, .27, .27, .27, .27, .22, .18, .18, .22, .28, .30, .30]),
    "france_south": ([11, 12, 15, 17, 21, 26, 29, 29, 25, 20, 14, 11],
                     [.20, .18, .20, .22, .20, .12, .07, .10, .15, .22, .22, .20]),
    "italy": ([12, 13, 16, 19, 23, 28, 31, 31, 27, 22, 16, 13],
              [.22, .22, .20, .22, .18, .10, .06, .08, .15, .22, .25, .25]),
    "georgia": ([6, 8, 12, 17, 22, 27, 30, 30, 25, 19, 12, 8],
                [.15, .18, .22, .25, .25, .22, .15, .15, .15, .18, .15, .15]),
    "new_zealand": ([21, 21, 19, 17, 14, 12, 11, 12, 13, 15, 17, 19],
                    [.25, .22, .25, .28, .32, .38, .38, .38, .32, .30, .28, .27]),
    "south_africa": ([27, 27, 25, 22, 20, 17, 17, 20, 23, 25, 26, 27],
                     [.30, .28, .25, .15, .08, .05, .05, .06, .10, .18, .25, .28]),
    "australia": ([27, 27, 25, 22, 19, 16, 15, 17, 20, 22, 24, 26],
                  [.20, .22, .22, .18, .18, .18, .15, .12, .12, .15, .18, .18]),
    "argentina": ([29, 28, 25, 21, 18, 14, 14, 16, 18, 21, 24, 27],
                  [.18, .18, .20, .15, .12, .12, .10, .10, .12, .18, .18, .18]),
    "pacific_northwest": ([6, 8, 10, 13, 17, 20, 22, 22, 19, 14, 9, 6],
                          [.55, .45, .45, .35, .30, .25, .15, .15, .25, .45, .55, .55]),
    "california": ([14, 16, 17, 18, 19, 21, 21, 22, 23, 21, 17, 14],
                   [.30, .30, .25, .12, .05, .02, .01, .01, .03, .10, .20, .30]),
    "tropical": ([30, 30, 30, 29, 28, 27, 26, 26, 27, 28, 29, 30],
                 [.45, .45, .45, .38, .30, .25, .22, .22, .25, .30, .35, .42]),
    "japan": ([9, 10, 13, 18, 22, 25, 29, 30, 27, 21, 16, 11],
              [.15, .20, .30, .32, .35, .45, .40, .35, .45, .38, .25, .15]),
}
DEFAULT_CLIMATE = "uk"
# Grounds whose climate isn't their listed country's (some are listed under
# the wrong one in the data). Matched as lowercase words of the name.
_BY_NAME = {
    "brisbane": "australia", "sydney": "australia", "canberra": "australia", "perth": "australia",
    "buenos": "argentina", "vancouver": "pacific_northwest", "san francisco": "california",
    "suva": "tropical", "perpignan": "france_south", "marseille": "france_south",
    "toulouse": "france_south", "castres": "france_south", "murrayfield": "scotland",
}
_BY_COUNTRY = {
    "england": "uk", "wales": "celtic", "ireland": "celtic", "scotland": "scotland",
    "france": "france", "italy": "italy", "georgia": "georgia", "new zealand": "new_zealand",
    "south africa": "south_africa", "australia": "australia", "argentina": "argentina",
    "americas": "pacific_northwest", "asia pacific": "tropical", "fiji": "tropical",
    "japan": "japan", "usa": "california",
}

NIGHT_SHARE = 0.4             # evening kick-offs, unless the template says ("night_share")
COLD = 6                      # °C at or below which the "cold" environment is preferred
BREATH = 8                    # °C at or below which breath shows
WET_SEASON = 0.27             # a month's rain chance from which pitches are worn and muddy
RAIN_SCALE = 0.8              # CLIMATES' rain chances are "a wet day"; this makes them "rain during the match"

# Pitch conditions available per region pack, with their light variants
# (from gsv.pitch_textures).
_TEXTURES = None


def textures():
    global _TEXTURES
    if _TEXTURES is None:
        try:
            from backend import game_specific_variables as gsv
            names = list(gsv.pitch_textures)
        except Exception:
            names = []
        _TEXTURES = set(names)
    return _TEXTURES


def climate_of(stadium) -> str:
    name = str((stadium or {}).get("name", "")).lower()
    for word, climate in _BY_NAME.items():
        if word in name:
            return climate
    return _BY_COUNTRY.get(str((stadium or {}).get("country", "")).lower(), DEFAULT_CLIMATE)


def stadium_info(t, fixture, ds=None) -> dict:
    """{name, country, environments} of the fixture's ground: from the
    data store when given, else the copy kept with the tournament."""
    sid = str(fixture.stadium_id or "")
    if ds is not None and sid in getattr(ds, "stadiums", {}):
        return ds.stadiums[sid]
    return (t.components.get("stadiums") or {}).get(sid, {})


def keep_stadiums(t, ds) -> None:
    """Store what the weather needs of every stadium with the tournament,
    so the simulator (which has no data store) knows the grounds."""
    t.components["stadiums"] = {
        str(sid): {"name": info.get("name", ""), "country": info.get("country", ""),
                   "environments": list(info.get("environments") or [])}
        for sid, info in (getattr(ds, "stadiums", None) or {}).items()}


def _interp(monthly, d):
    """The monthly value at date d, interpolated between month middles."""
    pos = d.month - 1 + (d.day - 15) / 30.0
    lo = math.floor(pos)
    frac = pos - lo
    return monthly[lo % 12] * (1 - frac) + monthly[(lo + 1) % 12] * frac


def _environment(envs, temp, night, wet, cloudy):
    envs = envs or ["day"]
    if temp <= COLD:
        prefs = ["cold", "night" if night else "overcast", "overcast", "night", "day"]
    elif night:
        prefs = ["night"] + (["cold"] if temp <= COLD + 2 else []) + ["overcast", "day"]
    elif wet or cloudy:
        prefs = ["overcast"] + (["cold"] if temp <= COLD + 2 else []) + ["day", "night"]
    else:
        prefs = ["day", "overcast", "night"]
    return next((e for e in prefs if e in envs), envs[0])


_LIGHT = {"day": "d", "night": "n", "overcast": "o", "cold": "o"}
# When a condition has no texture in the wanted light / region, the closest
# condition that may.
_FALLBACK = {"snow": ["frosty", "muddier", "norm"], "frosty": ["snow", "norm"],
             "muddier": ["muddy", "light_Mud", "soggy", "norm"], "muddy": ["light_Mud", "muddier", "soggy", "norm"],
             "light_Mud": ["soggy", "muddy", "norm"], "soggy": ["light_Mud", "norm"],
             "hard": ["dry", "best", "norm"], "dry": ["hard", "best", "norm"], "best": ["norm"], "norm": ["best"]}


def pitch_texture(condition, environment, region="Reg2") -> str:
    """The texture name for a condition in a light, falling back to the
    nearest available one; "default" when nothing matches."""
    have = textures()
    light = _LIGHT.get(environment, "d")
    lights = [light] + [x for x in ("o", "n", "d") if x != light]
    regions = [region] + [r for r in ("Reg2", "Reg3", "Reg1", "Reg4") if r != region]
    # the right light matters more than the exact condition: a night
    # match on a day-lit texture looks wrong, "muddy" for "muddier" doesn't
    conditions = [condition] + _FALLBACK.get(condition, [])
    for lt in lights:
        for cond in conditions:
            for reg in regions:
                name = f"{reg}_08_{cond}_{lt}"
                if name in have:
                    return name
    return "default"


def forecast(t, fixture, ds=None) -> dict:
    """The fixture's weather (see the module docstring). Keys: date, temp,
    precip ("none"/"rain"/"snow"), heavy, night, environment, pitch,
    condition, breath, baselayers / gloves (share of players who would
    wear them — not applied to players yet),
    summary ("6°C · heavy rain · evening")."""
    from .engine import fixture_rng
    rng = fixture_rng(t, fixture, "weather")
    d = calendar.fixture_date(t, fixture)
    stadium = stadium_info(t, fixture, ds)
    # a template played on stand-in grounds names the host country's climate
    # (RWC 2019: Japanese autumn at grounds the game doesn't have)
    climate = (t.template or {}).get("climate")
    climate = climate if climate in CLIMATES else climate_of(stadium)
    temps, rains = CLIMATES[climate]
    if d is None:
        temp_mean, rain_chance = 14.0, 0.25
    else:
        temp_mean, rain_chance = _interp(temps, d), _interp(rains, d) * RAIN_SCALE
    night = rng.random() < float((t.template or {}).get("night_share", NIGHT_SHARE)
                                 + (0.3 if temp_mean >= 26 else 0.0))
    temp = rng.gauss(temp_mean, 3.0) - (3.0 if night else 0.0)
    precip, heavy = "none", False
    if rng.random() < rain_chance:
        heavy = rng.random() < 0.35
        precip = "snow" if temp <= -1 else "rain"        # sleet around freezing reads as rain
    cloudy = precip != "none" or rng.random() < min(0.85, rain_chance * 1.4 + 0.15)
    environment = _environment(stadium.get("environments"), temp, night, precip != "none", cloudy)
    # the ground's lighting decides what the kick-off can look like
    if environment == "night":
        night = True
    elif environment == "day":
        night = False

    wet_season = rain_chance >= WET_SEASON
    roll = rng.random()
    if precip == "snow" or (temp <= -2 and roll < 0.3):
        condition = "snow"
    elif temp <= 1 and precip == "none":
        condition = "frosty"
    elif precip == "rain":
        condition = ("muddier" if wet_season else "muddy") if heavy else ("light_Mud" if wet_season else "soggy")
    elif wet_season and temp <= 12:
        condition = "soggy" if roll < 0.25 else ("light_Mud" if roll < 0.4 else "norm")
    elif temp >= 22 and rain_chance <= 0.15:
        condition = "hard" if roll < 0.5 else "dry"
    else:
        condition = "best" if roll < 0.5 else "norm"
    dry_climate = climate in ("south_africa", "australia", "argentina", "california", "italy")
    region = "Reg3" if dry_climate and condition in ("hard", "dry", "best") else "Reg2"

    if temp <= 4:
        baselayers = 0.7
    elif temp <= 8:
        baselayers = 0.45
    elif temp <= 12:
        baselayers = 0.2
    else:
        baselayers = 0.05
    words = [f"{round(temp)}°C"]
    if precip != "none":
        words.append(("heavy " if heavy else "light ") + precip)
    elif cloudy:
        words.append("overcast")
    else:
        words.append("clear")
    words.append("evening" if night else "afternoon")
    return {
        "date": d.isoformat() if d else "", "temp": round(temp, 1), "precip": precip, "heavy": heavy,
        "night": night, "environment": environment, "condition": condition,
        "pitch": pitch_texture(condition, environment, region), "breath": temp <= BREATH,
        "baselayers": baselayers, "gloves": 0.25 if temp <= 2 else 0.0,
        "summary": " · ".join(words),
    }
