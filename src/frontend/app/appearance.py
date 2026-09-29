"""
app/appearance.py — player look: skins, skin layers, gloves, boots (no Qt)
==========================================================================
One reading of the appearance keys of a player season, shared by the
editor, the validator, the match builder and the preview, so all of them
agree with what backend/game_files_processor actually writes.

  skin_tone     light / l_medium / d_medium / dark ("0".."3" = index)
  skin          "" or an image path (relative to mod data) replacing the tone
  skin_overlay  [] or image paths painted over the skin, bottom first
  gloves        "" = none, "yes" = the stock gloved texture, or an image path
                painted on top of everything
  boot_style    "0".."9" stock style, or an image path (boots.fsh layout)

Skin textures (custom skins, layers, gloves) share the game's 512×256 skin
UV layout; boots use the 256×256 "clet" layout. Paths are stored with "/"
relative to the mod data folder, like `face`.
"""
import os

SKIN_TONES = ["light", "l_medium", "d_medium", "dark"]
# skins.fsh entry names: bare arms / gloved, per tone.
STOCK_SKIN_ENTRIES = {"light": ("wksk", "whsg"), "l_medium": ("lmsk", "lmsg"),
                      "d_medium": ("dmsk", "dmsg"), "dark": ("dksk", "dksg")}
BOOT_STYLES = [str(i) for i in range(10)]
TRUE_WORDS = {"1", "true", "yes", "on"}
IMAGE_EXTS = (".png", ".bmp", ".jpg", ".jpeg")

# Folders (relative to mod data) holding each kind of image; the first that
# exists is used. Real mod data calls the strap images "straps", the test
# data "tapes".
ASSET_DIRS = {
    "skins": ["players/skins"],
    "baselayers": ["players/baselayers"],
    "straps": ["players/straps", "players/tapes"],
    "gloves": ["players/gloves"],
    "boots": ["players/boots"],
}
LAYER_KINDS = ["baselayers", "straps"]

SPECS = {
    "skin": {"size": (512, 256), "alpha": False, "ext": IMAGE_EXTS,
             "note": ""},
    "layer": {"size": (512, 256), "alpha": True, "ext": IMAGE_EXTS,
              "note": ""},
    "gloves": {"size": (512, 256), "alpha": True, "ext": IMAGE_EXTS,
               "note": ""},
    "boots": {"size": (256, 256), "alpha": False, "ext": IMAGE_EXTS,
              "note": ""},
}


# ── Values ───────────────────────────────────────────────────────────────
def normalize_tone(value):
    """A stock tone name, or None when the value is not a tone. Digits are
    the roster's tone index (0 = light … 3 = dark)."""
    v = str(value if value is not None else "").strip().lower()
    if v in SKIN_TONES:
        return v
    if v.isdigit() and int(v) < len(SKIN_TONES):
        return SKIN_TONES[int(v)]
    return None


def is_image_path(value):
    return isinstance(value, str) and value.strip().lower().endswith(IMAGE_EXTS)


def overlay_list(value):
    """The skin_overlay value as a list of path strings (bottom first)."""
    if isinstance(value, (list, tuple)):
        return [str(v) for v in value if isinstance(v, str) and v.strip()]
    if isinstance(value, str) and value.strip() and value.strip() not in ("False", "True"):
        return [value.strip()]
    return []


def gloves_kind(value):
    """"none" | "stock" | "image" | "invalid"."""
    if isinstance(value, bool):
        return "stock" if value else "none"
    v = str(value or "").strip()
    if not v or v.lower() in ("no", "false", "0", "off"):
        return "none"
    if v.lower() in TRUE_WORDS:
        return "stock"
    return "image" if is_image_path(v) else "invalid"


def boot_kind(value):
    """"stock" | "image" | "invalid" ("" counts as stock style 0)."""
    v = str(value if value is not None else "").strip()
    if not v or v in BOOT_STYLES:
        return "stock"
    return "image" if is_image_path(v) else "invalid"


def abs_path(mod_dir, rel):
    return os.path.join(mod_dir, rel) if rel and not os.path.isabs(rel) else (rel or "")


def exists(mod_dir, rel):
    return bool(rel) and os.path.isfile(abs_path(mod_dir, rel))


def relative_to_mod(mod_dir, path):
    if not path:
        return ""
    if os.path.isabs(path):
        path = os.path.relpath(path, mod_dir)
    return path.replace("\\", "/")


# ── Asset folders ────────────────────────────────────────────────────────
def asset_dir(mod_dir, kind):
    """(relative folder, absolute folder) for a kind of image — the first
    candidate that exists, else the first candidate."""
    candidates = ASSET_DIRS[kind]
    for rel in candidates:
        if os.path.isdir(os.path.join(mod_dir, rel)):
            return rel, os.path.join(mod_dir, rel)
    return candidates[0], os.path.join(mod_dir, candidates[0])


