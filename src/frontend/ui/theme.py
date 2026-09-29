"""
ui/theme.py — Design Tokens
============================
THE ONLY FILE you need to edit to retheme the entire application.

Broadcast-sports direction (dark stadium palette, condensed display type,
crest-forward) approved from the mockup review. Matches the tokens used to
render the mockups in scratchpad/mockup/gen_mockups.py so the built app and
the approved mockups agree.
"""
from pathlib import Path
from PyQt5.QtGui import QFont, QFontDatabase

# ── Colour Palette ────────────────────────────────────────────────────────────

# "Pitch at night": near-black, more saturated greens, like turf under
# floodlights, lifting toward a lit-grass green for highlights.
BG_BASE       = "#050f05"
BG_PANEL      = "#091406"
BG_CARD       = "#091a09"
BG_RAISED     = "#10200c"
BG_HIGHLIGHT  = "#0d1d0a"
# Dropdown surfaces use a blue field so open lists are distinct from panels.
DROPDOWN_BG   = "#071f37"
DROPDOWN_ROW  = "#0a2b4c"
DROPDOWN_FOCUS = "#0a2b4c"
DROPDOWN_BORDER = "#0c3a6b"
DROPDOWN_DISABLED_BG = "#091b2d"
DROPDOWN_TEXT = "#eef3ef"
DROPDOWN_SUBDUED_TEXT = "#cddbd3"
DROPDOWN_DISABLED_TEXT = "#5d7266"
DROPDOWN_FOCUS_TEXT = "#8fd3f4"
DROPDOWN_TAG = "#a9bdb2"
DROPDOWN_SUBTITLE = "#a9bdb2"
DROPDOWN_FOCUS_RAIL = "#8fd3f4"
DROPDOWN_SUBDUED_RAIL = "#46524b"
DROPDOWN_LABEL = "#cddbd3"
DROPDOWN_VALUE = "#eef3ef"
DROPDOWN_ARROW = "#5d7266"
DROPDOWN_TITLE = "#799bbc"

# Squad editor player-picker mode buttons (SUGGESTED / ALL).
SQUAD_PICKER_ACTIVE_BG = "#12304e"
SQUAD_PICKER_INACTIVE_BG = "#091b2d"
SQUAD_PICKER_ACTIVE_TEXT = "#A0A7B5"
SQUAD_PICKER_INACTIVE_TEXT = "#cddbd3"
SQUAD_PICKER_BORDER = "#4C536E"
SQUAD_PICKER_DIVIDER = "#3c4d6b"

# Non-dropdown list panels (for example SearchList in the editors).
LIST_BG = "#041E05"
LIST_ROW = "#043D07"
LIST_SELECTED = "#641d4f"
LIST_HOVER = "#81396b"
LIST_BORDER = "#041e04"
LIST_TEXT = "#eef3ef"
LIST_SUBDUED_TEXT = "#a9bdb2"
LIST_TAG = "#8fd3f4"
LIST_SUBTITLE = "#a9bdb2"

# Quiet borders stay in the green family; emphasised ones pick up the red.
# BORDER was #141f10 — only ~11,5,7 away from BG_CARD, so every dropdown /
# selector box it outlined read as a borderless smear against its own card.
# First bump (#2c3d24) still measured out too close to the fill once
# rendered (and worse over a remote display, which softens 1px lines) —
# this is ~5x the original's perceived brightness, on par with a typical
# dark-theme input border, not just a shade more green.
BORDER        = "#4a6b3c"
BORDER_EM     = "#107a13"

# Rugby 08 menu red — pure red, not pink (ACCENT ≈4.1:1 on BG_BASE,
# ACCENT_LITE ≈5.9:1, both large-text/decorative rather than body copy).
ACCENT        = "#e0202b"
ACCENT_LITE   = "#ff4d4d"
ACCENT_DARK   = "#a8121c"
# Selection / fill tint behind ACCENT_LITE text.
ACCENT_DIM    = "#3d1013"

HOME_TINT     = "#4fa8e8"
AWAY_TINT     = "#f2c14e"
GREEN         = "#7ccf4a"
GREEN_2         = "#095A0C"
# Orange, deliberately a different hue from ACCENT's red: a warning and a
# section heading must never be mistaken for each other at a glance.
WARN          = "#ff9f1c"
INFO          = "#8fd3f4"
BLOCKED       = "#46524b"

