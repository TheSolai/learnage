"""Persistent markdown notes per Mind — read by the Mind on every prompt."""

from __future__ import annotations

from pathlib import Path


class MindNotes:
    """Markdown notes stored at ~/.learnage/mind-notes/<mind_id>.md.

    These notes persist across sessions and are injected into every
    conversation with the Mind. They're Anne's way of telling the Mind
    things it should always remember about her — preferences, ongoing
    threads, names of people in her life, etc.
    """

    MAX_INJECT_CHARS = 4000

    def __init__(self, home: Path) -> None:
        self.home = Path(home)
        self.dir = self.home / "mind-notes"
        self.dir.mkdir(parents=True, exist_ok=True)

    def path_for(self, mind_id: str) -> Path:
        # Sanitize mind_id — should already be safe, but be defensive
        safe = "".join(c for c in mind_id if c.isalnum() or c in "-_")
        if not safe:
            safe = "unknown"
        return self.dir / f"{safe}.md"

    def load(self, mind_id: str) -> str:
        p = self.path_for(mind_id)
        if not p.exists():
            return ""
        try:
            return p.read_text(encoding="utf-8")
        except Exception:  # noqa: BLE001
            return ""

    def save(self, mind_id: str, content: str) -> None:
        p = self.path_for(mind_id)
        try:
            p.write_text(content, encoding="utf-8")
        except Exception:  # noqa: BLE001
            pass

    def exists(self, mind_id: str) -> bool:
        return self.path_for(mind_id).exists()

    def clear(self, mind_id: str) -> None:
        p = self.path_for(mind_id)
        if p.exists():
            try:
                p.unlink()
            except Exception:  # noqa: BLE001
                pass

    def for_injection(self, mind_id: str) -> str:
        """Return the notes content trimmed for system-prompt injection.

        Returns an empty string if no notes exist. Trims to MAX_INJECT_CHARS
        to avoid blowing past context limits.
        """
        text = self.load(mind_id).strip()
        if not text:
            return ""
        return text[: self.MAX_INJECT_CHARS]