def asset_options(mod_dir, kind):
    """Relative paths of every image in the kind's folder (recursive, sorted)."""
    rel, folder = asset_dir(mod_dir, kind)
    out = []
    if not os.path.isdir(folder):
        return out
    for dirpath, dirs, files in os.walk(folder):
        dirs.sort()
        for f in sorted(files):
            if f.lower().endswith(IMAGE_EXTS):
                sub = os.path.relpath(os.path.join(dirpath, f), folder).replace("\\", "/")
                out.append(f"{rel}/{sub}")
    return out


def kind_of_path(mod_dir, rel):
    """Which asset folder a stored path lives in ("" when none)."""
    rel = (rel or "").replace("\\", "/")
    for kind, candidates in ASSET_DIRS.items():
        if any(rel.startswith(c + "/") for c in candidates):
            return kind
    return ""


def label_of(rel):
    """Readable name of an image path: 'baselayer_top_marine.png' → 'baselayer top marine'."""
    base = os.path.splitext(os.path.basename(rel or ""))[0]
    return base.replace("_", " ")


def baselayer_zone(rel):
    """'top' or 'bottom' for an image in the baselayers folder, from its own
    filename convention (baselayer_top_*.png / baselayer_bottom_*.png —
    every file shipped so far follows it). Anything that doesn't match
    either prefix defaults to 'bottom' so it's never silently dropped from
    the editor's bottom/top baselayer split."""
    name = os.path.basename(rel or "").lower()
    return "top" if name.startswith("baselayer_top") else "bottom"


# ── Image facts (PIL, lazily imported) ────────────────────────────────────
_info_cache = {}


def image_info(path):
    """(width, height, has_transparency) or None when unreadable. Cached by mtime."""
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    key = (path, mtime)
    if key in _info_cache:
        return _info_cache[key]
    try:
        from PIL import Image
        with Image.open(path) as img:
            w, h = img.size
            alpha = False
            if img.mode in ("RGBA", "LA", "PA") or "transparency" in img.info:
                a = img.convert("RGBA").getchannel("A")
                alpha = a.getextrema()[0] < 255
        info = (w, h, alpha)
    except Exception:
        info = None
    _info_cache[key] = info
    return info


def asset_problems(mod_dir, rel, spec_key):
    """[(message, severity)] for one stored image path."""
    if not rel:
        return []
    spec = SPECS[spec_key]
    path = abs_path(mod_dir, rel)
    if not rel.lower().endswith(spec["ext"]):
        return [(f"'{os.path.basename(rel)}' is not an image file", "error")]
    if not os.path.isfile(path):
        return [(f"{rel} not found — the game skips it", "error")]
    info = image_info(path)
    if info is None:
        return [(f"{os.path.basename(rel)} can't be read as an image", "error")]
    w, h, alpha = info
    out = []
    if spec["size"] and (w, h) != spec["size"]:
        tw, th = spec["size"]
        out.append((f"{os.path.basename(rel)} is {w}×{h}, scaled to {tw}×{th}", "info"))
    if spec["alpha"] and not alpha:
        out.append((f"{os.path.basename(rel)} has no transparency — it covers the whole skin",
                    "warn"))
    return out


# ── What the game gets ───────────────────────────────────────────────────
def resolve(stats, mod_dir):
    """How the skin will be built, keeping only files that exist:
    {"tone", "custom_skin" (abs or None), "gloved" (stock gloved base),
     "layers" [abs, bottom first — overlays then gloves image], "missing" [rel]}.
    Mirrors backend.mod_utils.resolve_player_skin_layers + wears_stock_gloves."""
    tone = normalize_tone(stats.get("skin_tone")) or "light"
    missing = []
    skin = str(stats.get("skin") or "").strip()
    custom = None
    if skin and normalize_tone(skin) is None:
        if exists(mod_dir, skin):
            custom = abs_path(mod_dir, skin)
        else:
            missing.append(skin)
    elif skin:
        tone = normalize_tone(skin)
    layers = []
    for rel in overlay_list(stats.get("skin_overlay")):
        if exists(mod_dir, rel):
            layers.append(abs_path(mod_dir, rel))
        else:
            missing.append(rel)
    gloves = stats.get("gloves", "")
    kind = gloves_kind(gloves)
    gloved = kind == "stock"
    if kind == "image":
        if exists(mod_dir, gloves):
            layers.append(abs_path(mod_dir, gloves))
        else:
            missing.append(gloves)
            gloved = True
    return {"tone": tone, "custom_skin": custom, "gloved": gloved, "layers": layers,
            "missing": missing}


def stock_entry(resolved):
    """skins.fsh entry name of the stock base texture."""
    bare, gloved = STOCK_SKIN_ENTRIES[resolved["tone"]]
    return gloved if resolved["gloved"] else bare
