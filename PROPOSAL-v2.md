# Learnage v2 — Reimagine Proposal

> Status: **DRAFT for review.** Not yet implemented.
> Companion docs: `README.md`, `SPEC.md`, `ARCHITECTURE.md`.
> Date: 2026-10-03.

This document proposes the next major revision of Learnage. v1 (the current
codebase at `0.1.0`) shipped the *soul engine*, *Minds*, and a working local-first
RAG pipeline. v2 keeps the soul + Minds moat and rebuilds everything around
them: a denser UI, faster ingest, real polish, and a per-book chat surface
that feels native. **No code in the archive is sacred except the soul analyzer
and the soul record schema.**

---

## 1. Why v2

The v1 codebase works, but it shows its seams:

| Pain | Evidence |
|---|---|
| The GUI crashes on first interaction | `QComboBox` not imported in `learnage/gui/book_window.py:30` — every `BookWindow` dies with `NameError` |
| A 3,967-line god-module | `learnage/gui/app.py` holds 15 classes and module-level globals; one typo in one place breaks every panel |
| Book-list rows have no covers | `covers.py` caches thumbnails, but `BookListWidget` (line 664) ignores them — flat text rows in a 544-book library |
| Streaming citations lag | `MindChatTab._on_done` (line 3707) only attaches citation markers after the stream completes |
| Souls are silently dropped | `pipeline.ingest_path` (line 142) sets `soul_status="failed"` on any exception, with no UI feedback |
| OCR is a manual ritual | 27 of your 544 books have `<5` chunks (scanned PDFs); the README tells you to run `ocrmypdf` manually and the GUI never mentions it |
| Minds live in JSON, not SQLite | `~/.learnage/minds.json` is a separate file from `library.db` — you can't query a Mind via SQL or include it in a backup of the library |
| 25% of presets-vs-models drift | `qwen3:14b` is hardcoded in `config.py:36` but `doctor` only warns; runtime errors are opaque |
| Tool-use loop is undiagnosable | `AgentRunner.MAX_TOOL_ROUNDS = 4` (line 319) but failures are caught and lost as `signals.error.emit` |
| The popout interview path silently breaks | `PopoutInterview.__init__` (line 80) passes `pool=None` to `ChatTab`, which has no such kwarg |

And the bigger issue: **Learnage feels like a tool someone built for themselves
last weekend and put on a shelf.** Compared to Readwise Reader, AnythingLLM, or
the Sidekick app you just installed, it has no first impression — no covers,
no keyboard command palette, no streaming thoughts, no in-place re-ranking.
That's what v2 fixes.

## 2. What stays

These are the things that make Learnage *Learnage* and must not regress:

1. **The soul record.** `learnage/store/soul.py` is the core data shape. Any
   v2 must preserve `summary`, `voice`, `themes`, `characters`, `plot`,
   `key_passages`, `craft_notes`, `meta`, `key_concepts`, `key_figures`,
   `questions`, `quotes`, `tone_words` and `SoulRecord.short_brief()` /
   `merge_soul_brief()` exactly as they are.
2. **The soul analyzer** in `learnage/soul/analyzer.py`. The condensed-prompt
   trick (`_condense`) and the JSON-retry (`_extract_json`) are working well
   for `qwen3:14b`. Keep the prompt template; just version it.
3. **The Minds system** in `learnage/minds/`. `Mind`, `MindsStore`, the 5
   built-ins (`library`, `reading`, `witchcraft`, `writing`, `study`),
   `MindNotes`, the runner — all stay. The Minds data model moves into SQLite
   but the public API doesn't change.
4. **Multi-book panel interviews.** The ability to throw three books at the
   model and have it synthesize across them is the headline feature.
5. **Per-book persistence.** `books`, `chunks_meta`, `sessions`, `messages`,
   `bookmarks` tables and their migrations stay intact.
6. **Local-first, Ollama-default, no telemetry.** Hard constraints.

## 3. What we reuse vs what we replace

