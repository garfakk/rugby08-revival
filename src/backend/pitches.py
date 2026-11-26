"""
backend/pitches.py — the game's pitch textures
===============================================
A pitch texture is a pack in data.gob ("stadiums/pitches/reg2_08_muddy_n":
the grass tiles tp01..tp04, the mowing masks and the detail tile). A stadium
scene names the one it plays on in its Config2.bin; a match can force another
(.mis pitchtex=, gsv.pitch_textures are the names the game accepts).

The mod adds pitches of its own (data/pitches, tools/make_pitches.py): synthetic
and hybrid turf. The game only takes its own names, so a match on one has
the scene's Config2.bin and the pack put over the game's (`deploy`), and the
stadium's dirt probability set to the lowest (`DIRT`: turf doesn't muddy).

A stadium lists in its JSON ("pitches") the textures a match there may use:
none listed = any. `allowed(info)` is that list, `label(name)` a name for it,
`grass(name)` its picture.
"""
import hashlib
import os
import re

from backend.game_specific_variables import pitch_textures
from backend.stadium_scene import stock_pack_path
from shared.log import get_logger

log = get_logger(__name__)

OWN = ("Mod_08_synthetic_d", "Mod_08_synthetic_n", "Mod_08_hybrid_d")   # the mod's, packs in data/pitches
NAMES = tuple(pitch_textures) + OWN
DIRT = "Very_Low"        # stadiuminfo ProbabilityDirt of a match on an own pitch (the game's lowest: 0)
LIGHTS = {"d": "day", "n": "night", "o": "overcast"}
REGIONS = {"mod": "Synthetic & hybrid"}
_SCENES = {}


def _split(name):
    """("Reg2", "light mud", "n") of "Reg2_08_light_Mud_n"."""
    region, _, rest = str(name).split("_", 2)
    condition, _, light = rest.rpartition("_")
    return region, condition.replace("_", " ").lower(), light


def region_of(name) -> str:
    """"Region 2" of "Reg2_08_best_d"."""
    region = _split(name)[0]
    if region.lower() in REGIONS:
        return REGIONS[region.lower()]
    return f"Region {region[3:]}" if region.lower().startswith("reg") else region


def label(name) -> str:
    """"Muddy · night" of "Reg2_08_muddy_n"."""
    _, condition, light = _split(name)
    return " · ".join(x for x in (condition.capitalize(), LIGHTS.get(light)) if x)


# The game's condition words as a player reads them, driest first.
CONDITIONS = {"best": "Perfect", "dry": "Dry", "norm": "Normal", "hard": "Hard", "soggy": "Soggy",
              "light mud": "Light mud", "muddy": "Muddy", "muddier": "Very muddy",
              "frosty": "Frosty", "snow": "Snow", "synthetic": "Synthetic", "hybrid": "Hybrid"}


def condition(name) -> str:
    """"light mud" of "Reg2_08_light_Mud_n"."""
    return _split(name)[1]


def condition_label(name) -> str:
    """"Muddy" of "Reg2_08_muddy_n": the condition alone."""
    condition = _split(name)[1]
    return CONDITIONS.get(condition, condition.capitalize())


def condition_order(name) -> int:
    condition = _split(name)[1]
    return list(CONDITIONS).index(condition) if condition in CONDITIONS else len(CONDITIONS)


def simple_labels(names) -> dict:
    """{name: "Muddy"} for the pitches on offer: the condition alone, and
    where several share one (the game has six hard pitches, day and night, in
    four regions) a number in the order given: "Hard 1", "Hard 2"..."""
    groups = {}
    for n in names:
        groups.setdefault(condition_label(n), []).append(n)
    out = {}
    for text, items in groups.items():
        for i, n in enumerate(items, 1):
            out[n] = f"{text} {i}" if len(items) > 1 else text
    return out


def full_label(name) -> str:
    if _split(name)[0].lower() in REGIONS:
        return label(name)
    return f"{label(name)} ({region_of(name)})"


