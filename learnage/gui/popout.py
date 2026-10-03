"""Popout interview window — a detachable QMainWindow that mirrors
the embedded interview for a single book.
"""

from __future__ import annotations

from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from learnage.config import Preset
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Library
from learnage.store.vectors import VectorStore


def _get_chat_tab():
    """Lazy import to avoid circular dependency."""
    from learnage.gui.app import ChatTab
    return ChatTab


class PopoutInterview(QMainWindow):
    """Detachable interview window. Shares state with the embedded ChatTab."""

    closed = Signal()

    def __init__(
        self,
        book_id: str,
        library: Library,
        vectors: VectorStore,
        ollama: OllamaClient,
        preset: Preset,
        on_submit_ingest,
        on_submit_soul,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.book_id = book_id
        self.setWindowTitle(f"Interview · {self._book_title(library, book_id)}")
        self.resize(680, 820)
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet(
            "background: #15151a; border-bottom: 1px solid #2a2a34;"
        )
        h = QVBoxLayout(header)
        h.setContentsMargins(20, 16, 20, 16)
        h.setSpacing(4)
        t = QLabel("Interview")
        t.setStyleSheet("color: #e6e6ec; font-size: 18px; font-weight: 600;")
        h.addWidget(t)
        book_label = QLabel(f"with {self._book_title(library, book_id)}")
        book_label.setStyleSheet("color: #8a8a98; font-size: 12px;")
        h.addWidget(book_label)
        layout.addWidget(header)

        # Chat body — embed a ChatTab preconfigured for this single book
        ChatTab = _get_chat_tab()
        self.chat = ChatTab(
            library=library,
            vectors=vectors,
            ollama=ollama,
            preset=preset,
            pool=None,
            on_submit_ingest=on_submit_ingest,
            on_submit_soul=on_submit_soul,
        )
        # Hide the mode toggle (always agentic for interviews)
        self.chat._agentic = True
        self.chat._restrict_book_ids = [book_id]
        # Try to hide the mode toggle if it exists
        if hasattr(self.chat, "toggle"):
            self.chat.toggle.hide()
        layout.addWidget(self.chat, 1)

        self.setCentralWidget(central)

    def _book_title(self, library: Library, book_id: str) -> str:
        b = library.get_book(book_id)
        return b.title if b else "?"

    def closeEvent(self, event) -> None:
        self.closed.emit()
        super().closeEvent(event)
