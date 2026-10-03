"""Learnage native GUI — polished, dense, native Mac feel.

Design principles:
- Native macOS chrome (frameless with traffic lights; native scrollbars)
- Dense, content-first layout — pack information like Linear / Things 3
- One font family, intentional hierarchy, subtle accent
- Right-click context menus everywhere
- Keyboard shortcuts for everything
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPoint,
    QRunnable,
    QSize,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import (
    QAction,
    QColor,
    QFont,
    QFontDatabase,
    QIcon,
    QKeySequence,
    QPainter,
    QPixmap,
    QTextCursor,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QStatusBar,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from learnage.config import Preset, default_preset_name, load_preset
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Book, Library
from learnage.store.soul import SoulRecord
from learnage.store.vectors import VectorStore
from learnage.util.paths import default_home, ensure_home, library_db_path, vectors_dir
from learnage.worker import IngestJob, IngestPool, _run_job

from learnage.gui import covers
from learnage.gui.agent import AgentRunner, ToolCall
from learnage.gui.book_window import BookWindow
from learnage.store.blocklist import Blocklist


# ----------------------------------------------------------------- palette
# v2.0: extracted to learnage.gui.theme. Re-exported here so existing
# imports (`from learnage.gui.app import PALETTE, _qss, set_theme`) keep
# working during the split.

from learnage.gui.theme import (  # noqa: F401 — re-export
    PALETTE,
    PALETTE_DARK,
    PALETTE_LIGHT,
    set_theme,
    current_theme,
    _qss,
)
from learnage.gui.widgets import (  # noqa: F401 — re-export
    html_escape,
    truncate_label as _truncate_ch_label,
)


# ----------------------------------------------------------------- sidebar / book list
# v2.0: Sidebar + BookRow + BookListWidget extracted to learnage.gui.sidebar and
# learnage.gui.book_list. Re-exported here so existing imports keep working.
from learnage.gui.sidebar import Sidebar  # noqa: F401 — re-export
from learnage.gui.book_list import BookRow, BookListWidget  # noqa: F401 — re-export
from learnage.gui.chat import ChatTab, InterviewView, ToolCard  # noqa: F401 — re-export


# ----------------------------------------------------------------- soul / read view
# v2.0: SoulView + ReadView extracted to learnage.gui.views.soul / .read.
# Re-exported below so existing imports keep working.
from learnage.gui.views.soul import SoulView  # noqa: F401 — re-export
from learnage.gui.views.read import ReadView  # noqa: F401 — re-export

# ----------------------------------------------------------------- chat / interview view
# v2.0: ChatTab + ToolCard + InterviewView extracted to learnage.gui.chat.
# Re-exported below so existing imports keep working.

# ----------------------------------------------------------------- drop zone + ingest tab


class DropZone(QFrame):
    files_dropped = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.setProperty("role", "dropzone")
        self.setMinimumHeight(140)
        self.setAcceptDrops(True)

        v = QVBoxLayout(self)
        v.setAlignment(Qt.AlignCenter)
        title = QLabel("Drop books here")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 15px; font-weight: 500;"
        )
        v.addWidget(title)
        sub = QLabel("or use File ▸ Ingest (⌘I)  ·  .epub · .pdf · .docx · .txt")
        sub.setAlignment(Qt.AlignCenter)
        sub.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 11px;")
        v.addWidget(sub)

    def dragEnterEvent(self, e) -> None:
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self.setProperty("active", "true")
            self.style().unpolish(self)
            self.style().polish(self)

    def dragLeaveEvent(self, e) -> None:
        self.setProperty("active", "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dropEvent(self, e) -> None:
        self.setProperty("active", "false")
        self.style().unpolish(self)
        self.style().polish(self)
        if not e.mimeData().hasUrls():
            return
        paths = []
        for url in e.mimeData().urls():
            if url.isLocalFile():
                paths.append(Path(url.toLocalFile()))
        if paths:
            self.files_dropped.emit(paths)
        e.acceptProposedAction()


class CategorizeConfirmDialog(QDialog):
    """When a folder of books is dropped, ask for category/tag hints."""

    def __init__(self, folder: Path, file_count: int, library, parent=None):
        super().__init__(parent)
        self.library = library
        self.setWindowTitle(f"Bulk categorize — {folder.name}")
        self.setMinimumSize(540, 420)
        self.setStyleSheet(_qss())

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        head = QLabel(
            f"<b>{file_count} books</b> in <code>{html_escape(str(folder))}</code>"
        )
        head.setWordWrap(True)
        head.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 14px; padding: 4px 0;"
        )
        layout.addWidget(head)

        # Category
        cat_lbl = QLabel("CATEGORY")
        cat_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        layout.addWidget(cat_lbl)
        self.category_edit = QComboBox()
        self.category_edit.setEditable(True)
        self.category_edit.setInsertPolicy(QComboBox.NoInsert)
        # Suggest folder name as default category
        self.category_edit.addItem(folder.name)
        self.category_edit.addItem("")
        try:
            for existing in library.list_categories():
                if existing and self.category_edit.findText(existing) < 0:
                    self.category_edit.addItem(existing)
        except Exception:  # noqa: BLE001
            pass
        self.category_edit.setCurrentIndex(0)
        layout.addWidget(self.category_edit)

        # Tags
        tags_lbl = QLabel("TAGS (comma-separated, optional)")
        tags_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        layout.addWidget(tags_lbl)
        self.tags_edit = QLineEdit()
        # Suggest subfolder names as tags (the immediate subfolders of `folder`)
        sub_tags: list[str] = []
        try:
            for child in folder.iterdir():
                if child.is_dir():
                    sub_tags.append(child.name)
        except Exception:  # noqa: BLE001
            pass
        if sub_tags:
            self.tags_edit.setText(", ".join(sub_tags[:6]))
            self.tags_hint = QLabel(
                f"Auto-suggested from subfolders: {', '.join(sub_tags[:6])}"
            )
            self.tags_hint.setStyleSheet(
                f"color: {PALETTE['accent']}; font-size: 11px;"
            )
            layout.addWidget(self.tags_hint)
        self.tags_edit.setPlaceholderText("e.g. ritual, herbs, divination")
        layout.addWidget(self.tags_edit)

        # Mode
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["Apply to all", "Skip — ingest without categorizing"])
        layout.addWidget(self.mode_combo)

        layout.addStretch()

        # Buttons
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        btns.addStretch()
        self.confirm_btn = QPushButton("Categorize & Queue")
        self.confirm_btn.setProperty("variant", "primary")
        self.confirm_btn.clicked.connect(self._accept_and_save)
        btns.addWidget(self.confirm_btn)
        layout.addLayout(btns)

    def _accept_and_save(self) -> None:
        self.accept()

    def selected_category(self) -> str | None:
        if self.mode_combo.currentIndex() == 1:
            return None
        cat = self.category_edit.currentText().strip()
        return cat or None

    def selected_tags(self) -> list[str]:
        if self.mode_combo.currentIndex() == 1:
            return []
        raw = self.tags_edit.text()
        return [t.strip() for t in raw.split(",") if t.strip()]


class IngestTab(QWidget):
    def __init__(self, on_submit):
        super().__init__()
        self.on_submit = on_submit
        v = QVBoxLayout(self)
        v.setContentsMargins(40, 24, 40, 24)
        v.setSpacing(12)

        self.drop = DropZone()
        self.drop.files_dropped.connect(self._queue_paths)
        v.addWidget(self.drop)

        opts = QHBoxLayout()
        self.skip_soul = QCheckBox("Skip soul analysis")
        self.skip_soul.setChecked(True)
        opts.addWidget(self.skip_soul)
        opts.addStretch()
        opts.addWidget(QLabel("workers:"))
        self.workers_lbl = QLabel("8")
        opts.addWidget(self.workers_lbl)
        v.addLayout(opts)

        v.addWidget(QLabel("<b>Queue</b>"))

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(["state", "book", "chunks", "started", "error"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeToContents)
        self.table.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeToContents)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._table_context)
        self.table.verticalHeader().setVisible(False)
        v.addWidget(self.table, 1)

    def _queue_paths(self, paths: list[Path]) -> None:
        # Separate folders from loose files
        folders = [p for p in paths if p.is_dir()]
        loose = [p for p in paths if not p.is_dir() and p.exists()]
        if folders:
            # Take the first folder for categorization; queue everything else as-is
            self._handle_folder_drop(folders[0])
            return
        if loose:
            self.on_submit(loose, self.skip_soul.isChecked(), None, [])

    def _handle_folder_drop(self, folder: Path) -> None:
        # Expand the folder
        expanded: list[Path] = []
        for ext in ("epub", "pdf", "docx", "txt"):
            expanded.extend(folder.rglob(f"*.{ext}"))
        if not expanded:
            self.statusBar().showMessage(  # type: ignore[attr-defined]
                f"no epub/pdf/docx/txt files found in {folder}", 4000,
            )
            return
        # Find the topmost window (MainWindow) for parent dialog
        from learnage.store.library import Library
        win = self.window()
        library = getattr(win, "library", None)
        if library is None:
            # Fallback — just ingest everything
            self.on_submit(expanded, self.skip_soul.isChecked(), None, [])
            return
        dlg = CategorizeConfirmDialog(
            folder=folder, file_count=len(expanded), library=library, parent=win,
        )
        if dlg.exec() != QDialog.Accepted:
            return
        category = dlg.selected_category()
        tags = dlg.selected_tags()
        self.on_submit(expanded, self.skip_soul.isChecked(), category, tags)

    def _table_context(self, pos: QPoint) -> None:
        row = self.table.indexAt(pos).row()
        if row < 0:
            return
        menu = QMenu(self)
        copy = menu.addAction("Copy path")
        chosen = menu.exec_(self.table.viewport().mapToGlobal(pos))
        if chosen == copy:
            item = self.table.item(row, 1)
            if item:
                QApplication.clipboard().setText(item.text())

    def refresh(self, statuses, pending: int) -> None:
        self.table.setRowCount(len(statuses))
        for row, s in enumerate(statuses):
            color = {
                "queued":  PALETTE["text_muted"],
                "running": PALETTE["warning"],
                "done":    PALETTE["success"],
                "failed":  PALETTE["error"],
            }.get(s.state, PALETTE["text"])
            state_item = QTableWidgetItem(s.state)
            state_item.setForeground(QColor(color))
            self.table.setItem(row, 0, state_item)
            self.table.setItem(row, 1, QTableWidgetItem(s.job.display_name))
            self.table.setItem(row, 2, QTableWidgetItem(str(s.chunks)))
            t = time.strftime("%H:%M:%S", time.localtime(s.started_at)) if s.started_at else ""
            self.table.setItem(row, 3, QTableWidgetItem(t))
            err = (s.error or "")[:80]
            err_item = QTableWidgetItem(err)
            # Surface the full traceback / soul failure reason on hover so
            # silent soul failures don't disappear from the UI.
            if s.traceback or s.error:
                tooltip_parts = []
                if s.error:
                    tooltip_parts.append(s.error)
                if s.soul_status:
                    tooltip_parts.append(f"soul: {s.soul_status}")
                if s.traceback:
                    tooltip_parts.append("---")
                    tooltip_parts.append(s.traceback)
                err_item.setToolTip("\n".join(tooltip_parts))
            self.table.setItem(row, 4, err_item)


# ----------------------------------------------------------------- main window


class MainWindow(QMainWindow):
    def __init__(self, preset: Preset, home: Path, workers: int = 8) -> None:
        super().__init__()
        self.preset = preset
        self.home = home
        self.workers_n = workers

        self.library = Library(library_db_path(home))
        self.ollama = OllamaClient()
        self.vectors = VectorStore(vectors_dir(home), ollama=self.ollama, embed_model=preset.embed)
        self.pool = IngestPool(preset=preset, home=home, workers=workers)
        self.pool.start()

        # Mind registry
        from learnage.minds.registry import MindsStore
        self.minds_store = MindsStore(home)
        self._mind_chats: dict[str, "MindChatTab"] = {}
        self._mind_chat_indices: dict[str, int] = {}

        self._book_by_id: dict[str, Book] = {}
        self._section = "library"
        self._closed = False
        self._current_book_id: Optional[str] = None
        # Popouts are dead-code in v1 — they used to launch a separate
        # PopoutInterview window that depended on an unsupported ChatTab kwarg.
        # Popout will be reimplemented in v2 as a flag on BookWindow.
        self._popouts: dict[str, object] = {}

        self.setWindowTitle("Learnage")
        self.resize(1280, 800)
        # Show native traffic lights (frameless, but keep standard macOS chrome)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)

        self.setStyleSheet(_qss())
        self._build_ui()
        self._wire()

        # Timer — refresh library state
        self._timer = QTimer(self)
        self._timer.setInterval(2000)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # Inbox watcher
        self._inbox = self.home / "inbox"
        self._inbox.mkdir(parents=True, exist_ok=True)
        self._inbox_seen: set[str] = set()
        self._inbox_timer = QTimer(self)
        self._inbox_timer.setInterval(2000)
        self._inbox_timer.timeout.connect(self._check_inbox)
        self._inbox_timer.start()

        # Drain pool
        self._pool_timer = QTimer(self)
        self._pool_timer.setInterval(200)
        self._pool_timer.timeout.connect(self._drain_pool_once)
        self._pool_timer.start()

        # Auto-backup
        QTimer.singleShot(2000, self._maybe_backup_on_startup)

        self._refresh_library()

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        outer = QHBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Sidebar
        self.sidebar = Sidebar()
        self.sidebar.section_changed.connect(self._on_section_changed)
        self.sidebar.mind_opened.connect(self._on_mind_opened)
        self.sidebar.new_mind_requested.connect(self._on_new_mind_requested)
        self.sidebar.mind_reordered.connect(self._on_minds_reordered)
        self.sidebar.mind_sort_changed.connect(self._on_mind_sort_changed)
        outer.addWidget(self.sidebar)
        # Reflect persisted sort mode
        self.sidebar.set_sort_mode(self.minds_store.sort_mode())

        # Main: book list | queue pane
        self.split_h = QSplitter(Qt.Horizontal)
        outer.addWidget(self.split_h, 1)

        self.book_list = BookListWidget()
        self.book_list.book_selected.connect(self._on_book_selected)
        self.book_list.book_double_clicked.connect(self._on_book_double_clicked)
        self.book_list.book_context.connect(self._on_book_context)
        self.book_list.weed_requested.connect(self._open_weed_dialog)
        self.split_h.addWidget(self.book_list)

        # Right pane: stack of empty / ingest / global chat
        self.stack = QStackedWidget()
        self.empty_view = self._build_empty()
        self.stack.addWidget(self.empty_view)
        self.ingest_tab = IngestTab(self._queue_paths)
        self.stack.addWidget(self.ingest_tab)
        # Global chat — reads across ALL books
        self.global_chat = ChatTab(
            library=self.library,
            vectors=self.vectors,
            ollama=self.ollama,
            preset=self.preset,
            on_submit_ingest=self._queue_paths,
            on_submit_soul=self._queue_soul,
        )
        # Empty restriction — searches everything
        self.global_chat._restrict_book_ids = None
        self.stack.addWidget(self.global_chat)

        self._INDEX_EMPTY = 0
        self._INDEX_INGEST = 1
        self._INDEX_GLOBAL_CHAT = 2
        self.stack.setCurrentIndex(self._INDEX_EMPTY)

        self._refresh_library()
        self._refresh_mind_list()
        # Now that books are loaded, set an accurate welcome message
        n = len(self._book_by_id)
        while self.global_chat.log_v.count() > 1:
            it = self.global_chat.log_v.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self.global_chat._add_assistant(
            f"I'm reading <b>your entire library</b> with you — "
            f"<b>{n} books</b> ready when you are.\n\n"
            f"Ask me anything. I'll search across everything, cite the books I draw from, "
            f"and ground every answer in your library."
        )

        self.split_h.addWidget(self.stack)
        self.split_h.setSizes([320, 600])
        self.split_h.setStretchFactor(0, 0)
        self.split_h.setStretchFactor(1, 1)
        self.split_h.setHandleWidth(1)

        # Status bar
        sb = QStatusBar()
        self.setStatusBar(sb)
        self.status_main = QLabel(
            f'<span style="color:{PALETTE["text_muted"]}">{self.preset.name}</span>'
            f'  ·  <span style="color:{PALETTE["text_muted"]}">{self.workers_n} workers</span>'
        )
        sb.addWidget(self.status_main)
        self.status_queue = QLabel("")
        sb.addPermanentWidget(self.status_queue)

        # Track open book windows
        self._book_windows: dict[str, BookWindow] = {}
        self.blocklist = Blocklist(self.home)

    def _build_empty(self) -> QWidget:
        w = QWidget()
        w.setStyleSheet(f"background: {PALETTE['bg']};")
        v = QVBoxLayout(w)
        v.setAlignment(Qt.AlignCenter)
        v.setSpacing(14)
        # Big mark
        glyph = QLabel("◇")
        f = QFontDatabase.systemFont(QFontDatabase.TitleFont)
        f.setPointSize(72)
        f.setWeight(QFont.Light)
        glyph.setFont(f)
        glyph.setStyleSheet(
            f"color: {PALETTE['accent']}; font-weight: 200;"
        )
        glyph.setAlignment(Qt.AlignCenter)
        v.addWidget(glyph)
        # Title
        title = QLabel("Learnage")
        f2 = QFontDatabase.systemFont(QFontDatabase.TitleFont)
        f2.setPointSize(26)
        f2.setWeight(QFont.Light)
        title.setFont(f2)
        title.setStyleSheet(f"color: {PALETTE['text']};")
        title.setAlignment(Qt.AlignCenter)
        v.addWidget(title)
        # Subtitle
        sub = QLabel("Your local library, with memory.")
        sub.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 14px;")
        sub.setAlignment(Qt.AlignCenter)
        v.addWidget(sub)
        # Hint pills
        hint_row = QHBoxLayout()
        hint_row.setSpacing(12)
        hint_row.setAlignment(Qt.AlignCenter)
        for label, glyph in [
            ("Drop files anywhere", "↓"),
            ("⌘I to ingest", "I"),
            ("⌘T for light theme", "☼"),
        ]:
            pill = QLabel(f"  {glyph}  {label}  ")
            pill.setStyleSheet(
                f"background: {PALETTE['panel']}; color: {PALETTE['text_muted']};"
                f" border: 1px solid {PALETTE['border']};"
                f" border-radius: 999px; padding: 6px 12px; font-size: 11px;"
            )
            hint_row.addWidget(pill)
        v.addLayout(hint_row)
        v.addStretch(1)
        return w

    def _toggle_theme(self) -> None:
        new = "light" if current_theme() == "dark" else "dark"
        set_theme(new)
        self.setStyleSheet(_qss())
        # Propagate to open book windows
        for win in self._book_windows.values():
            win.setStyleSheet(_qss())

    # ---------------------------------------------------------------- keyboard shortcuts

    def keyPressEvent(self, e) -> None:
        mods = e.modifiers()
        key = e.key()

        # Cmd+T — toggle theme
        if key == Qt.Key_T and (mods & Qt.MetaModifier):
            self._toggle_theme()
            e.accept()
            return
        # Cmd+I — ingest (add books)
        if key == Qt.Key_I and (mods & Qt.MetaModifier):
            self.sidebar.list.setCurrentRow(5)  # "Add books" row
            e.accept()
            return
        # Cmd+, — settings
        if key == Qt.Key_Comma and (mods & Qt.MetaModifier):
            self._open_settings()
            e.accept()
            return
        # Cmd+Shift+L — focus library
        if key == Qt.Key_L and (mods & Qt.MetaModifier):
            self.sidebar.list.setCurrentRow(0)
            e.accept()
            return
        # Cmd+Shift+N — new chat session
        if key == Qt.Key_N and (mods & Qt.MetaModifier) and (mods & Qt.ShiftModifier):
            self._new_chat_active_window()
            e.accept()
            return

        super().keyPressEvent(e)

    def _new_chat_active_window(self) -> None:
        """Start a new chat session in the focused window (book window or global chat)."""
        import uuid
        # Check open book windows first
        for win in list(self._book_windows.values()):
            if win.isActiveWindow():
                session_id = str(uuid.uuid4())[:8]
                win.chat.set_session(session_id, [win.book.id])
                return
        # Global chat
        if self.stack.currentWidget() == self.global_chat:
            session_id = str(uuid.uuid4())[:8]
            self.global_chat.set_session(session_id, [])

    def _open_settings(self) -> None:
        """Show a simple settings dialog."""
        from PySide6.QtWidgets import QFormLayout

        dlg = QDialog(self)
        dlg.setWindowTitle("Settings")
        dlg.setMinimumWidth(420)
        lay = QFormLayout(dlg)

        # Theme
        theme_btn = QPushButton("Toggle theme")
        theme_btn.clicked.connect(lambda: (self._toggle_theme(), dlg.close()))
        lay.addRow("Theme", theme_btn)

        # Current preset
        cur = QLabel(self.preset.name)
        lay.addRow("Preset", cur)

        # LLM model
        llm_lbl = QLabel(self.preset.llm)
        lay.addRow("Chat model", llm_lbl)

        # Embed model
        embed_lbl = QLabel(self.preset.embed)
        lay.addRow("Embedding", embed_lbl)

        # k value
        k_lbl = QLabel(str(self.preset.retrieval_k))
        lay.addRow("Retrieval k", k_lbl)

        # Workers
        workers_lbl = QLabel(str(self.workers_n))
        lay.addRow("Workers", workers_lbl)

        # Library path
        path_lbl = QLabel(str(self.home))
        path_lbl.setWordWrap(True)
        lay.addRow("Library", path_lbl)

        close = QPushButton("Close")
        close.clicked.connect(dlg.close)
        lay.addRow("", close)

        dlg.setStyleSheet(_qss())
        dlg.exec()

    def _wire(self) -> None:
        # Frameless: support dragging the window
        self.sidebar.list.mousePressEvent = self._drag_start
        self.sidebar.list.mouseMoveEvent = self._drag_move

    def _drag_start(self, e) -> None:
        if e.button() == Qt.LeftButton:
            self._drag_pos = e.globalPos() - self.pos()
            e.accept()

    def _drag_move(self, e) -> None:
        if hasattr(self, "_drag_pos") and e.buttons() & Qt.LeftButton:
            self.move(e.globalPos() - self._drag_pos)
            e.accept()

    # ---------------------------------------------------------------- actions

    @Slot(str, object)
    def _on_section_changed(self, sid: str) -> None:
        if sid == "ingest":
            self.stack.setCurrentIndex(self._INDEX_INGEST)
            return
        if sid == "chat":
            self.stack.setCurrentIndex(self._INDEX_GLOBAL_CHAT)
            return
        self._section = sid
        self.stack.setCurrentIndex(self._INDEX_EMPTY)
        self._refresh_library()

    def _open_book(self, book_id: str, *, focus_tab: Optional[int] = None) -> None:
        """Open (or focus) a BookWindow for the given book id."""
        b = self._book_by_id.get(book_id)
        if not b:
            return
        existing = self._book_windows.get(book_id)
        if existing is not None and existing.isVisible():
            existing.raise_()
            existing.activateWindow()
            if focus_tab is not None:
                existing.tabs.setCurrentIndex(focus_tab)
            return
        win = BookWindow(
            book=b,
            library=self.library,
            vectors=self.vectors,
            ollama=self.ollama,
            preset=self.preset,
            home=self.home,
            on_submit_ingest=self._queue_paths,
            on_submit_soul=self._queue_soul,
            on_regenerate_soul=self._queue_soul,
        )
        win.closed.connect(lambda bid=book_id: self._book_windows.pop(bid, None))
        self._book_windows[book_id] = win
        # Position to the right of the launcher
        geo = self.geometry()
        offset = len(self._book_windows) * 24
        win.move(geo.x() + geo.width() + 12 + offset, geo.y() + offset)
        win.show()
        win.raise_()
        win.activateWindow()
        if focus_tab is not None:
            win.tabs.setCurrentIndex(focus_tab)

    def _open_book_at_chunk(self, book_id: str, chunk_index: int) -> None:
        """Open (or focus) a BookWindow and jump to a specific chunk."""
        b = self._book_by_id.get(book_id)
        if not b:
            return
        # Open or focus the book
        self._open_book(book_id)
        win = self._book_windows.get(book_id)
        if not win:
            return
        # Switch to Read tab (index 0) and jump
        from PySide6.QtCore import QTimer
        QTimer.singleShot(120, lambda: win.jump_to_chunk(chunk_index))
        self.statusBar().showMessage(
            f"jumped to {b.title} · chunk {chunk_index}", 3000,
        )

    def _seed_chat(self, prompt: str, book_id: str) -> None:
        bw = self._book_windows.get(book_id)
        if bw is None:
            return
        bw.chat.input.setText(prompt)
        bw.chat.input.setFocus()
        bw.chat._on_send()

    def _forget_book(self, book_id: str) -> None:
        b = self._book_by_id.get(book_id)
        if not b:
            return
        self.vectors.drop(b.id)
        self.library.delete_book(b.id)
        # Remember forever — never re-ingest this path
        try:
            self.blocklist.add(b.source_path)
        except Exception:  # noqa: BLE001
            pass
        # Close the window if open
        win = self._book_windows.pop(book_id, None)
        if win:
            win.close()
        self.statusBar().showMessage(f"forgot {b.title} permanently", 3000)
        self._refresh_library()

    @Slot(str)
    def _on_book_selected(self, bid: str) -> None:
        self._open_book(bid)

    @Slot(str)
    def _on_book_double_clicked(self, bid: str) -> None:
        self._open_book(bid, focus_tab=0)  # Read tab

    @Slot(str, object)
    def _on_book_context(self, bid: str, pos) -> None:
        b = self._book_by_id.get(bid)
        if not b:
            return
        # Detect multi-select
        selected_ids = self._book_list_selected_ids()
        multi = len(selected_ids) > 1
        menu = QMenu(self)

        if multi:
            n = len(selected_ids)
            menu.addAction(f"{n} books selected").setEnabled(False)
            menu.addSeparator()
            open_all = menu.addAction(f"Open all {n}")
            bulk_cat_act = menu.addAction("⊞ Bulk categorize…")
            bulk_tag_act = menu.addAction("⊞ Bulk add tags…")
            clear_cat_act = menu.addAction("⊞ Clear category")
            menu.addSeparator()
            forget_all = menu.addAction(
                f"✗ Forget all {n}  (will not be re-ingested)"
            )
            chosen = menu.exec_(pos)
            if chosen == open_all:
                for sbid in selected_ids:
                    self._open_book(sbid, focus_tab=0)
            elif chosen == bulk_cat_act:
                self._bulk_categorize(selected_ids)
            elif chosen == bulk_tag_act:
                self._bulk_tag(selected_ids)
            elif chosen == clear_cat_act:
                n_done = self.library.bulk_set_category(selected_ids, None)
                self._refresh_library()
                self.statusBar().showMessage(
                    f"cleared category on {n_done} book{'s' if n_done != 1 else ''}",
                    3000,
                )
            elif chosen == forget_all:
                self._bulk_forget(selected_ids)
            return

        # Single-book menu
        open_act = menu.addAction("Open")
        read_act = menu.addAction("    Open · Read")
        notes_act = menu.addAction("    Open · Notes")
        chat_act = menu.addAction("    Open · Chat (this book)")
        menu.addSeparator()

        # AI actions
        ai_menu = menu.addMenu("◇ Ask AI")
        ask_act = ai_menu.addAction("What is this book about?")
        sum_act = ai_menu.addAction("Summarize the soul")
        quote_act = ai_menu.addAction("Extract 5 key passages")
        themes_act = ai_menu.addAction("List the main themes")
        menu.addSeparator()

        soul_act = menu.addAction(
            "✺ Regenerate soul" if b.soul_status == "ok" else "✺ Generate soul"
        )
        menu.addSeparator()

        copy_act = menu.addAction("Copy title")
        copy_author = menu.addAction("Copy author")
        menu.addSeparator()

        # Danger zone
        forget_act = menu.addAction("Forget (will not be re-ingested)")

        chosen = menu.exec_(pos)
        if chosen == open_act:
            self._open_book(bid, focus_tab=0)
        elif chosen == read_act:
            self._open_book(bid, focus_tab=0)
        elif chosen == notes_act:
            self._open_book(bid, focus_tab=1)
        elif chosen == chat_act:
            self._open_book(bid, focus_tab=3)
        elif chosen == soul_act:
            self._queue_soul(bid)
        elif chosen == copy_act:
            QApplication.clipboard().setText(b.title)
        elif chosen == copy_author:
            QApplication.clipboard().setText(b.author or "")
        elif chosen == forget_act:
            self._forget_book(bid)
        elif chosen in (ask_act, sum_act, quote_act, themes_act):
            prompts = {
                ask_act: "What is this book about? Give me a clear, grounded summary.",
                sum_act: "Summarize the soul of this book — its themes, voice, and key tensions.",
                quote_act: "Extract 5 key passages from this book that capture its essence.",
                themes_act: "List the main themes of this book and explain each briefly.",
            }
            prompt = prompts[chosen]
            self._open_book(bid, focus_tab=3)
            QTimer.singleShot(
                400,
                lambda: self._seed_chat(prompt, bid),
            )

    def _book_list_selected_ids(self) -> list[str]:
        ids: list[str] = []
        for it in self.book_list.list.selectedItems():
            bid = it.data(Qt.UserRole)
            if bid:
                ids.append(bid)
        return ids

    def _bulk_categorize(self, book_ids: list[str]) -> None:
        """Set category on many books via a small dialog."""
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Bulk categorize — {len(book_ids)} books")
        dlg.setMinimumSize(480, 220)
        dlg.setStyleSheet(_qss())
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f"<b>{len(book_ids)} books</b> selected. Pick a category:"
        ))
        cat_edit = QComboBox()
        cat_edit.setEditable(True)
        cat_edit.setInsertPolicy(QComboBox.NoInsert)
        cat_edit.addItem("")
        try:
            for existing in self.library.list_categories():
                if existing:
                    cat_edit.addItem(existing)
        except Exception:  # noqa: BLE001
            pass
        layout.addWidget(cat_edit)
        layout.addStretch()
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        btns.addWidget(cancel)
        btns.addStretch()
        ok = QPushButton("Set category")
        ok.setProperty("variant", "primary")
        ok.clicked.connect(dlg.accept)
        btns.addWidget(ok)
        layout.addLayout(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        cat = cat_edit.currentText().strip() or None
        n = self.library.bulk_set_category(book_ids, cat)
        self._refresh_library()
        self.statusBar().showMessage(
            f"categorized {n} book{'s' if n != 1 else ''} as '{cat}'" if cat
            else f"cleared category on {n} books",
            3000,
        )

    def _bulk_tag(self, book_ids: list[str]) -> None:
        """Add tags to many books via a small dialog."""
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Bulk add tags — {len(book_ids)} books")
        dlg.setMinimumSize(480, 240)
        dlg.setStyleSheet(_qss())
        layout = QVBoxLayout(dlg)
        layout.addWidget(QLabel(
            f"<b>{len(book_ids)} books</b> selected. Tags to add:"
        ))
        tags_edit = QLineEdit()
        tags_edit.setPlaceholderText("comma-separated: ritual, herbs, divination")
        layout.addWidget(tags_edit)
        mode_row = QHBoxLayout()
        mode_lbl = QLabel("Mode:")
        mode_row.addWidget(mode_lbl)
        mode_combo = QComboBox()
        mode_combo.addItems(["Append to existing tags", "Replace existing tags"])
        mode_row.addWidget(mode_combo)
        mode_row.addStretch()
        layout.addLayout(mode_row)
        layout.addStretch()
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        btns.addWidget(cancel)
        btns.addStretch()
        ok = QPushButton("Add tags")
        ok.setProperty("variant", "primary")
        ok.clicked.connect(dlg.accept)
        btns.addWidget(ok)
        layout.addLayout(btns)
        if dlg.exec() != QDialog.Accepted:
            return
        raw = tags_edit.text()
        tags = [t.strip() for t in raw.split(",") if t.strip()]
        if not tags:
            return
        mode = "append" if mode_combo.currentIndex() == 0 else "replace"
        n = self.library.bulk_set_tags(book_ids, tags, mode=mode)
        self._refresh_library()
        self.statusBar().showMessage(
            f"tagged {n} book{'s' if n != 1 else ''} with {len(tags)} tag{'s' if len(tags) != 1 else ''}",
            3000,
        )

    def _bulk_forget(self, book_ids: list[str]) -> None:
        reply = QMessageBox.question(
            self, "Forget books?",
            f"Permanently forget {len(book_ids)} books?\n\n"
            "Their chunks, vectors, and notes will be deleted and they "
            "will not be re-ingested from their source paths.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from learnage.store.blocklist import Blocklist
        bl = Blocklist(self.home)
        for bid in book_ids:
            b = self.library.get_book(bid)
            if b:
                self.vectors.drop(bid)
                self.library.delete_book(bid)
                try:
                    bl.add(b.source_path)
                except Exception:  # noqa: BLE001
                    pass
            win = self._book_windows.pop(bid, None)
            if win:
                win.close()
        self._refresh_library()
        self.statusBar().showMessage(
            f"forgot {len(book_ids)} book{'s' if len(book_ids) != 1 else ''}",
            3000,
        )

    def _open_weed_dialog(self) -> None:
        books = self.library.list_books()
        dlg = WeedDialog(
            books=books,
            library=self.library,
            vectors=self.vectors,
            home=self.home,
            parent=self,
        )
        dlg.exec()
        self._refresh_library()

    # ---------------------------------------------------------------- minds

    def _refresh_mind_list(self) -> None:
        try:
            minds = self.minds_store.list_all()
            self.sidebar.set_minds(minds)
        except Exception:  # noqa: BLE001
            pass

    def _on_new_mind_requested(self) -> None:
        from learnage.minds.base import Mind
        import uuid
        new_mind = Mind(
            id=str(uuid.uuid4())[:8],
            name="New Mind",
            description="",
            scope_kind="all",
            scope_values=[],
            system_prompt="",
        )
        dlg = MindDialog(new_mind, self.library, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                self.minds_store.add(dlg.mind)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Save failed", str(exc))
                return
            self._refresh_mind_list()
            self._open_mind_chat(dlg.mind.id)

    def _on_mind_opened(self, payload: str) -> None:
        # payload may be "mind_id", "mind_id:edit", "mind_id:duplicate",
        # "mind_id:delete", "mind_id:up", "mind_id:down".
        if ":" in payload:
            mind_id, action = payload.split(":", 1)
        else:
            mind_id, action = payload, "open"
        if action == "open":
            self._open_mind_chat(mind_id)
        elif action == "edit":
            self._edit_mind(mind_id)
        elif action == "duplicate":
            self._duplicate_mind(mind_id)
        elif action == "delete":
            self._delete_mind(mind_id)
        elif action == "up":
            if self.minds_store.move_up(mind_id):
                self._refresh_mind_list()
        elif action == "down":
            if self.minds_store.move_down(mind_id):
                self._refresh_mind_list()

    def _on_minds_reordered(self, ordered_ids: list) -> None:
        try:
            self.minds_store.reorder(ordered_ids)
            # Make sure the sort mode is set to manual so the order sticks
            self.minds_store.set_sort_mode("manual")
            self.sidebar.set_sort_mode("manual")
        except Exception:  # noqa: BLE001
            pass

    def _on_mind_sort_changed(self, mode: str) -> None:
        try:
            self.minds_store.set_sort_mode(mode)
            self.sidebar.set_sort_mode(mode)
            self._refresh_mind_list()
        except Exception:  # noqa: BLE001
            pass

    def _open_mind_chat(self, mind_id: str) -> None:
        mind = self.minds_store.get(mind_id)
        if not mind:
            return
        # Record usage
        try:
            self.minds_store.record_open(mind_id)
        except Exception:  # noqa: BLE001
            pass
        # Reuse if already open
        if mind_id in self._mind_chats:
            self._focus_mind_chat(mind_id)
            return
        import uuid
        chat = MindChatTab(
            mind=mind,
            library=self.library,
            vectors=self.vectors,
            ollama=self.ollama,
            preset=self.preset,
            home=self.home,
        )
        # Session: scoped to all in-scope books at the moment of opening
        from learnage.minds.base import SCOPE_MANUAL
        if mind.scope_kind == SCOPE_MANUAL:
            scope_books = list(mind.scope_values)
        else:
            scope_books = [b.id for b in mind.filter_books(self.library.list_books())]
        sid = f"mind-{mind.id}-{str(uuid.uuid4())[:6]}"
        chat.set_session(sid, scope_books)
        chat.parent_edit_requested.connect(self._edit_mind)
        chat.citation_clicked.connect(self._open_book_at_chunk)
        self._mind_chats[mind_id] = chat
        idx = self.stack.addWidget(chat)
        self._mind_chat_indices[mind_id] = idx
        self.stack.setCurrentIndex(idx)
        self.statusBar().showMessage(f"opened mind: {mind.name}", 3000)

    def _focus_mind_chat(self, mind_id: str) -> None:
        idx = self._mind_chat_indices.get(mind_id)
        if idx is not None:
            self.stack.setCurrentIndex(idx)

    def _edit_mind(self, mind_id: str) -> None:
        mind = self.minds_store.get(mind_id)
        if not mind:
            return
        dlg = MindDialog(mind, self.library, parent=self)
        if dlg.exec() == QDialog.Accepted:
            try:
                self.minds_store.update(dlg.mind)
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Save failed", str(exc))
                return
            self._refresh_mind_list()
            # If the chat is open, refresh its header
            if mind_id in self._mind_chats:
                # Replace the widget entirely (simpler than mutating header)
                idx = self._mind_chat_indices.pop(mind_id, None)
                old = self._mind_chats.pop(mind_id)
                if idx is not None:
                    self.stack.removeWidget(old)
                self._open_mind_chat(mind_id)

    def _duplicate_mind(self, mind_id: str) -> None:
        import uuid
        new_id = str(uuid.uuid4())[:8]
        src = self.minds_store.get(mind_id)
        if not src:
            return
        copy = self.minds_store.duplicate(mind_id, new_id, f"{src.name} (copy)")
        if copy:
            self._refresh_mind_list()
            self.statusBar().showMessage(f"duplicated → {copy.name}", 3000)

    def _delete_mind(self, mind_id: str) -> None:
        mind = self.minds_store.get(mind_id)
        if not mind:
            return
        if mind.is_builtin:
            QMessageBox.information(
                self, "Built-in mind",
                f"'{mind.name}' is a built-in mind and can't be deleted.\n"
                "Duplicate it instead if you want a custom version.",
            )
            return
        reply = QMessageBox.question(
            self, "Delete mind?",
            f"Delete the mind '{mind.name}'?\n\n"
            "Existing chat sessions will remain, but no new chats will use this mind.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        try:
            self.minds_store.delete(mind_id)
        except Exception as exc:  # noqa: BLE001
            QMessageBox.warning(self, "Delete failed", str(exc))
            return
        # Close any open chat
        idx = self._mind_chat_indices.pop(mind_id, None)
        old = self._mind_chats.pop(mind_id, None)
        if idx is not None and old is not None:
            self.stack.removeWidget(old)
        self._refresh_mind_list()

    # ---------------------------------------------------------------- ingest

    def _queue_paths(
        self,
        paths: list[Path],
        skip_soul: bool = True,
        category: str | None = None,
        tags: list[str] | None = None,
    ) -> list[int]:
        expanded: list[Path] = []
        for p in paths:
            if p.is_dir():
                for ext in ("epub", "pdf", "docx", "txt"):
                    expanded.extend(p.rglob(f"*.{ext}"))
            elif p.exists():
                expanded.append(p)
        # Filter out blocklisted paths
        expanded = [p for p in expanded if not self.blocklist.contains(p)]
        jids = []
        for p in expanded:
            jids.append(self.pool.submit(
                IngestJob(
                    path=str(p.resolve()),
                    skip_soul=skip_soul,
                    category=category,
                    tags=tags,
                ),
            ))
        msg = f"queued {len(expanded)} file(s)"
        if category:
            tag_count = len(tags or [])
            bits = f"category={category}"
            if tag_count:
                bits += f", {tag_count} tag{'s' if tag_count != 1 else ''}"
            msg += f"  ·  {bits}"
        self.statusBar().showMessage(msg, 3000)
        self.stack.setCurrentIndex(self._INDEX_INGEST)
        return jids

    def _queue_soul(self, book_id: str) -> None:
        b = self.library.get_book(book_id)
        if not b:
            return
        self.pool.submit(IngestJob(path=b.source_path, skip_soul=False, overwrite=False))
        self.statusBar().showMessage(f"queued soul for {b.title}", 3000)

    def _check_inbox(self) -> None:
        if self._closed:
            return
        try:
            for p in sorted(self._inbox.iterdir()):
                if not p.is_file() or p.suffix.lower() not in (".epub", ".pdf", ".docx", ".txt"):
                    continue
                key = str(p.resolve())
                if key in self._inbox_seen:
                    continue
                sz1 = p.stat().st_size
                time.sleep(0.1)
                if not p.exists():
                    continue
                if p.stat().st_size != sz1:
                    continue
                self._inbox_seen.add(key)
                self.pool.submit(IngestJob(path=str(p.resolve()), skip_soul=True))
        except Exception:  # noqa: BLE001
            pass

    def _maybe_backup_on_startup(self) -> None:
        if self._closed:
            return
        from learnage.gui.backup import last_backup_age_hours, make_backup
        age = last_backup_age_hours()
        if age is None or age > 24:
            try:
                dest = make_backup(self.home)
                if dest:
                    self.statusBar().showMessage(f"auto-backup → {dest}", 3000)
            except Exception:  # noqa: BLE001
                pass

    def _drain_pool_once(self) -> None:
        if self._closed:
            return
        pool = self.pool
        if pool._executor is None:
            return
        in_flight = sum(1 for s in pool.statuses.values() if s.state == "running")
        free = max(0, pool.workers - in_flight)
        for _ in range(free):
            try:
                job = pool.queue.get_nowait()
            except Exception:  # noqa: BLE001
                break
            jid = next(
                (j for j, s in pool.statuses.items() if s.job is job and s.state == "queued"),
                None,
            )
            if jid is None:
                continue
            pool.statuses[jid].state = "running"
            pool.statuses[jid].started_at = time.time()
            fut = pool._executor.submit(
                _run_job, job.__dict__, pool.preset.__dict__, str(pool.home)
            )
            fut.add_done_callback(pool._make_done_callback(jid, None))

    # ---------------------------------------------------------------- refresh

    def _refresh_library(self) -> None:
        try:
            books = self.library.list_books()
        except Exception:  # noqa: BLE001
            return
        new_ids = {b.id for b in books}
        old_ids = set(self._book_by_id.keys())
        if new_ids == old_ids and len(books) == len(self._book_by_id):
            return
        self._book_by_id = {b.id: b for b in books}
        self.book_list.set_books(books, filter_kind=self._section)
        # When books change, mind in-scope counts can change too
        self._refresh_mind_list()

    def _tick(self) -> None:
        if self._closed:
            return
        try:
            self._refresh_library()
        except Exception:  # noqa: BLE001
            pass
        try:
            self.ingest_tab.refresh(self.pool.all_statuses(), self.pool.pending_count)
        except Exception:  # noqa: BLE001
            pass
        s = self.pool.all_statuses()
        n_run = sum(1 for x in s if x.state == "running")
        n_done = sum(1 for x in s if x.state == "done")
        n_fail = sum(1 for x in s if x.state == "failed")
        self.status_queue.setText(
            f'<span style="color:{PALETTE["text_muted"]}">{self.pool.pending_count} queued</span>'
            f'  ·  <span style="color:{PALETTE["warning"]}">{n_run} running</span>'
            f'  ·  <span style="color:{PALETTE["success"]}">{n_done} done</span>'
            f'  ·  <span style="color:{PALETTE["error"]}">{n_fail} failed</span>'
        )

    # ---------------------------------------------------------------- close

    def closeEvent(self, event) -> None:
        self._closed = True
        for t in (self._timer, getattr(self, "_pool_timer", None),
                  getattr(self, "_inbox_timer", None)):
            if t:
                t.stop()
        try:
            self.pool.stop(wait=False)
        finally:
            try:
                self.library.close()
            except Exception:  # noqa: BLE001
                pass
            try:
                self.ollama.close()
            except Exception:  # noqa: BLE001
                pass
        super().closeEvent(event)


# ----------------------------------------------------------------- minds
# v2.0: MindDialog + MindChatTab extracted to learnage.gui.minds.
# Re-exported below so existing imports keep working.
from learnage.gui.minds import MindDialog, MindChatTab  # noqa: F401 — re-export

# ----------------------------------------------------------------- weed dialog


class WeedDialog(QDialog):
    """Bulk-remove books by quality criteria.

    Shows a list of matching books with a checkbox so the user can
    selectively deselect ones they want to keep. Confirm deletes
    everything still checked.
    """

    def __init__(self, books: list[Book], library: Library,
                 vectors, home: Path, parent=None) -> None:
        super().__init__(parent)
        self.library = library
        self.vectors = vectors
        self.home = home
        self.setWindowTitle("Weed Books")
        self.setMinimumSize(700, 500)
        self.setStyleSheet(_qss())

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Mode selector
        mode_w = QWidget()
        mode_h = QHBoxLayout(mode_w)
        mode_h.setContentsMargins(0, 0, 0, 0)
        mode_h.addWidget(QLabel("Remove books where:"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems([
            "chunk_count == 0  (broken / no text)",
            "chunk_count < 5    (too short)",
            "chunk_count < 10  (too short)",
            "chunk_count < 20  (possibly short)",
        ])
        self.mode_combo.currentIndexChanged.connect(self._recompute)
        mode_h.addWidget(self.mode_combo)
        mode_h.addStretch()
        layout.addWidget(mode_w)

        self.list_widget = QListWidget()
        self.list_widget.setFrameShape(QFrame.NoFrame)
        layout.addWidget(self.list_widget, 1)

        # Footer: count + buttons
        footer = QWidget()
        fh = QHBoxLayout(footer)
        fh.setContentsMargins(0, 0, 0, 0)
        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 11px;")
        fh.addWidget(self.count_lbl)
        fh.addStretch()
        self.select_all_btn = QPushButton("Select All")
        self.select_all_btn.setFixedWidth(100)
        self.select_all_btn.clicked.connect(self._select_all)
        self.deselect_all_btn = QPushButton("Deselect All")
        self.deselect_all_btn.setFixedWidth(100)
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        self.delete_btn = QPushButton("Delete Selected")
        self.delete_btn.setProperty("variant", "danger")
        self.delete_btn.setFixedWidth(130)
        self.delete_btn.clicked.connect(self._delete_selected)
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedWidth(80)
        cancel_btn.clicked.connect(self.reject)
        fh.addWidget(self.select_all_btn)
        fh.addWidget(self.deselect_all_btn)
        fh.addWidget(self.delete_btn)
        fh.addWidget(cancel_btn)
        layout.addWidget(footer)

        self._books = books
        self._recompute()

    def _criteria(self) -> tuple[str, int]:
        idx = self.mode_combo.currentIndex()
        thresholds = [0, 5, 10, 20]
        ops = ["==", "<", "<", "<"]
        return ops[idx], thresholds[idx]

    def _matching(self) -> list[Book]:
        op, thresh = self._criteria()
        result: list[Book] = []
        for b in self._books:
            cc = getattr(b, "chunk_count", 0)
            if op == "==" and cc == thresh:
                result.append(b)
            elif op == "<" and cc < thresh:
                result.append(b)
        return result

    def _recompute(self) -> None:
        self.list_widget.clear()
        matches = self._matching()
        for b in matches:
            item = QListWidgetItem()
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked)
            item.setData(Qt.ItemDataRole.UserRole, b.id)
            label = f"{b.title[:55]}{'…' if len(b.title) > 55 else ''}"
            if b.author:
                label += f"  ·  {b.author}"
            label += f"  [{b.chunk_count or 0} chunks]"
            item.setText(label)
            self.list_widget.addItem(item)
        n = len(matches)
        self.count_lbl.setText(f"{n} book{'s' if n != 1 else ''} match — all checked by default")

    def _select_all(self) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.CheckState.Checked)

    def _deselect_all(self) -> None:
        for i in range(self.list_widget.count()):
            self.list_widget.item(i).setCheckState(Qt.CheckState.Unchecked)

    def _delete_selected(self) -> None:
        checked_ids = [
            self.list_widget.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self.list_widget.count())
            if self.list_widget.item(i).checkState() == Qt.CheckState.Checked
        ]
        if not checked_ids:
            QMessageBox.information(self, "Nothing selected", "No books are checked.")
            return
        reply = QMessageBox.warning(
            self, "Delete books?",
            f"This will permanently delete {len(checked_ids)} book(s)\n"
            "from your library and block them from re-ingestion.\n\n"
            "This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        from learnage.store.blocklist import Blocklist
        bl = Blocklist(self.home)
        for bid in checked_ids:
            b = self.library.get_book(bid)
            if b:
                self.vectors.drop(bid)
                self.library.delete_book(bid)
                try:
                    bl.add(b.source_path)
                except Exception:  # noqa: BLE001
                    pass
        self.accept()


# ----------------------------------------------------------------- entry


def run_gui(*, preset_name: Optional[str], workers: int, home: Optional[Path]) -> int:
    try:
        app = QApplication.instance() or QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(True)
        home = ensure_home(home or default_home())
        preset = load_preset(preset_name or default_preset_name())
        print(f"[learnage] building window — pid={os.getpid()}", flush=True)
        win = MainWindow(preset=preset, home=home, workers=workers)
        win.show()
        win.raise_()
        win.activateWindow()
        print(f"[learnage] GUI up — pid={os.getpid()} home={home} workers={workers}", flush=True)
        rc = app.exec()
        print(f"[learnage] GUI exit code={rc}", flush=True)
        return rc
    except Exception as e:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        print(f"[learnage] startup error: {e}", flush=True)
        return 1
