"""REPL interview session."""

from __future__ import annotations

import sys
import uuid
from dataclasses import dataclass, field
from typing import Iterator

from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.prompt import Prompt

from learnage.config import Preset
from learnage.interviewer.prompter import compose
from learnage.interviewer.retriever import Passage, retrieve
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Book, Library
from learnage.store.soul import SoulRecord
from learnage.store.vectors import VectorStore


@dataclass
class Session:
    session_id: str
    books: list[Book] = field(default_factory=list)
    souls: dict[str, SoulRecord | None] = field(default_factory=dict)
    history: list[dict] = field(default_factory=list)
    last_passages: list[Passage] = field(default_factory=list)

    def reset(self) -> None:
        self.history = []
        self.last_passages = []


def _load_souls(books: list[Book], library: Library) -> dict[str, SoulRecord | None]:
    out: dict[str, SoulRecord | None] = {}
    for b in books:
        if b.soul_json:
            try:
                out[b.id] = SoulRecord.from_json(b.soul_json)
            except Exception:  # noqa: BLE001
                out[b.id] = None
        else:
            out[b.id] = None
    return out


def _resolve_books(spec: str, library: Library) -> list[Book]:
    """Resolve a comma-separated title spec to a list of Book records."""
    out: list[Book] = []
    for raw in spec.split(","):
        title = raw.strip()
        if not title:
            continue
        b = library.find_by_title(title)
        if not b:
            raise SystemExit(f"No book matches {title!r}. Run `learnage library` to see ingested books.")
        out.append(b)
    return out


def _stream_answer(
    ollama: OllamaClient,
    *,
    model: str,
    messages: list[dict],
) -> Iterator[str]:
    """Stream the LLM's reply token by token. Yields chunks of text."""
    stream = ollama.chat(model=model, messages=messages, stream=True)
    if not hasattr(stream, "__iter__"):
        # Defensive: client returned a final dict for some reason.
        msg = (stream.get("message") or {}).get("content", "") if isinstance(stream, dict) else ""
        if msg:
            yield msg
        return
    for event in stream:
        msg = event.get("message") or {}
        chunk = msg.get("content", "")
        if chunk:
            yield chunk
        if event.get("done"):
            break


def run_session(
    spec: str,
    *,
    library: Library,
    vectors: VectorStore,
    ollama: OllamaClient,
    preset: Preset,
    console: Console,
) -> None:
    """Run a REPL interview against one or more books."""
    books = _resolve_books(spec, library)
    souls = _load_souls(books, library)
    session = Session(
        session_id=uuid.uuid4().hex[:12],
        books=books,
        souls=souls,
    )
    library.create_session(session.session_id, [b.id for b in books])

    titles = ", ".join(b.title for b in books)
    console.print(
        Panel.fit(
            f"[bold]Learnage[/bold] · interviewing [cyan]{titles}[/cyan]\n"
            f"session: {session.session_id} · model: {preset.llm} · k={preset.retrieval_k}\n"
            f"type /help for commands",
            border_style="cyan",
        )
    )

    while True:
        try:
            raw = Prompt.ask("[bold green]learnage[/bold green] ›").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            break

        if not raw:
            continue

        if raw.startswith("/"):
            cmd = raw[1:].strip().split()
            action = cmd[0] if cmd else ""
            if action in ("quit", "exit", "q"):
                break
            if action == "help":
                _print_help(console)
                continue
            if action == "clear":
                session.reset()
                console.print("[dim]conversation cleared[/dim]")
                continue
            if action == "soul":
                _cmd_soul(cmd[1:], session, console)
                continue
            if action == "passages":
                _cmd_passages(session, console)
                continue
            if action == "sources":
                _cmd_sources(session, library, console)
                continue
            if action == "books":
                console.print("\n".join(f"• {b.title}" for b in session.books))
                continue
            console.print(f"[red]unknown command:[/red] /{action}  (try /help)")
            continue

        # Regular question — retrieve, compose, stream, persist.
        session.last_passages = retrieve(
            raw,
            book_ids=[b.id for b in session.books],
            vectors=vectors,
            preset=preset,
        )
        messages = compose(
            question=raw,
            books=session.books,
            souls=session.souls,
            passages=session.last_passages,
            history=session.history,
        )
        library.append_message(session.session_id, "user", raw)

        # Stream into a Live panel.
        answer_parts: list[str] = []
        try:
            console.print()
            with Live(Markdown(""), console=console, refresh_per_second=20) as live:
                rendered = ""
                for chunk in _stream_answer(
                    ollama, model=preset.llm, messages=messages
                ):
                    answer_parts.append(chunk)
                    rendered += chunk
                    live.update(Markdown(rendered))
                console.print()
        except Exception as e:  # noqa: BLE001
            console.print(f"[red]error:[/red] {e}")
            continue

        answer = "".join(answer_parts)
        session.history.append({"role": "user", "content": raw})
        session.history.append({"role": "assistant", "content": answer})
        citations = [
            {"book_id": p.book_id, "chunk_index": p.chunk_index, "score": p.score}
            for p in session.last_passages
        ]
        library.append_message(
            session.session_id, "assistant", answer, citations=citations
        )

    library.end_session(session.session_id)


# ---------------------------------------------------------------------- /cmd


def _print_help(console: Console) -> None:
    console.print(
        "[dim]/help                show this help\n"
        "/soul                 show the soul of every book in session\n"
        "/soul <book> themes   narrow part\n"
        "/passages             show passages used for the last answer\n"
        "/sources              show sources (book + chunk) for the last answer\n"
        "/books                list books in this session\n"
        "/clear                clear conversation history\n"
        "/quit                 leave the session[/dim]"
    )


def _cmd_soul(args: list[str], session: Session, console: Console) -> None:
    if not args:
        for b in session.books:
            console.rule(b.title)
            s = session.souls.get(b.id)
            if not s:
                console.print("[dim](no soul — re-ingest with a soul-capable model)[/dim]")
                continue
            console.print(s.short_brief(max_chars=4000))
        return

    # /soul <book-substring> [section]
    target = " ".join(args[:-1]) if len(args) > 1 else args[0]
    section = args[-1] if len(args) > 1 else None
    matches = [b for b in session.books if target.lower() in b.title.lower()]
    if not matches:
        console.print(f"[red]no book in session matches {target!r}[/red]")
        return
    for b in matches:
        s = session.souls.get(b.id)
        if not s:
            console.print("[dim](no soul)[/dim]")
            continue
        if section:
            data = s.to_json()
            console.print(data)  # raw JSON; user asked for a section
        else:
            console.rule(b.title)
            console.print(s.short_brief(max_chars=4000))


def _cmd_passages(session: Session, console: Console) -> None:
    if not session.last_passages:
        console.print("[dim](no passages — ask a question first)[/dim]")
        return
    for i, p in enumerate(session.last_passages, 1):
        head = f"[p{i}] {p.book_id}"
        if p.chapter:
            head += f" — {p.chapter}"
        head += f"  (score={p.score:.2f})"
        console.rule(head)
        console.print(p.text)


def _cmd_sources(session: Session, library: Library, console: Console) -> None:
    if not session.last_passages:
        console.print("[dim](no sources — ask a question first)[/dim]")
        return
    title_by_id = {b.id: b.title for b in library.list_books()}
    for i, p in enumerate(session.last_passages, 1):
        title = title_by_id.get(p.book_id, p.book_id)
        console.print(
            f"[p{i}] [cyan]{title}[/cyan] · chunk {p.chunk_index}"
            + (f" · {p.chapter}" if p.chapter else "")
            + f" · score={p.score:.2f}"
        )
