"""
app/dressing.py — the stadium dressing a match wears: pads, posts and ads
==========================================================================
No Qt. Three independent slots, each a set reference (backend
stadium_dressing / adboards):

  pads   post pads + corner flags     posts   post + crossbar colours
  ads    the ad boards

A reference is a path relative to the mod data (a set folder, or for ads also
a .fsh / picture) or "stock:<name>" (the game's own file, read from
data.gob). Sets live in:

  stadium_graphics/<kind>/<set>/      the library (mod data)
  competitions/<c>/<where>/<kind>/    a competition's, named by its JSON
                                      ("pads", "posts", "adboards"), per
                                      season; <where> is assets, a year...
  the game                            every stock stadium's own

Who decides, first that has one: the match's pick (quick match pickers, or
the competition a tournament / challenge applies, which sets the same
fields), then the stadium's own (its JSON "dressing", else the stock set of
its game slot, gsv.STOCK_DRESSING).
"""
import os

from backend import game_specific_variables as gsv
from backend import stadium_dressing
from backend import pitch_stripes
from backend.adboards import IMAGE_EXTS
from shared.config import config

KINDS = ("pads", "posts", "ads")
JSON_KEY = {"pads": "pads", "posts": "posts", "ads": "adboards"}
CFG_ATTR = {"pads": "pads", "posts": "posts", "ads": "adboards"}
LIBRARY = stadium_dressing.LIBRARY
STOCK = "stock:"


def _label(name):
    return os.path.splitext(name)[0].replace("_", " ").strip().title()


def _relative(path):
    return os.path.relpath(path, config.mod_data_directory).replace("\\", "/")


# ── the sets on offer ──────────────────────────────────────────────────────
def library_sets(kind):
    """[{"label", "ref"}] of the library's sets of `kind` (folders; for ads
    also a loose .fsh or picture)."""
    root = os.path.join(config.mod_data_directory, LIBRARY, kind)
    out = []
    if not os.path.isdir(root):
        return out
    for name in sorted(os.listdir(root), key=str.lower):
        full = os.path.join(root, name)
        if name.startswith(".") or ".deleted-" in name:
            continue
        loose = kind == "ads" and name.lower().endswith((".fsh",) + IMAGE_EXTS)
        if os.path.isdir(full) or loose:
            out.append({"label": _label(name), "ref": f"{LIBRARY}/{kind}/{name}"})
    return out


def _season_label(name, seasons):
    seasons = [s for s in seasons if s]
    if not seasons:
        return name
    if len(seasons) == 1:
        return f"{name} {seasons[0]}"
    return f"{name} {seasons[0]}–{seasons[-1]}"


def competition_sets(ds, kind):
    """[{"label", "ref"}] of the competitions' sets of `kind`, one entry per
    set (seasons sharing a set share an entry: "Six Nations 2019–2026")."""
    key = JSON_KEY[kind]
    out = []
    for tid, seasons in ds.tournaments.items():
        folder = ds.tournaments_folder_path.get(tid, "")
        by_ref = {}
        for season, info in seasons.items():
            rel = (info.get(key) or "").strip()
            if not folder or not rel or not os.path.exists(os.path.join(folder, rel)):
                continue
            ref = _relative(os.path.join(folder, rel))
            by_ref.setdefault(ref, {"name": info.get("name") or tid, "seasons": []})
            by_ref[ref]["seasons"].append(season)
        for ref, entry in by_ref.items():
            out.append({"label": _season_label(entry["name"], sorted(entry["seasons"])), "ref": ref})
    return sorted(out, key=lambda o: o["label"].lower())


def competition_looks(ds):
    """[{"label", "refs": {kind: ref}}]: each competition's own pads, posts
    and ads, one entry per different look ("Six Nations 2019–2026")."""
    by_refs = {}
    for tid, seasons in ds.tournaments.items():
        folder = ds.tournaments_folder_path.get(tid, "")
        for season, info in seasons.items():
            refs = {}
            for kind in KINDS:
                rel = (info.get(JSON_KEY[kind]) or "").strip()
                if folder and rel and os.path.exists(os.path.join(folder, rel)):
                    refs[kind] = _relative(os.path.join(folder, rel))
            if not refs:
                continue
            key = tuple(sorted(refs.items()))
            entry = by_refs.setdefault(key, {"name": info.get("name") or tid, "seasons": [], "refs": refs})
            entry["seasons"].append(season)
    out = [{"label": _season_label(e["name"], sorted(e["seasons"])), "refs": e["refs"]}
           for e in by_refs.values()]
    return sorted(out, key=lambda o: o["label"].lower())


