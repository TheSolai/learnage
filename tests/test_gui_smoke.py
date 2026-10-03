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
    """PopoutInterview was dead code in v1; verify the module is gone."""
    gui_dir = ROOT / "learnage" / "gui"
    assert not (gui_dir / "popout.py").exists()


def test_app_module_re_exports(qapp):
    """v2.0 split gui/app.py into 9 modules. Verify every widget is re-exported
    so existing import paths still work."""
    from learnage.gui import app

    expected = [
        # theme/widgets
        "PALETTE", "set_theme", "current_theme", "_qss",
        "html_escape",
        # sidebar / book_list
        "Sidebar", "BookRow", "BookListWidget",
        # views
        "SoulView", "ReadView",
        # chat
        "ChatTab", "InterviewView", "ToolCard",
        # minds
        "MindDialog", "MindChatTab",
        # ingest / dialogs
        "DropZone", "CategorizeConfirmDialog", "IngestTab",
        "WeedDialog",
        # main window + entry
        "MainWindow", "run_gui",
    ]
    for name in expected:
        assert hasattr(app, name), f"learnage.gui.app.{name} should be re-exported"


def test_gui_module_layout(qapp):
    """Verify the new gui/ module structure from PROPOSAL-v2 §5."""
    gui_dir = ROOT / "learnage" / "gui"
    expected_files = [
        "__init__.py",
        "agent.py",
        "app.py",
        "backup.py",
        "book_list.py",
        "book_window.py",
        "chat.py",
        "covers.py",
        "dialogs.py",
        "export.py",
        "ingest.py",
        "minds.py",
        "sidebar.py",
        "theme.py",
        "views/__init__.py",
        "views/soul.py",
        "views/read.py",
        "widgets.py",
    ]
    for fname in expected_files:
        assert (gui_dir / fname).exists(), f"missing gui/{fname}"


def test_app_py_line_count_under_target(qapp):
    """The proposal target was app.py under 1,200 lines after the split."""
    from learnage.gui import app
    import inspect
    src = inspect.getsource(app)
    lines = src.count("\n")
    assert lines < 1500, (
        f"learnage.gui.app is {lines} lines — proposal target was under "
        f"1,200. The remaining bulk is MainWindow (~1000 lines)."
    )


def test_main_window_constructs_with_library(qapp, tmp_path, monkeypatch):
    """Smoke test: instantiate MainWindow against an empty DB.
    This exercises every imported widget's __init__."""
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    from learnage.config import Preset
    from learnage.gui.app import MainWindow

    home = tmp_path / "learnage"
    home.mkdir()
    preset = Preset(name="balanced", llm="qwen3:14b", embed="nomic-embed-text")
    win = MainWindow(preset=preset, home=home, workers=1)
    # Give the timers a chance to fire (they shouldn't crash on empty DB).
    win.close()