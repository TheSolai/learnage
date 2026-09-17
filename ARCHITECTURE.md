# Learnage — Architecture

> How it's built. Companion to `SPEC.md` (what it is and why).

---

## 1. Stack

| Layer | Choice | Why |
|-------|--------|-----|
| Language | **Python 3.12+** (3.14 supported) | Same as SmolQuill backend. Rich lib ecosystem. |
| LLM | **Ollama** (`localhost:11434`) | Already running locally. Default model `qwen3:8b`. |
| Embeddings | **Ollama** (`nomic-embed-text`, 768 dim) | Fast, small (137M), already installed. |
| Vector store | **ChromaDB** (persistent mode) | Disk-backed, no server, well-known, embeddable. |
| Metadata store | **SQLite** (stdlib `sqlite3`) | Library + conversations. No external DB. |
| EPUB parser | **`ebooklib`** + `BeautifulSoup4` | Standard for EPUB. |
| PDF parser | **`pypdf`** | Reliable, no native deps. Layout-aware when needed. |
| DOCX parser | **`python-docx`** | Standard. |
| HTTP | **`httpx`** | Async + sync, clean timeouts. |
| Config | **PyYAML** | Same as SmolQuill. |
| Packaging | **`uv`** | Lockfile + venv in one. |
| Tests | **`pytest`** | Standard. |

No Rust core. The performance-critical paths (embedding calls, Ollama
streaming) are I/O-bound; Python is fast enough. A future `learnage-core`
crate could replace the chunker if profiling demands it.

---

## 2. Layout

```
Learnage/
├── README.md
├── SPEC.md
├── ARCHITECTURE.md
├── pyproject.toml
├── uv.lock
├── .env.example
├── .gitignore
├── learnage/
│   ├── __init__.py
│   ├── __main__.py              # python -m learnage
│   ├── cli.py                   # argparse, REPL loop
│   ├── config.py                # YAML presets, env, paths
│   ├── llm/
│   │   ├── __init__.py
│   │   └── ollama.py            # chat(), embed(), stream() — single client
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── parsers.py           # detect() + parse(path) → ParsedBook
│   │   ├── chunker.py           # chunk(parsed) → [Chunk]
│   │   ├── embedder.py          # embed_chunks(chunks) → vectors
│   │   └── pipeline.py          # ingest(path) — orchestrates
│   ├── store/
│   │   ├── __init__.py
│   │   ├── library.py           # SQLite: books, chunks-meta, sessions
│   │   ├── vectors.py           # Chroma: per-book collections
│   │   └── soul.py              # SoulRecord: get / put / list
│   ├── soul/
│   │   ├── __init__.py
│   │   └── analyzer.py          # generate SoulRecord from chunks
│   ├── interviewer/
│   │   ├── __init__.py
│   │   ├── retriever.py         # semantic search across selected books
│   │   ├── prompter.py          # compose interview prompt
│   │   └── session.py           # REPL + streaming
│   └── util/
│       ├── __init__.py
│       ├── hash.py              # sha256 → stable book ids
│       └── paths.py             # ~/.learnage, library dir
├── presets/
│   ├── fast.yaml                # qwen3:8b
│   ├── balanced.yaml            # qwen3:14b
│   └── literary.yaml            # gemma4:31b
├── tests/
│   ├── conftest.py
│   ├── test_parsers.py
│   ├── test_chunker.py
│   ├── test_embedder.py
│   ├── test_pipeline.py
│   ├── test_soul.py
│   ├── test_retriever.py
│   └── test_prompter.py
└── data/                        # gitignored: working books, samples
    └── samples/
        └── short.txt
```

---

## 3. Data model

### 3.1 SQLite (`library.db`)

```
books (
  id              TEXT PRIMARY KEY,   -- sha256(path)[:16]
  title           TEXT NOT NULL,
  author          TEXT,
  source_path     TEXT NOT NULL,
  source_format   TEXT NOT NULL,      -- epub|pdf|docx
  source_hash     TEXT NOT NULL,      -- sha256 of file bytes
  byte_size       INTEGER,
  char_count      INTEGER,
  chunk_count     INTEGER,
  ingested_at     TEXT NOT NULL,      -- ISO 8601
  soul_json       TEXT,               -- JSON-encoded SoulRecord
  soul_generated_at TEXT,
  soul_status     TEXT                -- pending|ok|failed
);

chunks_meta (
  id              INTEGER PRIMARY KEY,
  book_id         TEXT NOT NULL,
  chunk_index     INTEGER NOT NULL,
  chapter         TEXT,               -- heading if known
  char_start      INTEGER,
  char_end        INTEGER,
  token_estimate  INTEGER,
  FOREIGN KEY (book_id) REFERENCES books(id)
);
CREATE INDEX idx_chunks_book ON chunks_meta(book_id);

sessions (
  id              TEXT PRIMARY KEY,
  started_at      TEXT NOT NULL,
  ended_at        TEXT,
  book_ids        TEXT NOT NULL,      -- comma-separated
  title           TEXT
);

messages (
  id              INTEGER PRIMARY KEY,
  session_id      TEXT NOT NULL,
  role            TEXT NOT NULL,      -- user|assistant|system
  content         TEXT NOT NULL,
  citations_json  TEXT,               -- JSON list of chunk refs
  created_at      TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id)
);
CREATE INDEX idx_messages_session ON messages(session_id, id);
```

