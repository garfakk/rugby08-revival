"""
screens/tournament/look_preview.py — what a competition look puts in a match
=============================================================================
The tournament editor's LOOK tab shows a look instead of naming it:

- LookGallery: every competition look as a card (its logo and name), plus
  "the home team's" (no look); click one to pick it.
- GraphicsStrip: the pictures the picked look brings: tournament logo, the
  two pitch logos, the ball, the pads, the posts and the ad boards.
- LookStadium: a stadium in 3D (ui/stadium_view) with the look's pitch logos
  on the grass and its pads, posts and boards on, as a match lays them.

A look is a competition_branding choice key ("world_cup:2023"); "" = none.
"""
import os

from PyQt5.QtCore import QRectF, Qt, QTimer, pyqtSignal
from PyQt5.QtGui import QColor, QFont, QPainter, QPixmap
from PyQt5.QtWidgets import QGridLayout, QHBoxLayout, QSizePolicy, QVBoxLayout, QWidget

from app import competition_branding
from shared.config import config
from shared.log import get_logger
from ui.broadcast import tracked_font
from ui.editor_kit import ChoiceField, Note, compact_button
from ui.theme import (ACCENT, BG_CARD, BORDER, FG_PRIMARY, FG_SECONDARY, FG_TERTIARY, FONT_DISPLAY,
                      T_LABEL, T_SMALL)

from .common import ActivatableCard, placeholder_crest

log = get_logger(__name__)

NONE_LABEL = "The home team's"
DEFAULT_LOOK = "default"          # data/competitions/default: what a match without a look shows


# ── reading a look ────────────────────────────────────────────────────────
def look_info(ds, choice):
    """(folder, info) of a look; ("", {}) for none."""
    tid, info = competition_branding.resolve(ds, choice)
    if not tid:
        return "", {}
    return ds.tournaments_folder_path.get(tid, ""), info or {}


def _file(folder, rel, frame=1):
    if not folder or not rel:
        return ""
    path = os.path.join(folder, rel.replace("%", str(frame)))
    return path if os.path.isfile(path) else ""


def _ads_pixmap(path, size):
    """The first board of an ad set (a .fsh, a picture or a folder of them)."""
    key = ("ads", path, size)
    if key not in _PIX:
        pix = None
        try:
            from io import BytesIO
            from backend import adboards
            ad_set = adboards.load_set(path)
            boards = list(ad_set.sheets or []) + list(ad_set.strips or [])
            if boards:
                buf = BytesIO()
                boards[0].image().convert("RGBA").save(buf, "PNG")
                pix = QPixmap()
                pix.loadFromData(buf.getvalue(), "PNG")
                pix = pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        except Exception as e:
            log.warning(f"ads preview {path}: {e}")
        _PIX[key] = pix
    return _PIX[key]


def look_files(ds, choice):
    """[(key, caption, path)] of the pictures a look brings ("" = the
    game's or the stadium's own)."""
    folder, info = look_info(ds, choice)
    ads = (info.get("adboards") or "").strip()
    return [
        ("logo", "Tournament logo", _file(folder, info.get("logo") or "")),
        ("pitch1", "Pitch logo · centre", _file(folder, info.get("pitch_logo") or "", 1)),
        ("pitch2", "Pitch logo · 22s", _file(folder, info.get("pitch_logo") or "", 2)),
        ("ball", "Ball", _file(folder, info.get("ball") or "", 1)),
        ("pads", "Post pads", _file(folder, info.get("pads") or "")),
        ("posts", "Posts", _file(folder, info.get("posts") or "")),
        ("ads", "Ad boards", os.path.join(folder, ads) if folder and ads and
         os.path.exists(os.path.join(folder, ads)) else ""),
    ]


def has_trophy(ds, choice):
    _folder, info = look_info(ds, choice)
    trophy = info.get("trophy") or {}
    return isinstance(trophy, dict) and bool(trophy.get("ceremony"))


def dressing_refs(ds, choice):
    """{"pads" | "posts" | "ads": set ref} the look dresses a stadium with."""
    folder, info = look_info(ds, choice)
    out = {}
    for kind, key in (("pads", "pads"), ("posts", "posts"), ("ads", "adboards")):
        rel = (info.get(key) or "").strip()
        if folder and rel and os.path.exists(os.path.join(folder, rel)):
            out[kind] = os.path.relpath(os.path.join(folder, rel),
                                        config.mod_data_directory).replace("\\", "/")
    return out