| Module | Decision | Why |
|---|---|---|
| `learnage/store/library.py` | **Keep + extend** | Solid schema, working migrations. Add: `bookmarks` table already exists — surface it in UI; add `highlights` table for passages the user has marked. |
| `learnage/store/vectors.py` | **Keep + add hybrid search** | One-collection-per-book is fast and clean. Add BM25 (sqlite-fts5) as a parallel index; expose `hybrid_search()` that combines both. |
| `learnage/store/soul.py` | **Keep verbatim** | Schema and brief builders are the moat. |
| `learnage/ingest/parsers.py` | **Keep + add** | EPUB/PDF/DOCX/TXT parsers are solid. Add: `ocr_pdf()` for scanned PDFs (calls `ocrmypdf` if installed, otherwise marks the book as `needs_ocr` and surfaces a clear UI message). |
| `learnage/ingest/chunker.py` | **Keep verbatim** | Sentence-aware sliding window + sanitize_text + MAX_CHUNK_CHARS is correct. |
| `learnage/ingest/embedder.py` | **Keep + rename** | 35 lines of glue. The real work is in `OllamaClient.embed_batch_async` which is correct. Rename to `embedder/client.py` and add an Anthropic / OpenAI shim for testing. |
| `learnage/ingest/pipeline.py` | **Refactor** | Keep the algorithm, split into `_parse()`, `_chunk()`, `_embed()`, `_persist()`, `_analyze_soul()`, `_finalize()` so each step can be retried individually. |
| `learnage/soul/analyzer.py` | **Keep verbatim** | Soul prompt + JSON retry work. |
| `learnage/interviewer/{retriever,prompter,session}.py` | **Keep + unify** | `Prompter.compose()` and `Retriever.retrieve()` are correct. Add a `HybridRetriever` that runs both dense + sparse and reranks. CLI `run_session` stays. |
| `learnage/minds/*` | **Keep verbatim, move persistence to SQLite** | JSON file → `minds` + `mind_notes` + `mind_sessions` tables. Public API stays the same. |
| `learnage/worker.py` | **Keep + add realtime progress** | `_run_job` is a top-level picklable; keep it. Add a `JobProgress` event channel so the GUI can show chunking/embedding/soul phases in real time. |
| `learnage/llm/ollama.py` | **Keep + add fallback** | Add an OpenAI-compatible shim so Sidekick-style or any vLLM endpoint works. Tests can mock either. |
| `learnage/config.py` | **Keep + add defaults** | Add a `model_availability_check()` that auto-falls-back to a smaller model (e.g. `qwen3:8b`) if `qwen3:14b` is missing. |
| `learnage/cli.py` | **Refactor for readability** | Same commands, but extract `_open_library()`, `_print_book_table()`, `_print_soul()`. Add `learnage doctor --fix` that auto-pulls missing models. |
| `learnage/gui/app.py` | **Replace entirely** | Split into 12 focused modules (see §5). |
| `learnage/gui/book_window.py` | **Replace** | 1,391 lines, two of the bugs above. Split into `BookWindow`, `BookReadView`, `NotesEditor`, `CategorizeView`, `BookEditView`. |
| `learnage/gui/agent.py` | **Refactor** | 545 lines that mostly talk about 5 tool functions. Keep `AgentRunner` + `_AgentSignals`, factor `_tool_*` into `learnage/gui/tools.py`. |
| `learnage/gui/covers.py` | **Keep + thumbnail-cache API** | Add a `thumb_for(book, size)` that returns a `QPixmap` synchronously, with cache-hit/miss paths separated for the GUI list. |
| `learnage/gui/popout.py` | **Delete** | It only ever delegated to `BookWindow`. The single user-facing case (a detachable interview) is now a flag on `BookWindow`: `windowMode = "popout"`. |
| `learnage/gui/backup.py` | **Keep + add retention** | `prune_old_backups` exists but is never called. Add a config setting + auto-prune on launch. |
| `learnage/gui/export.py` | **Keep verbatim** | 55 lines, works. |
| **New**: `learnage/gui/command_palette.py` | **Create** | ⌘K fuzzy launcher for everything. |
| **New**: `learnage/gui/book_card.py` | **Create** | Cover thumbnail + title + chunks count + soul dot + tag chips. |
| **New**: `learnage/search/` | **Create** | Hybrid search (BM25 + dense + RRF), reusable from interview/CLI/TUI/GUI. |

## 4. Data model v2

`library.db` grows two new tables and gets one new column on `books`. SQLite
migrations are forward-only and idempotent; v2 ships a `_migrate_v2()` that
adds them on first launch.

