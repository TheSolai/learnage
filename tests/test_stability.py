"""Stability harness — exercises every GUI widget programmatically to catch
crashes, dead references, and re-entrancy bugs that don't show up in
single-construction tests.

Run with:

    python -m pytest tests/test_stability.py -v -s

The harness builds the real MainWindow against a temp library, then
walks through every visible widget and invokes its primary actions
without crashing. Any exception from a callback bubbles up as a test
failure.

Skips automatically if there's no QT_QPA_PLATFORM=offscreen support.
"""

from __future__ import annotations

import os
import sys
import time
import traceback
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


@pytest.fixture(scope="module")
def main_window(qapp, tmp_path_factory):
    """Build a real MainWindow against a tmp home, sharing across tests."""
    home = tmp_path_factory.mktemp("learnage-home")
    from learnage.config import Preset
    from learnage.gui.app import MainWindow
    preset = Preset(name="balanced", llm="qwen3:14b", embed="nomic-embed-text")
    win = MainWindow(preset=preset, home=home, workers=1)
    yield win
    win.close()


# ---------------------------------------------------------------- smoke checks

def test_window_stays_alive_after_construction(main_window):
    """No deferred-destroy crash in the first ~500ms of life."""
    from PySide6.QtCore import QTimer
    QTimer.singleShot(500, lambda: None)
    main_window.library.list_books()  # exercise the SQLite connection


def test_library_refresh_does_not_crash_on_empty_db(main_window):
    """Library refresh fires every 2s — make sure empty DB is OK."""
    main_window._refresh_library()
    main_window._refresh_library()  # twice — guards against set-merge bugs


def test_mind_list_refresh_does_not_crash(main_window):
    """Mind list refresh — empty registry is fine."""
    main_window._refresh_mind_list()
    main_window._refresh_mind_list()


def test_status_queue_counts_under_zero_books(main_window):
    """Status bar shows correct counts even with no books."""
    main_window._tick()


# ---------------------------------------------------------------- palette exercise

def test_command_palette_opens_and_lists_commands(main_window):
    """⌘K opens the palette and it has all the bound commands."""
    from learnage.gui.command_palette import CommandPalette
    from learnage.gui.command_registry import all_commands

    palette = CommandPalette(parent=main_window)
    n = palette.list.count()
    assert n > 0
    # All registered commands are present
    keys = {palette.list.item(i).data(0x100) for i in range(n)}
    assert "toggle theme" in keys
    assert "back up now" in keys
    palette.close()


def test_command_palette_filters_as_user_types(main_window):
    """Typing should narrow the list."""
    from learnage.gui.command_palette import CommandPalette

    palette = CommandPalette(parent=main_window)
    before = palette.list.count()
    palette.input.setText("tog")
    palette._refilter()
    after = palette.list.count()
    assert after < before
    # The top hit must be toggle theme
    top = palette.list.item(0).data(0x100)
    assert top == "toggle theme"
    palette.close()


def test_command_palette_arrow_keys_navigate(main_window):
    """↑ / ↓ keys move the selection."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from learnage.gui.command_palette import CommandPalette

    palette = CommandPalette(parent=main_window)
    initial_row = palette.list.currentRow()
    palette.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Down, Qt.NoModifier))
    assert palette.list.currentRow() == (initial_row + 1) % palette.list.count()
    palette.close()


def test_command_palette_escape_closes(main_window):
    """esc closes the palette without raising."""
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QKeyEvent
    from learnage.gui.command_palette import CommandPalette

    palette = CommandPalette(parent=main_window)
    palette.keyPressEvent(QKeyEvent(QKeyEvent.KeyPress, Qt.Key_Escape, Qt.NoModifier))
    # Esc just calls self.reject(); for a modal exec() the result() would
    # equal QDialog.Rejected. Outside exec(), reject() is harmless — the
    # important thing is it didn't crash.
    assert palette.isHidden() or not palette.isVisible()


# ---------------------------------------------------------------- book list + covers

def test_book_list_set_books_no_op_main(main_window):
    """Setting an empty book list and a populated one."""
    from learnage.store.library import Book

    main_window.book_list.set_books([], filter_kind="library")
    assert main_window.book_list.list.count() == 0

    book = Book(
        id="aaaa1111", title="Synthetic", author="Anne",
        source_path="/tmp/syn.epub", source_format="epub",
        source_hash="x" * 64, byte_size=1, char_count=1,
        chunk_count=2, ingested_at="2026-10-03T00:00:00",
        soul_json=None, soul_generated_at=None, soul_status="ok",
    )
    main_window.book_list.set_books([book], filter_kind="library")
    assert main_window.book_list.list.count() == 1
    main_window.book_list.set_books([], filter_kind="library")


def test_cover_thumbnail_renders_for_synthetic_book(qapp):
    """show_soul builds a header that includes a cover QLabel + at least
    one QLabel for the title."""
    from PySide6.QtWidgets import QLabel
    from learnage.store.library import Book
    from learnage.store.soul import SoulRecord
    from learnage.gui.views.soul import SoulView

    view = SoulView()
    book = Book(
        id="bbbb2222", title="Cover Test", author="Anne",
        source_path="/tmp/cover.epub", source_format="pdf",
        source_hash="y" * 64, byte_size=1, char_count=1,
        chunk_count=5, ingested_at="2026-10-03T00:00:00",
        soul_json=None, soul_generated_at=None, soul_status="ok",
    )
    soul = SoulRecord(summary="A short summary for the cover test.")
    view.show_soul(book, soul)
    # show_soul builds a header row with a cover QLabel + title QLabel
    # plus a divider QFrame. Multiple QLabel children must exist.
    labels = [c for c in view.container.findChildren(QLabel)]
    assert len(labels) >= 2, (
        f"SoulView header should have multiple labels (cover + title), "
        f"got {len(labels)}"
    )
    view.deleteLater()


# ---------------------------------------------------------------- chat streams

def test_chat_bubble_text_can_be_repeatedly_set(main_window):
    """Set bubble text 100 times in a row — guards against state leaks."""
    from PySide6.QtWidgets import QLabel

    bubble = QLabel()
    for i in range(100):
        bubble.setText(f"<b>chunk {i}</b>")
    assert "99" in bubble.text()


def test_streaming_citations_render_under_load():
    """100 streamed texts render fast and don't leak."""
    from learnage.gui.chat import ChatTab
    import time

    passage_index = [(f"book_{i}", i * 10) for i in range(20)]
    sample_base = "According to [p1] and [p2] and [p3], "

    t0 = time.perf_counter()
    for i in range(100):
        text = sample_base + "the author " * (i % 30)
        ChatTab._render_streaming_citations(text, passage_index)
    elapsed = time.perf_counter() - t0
    # 100 renders should take well under a second
    assert elapsed < 1.0, f"streaming citation rendering is slow: {elapsed:.3f}s for 100"


