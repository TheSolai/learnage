"""Clickable citation rendering — turn [N] markers into clickable HTML links."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass


# Custom URL scheme for citations. Qt's QLabel linkActivated emits these
# when clicked; we route them back to book_id + chunk_index.
CITATION_SCHEME = "learnage-cite"


@dataclass
class Citation:
    """A single retrieved passage that the LLM may cite."""
    book_id: str
    chunk_index: int
    title: str = ""
    chapter: str = ""
    score: float = 0.0


_BRACKET_RE = re.compile(r"\[(\d+)\]")


def render_text_with_citations(text: str, citations: list[Citation]) -> str:
    """Convert [N] markers in `text` to clickable HTML links.

    Citations outside the valid range are left as plain text. The result
    is safe HTML for QLabel.setText() with RichText format.
    """
    safe = html.escape(text)
    n_max = len(citations)

    def replace(m: re.Match) -> str:
        try:
            n = int(m.group(1))
        except ValueError:
            return m.group(0)
        if n < 1 or n > n_max:
            return m.group(0)
        c = citations[n - 1]
        url = f"{CITATION_SCHEME}:{c.book_id}:{c.chunk_index}"
        label = f"[{n}]"
        return (
            f'<a href="{html.escape(url)}" '
            f'style="color: #b48ad8; text-decoration: none; '
            f'font-weight: 600; border-bottom: 1px dotted #b48ad8;">'
            f'{label}</a>'
        )

    return _BRACKET_RE.sub(replace, safe)


def parse_citation_url(url: str) -> tuple[str, int] | None:
    """Parse a `learnage-cite:book_id:chunk_index` URL into its parts."""
    prefix = f"{CITATION_SCHEME}:"
    if not url.startswith(prefix):
        return None
    rest = url[len(prefix):]
    parts = rest.split(":", 1)
    if len(parts) != 2:
        return None
    try:
        return parts[0], int(parts[1])
    except ValueError:
        return None


def build_citation_footer(citations: list[Citation]) -> str:
    """Build a small HTML footer listing every citation.

    Each entry is clickable; clicking it opens the source. The footer
    is shown beneath assistant bubbles.
    """
    if not citations:
        return ""
    rows: list[str] = []
    for i, c in enumerate(citations, start=1):
        title = c.title or c.book_id[:8]
        chapter = f" · {c.chapter}" if c.chapter else ""
        url = f"{CITATION_SCHEME}:{c.book_id}:{c.chunk_index}"
        rows.append(
            f'<div style="margin: 2px 0; color: #777; font-size: 11px;">'
            f'<a href="{html.escape(url)}" '
            f'style="color: #b48ad8; text-decoration: none; font-weight: 600;">'
            f'[{i}]</a> '
            f'<span style="color: #aaa;">{html.escape(title)}{html.escape(chapter)}</span>'
            f'</div>'
        )
    return (
        '<div style="margin-top: 8px; padding-top: 6px; '
        'border-top: 1px solid rgba(255,255,255,0.05);">'
        + "".join(rows)
        + "</div>"
    )
