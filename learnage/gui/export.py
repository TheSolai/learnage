"""Export a session's conversation to Markdown."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path


def export_session_markdown(
    session: dict, messages: list[dict], library, vectors, book_meta: dict
) -> str:
    """Render a session + messages as a Markdown document."""
    lines: list[str] = []
    title = session.get("title") or f"Conversation · {session.get('started_at', '')}"
    lines.append(f"# {title}")
    lines.append("")
    lines.append(f"_Started: {session.get('started_at', '')}_  ")
    lines.append(f"_Ended: {session.get('ended_at', 'in progress')}_  ")
    lines.append("")
    book_ids = [bid for bid in session.get("book_ids", "").split(",") if bid]
    if book_ids:
        names = []
        for bid in book_ids:
            b = library.get_book(bid)
            names.append(b.title if b else bid)
        lines.append(f"**Books:** {', '.join(names)}")
        lines.append("")

    lines.append("---")
    lines.append("")
    for m in messages:
        role = m.get("role", "user").title()
        ts = m.get("created_at", "")
        lines.append(f"## {role}  _{ts}_")
        lines.append("")
        content = (m.get("content") or "").strip()
        lines.append(content)
        lines.append("")
        citations = m.get("citations")
        if citations:
            lines.append("**Sources:**")
            for c in citations:
                bid = c.get("book_id")
                title = book_meta.get(bid, {}).get("title", bid) if isinstance(book_meta, dict) else bid
                lines.append(
                    f"- {title} · chunk {c.get('chunk_index', '?')} · "
                    f"score={c.get('score', '?')}"
                )
            lines.append("")
    return "\n".join(lines)


def write_export(markdown: str, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown, encoding="utf-8")