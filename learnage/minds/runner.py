"""Mind-aware RAG runner — retrieval, prompt build, streaming chat."""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Iterable, Iterator

from learnage.config import Preset
from learnage.interviewer.retriever import Passage
from learnage.llm.ollama import OllamaClient
from learnage.minds.base import Mind, SCOPE_MANUAL
from learnage.minds.citations import Citation
from learnage.store.library import Book, Library
from learnage.store.soul import SoulRecord, merge_soul_brief
from learnage.store.vectors import VectorStore


@dataclass
class MindAnswer:
    """One retrieved-and-answered round in a Mind chat."""
    passages: list[Passage]
    system_prompt: str
    sources: list[dict]   # [{book_id, title, author, chunk_index, chapter, score}]


def retrieve_for_mind(
    question: str,
    *,
    mind: Mind,
    library: Library,
    vectors: VectorStore,
    preset: Preset,
) -> list[Passage]:
    """Search every in-scope book for `question`, return top passages."""

    # Resolve scope to a list of book IDs
    if mind.scope_kind == SCOPE_MANUAL:
        book_ids = list(mind.scope_values)
    else:
        books = library.list_books()
        matched = mind.filter_books(books)
        book_ids = [b.id for b in matched]

    if not book_ids:
        return []

    rows = vectors.query_multi(
        book_ids=book_ids,
        question=question,
        k=mind.top_k,
    )
    # Slice to top_n for the prompt (but return full list for citations)
    passages = [
        Passage(
            book_id=r["book_id"],
            chunk_index=r["chunk_index"],
            chapter=r["chapter"],
            text=r["text"],
            score=r["score"],
        )
        for r in rows[:mind.top_n]
    ]
    return passages


def _format_passages(
    passages: list[Passage],
    *,
    library: Library,
) -> str:
    """Render passages as a citation-numbered context block."""
    if not passages:
        return "(no passages retrieved)"
    cache: dict[str, Book] = {}
    out: list[str] = []
    for i, p in enumerate(passages, start=1):
        b = cache.get(p.book_id)
        if b is None:
            b = library.get_book(p.book_id)
            cache[p.book_id] = b
        title = b.title if b else p.book_id[:8]
        author = b.author if b else ""
        chapter = p.chapter or ""
        head = f"[{i}] {title}"
        if author:
            head += f" · {author}"
        if chapter:
            head += f" · {chapter}"
        out.append(f"{head}\n{p.text.strip()}")
    return "\n\n---\n\n".join(out)


def _resolve_books_for_soul(mind: Mind, library: Library) -> list[Book]:
    if mind.scope_kind == SCOPE_MANUAL:
        out: list[Book] = []
        for bid in mind.scope_values:
            b = library.get_book(bid)
            if b:
                out.append(b)
        return out
    return mind.filter_books(library.list_books())


def _build_mind_system_prompt(
    mind: Mind,
    *,
    library: Library,
    home: Path | None = None,
) -> str:
    """Compose the full system prompt: persona + notes + collective soul + scope."""
    parts: list[str] = []

    if mind.system_prompt:
        parts.append(mind.system_prompt.strip())

    # Persistent notes — the Mind's long-term memory
    if home is not None:
        from learnage.minds.notes import MindNotes
        notes = MindNotes(home)
        notes_text = notes.for_injection(mind.id)
        if notes_text:
            parts.append(
                "\n\nPERSISTENT NOTES (the reader's standing instructions — "
                "honour these in every conversation):\n" + notes_text
            )

    parts.append(
        "\n\nGrounding rules:\n"
        "- Answer ONLY using the passages you were given. "
        "If they don't contain the answer, say so plainly.\n"
        "- Cite by [number] after the relevant sentence.\n"
        "- If passages disagree, surface the disagreement.\n"
        "- Do not invent book titles, authors, chapters, or quotes."
    )

    if mind.include_soul:
        # Build collective soul from in-scope books that have one
        books = _resolve_books_for_soul(mind, library)
        souls: list[SoulRecord] = []
        for b in books:
            if b.soul_status == "ok" and b.soul_json:
                try:
                    souls.append(SoulRecord.from_json(b.soul_json))
                except Exception:  # noqa: BLE001
                    pass
        if souls:
            brief = merge_soul_brief(souls, max_chars=mind.soul_max_chars)
            if brief:
                parts.append("\n\nCOLLECTIVE SOUL OF THIS MIND:\n" + brief)

    parts.append(f"\n\nSCOPE: {mind.scope_description()}")
    return "\n".join(parts).strip()


def collect_sources(
    passages: list[Passage],
    *,
    library: Library,
) -> list[dict]:
    """Build citation source records from passages."""
    cache: dict[str, Book] = {}
    out: list[dict] = []
    for p in passages:
        b = cache.get(p.book_id)
        if b is None:
            b = library.get_book(p.book_id)
            cache[p.book_id] = b
        out.append(
            {
                "book_id": p.book_id,
                "title": b.title if b else "",
                "author": b.author if b else "",
                "chunk_index": p.chunk_index,
                "chapter": p.chapter,
                "score": p.score,
            }
        )
    return out


def prepare_mind_answer(
    question: str,
    *,
    mind: Mind,
    library: Library,
    vectors: VectorStore,
    preset: Preset,
    home: Path | None = None,
) -> MindAnswer:
    """Retrieve passages and build the system prompt for a single round."""
    passages = retrieve_for_mind(
        question,
        mind=mind,
        library=library,
        vectors=vectors,
        preset=preset,
    )
    sys_prompt = _build_mind_system_prompt(mind, library=library, home=home)
    # Append passages as the final user-side context (the caller adds the question)
    ctx = _format_passages(passages, library=library)
    full = sys_prompt + "\n\n---\n\nPASSAGES:\n\n" + ctx
    return MindAnswer(
        passages=passages,
        system_prompt=full,
        sources=collect_sources(passages, library=library),
    )


def stream_mind_chat(
    question: str,
    *,
    mind: Mind,
    library: Library,
    vectors: VectorStore,
    ollama: OllamaClient,
    preset: Preset,
    history: list[dict] | None = None,
    home: Path | None = None,
) -> Iterator[str]:
    """Stream a Mind's answer to a question.

    `history` is a list of {role, content} dicts (excluding the current
    question) used to ground the conversation.
    """
    answer = prepare_mind_answer(
        question,
        mind=mind,
        library=library,
        vectors=vectors,
        preset=preset,
        home=home,
    )
    messages: list[dict] = [{"role": "system", "content": answer.system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": question})
    model = mind.preset_name or preset.llm
    return ollama.stream_chat(model=model, messages=messages)


def citations_for_mind(
    question: str,
    *,
    mind: Mind,
    library: Library,
    vectors: VectorStore,
    preset: Preset,
    home: Path | None = None,
) -> list[Citation]:
    """Retrieve the passages a Mind would cite, as Citation objects.

    This runs the same retrieval the chat runner uses, but returns a
    flat list suitable for clickable citation rendering.
    """
    answer = prepare_mind_answer(
        question,
        mind=mind,
        library=library,
        vectors=vectors,
        preset=preset,
        home=home,
    )
    out: list[Citation] = []
    for p in answer.passages:
        b = library.get_book(p.book_id)
        out.append(
            Citation(
                book_id=p.book_id,
                chunk_index=p.chunk_index,
                title=b.title if b else "",
                chapter=p.chapter or "",
                score=p.score,
            )
        )
    return out