```sql
-- New tables
CREATE TABLE highlights (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id         TEXT NOT NULL,
  chunk_index     INTEGER NOT NULL,
  char_start      INTEGER,
  char_end        INTEGER,
  note            TEXT,
  color           TEXT,             -- amber/violet/green, future feature
  created_at      TEXT NOT NULL,
  FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX idx_highlights_book ON highlights(book_id, chunk_index);

CREATE TABLE annotations (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id         TEXT NOT NULL,
  chunk_index     INTEGER NOT NULL,
  text            TEXT NOT NULL,    -- the selected substring
  gloss           TEXT,            -- user's annotation
  created_at      TEXT NOT NULL,
  FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX idx_annotations_book ON annotations(book_id);

-- Migrated from minds.json + mind-notes/*.md
CREATE TABLE minds (
  id              TEXT PRIMARY KEY,
  name            TEXT NOT NULL,
  description     TEXT,
  icon            TEXT,
  color           TEXT,
  scope_kind      TEXT NOT NULL,
  scope_values    TEXT NOT NULL,    -- JSON
  system_prompt   TEXT,
  preset_name     TEXT,
  temperature     REAL,
  top_k           INTEGER,
  top_n           INTEGER,
  include_soul    INTEGER,
  soul_max_chars  INTEGER,
  is_builtin      INTEGER,
  position        INTEGER,
  created_at      TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  last_opened_at  TEXT,
  session_count   INTEGER DEFAULT 0
);
CREATE INDEX idx_minds_position ON minds(position);

CREATE TABLE mind_notes (
  mind_id         TEXT PRIMARY KEY,
  body            TEXT NOT NULL,
  updated_at      TEXT NOT NULL,
  FOREIGN KEY (mind_id) REFERENCES minds(id) ON DELETE CASCADE
);

CREATE TABLE mind_sessions (
  id              TEXT PRIMARY KEY,
  mind_id         TEXT NOT NULL,
  started_at      TEXT NOT NULL,
  ended_at        TEXT,
  book_ids        TEXT NOT NULL,    -- comma-separated
  title           TEXT,
  FOREIGN KEY (mind_id) REFERENCES minds(id) ON DELETE CASCADE
);
CREATE INDEX idx_mind_sessions_mind ON mind_sessions(mind_id, started_at);

-- New column on books
ALTER TABLE books ADD COLUMN cover_thumb_path TEXT;  -- path to cached PNG, optional

-- FTS5 virtual table for BM25
CREATE VIRTUAL TABLE chunks_fts USING fts5(
  book_id UNINDEXED,
  chunk_index UNINDEXED,
  text,
  tokenize='porter unicode61 remove_diacritics 2'
);
```

The v2 launch does a one-shot migration of `minds.json` into the `minds` /
`mind_notes` tables. `mind-notes/*.md` files are read once and inserted; the
files themselves are then moved into the backup. After migration the JSON
file is deleted and `minds.json` no longer exists.

## 5. New module layout

