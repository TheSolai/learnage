"""Headless GUI smoke tests — exercise the import + construction paths that
v1 used to crash at runtime.

These tests do not open a window. They construct the offending widgets in
offscreen mode to make sure the imports and __init__ signatures are valid.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# Headless Qt — no display server needed.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    yield app


def test_qcombobox_is_importable_in_book_window(qapp):
    """Regression test for the v1 crash: QComboBox wasn't imported in
    book_window.py, so opening any BookWindow with Categorize tab raised
    NameError. Verify the symbol is in scope."""
    from learnage.gui import book_window
    assert hasattr(book_window, "QComboBox"), (
        "QComboBox must be importable from learnage.gui.book_window — "
        "CategorizeView uses QComboBox for the category dropdown."
    )


def test_categorize_view_constructs(qapp, tmp_path):
    """End-to-end construction test for CategorizeView — this is the exact
    widget that crashed in v1 when a user clicked any book."""
    from learnage.config import Preset
    from learnage.store.library import Book, Library
    from learnage.gui.book_window import CategorizeView

    # Minimal book record
    book = Book(
        id="abcd1234",
        title="Test Book",
        author="Anne",
        source_path="/tmp/test.epub",
        source_format="epub",
        source_hash="x" * 64,
        byte_size=1000,
        char_count=500,
        chunk_count=10,
        ingested_at="2026-10-03T00:00:00",
        soul_json=None,
        soul_generated_at=None,
        soul_status="ok",
    )
    library = Library(tmp_path / "library.db")

    # Construction must not raise NameError or any other exception.
    view = CategorizeView(book=book, library=library, home=tmp_path)
    assert view.category_edit is not None
    library.close()


def test_jobstatus_has_traceback_field():
    """The soul failure path now carries a traceback so the GUI can show it."""
    from learnage.worker import JobStatus, IngestJob
    s = JobStatus(
        job=IngestJob(path="/tmp/x.epub"),
        state="failed",
        error="ValueError: bad book",
        traceback="Traceback (most recent call last):\n  ...",
    )
    assert s.traceback is not None
    assert "Traceback" in s.traceback


def test_popout_module_removed(qapp):
    """PopoutInterview was dead code in v1 (passed pool=None to ChatTab which
    didn't accept it). It is deleted in v2.0; verify the module is gone."""
    gui_dir = ROOT / "learnage" / "gui"
    assert not (gui_dir / "popout.py").exists(), (
        "learnage/gui/popout.py must be deleted — it depended on a ChatTab "
        "kwarg that doesn't exist."
    )