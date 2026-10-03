"""Per-book window — opens when you click a book. Each book gets its own
QMainWindow with native traffic lights, tabs for Read / Notes / Soul / Chat,
and an embedded agentic chat.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    Q_ARG,
    QMetaObject,
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import (
    QAction,
    QFont,
    QFontDatabase,
    QKeySequence,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from learnage.config import Preset
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Book, Library
from learnage.store.soul import SoulRecord
from learnage.store.vectors import VectorStore
from learnage.util.paths import ensure_home, library_db_path, notes_dir, vectors_dir


# Module-level constants from app.py (resolved lazily via _lazy).
# We can't import app.py at top-level because app.py imports book_window.
_PALETTE = None
_QSS_FN = None
_CHAT_TAB_CLS = None
_SOUL_VIEW_CLS = None


def _lazy():
    """Resolve and cache the app.py symbols we need."""
    global _PALETTE, _QSS_FN, _CHAT_TAB_CLS, _SOUL_VIEW_CLS
    if _PALETTE is None:
        from learnage.gui import app as _app
        _PALETTE = _app.PALETTE
        _QSS_FN = _app._qss
        _CHAT_TAB_CLS = _app.ChatTab
        _SOUL_VIEW_CLS = _app.SoulView
    return _PALETTE, _QSS_FN, _CHAT_TAB_CLS, _SOUL_VIEW_CLS


def PALETTE():
    return _lazy()[0]


def _qss():
    return _lazy()[1]()


def ChatTab(*args, **kwargs):
    return _lazy()[2](*args, **kwargs)


def SoulView(*args, **kwargs):
    return _lazy()[3](*args, **kwargs)


# ----------------------------------------------------------------- notes


def notes_path(home: Path, book_id: str) -> Path:
    d = notes_dir(home)
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{book_id}.md"


def load_notes(home: Path, book_id: str) -> str:
    p = notes_path(home, book_id)
    if p.exists():
        return p.read_text(encoding="utf-8")
    return f"# Notes\n\n"


def save_notes(home: Path, book_id: str, text: str) -> None:
    p = notes_path(home, book_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ----------------------------------------------------------------- read view (editable + searchable)


class BookReadView(QWidget):
    """Read view of one book — searchable, copy-able, exportable."""

    def __init__(self, vectors: VectorStore, book: Book) -> None:
        super().__init__()
        self.vectors = vectors
        self.book = book
        self._chunks: list[dict] = []
        self._filtered: list[dict] = []
        self._base_pt = 15

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        tb = QWidget()
        tb.setStyleSheet(
            f"background: {PALETTE()['bg_elev']}; border-bottom: 1px solid {PALETTE()['border']};"
        )
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(20, 10, 20, 10)
        tbh.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find in this book…")
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._apply_filter)
        tbh.addWidget(self.search)
        tbh.addStretch()
        for delta, label in [(-1, "−"), (+1, "+")]:
            btn = QPushButton(label)
            btn.setFixedWidth(28)
            btn.clicked.connect(lambda _, d=delta: self._bump_font(d))
            tbh.addWidget(btn)
        self.export_btn = QPushButton("⤓ Export")
        self.export_btn.setProperty("variant", "ghost")
        self.export_btn.clicked.connect(self._export)
        tbh.addWidget(self.export_btn)
        layout.addWidget(tb)

        # Body
        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setStyleSheet(
            f"QTextBrowser {{ background: {PALETTE()['bg_elev']}; border: none; padding: 0; }}"
        )
        self._apply_font()
        # Right-click menu for copy
        self.body.setContextMenuPolicy(Qt.CustomContextMenu)
        self.body.customContextMenuRequested.connect(self._body_context)

        # Chapter navigator on the left
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(self._build_nav())
        sc = QScrollArea()
        sc.setWidget(self.body)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        splitter.addWidget(sc)
        splitter.setSizes([260, 800])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setHandleWidth(1)
        layout.addWidget(splitter, 1)

    def _build_nav(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(
            f"background: {PALETTE()['bg']}; border-right: 1px solid {PALETTE()['border']};"
        )
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(0)
        # Nav header
        head = QLabel("Chapters")
        head.setStyleSheet(
            f"color: {PALETTE()['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
            f" padding: 16px 16px 8px 16px;"
        )
        v.addWidget(head)
        self.nav = QListWidget()
        self.nav.setFrameShape(QFrame.NoFrame)
        self.nav.setStyleSheet(
            "QListWidget { padding: 4px 8px; outline: 0; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 6px; }"
        )
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        v.addWidget(self.nav, 1)
        self._populate()
        return w

    def _populate(self) -> None:
        self._chunks = self.vectors.get_all_chunks(self.book.id)
        self.nav.clear()
        if not self._chunks:
            self.nav.addItem("(no chunks)")
            return
        has_real = any(c.get("chapter") for c in self._chunks)
        if not has_real:
            self.nav.addItem(f"All text · {len(self._chunks)} sections")
            self._filtered = list(self._chunks)
            self._render()
            return
        seen: set[str] = set()
        for c in self._chunks:
            ch = c.get("chapter")
            if not ch or ch in seen:
                continue
            seen.add(ch)
            self.nav.addItem(_truncate_ch_label(ch))
        if self.nav.count() > 0:
            self.nav.setCurrentRow(0)
        self._apply_filter()

    def _apply_filter(self) -> None:
        if not self._chunks:
            return
        q = self.search.text().strip().lower()
        if not q:
            self._filtered = list(self._chunks)
        else:
            self._filtered = [c for c in self._chunks if q in c["text"].lower()]
        self._render()

    def _render(self) -> None:
        pt = self._base_pt
        col_w = 720
        parts = [
            f"<div style='margin: 40px auto 80px auto; max-width: {col_w}px;"
            f" padding: 0 40px; font-family: Georgia, Charter, serif;"
            f" font-size: {pt}px; line-height: 1.75; color: {PALETTE()['text']};"
            f" letter-spacing: 0.01em;'>"
        ]
        if not self._filtered:
            parts.append(
                f'<p style="color:{PALETTE()["text_muted"]}; text-align:center;'
                f' padding:80px 0; font-family:-apple-system,sans-serif;">No matches.</p>'
            )
        else:
            last_ch = None
            for c in self._filtered:
                ch = c.get("chapter") or ""
                if ch != last_ch:
                    margin = "0" if last_ch is None else "44px"
                    parts.append(
                        f'<h2 style="color:{PALETTE()["accent"]}; font-size: 10px;'
                        f' font-weight: 700; text-transform: uppercase;'
                        f' letter-spacing: 2.5px; margin: {margin} 0 18px 0;'
                        f' padding-bottom: 10px;'
                        f' border-bottom: 1px solid {PALETTE()["border"]};'
                        f' font-family: -apple-system, sans-serif;">'
                        f'{html_escape(ch or "—")}</h2>'
                    )
                    last_ch = ch
                text = html_escape(c["text"])
                if self.search.text().strip():
                    text = _highlight(text, self.search.text().strip())
                parts.append(
                    f'<p id="chunk-{c["chunk_index"]}" data-chunk="{c["chunk_index"]}" '
                    f'style="white-space: pre-wrap; margin: 0 0 18px 0;">{text}</p>'
                )
        parts.append("</div>")
        self.body.setHtml("\n".join(parts))

    def _on_nav_changed(self, row: int) -> None:
        if not self._chunks or row < 0:
            return
        if not any(c.get("chapter") for c in self._chunks):
            return
        chapters: list[str] = []
        seen: set[str] = set()
        for c in self._chunks:
            ch = c.get("chapter")
            if not ch or ch in seen:
                continue
            seen.add(ch)
            chapters.append(ch)
        if row >= len(chapters):
            return
        self._filtered = [c for c in self._chunks if c.get("chapter") == chapters[row]]
        self._render()

    def jump_to_chunk(self, chunk_index: int) -> bool:
        """Scroll the body to the chunk with `chunk_index`. Returns True if found."""
        if not self._chunks:
            return False
        # If the active chapter filter hides the chunk, drop the filter
        # first so we can show it. Then re-render and scroll.
        if self.search.text().strip():
            self.search.clear()
            self._apply_filter()
        # Check if the chunk is in the current visible set
        visible_ids = {c["chunk_index"] for c in self._filtered}
        if chunk_index not in visible_ids:
            # Drop the chapter filter (re-show all)
            if self.nav.count() > 1:
                self.nav.setCurrentRow(-1)
            self._filtered = list(self._chunks)
            self._render()
        # Scroll to anchor
        anchor = f"chunk-{chunk_index}"
        # Re-render is async — defer the scroll
        from PySide6.QtCore import QTimer
        QTimer.singleShot(
            50,
            lambda: self._scroll_to_anchor(anchor),
        )
        return True

    def _scroll_to_anchor(self, anchor: str) -> None:
        # Find the element via QTextBrowser's scrollToAnchor
        try:
            self.body.scrollToAnchor(anchor)
        except Exception:  # noqa: BLE001
            pass

    def _bump_font(self, delta: int) -> None:
        self._base_pt = max(11, min(24, self._base_pt + delta))
        self._apply_font()
        self._render()

    def _apply_font(self) -> None:
        f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        f.setStyleHint(QFont.Serif)
        f.setPointSize(self._base_pt)
        self.body.setFont(f)

    def _body_context(self, pos) -> None:
        menu = self.body.createStandardContextMenu()
        menu.exec_(self.body.mapToGlobal(pos))

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export book text",
            f"{self.book.title}.md",
            "Markdown (*.md);;Text (*.txt);;All files (*.*)"
        )
        if not path:
            return
        out = [f"# {self.book.title}\n\n"]
        if self.book.author:
            out.append(f"*by {self.book.author}*\n\n")
        for c in self._chunks:
            ch = c.get("chapter")
            if ch:
                out.append(f"\n## {ch}\n\n")
            out.append(c["text"])
            out.append("\n")
        Path(path).write_text("\n".join(out), encoding="utf-8")


def _truncate_ch_label(s: str, n: int = 60) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


def html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _highlight(text: str, query: str) -> str:
    import re
    if not query:
        return text
    return re.sub(
        f"({re.escape(query)})",
        r'<span style="background:' + PALETTE()["selection_strong"] + r'">\1</span>',
        text,
        flags=re.IGNORECASE,
    )


# ----------------------------------------------------------------- notes editor


class NotesEditor(QWidget):
    """Plain-text editor for notes — auto-saves to disk."""

    def __init__(self, home: Path, book: Book) -> None:
        super().__init__()
        self.home = home
        self.book = book
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        tb = QWidget()
        tb.setStyleSheet(
            f"background: {PALETTE()['bg_elev']}; border-bottom: 1px solid {PALETTE()['border']};"
        )
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(20, 10, 20, 10)
        tbh.setSpacing(8)
        self.saved_lbl = QLabel("")
        tbh.addWidget(self.saved_lbl)
        tbh.addStretch()
        for delta, label in [(-1, "−"), (+1, "+")]:
            btn = QPushButton(label)
            btn.setFixedWidth(28)
            btn.clicked.connect(lambda _, d=delta: self._bump_font(d))
            tbh.addWidget(btn)
        layout.addWidget(tb)

        # Editor
        self.editor = QPlainTextEdit()
        self.editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {PALETTE()['bg_elev']}; color: {PALETTE()['text']};"
            f" border: none; padding: 24px 32px;"
            f" font-family: Georgia, Charter, serif;"
            f" selection-background-color: {PALETTE()['selection']};"
            f"}}"
        )
        self._base_pt = 14
        self._apply_font()
        sc = QScrollArea()
        sc.setWidget(self.editor)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        layout.addWidget(sc, 1)

        # Load existing notes
        self.editor.setPlainText(load_notes(self.home, self.book.id))
        self._mark_saved()

        # Autosave timer
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._autosave)
        self._timer.start()
        self.editor.textChanged.connect(self._mark_dirty)

    def _apply_font(self) -> None:
        f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        f.setStyleHint(QFont.Serif)
        f.setPointSize(self._base_pt)
        self.editor.setFont(f)

    def _bump_font(self, delta: int) -> None:
        self._base_pt = max(11, min(22, self._base_pt + delta))
        self._apply_font()

    def _mark_dirty(self) -> None:
        self.saved_lbl.setText("● unsaved")
        self.saved_lbl.setStyleSheet(f"color: {PALETTE()['warning']}; font-size: 11px;")

    def _mark_saved(self) -> None:
        self.saved_lbl.setText("✓ saved")
        self.saved_lbl.setStyleSheet(f"color: {PALETTE()['text_muted']}; font-size: 11px;")

    def _autosave(self) -> None:
        try:
            save_notes(self.home, self.book.id, self.editor.toPlainText())
            self._mark_saved()
        except Exception:  # noqa: BLE001
            pass

    def closeEvent(self, event) -> None:
        # Force a final save before close
        try:
            save_notes(self.home, self.book.id, self.editor.toPlainText())
        except Exception:  # noqa: BLE001
            pass
        super().closeEvent(event)


# ----------------------------------------------------------------- categorize tab


class CategorizeView(QWidget):
    """Set a book's category and tags — autocomplete from existing values."""

    def __init__(self, book: Book, library: Library, home: Path) -> None:
        super().__init__()
        self.book = book
        self.library = library
        self.home = home
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(40, 28, 40, 28)
        layout.setSpacing(18)

        # Heading
        head = QLabel("Categorize")
        f = QFontDatabase.systemFont(QFontDatabase.TitleFont)
        f.setPointSize(20); f.setWeight(QFont.DemiBold)
        head.setFont(f)
        head.setStyleSheet(f"color: {PALETTE()['text']};")
        layout.addWidget(head)

        sub = QLabel("Pick a category and add tags. Both feed Minds — your scoped RAG personas.")
        sub.setWordWrap(True)
        sub.setStyleSheet(
            f"color: {PALETTE()['text_muted']}; font-size: 13px;"
        )
        layout.addWidget(sub)

        # Category row
        cat_box = QWidget()
        cat_h = QVBoxLayout(cat_box)
        cat_h.setContentsMargins(0, 0, 0, 0)
        cat_h.setSpacing(4)
        cat_lbl = QLabel("CATEGORY")
        cat_lbl.setStyleSheet(
            f"color: {PALETTE()['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        cat_h.addWidget(cat_lbl)
        cat_row = QHBoxLayout()
        cat_row.setSpacing(8)
        self.category_edit = QComboBox()
        self.category_edit.setEditable(True)
        self.category_edit.setInsertPolicy(QComboBox.NoInsert)
        self.category_edit.lineEdit().setPlaceholderText("e.g. witchcraft, fiction, philosophy…")
        self.category_edit.lineEdit().textChanged.connect(self._on_change)
        cat_row.addWidget(self.category_edit, 1)
        clear_cat = QPushButton("Clear")
        clear_cat.setProperty("variant", "ghost")
        clear_cat.setFixedWidth(70)
        clear_cat.clicked.connect(self._clear_category)
        cat_row.addWidget(clear_cat)
        cat_h.addLayout(cat_row)
        layout.addWidget(cat_box)

        # Tags row
        tags_box = QWidget()
        tags_h = QVBoxLayout(tags_box)
        tags_h.setContentsMargins(0, 0, 0, 0)
        tags_h.setSpacing(4)
        tags_lbl = QLabel("TAGS")
        tags_lbl.setStyleSheet(
            f"color: {PALETTE()['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        tags_h.addWidget(tags_lbl)

        # Existing tags as chips
        self.chips_w = QWidget()
        self.chips_h = QHBoxLayout(self.chips_w)
        self.chips_h.setContentsMargins(0, 0, 0, 0)
        self.chips_h.setSpacing(6)
        self.chips_h.addStretch(1)
        tags_h.addWidget(self.chips_w)

        # Input row
        add_row = QHBoxLayout()
        add_row.setSpacing(8)
        self.tag_input = QLineEdit()
        self.tag_input.setPlaceholderText("Add a tag and press Enter…")
        self.tag_input.returnPressed.connect(self._add_tag)
        add_row.addWidget(self.tag_input, 1)
        self.add_btn = QPushButton("Add")
        self.add_btn.clicked.connect(self._add_tag)
        add_row.addWidget(self.add_btn)
        tags_h.addLayout(add_row)

        # Autocomplete from common tags
        from PySide6.QtWidgets import QCompleter
        existing = self._existing_tags()
        if existing:
            completer = QCompleter(existing, self)
            completer.setCaseSensitivity(Qt.CaseInsensitive)
            self.tag_input.setCompleter(completer)

        layout.addWidget(tags_box)
        layout.addStretch(1)

        # Save button + status
        footer = QHBoxLayout()
        self.status_lbl = QLabel("")
        self.status_lbl.setStyleSheet(f"color: {PALETTE()['text_muted']}; font-size: 11px;")
        footer.addWidget(self.status_lbl)
        footer.addStretch()
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.setFixedWidth(100)
        self.save_btn.clicked.connect(self._save)
        footer.addWidget(self.save_btn)
        layout.addLayout(footer)

        self._populate()

    def _existing_tags(self) -> list[str]:
        try:
            return [t for t, _ in self.library.list_tags() if t]
        except Exception:  # noqa: BLE001
            return []

    def _populate(self) -> None:
        # Category dropdown — existing categories + free entry
        self.category_edit.blockSignals(True)
        self.category_edit.clear()
        cats = [""]  # empty = no category
        try:
            cats.extend(self.library.list_categories())
        except Exception:  # noqa: BLE001
            pass
        self.category_edit.addItems(cats)
        if self.book.category:
            idx = self.category_edit.findText(self.book.category)
            if idx >= 0:
                self.category_edit.setCurrentIndex(idx)
            else:
                self.category_edit.setEditText(self.book.category)
        self.category_edit.blockSignals(False)
        self._tags: list[str] = list(self.book.display_tags)
        self._render_chips()
        self.status_lbl.setText("saved")
        self._dirty = False

    def _render_chips(self) -> None:
        # Clear old chips (but keep the trailing stretch)
        while self.chips_h.count() > 1:
            it = self.chips_h.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        # Insert chips at index 0 (before stretch)
        for i, tag in enumerate(self._tags):
            chip = self._chip(tag, i)
            self.chips_h.insertWidget(i, chip)

    def _chip(self, tag: str, idx: int) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(4)
        lab = QLabel(tag)
        lab.setStyleSheet(
            f"background:{PALETTE()['bg_elev']}; color:{PALETTE()['accent']};"
            f" padding:4px 6px 4px 12px; border-radius:10px; font-size:12px;"
        )
        h.addWidget(lab)
        rm = QPushButton("✕")
        rm.setFixedSize(20, 20)
        rm.setProperty("variant", "ghost")
        rm.setStyleSheet(
            f"QPushButton {{ background:transparent; color:{PALETTE()['text_muted']};"
            f" border:none; font-size:12px; }}"
            f"QPushButton:hover {{ color:{PALETTE()['error']}; }}"
        )
        rm.clicked.connect(lambda _, i=idx: self._remove_tag(i))
        h.addWidget(rm)
        return w

    def _add_tag(self) -> None:
        text = self.tag_input.text().strip()
        if not text:
            return
        if any(t.lower() == text.lower() for t in self._tags):
            self.tag_input.clear()
            return
        self._tags.append(text)
        self.tag_input.clear()
        self._render_chips()
        self._mark_dirty()

    def _remove_tag(self, idx: int) -> None:
        if 0 <= idx < len(self._tags):
            del self._tags[idx]
            self._render_chips()
            self._mark_dirty()

    def _clear_category(self) -> None:
        self.category_edit.setEditText("")
        self._mark_dirty()

    def _on_change(self, _text: str) -> None:
        self._mark_dirty()

    def _mark_dirty(self) -> None:
        self._dirty = True
        self.status_lbl.setText("● unsaved")
        self.status_lbl.setStyleSheet(f"color: {PALETTE()['warning']}; font-size: 11px;")

    def _save(self) -> None:
        cat = self.category_edit.currentText().strip() or None
        try:
            self.library.set_book_category(self.book.id, cat)
            self.library.set_book_tags(self.book.id, self._tags)
        except Exception as exc:  # noqa: BLE001
            self.status_lbl.setText(f"error: {exc}")
            self.status_lbl.setStyleSheet(f"color: {PALETTE()['error']}; font-size: 11px;")
            return
        # Update the book object in-place
        self.book.category = cat
        self.book.tags = list(self._tags)
        self.status_lbl.setText("saved")
        self.status_lbl.setStyleSheet(f"color: {PALETTE()['text_muted']}; font-size: 11px;")
        self._dirty = False


# ----------------------------------------------------------------- text editor tab


class BookEditView(QWidget):
    """Edit a book's text directly — fix OCR, clean garbage, re-chunk + re-embed.

    Shows all chunks concatenated in a monospace editor. Save replaces the vectors;
    Revert reloads from the current chunks.
    """

    reembedded = Signal(int)  # emitted after save with new chunk count

    def __init__(
        self,
        book: Book,
        vectors: VectorStore,
        library: Library,
        ollama: OllamaClient,
        preset: Preset,
    ) -> None:
        super().__init__()
        self.book = book
        self.vectors = vectors
        self.library = library
        self.ollama = ollama
        self.preset = preset
        self._chunks: list[dict] = []
        self._dirty = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar
        tb = QWidget()
        tb.setStyleSheet(
            f"background: {PALETTE()['bg_elev']}; border-bottom: 1px solid {PALETTE()['border']};"
        )
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(20, 10, 20, 10)
        tbh.setSpacing(8)

        self.status_lbl = QLabel("loading…")
        self.status_lbl.setStyleSheet(f"color: {PALETTE()['text_muted']}; font-size: 11px;")
        tbh.addWidget(self.status_lbl)
        tbh.addStretch()

        self.save_btn = QPushButton("Save & Re-embed")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.setEnabled(False)
        self.save_btn.clicked.connect(self._save)
        self.save_btn.setToolTip("Re-chunk and re-embed all text. Overwrites old index.")
        tbh.addWidget(self.save_btn)

        self.revert_btn = QPushButton("Revert")
        self.revert_btn.setProperty("variant", "ghost")
        self.revert_btn.clicked.connect(self._revert)
        self.revert_btn.setToolTip("Discard changes and reload original text.")
        tbh.addWidget(self.revert_btn)

        self.editor = QPlainTextEdit()
        self.editor.setPlaceholderText(
            "Book text will appear here after loading…"
        )
        monofont = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        monofont.setPointSize(12)
        self.editor.setFont(monofont)
        self.editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {PALETTE()['bg_elev']}; color: {PALETTE()['text']};"
            f" border: none; padding: 24px 32px;"
            f" selection-background-color: {PALETTE()['selection']};"
            f" line-height: 1.6;"
            f"}}"
        )
        self.editor.textChanged.connect(self._on_text_changed)
        self.editor.setTabStopDistance(
            QFontMetricsF(monofont).horizontalAdvance("    ") * 4
        )

        splitter = QSplitter(Qt.Horizontal)

        # Chapter navigator
        nav_w = QWidget()
        nav_w.setStyleSheet(
            f"background: {PALETTE()['bg']}; border-right: 1px solid {PALETTE()['border']};"
        )
        nav_l = QVBoxLayout(nav_w)
        nav_l.setContentsMargins(0, 0, 0, 0)
        nav_l.setSpacing(0)
        head = QLabel("Sections")
        head.setStyleSheet(
            f"color: {PALETTE()['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
            f" padding: 16px 16px 8px 16px;"
        )
        nav_l.addWidget(head)
        self.nav = QListWidget()
        self.nav.setFrameShape(QFrame.NoFrame)
        self.nav.setStyleSheet(
            "QListWidget { padding: 4px 8px; outline: 0; }"
            "QListWidget::item { padding: 8px 10px; border-radius: 6px; }"
        )
        self.nav.currentRowChanged.connect(self._on_nav_select)
        nav_l.addWidget(self.nav, 1)

        splitter.addWidget(nav_w)
        splitter.addWidget(self.editor)
        splitter.setSizes([220, 900])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setHandleWidth(1)

        layout.addWidget(tb)
        layout.addWidget(splitter, 1)

        self._load_chunks()

    def _load_chunks(self) -> None:
        self._chunks = self.vectors.get_all_chunks(self.book.id)
        if not self._chunks:
            self.status_lbl.setText("no chunks — nothing to edit")
            self.editor.setPlaceholderText(
                "This book has no indexed chunks. Use Clean Text first to parse it."
            )
            return
        # Reconstruct full text preserving chunk order
        sections = self._reconstruct_sections()
        self._full_text = "\n\n".join(sections)
        self._original_text = self._full_text
        self.editor.setPlainText(self._full_text)
        self._populate_nav()
        chars = len(self._full_text)
        words = len(self._full_text.split())
        self.status_lbl.setText(f"{len(self._chunks)} chunks · {chars:,} chars · {words:,} words")
        self.save_btn.setEnabled(False)
        self._dirty = False

    def _reconstruct_sections(self) -> list[str]:
        """Rebuild section text preserving chapter headings."""
        out: list[str] = []
        seen_chapters: set[str] = set()
        for c in self._chunks:
            ch = c.get("chapter", "")
            text = c["text"].strip()
            if ch and ch not in seen_chapters:
                out.append(f"[CHAPTER: {ch}]\n")
                seen_chapters.add(ch)
            out.append(text)
        return out

    def _reparse(self, full_text: str) -> list[tuple[str | None, str]]:
        """Split edited text back into (chapter, text) pairs using [CHAPTER: ...] markers."""
        import re
        sections: list[tuple[str | None, str]] = []
        # Split on chapter markers
        parts = re.split(r"^\[CHAPTER: (.+)\]$", full_text, flags=re.MULTILINE)
        # parts alternates: [non-marker-text, chapter1, chapter1-text, chapter2, chapter2-text, ...]
        i = 0
        current_chapter: str | None = None
        while i < len(parts):
            part = parts[i].strip()
            if i % 2 == 0:
                # Non-chapter block
                if part:
                    sections.append((current_chapter, part))
            else:
                # Chapter name
                current_chapter = parts[i].strip()
            i += 1
        return sections

    def _populate_nav(self) -> None:
        self.nav.clear()
        seen: set[str] = set()
        for c in self._chunks:
            ch = c.get("chapter", "")
            if not ch or ch in seen:
                continue
            seen.add(ch)
            item = QListWidgetItem(_truncate_ch_label(ch, 40))
            self.nav.addItem(item)
        if self.nav.count() == 0:
            self.nav.addItem(f"All text · {len(self._chunks)} sections")

    def _on_nav_select(self, row: int) -> None:
        if row < 0:
            return
        seen: list[str] = []
        for c in self._chunks:
            ch = c.get("chapter", "")
            if ch and ch not in seen:
                seen.append(ch)
                if len(seen) - 1 == row:
                    # Scroll to this chapter
                    marker = f"[CHAPTER: {ch}]\n"
                    pos = self.editor.toPlainText().find(marker)
                    if pos >= 0:
                        cursor = self.editor.textCursor()
                        cursor.setPosition(pos)
                        self.editor.setTextCursor(cursor)
                        self.editor.ensureCursorVisible()
                    return
        # Fallback: scroll to section in order
        if row < len(self._chunks):
            text = self._chunks[row]["text"]
            pos = self.editor.toPlainText().find(text)
            if pos >= 0:
                cursor = self.editor.textCursor()
                cursor.setPosition(pos)
                self.editor.setTextCursor(cursor)
                self.editor.ensureCursorVisible()

    def _on_text_changed(self) -> None:
        if not hasattr(self, "_full_text"):
            return
        current = self.editor.toPlainText()
        is_dirty = current != self._original_text
        if is_dirty != self._dirty:
            self._dirty = is_dirty
            self.save_btn.setEnabled(is_dirty)
            if is_dirty:
                self.status_lbl.setText("● edited — save to re-embed")
                self.status_lbl.setStyleSheet(
                    f"color: {PALETTE()['warning']}; font-size: 11px;"
                )
            else:
                chars = len(current)
                words = len(current.split())
                self.status_lbl.setText(
                    f"{len(self._chunks)} chunks · {chars:,} chars · {words:,} words"
                )
                self.status_lbl.setStyleSheet(
                    f"color: {PALETTE()['text_muted']}; font-size: 11px;"
                )

    def _revert(self) -> None:
        if self._dirty:
            reply = QMessageBox.question(
                self, "Revert",
                "Discard all changes and reload the original text?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._load_chunks()

    def _save(self) -> None:
        full_text = self.editor.toPlainText().strip()
        if not full_text:
            QMessageBox.warning(self, "Empty", "Nothing to save.")
            return
        reply = QMessageBox.question(
            self, "Re-embed",
            f"This will re-chunk and re-embed all {len(self._chunks)} existing chunks.\n\n"
            "The old index will be replaced. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.status_lbl.setText("re-chunking…")
        self.status_lbl.setStyleSheet(
            f"color: {PALETTE()['accent']}; font-size: 11px;"
        )
        self.save_btn.setEnabled(False)
        QApplication.processEvents()

        try:
            # Re-parse into (chapter, text) pairs
            sections = self._reparse(full_text)
            from learnage.ingest.chunker import chunk_book, Chunk
            chunks = chunk_book(
                sections,
                target_tokens=self.preset.chunk_target_tokens,
                overlap_tokens=self.preset.chunk_overlap_tokens,
            )

            # Drop old vectors
            self.vectors.drop(self.book.id)

            # Add new chunks
            from learnage.ingest.embedder import embed_chunks
            import asyncio
            embedded = asyncio.run(
                embed_chunks(self.ollama, self.preset.embed, chunks)
            )

            # Store in Chroma
            self.vectors.add_chunks(self.book.id, embedded)

            # Update library metadata
            self.library.update_chunks(
                self.book.id,
                [(c.chunk_index, c.chapter, c.char_start, c.char_end, c.token_estimate)
                 for c in chunks],
            )

            chars = len(full_text)
            words = len(full_text.split())
            self.status_lbl.setText(
                f"saved — {len(chunks)} new chunks · {chars:,} chars · {words:,} words"
            )
            self.status_lbl.setStyleSheet(
                f"color: {PALETTE()['success']}; font-size: 11px;"
            )

            # Reload to show updated state
            self._load_chunks()
            self._original_text = full_text
            self._dirty = False
            self.reembedded.emit(len(chunks))

            QMessageBox.information(
                self, "Saved",
                f"Re-embedded {len(chunks)} chunks.\n\n"
                "Chat will now search the edited text."
            )

        except Exception as exc:
            self.status_lbl.setText(f"error: {exc}")
            self.status_lbl.setStyleSheet(
                f"color: {PALETTE()['error']}; font-size: 11px;"
            )
            self.save_btn.setEnabled(True)
            import traceback; traceback.print_exc()


# ----------------------------------------------------------------- main book window


class BookWindow(QMainWindow):
    """A book opens in its own OS window — tabs for Read / Notes / Soul / Chat."""

    closed = Signal(str)  # book_id

    def __init__(
        self,
        book: Book,
        *,
        library: Library,
        vectors: VectorStore,
        ollama: OllamaClient,
        preset: Preset,
        home: Path,
        on_submit_ingest,
        on_submit_soul,
        on_regenerate_soul,
    ) -> None:
        super().__init__()
        self.book = book
        self.home = home
        self.preset = preset

        self.setWindowTitle(book.title + (f"  ·  {book.author}" if book.author else ""))
        self.resize(1280, 820)

        # Apply stylesheet
        self.setStyleSheet(_qss())

        # Central widget: header bar + tabs + status
        central = QWidget()
        self.setCentralWidget(central)
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Slim in-window header — book title + actions (no duplicate of native title bar)
        self._build_header(outer)

        # Tabs — give the bar room by allowing it to expand naturally
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.tabBar().setExpanding(False)
        self.tabs.tabBar().setUsesScrollButtons(False)
        self.tabs.setStyleSheet(
            "QTabBar::tab { padding: 10px 22px; min-width: 90px; font-size: 13px; }"
        )

        # Read
        self.read_view = BookReadView(vectors, book)
        self.tabs.addTab(self.read_view, "✦  Read")

        # Notes
        self.notes = NotesEditor(home, book)
        self.tabs.addTab(self.notes, "✎  Notes")

        # Soul
        self.soul_view = SoulView()
        self._populate_soul(library)
        self.tabs.addTab(self.soul_view, "✺  Soul")

        # Chat
        self.chat = ChatTab(
            library=library,
            vectors=vectors,
            ollama=ollama,
            preset=preset,
            on_submit_ingest=on_submit_ingest,
            on_submit_soul=on_submit_soul,
        )
        # Per-book scope + create a named session
        import uuid
        session_id = str(uuid.uuid4())[:8]
        self.chat.set_session(session_id, [book.id])
        self.chat._add_assistant(
            f"I'm reading <b>{html_escape(book.title)}</b> with you.\n\n"
            f"Ask me anything. I'll search the text, cite passages, and ground every answer in the book."
        )
        self.tabs.addTab(self.chat, "◇  Chat")

        # Categorize — set category + tags
        self.categorize_view = CategorizeView(book=book, library=library, home=home)
        self.tabs.addTab(self.categorize_view, "⊞  Categorize")

        # Edit — raw text editor, re-chunk + re-embed on save
        self.edit_view = BookEditView(
            book=book,
            vectors=vectors,
            library=library,
            ollama=ollama,
            preset=preset,
        )
        self.tabs.addTab(self.edit_view, "✏  Edit")

        # Refresh Read view after re-embed so it shows the updated chunks
        self.edit_view.reembedded.connect(
            lambda n: self.read_view._populate() if hasattr(self, "read_view") else None
        )

        outer.addWidget(self.tabs, 1)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        sb.showMessage(
            f"{book.chunk_count or 0} chunks  ·  "
            f"soul {'✓' if book.soul_status == 'ok' else '—'}  ·  "
            f"notes auto-save"
        )

        # File menu (close + export)
        self._build_menu()

    def jump_to_chunk(self, chunk_index: int) -> bool:
        """Switch to Read tab and scroll to a specific chunk index."""
        # Find the Read tab index
        for i in range(self.tabs.count()):
            if self.tabs.tabText(i).strip().startswith("✦"):
                self.tabs.setCurrentIndex(i)
                break
        if hasattr(self, "read_view"):
            return self.read_view.jump_to_chunk(chunk_index)
        return False

    def _build_menu(self) -> None:
        bar = self.menuBar()
        file_menu = bar.addMenu("&File")

        close_act = QAction("&Close window", self)
        close_act.setShortcut(QKeySequence("Ctrl+W"))
        close_act.triggered.connect(self.close)
        file_menu.addAction(close_act)

        export_act = QAction("&Export book text…", self)
        export_act.setShortcut(QKeySequence("Ctrl+E"))
        export_act.triggered.connect(self.read_view._export)
        file_menu.addAction(export_act)

        file_menu.addSeparator()
        quit_act = QAction("&Quit Learnage", self)
        quit_act.setShortcut(QKeySequence.Quit)
        quit_act.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(quit_act)

        view = bar.addMenu("&View")
        for i, (label, idx) in enumerate([
            ("&Read", 0), ("&Notes", 1), ("&Soul", 2), ("&Chat", 3),
        ]):
            act = QAction(label, self)
            act.setShortcut(QKeySequence(f"Ctrl+{i+1}"))
            act.triggered.connect(lambda _, n=idx: self.tabs.setCurrentIndex(n))
            view.addAction(act)

    def _build_header(self, parent_layout) -> None:
        """Slim in-window header — title, author, actions, close. No duplicate of native title bar."""
        bar = QWidget()
        bar.setStyleSheet(
            f"background: {PALETTE()['panel']}; border-bottom: 1px solid {PALETTE()['border']};"
        )
        h = QHBoxLayout(bar)
        h.setContentsMargins(28, 14, 20, 14)
        h.setSpacing(14)
        # Title block (author as muted line under title)
        title_block = QVBoxLayout()
        title_block.setSpacing(0)
        title = QLabel(self.book.title)
        f = QFontDatabase.systemFont(QFontDatabase.TitleFont)
        f.setPointSize(15)
        f.setWeight(QFont.DemiBold)
        title.setFont(f)
        title.setStyleSheet(f"color: {PALETTE()['text']};")
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_block.addWidget(title)
        if self.book.author:
            author = QLabel(self.book.author)
            author.setStyleSheet(f"color: {PALETTE()['text_muted']}; font-size: 11px;")
            title_block.addWidget(author)
        h.addLayout(title_block, 1)

        # Actions
        clean = QPushButton("Clean text")
        clean.setProperty("variant", "ghost")
        clean.setToolTip("Re-parse the source file and strip page numbers, headers, OCR garbage")
        clean.clicked.connect(self._clean_text)
        h.addWidget(clean)

        regen = QPushButton("Regenerate soul")
        regen.setProperty("variant", "ghost")
        regen.clicked.connect(self._regen_soul)
        h.addWidget(regen)

        forget = QPushButton("Forget")
        forget.setProperty("variant", "ghost")
        forget.clicked.connect(self._forget)
        h.addWidget(forget)

        # Visible X close button
        close = QPushButton("✕")
        close.setFixedSize(28, 28)
        close.setToolTip("Close window")
        close.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {PALETTE()['text_muted']};"
            f" border: none; font-size: 14px; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {PALETTE()['error']}; color: white; }}"
        )
        close.clicked.connect(self.close)
        h.addWidget(close)

        parent_layout.addWidget(bar)

    def _populate_soul(self, library: Library) -> None:
        if self.book.soul_json:
            try:
                soul = SoulRecord.from_json(self.book.soul_json)
            except Exception:  # noqa: BLE001
                soul = SoulRecord()
        else:
            soul = SoulRecord()
        self.soul_view.show_soul(self.book, soul)

    def _regen_soul(self) -> None:
        # Hand off to MainWindow; close ourselves after.
        from learnage.gui.app import MainWindow
        for w in QApplication.instance().topLevelWidgets():
            if isinstance(w, MainWindow):
                w._queue_soul(self.book.id)
                break
        self.statusBar().showMessage(f"soul regeneration queued", 3000)

    def _clean_text(self) -> None:
        """Re-parse the source with aggressive sanitization, re-chunk, re-embed."""
        confirm = QMessageBox.question(
            self,
            "Clean text?",
            f"This will re-read <b>{html_escape(self.book.title)}</b> from the original file, "
            f"strip page numbers, headers, and OCR garbage, then re-chunk and re-embed.<br><br>"
            f"This takes a minute or so and uses Ollama. The book's soul and notes are kept. "
            f"Proceed?",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return

        # Show progress
        self.statusBar().showMessage("cleaning… 0%")

        # Run in a worker thread so the UI stays responsive
        from learnage.ingest.clean import clean_book_sync
        from learnage.gui.app import MainWindow

        # Find MainWindow to share its vectors / ollama / preset
        mw = None
        for w in QApplication.instance().topLevelWidgets():
            if isinstance(w, MainWindow):
                mw = w
                break
        if mw is None:
            self.statusBar().showMessage("couldn't find launcher", 4000)
            return

        class _Worker(QRunnable):
            def __init__(self_inner):
                super().__init__()
                self_inner.book_id = self.book.id

            def run(self_inner):
                def on_prog(bid, done, total):
                    pct = int(done / max(total, 1) * 100)
                    QMetaObject.invokeMethod(
                        self, "_update_clean_progress",
                        Qt.QueuedConnection,
                        Q_ARG(str, f"cleaning… {pct}%"),
                    )
                try:
                    result = clean_book_sync(
                        self_inner.book_id,
                        library=mw.library,
                        vectors=mw.vectors,
                        ollama=mw.ollama,
                        preset=mw.preset,
                        on_progress=on_prog,
                    )
                    if "error" in result:
                        QMetaObject.invokeMethod(
                            self, "_update_clean_progress",
                            Qt.QueuedConnection,
                            Q_ARG(str, f"clean failed: {result['error']}"),
                        )
                    else:
                        old_k = result["old_chars"] // 1000
                        new_k = result["new_chars"] // 1000
                        QMetaObject.invokeMethod(
                            self, "_update_clean_progress",
                            Qt.QueuedConnection,
                            Q_ARG(str, f"cleaned: {result['chunks']} chunks ({old_k}→{new_k}k chars)"),
                        )
                        # Refresh the read view to show new text
                        self.read_view._chunks = []
                        self.read_view._filtered = []
                        self.read_view.show_book(mw.library.get_book(self_inner.book_id))
                        self.read_view._apply_filter()
                except Exception as e:  # noqa: BLE001
                    QMetaObject.invokeMethod(
                        self, "_update_clean_progress",
                        Qt.QueuedConnection,
                        Q_ARG(str, f"clean error: {e}"),
                    )

        QThreadPool.globalInstance().start(_Worker())

    def _update_clean_progress(self, msg: str) -> None:
        self.statusBar().showMessage(msg, 5000)

    def _forget(self) -> None:
        confirm = QMessageBox.question(
            self,
            "Forget this book?",
            f"Remove <b>{html_escape(self.book.title)}</b> and all its chunks?<br><br>"
            "This cannot be undone.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirm != QMessageBox.Yes:
            return
        from learnage.gui.app import MainWindow
        for w in QApplication.instance().topLevelWidgets():
            if isinstance(w, MainWindow):
                w._forget_book(self.book.id)
                break
        self.close()

    def closeEvent(self, event) -> None:
        # Save notes before close
        try:
            self.notes._autosave()
        except Exception:  # noqa: BLE001
            pass
        self.closed.emit(self.book.id)
        super().closeEvent(event)