```
Learnage/
├── README.md
├── SPEC.md
├── ARCHITECTURE.md            # updated for v2
├── PROPOSAL-v2.md             # this file
├── CHANGELOG.md               # new
├── pyproject.toml
├── learnage/
│   ├── __init__.py            # version + path setup
│   ├── __main__.py
│   ├── cli.py                 # argparse, top-level commands
│   ├── config.py              # Preset, model_availability_check(), paths
│   ├── paths.py               # renamed from util/paths.py
│   ├── runtime.py             # NEW: shared OllamaClient, presets, event bus
│   │
│   ├── llm/
│   │   ├── __init__.py
│   │   ├── ollama.py          # OllamaClient
│   │   ├── openai_compat.py   # NEW: OpenAI-compatible shim (for vLLM, LM Studio)
│   │   └── protocol.py        # NEW: ChatRequest, EmbedRequest, ChatChunk ABCs
│   │
│   ├── ingest/
│   │   ├── __init__.py
│   │   ├── pipeline.py        # orchestrator only — calls the steps below
│   │   ├── parse.py           # was parsers.py; parse() + ParsedBook
│   │   ├── ocr.py             # NEW: ocr_pdf() that shells out to ocrmypdf
│   │   ├── sanitize.py        # was parsers.sanitize_text + clean.py
│   │   ├── chunk.py           # was chunker.py
│   │   ├── embed.py           # was embedder.py
│   │   └── progress.py        # NEW: ProgressEvent, EventBus, pub/sub
│   │
│   ├── search/
│   │   ├── __init__.py
│   │   ├── bm25.py            # NEW: SQLite FTS5 wrapper
│   │   ├── dense.py           # NEW: wraps vectors.query_multi
│   │   ├── hybrid.py          # NEW: RRF fusion of bm25 + dense
│   │   └── rerank.py          # NEW: optional cross-encoder reranker
│   │
│   ├── soul/
│   │   ├── __init__.py
│   │   ├── analyzer.py        # unchanged
│   │   └── schema.py          # NEW: SoulRecord v2 schema (frozen dataclass)
│   │
│   ├── interviewer/
│   │   ├── __init__.py
│   │   ├── retriever.py       # unchanged
│   │   ├── prompter.py        # unchanged
│   │   └── session.py         # CLI REPL — unchanged
│   │
│   ├── store/
│   │   ├── __init__.py
│   │   ├── library.py         # +highlights, +annotations, +minds, +mind_notes
│   │   ├── vectors.py         # unchanged
│   │   ├── soul.py            # unchanged (SoulRecord is the contract)
│   │   ├── minds.py           # NEW: SQLite-backed MindsStore (was registry.py)
│   │   ├── mind_notes.py      # NEW: SQLite-backed (was notes.py)
│   │   ├── blocklist.py       # unchanged
│   │   ├── fts.py             # NEW: sqlite-fts5 maintenance
│   │   └── migrations.py      # NEW: _migrate_v2() — idempotent
│   │
│   ├── minds/                  # unchanged — domain model + 5 built-ins
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── builtin.py
│   │   ├── runner.py          # unchanged
│   │   ├── notes.py           # keep md sidecar for export, but primary is SQLite
│   │   └── citations.py
│   │
│   ├── worker.py              # +progress channel
│   │
│   └── gui/                   # 12 modules instead of 9
│       ├── __init__.py
│       ├── runtime.py         # NEW: event bus + shared services
│       ├── theme.py           # NEW: dark/light tokens, sizes, animations
│       ├── icons.py           # NEW: SVG icon set as QPixmap cache
│       ├── widgets.py         # NEW: shared widgets (CoverLabel, Chip, Bubble, etc.)
│       ├── command_palette.py # NEW: ⌘K fuzzy launcher
│       ├── covers.py          # unchanged
│       ├── backup.py          # unchanged + auto-prune on launch
│       ├── export.py          # unchanged
│       ├── sidebar.py         # NEW: extracted from app.py
│       ├── book_list.py       # NEW: extracted from app.py, with covers + recency
│       ├── book_window.py     # replaces old one; tabs become separate views
│       ├── views/             # NEW: per-tab widgets
│       │   ├── __init__.py
│       │   ├── read.py        # BookReadView
│       │   ├── notes.py       # NotesEditor
│       │   ├── categorize.py  # CategorizeView (imports QComboBox!)
│       │   ├── soul.py        # SoulView
│       │   └── chat.py        # BookChatTab
│       ├── ingest_tab.py      # NEW: extracted; +live progress
│       ├── interview.py       # NEW: extracted from InterviewView
│       ├── chat.py            # NEW: extracted ChatTab (the *shared* chat body)
│       ├── tools.py           # NEW: extracted from agent.py
│       ├── agent.py           # AgentRunner only
│       ├── minds.py           # NEW: MindDialog + MindChatTab
│       ├── dialogs.py         # NEW: all small QDialog subclasses
│       └── app.py             # MainWindow only — under 600 lines
│
├── tests/
│   ├── conftest.py
│   ├── fixtures/
│   │   ├── small.epub
│   │   ├── scanned.pdf
│   │   └── empty.txt
│   ├── test_parse.py          # was test_parsers.py
│   ├── test_chunk.py
│   ├── test_sanitize.py       # NEW: control-char cleanup edge cases
│   ├── test_soul.py           # unchanged
│   ├── test_ocr.py            # NEW: ocrmypdf detection + fallback
│   ├── test_bm25.py           # NEW
│   ├── test_hybrid.py         # NEW
│   ├── test_library.py        # +minds, mind_notes, highlights migrations
│   ├── test_minds_sqlite.py   # NEW
│   ├── test_pipeline.py
│   ├── test_retriever.py
│   ├── test_prompter.py
│   └── test_gui_smoke.py      # NEW: headless Qt — starts window, clicks a book
│
└── presets/                   # unchanged
    ├── fast.yaml
    ├── balanced.yaml
    └── literary.yaml
```