def look_choices(ds):
    """[(choice, label)] of the looks with at least one picture, newest
    edition first within a competition."""
    seen, out = set(), []
    for key in ("logo", "pitch_logo"):
        for choice, label in competition_branding.choices(ds, key):
            if choice not in seen:
                seen.add(choice)
                out.append((choice, label))
    return sorted(out, key=lambda c: (c[1].rstrip("0123456789 ").lower(), -_year(c[0])))


def _year(choice):
    tail = choice.rpartition(":")[2]
    return int(tail) if tail.isdigit() else 0


_PIX = {}


def _pixmap(path, size):
    if not path:
        return None
    key = (path, size)
    if key not in _PIX:
        pix = QPixmap(path)
        _PIX[key] = None if pix.isNull() else pix.scaled(size, size, Qt.KeepAspectRatio,
                                                         Qt.SmoothTransformation)
    return _PIX[key]


# ── the gallery ───────────────────────────────────────────────────────────
class LookCard(ActivatableCard):
    W, H = 150, 112

    def __init__(self, key, label, pix, parent=None):
        super().__init__(parent)
        self.key, self.label, self.pix = key, label, pix
        self.setFixedSize(self.W, self.H)
        self.setToolTip(label)

    def paintEvent(self, event):
        p = QPainter(self)
        self.paint_background(p)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        box = QRectF(10, 8, self.W - 20, 64)
        if self.pix is not None:
            s = min(box.width() / self.pix.width(), box.height() / self.pix.height())
            w, h = self.pix.width() * s, self.pix.height() * s
            p.drawPixmap(QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h), self.pix,
                         QRectF(self.pix.rect()))
        p.setFont(tracked_font(FONT_DISPLAY, T_SMALL, QFont.DemiBold, 0.4))
        p.setPen(QColor(FG_PRIMARY if self.selected else FG_SECONDARY))
        text = p.fontMetrics().elidedText(self.label, Qt.ElideRight, self.W - 16)
        p.drawText(QRectF(8, 76, self.W - 16, 30), Qt.AlignCenter, text)


