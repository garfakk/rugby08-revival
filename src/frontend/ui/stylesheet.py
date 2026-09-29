"""
ui/stylesheet.py — Global Qt Stylesheet
=========================================
Builds the application-wide QSS from theme tokens.
Applied once via app.setStyleSheet(APP_STYLESHEET).
"""

from ui.theme import (
    BG_BASE, BG_PANEL, BG_CARD, BG_RAISED, BG_HIGHLIGHT,
    BORDER, BORDER_EM,
    ACCENT, ACCENT_LITE, ACCENT_DARK, ACCENT_DIM,
    FG_PRIMARY, FG_SECONDARY, FG_MUTED,
    DANGER, DANGER_LITE,
    FONT_DISPLAY, FONT_BODY, FONT_BODY_STACK,
    GRAD_HEADER,
)

APP_STYLESHEET = f"""

/* ── Base ───────────────────────────────────────────────────────────────── */
QWidget {{
    background-color: {BG_BASE};
    color: {FG_PRIMARY};
    font-family: {FONT_BODY_STACK};
    font-size: 10pt;
    selection-background-color: {ACCENT_DIM};
    selection-color: {ACCENT_LITE};
}}

/* ── GroupBox ───────────────────────────────────────────────────────────── */
QGroupBox {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-top: 2px solid {ACCENT_DARK};
    border-radius: 0px;
    margin-top: 20px;
    padding: 14px 12px 12px 12px;
    font-family: "{FONT_DISPLAY}";
    font-size: 9pt;
    font-weight: bold;
    color: {ACCENT};
    letter-spacing: 2px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -1px;
    padding: 0 10px;
    background-color: {BG_PANEL};
    color: {ACCENT};
}}

/* ── Labels ─────────────────────────────────────────────────────────────── */
QLabel {{
    background: transparent;
    color: {FG_PRIMARY};
}}

/* ── ComboBox ───────────────────────────────────────────────────────────── */
QComboBox {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 0px;
    padding: 6px 12px;
    color: {FG_PRIMARY};
    min-height: 30px;
    font-family: "{FONT_BODY}";
}}
QComboBox:hover {{
    border: 1px solid {BORDER_EM};
    background-color: {BG_RAISED};
}}
QComboBox:focus {{
    border: 2px solid {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    border-left: 1px solid {BORDER};
    width: 28px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid {FG_MUTED};
    margin-right: 8px;
}}
QComboBox::down-arrow:hover {{
    border-top-color: {ACCENT};
}}
QComboBox QAbstractItemView {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER_EM};
    border-radius: 0px;
    selection-background-color: {ACCENT_DIM};
    selection-color: {ACCENT_LITE};
    outline: none;
    padding: 2px;
}}

/* ── LineEdit ───────────────────────────────────────────────────────────── */
QLineEdit {{
    background-color: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 0px;
    padding: 6px 12px;
    color: {FG_PRIMARY};
}}
QLineEdit:focus {{ border: 1px solid {ACCENT_DARK}; }}

/* ── TextEdit ───────────────────────────────────────────────────────────── */
QTextEdit {{
    background-color: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 0px;
    padding: 10px;
    color: {FG_PRIMARY};
    font-family: "{FONT_DISPLAY}";
    font-size: 9pt;
}}

/* ── Scrollbar ──────────────────────────────────────────────────────────── */
QScrollBar:vertical {{
    background: {BG_PANEL};
    width: 8px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:vertical {{
    background: {BORDER_EM};
    min-height: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:vertical:hover {{ background: {ACCENT_DARK}; }}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical  {{ height: 0; border: none; }}
QScrollBar::add-page:vertical,
QScrollBar::sub-page:vertical  {{ background: none; }}

QScrollBar:horizontal {{
    background: {BG_PANEL};
    height: 8px;
    margin: 0;
    border: none;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER_EM};
    min-width: 30px;
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{ background: {ACCENT_DARK}; }}
QScrollBar::add-line:horizontal,
QScrollBar::sub-line:horizontal  {{ width: 0; border: none; }}
QScrollBar::add-page:horizontal,
QScrollBar::sub-page:horizontal  {{ background: none; }}

/* ── Separators ─────────────────────────────────────────────────────────── */
QFrame[frameShape="4"] {{ color: {BORDER}; }}
QFrame[frameShape="5"] {{ color: {BORDER}; }}

/* ── MessageBox ─────────────────────────────────────────────────────────── */
QMessageBox               {{ background-color: {BG_PANEL}; }}
QMessageBox QLabel        {{ color: {FG_PRIMARY}; }}

/* ── Splitter ───────────────────────────────────────────────────────────── */
QSplitter::handle {{ background: {BORDER}; }}

/* ── ScrollArea ─────────────────────────────────────────────────────────── */
QScrollArea {{
    border: none;
    background: transparent;
}}

"""