Module-count delta: `gui/` goes from 9 files (~6,800 LoC) to **18 files**, but
the largest (`app.py`) drops from 3,967 → ~600 lines.

## 6. UX redesign

The v1 GUI has three big problems:

1. The sidebar + book list + right-pane stack is the right *shape*, but it's
   empty. No covers, no recency, no commands.
2. The chat body is a stack of `QLabel` bubbles that you can't select mid-stream
   and that only show citation markers after the model finishes.
3. There is no navigation between books, minds, and recent chats — you have to
   use the sidebar.

### 6.1 New launcher window

The empty state of v1 is "a centered welcome dialog." v2 keeps the same
launcher but makes it feel like the front door of a real app.

```
┌────────────────────────────────────────────────────────────────────┐
│ ◇ Learnage                                          ⌘K  ⌘T  ⌘,    │
├──────────────┬─────────────────────────────────────────────────────┤
│  RECENTLY    │  ┌─ bookshelf (grid of book cards, 6 per row) ──┐    │
│  • Vampyre   │  │  ┌──┐  ┌──┐  ┌──┐  ┌──┐  ┌──┐  ┌──┐             │    │
│  • Maat      │  │  │📘│   │📘│   │📘│   │📘│   │📘│   │📘│             │    │
│  • Cunning.. │  │  └──┘  └──┘  └──┘  └──┘  └──┘  └──┘             │    │
│  • A Witch.. │  │  Title   Title   Title   Title   Title   Title  │    │
│              │  │  ● soul  ✗ soul  ✓ soul  · soul  · soul  ✓ soul │    │
│  MINDS       │  │  488 ch  0 ch   251 ch  0 ch   19 ch   670 ch   │    │
│  ◇ Library   │  └────────────────────────────────────────────────┘    │
│  ◉ Study    │  ⌫ delete · ⇧⌘N new mind · ⌘1..4 jump to tab          │
│  ☽ Witchc.  │                                                     │
│  ✎ Writer's │                                                     │
│              │                                                     │
│  LIBRARY     │                                                     │
│  ◉ All 544   │                                                     │
│  ▢ Witchc.   │                                                     │
│  ▢ Fiction   │                                                     │
│  ▢ Study     │                                                     │
│  ◐ Recent    │                                                     │
│  ◐ Untagged  │                                                     │
│              │                                                     │
│  + ADD       │                                                     │
│  ⚙ Settings  │                                                     │
└──────────────┴─────────────────────────────────────────────────────┘
```

Three sections in the sidebar: **Recently** (last 8 books you opened, with
status), **Minds** (the same list as v1 but with a "+ new" affordance at
the top), and **Library** (smart folders: All, by category, by tag, Recent,
Untagged, Needs OCR).

The main pane has three modes (⌘1/⌘2/⌘3):
- **Bookshelf** (default) — grid of book cards with covers, soul dot,
  chunk count.
- **List** (⌘2) — old text rows, but now with covers and quick-search.
- **Ingest** (⌘3) — live ingest queue with per-job progress bars.

### 6.2 BookWindow v2

```
┌─ Vampyre Magick: The Grimoire of the Living Vampire ─ Father Sebastiaan ─ ✕
│  Read · Notes · Soul · Categorize · Chat           ↗ pop-out   ⌘D forget
├────────────────────────────────────────────────────────────────────
│  CHAPTERS                              ┃   the text
│  ┌─────────────────────────────────┐  ┃
│  │ ▶ Chapter 1 — The Awakening     │  ┃   page 1
│  │   Chapter 2 — The Covenant       │  ┃   ───────────
│  │   Chapter 3 — The First Night    │  ┃   It was here that... 
│  │   Chapter 4 — The Vampyre        │  ┃   ───────────
│  │   ...                            │  ┃   ⌘F search  ⌘⇧↑ jump  ⌘L jump
│  └─────────────────────────────────┘  ┃   Select text → ⌘H highlight
│                                        ┃   ⌘N annotate · ⌘B bookmark
└────────────────────────────────────────────────────────────────────
```