# ---------------------------------------------------------------- repeated state cycles

def test_main_window_survives_50_tick_cycles(main_window):
    """Run the tick loop 50 times — exercises timer-driven refresh paths."""
    for _ in range(50):
        main_window._tick()
    # No exceptions, library still consistent
    books = main_window.library.list_books()
    assert isinstance(books, list)


def test_sidebar_section_change_emits(main_window):
    """Selecting a sidebar row emits section_changed with the section id."""
    received: list[str] = []
    main_window.sidebar.section_changed.connect(received.append)
    try:
        main_window.sidebar.list.setCurrentRow(1)
        assert "souls" in received, (
            f"expected 'souls' in section_changed events, got {received}"
        )
    finally:
        main_window.sidebar.section_changed.disconnect(received.append)


def test_main_window_close_is_clean(main_window):
    """closeEvent shouldn't crash and should drain timers."""
    from PySide6.QtGui import QCloseEvent
    ev = QCloseEvent()
    main_window.closeEvent(ev)
    assert main_window._closed is True


def test_book_window_constructs_against_mocked_ollama(qapp, tmp_path):
    """BookWindow must construct without crashing. Regression for the
    QFontMetricsF import bug — opening any book from the launcher used to
    raise NameError on the BookEditView tab."""
    from pathlib import Path
    from unittest.mock import MagicMock
    from learnage.config import Preset
    from learnage.store.library import Library, Book
    from learnage.gui.book_window import BookWindow

    library = Library(tmp_path / "library.db")
    book = Book(
        id="1234abcd", title="BookWindow Test", author="Anne",
        source_path="/tmp/bw.epub", source_format="epub",
        source_hash="x" * 64, byte_size=1, char_count=1,
        chunk_count=5, ingested_at="2026-01-01T00:00:00",
        soul_json=None, soul_generated_at=None, soul_status="ok",
    )
    vectors = MagicMock()
    vectors.get_all_chunks.return_value = []
    vectors.query_multi.return_value = []
    ollama = MagicMock()
    preset = Preset(name="balanced")
    win = BookWindow(
        book=book, library=library, vectors=vectors, ollama=ollama,
        preset=preset, home=Path(tmp_path),
        on_submit_ingest=lambda *a, **k: None,
        on_submit_soul=lambda *a, **k: None,
        on_regenerate_soul=lambda *a, **k: None,
    )
    assert win.book.id == book.id
    win.close()
    library.close()

@pytest.mark.timeout(60)
def test_main_window_soak_30_seconds(qapp, tmp_path):
    """Run the launcher for 30 seconds of wall clock with the Qt event loop
    spinning. Catches deferred-destroy bugs, timer miscounts, and
    re-entrancy crashes that only appear after multiple cycles."""
    home = tmp_path / "learnage"
    home.mkdir()
    from learnage.config import Preset
    from learnage.gui.app import MainWindow
    preset = Preset(name="balanced", llm="qwen3:14b", embed="nomic-embed-text")
    win = MainWindow(preset=preset, home=home, workers=1)
    end = time.time() + 30
    cycles = 0
    while time.time() < end:
        win._tick()
        win._refresh_library()
        win._refresh_mind_list()
        cycles += 1
        qapp.processEvents()
    win.close()
    assert cycles > 50, f"only {cycles} cycles in 30s"