"""Stable content hashing for book identity and idempotency."""

from __future__ import annotations

import hashlib
from pathlib import Path


def file_hash(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """SHA-256 of a file's bytes."""
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(chunk_size), b""):
            h.update(block)
    return h.hexdigest()


def book_id(source_hash: str) -> str:
    """Stable book id from source hash. 16 hex chars."""
    return source_hash[:16]
