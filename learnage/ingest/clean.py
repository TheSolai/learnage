"""Clean a book — re-parse the source with aggressive sanitization,
re-chunk, re-embed, and replace the existing chunks in the library.

Useful for books that came from scanned/OCR PDFs and have:
- Page numbers at the top/bottom of every page
- Header/footer repeats
- Hyphenated line-breaks across lines
- Random binary control chars
- Multiple consecutive blank lines
- Non-printable garbage from font encoding tables
"""

from __future__ import annotations

import asyncio
import re
import time
from pathlib import Path
from typing import Callable

from learnage.config import Preset
from learnage.ingest.chunker import chunk_book
from learnage.ingest.parsers import _parse_epub, _parse_pdf, _parse_docx, _parse_txt, sanitize_text
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Library
from learnage.store.vectors import VectorStore


# ---------- extra aggressive normalization patterns ----------


_PAGE_NUM_RE = re.compile(
    r"(?m)^\s*(?:[-—–]\s*)?(?:\d{1,4}|[ivxlcdm]+)(?:\s*[-—–])?\s*$"
)
_PAGE_NUM_INLINE_RE = re.compile(
    r"\b(?:Page|PAGE)\s+\d{1,4}\b"
)
_HEADER_FOOTER_HINT_RE = re.compile(
    r"(?i)\b(?:copyright|all rights reserved|printed in|published by|"
    r"isbn|first edition|second edition|third edition|no part of this)\b"
)
_HYPHEN_LINEBREAK_RE = re.compile(r"-\n\s*")
_MULTI_BLANK_RE = re.compile(r"\n{3,}")
_LINE_BREAK_IN_PARA_RE = re.compile(r"(?<![.!?\n])\n(?=[a-z\"])")
_PAGE_BREAK_RE = re.compile(r"\n\s*\f\s*\n|\n{3,}")


def deep_clean(text: str) -> str:
    """Aggressive cleaning for text extracted from scanned/OCR PDFs.

    Steps:
    1. Sanitize control chars (via sanitize_text)
    2. De-hyphenate line-broken words (e.g. "para-\\nmancers" → "paramancers")
    3. Drop page-number lines that are alone on a line
    4. Drop inline page-number mentions ("Page 42")
    5. Drop copyright/license footer lines
    6. Join soft-wrapped lines (lines that don't end with punctuation)
    7. Collapse multiple blank lines
    8. Strip leading/trailing whitespace per line
    """
    if not text:
        return ""
    s = sanitize_text(text)
    # 2. de-hyphenate across lines
    s = _HYPHEN_LINEBREAK_RE.sub("", s)
    # 3. drop page-number-only lines
    lines = s.split("\n")
    kept: list[str] = []
    for ln in lines:
        s_ln = ln.strip()
        if _PAGE_NUM_RE.match(s_ln):
            continue
        if _HEADER_FOOTER_HINT_RE.search(s_ln):
            # If the line is short and clearly metadata, drop it.
            if len(s_ln) < 90:
                continue
        kept.append(ln.rstrip())
    s = "\n".join(kept)
    # 4. drop inline "Page N" mentions
    s = _PAGE_NUM_INLINE_RE.sub("", s)
    # 5. form-feed page breaks → blank line
    s = s.replace("\f", "\n\n")
    # 6. join soft-wrapped lines: a line ending without .!? that is followed by another non-empty line
    s = _LINE_BREAK_IN_PARA_RE.sub(" ", s)
    # 7. collapse multi blanks
    s = _MULTI_BLANK_RE.sub("\n\n", s)
    return s.strip()


def _parse(path: Path):
    """Dispatch to the right parser."""
    suf = path.suffix.lower().lstrip(".")
    if suf == "epub":
        return _parse_epub(path)
    if suf == "pdf":
        return _parse_pdf(path)
    if suf in ("docx", "doc"):
        return _parse_docx(path)
    if suf == "txt":
        return _parse_txt(path)
    raise ValueError(f"unsupported format: {path.suffix}")


# ---------- public entry point ----------


async def clean_book(
    book_id: str,
    *,
    library: Library,
    vectors: VectorStore,
    ollama: OllamaClient,
    preset: Preset,
    on_progress: Callable[[str, int, int], None] | None = None,
) -> dict:
    """Re-parse, deep-clean, re-chunk, re-embed, and replace.

    Returns {"chunks": N, "chapters": N, "old_chars": int, "new_chars": int}.
    """
    book = library.get_book(book_id)
    if not book:
        return {"error": "book not found"}
    src = Path(book.source_path).expanduser().resolve()
    if not src.exists():
        return {"error": f"source missing: {src}"}

    # Snapshot old chunk count + total chars
    old_meta = library.get_chunk_meta_for_book(book_id)
    old_chars = sum(m["char_end"] - m["char_start"] for m in old_meta) if old_meta else 0

    # Re-parse
    parsed = _parse(src)
    chapters = [
        (ch.heading, deep_clean(ch.text))
        for ch in parsed.chapters
        if ch.text and ch.text.strip()
    ]
    new_chars = sum(len(t) for _, t in chapters)

    if not chapters:
        return {"error": "no text extracted", "old_chars": old_chars, "new_chars": 0}

    # Re-chunk
    chunks = chunk_book(
        chapters,
        target_tokens=preset.chunk_target_tokens,
        overlap_tokens=preset.chunk_overlap_tokens,
    )

    # Drop the old collection, add new
    vectors.drop(book_id)
    if chunks:
        # embed & add in batches
        BATCH = 64
        for i in range(0, len(chunks), BATCH):
            batch = chunks[i : i + BATCH]
            texts = [c.text for c in batch]
            vecs = await ollama.embed_batch_async(
                preset.embed, texts, concurrency=16
            )
            coll = vectors.get_or_create(book_id)
            ids = [f"{book_id}:{i + j}" for j in range(len(batch))]
            metas = [
                {"book_id": book_id, "chunk_index": i + j, "chapter": c.chapter or ""}
                for j, c in enumerate(batch)
            ]
            coll.add(ids=ids, embeddings=vecs, documents=texts, metadatas=metas)
            if on_progress:
                on_progress(book_id, min(i + BATCH, len(chunks)), len(chunks))

    # Replace chunks_meta rows
    library.replace_chunks(
        book_id,
        [
            (i, c.chapter, c.char_start, c.char_end, c.token_estimate)
            for i, c in enumerate(chunks)
        ],
    )
    # Update book chunk_count
    from learnage.store.library import Book
    new_book = Book(
        id=book.id, title=book.title, author=book.author,
        source_path=book.source_path, source_format=book.source_format,
        source_hash=book.source_hash, byte_size=book.byte_size,
        char_count=new_chars, chunk_count=len(chunks),
        ingested_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
        soul_json=book.soul_json, soul_generated_at=book.soul_generated_at,
        soul_status=book.soul_status,
    )
    library.upsert_book(new_book)

    return {
        "chapters": len(chapters),
        "chunks": len(chunks),
        "old_chars": old_chars,
        "new_chars": new_chars,
        "title": book.title,
    }


def clean_book_sync(*args, **kwargs) -> dict:
    return asyncio.run(clean_book(*args, **kwargs))
