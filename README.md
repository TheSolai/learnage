# Learnage

> A local-first book interviewer that *remembers* what it read.

Drop in `epub` / `pdf` / `docx` files. Learnage ingests them, distills their
**soul** (themes, voice, characters, key passages), and lets you interview
the books in a REPL — one at a time or several at once. The library is
durable. The model's memory of each book survives across sessions.

Built on Ollama. Local-only. No cloud, no telemetry.

---

## Quick start

```bash
# 1. Install
git clone <this-repo> && cd Learnage
uv sync

# 2. Make sure Ollama is running and models are pulled
ollama pull nomic-embed-text
ollama pull qwen3:8b          # default chat model
ollama pull qwen3:14b         # for better quality

# 3. Sanity-check
uv run learnage doctor

# 4. Open the TUI (interactive; uses all your cores for background ingest)
uv run learnage tui --workers 8
```

If you'd rather stay in the terminal:

```bash
# 4b. Ingest a book from the CLI
uv run learnage ingest ~/Calibre\ Library/SORTED/SomeBook.epub

# 5b. Interview it
uv run learnage read "Some Book"
```

Inside the CLI REPL:

```
learnage › what does the author think about grief?
... (streams)

learnage › /soul                # show what the model thinks this book is
learnage › /passages            # show sources for the last answer
learnage › /clear               # clear conversation memory
learnage › /quit
```

Multi-book panel:

```bash
uv run learnage read "Book A","Book B","Book C"
```

---

## Commands

```
learnage tui [--workers N]         # open the Textual TUI (default 8 workers)
learnage worker --inbox PATH       # standalone daemon: watches inbox, ingests new files
learnage ingest [--no-soul] PATH... # CLI ingest (no-soul = faster, skips soul analysis)
learnage library                   # list ingested books
learnage show <book>               # show a book's soul
learnage forget <book>             # remove a book + its vectors
learnage read <book>[,<book>...]   # CLI REPL interview (one or many books)
learnage doctor                    # check Ollama, models, db
learnage --help                    # everything else
```

## TUI

`learnage tui` opens a three-tab interface:

- **Library** — sortable list of every ingested book. Click one to read its soul.
- **Ingest** — type a path (or click "Add dir" for a folder). Files go into a queue
  processed by `--workers` parallel subprocesses. The UI never blocks. Live
  queue + state shown below.
- **Interview** — set the books you want to talk to, then ask. Streams the
  answer grounded in the books you chose.

Press `ctrl+l` / `ctrl+i` / `ctrl+r` to jump between tabs.

## Background daemon

For headless background ingestion (e.g. running on a server, or you just want
to drop books in a folder and forget):

```bash
mkdir -p ~/.learnage/inbox
uv run learnage worker --inbox ~/.learnage/inbox --workers 8
```

Then any `.epub` / `.pdf` / `.docx` / `.txt` you drop into `~/.learnage/inbox`
gets ingested automatically as soon as its size stops changing.

---

## Presets

```bash
uv run learnage --preset fast read "Book"        # qwen3:8b — snappy
uv run learnage --preset balanced read "Book"    # qwen3:14b — default
uv run learnage --preset literary read "Book"    # gemma4:31b — best prose awareness
```

Define your own in `presets/<name>.yaml` and pass `--preset <name>`.

---

## What "soul" means

When Learnage reads a book it generates a structured summary:

- **summary** — one paragraph
- **voice** — register, tone, rhythm, diction
- **themes** — 5–10 themes with one-line glosses
- **characters** — major characters + role
- **plot** — shape + central tension
- **key passages** — 3–10 load-bearing quotations
- **craft notes** — observations about how the author works

This is what the model carries into the conversation. The chunk index is
just evidence it pulls on demand.

```bash
uv run learnage show "Book"
# prints the soul as JSON
```

---

## Library location

By default everything lives under `~/.learnage/`:

```
~/.learnage/
├── library.db         # SQLite: books, chunks meta, sessions, messages
└── vectors/           # ChromaDB persistent directory
```

Override:

```bash
LEARNAGE_HOME=/path/to/library uv run learnage ...
uv run learnage --home /path/to/library ...
```

---

## Status

Working. Ingestion, soul analysis, REPL interview, multi-book sessions,
and persistence are all live. See `SPEC.md` for the full product vision
and `ARCHITECTURE.md` for the design.

---

## Relationship to SmolQuill

SmolQuill is Anne's SwiftUI writing app — Learnage is its reading-room
twin. Same vibe (Python + Ollama, presets, layered architecture,
soul-aware), opposite domain. **Learnage never touches SmolQuill's code
or repo**; this is a fresh project.