### 3.2 Chroma (`vectors/`)

One **collection per book**, named `book_<book_id>`. This makes per-book
queries fast and gives clean isolation. Cross-book queries iterate
collections.

Each Chroma document: `{"id": "<chunk_id>", "document": "<text>",
"metadata": {"book_id", "chunk_index", "chapter"}}`.

Embedding is computed via Ollama (`nomic-embed-text`) and the resulting
vectors are stored with `embedding_function=None` so Chroma doesn't try to
re-embed (we own embedding).

### 3.3 SoulRecord (JSON)

```json
{
  "summary": "One paragraph describing the book.",
  "voice": {
    "register": "literary|casual|academic|...",
    "tone": "...",
    "rhythm": "...",
    "diction": "..."
  },
  "themes": [
    {"name": "...", "gloss": "..."},
    ...
  ],
  "characters": [
    {"name": "...", "role": "protagonist|antagonist|...", "gloss": "..."},
    ...
  ],
  "plot": {
    "shape": "...",
    "central_tension": "...",
    "arc": "..."
  },
  "key_passages": [
    {"quote": "...", "context": "...", "why": "..."},
    ...
  ],
  "craft_notes": ["...", "..."]
}
```

Persisted as `soul_json` on the book row. Surfaced via `/soul`.

---

## 4. Ingestion pipeline

```
path ─► detect() ─► parse(path) ─► ParsedBook
                                       │
                                       ▼
                                  chunk(parsed)
                                       │
                                       ▼
                                  [Chunk, ...]
                                       │
                                       ▼
                              embed(chunks) via Ollama
                                       │
                                       ▼
                              store(book_meta, chunks, vectors)
                                       │
                                       ▼
                              analyze_soul(chunks) via Ollama
                                       │
                                       ▼
                              store(soul)
```

### 4.1 Parsers

Each format returns a `ParsedBook`:

```python
ParsedBook(
  title: str,
  author: Optional[str],
  chapters: list[Chapter],     # [(heading, text)]
  full_text: str,              # concat of chapters
)
```

- **EPUB**: `ebooklib` reads the OPF; chapters from the spine. Strip HTML via
  BeautifulSoup (`get_text()`); preserve heading levels.
- **PDF**: `pypdf` extracts per page. Heuristic chapter detection: lines that
  look like headings (short, mostly caps, optional "Chapter N") on a page
  start a new chunk. Page breaks are recorded as soft chapter boundaries.
- **DOCX**: `python-docx` reads paragraphs. Headings via `style.name`.

### 4.2 Chunker

Sentence-aware sliding window.

```python
def chunk(text: str, target_tokens=800, overlap_tokens=150) -> list[Chunk]:
    sentences = split_sentences(text)        # regex + abbrev-aware
    chunks, cur, cur_len = [], [], 0
    for s in sentences:
        if cur_len + len_tokens(s) > target_tokens and cur:
            chunks.append(emit(cur))
            cur = tail(cur, overlap_tokens)  # keep last few sentences
            cur_len = sum(len_tokens(x) for x in cur)
        cur.append(s)
        cur_len += len_tokens(s)
    if cur: chunks.append(emit(cur))
    return chunks
```

Chunk text is joined sentences; `char_start`/`char_end` map back to the
original. Chapters are recorded as `chapter` metadata on each chunk.

### 4.3 Embedder

Batched calls to Ollama `/api/embeddings`. Default batch size 16. Streams
results back so a 1000-chunk book doesn't blow memory.

### 4.4 Soul analyzer

After embedding, a separate LLM call. The model is shown a **condensed
view** of the book:

- First/last paragraphs.
- All chapter headings.
- One representative chunk per chapter (or, for long books, every Nth).

The model is asked to fill a JSON schema matching `SoulRecord`. Output is
validated; if invalid, the call is retried once with a "fix the JSON"
follow-up, then marked `failed` if still bad (soul is optional; chunks
still work).

