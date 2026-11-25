"""ui/dressing_picker.py — the match-setup stadium dressing choosers (pads,
posts, ads; app/dressing.py). Two collapsible sections: the sets suggested
for this match (the stadium's own, its teams' competitions') and all the
others; the open list previews the option under the cursor: pads and posts
on a 3D goal, ads as a strip of boards."""
from PIL import Image
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QLabel, QVBoxLayout, QWidget

from shared.log import get_logger
from ui.dropdown import DropdownRow, PopupList
from ui.theme import DROPDOWN_BORDER

log = get_logger(__name__)

PREVIEW_H = 190
STRIP_H = 96
SUGGESTED, OTHERS = "Suggested", "All others"
GROUPS = (SUGGESTED, OTHERS)


def _group(option):
    return SUGGESTED if option.get("suggested") else OTHERS


def _pixmap(image):
    image = image.convert("RGBA")
    q = QImage(image.tobytes(), image.width, image.height, QImage.Format_RGBA8888)
    return QPixmap.fromImage(q.copy())


class DressingRow(DropdownRow):
    """values are {"label", "ref"} option dicts (app/dressing.choices).
    `preview(option)` gives what to show for one: {tag: image} for a 3D
    goal (kind "pads"/"posts"), a PIL image strip for "ads"."""

    def __init__(self, label, kind, get_choices, preview, parent=None):
        super().__init__(label, display=self._label_of, parent=parent)
        self.kind = kind
        self._get_choices = get_choices
        self._preview = preview
        self.group = _group
        self.group_order = GROUPS
        self.group_open = (SUGGESTED,)

    @staticmethod
    def _label_of(option):
        return option["label"]

    def refresh(self, ref=None):
        """Reread the options and select `ref` (the current one when None)."""
        keep = (self.current() or {}).get("ref", "") if ref is None else ref
        values = self._get_choices(keep)
        index = next((i for i, v in enumerate(values) if keep in v.get("refs", [v["ref"]])), 0)
        self.set_values(values, index=index)

    def current_ref(self):
        return (self.current() or {}).get("ref", "")

    def effective_ref(self, option=None):
        """The set `option` (the current one) stands for: "Stadium default"
        resolves to the stadium's own."""
        option = option or self.current() or {}
        return option.get("ref") or option.get("default_ref", "")

    # ── popup ──────────────────────────────────────────────────────────────
    def _make_preview(self):
        holder = QWidget()
        v = QVBoxLayout(holder)
        v.setContentsMargins(0, 0, 0, 4)
        if self.kind == "ads":
            view = QLabel()
            view.setAlignment(Qt.AlignCenter)
            view.setFixedHeight(STRIP_H + 8)
            holder.setFixedHeight(STRIP_H + 12)

            def show(option):
                try:
                    strip = self._preview(option)
                except Exception as e:          # a broken set must not break the list
                    log.warning(f"ads preview: {e}")
                    strip = None
                view.setPixmap(_pixmap(strip) if strip is not None else QPixmap())
        else:
            from ui.posts_view import PostsView     # GL stack only when opened
            view = PostsView(view="pads" if self.kind == "pads" else "posts")
            holder.setFixedHeight(PREVIEW_H)

            def show(option):
                try:
                    view.show_images(self._preview(option))
                except Exception as e:
                    log.warning(f"{self.kind} preview: {e}")
        v.addWidget(view)
        return holder, show

    def _open_popup(self):
        if not self._values:
            return
        screen = self.window()
        extra = STRIP_H + 12 if self.kind == "ads" else PREVIEW_H
        popup = PopupList(screen, width=max(340, self.width()), height=380 + extra,
                          own_keys=True, show_title=False, list_bg=DROPDOWN_BORDER)
        holder, show = self._make_preview()
        popup.set_toolbar_widget(holder)
        current = self.current()
        self._fill_grouped(popup, current)
        popup.hovered.connect(lambda option: show(option) if isinstance(option, dict) else None)
        popup.picked.connect(self._on_picked)
        popup.closed.connect(self._on_popup_closed)
        popup.open_at(self, screen, gap=0, own_toggle=True)
        current_i = next((i for i, r in enumerate(popup._rows) if r.data is current), None)
        if current_i is not None:
            popup.set_highlight(current_i, scroll=True)
        if current is not None:
            show(current)
        self._popup = popup
        self._popup_open = True
        self.update()

