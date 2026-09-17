# Learnage — Product Specification

> A local-first book interviewer that actually *remembers* what it read.

---

## 1. What it is

Learnage is a personal library that learns. You drop in `epub`, `pdf`, or `docx`
books; it reads them, distills their **soul** (themes, voice, characters, arcs,
key passages), and turns them into a conversational companion. You can sit
across from a book — or several at once — and interview it the way you'd
interview the author.

The model **remembers**. Once a book is ingested, its soul is durable. The
library grows. Re-opening the app after a month, the books are still there and
the model still knows them.

---

## 2. Why it exists

Most LLM "chat with your docs" tools treat documents as opaque chunks to be
retrieved. They forget after the session ends, they have no sense of the work
as a whole, and they can't carry the *character* of what they read into a
conversation.

Learnage does three things differently:

1. **Soul, not snippets.** When it ingests a book, it generates a structured
   "soul" — themes, voice, major characters, plot shape, key passages — and
   keeps that alongside the chunk index. The soul is what the model carries
   into the conversation; the chunks are just evidence it can pull when
   needed.
2. **Persistent library.** Ingestion is one-way and durable. Books, their
   souls, their embeddings, and the conversation history of every interview
   are all persisted. The library is the product.
3. **Multi-book synthesis.** You can have a conversation with several books
   at once — a panel interview. Useful for comparing craft, finding common
   threads, or stress-testing an idea against multiple influences.

---

## 3. Who it's for

- Writers who want to study the books they're learning from.
- Readers who want to ask questions of the books they love — *what was the
  author thinking here?* — and get answers that survive across sessions.
- Researchers / students who want to compare ideas across many texts.

---

## 4. User experience

### CLI

```
learnage ingest <path>...     # ingest one or many books
learnage library              # list ingested books
learnage show <book>          # show a book's soul
learnage read <book>          # open a REPL interview with one book
learnage read <a>,<b>,<c>     # multi-book panel interview
learnage forget <book>        # remove a book
learnage doctor               # check ollama, db, embeddings
```

### REPL

```
learnage › /soul                 # show the book's soul
learnage › /soul show themes     # narrow part
learnage › /passages             # show retrieved passages for last question
learnage › /sources              # show sources + book for last answer
learnage › /clear                # clear conversation memory
learnage › /quit
```

### Soul as a first-class concept

When Learnage reads a book, it doesn't just store text. It computes and
persists:

- **Summary** — a paragraph describing the book in plain English.
- **Voice** — narrative voice, register, rhythm, diction.
- **Themes** — 5–10 themes, each with a one-line gloss.
- **Characters** — major characters, with a one-line description each.
- **Plot shape** — beginning / middle / end, plus the central tension.
- **Key passages** — 3–10 quotations the soul analyzer flagged as load-bearing.
- **Craft notes** — observations about how the author achieves their effects
  (only if the book is craft-adjacent, e.g. a writing manual).

These are stored as JSON in the book record and surfaced via `/soul`.

---

## 5. Functional requirements

### 5.1 Ingestion

- **Input formats**: `epub`, `pdf`, `docx`.
- **Pipeline**: parse → clean → chunk → embed → store → analyze soul.
- **Chunking**: sliding window, ~500–1000 tokens, ~150-token overlap,
  sentence-boundary aware.
- **Embeddings**: Ollama, default model `nomic-embed-text` (768 dim).
- **Vector store**: ChromaDB, persistent, on disk.
- **Soul analysis**: separate LLM pass after chunking, using the chunk text
  + chapter headings as input. Persisted.
- **Idempotent**: re-ingesting the same file updates rather than duplicating.
- **Batch-friendly**: `learnage ingest path/ books/` walks directories.

### 5.2 Library

- **Per-book record**: id, title, author, source path, format, hash,
  ingestion timestamp, soul JSON, chunk count, token estimate.
- **Per-chunk record**: book id, chunk index, text, char offsets, embedding
  pointer, chapter heading (if known).
- **Per-conversation record**: session id, book ids, message history,
  timestamps.
- **Storage layout**: SQLite for the library + ChromaDB for vectors.
- **Location**: `~/.learnage/` by default; overridable.

### 5.3 Interviewer

- **Retrieval**: top-k semantic search across selected books. k default 8.
- **Prompt composition**:
  1. System preamble (Learnage is a book interviewer).
  2. Soul of each selected book (concise, formatted).
  3. Top retrieved chunks (formatted with citation metadata).
  4. Recent conversation history.
  5. The user's question.
- **Model**: Ollama, default `qwen3:8b` (fast) or `qwen3:14b` (quality).
- **Streaming**: yes, token-by-token to the REPL.
- **Citation honesty**: every answer is grounded in retrieved chunks; the
  model is told to say "the book doesn't address that" when it doesn't.
- **Cross-book synthesis**: when multiple books are active, the prompt
  instructs the model to attribute claims to specific books and to flag
  disagreement.

### 5.4 Memory

- **Book memory**: persistent. Once ingested, never lost unless `forget`.
- **Conversation memory**: per-session. `/clear` resets it.
- **Index of sessions**: queryable via the library; exportable to JSONL.
- **Soul is the bridge**: when the conversation is closed and reopened, the
  soul is what the model carries forward. The chunks are still there for
  retrieval, but the soul gives the model its *character*.

### 5.5 Configurability

- **Presets**: `fast`, `balanced`, `literary`. Defined in `presets/*.yaml`.
- **Override at runtime**: `--model`, `--embed-model`, `--k`, `--chunk-size`.
- **Library location**: `--library <path>`.

---

## 6. Non-functional requirements

- **Local-first**: no network calls except Ollama (local). Library stays on
  disk under the user's control.
- **No cloud fallback**: deliberately offline.
- **Single-user**: not designed for multi-user libraries.
- **No telemetry**.
- **Memory safety**: ingestion can stream through large books without OOM.
- **Reproducible**: re-running the same commands on the same library yields
  the same state.

---

## 7. Anti-goals

- Not a writing tool. (That's SmolQuill's job.)
- Not a general document Q&A. Books are the unit; documents-as-snippets is
  not the model.
- Not a web service. Local-only, CLI-first.
- Not a model trainer. Learnage reads; it does not retrain anything.
- Not a research database. No citation graph, no entity linking, no claim
  verification. Just honest conversation.

---

## 8. Success criteria

A user can:

1. Ingest a 300-page PDF and have a meaningful conversation with it within
   ten minutes on a MacBook with `qwen3:14b`.
2. Close the app, reopen it tomorrow, ask a follow-up, and the model
   remembers the book's themes, voice, and prior conversation turns.
3. Add a second book to the same session and ask a comparison question.
4. Read back what the model thinks each book *is* via `/soul` and recognize
   the books.

---

## 9. Stretch

- TUI (Textual) — same library, different front-end.
- Web mirror — static export of the soul for sharing.
- Voice — Piper TTS reading the soul aloud.
- Reading-mode — model walks the user through a book chapter-by-chapter.
- Per-passage annotations — let the user highlight and re-anchor.
