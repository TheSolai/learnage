#!/usr/bin/env -S uv run python
"""End-to-end smoke test: open the TUI, queue an ingest, verify it runs while UI is responsive."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from learnage.config import load_preset
from learnage.store.library import Library
from learnage.tui.app import LearnageApp, IngestPane
from learnage.util.paths import default_home, ensure_home, library_db_path
from learnage.worker import IngestJob


async def main() -> int:
    home = ensure_home(default_home())
    preset = load_preset("fast")
    app = LearnageApp(preset=preset, home=home, workers=2)

    async with app.run_test(headless=True) as pilot:
        # Switch to ingest tab
        await pilot.press("ctrl+i")
        await pilot.pause(0.2)

        # Submit a job via the pool directly
        sample = Path(__file__).resolve().parent.parent / "data" / "samples" / "short_story.txt"
        jid = app.pool.submit(IngestJob(path=str(sample), skip_soul=True))
        print(f"submitted job {jid}")

        # Watch for completion
        deadline = time.time() + 60
        while time.time() < deadline:
            s = app.pool.get_status(jid)
            if s and s.state in ("done", "failed"):
                break
            await asyncio.sleep(0.2)

        s = app.pool.get_status(jid)
        print(f"final: state={s.state} chunks={s.chunks} error={s.error}")

        # Library should show the book now
        lib = Library(library_db_path(home))
        n = len(lib.list_books())
        print(f"library now has {n} book(s)")
        lib.close()

        # Force the TUI to refresh and verify it didn't crash
        await pilot.pause(0.3)

        # Quit cleanly
        await pilot.press("ctrl+q")

    return 0 if s and s.state == "done" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