def ads_strip(ref, height=STRIP_H, boards=4):
    """A preview strip (PIL) of the first `boards` ad sheets of set `ref`."""
    from backend import adboards
    ad_set = adboards.load_ref(ref) if ref else None
    if ad_set is None:
        return None
    images = [b.image().convert("RGBA") for b in ad_set.sheets[:boards]]
    if not images:
        return None
    scaled = [im.resize((max(1, round(im.width * height / im.height)), height), Image.LANCZOS)
              for im in images]
    gap = 6
    out = Image.new("RGBA", (sum(i.width for i in scaled) + gap * (len(scaled) - 1), height), (0, 0, 0, 0))
    x = 0
    for im in scaled:
        out.paste(im, (x, 0))
        x += im.width + gap
    return out


TURF = (46, 110, 52, 255)
TURF_DARK = (40, 99, 46, 255)
LINE = (236, 240, 236, 255)
LINE_SOFT = (150, 190, 154, 255)      # the dashed lines, kept quieter than the logos
PITCH_PREVIEW_W = 440
# metres: half the field of play, in-goal depth, half the width, margin
_HALF_LEN, _IN_GOAL, _HALF_W, _MARGIN = 50.0, 7.0, 35.0, 2.0
_SUPER = 3                      # drawn this many times bigger, then scaled down


def _logo_images(ds, choice):
    """{"loga": pitch_logo_1, "logb": pitch_logo_2} (PIL) of a choice."""
    import os
    from app import competition_branding
    tid, info = competition_branding.resolve(ds, choice)
    pattern = (info.get("pitch_logo") or "").strip() if tid else ""
    folder = ds.tournaments_folder_path.get(tid, "") if tid else ""
    out = {}
    if not (folder and pattern):
        return out
    for frame, tag in ((1, "loga"), (2, "logb")):
        try:
            out[tag] = Image.open(os.path.join(folder, pattern.replace("%", str(frame)))).convert("RGBA")
        except (OSError, ValueError):
            pass
    return out


def _flat_quads(layout):
    """backend/pitch_logos.quads() without the game's model: each logo a
    flat rectangle (centre: a square of pitch_logo_1; side: a 2:1 strip
    along the pitch of one half of pitch_logo_2)."""
    import math
    from backend import pitch_logos
    out = {}
    for logo in pitch_logos.clean(layout):
        s = logo["size"] * pitch_logos.UNITS_PER_M
        if logo["kind"] == "centre":
            tag, hx, hz, v0, v1 = "loga", s / 2, s / 2, 0.0, 1.0
        else:
            tag, hx, hz = "logb", s / 4, s / 2
            v0, v1 = (0.0, 0.5) if logo["kind"] == "side_a" else (0.5, 1.0)
        a = math.radians(logo["angle"])
        cx, cz = logo["x"] * pitch_logos.UNITS_PER_M, logo["z"] * pitch_logos.UNITS_PER_M
        pos, uvs = [], []
        # corners (across, along) with their uv: u runs against z, v with x
        for (dx, dz), uv in (((-hx, hz), (0.0, v0)), ((hx, hz), (0.0, v1)),
                             ((-hx, -hz), (1.0, v0)), ((hx, -hz), (1.0, v1))):
            rx = dx * math.cos(a) + dz * math.sin(a)
            rz = -dx * math.sin(a) + dz * math.cos(a)
            pos.append((cx + rx, 0.0, cz + rz))
            uvs.append(uv)
        positions, uv_list, tris = out.setdefault(tag, ([], [], []))
        base = len(positions)
        positions += pos
        uv_list += uvs
        tris += [(base, base + 1, base + 2), (base + 2, base + 1, base + 3)]
    return out