def allowed(info) -> list:
    """The textures a match at stadium `info` may use, in the game's order;
    [] when it doesn't restrict them."""
    have = {str(n).lower(): n for n in NAMES}
    picked = {have[str(n).lower()] for n in ((info or {}).get("pitches") or []) if str(n).lower() in have}
    return [n for n in NAMES if n in picked]


def is_own(name) -> bool:
    return str(name).lower() in {n.lower() for n in OWN}


def own_file(name) -> str:
    """The mod's pack of an own pitch, in data/pitches."""
    from shared.config import config
    return os.path.join(config.mod_data_directory, "pitches", str(name).lower() + ".big")


def pack_path(name):
    if is_own(name):
        path = own_file(name)
        return path if os.path.isfile(path) else None
    return stock_pack_path("stadiums/pitches/" + str(name).lower())


def scene(name):
    """The pitch as a stadium_scene.Scene (the pack's PitchColour.o with its
    grass tiles tp01..tp04), None when the game's pack can't be read."""
    key = str(name).lower()
    if key not in _SCENES:
        found = None
        path = pack_path(name)
        if path:
            try:
                from backend import stadium_scene
                found = stadium_scene.read(path)
                if not any(p.model == "PitchColour.o" for p in found.parts):
                    found = None
            except Exception as e:
                log.warning(f"pitch {name}: {e}")
        _SCENES[key] = found
    return _SCENES[key]


def grass(name):
    """The pitch's main grass tile (RGBA), None when the pack can't be read."""
    found = scene(name)
    if found is None:
        return None
    for tag in ("tp02", "tp01", "tp04", "tp03"):
        if tag in found.textures:
            return found.textures[tag]
    return None


def own_name(scene_path):
    """The pitch texture the scene pack at `scene_path` plays on (the first
    line of its Config2.bin, "pitches\\Reg2_08_Best_d"), a name of NAMES when
    it is one, else as written; "" when unknown."""
    try:
        from shared.omodel.bigfile import BigArchive
        raw = BigArchive.open(scene_path).read("Config2.bin")
    except Exception:
        return ""
    line = raw[1:1 + raw[0]].decode("latin-1") if raw else ""      # length-prefixed
    name = line.split("\\")[-1].strip()
    lower = {n.lower(): n for n in NAMES}
    return lower.get(name.lower(), name)


def set_line(path, name):
    """Make the scene pack at `path` play on pitch `name`: its Config2.bin's
    first line (length-prefixed). False when it has no Config2.bin."""
    from shared.omodel.bigfile import BigArchive, pack_big
    with open(path, "rb") as fh:
        archive = BigArchive(fh.read())
    if "Config2.bin" not in archive:
        return False
    line = ("pitches\\" + str(name)).encode("latin-1")
    entries = [(n, bytes([len(line)]) + line if n == "Config2.bin" else archive.read(n)) for n in archive.entries]
    with open(path, "wb") as fh:
        fh.write(pack_big(entries))
    return True


def set_dirt(xml, filename, environment, level=DIRT):
    """stadiuminfo.xml bytes with ProbabilityDirt of stadium `filename`'s
    `environment` set to `level` (Very_Low | Low | Medium | High); None when
    that stadium has no such environment."""
    done = []

    def stadium(m):
        if m.group(1).decode("latin-1").lower() != str(filename).lower():
            return m.group(0)

        def env(e):
            tag = e.group(0)
            if re.search(rb'\btype="%s"' % environment.encode(), tag, re.I) is None:
                return tag
            done.append(1)
            return re.sub(rb'ProbabilityDirt="[^"]*"', b'ProbabilityDirt="' + level.encode() + b'"', tag)
        return re.sub(rb"<environment\b[^>]*>", env, m.group(0))

    out = re.sub(rb'<stadium\b[^>]*?\bFileName="([^"]*)"[^>]*>.*?</stadium>', stadium, xml, flags=re.S | re.I)
    return out if done else None