def stock_label(name):
    """"standard/twickenham" -> "Twickenham", "tournaments/super14" ->
    "Super14 (tournament)"."""
    group, _, base = name.rpartition("/")
    label = base.replace("_", " ").title()
    return f"{label} (tournament)" if group == "tournaments" else label


def stock_sets(kind):
    names = gsv.STOCK_ADS if kind == "ads" else gsv.STOCK_PADS
    return sorted(({"label": f"Stock · {stock_label(n)}", "ref": STOCK + n} for n in names),
                  key=lambda o: o["label"].lower())


# ── a mod stadium's own dressing (Tools > Stadium editor) ──────────────────
def stadium_json_path(sid):
    """The JSON of the mod stadium `sid` in the data pack (data/stadiums/
    <Folder>/<folder>.json), None when no stadium folder defines it."""
    import json
    root = os.path.join(config.pack_directory, "stadiums")
    if not os.path.isdir(root):
        return None
    for folder in sorted(os.listdir(root)):
        path = os.path.join(root, folder, f"{folder.lower().replace(' ', '_')}.json")
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and str(sid) in data:
            return path
    return None


def save_stadium(ds, sid, refs, pitches=(), logos=None, stripes=None, environments=None) -> str:
    """Write the stadium's "dressing" ({kind: ref}, empty refs removed; none
    = the slot's stock sets) and "pitches" (the pitch textures a match there
    may use; none = any), "pitch_logos" (backend/pitch_logos layout; None =
    the game's own) and "stripes" ({environment: {"opacity", "brightness"}},
    backend/pitch_stripes; none = the scene packs' own) and "environments"
    (the ones a match there may use; None = those it has scenes for) in its
    JSON (the maintainer's mode, config save_edits_to = mod) or, as every
    edit, in user_data/edits/stadiums (app/user_stadiums.py), and into the
    loaded data. The file's path."""
    import json
    from app import game_data as G
    from app import user_stadiums
    path = stadium_json_path(sid)
    if path is None:
        raise OSError(f"no stadium folder defines {sid}")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    refs = {k: v for k, v in (refs or {}).items() if k in KINDS and v}
    pitches = list(pitches or [])
    stripes = {env: v for env, v in ((e, pitch_stripes.clean(v)) for e, v in (stripes or {}).items()) if v}
    entry = data[str(sid)]
    environments = list(environments or [])
    values = (("dressing", refs), ("pitches", pitches), ("pitch_logos", logos), ("stripes", stripes),
              ("environments", environments))
    if G.saves_to_user_edits():
        # the edit is the user's: kept in user_data, the pack's file untouched
        if not ds.edits.enabled:
            raise G.SaveError("your edits are turned off: turn them on in Tools › My edits to save")
        path = user_stadiums.save(sid, dict(values), {k: entry.get(k) for k in user_stadiums.EDIT_KEYS})
    else:
        for key, value in values:
            if value or (key == "pitch_logos" and value is not None):
                entry[key] = value
            else:
                entry.pop(key, None)
        with open(path + ".tmp", "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
            fh.write("\n")
        os.replace(path + ".tmp", path)
    info = ds.stadiums.get(str(sid))
    if isinstance(info, dict):
        for key, value in values:
            if value or (key == "pitch_logos" and value is not None):
                info[key] = value
            else:
                info.pop(key, None)
        if not environments:        # the loader's default: the scenes it has
            info["environments"] = list(info.get("scenes") or [])
    return path


def own_default(stadium, kind):
    """What the stadium wears without its own "dressing": the stock set of
    its game slot."""
    info = dict(stadium or {})
    info.pop("dressing", None)
    return stadium_default(info, kind)


def stadium_default(stadium, kind):
    """The set reference a stadium wears for `kind` when nothing else is
    picked: its JSON "dressing" (the stadium editor writes it), else its
    game slot's stock set. `stadium` is the stadium's data dict
    (stadiums.json entry or custom JSON)."""
    info = stadium or {}
    own = (info.get("dressing") or {}).get(kind)
    if own:
        return stadium_dressing.library_ref(own)
    try:
        stock = gsv.STOCK_DRESSING.get(int(info.get("game_id")))
    except (TypeError, ValueError):
        stock = None
    if not stock:
        return ""
    return STOCK + (stock["ads"] if kind == "ads" else stock["pads"])


def label_of(ds, kind, ref):
    """Display name of a set reference."""
    if not ref:
        return "Stadium default"
    for option in library_sets(kind) + competition_sets(ds, kind) + stock_sets(kind):
        if option["ref"] == ref:
            return option["label"]
    return _label(os.path.basename(ref.rstrip("/")))


def _participant_ids(node, out):
    if isinstance(node, dict):
        for v in node.values():
            _participant_ids(v, out)
    elif isinstance(node, list):
        for v in node:
            _participant_ids(v, out)
    elif isinstance(node, (str, int)):
        out.add(str(node))
    return out


_TEMPLATES = None


def _templates():
    """[(competition id, season, team ids, categories)] of every competition
    template, read once."""
    global _TEMPLATES
    if _TEMPLATES is None:
        from app.tournament import formats
        _TEMPLATES = []
        try:
            templates = formats.load_templates()
        except Exception:          # a broken template must not break match setup
            templates = {}
        for tid, tpl in templates.items():
            cats = tpl.get("category") or []
            cats = [cats] if isinstance(cats, str) else list(cats)
            _TEMPLATES.append((str(tpl.get("branding") or tid), str(tpl.get("branding_season") or ""),
                               _participant_ids(tpl.get("participants") or {}, set()),
                               {c.lower() for c in cats}))
    return _TEMPLATES


# team categories under an older name of a competition's
CATEGORY_ALIASES = {"super 14": "super rugby", "pro12": "pro14", "celtic league": "pro14",
                    "pro14": "urc"}


def _categories(category):
    out, cat = set(), str(category or "").strip().lower()
    while cat and cat not in out:
        out.add(cat)
        cat = CATEGORY_ALIASES.get(cat, "")
    return out


def team_competitions(teams):
    """{(competition id, season)} the teams play in: a template lists them,
    or takes their category (Top 14 clubs -> Top 14). `teams` is
    [(team id, team info)]."""
    ids = {str(t) for t, _ in teams if t}
    cats = set().union(*[_categories((info or {}).get("category")) for _, info in teams])
    return {(comp, season) for comp, season, members, tcats in _templates()
            if members & ids or tcats & cats}


def suggested_refs(ds, kind, teams=(), stadium=None, home_ground=None):
    """The set references worth offering first for a match: the stadium's
    own, its teams' competitions', the home team's ground's."""
    out = []
    if stadium:
        out.append(stadium_default(stadium, kind))
    key = JSON_KEY[kind]
    for comp, season in sorted(team_competitions(teams)):
        seasons = ds.tournaments.get(comp) or {}
        info = seasons.get(season) or (seasons.get("") if not season else None)
        folder = ds.tournaments_folder_path.get(comp, "")
        rel = ((info or {}).get(key) or "").strip()
        if folder and rel and os.path.exists(os.path.join(folder, rel)):
            out.append(_relative(os.path.join(folder, rel)))
    if home_ground:
        out.append(stadium_default(home_ground, kind))
    seen, ordered = set(), []
    for ref in out:
        if ref and ref not in seen:
            seen.add(ref)
            ordered.append(ref)
    return ordered


# ── one entry per look ─────────────────────────────────────────────────────
# Many sets look the same (14 English grounds share their pads, nearly all
# posts are white with a coloured band on the crossbar): the pickers list
# each look once. Posts are named after their colours.
_LOOKS = {}
COLOURS = {
    "white": (235, 235, 235), "grey": (130, 130, 130), "black": (30, 30, 30),
    "navy": (20, 35, 95), "blue": (55, 75, 190), "light blue": (120, 180, 210),
    "red": (175, 30, 40), "maroon": (110, 20, 25), "green": (25, 95, 50),
    "purple": (90, 60, 140), "orange": (210, 140, 50), "yellow": (230, 200, 40),
    "pink": (220, 0, 200),
}


def _colour_names(pixels):
    """The COLOURS name nearest each (N, 3) pixel."""
    import numpy as np
    names = list(COLOURS)
    ref = np.array([COLOURS[n] for n in names], dtype=np.float32)
    d = ((np.asarray(pixels, dtype=np.float32)[:, None, :] - ref[None]) ** 2).sum(-1)
    return [names[i] for i in d.argmin(1)]


def _colour_name(rgb):
    return _colour_names([rgb])[0]


def posts_name(images):
    """"White", "White · navy", "White · orange & black": the post's colour,
    then the crossbar's band colours by area."""
    import numpy as np
    post, bar = images.get("post"), images.get("xbar")
    if post is None:
        return ""
    base = _colour_name(np.asarray(post.convert("RGB").resize((8, 8))).reshape(-1, 3).mean(0))
    name = base.capitalize()
    if bar is None:
        return name
    px = np.asarray(bar.convert("RGB").resize((16, 16))).reshape(-1, 3)
    names = _colour_names(px)
    counts = {}
    for n in names:
        if n != base:
            counts[n] = counts.get(n, 0) + 1
    bands = [n for n, c in sorted(counts.items(), key=lambda kv: -kv[1]) if c >= len(px) // 16][:2]
    return f"{name} · {' & '.join(bands)}" if bands else name


def _placeholder(images):
    """The game's magenta "missing texture" stand-in (stock England Day)."""
    import numpy as np
    for image in images.values():
        r, g, b = np.asarray(image.convert("RGB").resize((8, 8))).reshape(-1, 3).mean(0)
        if r > 170 and b > 150 and g < 80:
            return True
    return False


def look(ref, kind):
    """A key equal for sets that look the same (pictures shrunk and
    rounded); for posts its colour name. None when the set can't be read."""
    if not ref:
        return None
    ref = stadium_dressing.library_ref(ref)
    path = ref if ref.startswith(STOCK) else os.path.join(config.mod_data_directory, ref)
    try:
        stamp = 0 if ref.startswith(STOCK) else os.path.getmtime(path)
    except OSError:
        return None
    cached = _LOOKS.get((ref, kind))
    if cached and cached[0] == stamp:
        return cached[1]
    import hashlib
    import numpy as np
    images = stadium_dressing.load(ref, kind)
    if not images or _placeholder(images):
        key = None
    elif kind == "posts":
        key = posts_name(images)
    else:
        h = hashlib.md5()
        for tag in sorted(images):
            small = np.asarray(images[tag].convert("RGB").resize((8, 8))) // 24
            h.update(tag.encode() + small.tobytes())
        key = h.hexdigest()
    _LOOKS[(ref, kind)] = (stamp, key)
    return key


def _one_per_look(kind, options, default_look):
    """`options` with sets looking like an earlier one (or like the default)
    folded into it: each kept option lists the refs it stands for."""
    if kind not in ("pads", "posts"):
        return [dict(o, refs=[o["ref"]]) for o in options]
    stadium_dressing.prefetch_stock([stadium_dressing.stock_game_path(o["ref"])
                                     for o in options if o["ref"].startswith(STOCK)])
    out, by_look = [], {}
    for o in options:
        key = look(o["ref"], kind)
        if key is None:
            continue                   # unreadable, or the magenta stand-in
        if key == default_look:
            continue
        if key is not None and key in by_look:
            by_look[key]["refs"].append(o["ref"])
            continue
        o = dict(o, refs=[o["ref"]])
        if kind == "posts" and key:
            o["label"] = key
        if key is not None:
            by_look[key] = o
        out.append(o)
    return out


def choices(ds, kind, current=None, stadium=None, suggested=()):
    """The picker's options: "Default" (ref "": the stadium's own), the
    suggested sets, then every other set of the library, the competitions
    and the game, each look once (pads, posts); `current` is added when
    none of them stands for it."""
    default = {"label": "Default", "ref": "", "suggested": True, "refs": [""]}
    own = stadium_default(stadium, kind) if stadium else ""
    if own:
        default["default_ref"] = own
    rest = library_sets(kind) + competition_sets(ds, kind) + stock_sets(kind)
    if current and not any(o["ref"] == current for o in rest):
        rest.append({"label": _label(os.path.basename(current.rstrip("/"))), "ref": current})
    picked = [r for r in suggested if r != own]
    by_ref = {o["ref"]: o for o in rest}
    first = [dict(by_ref[r], suggested=True) for r in picked if r in by_ref]
    others = [o for o in rest if o["ref"] not in set(picked)]
    folded = _one_per_look(kind, first + others, look(own, kind) if own else None)
    if current and current != own and not any(current in o["refs"] for o in folded):
        # the pick looks like the default: keep it listed so it stays picked
        folded.append(dict(by_ref.get(current) or {"label": _label(current), "ref": current},
                           refs=[current]))
    return [default] + folded


def resolve(cfg, kind):
    """The set reference match `cfg` wears for `kind`."""
    picked = getattr(cfg, CFG_ATTR[kind], None)
    if picked:
        return picked
    return stadium_default((cfg.stadium or {}).get("data") or {}, kind)