def _draw_textured_triangle(canvas, texture, dst, src):
    """Paint the triangle `src` (texture pixels) of `texture` onto `canvas`
    at `dst` (canvas pixels): an affine map per triangle."""
    import numpy as np
    from PIL import ImageDraw
    (x0, y0), (x1, y1), (x2, y2) = dst
    m = np.array([[x0, y0, 1], [x1, y1, 1], [x2, y2, 1]], dtype=float)
    if abs(np.linalg.det(m)) < 1e-6:
        return
    a, b, c = np.linalg.solve(m, [p[0] for p in src])
    d, e, f = np.linalg.solve(m, [p[1] for p in src])
    layer = texture.transform(canvas.size, Image.AFFINE, (a, b, c, d, e, f), resample=Image.BICUBIC)
    mask = Image.new("L", canvas.size, 0)
    ImageDraw.Draw(mask).polygon([tuple(p) for p in dst], fill=255, outline=255)
    alpha = layer.getchannel("A")
    layer.putalpha(Image.fromarray(np.minimum(np.asarray(alpha), np.asarray(mask))))
    canvas.alpha_composite(layer)


def _pitch(scale):
    """The turf and lines, seen from above, long side across (PIL); pixel
    (x, y) of pitch point (along z, across x) metres is
    (cx - z * scale, cy + x * scale)."""
    from PIL import ImageDraw
    half_l = _HALF_LEN + _IN_GOAL + _MARGIN
    half_w = _HALF_W + _MARGIN
    w, h = round(2 * half_l * scale), round(2 * half_w * scale)
    img = Image.new("RGBA", (w, h), TURF)
    d = ImageDraw.Draw(img)
    cx, cy = w / 2, h / 2

    def px(z, x):
        return cx - z * scale, cy + x * scale

    stripe = 5.0                                        # mown bands, 5 m along the pitch
    z = -half_l
    i = 0
    while z < half_l:
        if i % 2:
            d.rectangle([px(z + stripe, -half_w), px(z, half_w)], fill=TURF_DARK)
        z += stripe
        i += 1
    lw = max(1, round(0.25 * scale))
    end = _HALF_LEN + _IN_GOAL
    d.rectangle([px(end, -_HALF_W), px(-end, _HALF_W)], outline=LINE, width=lw)
    for z in (-_HALF_LEN, -22 - 6, 0, 22 + 6, _HALF_LEN):          # try lines, 22s, halfway
        d.line([px(z, -_HALF_W), px(z, _HALF_W)], fill=LINE, width=lw)

    def dashed(z0, x0, z1, x1, dash=2.0, gap=2.0):
        import math
        length = math.hypot(z1 - z0, x1 - x0)
        t = 0.0
        while t < length:
            t1 = min(length, t + dash)
            d.line([px(z0 + (z1 - z0) * t / length, x0 + (x1 - x0) * t / length),
                    px(z0 + (z1 - z0) * t1 / length, x0 + (x1 - x0) * t1 / length)],
                   fill=LINE_SOFT, width=lw)
            t = t1 + gap

    for z in (-10, 10, -_HALF_LEN + 5, _HALF_LEN - 5):              # 10 m and 5 m lines
        dashed(z, -_HALF_W, z, _HALF_W)
    for x in (-_HALF_W + 5, _HALF_W - 5, -_HALF_W + 15, _HALF_W - 15):
        dashed(-_HALF_LEN, x, _HALF_LEN, x, dash=1.0, gap=9.0)
    for z in (-_HALF_LEN, _HALF_LEN):                                # the posts
        for x in (-2.8, 2.8):
            r = max(1.5, 0.45 * scale)
            x0, y0 = px(z, x)
            d.ellipse([x0 - r, y0 - r, x0 + r, y0 + r], fill=LINE)
    return img, px


def pitch_logo_preview(ds, choice, layout=None, width=PITCH_PREVIEW_W):
    """A competition's pitch logos where a match paints them, on a pitch
    seen from above (PIL): `layout` is the stadium's own (backend
    pitch_logos), None = the game's. A bare pitch for "none"."""
    from backend import pitch_logos
    images = _logo_images(ds, choice)
    scale = width / (2 * (_HALF_LEN + _IN_GOAL + _MARGIN)) * _SUPER
    canvas, px = _pitch(scale)
    if not images:
        return _shrink(canvas)
    if layout is None:
        layout = pitch_logos.stock_layout() or [
            {"kind": "centre", "x": 0.0, "z": 0.0, "size": 13.98, "angle": 0.0},
            {"kind": "side_a", "x": 0.0, "z": 27.96, "size": 7.77, "angle": 10.0},
            {"kind": "side_b", "x": 0.0, "z": -27.96, "size": 7.77, "angle": -10.0}]
    try:
        quads = pitch_logos.quads(layout)
    except Exception as e:                  # a broken model: the logos laid flat
        log.warning(f"pitch logos model: {e}")
        quads = {}
    if not quads:
        quads = _flat_quads(layout)
    for tag, (positions, uvs, tris) in quads.items():
        tex = images.get(tag)
        if tex is None:
            continue
        tw, th = tex.size
        for tri in tris:
            dst = [px(positions[i][2] / pitch_logos.UNITS_PER_M, positions[i][0] / pitch_logos.UNITS_PER_M)
                   for i in tri]
            src = [(uvs[i][0] * tw, uvs[i][1] * th) for i in tri]
            _draw_textured_triangle(canvas, tex, dst, src)
    return _shrink(canvas)


