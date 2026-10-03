"""Semantic retrieval across one or many books."""

from __future__ import annotations

from dataclasses import dataclass

from learnage.config import Preset
from learnage.store.vectors import VectorStore


@dataclass
class Passage:
    book_id: str
    chunk_index: int
    chapter: str | None
    text: str
    score: float


def retrieve(
    question: str,
    *,
    book_ids: list[str],
    vectors: VectorStore,
    preset: Preset,
) -> list[Passage]:
    rows = vectors.query_multi(
        book_ids=book_ids,
        question=question,
        k=preset.retrieval_k,
    )
    return [
        Passage(
            book_id=r["book_id"],
            chunk_index=r["chunk_index"],
            chapter=r["chapter"],
            text=r["text"],
            score=r["score"],
        )
        for r in rows
    ]
