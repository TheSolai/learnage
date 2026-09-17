"""Embed chunks via Ollama."""

from __future__ import annotations

import asyncio
from typing import Iterable

from learnage.ingest.chunker import Chunk
from learnage.llm.ollama import OllamaClient


def embed_chunks(
    chunks: Iterable[Chunk],
    *,
    client: OllamaClient,
    model: str,
    batch_size: int = 16,
    on_progress=None,
    concurrency: int = 16,
) -> list[list[float]]:
    """Embed a sequence of chunks concurrently. Returns a list of vectors in input order."""
    chunks = list(chunks)
    if not chunks:
        return []
    vectors = asyncio.run(
        client.embed_batch_async(
            model,
            [c.text for c in chunks],
            concurrency=concurrency,
        )
    )
    if on_progress:
        on_progress(len(chunks), len(chunks))
    return vectors

