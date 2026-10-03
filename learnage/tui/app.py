"""Textual TUI for Learnage.

Three tabs:
  - Library: list of all ingested books, click to view soul
  - Ingest: add files / dirs, watch background workers process them
  - Interview: ask a question, stream an answer grounded in selected books

The TUI owns a single IngestPool for the session. Ingest jobs run in a
ProcessPoolExecutor using `workers` subprocesses — never blocking the UI.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.reactive import reactive
from textual.screen import ModalScreen
from textual.widgets import (
    Button,
    DataTable,
    Footer,
    Header,
    Input,
    Label,
    RichLog,
    Static,
    TabbedContent,
    TabPane,
)

from learnage.config import Preset, default_preset_name, load_preset
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Book, Library
from learnage.store.soul import SoulRecord
from learnage.store.vectors import VectorStore
from learnage.util.paths import default_home, ensure_home, library_db_path, vectors_dir
from learnage.worker import IngestJob, IngestPool, JobStatus


def _fmt_ts(ts: Optional[float]) -> str:
    if ts is None:
        return "—"
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


# ----------------------------------------------------------------- Library tab


class LibraryPane(Vertical):
    """List of ingested books + a soul viewer."""

    def __init__(self, library: Library) -> None:
        super().__init__()
        self.library = library

    def compose(self) -> ComposeResult:
        yield Label("[bold]Your library[/bold]")
        yield DataTable(id="library-table", cursor_type="row", zebra_stripes=True)
        yield Label("[bold]Soul[/bold]  (select a book above)")
        yield RichLog(id="soul-view", wrap=True, markup=True, highlight=True)

    def on_mount(self) -> None:
        table = self.query_one("#library-table", DataTable)
        table.add_columns("title", "author", "chunks", "soul", "ingested")
        self.refresh_table()
        # Refresh every 2s while focused.
        self.set_interval(2.0, self.refresh_table)

    def refresh_table(self) -> None:
        table = self.query_one("#library-table", DataTable)
        table.clear()
        for b in self.library.list_books():
            soul_mark = {"ok": "✓", "failed": "✗", "pending": "·", "skipped": "·"}.get(b.soul_status or "", "?")
            table.add_row(
                b.title,
                b.author or "—",
                str(b.chunk_count or 0),
                soul_mark,
                b.ingested_at,
                key=b.id,
            )

    def on_data_table_row_highlighted(self, event: DataTable.RowHighlighted) -> None:
        book_id = event.row_key.value if event.row_key else None
        if not book_id:
            return
        book = self.library.get_book(book_id)
        log = self.query_one("#soul-view", RichLog)
        log.clear()
        if not book:
            log.write("(book not found)")
            return
        if not book.soul_json:
            log.write("[dim](no soul — re-ingest or run `learnage soul <book>`)[/dim]")
            return
        try:
            soul = SoulRecord.from_json(book.soul_json)
        except Exception as e:  # noqa: BLE001
            log.write(f"[red]parse error:[/red] {e}")
            return
        log.write(Text(book.title + (f" — {book.author}" if book.author else ""), style="bold"))
        log.write("")
        if soul.summary:
            log.write(f"[b]Summary[/b]\n{soul.summary}\n")
        if soul.voice:
            log.write("[b]Voice[/b]")
            for k, v in soul.voice.items():
                log.write(f"  {k}: {v}")
        if soul.themes:
            log.write("[b]Themes[/b]")
            for t in soul.themes:
                log.write(f"  • {t.get('name','')} — {t.get('gloss','')}")
        if soul.characters:
            log.write("[b]Characters[/b]")
            for c in soul.characters:
                log.write(f"  • {c.get('name','')} ({c.get('role','')}) — {c.get('gloss','')}")
        if soul.key_passages:
            log.write("[b]Key passages[/b]")
            for kp in soul.key_passages:
                log.write(f"  • “{kp.get('quote','')}” ({kp.get('context','')})")
        if soul.craft_notes:
            log.write("[b]Craft notes[/b]")
            for n in soul.craft_notes:
                log.write(f"  • {n}")


# ----------------------------------------------------------------- Ingest tab


class IngestPane(Vertical):
    """Add files to the ingest queue and watch the worker process them."""

    def __init__(self, pool: IngestPool, library: Library) -> None:
        super().__init__()
        self.pool = pool
        self.library = library

    def compose(self) -> ComposeResult:
        with Horizontal(id="ingest-controls"):
            yield Input(placeholder="path to a book or directory", id="ingest-path")
            yield Button("Add", id="ingest-add", variant="primary")
            yield Button("Add dir", id="ingest-add-dir", variant="default")
            yield Label(f"workers: {self.pool.workers}", id="workers-label")
        yield Label("[bold]Queue[/bold]  (running · done · failed)")
        yield DataTable(id="queue-table", cursor_type="row", zebra_stripes=True)
        with Horizontal(id="ingest-stats"):
            yield Label("queued: 0   running: 0   done: 0   failed: 0", id="ingest-summary")

    def on_mount(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.add_columns("state", "book", "chunks", "started", "finished", "error")
        self.set_interval(0.5, self.refresh_table)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        path_input = self.query_one("#ingest-path", Input)
        text = path_input.value.strip()
        if not text:
            return
        if event.button.id == "ingest-add-dir":
            p = Path(text).expanduser()
            if p.is_dir():
                count = 0
                for ext in ("epub", "pdf", "docx", "txt"):
                    for f in p.rglob(f"*.{ext}"):
                        self.pool.submit(IngestJob(path=str(f.resolve())))
                        count += 1
                self.app.notify(f"queued {count} files from {p}")
                path_input.value = ""
                return
        # Single file
        p = Path(text).expanduser()
        if p.exists():
            self.pool.submit(IngestJob(path=str(p.resolve())))
            self.app.notify(f"queued {p.name}")
            path_input.value = ""
        else:
            self.app.notify(f"not found: {text}", severity="error")

    def refresh_table(self) -> None:
        table = self.query_one("#queue-table", DataTable)
        table.clear()
        for jid, s in sorted(self.pool.statuses.items()):
            err = s.error or ""
            if err and len(err) > 40:
                err = err[:37] + "..."
            table.add_row(
                s.state,
                s.job.display_name,
                str(s.chunks),
                _fmt_ts(s.started_at),
                _fmt_ts(s.finished_at),
                err,
                key=str(jid),
            )
        n_queued = sum(1 for s in self.pool.statuses.values() if s.state == "queued")
        n_running = sum(1 for s in self.pool.statuses.values() if s.state == "running")
        n_done = sum(1 for s in self.pool.statuses.values() if s.state == "done")
        n_failed = sum(1 for s in self.pool.statuses.values() if s.state == "failed")
        summary = self.query_one("#ingest-summary", Label)
        summary.update(
            f"queued: {n_queued}   running: {n_running}   done: {n_done}   failed: {n_failed}"
        )


# ----------------------------------------------------------------- Interview tab


class InterviewPane(Vertical):
    """Ask questions against one or many books."""

    def __init__(
        self,
        library: Library,
        vectors: VectorStore,
        ollama: OllamaClient,
        preset: Preset,
    ) -> None:
        super().__init__()
        self.library = library
        self.vectors = vectors
        self.ollama = ollama
        self.preset = preset
        self.history: list[dict] = []
        self.last_passages: list = []
        self.book_ids: list[str] = []

    def compose(self) -> ComposeResult:
        with Horizontal(id="iv-controls"):
            yield Input(placeholder="comma-separated book titles", id="iv-books")
            yield Button("Set books", id="iv-set", variant="primary")
            yield Label("no books set", id="iv-status")
        yield RichLog(id="iv-log", wrap=True, markup=True, highlight=True)
        yield Input(placeholder="ask a question…", id="iv-question")

    def on_mount(self) -> None:
        log = self.query_one("#iv-log", RichLog)
        log.write("[dim]Welcome. Set the books you want to interview, then ask away.[/dim]")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "iv-set":
            self.set_books()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "iv-question":
            asyncio.create_task(self.ask(event.value))
            event.input.value = ""

    def set_books(self) -> None:
        text = self.query_one("#iv-books", Input).value.strip()
        ids: list[str] = []
        for raw in text.split(","):
            title = raw.strip()
            if not title:
                continue
            b = self.library.find_by_title(title)
            if not b:
                self.app.notify(f"no match: {title}", severity="error")
                continue
            ids.append(b.id)
        self.book_ids = ids
        books = [self.library.get_book(i) for i in ids]
        titles = ", ".join(b.title for b in books if b)
        self.query_one("#iv-status", Label).update(f"{len(ids)} book(s): {titles[:60]}")
        self.history = []

    async def ask(self, question: str) -> None:
        if not self.book_ids:
            self.app.notify("set books first", severity="warning")
            return
        if not question.strip():
            return
        log = self.query_one("#iv-log", RichLog)
        log.write(f"\n[bold cyan]you[/bold cyan] › {question}")

        # Pull books + souls
        books: list[Book] = []
        souls: dict[str, SoulRecord | None] = {}
        for bid in self.book_ids:
            b = self.library.get_book(bid)
            if b:
                books.append(b)
                if b.soul_json:
                    try:
                        souls[bid] = SoulRecord.from_json(b.soul_json)
                    except Exception:  # noqa: BLE001
                        souls[bid] = None
                else:
                    souls[bid] = None

        # Retrieve
        from learnage.interviewer.prompter import compose
        from learnage.interviewer.retriever import retrieve

        passages = retrieve(
            question,
            book_ids=self.book_ids,
            vectors=self.vectors,
            preset=self.preset,
        )
        self.last_passages = passages

        messages = compose(
            question=question,
            books=books,
            souls=souls,
            passages=passages,
            history=self.history,
        )

        # Stream
        log.write("[bold green]learnage[/bold green] › ", expand=False)
        answer_parts: list[str] = []
        try:
            for event in self.ollama.chat(
                model=self.preset.llm, messages=messages, stream=True
            ):
                chunk = (event.get("message") or {}).get("content", "")
                if chunk:
                    answer_parts.append(chunk)
                    log.write(chunk, expand=False)
                if event.get("done"):
                    break
        except Exception as e:  # noqa: BLE001
            log.write(f"\n[red]error:[/red] {e}")
            return

        log.write("\n")
        self.history.append({"role": "user", "content": question})
        self.history.append({"role": "assistant", "content": "".join(answer_parts)})

        # Persist
        from learnage.store.library import Library as _Lib  # noqa: F401
        import uuid
        sid = uuid.uuid4().hex[:12]
        self.library.create_session(sid, self.book_ids)
        self.library.append_message(sid, "user", question)
        self.library.append_message(
            sid,
            "assistant",
            "".join(answer_parts),
            citations=[
                {"book_id": p.book_id, "chunk_index": p.chunk_index, "score": p.score}
                for p in passages
            ],
        )
        self.library.end_session(sid)


# ----------------------------------------------------------------- App


class LearnageApp(App):
    CSS = """
    Screen { layout: vertical; }
    #ingest-controls, #iv-controls { height: 3; padding: 1 1; }
    #ingest-stats { height: 1; padding: 0 1; }
    DataTable { height: 1fr; }
    RichLog { height: 1fr; border: solid $accent; }
    #soul-view { height: 1fr; }
    #workers-label { width: auto; padding: 1 1; }
    """

    BINDINGS = [
        Binding("ctrl+l", "show_tab('library')", "Library"),
        Binding("ctrl+i", "show_tab('ingest')", "Ingest"),
        Binding("ctrl+r", "show_tab('interview')", "Interview"),
        Binding("ctrl+q", "quit", "Quit"),
    ]

    def __init__(
        self,
        *,
        preset: Preset,
        home: Path,
        workers: int,
    ) -> None:
        super().__init__()
        self.preset = preset
        self.home = home
        self.workers_n = workers
        self.library = Library(library_db_path(home))
        self.ollama = OllamaClient()
        self.vectors = VectorStore(vectors_dir(home), ollama=self.ollama, embed_model=preset.embed)
        self.pool = IngestPool(preset=preset, home=home, workers=workers)
        self.pool.start()
        self._runner_task: Optional[asyncio.Task] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with TabbedContent(initial="library"):
            with TabPane("Library", id="library"):
                yield LibraryPane(self.library)
            with TabPane("Ingest", id="ingest"):
                yield IngestPane(self.pool, self.library)
            with TabPane("Interview", id="interview"):
                yield InterviewPane(
                    self.library, self.vectors, self.ollama, self.preset
                )
        yield Footer()

    async def on_mount(self) -> None:
        self.title = "Learnage"
        self.sub_title = f"{self.preset.name} · {self.workers_n} workers · {self.home}"

        # Start the background pool runner.
        self._runner_task = asyncio.create_task(self.pool.run_forever())

    async def on_unmount(self) -> None:
        if self._runner_task:
            self._runner_task.cancel()
            try:
                await self._runner_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        self.pool.stop(wait=False)
        self.library.close()
        self.ollama.close()

    def action_show_tab(self, tab_id: str) -> None:
        tabs = self.query_one(TabbedContent)
        tabs.active = tab_id


def run_tui(*, preset_name: Optional[str], workers: int, home: Optional[Path]) -> None:
    """Entry point used by `learnage tui`."""
    home = ensure_home(home or default_home())
    preset = load_preset(preset_name or default_preset_name())
    app = LearnageApp(preset=preset, home=home, workers=workers)
    # Headless safety: if not a TTY, run headless so we don't burn CPU.
    headless = not os.isatty(0) or not os.isatty(1)
    app.run(headless=headless)