def _shrink(canvas):
    return canvas.resize((round(canvas.width / _SUPER), round(canvas.height / _SUPER)), Image.LANCZOS)


class PitchLogoRow(DropdownRow):
    """The match-setup pitch logo chooser: values are (choice, label); the
    open list shows the logos of the option under the cursor on a pitch
    (`preview(choice)`: pitch_logo_preview)."""

    PREVIEW_W = PITCH_PREVIEW_W
    PREVIEW_H = round(PITCH_PREVIEW_W * (_HALF_W + _MARGIN) / (_HALF_LEN + _IN_GOAL + _MARGIN))

    def __init__(self, label, preview, parent=None):
        super().__init__(label, display=lambda t: t[1], parent=parent)
        self._preview = preview

    def _open_popup(self):
        if not self._values:
            return
        screen = self.window()
        extra = self.PREVIEW_H + 16
        popup = PopupList(screen, width=max(self.PREVIEW_W + 16, self.width()), height=300,
                          own_keys=True, show_title=False, list_bg=DROPDOWN_BORDER)
        view = QLabel()
        view.setAlignment(Qt.AlignCenter)
        view.setFixedHeight(extra)
        shown = {}                              # choice -> pixmap, while the list is open

        def show(option):
            if not isinstance(option, tuple):
                return
            if option[0] not in shown:
                try:
                    strip = self._preview(option[0])
                except Exception as e:          # a broken logo must not break the list
                    log.warning(f"logo preview: {e}")
                    strip = None
                shown[option[0]] = _pixmap(strip) if strip is not None else QPixmap()
            view.setPixmap(shown[option[0]])

        popup.set_toolbar_widget(view)
        current = self.current()
        current_i = None
        for i, v in enumerate(self._values):
            popup.add_row(self._display(v).upper(), v, selected=(v == current))
            if v == current:
                current_i = i
        popup.size_to(len(self._values))
        popup.hovered.connect(show)
        popup.picked.connect(self._on_picked)
        popup.closed.connect(self._on_popup_closed)
        popup.open_at(self, screen, gap=0, own_toggle=True)
        if current_i is not None:
            popup.set_highlight(current_i, scroll=True)
        if current is not None:
            show(current)
        self._popup = popup
        self._popup_open = True
        self.update()


class TournamentLogoRow(PitchLogoRow):
    """The match-setup tournament logo chooser: values are (choice, label);
    the open list shows the logo of the option under the cursor."""
    PREVIEW_W, PREVIEW_H = 320, 150


def tournament_logo_preview(ds, choice, width=TournamentLogoRow.PREVIEW_W,
                            height=TournamentLogoRow.PREVIEW_H):
    """A competition's tournament logo fitted in width x height (PIL), None
    for "none" or nothing on disk."""
    import os
    from app import competition_branding
    tid, info = competition_branding.resolve(ds, choice)
    rel = (info.get("logo") or "").strip() if tid else ""
    folder = ds.tournaments_folder_path.get(tid, "") if tid else ""
    if not (folder and rel):
        return None
    try:
        im = Image.open(os.path.join(folder, rel)).convert("RGBA")
    except (OSError, ValueError):
        return None
    box = im.getbbox()                      # transparent margins trimmed
    if box:
        im = im.crop(box)
    k = min(width / im.width, height / im.height)
    return im.resize((max(1, round(im.width * k)), max(1, round(im.height * k))), Image.LANCZOS)