FG_PRIMARY    = "#eef3ef"
FG_SECONDARY  = "#cddbd3"
# Readable de-emphasised text (≈7.9:1 on BG_CARD, passes WCAG AA) — for
# placeholders, hints and secondary values the user still has to read.
FG_TERTIARY   = "#a9bdb2"
# Decorative only (≈3:1): dividers, disabled chrome. Never for text that
# carries information.
FG_MUTED      = "#5d7266"

# Pinker than ACCENT so an error doesn't read as a heading.
DANGER        = "#5c1020"
DANGER_LITE   = "#ff6b8a"

# Back-compat aliases (old code / widgets still reference these names)
BG_HIGH = BG_HIGHLIGHT

# ── Typography ────────────────────────────────────────────────────────────────
# Bundled OFL fonts registered with Qt below — never rely on the OS having them.
_FONTS_DIR = Path(__file__).parent / "fonts"
_FONT_FILES = [
    "BarlowCondensed-Bold.ttf",
    "BarlowCondensed-SemiBold.ttf",
    "BarlowCondensed-Regular.ttf",
    "Barlow-Regular.ttf",
    "Barlow-Medium.ttf",
]

_fonts_registered = False


def register_fonts():
    """Load the bundled fonts into the Qt font database. Safe to call more than
    once; safe to call before a QApplication exists (Qt just no-ops)."""
    global _fonts_registered
    if _fonts_registered:
        return
    for fname in _FONT_FILES:
        fp = _FONTS_DIR / fname
        if fp.exists():
            QFontDatabase.addApplicationFont(str(fp))
    _fonts_registered = True


FONT_DISPLAY = "Barlow Condensed"
FONT_BODY    = "Barlow"
# Fallback stacks for QSS (font-family accepts a comma list)
FONT_DISPLAY_STACK = f"'{FONT_DISPLAY}', 'DejaVu Sans Condensed', sans-serif"
FONT_BODY_STACK    = f"'{FONT_BODY}', 'DejaVu Sans', sans-serif"


def _qfont(family, size, weight=QFont.Normal):
    f = QFont(family, size, weight)
    f.setStyleStrategy(QFont.PreferAntialias)
    return f


F_HUGE  = _qfont(FONT_DISPLAY, 34, QFont.Bold)
F_H1    = _qfont(FONT_DISPLAY, 22, QFont.Bold)
F_H2    = _qfont(FONT_DISPLAY, 14, QFont.DemiBold)
F_H3    = _qfont(FONT_DISPLAY, 11, QFont.DemiBold)
F_BODY  = _qfont(FONT_BODY,    10)
F_SMALL = _qfont(FONT_BODY,     9)
F_MONO  = _qfont(FONT_DISPLAY,  9, QFont.DemiBold)

# ── Spacing & Geometry ────────────────────────────────────────────────────────
HEADER_HEIGHT    = 76
HEADER_BAR_H     = 3
BTN_HEIGHT       = 48
BTN_HEIGHT_SM    = 36
BTN_HEIGHT_BACK  = 40
PAGE_MARGIN      = 28
PAGE_MARGIN_WIDE = 100
SECTION_SPACING  = 16
KIT_PREVIEW_SIZE = 260

# Editor type scale (points). Nothing in the editors goes below T_SMALL.
T_DISPLAY = 26
T_TITLE   = 18
T_SECTION = 11
T_LABEL   = 11
T_VALUE   = 13
T_SMALL   = 10

EDITOR_ROW_H = 40

# Focus ring — applied to every focusable widget by the focus system.
FOCUS_RING = f"2px solid {ACCENT}"

# ── Gradient helpers (for QSS) ────────────────────────────────────────────────
GRAD_HEADER = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
    f" stop:0 #050b08, stop:1 {BG_PANEL})"
)
GRAD_PANEL = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
    f" stop:0 {BG_PANEL}, stop:1 {BG_BASE})"
)
GRAD_ACCENT_BTN = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
    f" stop:0 {ACCENT_LITE}, stop:0.5 {ACCENT}, stop:1 {ACCENT_DARK})"
)
GRAD_ACCENT_BTN_HOVER = (
    f"qlineargradient(x1:0, y1:0, x2:0, y2:1,"
    f" stop:0 #ff7a7a, stop:0.5 {ACCENT_LITE}, stop:1 {ACCENT})"
)