---

## 5. Interviewer

### 5.1 Retrieval

```python
def retrieve(question: str, book_ids: list[str], k=8) -> list[Passage]:
    passages = []
    for bid in book_ids:
        coll = chroma.get_collection(f"book_{bid}")
        results = coll.query(query_texts=[question], n_results=k)
        for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
            passages.append(Passage(text=doc, book_id=meta["book_id"], ...))
    return passages
```

We deliberately don't ask the LLM to embed the question — we send the
**text** to Chroma, which embeds via Ollama under the hood (we configured
it that way at ingest), so there's no drift between how chunks were
embedded and how queries are embedded.

### 5.2 Prompt

```
SYSTEM
You are Learnage, an interviewer of books. You speak for the books in your
library the way a careful reader would. You ground every claim in a passage
you can cite. If the books don't address something, you say so.

LIBRARY
[Book: TITLE — by AUTHOR]
SOUL: {soul.summary}
VOICE: {soul.voice}
THEMES: ...
CHARACTERS: ...
KEY PASSAGES: ...

[Book: ...]

PASSAGES
[p1] TITLE — ch. 3
<text>

[p2] TITLE — ch. 7
<text>

CONVERSATION
user: ...
assistant: ...
user: <question>
```

The model is told to cite `[p1]`-style references in its answers.

### 5.3 Streaming

`ollama.generate(stream=True)` yields token dicts. The REPL prints each
token as it arrives. On completion, the full message + citations are
persisted to the `messages` table.

---

## 6. Config & presets

### 6.1 `presets/fast.yaml`

```yaml
name: fast
description: Snappy on a laptop.
llm: qwen3:8b
embed: nomic-embed-text
chunk_target_tokens: 600
chunk_overlap_tokens: 120
retrieval_k: 6
soul_model: qwen3:8b
soul_max_input_chars: 60000
```

### 6.2 `presets/balanced.yaml`

```yaml
name: balanced
description: Default. Quality + speed.
llm: qwen3:14b
embed: nomic-embed-text
chunk_target_tokens: 800
chunk_overlap_tokens: 150
retrieval_k: 8
soul_model: qwen3:14b
soul_max_input_chars: 80000
```

### 6.3 `presets/literary.yaml`

```yaml
name: literary
description: Best prose awareness, slower.
llm: gemma4:31b
embed: nomic-embed-text
chunk_target_tokens: 1000
chunk_overlap_tokens: 200
retrieval_k: 10
soul_model: gemma4:31b
soul_max_input_chars: 120000
```

### 6.4 Runtime overrides

Any preset field can be overridden via `--llm`, `--embed`, `--k`, etc.

---

## 7. Storage layout

```
~/.learnage/
├── library.db                # SQLite
├── vectors/                  # Chroma persistent dir
│   └── ...
└── sessions/                 # JSONL session exports (optional)
    └── <session_id>.jsonl
```

Override with `--library <path>` or `LEARNAGE_HOME=<path>`.

---

## 8. Errors & edge cases

- **Ollama not running**: `doctor` checks; `ingest`/`read` fail fast with a
  clear message.
- **Model missing**: detect by name; fall back to default with a warning.
- **PDF with no extractable text** (scanned): log warning, skip the file.
- **EPUB with DRM**: detect via `ebooklib` failure; refuse with message.
- **Huge book**: stream parsing, chunk in batches.
- **Soul analysis failure**: mark `soul_status=failed`; ingestion still
  succeeds (chunks and retrieval work without soul).
- **Re-ingest**: if `source_hash` matches an existing book, skip. If the
  file changed, ask before replacing.

---

## 9. Testing

- **Unit**: parsers on fixture books (short epub, pdf, docx in `data/samples/`).
- **Chunker**: round-trip — chunks should cover the full input without
  huge gaps.
- **Embedder**: mocked Ollama; assert batch sizing and retries.
- **Soul**: golden-file test with small synthetic chunk input.
- **Retriever**: deterministic with mocked embeddings.
- **Prompter**: snapshot tests on a fixed library + question.
- **E2E**: smoke test that ingests a tiny book and asks a question; uses
  the real Ollama if `LEARNAGE_LIVE=1`, else mocks everything.

Live tests are opt-in and skipped by default.

---

## 10. Future Rust surface

If profiling demands it, the chunker is the natural Rust boundary — it's
CPU-bound, deterministic, and embarrassingly parallel. A `learnage-chunk`
crate with a Python binding via `pyo3` would slot in without touching the
rest of the architecture.

Not built today. YAGNI.
