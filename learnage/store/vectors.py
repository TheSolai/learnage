"""ChromaDB-backed vector store. One collection per book."""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

import chromadb
from chromadb.config import Settings  # type: ignore

from learnage.ingest.chunker import Chunk
from learnage.llm.ollama import OllamaClient


class VectorStore:
    """Persistent Chroma client.

    We manage embedding ourselves via Ollama so we pass `embedding_function=None`
    at collection time. Chroma's built-in functions don't include Ollama out
    of the box, and consistency between ingest-time and query-time embedding
    matters more than convenience.
    """

    def __init__(self, home: Path, ollama: OllamaClient, embed_model: str) -> None:
        self.home = Path(home)
        self.home.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(
            path=str(self.home),
            settings=Settings(anonymized_telemetry=False, allow_reset=False),
        )
        self.ollama = ollama
        self.embed_model = embed_model

    # ------------------------------------------------------------- collections

    @staticmethod
    def collection_name(book_id: str) -> str:
        return f"book_{book_id}"

    def get_or_create(self, book_id: str):
        return self.client.get_or_create_collection(
            name=self.collection_name(book_id),
            embedding_function=None,  # we embed via Ollama
            metadata={"hnsw:space": "cosine"},
        )

    def drop(self, book_id: str) -> None:
        try:
            self.client.delete_collection(self.collection_name(book_id))
        except Exception:  # noqa: BLE001
            pass

    # --------------------------------------------------------------- ingest

    def add_chunks(
        self,
        book_id: str,
        chunks: list[Chunk],
        *,
        batch_size: int = 64,
        concurrency: int = 16,
        on_progress=None,
    ) -> None:
        coll = self.get_or_create(book_id)
        if not chunks:
            return

        import asyncio

        for i in range(0, len(chunks), batch_size):
            batch = chunks[i : i + batch_size]
            texts = [c.text for c in batch]
            vectors = asyncio.run(
                self.ollama.embed_batch_async(
                    self.embed_model, texts, concurrency=concurrency
                )
            )
            ids = [f"{book_id}:{i + j}" for j in range(len(batch))]
            metadatas = [
                {
                    "book_id": book_id,
                    "chunk_index": i + j,
                    "chapter": c.chapter or "",
                }
                for j, c in enumerate(batch)
            ]
            coll.add(ids=ids, embeddings=vectors, documents=texts, metadatas=metadatas)
            if on_progress:
                on_progress(min(i + batch_size, len(chunks)), len(chunks))

    # --------------------------------------------------------------- query

    def query(
        self,
        book_id: str,
        question: str,
        *,
        k: int = 8,
    ) -> dict:
        coll = self.get_or_create(book_id)
        # Question embedding is one call; reuse the sync helper.
        qvec = self.ollama.embed(self.embed_model, question)
        return coll.query(
            query_embeddings=[qvec],
            n_results=k,
            include=["documents", "metadatas", "distances"],
        )

    def query_multi(
        self,
        book_ids: Iterable[str],
        question: str,
        *,
        k: int = 8,
    ) -> list[dict]:
        """Query multiple books; return per-passage records sorted by score."""
        results: list[dict] = []
        for bid in book_ids:
            r = self.query(bid, question, k=k)
            docs = r.get("documents", [[]])[0]
            metas = r.get("metadatas", [[]])[0]
            dists = r.get("distances", [[]])[0]
            for doc, meta, dist in zip(docs, metas, dists):
                results.append(
                    {
                        "book_id": meta.get("book_id", bid),
                        "chunk_index": meta.get("chunk_index"),
                        "chapter": meta.get("chapter"),
                        "text": doc,
                        "score": 1.0 - dist,  # cosine: distance -> similarity
                    }
                )
        results.sort(key=lambda x: x["score"], reverse=True)
        return results

    def get_all_chunks(self, book_id: str) -> list[dict]:
        """Return every chunk for a book, ordered by chunk_index."""
        try:
            coll = self.get_or_create(book_id)
        except Exception:  # noqa: BLE001
            return []
        data = coll.get(include=["documents", "metadatas"])
        docs = data.get("documents", [])
        metas = data.get("metadatas", [])
        # Pair and sort by chunk_index
        pairs = []
        for doc, meta in zip(docs, metas):
            pairs.append(
                {
                    "book_id": book_id,
                    "chunk_index": meta.get("chunk_index", 0),
                    "chapter": meta.get("chapter") or None,
                    "text": doc,
                }
            )
        pairs.sort(key=lambda p: p["chunk_index"])
        return pairs