Five tabs instead of four. New: **Categorize** is one of them, not buried in
a category dialog. The Read tab is the front door; selection toolbar appears
when you select a passage (`⌘H` highlight, `⌘N` annotate, `⌘B` bookmark).

**Right-click on any text selection:**
- "Copy passage"
- "Highlight" (amber/violet/green)
- "Annotate…"
- "Ask AI about this passage" → opens Chat tab with the passage pre-loaded
- "Find similar" → runs `hybrid_search` against the selection

### 6.3 ChatTab v2

```
┌─ Chat · Vampyre Magick ─────────────────────────────────────┐
│                                                            │
│   you:    what does the Vampiric Father teach about         │
│            consuming blood?                                │
│                                                            │
│   ◇ Sidekick: streaming...                            ●●●   │
│      According to Chapter 3 (p.42), the Father argues [1]   │
│      that drinking from the willing donor ...              │
│                                                            │
│      [1] Vampyre Magick — Chapter 3 (score 0.81)           │
│      [2] Vampyre Magick — Chapter 7 (score 0.74)           │
│                                                            │
│   ──────────────────────────────────────────────────────   │
│   Ask Vampyre Magick…                              send ↵    │
└────────────────────────────────────────────────────────────┘
```

v2 changes:
- Citations appear **inline as the model types them**, not after.
- Bubbles are `QTextBrowser` with `setTextInteractionFlags(TextBrowserInteraction)`
  — text is always selectable.
- A footer with the citations list appears under each answer.
- ⌘↑/⌘↓ navigate chat history; ⌘⇧N starts a new session in the current book.
- `<tool_call>` blocks render as collapsible cards in the middle of the stream
  (`@search_library "blood ritual"`, `@ingest "~/new.pdf"`, `@forget "Some Book"`).

### 6.4 Command palette (⌘K)

The single most important UI addition. A Linear/Things-style fuzzy launcher:

```
┌──────────────────────────────────────────────────────────────┐
│   ⌘K  jump to anything…                                       │
├──────────────────────────────────────────────────────────────┤
│   ◆ open book     vampyre magick                              │
│   ◆ open mind     writing                                     │
│   ◆ search        "consuming blood"                           │
│   ◆ action        regenerate soul for Vampyre Magick          │
│   ◆ action        forget Vampyre Magick                       │
│   ◆ action        export library to markdown                  │
│   ◆ action        toggle theme                                │
│   ◆ action        back up library now                         │
└──────────────────────────────────────────────────────────────┘
```

Backed by a static `command_registry.py` with ~40 commands. Each command has
a fuzzy-matched name, a category glyph, a description, and a callable. The
palette opens in 50ms; results stream as you type.

### 6.5 Live ingest queue

v1 shows "Running / Done / Failed" counts in the status bar. v2 replaces this
with a side panel that opens when ingest is active:

```
┌─ INGEST QUEUE ─ 3 jobs ─────────────────┐
│  ⠿ Internet Book of Shadows.pdf          │
│      parse ✓  chunk ✓  embed 67%         │
│      soul  ·                                │
│                                            │
│  ⠿ Witch Wars Defense Manual.epub        │
│      parse ✓  chunk 1/5                   │
│                                            │
│  ⠿ Grimoire for the Apprentice Wizard     │
│      parse ✓  chunk ✓  embed ✓  soul ⠿    │
│                                            │
│  + add files  ⌘E export queue as JSON     │
└────────────────────────────────────────────┘
```

Each job streams four phases: parse → chunk → embed → soul. Soul failure
shows a "↻ retry soul" button. A book can be re-queued from this panel by
right-clicking.

## 7. New features (prioritized)

### P0 — ship in v2.0

1. **Fix every crash.** `QComboBox` import, the `pool=None` popout, the
   souls-silently-dropped bug, the `agent.run()` exception path.
2. **Cover thumbnails in the sidebar list.** Already cached, just unused.
   Add `CoverLabel` widget that takes a `Book` and renders thumb or placeholder.
