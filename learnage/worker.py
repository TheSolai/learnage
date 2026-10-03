"""Background ingestion worker.

Runs as either:
- An embedded pool inside the TUI (ProcessPoolExecutor + asyncio)
- A standalone daemon process (`learnage worker`) that polls an inbox folder

The unit of work is `_run_job`, which is a top-level picklable function so it
can run in a subprocess.
"""

from __future__ import annotations

import asyncio
import multiprocessing as mp
import os
import queue
import time
import traceback
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from learnage.config import Preset


# --------------------------------------------------------------- job model


@dataclass
class IngestJob:
    path: str
    skip_soul: bool = True
    overwrite: bool = False
    # Optional category/tags hints — applied to the Book after ingest
    category: str | None = None
    tags: list[str] | None = None

    @property
    def display_name(self) -> str:
        return os.path.basename(self.path)


@dataclass
class JobStatus:
    job: IngestJob
    state: str = "queued"  # queued|running|done|failed
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    chunks: int = 0
    soul_status: Optional[str] = None
    error: Optional[str] = None
    traceback: Optional[str] = None


# --------------------------------------------------------------- worker fn


def _run_job(job_dict: dict, preset_dict: dict, home_str: str) -> dict:
    """Subprocess entry point — picklable; constructs its own clients.

    Returns a JSON-serializable dict describing the result.
    """
    import asyncio as _asyncio
    from learnage.config import Preset
    from learnage.ingest.chunker import chunk_book
    from learnage.ingest.parsers import detect_format, parse
    from learnage.llm.ollama import OllamaClient
    from learnage.soul.analyzer import analyze_soul
    from learnage.store.library import Book, Library
    from learnage.store.vectors import VectorStore
    from learnage.util.hash import book_id, file_hash
    from learnage.util.paths import library_db_path, vectors_dir

    job = IngestJob(**job_dict)
    preset = Preset(**preset_dict)
    home = Path(home_str)

    result: dict = {
        "path": job.path,
        "state": "running",
        "started_at": time.time(),
    }

    library = Library(library_db_path(home))
    ollama = OllamaClient()
    vectors = VectorStore(vectors_dir(home), ollama=ollama, embed_model=preset.embed)

    try:
        path = Path(job.path).expanduser().resolve()
        if not path.exists():
            raise FileNotFoundError(str(path))

        fmt = detect_format(path)
        src_hash = file_hash(path)
        existing = library.find_by_hash(src_hash)
        if existing and not job.overwrite:
            result.update(
                state="done",
                finished_at=time.time(),
                chunks=existing.chunk_count or 0,
                soul_status=existing.soul_status or "ok",
                skipped=True,
            )
            return result

        bid = book_id(src_hash)
        parsed = parse(path)
        chapters = [(c.heading, c.text) for c in parsed.chapters]
        chunks = chunk_book(
            chapters,
            target_tokens=preset.chunk_target_tokens,
            overlap_tokens=preset.chunk_overlap_tokens,
        )

        vectors.drop(bid)

        # Async embed + add
        async def _do_embed() -> None:
            if not chunks:
                return
            texts = [c.text for c in chunks]
            vecs = await ollama.embed_batch_async(
                preset.embed, texts, concurrency=16
            )
            coll = vectors.get_or_create(bid)
            ids = [f"{bid}:{i}" for i in range(len(chunks))]
            metas = [
                {"book_id": bid, "chunk_index": i, "chapter": c.chapter or ""}
                for i, c in enumerate(chunks)
            ]
            coll.add(ids=ids, embeddings=vecs, documents=texts, metadatas=metas)

        _asyncio.run(_do_embed())

        record = Book(
            id=bid,
            title=parsed.title,
            author=parsed.author,
            source_path=str(path),
            source_format=fmt,
            source_hash=src_hash,
            byte_size=path.stat().st_size,
            char_count=len(parsed.full_text),
            chunk_count=len(chunks),
            ingested_at=time.strftime("%Y-%m-%dT%H:%M:%S"),
            soul_json=None,
            soul_generated_at=None,
            soul_status="pending",
        )
        library.upsert_book(record)
        library.replace_chunks(
            bid,
            [(i, c.chapter, c.char_start, c.char_end, c.token_estimate) for i, c in enumerate(chunks)],
        )
        # Apply category/tags hints from the job (set by bulk-categorize)
        if job.category:
            try:
                library.set_book_category(bid, job.category)
            except Exception:  # noqa: BLE001
                pass
        if job.tags:
            try:
                library.set_book_tags(bid, job.tags)
            except Exception:  # noqa: BLE001
                pass

        if job.skip_soul:
            library.set_soul(bid, "{}", status="skipped")
            soul_status = "skipped"
        else:
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
                soul_status = "ok"
            except Exception:  # noqa: BLE001
                library.set_soul(bid, "{}", status="failed")
                soul_status = "failed"

        result.update(
            state="done",
            finished_at=time.time(),
            chunks=len(chunks),
            soul_status=soul_status,
        )
    except Exception as e:  # noqa: BLE001
        result.update(
            state="failed",
            finished_at=time.time(),
            error=f"{type(e).__name__}: {e}",
            traceback=traceback.format_exc(),
        )
    finally:
        library.close()
        ollama.close()
    return result


# --------------------------------------------------------------- pool


