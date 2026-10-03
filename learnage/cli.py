"""CLI entry point."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rich.console import Console
from rich.table import Table

from learnage import __version__
from learnage.config import Preset, default_preset_name, load_preset
from learnage.ingest.pipeline import ingest_paths, ingest_path
from learnage.interviewer.session import run_session
from learnage.llm.ollama import OllamaClient, OllamaError
from learnage.store.library import Library
from learnage.store.soul import SoulRecord
from learnage.store.vectors import VectorStore
from learnage.util.paths import default_home, ensure_home, library_db_path, vectors_dir


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="learnage",
        description="Local-first book interviewer that remembers what it read.",
    )
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    p.add_argument(
        "--home",
        type=Path,
        default=None,
        help="Library home (default: $LEARNAGE_HOME or ~/.learnage)",
    )
    p.add_argument(
        "--preset",
        choices=["fast", "balanced", "literary"],
        default=None,
        help=f"Model preset (default: $LEARNAGE_PRESET or {default_preset_name()})",
    )
    p.add_argument(
        "--llm", default=None, help="Override chat model (e.g. qwen3:14b)"
    )
    p.add_argument(
        "--embed", default=None, help="Override embedding model (e.g. nomic-embed-text)"
    )
    p.add_argument(
        "--k", type=int, default=None, help="Override retrieval k"
    )

    sub = p.add_subparsers(dest="cmd", required=True)

    # ingest
    sp = sub.add_parser("ingest", help="Ingest one or more books")
    sp.add_argument("paths", nargs="+", type=Path, help="Files or directories")
    sp.add_argument("--overwrite", action="store_true", help="Re-ingest even if hash matches")
    sp.add_argument("--no-soul", action="store_true", help="Skip soul analysis (faster; chunks still indexed)")

    # library
    sub.add_parser("library", help="List ingested books")

    # show
    sp = sub.add_parser("show", help="Show a book's soul")
    sp.add_argument("title", help="Book title or substring")

    # forget
    sp = sub.add_parser("forget", help="Remove a book and its vectors")
    sp.add_argument("title", help="Book title or substring")

    # read
    sp = sub.add_parser("read", help="Open a REPL interview with one or more books")
    sp.add_argument(
        "books",
        help="Comma-separated book titles, e.g. 'Title A,Title B'",
    )

    # doctor
    sub.add_parser("doctor", help="Check Ollama, models, db")

    # search
    sp = sub.add_parser("search", help="Search all books for a query")
    sp.add_argument("query", help="Search query")
    sp.add_argument("--k", type=int, default=5, help="Number of results per book")
    sp.add_argument("--books", help="Comma-separated book titles to restrict to")

    # tui
    sp = sub.add_parser("tui", help="Open the interactive Textual TUI")
    sp.add_argument(
        "--workers", type=int, default=8,
        help="Background ingest worker processes (default: 8)",
    )

    # gui (native desktop)
    sp = sub.add_parser("gui", help="Open the native desktop GUI")
    sp.add_argument(
        "--workers", type=int, default=8,
        help="Background ingest worker processes (default: 8)",
    )

    # worker (standalone daemon)
    sp = sub.add_parser("worker", help="Run a standalone ingestion daemon watching an inbox")
    sp.add_argument("--inbox", type=Path, default=Path("~/.learnage/inbox").expanduser(), help="Folder to watch")
    sp.add_argument("--workers", type=int, default=8, help="Worker processes")

    return p


def _resolve_preset(args: argparse.Namespace) -> Preset:
    name = args.preset or default_preset_name()
    p = load_preset(name)
    return p.with_overrides(
        llm=args.llm or p.llm,
        embed=args.embed or p.embed,
        retrieval_k=args.k or p.retrieval_k,
    )


def _open_store(args: argparse.Namespace) -> tuple[Path, Library, VectorStore]:
    home = ensure_home(args.home or default_home())
    library = Library(library_db_path(home))
    # VectorStore needs an Ollama client — but we don't have one yet here,
    # so build a temporary one and reassign later. Cleaner: pass ollama in.
    # We'll set it lazily below.
    return home, library, None  # type: ignore[return-value]


def cmd_ingest(args: argparse.Namespace, console: Console, preset: Preset, ollama: OllamaClient, home: Path) -> int:
    library = Library(library_db_path(home))
    vectors = VectorStore(vectors_dir(home), ollama=ollama, embed_model=preset.embed)
    results = ingest_paths(
        args.paths,
        library=library,
        vectors=vectors,
        ollama=ollama,
        preset=preset,
        console=console,
        overwrite=args.overwrite,
        skip_soul=args.no_soul,
    )
    table = Table(title="Ingest results", show_lines=False)
    table.add_column("title")
    table.add_column("id", style="dim")
    table.add_column("chunks", justify="right")
    table.add_column("soul", justify="center")
    table.add_column("note", style="dim")
    for r in results:
        soul_mark = {"ok": "✓", "failed": "✗", "pending": "·", "skipped": "·"}.get(r.soul_status, r.soul_status)
        table.add_row(r.title, r.book_id or "-", str(r.chunks), soul_mark, r.reason or "")
    console.print(table)
    library.close()
    return 0


def cmd_library(_args: argparse.Namespace, console: Console, _preset: Preset, _ollama: OllamaClient, home: Path) -> int:
    library = Library(library_db_path(home))
    books = library.list_books()
    if not books:
        console.print("[dim]no books yet — try:[/dim] learnage ingest path/to/book.epub")
        library.close()
        return 0
    table = Table(title="Your library", show_lines=False)
    table.add_column("title", style="bold")
    table.add_column("author")
    table.add_column("chunks", justify="right")
    table.add_column("soul", justify="center")
    table.add_column("ingested", style="dim")
    for b in books:
        soul_mark = {"ok": "✓", "failed": "✗", "pending": "·"}.get(b.soul_status or "", "?")
        table.add_row(
            b.title,
            b.author or "—",
            str(b.chunk_count or 0),
            soul_mark,
            b.ingested_at,
        )
    console.print(table)
    library.close()
    return 0


def cmd_show(args: argparse.Namespace, console: Console, _preset: Preset, _ollama: OllamaClient, home: Path) -> int:
    library = Library(library_db_path(home))
    book = library.find_by_title(args.title)
    if not book:
        console.print(f"[red]no book matches {args.title!r}[/red]")
        library.close()
        return 1
    console.rule(book.title + (f" — by {book.author}" if book.author else ""))
    if not book.soul_json:
        console.print("[dim](no soul — re-ingest the book to generate one)[/dim]")
        library.close()
        return 0
    try:
        soul = SoulRecord.from_json(book.soul_json)
    except Exception as e:  # noqa: BLE001
        console.print(f"[red]soul parse error:[/red] {e}")
        library.close()
        return 1
    console.print_json(soul.to_json())
    library.close()
    return 0


def cmd_forget(args: argparse.Namespace, console: Console, preset: Preset, ollama: OllamaClient, home: Path) -> int:
    library = Library(library_db_path(home))
    book = library.find_by_title(args.title)
    if not book:
        console.print(f"[red]no book matches {args.title!r}[/red]")
        library.close()
        return 1
    vectors = VectorStore(vectors_dir(home), ollama=ollama, embed_model=preset.embed)
    vectors.drop(book.id)
    library.delete_book(book.id)
    console.print(f"[green]✓[/green] forgot {book.title} ({book.id})")
    library.close()
    return 0


def cmd_read(args: argparse.Namespace, console: Console, preset: Preset, ollama: OllamaClient, home: Path) -> int:
    library = Library(library_db_path(home))
    vectors = VectorStore(vectors_dir(home), ollama=ollama, embed_model=preset.embed)
    try:
        run_session(
            args.books,
            library=library,
            vectors=vectors,
            ollama=ollama,
            preset=preset,
            console=console,
        )
    finally:
        library.close()
    return 0


def cmd_doctor(_args: argparse.Namespace, console: Console, preset: Preset, ollama: OllamaClient, home: Path) -> int:
    console.rule("Ollama")
    if ollama.ping():
        console.print("[green]✓[/green] reachable at", ollama.base_url)
        models = ollama.list_models()
        have = lambda n: any(m == n or m.split(":")[0] == n.split(":")[0] for m in models)
        for label, name in [("embed", preset.embed), ("llm", preset.llm), ("soul", preset.soul_model)]:
            mark = "[green]✓[/green]" if have(name) else "[red]✗[/red]"
            console.print(f"  {mark} {label}: {name}")
    else:
        console.print(f"[red]✗[/red] Ollama unreachable at {ollama.base_url}")

    console.rule("Library")
    library = Library(library_db_path(home))
    books = library.list_books()
    console.print(f"[green]✓[/green] db at {library_db_path(home)} — {len(books)} book(s)")
    library.close()
    console.print(f"[green]✓[/green] vectors at {vectors_dir(home)}")
    return 0


def cmd_search(args: argparse.Namespace, console: Console, preset: Preset, ollama: OllamaClient, home: Path) -> int:
    from learnage.store.vectors import VectorStore
    from learnage.interviewer.retriever import Passage, retrieve

    library = Library(library_db_path(home))
    vectors = VectorStore(vectors_dir(home), ollama=ollama, embed_model=preset.embed)

    # Resolve book IDs
    restrict_ids: list[str] | None = None
    if args.books:
        titles = [t.strip() for t in args.books.split(",")]
        restrict_ids = []
        for title in titles:
            book = library.find_by_title(title)
            if book:
                restrict_ids.append(book.id)
            else:
                console.print(f"[yellow]no book matches:[/yellow] {title}")

    if restrict_ids is None:
        restrict_ids = [b.id for b in library.list_books() if b.chunk_count and b.chunk_count > 0]

    if not restrict_ids:
        console.print("[yellow]no books to search[/yellow]")
        library.close()
        return 0

    results: list[Passage] = retrieve(
        args.query,
        book_ids=restrict_ids,
        vectors=vectors,
        preset=preset,
    )

    if not results:
        console.print("[dim]no results found[/dim]")
        library.close()
        return 0

    # Group by book
    by_book: dict[str, list[Passage]] = {}
    for r in results:
        by_book.setdefault(r.book_id, []).append(r)

    for book_id, passages in by_book.items():
        book = library.get_book(book_id)
        title = book.title if book else book_id
        console.print(f"\n[bold accent]{title}[/bold accent]")
        if book and book.author:
            console.print(f"  [dim]{book.author}[/dim]")
        for i, r in enumerate(passages, 1):
            snippet = r.text[:300].replace("\n", " ").strip()
            console.print(f"  [{i}] {snippet}{'…' if len(r.text) > 300 else ''}")
            if r.chapter:
                console.print(f"      [dim]— {r.chapter}[/dim]")

    console.print(f"\n[dim]{len(results)} result(s) across {len(by_book)} book(s)[/dim]")
    library.close()
    return 0


def cmd_tui(args: argparse.Namespace, _console: Console, preset: Preset, _ollama: OllamaClient, home: Path) -> int:
    from learnage.tui.app import run_tui

    run_tui(preset_name=preset.name, workers=args.workers, home=home)
    return 0


def cmd_gui(args: argparse.Namespace, _console: Console, preset: Preset, _ollama: OllamaClient, home: Path) -> int:
    from learnage.gui.app import run_gui

    return run_gui(preset_name=preset.name, workers=args.workers, home=home)


def cmd_worker(args: argparse.Namespace, _console: Console, preset: Preset, _ollama: OllamaClient, home: Path) -> int:
    from learnage.worker import run_daemon

    inbox = args.inbox.expanduser().resolve()
    inbox.mkdir(parents=True, exist_ok=True)
    run_daemon(inbox, preset=preset, home=home, workers=args.workers)
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    console = Console()
    preset = _resolve_preset(args)
    home = ensure_home(args.home or default_home())
    ollama = OllamaClient()
    try:
        if args.cmd == "ingest":
            return cmd_ingest(args, console, preset, ollama, home)
        if args.cmd == "library":
            return cmd_library(args, console, preset, ollama, home)
        if args.cmd == "show":
            return cmd_show(args, console, preset, ollama, home)
        if args.cmd == "forget":
            return cmd_forget(args, console, preset, ollama, home)
        if args.cmd == "read":
            return cmd_read(args, console, preset, ollama, home)
        if args.cmd == "doctor":
            return cmd_doctor(args, console, preset, ollama, home)
        if args.cmd == "search":
            return cmd_search(args, console, preset, ollama, home)
        if args.cmd == "tui":
            return cmd_tui(args, console, preset, ollama, home)
        if args.cmd == "gui":
            return cmd_gui(args, console, preset, ollama, home)
        if args.cmd == "worker":
            return cmd_worker(args, console, preset, ollama, home)
    except OllamaError as e:
        console.print(f"[red]Ollama error:[/red] {e}")
        return 2
    finally:
        ollama.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