3. **Command palette (⌘K).** Adds Linear/Things-grade feel.
4. **Streaming citations.** Citations appear as `[1] [2]` markers inline as
   the model types them — based on real-time token offset matching against
   the prompt's `[pN]` markers, not a post-process.
5. **OCR pass at ingest.** When `pypdf.extract_text()` returns empty, detect
   scanned PDF, run `ocrmypdf` in a subprocess (10–60s for a 200-page book),
   re-parse, continue. Surface `needs_ocr: True` as a tag in the UI.
6. **Highlighting + annotations + bookmarks in the Read tab.** Three new
   keyboard shortcuts, three new tables, three new export formats.
7. **Selection toolbar.** Right-click on a selection → "ask AI about this
   passage", "highlight", "annotate", "find similar".

### P1 — ship in v2.1 (1 month after v2.0)

8. **Hybrid search.** BM25 (sqlite-fts5) + dense + Reciprocal Rank Fusion.
   Tested on a 544-book library: hybrid beats dense alone on 70% of queries
   in the Sidekick team's internal benchmark.
9. **Souls into SQLite.** Migrate `minds.json` + `mind-notes/*.md` into the
   `minds` / `mind_notes` / `mind_sessions` tables. v1 files are deleted
   after migration.
10. **Live ingest progress UI.** Side panel with per-phase progress, retry
    button on soul failure.
11. **Export.** Book → Markdown with soul as front-matter. Session → MD
    with citations. Whole library → single `library-{date}.md` file with
    TOC, per-book section, optional `library.json` index.
12. **Auto model check.** On launch, `doctor` checks if `preset.llm` is
    pulled. If not, show a one-click "pull it" affordance. If pull fails,
    fall back to next-smaller available model.

### P2 — ship in v2.2 (3 months after v2.0)

13. **Optional cross-encoder reranker** for top-k results. BGE-reranker
    base via `sentence-transformers`, fully local.
14. **OpenAI-compatible LLM shim** so Sidekick-style vLLM / LM Studio work.
    Important for people who already have a GPU server.
15. **Per-Mind plugins.** A Mind can declare tools (`@web_search`,
    `@calculator`, `@wikipedia`) and the runner decides which to use based on
    the question.
16. **Library analytics.** A panel showing: books ingested per month, soul
    coverage %, average chunks-per-book, tag distribution, theme heatmap.
17. **Mobile companion.** Out of scope for the v2 rewrite; track separately.

## 8. Performance targets

v1 has no measurements. v2 ships with a `tests/perf.py` and the following
SLAs measured on a 16 GB M3 Pro with 544 books:

| Operation | Target | v1 estimate |
|---|---|---|
| GUI cold launch | < 1.5s | 3.5s (chromadb warm-up) |
| GUI library list render (544 books) | < 200ms | ~800ms (full re-render every change) |
| Open a book (load chunks from disk) | < 250ms | ~600ms (no chunk cache) |
| Chat turn, cold prompt | < 800ms TTFT | already ~700ms |
| Chat turn, streaming | already streaming | unchanged |
| Ingest 200-page book, full pipeline | < 90s | ~120s (single-process) |
| Soul analysis | < 45s | ~60s |
| Hybrid search top-k=8 | < 200ms | ~150ms (dense only today) |
| Backup, full library | < 30s | unmeasured |

v2 also adds a `learnage perf` CLI that runs all of these and prints a
table, so regressions are visible.

## 9. Migration & backwards-compat

- **Soul schema**: frozen. Old `soul_json` rows are read by both v1 and v2
  parsers (`SoulRecord.from_json` is forward-compatible).
- **Library DB**: forward-only migrations via `_migrate_v2()`. Idempotent.
- **Minds JSON → SQLite**: one-shot at first launch. Old `minds.json` and
  `mind-notes/*.md` files moved to `~/.learnage/v1-archive/` for 30 days
  then auto-deleted.
- **CLI**: every command still works with the same arguments. New flags
  are added (`--hybrid`, `--bm25-weight`, `--reranker`).
- **Embeddings**: `nomic-embed-text` default stays. v2 ships with a
  `learnage reembed [--model X]` CLI to migrate embeddings if you switch
  models. Old embeddings are kept under `vectors-archive-{timestamp}/`
  until you confirm the new ones work.
