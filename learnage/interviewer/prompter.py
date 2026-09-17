"""Compose interview prompts."""

from __future__ import annotations

from learnage.interviewer.retriever import Passage
from learnage.store.library import Book
from learnage.store.soul import SoulRecord


_SYSTEM = (
    "You are Learnage, an interviewer of books. You speak for the books in "
    "your library the way a careful, well-read friend would. You ground every "
    "claim in a passage you can cite (e.g. [p1]). If the books don't address "
    "something, say so plainly — do not invent. When several books are present, "
    "attribute claims to specific books and flag where they agree or disagree. "
    "Keep answers concise but specific; quote when wording matters."
)


def _book_brief(book: Book, soul: SoulRecord | None) -> str:
    parts: list[str] = [f"[Book: {book.title}" + (f" — by {book.author}" if book.author else "") + "]"]
    if soul:
        parts.append(soul.short_brief(max_chars=900))
    else:
        parts.append("(no soul available — speak only from passages)")
    return "\n".join(parts)


def _passages_block(passages: list[Passage]) -> str:
    out: list[str] = []
    for i, p in enumerate(passages, start=1):
        ch = f" — ch. {p.chapter}" if p.chapter else ""
        out.append(f"[p{i}] {p.book_id}{ch}\n{p.text}")
    return "\n\n".join(out)


def _history_block(history: list[dict]) -> str:
    out: list[str] = []
    for m in history:
        role = m.get("role", "user")
        content = m.get("content", "")
        out.append(f"{role}: {content}")
    return "\n".join(out)


def compose(
    *,
    question: str,
    books: list[Book],
    souls: dict[str, SoulRecord | None],
    passages: list[Passage],
    history: list[dict],
) -> list[dict]:
    """Return a chat `messages` list ready for the LLM."""
    library_section = "\n\n".join(
        _book_brief(b, souls.get(b.id)) for b in books
    )
    passages_section = (
        _passages_block(passages)
        if passages
        else "(no passages retrieved — answer from soul only, or decline)"
    )
    history_section = _history_block(history) if history else "(no prior turns)"

    user = (
        "LIBRARY\n"
        + library_section
        + "\n\nPASSAGES\n"
        + passages_section
        + "\n\nCONVERSATION\n"
        + history_section
        + "\n\nQUESTION\n"
        + question.strip()
    )

    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]
