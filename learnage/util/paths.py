"""Library paths."""

from __future__ import annotations

import os
from pathlib import Path


def default_home() -> Path:
    """Return the default library home (~/.learnage or $LEARNAGE_HOME)."""
    env = os.environ.get("LEARNAGE_HOME")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".learnage").resolve()


def ensure_home(home: Path) -> Path:
    """Create the home layout if missing."""
    home = Path(home).expanduser().resolve()
    home.mkdir(parents=True, exist_ok=True)
    (home / "vectors").mkdir(exist_ok=True)
    (home / "sessions").mkdir(exist_ok=True)
    return home


def library_db_path(home: Path) -> Path:
    return Path(home) / "library.db"


def vectors_dir(home: Path) -> Path:
    return Path(home) / "vectors"


def sessions_dir(home: Path) -> Path:
    return Path(home) / "sessions"


def notes_dir(home: Path) -> Path:
    return Path(home) / "notes"


def blocklist_path(home: Path) -> Path:
    return Path(home) / "blocklist.txt"
