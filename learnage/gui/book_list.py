"""Book list widget — the middle column of the launcher.

Extracted from app.py in v2.0. Two classes:

- ``BookRow`` — one book, with cover, title, soul status badge, chunk count.
- ``BookListWidget`` — the searchable / sortable / filterable list of books.

Signals on BookListWidget:
- book_selected(str)            — user single-clicked
- book_double_clicked(str)      — user double-clicked (open to Read tab)
- book_context(str, QPoint)     — user right-clicked (show context menu)
- bulk_action_requested(str)    — multi-select bulk action
- weed_requested()              — open the Weed dialog
"""

from __future__ import annotations

import time
from typing import Optional

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from learnage.gui import covers
from learnage.gui.theme import PALETTE
from learnage.store.library import Book


class BookRow(QFrame):
    """One book in the list — cover, title, author, status."""

    double_clicked = Signal()
    context_requested = Signal(object)  # QPoint

    def __init__(self, book: Book) -> None:
        super().__init__()
        self.book = book
        self.setObjectName("bookrow")
        self.setFixedHeight(64)
        self.setStyleSheet(
            f"QFrame#bookrow {{ background: transparent; border-radius: 8px; }}"
            f"QFrame#bookrow:hover {{ background: {PALETTE['panel']}; }}"
            f"QFrame#bookrow[selected=\"true\"] {{ background: {PALETTE['selection']}; }}"
        )

        h = QHBoxLayout(self)
        h.setContentsMargins(8, 8, 12, 8)
        h.setSpacing(10)

        cover = QLabel()
        pix = covers.extract_or_placeholder(
            {"title": book.title}, book.source_format, book.source_path,
            size=QSize(96, 144),
        )
        cover.setPixmap(pix.scaled(40, 60, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        cover.setFixedSize(40, 60)
        h.addWidget(cover)

        col = QVBoxLayout()
        col.setSpacing(2)

        title_row = QHBoxLayout()
        title_row.setSpacing(6)
        title = QLabel()
        title.setTextFormat(Qt.PlainText)  # prevent HTML injection in titles
        title.setText(book.title)
        title.setStyleSheet(
            f"color: {PALETTE['text']}; font-weight: 600; font-size: 13px;"
        )
        title.setWordWrap(False)
        title.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        title_row.addWidget(title, 1)

        # Right-side badge: soul status
        if book.soul_status == "ok":
            badge = QLabel("✺")
            badge.setStyleSheet(f"color: {PALETTE['accent']}; font-size: 12px;")
            badge.setToolTip("Soul ready")
            title_row.addWidget(badge)
        elif book.soul_status == "pending":
            badge = QLabel("·")
            badge.setStyleSheet(f"color: {PALETTE['text_dim']}; font-size: 12px;")
            title_row.addWidget(badge)
        col.addLayout(title_row)

        meta_parts = []
        if book.author:
            meta_parts.append(book.author)
        meta_parts.append(f"{book.chunk_count or 0} chunks")
        meta = QLabel("  ·  ".join(meta_parts))
        meta.setTextFormat(Qt.PlainText)
        meta.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 11px;")
        meta.setWordWrap(False)
        col.addWidget(meta)

        h.addLayout(col, 1)

    def mouseDoubleClickEvent(self, e) -> None:
        self.double_clicked.emit()
        super().mouseDoubleClickEvent(e)

    def contextMenuEvent(self, e) -> None:
        self.context_requested.emit(e.globalPos())
        e.accept()


class BookListWidget(QWidget):
    book_selected = Signal(str)
    book_double_clicked = Signal(str)
    book_context = Signal(str, object)  # book_id, QPoint
    bulk_action_requested = Signal(str)  # action name: 'categorize' | 'tag' | 'clear_category'
    weed_requested = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Toolbar: sort + count
        toolbar = QWidget()
        toolbar_h = QHBoxLayout(toolbar)
        toolbar_h.setContentsMargins(6, 4, 6, 4)
        toolbar_h.setSpacing(6)

        self.sort_combo = QComboBox()
        self.sort_combo.addItems([
            "Title ↑", "Title ↓",
            "Author ↑", "Author ↓",
            "Category ↑", "Category ↓",
            "Chunks ↓", "Chunks ↑",
            "Quality ↓",   # chunks desc, then recent
            "Recent first",
        ])
        self.sort_combo.setFixedHeight(24)
        self.sort_combo.currentIndexChanged.connect(self._refresh)
        self.sort_combo.setToolTip("Sort books")
        toolbar_h.addWidget(self.sort_combo)

        self.count_lbl = QLabel()
        self.count_lbl.setStyleSheet(f"color: {PALETTE['text_dim']}; font-size: 10px;")
        toolbar_h.addWidget(self.count_lbl)
        toolbar_h.addStretch()

        self.weed_btn = QPushButton("Weed")
        self.weed_btn.setFixedHeight(24)
        self.weed_btn.setToolTip("Remove broken or low-quality books in bulk")
        self.weed_btn.clicked.connect(self.weed_requested.emit)
        toolbar_h.addWidget(self.weed_btn)

        layout.addWidget(toolbar)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Search title or author…")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._refresh)
        layout.addWidget(self.search)

        # Filters row: category dropdown + tag chip input
        filter_row = QHBoxLayout()
        filter_row.setContentsMargins(6, 0, 6, 4)
        filter_row.setSpacing(6)
        self.cat_filter = QComboBox()
        self.cat_filter.setMinimumWidth(120)
        self.cat_filter.setToolTip("Filter by category")
        self.cat_filter.currentIndexChanged.connect(self._refresh)
        filter_row.addWidget(self.cat_filter, 1)
        self.tag_filter = QLineEdit()
        self.tag_filter.setPlaceholderText("Tag…")
        self.tag_filter.setMaximumWidth(120)
        self.tag_filter.setClearButtonEnabled(True)
        self.tag_filter.textChanged.connect(self._refresh)
        filter_row.addWidget(self.tag_filter, 1)
        layout.addLayout(filter_row)

        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.list.setUniformItemSizes(True)
        self.list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list, 1)

        self._book_by_id: dict[str, Book] = {}
        self._filter = "library"
        self._all: list[Book] = []

    def set_books(self, books: list[Book], filter_kind: str = "library") -> None:
        self._filter = filter_kind
        self._book_by_id = {b.id: b for b in books}
        # Refresh the category dropdown from the books we now know about
        try:
            cats = [""]  # 0 = all
            for b in books:
                if b.category and b.category not in cats:
                    cats.append(b.category)
            current_data = self.cat_filter.currentData()
            self.cat_filter.blockSignals(True)
            self.cat_filter.clear()
            for i, c in enumerate(cats):
                self.cat_filter.addItem("All categories" if i == 0 else c, c)
            if current_data is not None:
                idx = self.cat_filter.findData(current_data)
                if idx >= 0:
                    self.cat_filter.setCurrentIndex(idx)
            self.cat_filter.blockSignals(False)
        except Exception:  # noqa: BLE001
            pass
        if filter_kind == "souls":
            books = [b for b in books if b.soul_status == "ok"]
        elif filter_kind == "recent":
            books = books[:30]
        self._all = books
        self._refresh()

    def _refresh(self) -> None:
        q = self.search.text().strip().lower()
        cat_idx = self.cat_filter.currentIndex()
        cat = self.cat_filter.itemData(cat_idx) if cat_idx > 0 else None
        tag_q = self.tag_filter.text().strip().lower()
        visible = list(self._all)
        if cat is not None:
            visible = [b for b in visible if (b.category or "") == cat]
        if tag_q:
            visible = [b for b in visible if any(tag_q in t.lower() for t in b.display_tags)]
        if q:
            visible = [
                b for b in visible
                if q in b.title.lower() or q in (b.author or "").lower()
            ]
        # Apply sort
        sort_idx = self.sort_combo.currentIndex()
        if sort_idx == 0:
            visible.sort(key=lambda b: b.title.lower())
        elif sort_idx == 1:
            visible.sort(key=lambda b: b.title.lower(), reverse=True)
        elif sort_idx == 2:
            visible.sort(key=lambda b: (b.author or "").lower() or "~~~")
        elif sort_idx == 3:
            visible.sort(key=lambda b: (b.author or "").lower() or "~~~", reverse=True)
        elif sort_idx == 4:
            visible.sort(key=lambda b: ((b.category or "").lower() or "~~~", b.title.lower()))
        elif sort_idx == 5:
            visible.sort(key=lambda b: ((b.category or "").lower() or "~~~", b.title.lower()), reverse=True)
        elif sort_idx == 6:
            visible.sort(key=lambda b: b.chunk_count or 0, reverse=True)
        elif sort_idx == 7:
            visible.sort(key=lambda b: b.chunk_count or 0)
        elif sort_idx == 8:
            # Quality — most chunks first, then most recent
            visible.sort(key=lambda b: (
                -(b.chunk_count or 0),
                -(int(time.mktime(time.strptime(b.ingested_at, "%Y-%m-%dT%H:%M:%S")))
                  if b.ingested_at else 0,
            ))
        elif sort_idx == 9:
            visible.sort(key=lambda b: b.ingested_at or "", reverse=True)

        self.count_lbl.setText(f"{len(visible)} books")
        self.list.clear()
        for b in visible:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, b.id)
            item.setSizeHint(QSize(0, 64))
            self.list.addItem(item)
            row = BookRow(b)
            row.double_clicked.connect(lambda bid=b.id: self.book_double_clicked.emit(bid))
            row.context_requested.connect(
                lambda pos, bid=b.id: self.book_context.emit(bid, pos)
            )
            self.list.setItemWidget(item, row)

    def _on_current_changed(self, current, _prev) -> None:
        if current is None:
            return
        bid = current.data(Qt.UserRole)
        if bid:
            self.book_selected.emit(bid)

    def restore_selection(self, book_id: str) -> None:
        for i in range(self.list.count()):
            if self.list.item(i).data(Qt.UserRole) == book_id:
                self.list.setCurrentRow(i)
                return

    def current_id(self) -> Optional[str]:
        item = self.list.currentItem()
        return item.data(Qt.UserRole) if item else None