"""Sentence-aware sliding-window chunker."""

from __future__ import annotations

import re
from dataclasses import dataclass

from learnage.ingest.parsers import sanitize_text


@dataclass
class Chunk:
    text: str
    chapter: str | None
    char_start: int
    char_end: int

    @property
    def token_estimate(self) -> int:
        # Cheap heuristic: ~0.75 tokens per whitespace-delimited word,
        # plus a small per-token overhead.
        return max(1, int(len(self.text.split()) / 0.75))


# Sentence boundary: period/!/?/… followed by whitespace, but not after
# common abbreviations.
_ABBREVIATIONS = {
    "mr", "mrs", "ms", "dr", "st", "sr", "jr", "vs", "etc", "e.g", "i.e",
    "no", "a.m", "p.m", "u.s", "u.k", "fig", "eq",
}
_SENT_END = re.compile(r"(?<=[.!?…])\s+(?=[A-Z\"'(\[])")
_WORD_RE = re.compile(r"\s+")


def split_sentences(text: str) -> list[str]:
    """Naive sentence splitter.

    Not perfect, but cheap and good enough as a chunk boundary source.
    """
    # Protect common abbreviations by temporarily replacing their dot,
    # preserving the original case of the abbreviation.
    def _protect(match: re.Match) -> str:
        return f"{match.group(0)[:-1]}\u0001"

    protected = text
    for abbr in _ABBREVIATIONS:
        # Build a case-insensitive pattern that matches `<abbr>.`.
        pattern = re.compile(rf"\b{re.escape(abbr)}\.", re.IGNORECASE)
        protected = pattern.sub(_protect, protected)

    parts = _SENT_END.split(protected)
    sentences = [p.replace("\u0001", ".").strip() for p in parts if p.strip()]
    return sentences


def chunk_text(
    text: str,
    *,
    target_tokens: int = 800,
    overlap_tokens: int = 150,
    chapter: str | None = None,
) -> list[Chunk]:
    """Split text into overlapping chunks of roughly target_tokens size.

    Sentence-aware: chunks end on sentence boundaries; overlap is implemented
    by keeping the last `overlap_tokens`-worth of sentences.
    """
    if not text.strip():
        return []
    sentences = split_sentences(text)
    return _pack_sentences(
        sentences,
        target_tokens=target_tokens,
        overlap_tokens=overlap_tokens,
        chapter=chapter,
        base_offset=0,
    )


def _pack_sentences(
    sentences: list[str],
    *,
    target_tokens: int,
    overlap_tokens: int,
    chapter: str | None,
    base_offset: int,
) -> list[Chunk]:
    chunks: list[Chunk] = []
    cur: list[str] = []
    cur_tokens = 0
    cursor = 0  # char offset into the joined text

    # Hard cap on a single chunk so we don't blow past embed model context.
    # nomic-embed-text has a 2048-token context. Single-character tokens
    # (punctuation, digits) can balloon token count, so be very conservative.
    MAX_CHUNK_CHARS = 1200  # ~600 tokens even with heavy single-char tokens

    def emit() -> None:
        nonlocal cur, cur_tokens, cursor
        if not cur:
            return
        joined = sanitize_text(" ".join(cur))
        if not joined:
            return
        # Hard split if still too long
        if len(joined) > MAX_CHUNK_CHARS:
            for i in range(0, len(joined), MAX_CHUNK_CHARS):
                seg = joined[i : i + MAX_CHUNK_CHARS]
                if seg.strip():
                    start = base_offset + cursor + i
                    chunks.append(
                        Chunk(
                            text=seg,
                            chapter=chapter,
                            char_start=start,
                            char_end=start + len(seg),
                        )
                    )
            cursor += len(joined)
            cur = []
            cur_tokens = 0
            return
        start = base_offset + cursor
        end = start + len(joined)
        chunks.append(
            Chunk(text=joined, chapter=chapter, char_start=start, char_end=end)
        )
        # Keep overlap: tail sentences that fit in overlap_tokens.
        kept: list[str] = []
        kept_tokens = 0
        for s in reversed(cur):
            t = max(1, int(len(s.split()) / 0.75))
            if kept_tokens + t > overlap_tokens:
                break
            kept.insert(0, s)
            kept_tokens += t
        dropped_text = " ".join(cur[: len(cur) - len(kept)]) if len(cur) > len(kept) else ""
        cursor += len(dropped_text) + (1 if dropped_text else 0)
        cur = kept
        cur_tokens = kept_tokens

    # Pre-split any oversized sentences so we never get stuck.
    bounded: list[str] = []
    for s in sentences:
        s = s.strip()
        if not s:
            continue
        if len(s) > MAX_CHUNK_CHARS:
            # Hard-split on word boundaries.
            for i in range(0, len(s), MAX_CHUNK_CHARS):
                bounded.append(s[i : i + MAX_CHUNK_CHARS])
        else:
            bounded.append(s)
    sentences = bounded

    # If the text has lots of single-character "tokens" (e.g. scanned OCR garbage
    # that's just punctuation), be even more conservative — each char ~= 1 token.
    def est_tokens(s: str) -> int:
        # If 50%+ are non-alphanumeric, count characters; else use word heuristic.
        nonalpha = sum(1 for ch in s if not ch.isalnum() and not ch.isspace())
        if len(s) > 0 and nonalpha / len(s) > 0.5:
            return len(s)
        return max(1, int(len(s.split()) / 0.75))

    for s in sentences:
        s_tokens = est_tokens(s)
        if cur and cur_tokens + s_tokens > target_tokens:
            emit()
        cur.append(s)
        cur_tokens += s_tokens

    if cur:
        emit()
    return chunks


def chunk_book(
    chapters: list[tuple[str | None, str]],
    *,
    target_tokens: int = 800,
    overlap_tokens: int = 150,
) -> list[Chunk]:
    """Chunk an entire book given its chapter breakdown.

    Char offsets are local to each chapter. Chunk text starts at 0 per chapter.
    """
    chunks: list[Chunk] = []
    for heading, text in chapters:
        if not text.strip():
            continue
        sub = chunk_text(
            text,
            target_tokens=target_tokens,
            overlap_tokens=overlap_tokens,
            chapter=heading,
        )
        chunks.extend(sub)
    return chunks
