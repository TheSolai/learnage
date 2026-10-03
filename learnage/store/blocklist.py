"""Blocklist — paths that have been explicitly forgotten. They are never
reingested, even if found on disk again. Persists to ~/.learnage/blocklist.txt.
"""

from __future__ import annotations

from pathlib import Path


def _normalise(p: str | Path) -> str:
    return str(Path(p).expanduser().resolve())


class Blocklist:
    def __init__(self, home: Path) -> None:
        self.path = Path(home) / "blocklist.txt"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._entries: set[str] = set()
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            return
        for line in self.path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                self._entries.add(_normalise(line))

    def _save(self) -> None:
        lines = ["# Learnage blocklist — paths here are never auto-ingested",
                 "# One absolute path per line."]
        lines.extend(sorted(self._entries))
        self.path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def add(self, path: str | Path) -> None:
        n = _normalise(path)
        if n not in self._entries:
            self._entries.add(n)
            self._save()

    def remove(self, path: str | Path) -> None:
        n = _normalise(path)
        if n in self._entries:
            self._entries.remove(n)
            self._save()

    def contains(self, path: str | Path) -> bool:
        return _normalise(path) in self._entries

    def all(self) -> list[str]:
        return sorted(self._entries)

    def __len__(self) -> int:
        return len(self._entries)