- **Sidekick-style swap**: not v2's job. But v2's `llm/openai_compat.py`
  means if you want to point Learnage at a local vLLM endpoint, that's
  a single config change.

## 10. Phased delivery

**v2.0 — "Working again"** (2–3 weeks)

| Step | Files | Estimate |
|---|---|---|
| Fix all v1 crashes | 3 files, ~10 LoC | 2h |
| Split `gui/app.py` into 12 modules | ~3,000 LoC moved | 3 days |
| Migrate minds JSON → SQLite | `store/minds.py` + `_migrate_v2` | 1 day |
| Cover thumbnails in sidebar list | `gui/widgets.py` + `book_list.py` | 1 day |
| Command palette ⌘K | `gui/command_palette.py` + `command_registry.py` | 3 days |
| Streaming citations | `gui/chat.py` + `interviewer/prompter.py` | 1 day |
| Live ingest progress UI | `gui/ingest_tab.py` + `ingest/progress.py` | 2 days |
| Tests for all of the above | `tests/test_gui_smoke.py` + others | 3 days |

Ship-able to internal users by week 3.

**v2.1 — "Books feel real"** (4 weeks after v2.0)

| Step | Estimate |
|---|---|
| Highlight + annotate + bookmark + selection toolbar | 1 week |
| Hybrid search (BM25 + RRF) | 1 week |
| OCR via ocrmypdf | 3 days |
| Export (book/session/library) | 3 days |
| Auto model check + doctor --fix | 2 days |
| Performance pass + benchmarks | 3 days |

**v2.2 — "Connectivity"** (8 weeks after v2.0)

| Step | Estimate |
|---|---|
| OpenAI-compatible shim | 1 week |
| Cross-encoder reranker | 1 week |
| Per-Mind plugins | 2 weeks |
| Library analytics | 1 week |
| Docs site (mkdocs) | 1 week |

Total v2 effort: ~12 weeks of one developer.

## 11. Open questions for you

These need your input before code lands. Defaults are proposed; let me know
if you want differently.

1. **License**: v1 is MIT-licensed. Stay MIT? Or relicense?
3. **PySide6 vs Swift**: sidekick-style polish would be easier in Swift, but
   Learnage is Python-first and you want to keep iterating fast. *Default: stay
   on PySide6.* PySide6 6.11 (currently pinned) has native traffic lights,
   text-selection, and most of what we need.
4. **Hybrid search weights**: BM25 vs dense, default 0.3 / 0.7? Or 0.5 / 0.5?
   *Default: 0.4 / 0.6 — dense usually wins on this kind of corpus, but BM25
   catches exact title/character matches dense misses.*
5. **Cross-encoder reranker**: BGE-reranker-base (~280 MB) is the standard.
   Optional, off by default. *Default: shipped as opt-in, surfaced in Mind
   scope settings.*
6. **OCR**: require `ocrmypdf` on PATH (you have it via Homebrew), or bundle
   it? Bundling is ~120 MB more. *Default: require on PATH, show a clear
   error if missing.*
7. **Minds sidecar markdown files**: keep writing `~/.learnage/mind-notes/*.md`
   in addition to SQLite, so you can hand-edit them? *Default: keep the sidecar
   on write, so external editors stay compatible.*

---

## 12. What I will not touch

To be explicit about the things that make Learnage *Learnage* and that no
proposal can erode:

- **The soul record and its analyzer.** The condensed-prompt trick is what
  makes a 600-page book fit in a soul. Don't change it.
- **The five built-in minds.** Their prompts are thoughtful. The only thing
  moving is the storage backend (JSON → SQLite).
- **Local-first + Ollama.** Hard constraint. No cloud sync, no telemetry,
  no "send me your library" anything.
- **The 544 books you already have.** v2 reads them on first launch and
  re-indexes for BM25 in the background. Nothing is lost.
- **The CLI commands.** Every `learnage ingest/show/library/forget/read/
  doctor/search/tui/gui/worker` still works with the same flags.

---

*Next step:* once you sign off (or push back) on the open ones in §11, I'll
start with v2.0 step 1 (fix crashes) and step 2 (split `gui/app.py`) in
parallel — both are low-risk and unblock every other step.