#!/usr/bin/env -S uv run python
"""Smoke test the IngestPool against the sample story."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from learnage.config import load_preset
from learnage.util.paths import default_home, ensure_home
from learnage.worker import IngestJob, IngestPool


async def main() -> int:
    home = ensure_home(default_home())
    preset = load_preset("fast")
    pool = IngestPool(preset=preset, home=home, workers=2)
    pool.start()

    sample = Path(__file__).resolve().parent.parent / "data" / "samples" / "short_story.txt"
    print(f"submitting {sample}")
    jid = pool.submit(IngestJob(path=str(sample), skip_soul=True))
    print(f"queued as job {jid}")

    updates: list[tuple[int, str]] = []

    def on_update(jid: int, status) -> None:
        updates.append((jid, status.state))
        print(f"  update: job={jid} state={status.state} chunks={status.chunks} soul={status.soul_status}")

    # Run the pool until job is done.
    runner = asyncio.create_task(pool.run_forever(on_update=on_update))
    deadline = time.time() + 60
    while pool.get_status(jid).state in ("queued", "running"):
        if time.time() > deadline:
            print("TIMEOUT")
            runner.cancel()
            return 1
        await asyncio.sleep(0.3)
    runner.cancel()
    final = pool.get_status(jid)
    print(f"\nfinal: state={final.state} chunks={final.chunks} soul={final.soul_status}")
    if final.error:
        print(f"  error: {final.error}")
    pool.stop(wait=True)
    return 0 if final.state == "done" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
