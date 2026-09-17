"""Mind data model — a Mind is a scoped, persona-driven RAG agent."""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field, asdict
from typing import Iterable

from learnage.store.library import Book


# Scope kinds. 'all' = every book. 'category' = match category. 'tag' = match
# any tag. 'union' = match category OR tag in values. 'manual' = explicit IDs.
SCOPE_ALL = "all"
SCOPE_CATEGORY = "category"
SCOPE_TAG = "tag"
SCOPE_UNION = "union"
SCOPE_MANUAL = "manual"

ALL_SCOPES = [SCOPE_ALL, SCOPE_CATEGORY, SCOPE_TAG, SCOPE_UNION, SCOPE_MANUAL]

SCOPE_LABELS = {
    SCOPE_ALL: "All books",
    SCOPE_CATEGORY: "By category",
    SCOPE_TAG: "By tag",
    SCOPE_UNION: "Category or tag",
    SCOPE_MANUAL: "Specific books",
}


@dataclass
class Mind:
    """A Mind is a scoped RAG persona.

    A Mind answers questions using only books matching `scope_kind` /
    `scope_values`, wearing the persona defined by `system_prompt`.
    """

    id: str
    name: str
    description: str = ""
    icon: str = "✦"
    color: str = "#9ca8b8"

    # Scope
    scope_kind: str = SCOPE_ALL
    scope_values: list[str] = field(default_factory=list)

    # Persona + retrieval tuning
    system_prompt: str = ""
    preset_name: str | None = None
    temperature: float = 0.4
    top_k: int = 12
    top_n: int = 6
    include_soul: bool = True
    soul_max_chars: int = 2400

    # Meta + sorting
    is_builtin: bool = False
    created_at: str = ""
    updated_at: str = ""
    position: int = 0           # user-defined order; built-ins pinned to 0..N-1
    session_count: int = 0       # incremented every time a chat opens
    last_opened_at: str = ""     # ISO timestamp

    def __post_init__(self) -> None:
        if not self.created_at:
            self.created_at = _now_iso()
        if not self.updated_at:
            self.updated_at = self.created_at

    # ------------------------------------------------------------ matching

    def matches(self, book: Book) -> bool:
        if self.scope_kind == SCOPE_ALL:
            return True
        if self.scope_kind == SCOPE_MANUAL:
            return book.id in self.scope_values
        cat = (book.category or "").strip().lower()
        tags = [t.strip().lower() for t in book.display_tags]
        wanted = [v.strip().lower() for v in self.scope_values if v.strip()]
        if self.scope_kind == SCOPE_CATEGORY:
            return cat in wanted
        if self.scope_kind == SCOPE_TAG:
            return any(t in wanted for t in tags)
        if self.scope_kind == SCOPE_UNION:
            return cat in wanted or any(t in wanted for t in tags)
        return False

    def filter_books(self, books: Iterable[Book]) -> list[Book]:
        return [b for b in books if self.matches(b)]

    # ------------------------------------------------------------ display

    def scope_description(self) -> str:
        if self.scope_kind == SCOPE_ALL:
            return "All books in your library"
        if self.scope_kind == SCOPE_MANUAL:
            n = len(self.scope_values)
            return f"{n} specific book{'s' if n != 1 else ''}"
        if not self.scope_values:
            return "(no scope set)"
        head = SCOPE_LABELS.get(self.scope_kind, self.scope_kind)
        items = ", ".join(self.scope_values[:5])
        more = f" +{len(self.scope_values) - 5} more" if len(self.scope_values) > 5 else ""
        return f"{head}: {items}{more}"

    def matches_count(self, books: Iterable[Book]) -> int:
        return sum(1 for b in books if self.matches(b))

    # ------------------------------------------------------------ serialise

    def to_dict(self) -> dict:
        d = asdict(self)
        return d

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    @staticmethod
    def from_dict(d: dict) -> "Mind":
        # Strip unknown keys for forward compatibility
        known = set(Mind.__dataclass_fields__.keys())  # type: ignore[attr-defined]
        clean = {k: v for k, v in d.items() if k in known}
        return Mind(**clean)

    @staticmethod
    def from_json(s: str) -> "Mind":
        return Mind.from_dict(json.loads(s))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
