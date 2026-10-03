"""Theme tokens + global QSS.

Extracted from app.py in v2.0. Holds the dark/light palettes, theme state,
and the single global stylesheet string. Other GUI modules call
``set_theme("light"|"dark")`` to flip, and read ``PALETTE`` directly.
"""

from __future__ import annotations

from typing import Literal

Theme = Literal["dark", "light"]


PALETTE_DARK: dict[str, str] = {
    "bg":              "#0c0c10",
    "bg_elev":         "#16161d",
    "panel":           "#1c1c24",
    "panel_hover":     "#23232d",
    "border":          "#26262f",
    "border_strong":   "#363640",
    "text":            "#e8e8ee",
    "text_muted":      "#8e8e9c",
    "text_dim":        "#5e5e6e",
    "accent":          "#a78bfa",   # softer violet
    "accent_dim":      "#7c5cfa",
    "success":         "#34d399",
    "warning":         "#fbbf24",
    "error":           "#fb7185",
    "selection":       "#2a2236",
    "selection_strong":"#3a2d50",
}


PALETTE_LIGHT: dict[str, str] = {
    "bg":              "#fbfbf9",
    "bg_elev":         "#f5f5f1",
    "panel":           "#ffffff",
    "panel_hover":     "#f0efe9",
    "border":          "#e6e3da",
    "border_strong":   "#cecabd",
    "text":            "#1c1b18",
    "text_muted":      "#6b6860",
    "text_dim":        "#9a978d",
    "accent":          "#6d49d6",
    "accent_dim":      "#5b3aaf",
    "success":         "#059669",
    "warning":         "#b45309",
    "error":           "#be123c",
    "selection":       "#f0ebff",
    "selection_strong":"#e0d6ff",
}


# Mutable global — read by every widget that builds stylesheets.
PALETTE: dict[str, str] = dict(PALETTE_DARK)
_THEME: str = "dark"


def set_theme(theme: str) -> None:
    """Flip the active palette. Callers should also re-apply the QSS to
    every top-level window via ``app.setStyleSheet(_qss())``."""
    global _THEME
    src = PALETTE_LIGHT if theme == "light" else PALETTE_DARK
    PALETTE.update(src)
    _THEME = theme


def current_theme() -> str:
    return _THEME


def _qss() -> str:
    """The global Qt stylesheet. Single source of truth for all widgets."""
    p = PALETTE
    return f"""
    QMainWindow, QWidget {{
        background: {p['bg']};
        color: {p['text']};
        font-family: -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif;
        font-size: 13px;
    }}
    QToolTip {{
        background: {p['bg_elev']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 6px 10px;
        border-radius: 6px;
        font-size: 12px;
    }}
    QMenu {{
        background: {p['bg_elev']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 6px;
        border-radius: 8px;
    }}
    QMenu::item {{
        padding: 7px 24px 7px 14px;
        border-radius: 5px;
        margin: 1px 0;
    }}
    QMenu::item:selected {{ background: {p['accent_dim']}; color: white; }}
    QMenu::separator {{ height: 1px; background: {p['border']}; margin: 6px 8px; }}

    QSplitter {{ background: {p['bg']}; }}
    QSplitter::handle {{ background: {p['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}

    QStatusBar {{
        background: {p['bg']};
        color: {p['text_muted']};
        border-top: 1px solid {p['border']};
        font-size: 11px;
        padding: 0 8px;
    }}
    QStatusBar::item {{ border: none; }}

    QLabel {{ background: transparent; color: {p['text']}; }}
    QLabel[role="muted"] {{ color: {p['text_muted']}; }}
    QLabel[role="dim"] {{ color: {p['text_dim']}; }}

    QLineEdit {{
        background: {p['panel']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 7px;
        padding: 6px 10px;
        selection-background-color: {p['selection']};
    }}
    QLineEdit:focus {{ border-color: {p['accent_dim']}; }}

    QPushButton {{
        background: {p['panel']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 7px;
        padding: 5px 12px;
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {p['panel_hover']}; border-color: {p['border_strong']}; }}
    QPushButton:pressed {{ background: {p['bg_elev']}; }}
    QPushButton[variant="primary"] {{
        background: {p['accent_dim']};
        border-color: {p['accent_dim']};
        color: white;
    }}
    QPushButton[variant="primary"]:hover {{ background: {p['accent']}; border-color: {p['accent']}; }}
    QPushButton[variant="ghost"] {{
        background: transparent;
        border: 1px solid transparent;
        padding: 4px 10px;
        color: {p['text_muted']};
    }}
    QPushButton[variant="ghost"]:hover {{ color: {p['text']}; background: {p['panel_hover']}; border-color: {p['border']}; }}
    QPushButton[variant="danger"] {{
        background: {p['error']};
        border-color: {p['error']};
        color: white;
    }}

    QTabWidget::pane {{ background: transparent; border: none; padding: 0; }}
    QTabBar {{ background: transparent; border: none; qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {p['text_muted']};
        padding: 12px 22px;
        margin: 0 2px;
        border: none;
        font-weight: 500;
        font-size: 13px;
        min-width: 80px;
    }}
    QTabBar::tab:hover {{ color: {p['text']}; }}
    QTabBar::tab:selected {{
        color: {p['text']};
        border-bottom: 2px solid {p['accent']};
    }}

    QListWidget {{
        background: transparent;
        border: none;
        outline: 0;
        padding: 4px;
    }}
    QListWidget::item {{ background: transparent; border: none; padding: 0; margin: 0; }}
    QListWidget::item:selected {{ background: {p['selection']}; border-radius: 8px; }}
    QListWidget#sidebar {{
        background: transparent;
        padding: 6px;
    }}
    QListWidget#sidebar::item {{
        padding: 7px 10px;
        border-radius: 6px;
        color: {p['text_muted']};
        font-size: 13px;
        font-weight: 500;
    }}
    QListWidget#sidebar::item:hover {{ background: {p['panel']}; color: {p['text']}; }}
    QListWidget#sidebar::item:selected {{
        background: {p['selection_strong']};
        color: {p['text']};
    }}

    QTextBrowser {{ background: transparent; border: none; padding: 0; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p['border_strong']};
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['text_dim']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: transparent; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

    QTableWidget {{
        background: {p['panel']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        gridline-color: {p['border']};
    }}
    QHeaderView::section {{
        background: {p['panel_hover']};
        color: {p['text_muted']};
        padding: 6px 10px;
        border: none;
        border-bottom: 1px solid {p['border']};
        font-weight: 600;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    QCheckBox {{ color: {p['text']}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px;
        border: 1px solid {p['border_strong']};
        border-radius: 3px;
        background: {p['panel']};
    }}
    QCheckBox::indicator:checked {{
        background: {p['accent_dim']};
        border-color: {p['accent_dim']};
    }}

    QProgressBar {{
        background: {p['panel']};
        border: 1px solid {p['border']};
        border-radius: 4px;
        text-align: center;
        color: {p['text_muted']};
        height: 6px;
    }}
    QProgressBar::chunk {{ background: {p['accent']}; border-radius: 3px; }}

    QFrame[role="dropzone"] {{
        background: {p['bg_elev']};
        border: 1.5px dashed {p['border_strong']};
        border-radius: 12px;
    }}
    QFrame[role="dropzone"][active="true"] {{
        border-color: {p['accent']};
        background: {p['selection']};
    }}
    """