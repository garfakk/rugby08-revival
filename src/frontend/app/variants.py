"""
app/variants.py — competition variants of a team season
=========================================================
Two independent kinds, both keyed by a competition family id (the
competition template id: "world_cup", "six_nations", "european_cup"...).

SQUAD variants live in the season block and only hold a squad: "players",
"roles" and "setPlays" (plus a display "label"). Season "2024" + "world_cup"
is the 2023 World Cup squad (season YEAR is YEAR-1/YEAR):

    "2024": {
      "name": "France", "kits": {...}, "players": [...], "roles": {...}, ...,
      "variant": {
        "world_cup": {"label": "Rugby World Cup 2023", "players": [...], "roles": {...}}
      }
    }

KIT variants live inside one kit: the same kit with a small difference (a
tournament patch, a logo). Each kit has its own; home may have a World Cup
version while away has none:

    "kits": {
      "home": {
        "frontKitFile": "kits_2024/home_front.png", ...,
        "variants": {
          "world_cup": {"label": "RWC 2023 patch",
                        "frontKitFile": "kits_2024_world_cup/home_front.png"}
        }
      }
    }

Both only store what differs: each key a variant gives replaces the
default's value WHOLE; every key it leaves out is the default's. "label" is
the variant's display name and never reaches a resolved block or kit. A
squad variant that gives "players" but no "roles" keeps the default roles of
the players it still lists; empty roles are filled where they are used, as
for any team.

Nothing here touches Qt or disk: readers go through `resolve` /
`team_season` / `resolve_kit`, which hand back COPIES shaped exactly like a
plain season block or kit (no "variant" / "variants" key), so code written
for plain blocks keeps working unchanged.
"""
import copy

VARIANT_KEY = "variant"
KIT_VARIANTS_KEY = "variants"
DEFAULT = ""                 # the season's own block / the plain kit
META_KEYS = ("label",)       # variant-only keys, never merged into a team block
SQUAD_KEYS = ("players", "roles", "setPlays")   # all a squad variant may change


def variant_ids(info) -> list:
    """Variant ids of one season block, in file order."""
    return list(((info or {}).get(VARIANT_KEY) or {}))


def variant_label(info, variant) -> str:
    if not variant:
        return "Default"
    entry = ((info or {}).get(VARIANT_KEY) or {}).get(variant) or {}
    return entry.get("label") or variant.replace("_", " ").title()


def has_variant(info, variant) -> bool:
    return bool(variant) and variant in ((info or {}).get(VARIANT_KEY) or {})


def overrides(info, variant) -> dict:
    """The squad keys a variant itself sets — {} for the default."""
    if not variant:
        return {}
    entry = ((info or {}).get(VARIANT_KEY) or {}).get(variant) or {}
    return {k: v for k, v in entry.items() if k in SQUAD_KEYS}


def resolve(info, variant=DEFAULT) -> dict:
    """The season block as `variant` sees it (a copy). An unknown variant is
    the default."""
    base = {k: v for k, v in (info or {}).items() if k != VARIANT_KEY}
    out = copy.deepcopy(base)
    over = overrides(info, variant)
    for key, value in over.items():
        out[key] = copy.deepcopy(value)
    if "players" in over and "roles" not in over:
        squad = {str(p) for p in out.get("players", [])}
        out["roles"] = {k: (v if str(v) in squad else "")
                        for k, v in (base.get("roles") or {}).items()}
    return out


def pick_season(seasons, wanted) -> str:
    """`wanted` if the team has it, else the closest one it does have (the
    later one on a tie)."""
    wanted = str(wanted or "")
    if wanted in seasons:
        return wanted
    keys = sorted(seasons, key=lambda s: int(s) if str(s).isdigit() else 0)
    if not keys:
        return ""
    try:
        w = int(wanted)
        return min(keys, key=lambda s: (abs(int(s) - w), -int(s)))
    except (TypeError, ValueError):
        return keys[-1]


def team_season(teams, team_id, season, variant=DEFAULT, exact=False) -> dict:
    """Resolved block of `team_id` for `season` / `variant`.

    Fallbacks: a variant the season does not have is that season's default
    (never another season's variant: a 2020 Six Nations squad is not a 2024
    one); a season the team does not have is its nearest season, unless
    `exact` (then {})."""
    seasons = (teams or {}).get(str(team_id)) or {}
    if not seasons:
        return {}
    s = str(season) if exact else pick_season(seasons, season)
    if s not in seasons:
        return {}
    info = seasons[s]
    return resolve(info, variant if has_variant(info, variant) else DEFAULT)


def migrate_season(info) -> bool:
    """Older data let a squad variant carry its own "kits": move each of its
    kits into that kit's own "variants" (only the keys that differ), and drop
    every other non-squad key. True when the block changed."""
    changed = False
    kits = (info or {}).get("kits") or {}
    for vid, entry in ((info or {}).get(VARIANT_KEY) or {}).items():
        if not isinstance(entry, dict):
            continue
        for key in [k for k in entry if k not in SQUAD_KEYS + META_KEYS]:
            value = entry.pop(key)
            changed = True
            if key != "kits" or not isinstance(value, dict):
                continue
            for name, vkit in value.items():
                base = kits.get(name)
                if not isinstance(base, dict) or not isinstance(vkit, dict):
                    continue
                diff = {k: copy.deepcopy(v) for k, v in vkit.items()
                        if k != KIT_VARIANTS_KEY and base.get(k) != v}
                if diff:
                    label = entry.get("label")
                    if label:
                        diff["label"] = label
                    base.setdefault(KIT_VARIANTS_KEY, {}).setdefault(vid, diff)
    return changed


# ── kit variants ─────────────────────────────────────────────────────────
def kit_variant_ids(kit) -> list:
    """Variant ids of one kit, in file order."""
    return list(((kit or {}).get(KIT_VARIANTS_KEY) or {}))


def kit_variant_label(kit, variant) -> str:
    if not variant:
        return "Default"
    entry = ((kit or {}).get(KIT_VARIANTS_KEY) or {}).get(variant) or {}
    return entry.get("label") or variant.replace("_", " ").title()


def kit_overrides(kit, variant) -> dict:
    """The keys a kit variant itself sets (no label) — {} for the plain kit."""
    if not variant:
        return {}
    entry = ((kit or {}).get(KIT_VARIANTS_KEY) or {}).get(variant) or {}
    return {k: v for k, v in entry.items() if k not in META_KEYS}


def resolve_kit(kit, variant=DEFAULT) -> dict:
    """The kit as `variant` sees it (a copy, no "variants" key). An unknown
    variant is the plain kit."""
    out = copy.deepcopy({k: v for k, v in (kit or {}).items() if k != KIT_VARIANTS_KEY})
    for key, value in kit_overrides(kit, variant).items():
        out[key] = copy.deepcopy(value)
    return out


def asset_folder(season, variant, kind="kits") -> str:
    """Folder (inside the team folder) for a variant's own assets."""
    return f"{kind}_{season}_{variant}" if variant else f"{kind}_{season}"


def all_variant_ids(teams) -> list:
    """Every variant id used anywhere (squads and kits), sorted."""
    ids = set()
    for seasons in (teams or {}).values():
        for info in seasons.values():
            ids.update(variant_ids(info))
            for kit in (info.get("kits") or {}).values():
                ids.update(kit_variant_ids(kit))
    return sorted(ids)