class IngestPool:
    """Non-blocking ingest pool.

    Usage:
        pool = IngestPool(preset, home, workers=8)
        pool.start()
        jid = pool.submit(IngestJob(path=...))
        asyncio.run(pool.run_forever(on_update=cb))
    """

    def __init__(self, *, preset: Preset, home: Path, workers: int = 8) -> None:
        self.preset = preset
        self.home = home
        self.workers = workers
        self.queue: queue.Queue[IngestJob] = queue.Queue()
        self.statuses: dict[int, JobStatus] = {}
        self._executor: Optional[ProcessPoolExecutor] = None
        self._id_seq = 0

    def start(self) -> None:
        if self._executor is not None:
            return
        ctx = mp.get_context("spawn")
        self._executor = ProcessPoolExecutor(max_workers=self.workers, mp_context=ctx)

    def stop(self, *, wait: bool = True) -> None:
        if self._executor is not None:
            self._executor.shutdown(wait=wait)
            self._executor = None

    def submit(self, job: IngestJob) -> int:
        self._id_seq += 1
        jid = self._id_seq
        self.statuses[jid] = JobStatus(job=job)
        self.queue.put(job)
        return jid

    @property
    def pending_count(self) -> int:
        return self.queue.qsize()

    def get_status(self, jid: int) -> Optional[JobStatus]:
        return self.statuses.get(jid)

    def all_statuses(self) -> list[JobStatus]:
        return sorted(self.statuses.values(), key=lambda s: s.job.path)

    async def run_forever(
        self,
        on_update: Callable[[int, JobStatus], None] | None = None,
        *,
        poll_interval: float = 0.2,
    ) -> None:
        if self._executor is None:
            self.start()
        assert self._executor is not None
        loop = asyncio.get_running_loop()

        # Pre-create a status placeholder per queued job so the UI sees them
        # before they start running.
        # (Already done in submit.)

        while True:
            # Submit as many pending jobs as we have free workers.
            in_flight = sum(1 for s in self.statuses.values() if s.state == "running")
            free = max(0, self.workers - in_flight)
            for _ in range(free):
                try:
                    job = self.queue.get_nowait()
                except queue.Empty:
                    break
                # Find the queued status for this job.
                jid = next(
                    (jid for jid, s in self.statuses.items() if s.job is job and s.state == "queued"),
                    None,
                )
                if jid is None:
                    continue
                self.statuses[jid].state = "running"
                self.statuses[jid].started_at = time.time()
                if on_update is not None:
                    try:
                        on_update(jid, self.statuses[jid])
                    except Exception:  # noqa: BLE001
                        pass

                fut = loop.run_in_executor(
                    self._executor,
                    _run_job,
                    job.__dict__,
                    self.preset.__dict__,
                    str(self.home),
                )
                fut.add_done_callback(self._make_done_callback(jid, on_update))

            await asyncio.sleep(poll_interval)

    def _make_done_callback(self, jid: int, on_update):
        def _cb(fut) -> None:
            try:
                result = fut.result()
            except Exception as e:  # noqa: BLE001
                status = JobStatus(
                    job=self.statuses[jid].job,
                    state="failed",
                    finished_at=time.time(),
                    error=str(e),
                )
            else:
                status = JobStatus(
                    job=self.statuses[jid].job,
                    state=result.get("state", "failed"),
                    started_at=result.get("started_at"),
                    finished_at=result.get("finished_at"),
                    chunks=result.get("chunks", 0),
                    soul_status=result.get("soul_status"),
                    error=result.get("error"),
                    traceback=result.get("traceback"),
                )
            self.statuses[jid] = status
            if on_update is not None:
                try:
                    on_update(jid, status)
                except Exception:  # noqa: BLE001
                    pass
        return _cb


# --------------------------------------------------------------- standalone


def run_daemon(inbox: Path, *, preset: Preset, home: Path, workers: int = 8) -> None:
    """Watch `inbox` for new files and ingest them. Runs forever."""
    import asyncio as _asyncio
    import sys as _sys

    pool = IngestPool(preset=preset, home=home, workers=workers)
    pool.start()

    seen: set[str] = set()
    console = None

    def on_update(jid: int, status: JobStatus) -> None:
        msg = (
            f"[{status.state:>7}] {status.job.display_name} "
            f"chunks={status.chunks} soul={status.soul_status}"
        )
        if status.error:
            msg += f" error={status.error}"
        print(msg, flush=True)

    async def _watch() -> None:
        runner = _asyncio.create_task(pool.run_forever(on_update=on_update))
        try:
            while True:
                if inbox.exists():
                    for p in sorted(inbox.iterdir()):
                        if p.is_file() and p.suffix.lower() in (".epub", ".pdf", ".docx", ".txt"):
                            key = str(p.resolve())
                            if key in seen:
                                continue
                            # Wait until file size is stable (write done).
                            sz1 = p.stat().st_size
                            await _asyncio.sleep(0.3)
                            sz2 = p.stat().st_size
                            if sz1 != sz2:
                                continue
                            seen.add(key)
                            pool.submit(IngestJob(path=str(p.resolve())))
                await _asyncio.sleep(1.0)
        finally:
            runner.cancel()

    try:
        _asyncio.run(_watch())
    except KeyboardInterrupt:
        pool.stop()
