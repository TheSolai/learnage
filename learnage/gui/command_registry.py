"""Command registry — single source of truth for every action the launcher
exposes. Powers the ⌘K command palette.

Each command is a small dataclass with:
- key:         lowercase, used for fuzzy matching
- label:       shown in the palette
- glyph:       1-char icon (◆ ◇ ✺ ⊕ ⌘ ⚙ ✕ ✺ ⌫)
- category:    for grouping ("Open", "Action", "Settings")
- description: 1-line subtitle
- run():      callable that returns True on success, False on error
- target_kw:  optional — the runtime passes it via ``run(target_kw=...)``
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Optional


@dataclass
class Command:
    key: str
    label: str
    glyph: str
    category: str
    description: str
    run: Callable[..., bool] = field(default=lambda: True)
    target_kw: Optional[str] = None   # if set, runner is given target_kw=...


_REGISTRY: list[Command] = []


def register(cmd: Command) -> Command:
    """Add a command to the registry. Idempotent by key."""
    for i, existing in enumerate(_REGISTRY):
        if existing.key == cmd.key:
            _REGISTRY[i] = cmd
            return cmd
    _REGISTRY.append(cmd)
    return cmd


def all_commands() -> list[Command]:
    """Return all registered commands, sorted by category then label."""
    return sorted(_REGISTRY, key=lambda c: (c.category, c.label.lower()))


def commands_for_target(target_kind: str, target_id: Optional[str]) -> list[Command]:
    """Return commands valid for the current selection.

    ``target_kind`` is one of: "book", "mind", "section", "library", "none".
    The palette uses this to filter which commands show up first.
    """
    out: list[Command] = []
    for c in all_commands():
        if c.target_kw is None or c.target_kw == target_kind:
            out.append(c)
    return out


def run_command(key: str, **kwargs) -> bool:
    """Run a command by key. Returns True/False based on the command's return."""
    for c in _REGISTRY:
        if c.key == key:
            try:
                return bool(c.run(**kwargs))
            except Exception:  # noqa: BLE001
                import traceback
                traceback.print_exc()
                return False
    return False


# Default commands — registered below. These are placeholders until the
# MainWindow wires up its real handlers via ``bind_handlers``.

def _stub(label: str) -> Callable[..., bool]:
    """Placeholder for not-yet-bound commands. Replaced at boot by
    MainWindow._bind_command_handlers."""
    def _f(**_kwargs) -> bool:
        return False
    _f.__name__ = f"_stub_{label}"
    return _f


def register_defaults() -> None:
    """Register the canonical command set. Called once at startup."""
    if _REGISTRY:
        return
    cmds = [
        # ---- navigation: open a book ----
        Command(
            key="open book",
            label="Open book…",
            glyph="◇",
            category="Open",
            description="Search and open a book from your library",
            run=_stub("open_book"),
            target_kw="library",
        ),
        Command(
            key="search passages",
            label="Search passages…",
            glyph="◐",
            category="Open",
            description="Semantic search across every book in your library",
            run=_stub("search_passages"),
            target_kw="library",
        ),
        # ---- minds ----
        Command(
            key="open mind",
            label="Open mind…",
            glyph="✦",
            category="Mind",
            description="Jump to a scoped Mind chat",
            run=_stub("open_mind"),
        ),
        Command(
            key="new mind",
            label="New mind",
            glyph="⊕",
            category="Mind",
            description="Create a new scoped Mind (persona)",
            run=_stub("new_mind"),
        ),
        # ---- ingest ----
        Command(
            key="add books",
            label="Add books…",
            glyph="＋",
            category="Ingest",
            description="Pick one or more files to add to the library",
            run=_stub("add_books"),
        ),
        Command(
            key="regenerate soul",
            label="Regenerate soul (selected book)",
            glyph="✺",
            category="Ingest",
            description="Re-run the soul analyzer on the selected book",
            run=_stub("regenerate_soul"),
            target_kw="book",
        ),
        Command(
            key="weed library",
            label="Weed library…",
            glyph="⌫",
            category="Ingest",
            description="Bulk-remove broken or low-chunk books",
            run=_stub("weed"),
        ),
        Command(
            key="back up now",
            label="Back up library now",
            glyph="⤓",
            category="Ingest",
            description="Snapshot library.db and vectors to ~/Documents/learnage-backups/",
            run=_stub("backup"),
        ),
        # ---- search / filter ----
        Command(
            key="search title",
            label="Search title or author…",
            glyph="⌕",
            category="Search",
            description="Filter the book list by title or author",
            run=_stub("search_title"),
            target_kw="library",
        ),
        # ---- actions on selected book ----
        Command(
            key="open book in new window",
            label="Open book in new window",
            glyph="↗",
            category="Book",
            description="Detach the selected book into a free-floating window",
            run=_stub("open_book_new"),
            target_kw="book",
        ),
        Command(
            key="forget book",
            label="Forget this book",
            glyph="✕",
            category="Book",
            description="Remove the selected book from the library",
            run=_stub("forget"),
            target_kw="book",
        ),
        Command(
            key="export book",
            label="Export book as Markdown…",
            glyph="⤓",
            category="Book",
            description="Save the book's chunks + soul as a .md file",
            run=_stub("export_book"),
            target_kw="book",
        ),
        Command(
            key="categorize book",
            label="Categorize…",
            glyph="⊞",
            category="Book",
            description="Set the selected book's category",
            run=_stub("categorize"),
            target_kw="book",
        ),
        Command(
            key="bulk categorize",
            label="Bulk categorize (multi-select)…",
            glyph="⊞",
            category="Book",
            description="Apply a category to every selected book",
            run=_stub("bulk_categorize"),
            target_kw="library",
        ),
        # ---- settings ----
        Command(
            key="toggle theme",
            label="Toggle dark / light theme",
            glyph="☼",
            category="Settings",
            description="Switch the colour palette",
            run=_stub("toggle_theme"),
        ),
        Command(
            key="open settings",
            label="Settings…",
            glyph="⚙",
            category="Settings",
            description="Library path, workers, model",
            run=_stub("settings"),
        ),
        Command(
            key="new chat",
            label="New chat (active window)",
            glyph="✛",
            category="Action",
            description="Start a fresh session for the focused book",
            run=_stub("new_chat"),
        ),
        Command(
            key="cancel",
            label="Cancel",
            glyph="⎋",
            category="Action",
            description="Dismiss the palette",
            run=lambda: True,
        ),
    ]
    for c in cmds:
        register(c)


def bind_handler(key: str, run: Callable[..., bool]) -> None:
    """Replace the run callable for a registered command. Called by
    MainWindow once on construction to wire real handlers."""
    for c in _REGISTRY:
        if c.key == key:
            c.run = run
            return
    # Not found — register a fresh command with this handler.
    register(Command(
        key=key, label=key, glyph="◆", category="Misc",
        description="", run=run,
    ))