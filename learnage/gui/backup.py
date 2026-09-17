"""Auto-backup — periodic snapshots of the library DB + vectors."""

from __future__ import annotations

import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path


def make_backup(home: Path, dest_root: Path | None = None) -> Path | None:
    """Take a snapshot of library.db into dest_root/YYYY-MM-DD/HH-MM-SS/.

    Returns the snapshot path, or None on failure.
    """
    if dest_root is None:
        dest_root = Path.home() / "Documents" / "learnage-backups"
    dest_root = Path(dest_root).expanduser().resolve()
    db = home / "library.db"
    if not db.exists():
        return None

    stamp = datetime.now().strftime("%Y-%m-%d/%H-%M-%S")
    dest = dest_root / stamp
    dest.mkdir(parents=True, exist_ok=True)

    # Use SQLite's online backup API to get a consistent snapshot even while
    # the library is being written to.
    try:
        src = sqlite3.connect(str(db))
        out = sqlite3.connect(str(dest / "library.db"))
        with out:
            src.backup(out)
        src.close()
        out.close()
    except Exception:  # noqa: BLE001
        # Fallback: copy bytes
        shutil.copy2(db, dest / "library.db")

    # Vector store — Chroma is a directory of files. Just copy.
    src_vec = home / "vectors"
    if src_vec.exists():
        dst_vec = dest / "vectors"
        if dst_vec.exists():
            shutil.rmtree(dst_vec)
        shutil.copytree(src_vec, dst_vec, dirs_exist_ok=True)

    # Write a manifest
    manifest = dest / "MANIFEST.txt"
    manifest.write_text(
        f"learnage backup\n"
        f"created: {datetime.now().isoformat()}\n"
        f"source: {home}\n"
    )
    return dest


def prune_old_backups(dest_root: Path | None = None, *, keep: int = 20) -> int:
    """Keep only the most recent `keep` backups (timestamped directories)."""
    if dest_root is None:
        dest_root = Path.home() / "Documents" / "learnage-backups"
    dest_root = Path(dest_root).expanduser().resolve()
    if not dest_root.exists():
        return 0
    # backups are YYYY-MM-DD/HH-MM-SS — group by date dir
    removed = 0
    date_dirs = sorted([p for p in dest_root.iterdir() if p.is_dir()], reverse=True)
    if len(date_dirs) <= keep:
        return 0
    for d in date_dirs[keep:]:
        try:
            shutil.rmtree(d)
            removed += 1
        except Exception:  # noqa: BLE001
            pass
    return removed


def last_backup_age_hours(dest_root: Path | None = None) -> float | None:
    """How many hours since the most recent backup. None if no backups exist."""
    if dest_root is None:
        dest_root = Path.home() / "Documents" / "learnage-backups"
    dest_root = Path(dest_root).expanduser().resolve()
    if not dest_root.exists():
        return None
    date_dirs = sorted([p for p in dest_root.iterdir() if p.is_dir()], reverse=True)
    if not date_dirs:
        return None
    try:
        # First backup in newest group
        stamps = sorted([p for p in date_dirs[0].iterdir() if p.is_dir()], reverse=True)
        if not stamps:
            return None
        mtime = stamps[0].stat().st_mtime
        return (time.time() - mtime) / 3600
    except Exception:  # noqa: BLE001
        return None