class LookGallery(QWidget):
    """The looks as cards that wrap to the width. `picked(choice)`."""

    picked = pyqtSignal(str)

    def __init__(self, focus=None, parent=None):
        super().__init__(parent)
        self._focus = focus
        self.cards = []
        self._current = None
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(8)
        self._cols = 0
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

    def set_looks(self, ds, choices):
        for c in self.cards:
            if self._focus is not None:
                self._focus.unregister(c)
            c.setParent(None)
            c.deleteLater()
        self.cards = []
        rows = [("", NONE_LABEL, placeholder_crest(56))]
        for choice, label in choices:
            path = next((p for k, _c, p in look_files(ds, choice) if k == "logo" and p), "")
            rows.append((choice, label, _pixmap(path, 96) or placeholder_crest(56)))
        for key, label, pix in rows:
            card = LookCard(key, label, pix)
            card.activated.connect(lambda k=key: self.picked.emit(k))
            if self._focus is not None:
                self._focus.register(card)
            self.cards.append(card)
        self._cols = 0
        self._layout()
        self.set_current(self._current or "")

    def set_current(self, choice):
        self._current = choice
        for c in self.cards:
            c.selected = c.key == choice
            c.update()

    def _layout(self):
        cols = max(1, (self.width() + 8) // (LookCard.W + 8))
        if cols == self._cols:
            return
        self._cols = cols
        for c in self.cards:
            self._grid.removeWidget(c)
        for i, c in enumerate(self.cards):
            self._grid.addWidget(c, i // cols, i % cols)
        self._grid.setColumnStretch(cols, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        cols = max(1, (width + 8) // (LookCard.W + 8))
        rows = (len(self.cards) + cols - 1) // cols
        return rows * (LookCard.H + 8)


# ── the pictures ──────────────────────────────────────────────────────────
class _Picture(QWidget):
    S = 96

    def __init__(self, caption, parent=None):
        super().__init__(parent)
        self.caption = caption
        self.pix = None
        self.note = ""
        self.setFixedSize(self.S + 30, self.S + 34)

    def set(self, pix, note=""):
        self.pix, self.note = pix, note
        self.setToolTip(note or self.caption)
        self.update()

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        box = QRectF(15, 0, self.S, self.S)
        p.fillRect(box, QColor(BG_CARD))
        p.setPen(QColor(BORDER))
        p.drawRect(box.adjusted(0.5, 0.5, -0.5, -0.5))
        if self.pix is not None:
            s = min((self.S - 8) / self.pix.width(), (self.S - 8) / self.pix.height())
            w, h = self.pix.width() * s, self.pix.height() * s
            p.drawPixmap(QRectF(box.center().x() - w / 2, box.center().y() - h / 2, w, h), self.pix,
                         QRectF(self.pix.rect()))
        else:
            p.setPen(QColor(FG_TERTIARY))
            p.setFont(tracked_font(FONT_DISPLAY, T_SMALL - 1, QFont.DemiBold, 0.4))
            p.drawText(box.adjusted(6, 0, -6, 0), Qt.AlignCenter | Qt.TextWordWrap, self.note or "—")
        p.setPen(QColor(FG_SECONDARY))
        p.setFont(tracked_font(FONT_DISPLAY, T_SMALL - 1, QFont.DemiBold, 0.4))
        p.drawText(QRectF(0, self.S + 2, self.width(), 30), Qt.AlignHCenter | Qt.AlignTop | Qt.TextWordWrap,
                   self.caption)


class GraphicsStrip(QWidget):
    """The look's pictures side by side, wrapping to the width."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._grid = QGridLayout(self)
        self._grid.setContentsMargins(0, 0, 0, 0)
        self._grid.setSpacing(6)
        self.pictures = {}
        for key, caption, _p in look_files(None, ""):
            self.pictures[key] = _Picture(caption)
        self.trophy = Note("", color=FG_SECONDARY, size=T_LABEL)
        self._cols = 0
        self._layout()

    def show_look(self, ds, choice):
        own = {"pads": "the stadium's own", "posts": "the stadium's own", "ads": "the stadium's own",
               "ball": "the home team's", "logo": "none", "pitch1": "the game's own",
               "pitch2": "the game's own"}
        files = look_files(ds, choice)
        if not choice:                  # no look: a match shows the default pictures
            default = dict((k, p) for k, _c, p in look_files(ds, DEFAULT_LOOK))
            files = [(k, c, default.get(k, "") if k.startswith("pitch") else p) for k, c, p in files]
        for key, _caption, path in files:
            pix = _ads_pixmap(path, 192) if key == "ads" and path else _pixmap(path, 192)
            self.pictures[key].set(pix, own[key])
        self.trophy.setText("Its own trophy is lifted at the end." if has_trophy(ds, choice) else
                            "The usual trophy is lifted at the end.")

    def _layout(self):
        cols = max(1, (self.width() + 6) // (_Picture.S + 36))
        if cols == self._cols:
            return
        self._cols = cols
        for w in self.pictures.values():
            self._grid.removeWidget(w)
        for i, w in enumerate(self.pictures.values()):
            self._grid.addWidget(w, i // cols, i % cols)
        self._grid.removeWidget(self.trophy)
        self._grid.addWidget(self.trophy, len(self.pictures) // cols + 1, 0, 1, cols)
        self._grid.setColumnStretch(cols, 1)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout()


# ── the stadium ───────────────────────────────────────────────────────────
class LookStadium(QWidget):
    """A stadium in 3D wearing the look. The scene loads when first shown."""

    VIEWS = (("broadcast", "MAIN STAND"), ("pitch", "PITCH LEVEL"), ("aerial", "FROM ABOVE"))

    def __init__(self, ds, focus=None, parent=None):
        super().__init__(parent)
        self.ds = ds
        self._choice = ""
        self._sid = ""
        self._scene_key = None
        self._scene = None
        self._shown = None
        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        bar = QHBoxLayout()
        bar.setSpacing(6)
        self.f_stadium = ChoiceField("stadium", allow_blank=False, display=self._stadium_name)
        self.f_stadium.searchable = True
        self.f_stadium.popup_title = "see it in"
        self.f_stadium.label_width = 80
        self.f_stadium.edited.connect(self.set_stadium)
        bar.addWidget(self.f_stadium, stretch=1)
        v.addLayout(bar)
        views = QHBoxLayout()
        views.setSpacing(6)
        self.view_btns = {}
        for name, text in self.VIEWS:
            b = compact_button(text)
            b.clicked.connect(lambda _=False, n=name: self.view.set_view(n))
            views.addWidget(b)
            self.view_btns[name] = b
        views.addStretch(1)
        v.addLayout(views)
        from ui.stadium_view import StadiumView
        self.view = StadiumView()
        self.view.setMinimumSize(240, 300)
        v.addWidget(self.view, stretch=1)
        v.addWidget(Note("Drag to turn round, wheel to zoom.", color=FG_TERTIARY))
        if focus is not None:
            for w in (self.f_stadium, *self.view_btns.values()):
                focus.register(w)

    def _stadium_name(self, sid):
        info = self.ds.stadiums.get(str(sid)) or {}
        return info.get("name") or f"stadium {sid}"

    def stadiums(self):
        """The stadiums that have a 3D scene to show."""
        from backend import stadium_scene
        out = []
        for sid, info in self.ds.stadiums.items():
            if not isinstance(info, dict):
                continue
            envs = stadium_scene.environments(info)
            if envs:
                out.append(str(sid))
        return sorted(out, key=lambda s: self._stadium_name(s).lower())

    def set_stadium(self, sid):
        sid = str(sid or "")
        if sid == self._sid:
            return
        self._sid = sid
        if self.f_stadium.value() != sid:
            self.f_stadium.set_value(sid)
        if self.isVisible():
            self._load()

    def set_look(self, choice):
        self._choice = choice or ""
        if self._scene is not None:
            self._dress()

    def prepare(self, preferred=()):
        """Fill the stadium list once; `preferred`: stadium ids to show
        first (the tournament's own venues)."""
        if getattr(self, "_options", None) is None:
            self._options = self.stadiums()
            self.f_stadium.set_options(self._options)
        options = self._options
        if self._sid not in options:
            sid = next((str(s) for s in preferred if str(s) in options), "")
            if not sid:
                sid = next((s for s in options if (self.ds.stadiums.get(s) or {}).get("is_custom")),
                           options[0] if options else "")
            self._sid = ""
            self.set_stadium(sid)

    def showEvent(self, event):
        super().showEvent(event)
        QTimer.singleShot(0, self._load)

    def _load(self):
        if not self._sid:
            self.view.set_message("No stadium with a 3D scene: is the game folder set in Settings?")
            return
        info = self.ds.stadiums.get(self._sid) or {}
        from backend import stadium_scene
        envs = stadium_scene.environments(info)
        env = "day" if "day" in envs else (envs[0] if envs else "")
        key = (self._sid, env)
        if key == self._scene_key and self._scene is not None:
            return
        self._scene_key = key
        self.view.set_message("Loading…")
        self.view.repaint()

        def go():
            if self._scene_key != key:
                return
            try:
                path = stadium_scene.pack_path(info, env)
                scene = stadium_scene.load(path) if path else None
            except Exception:
                log.exception("look preview scene")
                scene = None
            if scene is None:
                self._scene = None
                self.view.set_message("This stadium's 3D scene isn't found: is the game folder set in "
                                      "Settings?")
                return
            self._scene = scene
            self._shown = None
            self.view.set_message("")
            self.view.set_scene(scene)
            self.view.set_environment(env)
            self._dress()
        QTimer.singleShot(10, go)

    def _dress(self):
        """The look's pitch logos, pads, posts and boards on the stadium."""
        if self._scene is None or self._shown == (self._sid, self._choice):
            return
        self._shown = (self._sid, self._choice)
        from PIL import Image
        from app import dressing
        from backend import pitch_logos, stadium_scene
        info = self.ds.stadiums.get(self._sid) or {}
        try:
            layout = (pitch_logos.clean(info["pitch_logos"]) if info.get("pitch_logos") is not None
                      else pitch_logos.stock_layout())
            quads = pitch_logos.quads(layout)
        except Exception as e:                  # a broken model must not break the view
            log.warning(f"pitch logos preview: {e}")
            quads = {}
        folder, look = look_info(self.ds, self._choice or DEFAULT_LOOK)
        pattern = (look.get("pitch_logo") or "").strip()
        images = {}
        for i, tag in ((1, "loga"), (2, "logb")):
            path = _file(folder, pattern, i)
            if path:
                try:
                    images[tag] = Image.open(path).convert("RGBA")
                except (OSError, ValueError):
                    pass
        self.view.set_logos(quads, images)
        refs = dressing_refs(self.ds, self._choice)
        want = {k: refs.get(k) or dressing.stadium_default(info, k) for k in ("pads", "posts", "ads")}
        textures = {}
        textures.update(stadium_scene.pads_textures(want["pads"] or "", want["posts"] or ""))
        textures.update(stadium_scene.ads_textures(self._scene, want["ads"] or ""))
        if textures:
            self.view.set_textures(textures)
