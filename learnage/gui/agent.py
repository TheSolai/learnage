"""Agentic chat — Learnage can take actions via Ollama function calling.

The LLM is given a tool list and decides when to call them. Each tool is a
real Learnage operation (search, ingest, generate soul, etc.). Results flow
back into the conversation and the model continues until it has enough to
answer.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal

from learnage.config import Preset
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Book, Library
from learnage.store.soul import SoulRecord
from learnage.store.vectors import VectorStore


# --------------------------------------------------------------- tool registry


@dataclass
class ToolCall:
    name: str
    arguments: dict[str, Any]
    result: Any = None
    error: str | None = None
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None


# --------------------------------------------------------------- tools


def _tool_search_library(
    library: Library, vectors: VectorStore, preset: Preset, restrict: list[str] | None = None
) -> Callable:
    def f(query: str, k: int = 5) -> dict:
        from learnage.interviewer.retriever import retrieve

        if restrict is not None:
            book_ids = restrict
        else:
            book_ids = [b.id for b in library.list_books()]
        passages = retrieve(query, book_ids=book_ids, vectors=vectors, preset=preset)
        passages = passages[:k]
        return {
            "query": query,
            "results": [
                {
                    "book_id": p.book_id,
                    "chunk_index": p.chunk_index,
                    "chapter": p.chapter,
                    "score": round(p.score, 3),
                    "text": p.text[:500],
                }
                for p in passages
            ],
        }

    return f


def _tool_list_books(library: Library, restrict: list[str] | None = None) -> Callable:
    def f(query: str | None = None, limit: int = 50) -> dict:
        if restrict is not None:
            all_books = {b.id: b for b in library.list_books()}
            books = [all_books[bid] for bid in restrict if bid in all_books]
        else:
            books = library.list_books()
        if query:
            q = query.lower()
            books = [b for b in books if q in b.title.lower() or q in (b.author or "").lower()]
        return {
            "count": len(books),
            "books": [
                {
                    "id": b.id,
                    "title": b.title,
                    "author": b.author,
                    "chunks": b.chunk_count,
                    "soul_status": b.soul_status,
                }
                for b in books[:limit]
            ],
        }

    return f


def _tool_read_soul(library: Library, restrict: list[str] | None = None) -> Callable:
    def f(book_id: str | None = None, title: str | None = None) -> dict:
        b: Book | None = None
        if book_id:
            b = library.get_book(book_id)
        elif title:
            b = library.find_by_title(title)
        if not b:
            return {"error": f"no book matches {book_id or title}"}
        if restrict is not None and b.id not in restrict:
            return {"error": "that book is not in this interview"}
        if not b.soul_json:
            return {"title": b.title, "soul": None, "note": "no soul yet"}
        try:
            soul = SoulRecord.from_json(b.soul_json)
            return {
                "title": b.title,
                "author": b.author,
                "summary": soul.summary,
                "voice": soul.voice,
                "themes": soul.themes,
                "characters": soul.characters,
                "plot": soul.plot,
                "key_passages": soul.key_passages,
                "craft_notes": soul.craft_notes,
            }
        except Exception as e:  # noqa: BLE001
            return {"error": f"soul parse failed: {e}"}

    return f


def _tool_ingest(on_submit: Callable[[list[Path], bool], list[int]]) -> Callable:
    """Returns a function that the LLM calls; we delegate to the GUI's ingest pool.

    Security: restricts paths to the user's home tree to prevent traversal attacks.
    """

    _SAFE_ROOTS = [
        Path.home(),
        Path.home() / "Downloads",
        Path.home() / "Documents",
    ]

    def f(paths: list[str], skip_soul: bool = True) -> dict:
        ps = []
        for p in paths:
            try:
                pp = Path(p).expanduser().resolve()
            except Exception:
                continue
            # Path must be within a safe root (no traversal outside home)
            if not any(str(pp).startswith(str(root)) for root in _SAFE_ROOTS):
                continue
            if pp.is_dir():
                for ext in ("epub", "pdf", "docx", "txt"):
                    for fpath in pp.rglob(f"*.{ext}"):
                        if any(str(fpath).startswith(str(r)) for r in _SAFE_ROOTS):
                            ps.append(fpath)
            elif pp.exists() and pp.is_file():
                ps.append(pp)
        if not ps:
            return {"error": "no valid files found (paths must be under ~/Downloads or ~/Documents)", "paths": paths}
        jids = on_submit(ps, skip_soul)
        return {
            "queued": len(jids),
            "files": [str(p) for p in ps[:20]],
            "job_ids": jids,
            "note": "ingest is async; ask the user to wait or check the Ingest tab",
        }

    return f


def _tool_generate_soul(library: Library, on_submit_soul: Callable[[str], None]) -> Callable:
    def f(book_id: str | None = None, title: str | None = None) -> dict:
        b: Book | None = None
        if book_id:
            b = library.get_book(book_id)
        elif title:
            b = library.find_by_title(title)
        if not b:
            return {"error": f"no book matches {book_id or title}"}
        on_submit_soul(b.id)
        return {"queued": True, "book": b.title, "note": "soul generation queued"}

    return f


def _tool_forget(library: Library, vectors: VectorStore) -> Callable:
    def f(book_id: str | None = None, title: str | None = None) -> dict:
        b: Book | None = None
        if book_id:
            b = library.get_book(book_id)
        elif title:
            b = library.find_by_title(title)
        if not b:
            return {"error": f"no book matches {book_id or title}"}
        vectors.drop(b.id)
        library.delete_book(b.id)
        return {"forgot": b.title, "id": b.id}

    return f


# --------------------------------------------------------------- tool schema


TOOL_SCHEMA: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "search_library",
            "description": (
                "Semantic search across every ingested book. Returns passages with "
                "book id, chapter, score, and a 500-char snippet. Use this when the "
                "user asks a question that requires evidence from the library."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "search query"},
                    "k": {"type": "integer", "default": 5},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_books",
            "description": "List ingested books. Use when you need to find a book or show what's in the library.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "optional filter on title/author"},
                    "limit": {"type": "integer", "default": 50},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_soul",
            "description": "Read a book's soul — themes, voice, characters, plot, key passages, craft notes.",
            "parameters": {
                "type": "object",
                "properties": {
                    "book_id": {"type": "string"},
                    "title": {"type": "string", "description": "title or substring"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ingest",
            "description": (
                "Ingest one or more book files into the library. Accepts paths to "
                "files or folders. Folders are walked for .epub/.pdf/.docx/.txt. "
                "Returns job ids so the user can watch progress. Async — they happen "
                "in the background."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "paths": {"type": "array", "items": {"type": "string"}},
                    "skip_soul": {"type": "boolean", "default": True},
                },
                "required": ["paths"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_soul",
            "description": "Queue soul (re-)generation for a book. Returns immediately; takes 30-60s in the background.",
            "parameters": {
                "type": "object",
                "properties": {
                    "book_id": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "forget",
            "description": "Remove a book from the library and delete its vectors. Cannot be undone.",
            "parameters": {
                "type": "object",
                "properties": {
                    "book_id": {"type": "string"},
                    "title": {"type": "string"},
                },
            },
        },
    },
]


# --------------------------------------------------------------- runner


class _AgentSignals(QObject):
    token = Signal(str)
    tool_call_started = Signal(object)    # ToolCall
    tool_call_finished = Signal(object)   # ToolCall
    final = Signal(str)                   # final assistant message
    error = Signal(str)


class AgentRunner(QRunnable):
    """Run an agentic chat turn. Streams tokens; reports tool calls as cards."""

    MAX_TOOL_ROUNDS = 4  # safety cap on tool-use loops

    def __init__(
        self,
        question: str,
        history: list[dict],
        preset: Preset,
        ollama: OllamaClient,
        library: Library,
        vectors: VectorStore,
        on_submit_ingest: Callable[[list[Path], bool], list[int]],
        on_submit_soul: Callable[[str], None],
        restrict_book_ids: list[str] | None = None,
    ) -> None:
        super().__init__()
        self.question = question
        self.history = history
        self.preset = preset
        self.ollama = ollama
        self.library = library
        self.vectors = vectors
        self.on_submit_ingest = on_submit_ingest
        self.on_submit_soul = on_submit_soul
        self.restrict_book_ids = restrict_book_ids
        self.signals = _AgentSignals()

    def run(self) -> None:
        try:
            self._run()
        except Exception as e:  # noqa: BLE001
            self.signals.error.emit(f"{type(e).__name__}: {e}")

    def _run(self) -> None:
        tools = self._build_tools()
        # System prompt varies depending on whether we're scoped to a single book
        if self.restrict_book_ids:
            # Per-book interview — strong context
            book_titles: list[str] = []
            book_meta_lines: list[str] = []
            book_soul_lines: list[str] = []
            for bid in self.restrict_book_ids:
                b = self.library.get_book(bid)
                if b:
                    book_titles.append(b.title)
                    author = f" by {b.author}" if b.author else ""
                    book_meta_lines.append(f"- {b.title}{author}")
                    if b.soul_json:
                        try:
                            from learnage.store.soul import SoulRecord
                            soul = SoulRecord.from_json(b.soul_json)
                            if soul.summary:
                                book_soul_lines.append(f"  Summary: {soul.summary[:300]}")
                            if soul.themes:
                                themes = ", ".join(t.get("name", "") for t in soul.themes[:5])
                                book_soul_lines.append(f"  Themes: {themes}")
                        except Exception:  # noqa: BLE001
                            pass
            book_list = "\n".join(book_meta_lines) if book_meta_lines else "(unknown)"
            soul_block = ("\n" + "\n".join(book_soul_lines)) if book_soul_lines else ""
            title_str = ", ".join(book_titles) if book_titles else "this book"
            system = (
                f"You are Learnage, the user's local book interviewer.\n\n"
                f"You are currently interviewing **{title_str}**:\n"
                f"{book_list}{soul_block}\n\n"
                f"RULES — read carefully:\n"
                f"1. ALWAYS call `search_library` with the user's question BEFORE answering.\n"
                f"   Do not answer from general knowledge. The user wants evidence from the book.\n"
                f"2. Cite every passage you use with [book_title — chapter] markers.\n"
                f"3. If the book doesn't address the question, say so plainly — do NOT invent.\n"
                f"4. Be concise but specific. Quote the book when wording matters.\n"
                f"5. Speak casually; you're a colleague, not a professor."
            )
        else:
            # Global chat — reads across the whole library
            n = len(self.library.list_books())
            system = (
                f"You are Learnage, the user's local book interviewer.\n\n"
                f"You have access to a library of {n} ingested books.\n\n"
                f"RULES:\n"
                f"1. ALWAYS call `search_library` with the user's question BEFORE answering.\n"
                f"2. Cite every passage with [book_title — chapter] markers.\n"
                f"3. When the user asks about a specific book, also call `read_soul` for context.\n"
                f"4. Be concise but specific. Quote the book when wording matters.\n"
                f"5. Speak casually; you're a colleague, not a professor."
            )
        messages: list[dict] = [{"role": "system", "content": system}]
        # Bring recent history
        messages.extend(self.history[-10:])

        # PRE-SEARCH for the user's question when in per-book mode.
        # Inject the top passages directly so the model has the context
        # without needing to call a tool (and to guarantee the answer is grounded).
        user_msg = self.question
        if self.restrict_book_ids:
            try:
                from learnage.interviewer.retriever import retrieve
                passages = retrieve(
                    self.question,
                    book_ids=self.restrict_book_ids,
                    vectors=self.vectors,
                    preset=self.preset,
                )
                if passages:
                    ctx_lines = []
                    for p in passages[:5]:
                        title = self.library.get_book(p.book_id)
                        title_str = title.title if title else p.book_id
                        ch = f" — {p.chapter}" if p.chapter else ""
                        ctx_lines.append(f"[{title_str}{ch}] {p.text[:600]}")
                    context = "\n\n".join(ctx_lines)
                    user_msg = (
                        f"{self.question}\n\n"
                        f"— Retrieved passages —\n{context}"
                    )
            except Exception:  # noqa: BLE001
                pass

        messages.append({"role": "user", "content": user_msg})

        for _ in range(self.MAX_TOOL_ROUNDS + 1):
            stream = self.ollama.chat(
                model=self.preset.llm,
                messages=messages,
                stream=True,
                tools=TOOL_SCHEMA,
            )

            content_buf: list[str] = []
            tool_calls: dict[int, dict] = {}  # idx -> {name, arguments}
            final_text = ""

            for event in stream:
                msg = event.get("message") or {}
                chunk = msg.get("content", "")
                if chunk:
                    content_buf.append(chunk)
                    self.signals.token.emit(chunk)

                # Tool calls
                if msg.get("tool_calls"):
                    for tc in msg["tool_calls"]:
                        idx = tc.get("index", 0)
                        entry = tool_calls.setdefault(idx, {"name": "", "arguments": ""})
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            entry["name"] = fn["name"]
                        if fn.get("arguments"):
                            entry["arguments"] += fn["arguments"]

                if event.get("done"):
                    # Some Ollama versions put tool_calls on the final message
                    if msg.get("tool_calls"):
                        for tc in msg["tool_calls"]:
                            idx = tc.get("index", 0)
                            entry = tool_calls.setdefault(idx, {"name": "", "arguments": ""})
                            fn = tc.get("function") or {}
                            if fn.get("name"):
                                entry["name"] = fn["name"]
                            if fn.get("arguments"):
                                entry["arguments"] += fn["arguments"]
                    final_text = "".join(content_buf)
                    break

            # If no tool calls, we're done.
            if not tool_calls:
                self.signals.final.emit(final_text or "".join(content_buf))
                return

            # Append the assistant message (text + tool_calls) to the conversation.
            assistant_msg: dict = {"role": "assistant", "content": "".join(content_buf)}
            # Re-shape tool_calls into a list.
            tcs = []
            for idx, tc in tool_calls.items():
                try:
                    args = json.loads(tc["arguments"]) if tc["arguments"] else {}
                except Exception:  # noqa: BLE001
                    args = {"_raw": tc["arguments"]}
                tcs.append(
                    {
                        "id": f"call_{idx}",
                        "type": "function",
                        "function": {"name": tc["name"], "arguments": json.dumps(args)},
                    }
                )
            assistant_msg["tool_calls"] = tcs
            messages.append(assistant_msg)

            # Execute each tool call.
            for tc in tcs:
                name = tc["function"]["name"]
                args = json.loads(tc["function"]["arguments"])
                call = ToolCall(name=name, arguments=args)
                self.signals.tool_call_started.emit(call)
                try:
                    fn = tools.get(name)
                    if not fn:
                        call.result = {"error": f"unknown tool: {name}"}
                        call.error = call.result["error"]
                    else:
                        call.result = fn(**args)
                        if isinstance(call.result, dict) and "error" in call.result:
                            call.error = call.result["error"]
                except Exception as e:  # noqa: BLE001
                    call.error = f"{type(e).__name__}: {e}"
                    call.result = {"error": call.error}
                call.finished_at = time.time()
                self.signals.tool_call_finished.emit(call)
                messages.append(
                    {
                        "role": "tool",
                        "content": json.dumps(call.result, default=str)[:4000],
                    }
                )

        # Out of rounds — give up gracefully.
        self.signals.final.emit("(I used my tool budget — try asking again.)")

    def _build_tools(self) -> dict[str, Callable]:
        restrict = self.restrict_book_ids
        return {
            "search_library": _tool_search_library(self.library, self.vectors, self.preset, restrict),
            "list_books": _tool_list_books(self.library, restrict),
            "read_soul": _tool_read_soul(self.library, restrict),
            "ingest": _tool_ingest(self.on_submit_ingest),
            "generate_soul": _tool_generate_soul(self.library, self.on_submit_soul),
            "forget": _tool_forget(self.library, self.vectors),
        }
