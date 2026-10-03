#!/usr/bin/env -S uv run python
"""Smoke test: open session, ask a question, stream answer, persist message."""

from pathlib import Path

from learnage.config import load_preset
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Library
from learnage.store.vectors import VectorStore
from learnage.util.paths import default_home, ensure_home, library_db_path, vectors_dir


def main() -> int:
    home = ensure_home(default_home())
    preset = load_preset("fast")
    ollama = OllamaClient()
    library = Library(library_db_path(home))
    vectors = VectorStore(vectors_dir(home), ollama=ollama, embed_model=preset.embed)

    books = library.list_books()
    if not books:
        print("no books ingested; run: uv run learnage ingest <file>")
        return 1
    book = books[0]
    print(f"interviewing: {book.title}")

    # Load soul
    from learnage.store.soul import SoulRecord
    soul = SoulRecord.from_json(book.soul_json) if book.soul_json else None

    # Retrieve
    from learnage.interviewer.retriever import retrieve
    from learnage.interviewer.prompter import compose

    question = "What does the grandmother mean when she says 'Everything that has a name can be lost'?"
    passages = retrieve(question, book_ids=[book.id], vectors=vectors, preset=preset)
    print(f"\nretrieved {len(passages)} passages; top score {passages[0].score:.3f}\n")

    messages = compose(
        question=question,
        books=[book],
        souls={book.id: soul},
        passages=passages,
        history=[],
    )

    print(f"--- streaming from {preset.llm} ---\n")
    full = []
    for chunk in ollama.chat(model=preset.llm, messages=messages, stream=True):
        c = (chunk.get("message") or {}).get("content", "")
        if c:
            print(c, end="", flush=True)
            full.append(c)
        if chunk.get("done"):
            break
    print("\n\n--- end ---\n")

    # Persist
    import uuid
    sid = uuid.uuid4().hex[:12]
    library.create_session(sid, [book.id])
    library.append_message(sid, "user", question)
    library.append_message(
        sid,
        "assistant",
        "".join(full),
        citations=[{"book_id": p.book_id, "chunk_index": p.chunk_index, "score": p.score} for p in passages],
    )
    library.end_session(sid)
    print(f"session {sid} persisted")

    library.close()
    ollama.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
