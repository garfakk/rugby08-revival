"""
app/tattoos/store.py — where tattoos and skin adjustments live (no Qt)
======================================================================
What a player wears (paths relative to the mod data, like every other skin layer):

  players/tattoos/<pid>_<hash>.png     the flattened tattoos (512×256, transparent) — first in `skin_overlay`,
                                       so baselayers, straps and gloves stay on top of them
  players/tattoos/<pid>_<hash>.json    its layers, so the editor can open the design again
  players/skins/<pid>_tint_<hash>.png  the adjusted skin (brightness, contrast…) — the player's `skin`
  players/skins/<pid>_tint_<hash>.json what it was made from ({"from", "adjust"}) — never adjusted twice
  players/tattoos/library/             pictures the user imported (index.json + <id>.png)

Every save writes new files (named by their content) rather than overwriting: undo, a discarded edit, or another
player sharing the files keeps pointing at a picture that still exists. `cleanup` removes this player's
versions nothing refers to any more. Files go through app.disk_import.copy_into_data, i.e. into the user's own
mod data when the program uses one, never through the data pack.

A tattoo picture without its .json (made elsewhere, e.g. by R08 Studio) opens as one "Earlier tattoos" layer
per limb, kept as it is.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tempfile

from PIL import Image, ImageOps

from . import render as Rn

TATTOO_DIR = "players/tattoos"
SKIN_DIR = "players/skins"
LIBRARY_DIR = "players/tattoos/library"


def _abs(mod_dir, rel):
    return os.path.join(mod_dir, *rel.split("/"))


def _safe_pid(pid) -> str:
    pid = str(pid)
    if not re.fullmatch(r"[A-Za-z0-9_\-]{1,40}", pid):
        raise ValueError(f"bad player id {pid!r}")
    return pid


def _write_bytes(mod_dir, rel, data: bytes) -> str:
    """Put `data` at `rel` in the mod data (through the user's overlay when there is one)."""
    from app.disk_import import copy_into_data
    fd, tmp = tempfile.mkstemp(suffix=os.path.splitext(rel)[1])
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        copy_into_data(tmp, _abs(mod_dir, rel))
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass
    return rel


def _remove(mod_dir, rel):
    """Remove a file this module wrote (its names are its own: no pack ships them): the user's overlay copy
    and the copy in the folder the program reads."""
    from app import game_data as G
    paths = [_abs(mod_dir, rel)]
    if G.saves_to_user_edits():
        from shared import mod_overlay
        from shared.app_paths import user_data_directory
        paths.append(os.path.join(mod_overlay.overlay_directory(user_data_directory()), *rel.split("/")))
    for p in paths:
        try:
            os.remove(p)
        except OSError:
            pass


def png_bytes(img: Image.Image) -> bytes:
    buf = io.BytesIO()
    img.save(buf, "PNG", optimize=False)
    return buf.getvalue()


def _digest(*parts: bytes) -> str:
    h = hashlib.sha1()
    for p in parts:
        h.update(p)
    return h.hexdigest()[:10]


# ── the user's imported pictures ─────────────────────────────────────────────
class Library:
    """Pictures imported into the editor: an ink mask (one colour, like any tattoo) or a colour picture kept as is."""

    def __init__(self, mod_dir):
        self.mod_dir = mod_dir
        self._cache = {}

    @property
    def folder(self):
        return _abs(self.mod_dir, LIBRARY_DIR)

    def index(self) -> dict:
        try:
            with open(os.path.join(self.folder, "index.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def items(self) -> list[dict]:
        return [{"id": f"user:{k}", "name": v.get("name", "Picture"), "aspect": v.get("aspect", 1), "size": v.get("size", 40),
                 "mode": v.get("mode", "ink"), "path": os.path.join(self.folder, f"{k}.png")}
                for k, v in self.index().items() if os.path.isfile(os.path.join(self.folder, f"{k}.png"))]

    def item(self, iid: str):
        """A picture by id — also one removed from the list, which tattoos made with it still use."""
        if not re.fullmatch(r"[0-9a-f]{8,12}", iid or ""):
            return None
        path = os.path.join(self.folder, f"{iid}.png")
        if not os.path.isfile(path):
            return None
        v = self.index().get(iid)
        if v is None:
            v = self._removed().get(iid) or {}
            if not v:
                with Image.open(path) as im:
                    v = {"aspect": round(im.width / im.height, 3)}
        return {"name": v.get("name", "Picture"), "aspect": float(v.get("aspect", 1)), "size": float(v.get("size", 40)),
                "mode": v.get("mode", "ink")}

    def _image(self, iid):
        path = os.path.join(self.folder, f"{iid}.png")
        key = (iid, os.path.getmtime(path))
        if key not in self._cache:
            im = Image.open(path)
            im.load()
            self._cache[key] = im.convert("RGBA")
        return self._cache[key]

    def picture(self, iid: str, w: int, h: int):
        """(mask, colours or None) of a picture at w×h."""
        info = self.item(iid)
        if info is None:
            return Image.new("L", (w, h), 0), None
        im = self._image(iid).resize((max(1, w), max(1, h)), Image.LANCZOS)
        if info["mode"] == "colour":
            return im.getchannel("A"), im.convert("RGB")
        return im.getchannel("A"), None

    def atlas(self, rel: str):
        """A whole 512×256 tattoo picture of the mod data (an "Earlier tattoos" layer), or None."""
        path = _abs(self.mod_dir, rel)
        try:
            key = (rel, os.path.getmtime(path))
        except OSError:
            return None
        if key not in self._cache:
            try:
                im = Image.open(path).convert("RGBA")
            except Exception:
                return None
            self._cache[key] = im if im.size == Rn.ATLAS else im.resize(Rn.ATLAS, Image.LANCZOS)
        return self._cache[key]

    def add(self, data: bytes, name: str = "", mode: str = "ink", light_on_dark: bool = False,
            threshold: float = .5) -> dict:
        """Any picture → a library item. "ink": its transparency when it has some, else its dark parts
        (`light_on_dark` for a light drawing on a dark background), `threshold` 0…1 = how dark counts as ink.
        "colour": kept with its colours (its own transparency, or the background colour taken out)."""
        im = Image.open(io.BytesIO(data))
        im.load()
        rgba = ImageOps.exif_transpose(im).convert("RGBA")
        alpha = rgba.getchannel("A")
        transparent = alpha.getextrema()[0] < 250
        if transparent:
            mask = alpha
        else:
            g = ImageOps.autocontrast(rgba.convert("L"), cutoff=2)
            ink = g if light_on_dark else ImageOps.invert(g)
            lo = int(20 + 160 * min(max(threshold, 0), 1))
            mask = ink.point(lambda v: 0 if v < lo else min(255, int((v - lo) * 255 / max(1, 255 - lo) * 1.6)))
        box = mask.getbbox()
        if not box:
            raise ValueError("No drawing found in this picture.")
        if mode == "colour":
            out = rgba.copy()
            out.putalpha(mask)
        else:
            mode = "ink"
            out = Image.merge("RGBA", (Image.new("L", mask.size, 0),) * 3 + (mask,))
        out = out.crop(box)
        if max(out.size) > 512:
            out.thumbnail((512, 512), Image.LANCZOS)
        iid = _digest(data, name.encode(), mode.encode(), str(light_on_dark).encode(), str(threshold).encode())
        _write_bytes(self.mod_dir, f"{LIBRARY_DIR}/{iid}.png", png_bytes(out))
        idx = self.index()
        idx[iid] = {"name": (name or "Picture")[:40], "aspect": round(out.width / out.height, 3), "size": 40, "mode": mode}
        gone = self._removed()
        if gone.pop(iid, None) is not None:             # imported again: back on the list
            _write_bytes(self.mod_dir, f"{LIBRARY_DIR}/removed.json", json.dumps(gone, indent=1).encode("utf-8"))
        _write_bytes(self.mod_dir, f"{LIBRARY_DIR}/index.json", json.dumps(idx, indent=1).encode("utf-8"))
        return {"id": f"user:{iid}", **idx[iid]}

    def _removed(self) -> dict:
        try:
            with open(os.path.join(self.folder, "removed.json"), encoding="utf-8") as fh:
                data = json.load(fh)
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def remove(self, iid: str) -> None:
        """Off the list; the picture itself stays for the designs that use it."""
        idx = self.index()
        entry = idx.pop(iid, None)
        if entry is None:
            return
        gone = self._removed()
        gone[iid] = entry
        _write_bytes(self.mod_dir, f"{LIBRARY_DIR}/removed.json", json.dumps(gone, indent=1).encode("utf-8"))
        _write_bytes(self.mod_dir, f"{LIBRARY_DIR}/index.json", json.dumps(idx, indent=1).encode("utf-8"))


def preview_import(data: bytes, mode="ink", light_on_dark=False, threshold=.5) -> Image.Image:
    """What `Library.add` would keep, without saving it (RGBA, ink in dark grey)."""
    im = Image.open(io.BytesIO(data))
    im.load()
    rgba = ImageOps.exif_transpose(im).convert("RGBA")
    alpha = rgba.getchannel("A")
    if alpha.getextrema()[0] < 250:
        mask = alpha
    else:
        g = ImageOps.autocontrast(rgba.convert("L"), cutoff=2)
        ink = g if light_on_dark else ImageOps.invert(g)
        lo = int(20 + 160 * min(max(threshold, 0), 1))
        mask = ink.point(lambda v: 0 if v < lo else min(255, int((v - lo) * 255 / max(1, 255 - lo) * 1.6)))
    if mode == "colour":
        out = rgba.copy()
    else:
        out = Image.new("RGBA", rgba.size, (28, 36, 51, 255))
    out.putalpha(mask)
    return out


# ── reading what the player wears ────────────────────────────────────────────
def is_tattoo_path(rel) -> bool:
    rel = str(rel or "").replace("\\", "/")
    return rel.startswith(TATTOO_DIR + "/") and not rel.startswith(LIBRARY_DIR + "/")


def tattoo_of(stats) -> str:
    """The player's tattoo layer (the first one in skin_overlay), or ""."""
    from app import appearance as A
    return next((r for r in A.overlay_list(stats.get("skin_overlay")) if is_tattoo_path(r)), "")


def _sidecar(mod_dir, rel):
    try:
        with open(_abs(mod_dir, os.path.splitext(rel)[0] + ".json"), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else None
    except (OSError, ValueError):
        return None


def load_design(stats, mod_dir, library) -> dict:
    """The design of the tattoos the player wears (empty design when none)."""
    rel = tattoo_of(stats)
    if not rel or not os.path.isfile(_abs(mod_dir, rel)):
        return Rn.clean_design({})
    data = _sidecar(mod_dir, rel)
    if data is not None and isinstance(data.get("layers"), list):
        return Rn.clean_design(data, library)
    # a picture made elsewhere: kept whole, as one layer per limb
    return Rn.clean_design({"layers": [
        {"id": f"earlier{limb}", "motif": Rn.ATLAS_MOTIF, "src": rel, "limb": limb, "side": "both",
         "name": "Earlier tattoos", "opacity": 1, "soft": 0} for limb in Rn.LIMBS]}, library)


def skin_source(stats, mod_dir) -> dict:
    """{"skin": the skin value the adjusted skin is made from ("" or a stock tone or an image path),
        "adjust": the current adjustment, "rel": the adjusted skin file the player wears or ""}."""
    skin = str(stats.get("skin") or "")
    if skin.startswith(SKIN_DIR + "/"):
        data = _sidecar(mod_dir, skin)
        if data is not None and "adjust" in data:
            return {"skin": str(data.get("from") or ""), "adjust": Rn.clean_adjust(data.get("adjust")), "rel": skin}
    return {"skin": skin, "adjust": Rn.clean_adjust({}), "rel": ""}


def source_image(stats, mod_dir, skin_value, stock_image) -> Image.Image:
    """The skin texture `skin_value` stands for (custom image, or the stock tone — gloved when the player
    wears the stock gloves), 512×256 RGBA. `stock_image(entry)` decodes a skins.fsh entry."""
    from app import appearance as A
    st = dict(stats)
    st["skin"] = skin_value
    st["skin_overlay"] = []
    resolved = A.resolve(st, mod_dir)
    if resolved["custom_skin"]:
        try:
            base = Image.open(resolved["custom_skin"]).convert("RGBA")
        except Exception:
            base = stock_image(A.stock_entry(resolved)).convert("RGBA")
    else:
        base = stock_image(A.stock_entry(resolved)).convert("RGBA")
    return base if base.size == Rn.ATLAS else base.resize(Rn.ATLAS, Image.LANCZOS)


def other_layers(stats, mod_dir) -> list[Image.Image]:
    """The layers painted over the tattoos (baselayers, straps, custom gloves), bottom first."""
    from app import appearance as A
    st = dict(stats)
    st["skin_overlay"] = [r for r in A.overlay_list(stats.get("skin_overlay")) if not is_tattoo_path(r)]
    out = []
    for path in A.resolve(st, mod_dir)["layers"]:
        try:
            out.append(Image.open(path).convert("RGBA"))
        except Exception:
            continue
    return out


# ── writing ──────────────────────────────────────────────────────────────────
def write_tattoos(mod_dir, pid, design, base, library) -> str:
    """Flatten the design onto `base` (the skin it lies on) and write it; "" when it has no ink."""
    pid = _safe_pid(pid)
    if not Rn.has_ink(design):
        return ""
    data = png_bytes(Rn.render_overlay(design, base, library))
    meta = json.dumps({"version": 2, "layers": design["layers"]}, indent=1).encode("utf-8")
    stem = f"{TATTOO_DIR}/{pid}_{_digest(data, meta)}"
    _write_bytes(mod_dir, stem + ".json", meta)
    return _write_bytes(mod_dir, stem + ".png", data)


def write_skin(mod_dir, pid, source_value, adjust, source_img) -> str:
    """The adjusted skin, written; "" when nothing is adjusted (the source is then the player's skin)."""
    pid = _safe_pid(pid)
    adjust = Rn.clean_adjust(adjust)
    if not Rn.is_adjusted(adjust):
        return ""
    data = png_bytes(Rn.adjust_skin(source_img, adjust).convert("RGB"))
    meta = json.dumps({"from": source_value, "adjust": adjust}, indent=1).encode("utf-8")
    stem = f"{SKIN_DIR}/{pid}_tint_{_digest(data, meta)}"
    _write_bytes(mod_dir, stem + ".json", meta)
    return _write_bytes(mod_dir, stem + ".png", data)


def put_on(stats, tattoo_rel, skin_value=None) -> None:
    """Point one season at the tattoos (first in skin_overlay, replacing any earlier tattoo layer; "" = none)
    and, when `skin_value` is given, at that skin."""
    from app import appearance as A
    rest = [r for r in A.overlay_list(stats.get("skin_overlay")) if not is_tattoo_path(r)]
    stats["skin_overlay"] = ([tattoo_rel] if tattoo_rel else []) + rest
    if skin_value is not None:
        stats["skin"] = skin_value


def referenced(records) -> set:
    """Every skin / skin_overlay path the given player records use."""
    from app import appearance as A
    out = set()
    for rec in records:
        for st in ((rec or {}).get("stats") or {}).values():
            if not isinstance(st, dict):
                continue
            out.update(A.overlay_list(st.get("skin_overlay")))
            if st.get("skin"):
                out.add(str(st["skin"]))
    return out


def cleanup(mod_dir, pid, keep: set) -> list[str]:
    """Remove this player's tattoo / adjusted-skin versions that `keep` (paths still used anywhere) doesn't
    name. Only files named like this module names them; returns what was removed."""
    pid = _safe_pid(pid)
    keep_stems = {os.path.splitext(k)[0] for k in keep}
    ours = re.compile(re.escape(pid) + r"_(?:tint_)?[0-9a-f]{10}\.(?:png|json)")
    gone = []
    for folder in (TATTOO_DIR, SKIN_DIR):
        try:
            names = os.listdir(_abs(mod_dir, folder))
        except OSError:
            continue
        for name in names:
            if not ours.fullmatch(name):
                continue
            rel = f"{folder}/{name}"
            if os.path.splitext(rel)[0] in keep_stems:
                continue
            _remove(mod_dir, rel)
            gone.append(rel)
    return gone
