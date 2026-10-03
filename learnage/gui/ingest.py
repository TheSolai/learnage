"""Ingest UI — drag-drop zone, ingest tab, and the categorize-confirm dialog.

Extracted from gui/app.py in v2.0. Three classes:

- DropZone — visible drop target for new files/folders.
- CategorizeConfirmDialog — pops up after dropping a folder, lets the user
  assign a category + tags to all the files inside.
- IngestTab — the right-hand pane of the launcher showing the live job queue.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Optional

from PySide6.QtCore import QPoint, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QTableWidget,
    QTableWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from learnage.gui.theme import PALETTE
from learnage.store.library import Book, Library
from learnage.worker import JobStatus


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


