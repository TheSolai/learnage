"""Small helpers shared across the GUI.

Extracted from app.py in v2.0. ``html_escape``, ``_truncate_ch_label``, and
``highlight_match`` are used by ReadView, the chat bubbles, and the soul view.
"""

from __future__ import annotations

import re


def html_escape(s: str) -> str:
    """Escape text for safe use inside ``QLabel.setHtml()``."""
    return (
        s.replace("&", "&amp;")
         .replace("<", "&lt;")
         .replace(">", "&gt;")
         .replace('"', "&quot;")
         .replace("'", "&#39;")
    )


def truncate_label(s: str, n: int = 60) -> str:
    """Truncate a chapter heading for sidebar display, with an ellipsis."""
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def highlight_match(text: str, query: str, *, accent_bg: str) -> str:
    """Wrap occurrences of ``query`` in a span with the highlight colour.

    Callers pass the theme's selection_strong from PALETTE. Returns the
    HTML-escaped text with spans. Case-insensitive.
    """
    if not query:
        return text
    return re.sub(
        f"({re.escape(query)})",
        r'<span style="background:' + accent_bg + r'">\1</span>',
        text,
        flags=re.IGNORECASE,
    )