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

  stadiums/dressing/<kind>/<set>/                  the library (mod data)
  competitions/<c>/assets/dressing/<kind>/<set>/   a competition's, named by
                                                   its JSON ("pads", "posts",
                                                   "adboards"), per season
  the game                                         every stock stadium's own

Who decides, first that has one: the match's pick (quick match pickers, or
the competition a tournament / challenge applies, which sets the same
fields), then the stadium's own (its JSON "dressing", else the stock set of
its game slot, gsv.STOCK_DRESSING).
"""
import os

from backend import game_specific_variables as gsv
from backend.adboards import IMAGE_EXTS
from shared.config import config

KINDS = ("pads", "posts", "ads")
JSON_KEY = {"pads": "pads", "posts": "posts", "ads": "adboards"}
CFG_ATTR = {"pads": "pads", "posts": "posts", "ads": "adboards"}
LIBRARY = "stadiums/dressing"
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


def stadium_default(stadium, kind):
    """The set reference a stadium wears for `kind` when nothing else is
    picked: its JSON "dressing", else its game slot's stock set. `stadium`
    is the stadium's data dict (stadiums.json entry or custom JSON)."""
    info = stadium or {}
    own = (info.get("dressing") or {}).get(kind)
    if own:
        return own
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


def choices(ds, kind, current=None, stadium=None, suggested=()):
    """The picker's options: "Stadium default" (ref "", named after what
    that is for `stadium`), then every set of the library, the competitions
    and the game; the refs in `suggested` are flagged "suggested" and come
    first. `current` is added when none of them."""
    default = {"label": "Stadium default", "ref": "", "suggested": True}
    own = stadium_default(stadium, kind) if stadium else ""
    if own:
        default["detail"] = label_of(ds, kind, own)
        default["default_ref"] = own
    rest = library_sets(kind) + competition_sets(ds, kind) + stock_sets(kind)
    if current and not any(o["ref"] == current for o in rest):
        rest.append({"label": _label(os.path.basename(current.rstrip("/"))), "ref": current})
    picked = [r for r in suggested if r != own]
    by_ref = {o["ref"]: o for o in rest}
    first = [dict(by_ref[r], suggested=True) for r in picked if r in by_ref]
    others = [o for o in rest if o["ref"] not in set(picked)]
    return [default] + first + others


def resolve(cfg, kind):
    """The set reference match `cfg` wears for `kind`."""
    picked = getattr(cfg, CFG_ATTR[kind], None)
    if picked:
        return picked
    return stadium_default((cfg.stadium or {}).get("data") or {}, kind)
