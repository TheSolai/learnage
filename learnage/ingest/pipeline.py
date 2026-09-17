"""End-to-end ingestion pipeline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn

from learnage.config import Preset
from learnage.ingest.chunker import chunk_book
from learnage.ingest.parsers import detect_format, parse
from learnage.llm.ollama import OllamaClient
from learnage.soul.analyzer import analyze_soul
from learnage.store.library import Book, Library
from learnage.store.vectors import VectorStore
from learnage.util.hash import book_id, file_hash


@dataclass
class IngestResult:
    book_id: str
    title: str
    chunks: int
    soul_status: str
    skipped: bool = False
    reason: str | None = None


def ingest_path(
    path: Path,
    *,
    library: Library,
    vectors: VectorStore,
    ollama: OllamaClient,
    preset: Preset,
    console: Console | None = None,
    overwrite: bool = False,
    skip_soul: bool = False,
) -> IngestResult:
    """Ingest a single file. Idempotent on file hash unless overwrite=True."""
    console = console or Console()
    path = Path(path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(path)

    fmt = detect_format(path)
    src_hash = file_hash(path)
    existing = library.find_by_hash(src_hash)

    if existing and not overwrite:
        return IngestResult(
            book_id=existing.id,
            title=existing.title,
            chunks=existing.chunk_count or 0,
            soul_status=existing.soul_status or "ok",
            skipped=True,
            reason="already ingested (same hash)",
        )

    bid = book_id(src_hash)
    console.print(f"[bold]→[/bold] parsing {path.name}")
    parsed = parse(path)

    console.print(
        f"[dim]   {fmt} · {len(parsed.chapters)} chapter(s) · "
        f"{len(parsed.full_text):,} chars[/dim]"
    )

    chapters = [(c.heading, c.text) for c in parsed.chapters]
    chunks = chunk_book(
        chapters,
        target_tokens=preset.chunk_target_tokens,
        overlap_tokens=preset.chunk_overlap_tokens,
    )
    console.print(f"[dim]   {len(chunks)} chunk(s) · ~{sum(c.token_estimate for c in chunks):,} tokens[/dim]")

    # Replace any prior chunks/vectors for this book id.
    vectors.drop(bid)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        console=console,
        transient=True,
    ) as progress:
        task = progress.add_task("embedding", total=len(chunks))
        vectors.add_chunks(
            bid,
            chunks,
            on_progress=lambda done, total: progress.update(task, completed=done),
        )

    # Persist metadata + chunks meta.
    import time as _t
    book_record = Book(
        id=bid,
        title=parsed.title,
        author=parsed.author,
        source_path=str(path),
        source_format=fmt,
        source_hash=src_hash,
        byte_size=path.stat().st_size,
        char_count=len(parsed.full_text),
        chunk_count=len(chunks),
        ingested_at=_t.strftime("%Y-%m-%dT%H:%M:%S"),
        soul_json=None,
        soul_generated_at=None,
        soul_status="pending",
    )
    library.upsert_book(book_record)
    library.replace_chunks(
        bid,
        [
            (i, c.chapter, c.char_start, c.char_end, c.token_estimate)
            for i, c in enumerate(chunks)
        ],
    )

    # Soul analysis (best-effort).
    if skip_soul:
        library.set_soul(bid, "{}", status="skipped")
        soul_status = "skipped"
        console.print(f"[dim]   soul skipped (--no-soul)[/dim]")
    else:
        console.print(f"[bold]→[/bold] analyzing soul with {preset.soul_model}")
        try:
            soul = analyze_soul(
                title=parsed.title,
                author=parsed.author,
                chunks=chunks,
                client=ollama,
                model=preset.soul_model,
                max_input_chars=preset.soul_max_input_chars,
            )
            library.set_soul(bid, soul.to_json(), status="ok")
            console.print(f"[green]✓[/green] soul ready")
            soul_status = "ok"
        except Exception as e:  # noqa: BLE001
            console.print(f"[yellow]![/yellow] soul analysis failed: {e}")
            library.set_soul(bid, "{}", status="failed")
            soul_status = "failed"

    return IngestResult(
        book_id=bid,
        title=parsed.title,
        chunks=len(chunks),
        soul_status=soul_status,
    )


def ingest_paths(
    paths: list[Path],
    *,
    library: Library,
    vectors: VectorStore,
    ollama: OllamaClient,
    preset: Preset,
    console: Console | None = None,
    overwrite: bool = False,
    skip_soul: bool = False,
) -> list[IngestResult]:
    """Ingest a list of files; directories are walked for supported formats."""
    console = console or Console()
    targets: list[Path] = []
    for p in paths:
        p = Path(p).expanduser().resolve()
        if p.is_dir():
            for ext in ("epub", "pdf", "docx", "txt"):
                targets.extend(p.rglob(f"*.{ext}"))
        elif p.exists():
            targets.append(p)
    targets.sort()
    results: list[IngestResult] = []
    for t in targets:
        try:
            results.append(
                ingest_path(
                    t,
                    library=library,
                    vectors=vectors,
                    ollama=ollama,
                    preset=preset,
                    console=console,
                    overwrite=overwrite,
                    skip_soul=skip_soul,
                )
            )
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]✗[/red] {t}: {e}")
            results.append(
                IngestResult(book_id="", title=t.name, chunks=0, soul_status="failed", reason=str(e))
            )
    return results
