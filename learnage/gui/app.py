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


PALETTE_DARK = {
    "bg":            "#0c0c10",
    "bg_elev":       "#16161d",
    "panel":         "#1c1c24",
    "panel_hover":   "#23232d",
    "border":        "#26262f",
    "border_strong": "#363640",
    "text":          "#e8e8ee",
    "text_muted":    "#8e8e9c",
    "text_dim":      "#5e5e6e",
    "accent":        "#a78bfa",   # softer violet
    "accent_dim":    "#7c5cfa",
    "success":       "#34d399",
    "warning":       "#fbbf24",
    "error":         "#fb7185",
    "selection":     "#2a2236",
    "selection_strong":"#3a2d50",
}


PALETTE_LIGHT = {
    "bg":            "#fbfbf9",
    "bg_elev":       "#f5f5f1",
    "panel":         "#ffffff",
    "panel_hover":   "#f0efe9",
    "border":        "#e6e3da",
    "border_strong": "#cecabd",
    "text":          "#1c1b18",
    "text_muted":    "#6b6860",
    "text_dim":      "#9a978d",
    "accent":        "#6d49d6",
    "accent_dim":    "#5b3aaf",
    "success":       "#059669",
    "warning":       "#b45309",
    "error":         "#be123c",
    "selection":     "#f0ebff",
    "selection_strong":"#e0d6ff",
}


PALETTE: dict[str, str] = dict(PALETTE_DARK)
_THEME: str = "dark"


def set_theme(theme: str) -> None:
    global _THEME
    src = PALETTE_LIGHT if theme == "light" else PALETTE_DARK
    PALETTE.update(src)
    _THEME = theme


def current_theme() -> str:
    return _THEME


# ----------------------------------------------------------------- stylesheet


def _qss() -> str:
    p = PALETTE
    return f"""
    QMainWindow, QWidget {{
        background: {p['bg']};
        color: {p['text']};
        font-family: -apple-system, "SF Pro Text", "Helvetica Neue", sans-serif;
        font-size: 13px;
    }}
    QToolTip {{
        background: {p['bg_elev']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 6px 10px;
        border-radius: 6px;
        font-size: 12px;
    }}
    QMenu {{
        background: {p['bg_elev']};
        color: {p['text']};
        border: 1px solid {p['border']};
        padding: 6px;
        border-radius: 8px;
    }}
    QMenu::item {{
        padding: 7px 24px 7px 14px;
        border-radius: 5px;
        margin: 1px 0;
    }}
    QMenu::item:selected {{ background: {p['accent_dim']}; color: white; }}
    QMenu::separator {{ height: 1px; background: {p['border']}; margin: 6px 8px; }}

    QSplitter {{ background: {p['bg']}; }}
    QSplitter::handle {{ background: {p['border']}; }}
    QSplitter::handle:horizontal {{ width: 1px; }}
    QSplitter::handle:vertical {{ height: 1px; }}

    QStatusBar {{
        background: {p['bg']};
        color: {p['text_muted']};
        border-top: 1px solid {p['border']};
        font-size: 11px;
        padding: 0 8px;
    }}
    QStatusBar::item {{ border: none; }}

    QLabel {{ background: transparent; color: {p['text']}; }}
    QLabel[role="muted"] {{ color: {p['text_muted']}; }}
    QLabel[role="dim"] {{ color: {p['text_dim']}; }}

    QLineEdit {{
        background: {p['panel']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 7px;
        padding: 6px 10px;
        selection-background-color: {p['selection']};
    }}
    QLineEdit:focus {{ border-color: {p['accent_dim']}; }}

    QPushButton {{
        background: {p['panel']};
        color: {p['text']};
        border: 1px solid {p['border']};
        border-radius: 7px;
        padding: 5px 12px;
        font-weight: 500;
    }}
    QPushButton:hover {{ background: {p['panel_hover']}; border-color: {p['border_strong']}; }}
    QPushButton:pressed {{ background: {p['bg_elev']}; }}
    QPushButton[variant="primary"] {{
        background: {p['accent_dim']};
        border-color: {p['accent_dim']};
        color: white;
    }}
    QPushButton[variant="primary"]:hover {{ background: {p['accent']}; border-color: {p['accent']}; }}
    QPushButton[variant="ghost"] {{
        background: transparent;
        border: 1px solid transparent;
        padding: 4px 10px;
        color: {p['text_muted']};
    }}
    QPushButton[variant="ghost"]:hover {{ color: {p['text']}; background: {p['panel_hover']}; border-color: {p['border']}; }}

    QTabWidget::pane {{ background: transparent; border: none; padding: 0; }}
    QTabBar {{ background: transparent; border: none; qproperty-drawBase: 0; }}
    QTabBar::tab {{
        background: transparent;
        color: {p['text_muted']};
        padding: 12px 22px;
        margin: 0 2px;
        border: none;
        font-weight: 500;
        font-size: 13px;
        min-width: 80px;
    }}
    QTabBar::tab:hover {{ color: {p['text']}; }}
    QTabBar::tab:selected {{
        color: {p['text']};
        border-bottom: 2px solid {p['accent']};
    }}

    QListWidget {{
        background: transparent;
        border: none;
        outline: 0;
        padding: 4px;
    }}
    QListWidget::item {{ background: transparent; border: none; padding: 0; margin: 0; }}
    QListWidget::item:selected {{ background: {p['selection']}; border-radius: 8px; }}
    QListWidget#sidebar {{
        background: transparent;
        padding: 6px;
    }}
    QListWidget#sidebar::item {{
        padding: 7px 10px;
        border-radius: 6px;
        color: {p['text_muted']};
        font-size: 13px;
        font-weight: 500;
    }}
    QListWidget#sidebar::item:hover {{ background: {p['panel']}; color: {p['text']}; }}
    QListWidget#sidebar::item:selected {{
        background: {p['selection_strong']};
        color: {p['text']};
    }}

    QTextBrowser {{ background: transparent; border: none; padding: 0; }}
    QScrollArea {{ background: transparent; border: none; }}
    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0;
    }}
    QScrollBar::handle:vertical {{
        background: {p['border_strong']};
        border-radius: 3px;
        min-height: 30px;
    }}
    QScrollBar::handle:vertical:hover {{ background: {p['text_dim']}; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; background: transparent; }}
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{ background: transparent; }}

    QTableWidget {{
        background: {p['panel']};
        border: 1px solid {p['border']};
        border-radius: 8px;
        gridline-color: {p['border']};
    }}
    QHeaderView::section {{
        background: {p['panel_hover']};
        color: {p['text_muted']};
        padding: 6px 10px;
        border: none;
        border-bottom: 1px solid {p['border']};
        font-weight: 600;
        font-size: 10px;
        text-transform: uppercase;
        letter-spacing: 0.5px;
    }}

    QCheckBox {{ color: {p['text']}; spacing: 8px; }}
    QCheckBox::indicator {{
        width: 14px; height: 14px;
        border: 1px solid {p['border_strong']};
        border-radius: 3px;
        background: {p['panel']};
    }}
    QCheckBox::indicator:checked {{
        background: {p['accent_dim']};
        border-color: {p['accent_dim']};
    }}

    QProgressBar {{
        background: {p['panel']};
        border: 1px solid {p['border']};
        border-radius: 4px;
        text-align: center;
        color: {p['text_muted']};
        height: 6px;
    }}
    QProgressBar::chunk {{ background: {p['accent']}; border-radius: 3px; }}

    QFrame[role="dropzone"] {{
        background: {p['bg_elev']};
        border: 1.5px dashed {p['border_strong']};
        border-radius: 12px;
    }}
    QFrame[role="dropzone"][active="true"] {{
        border-color: {p['accent']};
        background: {p['selection']};
    }}
    """


# ----------------------------------------------------------------- helpers


def html_escape(s: str) -> str:
    return (s
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#39;"))


def _truncate_ch_label(s: str, n: int = 60) -> str:
    s = s.strip()
    if len(s) <= n:
        return s
    return s[: n - 1].rstrip() + "…"


# ----------------------------------------------------------------- sidebar


class Sidebar(QWidget):
    section_changed = Signal(str)
    mind_opened = Signal(str)  # mind_id
    mind_reordered = Signal(list)  # ordered list of mind_ids
    mind_sort_changed = Signal(str)  # sort mode
    new_mind_requested = Signal()

    SECTIONS = [
        ("library",   "Library",      "◇",  "books"),
        ("souls",     "Souls",        "✺",  "souls"),
        ("chat",      "Chat all",     "✦",  "global chat"),
        ("queue",     "Ingesting",    "⟳",  "queue"),
        ("recent",    "Recent",       "◴",  "recent"),
        ("ingest",    "Add books",    "＋", "ingest"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self.setFixedWidth(220)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Brand
        brand = QLabel("Learnage")
        brand.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 16px; font-weight: 600;"
            f" padding: 14px 18px 4px 18px;"
        )
        layout.addWidget(brand)

        sub = QLabel("local-first · ollama · private")
        sub.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 10px; padding: 0 18px 14px 18px;"
        )
        layout.addWidget(sub)

        # Section list
        self.list = QListWidget()
        self.list.setObjectName("sidebar")
        self.list.setFrameShape(QFrame.NoFrame)
        for sid, label, glyph, _ in self.SECTIONS:
            item = QListWidgetItem(f"  {glyph}    {label}")
            item.setData(Qt.UserRole, sid)
            item.setSizeHint(QSize(200, 30))
            self.list.addItem(item)
        self.list.setCurrentRow(0)
        self.list.currentItemChanged.connect(self._on_changed)
        layout.addWidget(self.list, 0)

        # Separator
        sep = QFrame()
        sep.setFrameShape(QFrame.HLine)
        sep.setStyleSheet(
            f"background: {PALETTE['border']}; max-height: 1px; margin: 4px 14px;"
        )
        layout.addWidget(sep)

        # Minds header row
        minds_head = QWidget()
        mh_h = QHBoxLayout(minds_head)
        mh_h.setContentsMargins(18, 8, 10, 6)
        mh_h.setSpacing(0)
        minds_lbl = QLabel("MINDS")
        minds_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        mh_h.addWidget(minds_lbl)
        mh_h.addStretch()
        self.sort_btn = QPushButton("⇅")
        self.sort_btn.setFixedSize(20, 20)
        self.sort_btn.setToolTip("Sort minds")
        self.sort_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {PALETTE['text_muted']};"
            f" border: none; font-size: 13px; }}"
            f"QPushButton:hover {{ color: {PALETTE['text']}; }}"
        )
        self.sort_btn.clicked.connect(self._show_sort_menu)
        mh_h.addWidget(self.sort_btn)
        self.new_mind_btn = QPushButton("+")
        self.new_mind_btn.setFixedSize(20, 20)
        self.new_mind_btn.setToolTip("New mind")
        self.new_mind_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {PALETTE['accent']};"
            f" border: none; font-size: 16px; font-weight: 600; }}"
            f"QPushButton:hover {{ color: {PALETTE['text']}; }}"
        )
        self.new_mind_btn.clicked.connect(self.new_mind_requested.emit)
        mh_h.addWidget(self.new_mind_btn)
        layout.addWidget(minds_head)

        # Mind list — drag-to-reorder enabled
        self.mind_list = QListWidget()
        self.mind_list.setObjectName("sidebar")
        self.mind_list.setFrameShape(QFrame.NoFrame)
        self.mind_list.itemClicked.connect(self._on_mind_clicked)
        self.mind_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mind_list.customContextMenuRequested.connect(self._mind_context_menu)
        self.mind_list.setDragDropMode(QAbstractItemView.InternalMove)
        self.mind_list.model().rowsMoved.connect(self._on_mind_drag_moved)
        self.mind_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.mind_list, 1)

        # Footer
        self.status = QLabel()
        self.status.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 10px; padding: 10px 18px;"
        )
        self.status.setWordWrap(True)
        layout.addWidget(self.status)

        # Current sort mode (updated by set_sort_mode)
        self._sort_mode = "builtin"

    def _show_sort_menu(self) -> None:
        from learnage.minds.registry import SORT_LABELS, ALL_SORTS
        menu = QMenu(self)
        acts = {}
        for s in ALL_SORTS:
            acts[s] = menu.addAction(SORT_LABELS[s])
            if s == self._sort_mode:
                acts[s].setCheckable(True)
                acts[s].setChecked(True)
        chosen = menu.exec_(self.sort_btn.mapToGlobal(QPoint(0, self.sort_btn.height())))
        if chosen:
            for s, a in acts.items():
                if chosen == a:
                    self.mind_sort_changed.emit(s)
                    return

    def set_sort_mode(self, mode: str) -> None:
        self._sort_mode = mode
        from learnage.minds.registry import SORT_LABELS
        self.sort_btn.setToolTip(f"Sort: {SORT_LABELS.get(mode, mode)}")

    def _on_mind_drag_moved(self, *_args) -> None:
        # Emit new order so MainWindow can persist it
        ids = []
        for i in range(self.mind_list.count()):
            it = self.mind_list.item(i)
            ids.append(it.data(Qt.UserRole))
        self.mind_reordered.emit(ids)

    def set_minds(self, minds: list) -> None:
        """Replace the mind list with the given Mind objects."""
        self.mind_list.clear()
        from learnage.minds.base import SCOPE_MANUAL
        for m in minds:
            if m.id == "reading":
                continue
            glyph = m.icon or "✦"
            label = m.name
            item = QListWidgetItem(f"  {glyph}    {label}")
            item.setData(Qt.UserRole, m.id)
            item.setSizeHint(QSize(200, 30))
            item.setToolTip(m.description or m.scope_description())
            # Built-ins can't be dragged
            if m.is_builtin:
                from PySide6.QtCore import Qt as _Qt
                item.setFlags(item.flags() & ~_Qt.ItemIsDragEnabled)
            self.mind_list.addItem(item)

    def _on_changed(self, current, _prev) -> None:
        if current is None:
            return
        self.section_changed.emit(current.data(Qt.UserRole))

    def _on_mind_clicked(self, item) -> None:
        mid = item.data(Qt.UserRole)
        if mid:
            self.mind_opened.emit(mid)

    def _mind_context_menu(self, pos) -> None:
        item = self.mind_list.itemAt(pos)
        if not item:
            return
        mid = item.data(Qt.UserRole)
        from learnage.minds.registry import MindsStore
        store = MindsStore(self.parent().home) if hasattr(self.parent(), "home") else None
        mind = store.get(mid) if store else None
        is_builtin = bool(mind and mind.is_builtin)
        menu = QMenu(self)
        edit_act = menu.addAction("Edit mind…")
        up_act = menu.addAction("Move up")
        down_act = menu.addAction("Move down")
        dup_act = menu.addAction("Duplicate")
        del_act = menu.addAction("Delete")
        if is_builtin:
            up_act.setEnabled(False)
            down_act.setEnabled(False)
            del_act.setEnabled(False)
        chosen = menu.exec_(self.mind_list.viewport().mapToGlobal(pos))
        if chosen == edit_act:
            self.mind_opened.emit(mid + ":edit")
        elif chosen == up_act:
            self.mind_opened.emit(mid + ":up")
        elif chosen == down_act:
            self.mind_opened.emit(mid + ":down")
        elif chosen == dup_act:
            self.mind_opened.emit(mid + ":duplicate")
        elif chosen == del_act:
            self.mind_opened.emit(mid + ":delete")

    def set_status(self, text: str) -> None:
        self.status.setText(text)


# ----------------------------------------------------------------- book list


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


# ----------------------------------------------------------------- main book list widget


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
            visible.sort(key=lambda b: (-(b.chunk_count or 0), -(int(time.mktime(time.strptime(b.ingested_at, "%Y-%m-%dT%H:%M:%S"))) if b.ingested_at else 0)))
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

    def _on_search_changed(self) -> None:
        self._refresh()

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


# ----------------------------------------------------------------- soul view


class SoulView(QScrollArea):
    def __init__(self) -> None:
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.container = QWidget()
        self.v = QVBoxLayout(self.container)
        self.v.setContentsMargins(40, 28, 40, 28)
        self.v.setSpacing(16)
        self.setWidget(self.container)
        self._placeholder()

    def _placeholder(self) -> None:
        self._clear()
        self.v.addStretch(1)

    def _clear(self) -> None:
        while self.v.count():
            it = self.v.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()

    def show_soul(self, book: Book, soul: SoulRecord) -> None:
        self._clear()
        title = QLabel()
        title.setTextFormat(Qt.PlainText)  # prevent HTML injection in titles
        title.setText(book.title)
        f = QFontDatabase.systemFont(QFontDatabase.TitleFont)
        f.setPointSize(22)
        f.setWeight(QFont.DemiBold)
        title.setFont(f)
        title.setWordWrap(True)
        title.setStyleSheet(f"color: {PALETTE['text']};")
        self.v.addWidget(title)

        if book.author:
            sub = QLabel(book.author)
            sub.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 13px;")
            self.v.addWidget(sub)

        meta = QHBoxLayout()
        meta.setSpacing(20)
        meta.setContentsMargins(0, 4, 0, 12)
        for label, value, color in [
            ("chunks", str(book.chunk_count or 0), PALETTE["text"]),
            ("format", book.source_format.upper(), PALETTE["text"]),
            ("soul", "✓" if book.soul_status == "ok" else "—",
             PALETTE["success"] if book.soul_status == "ok" else PALETTE["text_muted"]),
        ]:
            chip = QLabel(
                f'<span style="color:{PALETTE["text_muted"]};font-size:10px;'
                f'text-transform:uppercase;letter-spacing:0.6px">{label}</span> '
                f'<span style="color:{color};font-size:13px;font-weight:500">{value}</span>'
            )
            meta.addWidget(chip)
        meta.addStretch(1)
        self.v.addLayout(meta)
        self.v.addWidget(self._div())

        if soul.summary:
            self.v.addWidget(self._section_title("Summary"))
            self.v.addWidget(self._prose(soul.summary))
            self.v.addWidget(self._div())

        if soul.voice:
            self.v.addWidget(self._section_title("Voice"))
            grid = QHBoxLayout()
            grid.setSpacing(24)
            for k, v in soul.voice.items():
                col = QVBoxLayout()
                col.setSpacing(2)
                kk = QLabel(str(k))
                kk.setStyleSheet(
                    f"color: {PALETTE['text_dim']}; font-size: 10px;"
                    f" text-transform: uppercase; letter-spacing: 0.5px;"
                )
                col.addWidget(kk)
                vv = QLabel(str(v))
                vv.setStyleSheet(f"color: {PALETTE['text']}; font-size: 13px;")
                vv.setWordWrap(True)
                col.addWidget(vv)
                grid.addLayout(col, 1)
            wrap = QWidget()
            wrap.setLayout(grid)
            self.v.addWidget(wrap)
            self.v.addWidget(self._div())

        if soul.tone_words:
            self.v.addWidget(self._section_title("Tone"))
            chips = QHBoxLayout()
            chips.setSpacing(6)
            chips.setContentsMargins(0, 0, 0, 0)
            for w in soul.tone_words:
                chip = QLabel(html_escape(str(w)))
                chip.setStyleSheet(
                    f"background:{PALETTE['bg_elev']}; color:{PALETTE['text_muted']};"
                    f" padding:4px 10px; border-radius:10px; font-size:12px;"
                )
                chips.addWidget(chip)
            chips.addStretch(1)
            tone_w = QWidget(); tone_w.setLayout(chips)
            self.v.addWidget(tone_w)
            self.v.addWidget(self._div())

        if soul.meta:
            self.v.addWidget(self._section_title("Meta"))
            grid = QHBoxLayout()
            grid.setSpacing(24)
            for k, v in soul.meta.items():
                col = QVBoxLayout()
                col.setSpacing(2)
                kk = QLabel(str(k))
                kk.setStyleSheet(
                    f"color:{PALETTE['text_dim']}; font-size:10px;"
                    f" text-transform:uppercase; letter-spacing:0.5px;"
                )
                col.addWidget(kk)
                vv = QLabel(str(v))
                vv.setStyleSheet(f"color:{PALETTE['text']}; font-size:13px;")
                vv.setWordWrap(True)
                col.addWidget(vv)
                grid.addLayout(col, 1)
            wrap = QWidget(); wrap.setLayout(grid)
            self.v.addWidget(wrap)
            self.v.addWidget(self._div())

        if soul.key_concepts:
            self.v.addWidget(self._section_title("Concepts"))
            chips = QHBoxLayout()
            chips.setSpacing(6)
            chips.setContentsMargins(0, 0, 0, 0)
            for c in soul.key_concepts:
                chip = QLabel(html_escape(str(c)))
                chip.setStyleSheet(
                    f"background:{PALETTE['bg_elev']}; color:{PALETTE['accent']};"
                    f" padding:4px 10px; border-radius:10px; font-size:12px;"
                )
                chips.addWidget(chip)
            chips.addStretch(1)
            wrap = QWidget(); wrap.setLayout(chips)
            self.v.addWidget(wrap)
            self.v.addWidget(self._div())

        if soul.key_figures:
            self.v.addWidget(self._section_title("Figures"))
            chips = QHBoxLayout()
            chips.setSpacing(6)
            chips.setContentsMargins(0, 0, 0, 0)
            for f in soul.key_figures:
                chip = QLabel(html_escape(str(f)))
                chip.setStyleSheet(
                    f"background:{PALETTE['bg_elev']}; color:{PALETTE['text']};"
                    f" padding:4px 10px; border-radius:10px; font-size:12px;"
                )
                chips.addWidget(chip)
            chips.addStretch(1)
            wrap = QWidget(); wrap.setLayout(chips)
            self.v.addWidget(wrap)
            self.v.addWidget(self._div())

        if soul.questions:
            self.v.addWidget(self._section_title("Questions this book answers"))
            for q in soul.questions:
                self.v.addWidget(self._bullet(html_escape(str(q))))
            self.v.addWidget(self._div())

        if soul.quotes:
            self.v.addWidget(self._section_title("Quotes"))
            for q in soul.quotes:
                block = QLabel(
                    f'<div style="margin:6px 0;color:{PALETTE["accent"]};'
                    f'font-style:italic;font-size:15px;line-height:1.5">'
                    f'“{html_escape(str(q))}”</div>'
                )
                block.setWordWrap(True)
                block.setTextFormat(Qt.RichText)
                self.v.addWidget(block)
            self.v.addWidget(self._div())

        if soul.themes:
            self.v.addWidget(self._section_title("Themes"))
            for t in soul.themes:
                self.v.addWidget(self._bullet(
                    f'<b style="color:{PALETTE["accent"]}">{html_escape(t.get("name", ""))}</b> — '
                    f'{html_escape(t.get("gloss", ""))}'
                ))
            self.v.addWidget(self._div())

        if soul.characters:
            self.v.addWidget(self._section_title("Characters"))
            for c in soul.characters:
                self.v.addWidget(self._bullet(
                    f'<b>{html_escape(c.get("name", ""))}</b> '
                    f'<span style="color:{PALETTE["text_muted"]}">· {html_escape(c.get("role", ""))}</span> — '
                    f'{html_escape(c.get("gloss", ""))}'
                ))
            self.v.addWidget(self._div())

        if soul.plot:
            self.v.addWidget(self._section_title("Plot"))
            for k, v in soul.plot.items():
                self.v.addWidget(self._bullet(
                    f'<b style="color:{PALETTE["text_dim"]}">{html_escape(str(k))}</b> — '
                    f'{html_escape(str(v))}'
                ))
            self.v.addWidget(self._div())

        if soul.key_passages:
            self.v.addWidget(self._section_title("Key passages"))
            for kp in soul.key_passages:
                quote = html_escape(kp.get("quote", ""))
                ctx = html_escape(kp.get("context", ""))
                why = html_escape(kp.get("why", ""))
                block = QLabel(
                    f'<div style="margin:6px 0">'
                    f'<div style="color:{PALETTE["accent"]};font-style:italic;'
                    f'font-size:15px;line-height:1.5">“{quote}”</div>'
                    f'<div style="color:{PALETTE["text_muted"]};font-size:11px;'
                    f'margin-top:2px">{ctx}</div>'
                    f'<div style="color:{PALETTE["text"]};font-size:12px;'
                    f'margin-top:4px">{why}</div>'
                    f'</div>'
                )
                block.setWordWrap(True)
                block.setTextFormat(Qt.RichText)
                self.v.addWidget(block)
            self.v.addWidget(self._div())

        if soul.craft_notes:
            self.v.addWidget(self._section_title("Craft notes"))
            for n in soul.craft_notes:
                self.v.addWidget(self._bullet(html_escape(str(n))))

        self.v.addStretch(1)

    def _section_title(self, text: str) -> QLabel:
        l = QLabel(text)
        l.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px; font-weight: 700;"
            f" text-transform: uppercase; letter-spacing: 1.5px;"
        )
        return l

    def _prose(self, text: str) -> QLabel:
        l = QLabel(html_escape(text))
        f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        f.setPointSize(15)
        l.setFont(f)
        l.setWordWrap(True)
        l.setStyleSheet(f"color: {PALETTE['text']}; line-height: 1.55;")
        l.setTextFormat(Qt.RichText)
        return l

    def _bullet(self, html: str) -> QLabel:
        l = QLabel(
            f'<span style="color:{PALETTE["accent_dim"]};margin-right:8px">›</span> {html}'
        )
        l.setWordWrap(True)
        l.setTextFormat(Qt.RichText)
        l.setStyleSheet(f"color: {PALETTE['text']}; padding: 4px 0; font-size: 13px;")
        return l

    def _div(self) -> QFrame:
        line = QFrame()
        line.setFrameShape(QFrame.HLine)
        line.setStyleSheet(f"background: {PALETTE['border']}; max-height: 1px;")
        return line


# ----------------------------------------------------------------- read view


class ReadView(QWidget):
    def __init__(self, library: Library, vectors: VectorStore) -> None:
        super().__init__()
        self.library = library
        self.vectors = vectors
        self._book_id: Optional[str] = None
        self._chunks: list[dict] = []
        self._filtered: list[dict] = []
        self._base_pt = 15

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Chapter navigator
        self.nav = QListWidget()
        self.nav.setObjectName("readnav")
        self.nav.setFixedWidth(240)
        self.nav.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.nav.currentRowChanged.connect(self._on_nav_changed)
        self.nav.setContextMenuPolicy(Qt.CustomContextMenu)
        self.nav.customContextMenuRequested.connect(self._nav_context_menu)
        layout.addWidget(self.nav)

        # Body
        right = QWidget()
        right.setStyleSheet(f"background: {PALETTE['bg_elev']};")
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)

        tb = QWidget()
        tb.setStyleSheet(
            f"background: {PALETTE['bg_elev']}; border-bottom: 1px solid {PALETTE['border']};"
        )
        tbh = QHBoxLayout(tb)
        tbh.setContentsMargins(20, 10, 20, 10)
        tbh.setSpacing(8)
        self.title_lbl = QLabel("Pick a book to read")
        self.title_lbl.setTextFormat(Qt.PlainText)  # prevent HTML injection in titles
        self.title_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 14px; font-weight: 600;"
        )
        tbh.addWidget(self.title_lbl)
        tbh.addStretch()
        self.bookmark_btn = QPushButton("✦ Bookmark")
        self.bookmark_btn.setProperty("variant", "ghost")
        self.bookmark_btn.clicked.connect(self._add_bookmark)
        tbh.addWidget(self.bookmark_btn)
        self.font_minus = QPushButton("−")
        self.font_minus.setFixedWidth(28)
        self.font_minus.clicked.connect(lambda: self._bump_font(-1))
        tbh.addWidget(self.font_minus)
        self.font_plus = QPushButton("+")
        self.font_plus.setFixedWidth(28)
        self.font_plus.clicked.connect(lambda: self._bump_font(+1))
        tbh.addWidget(self.font_plus)
        rl.addWidget(tb)

        # Body — search bar above the text
        body_container = QWidget()
        body_container.setStyleSheet(f"background: {PALETTE['bg_elev']};")
        bcl = QVBoxLayout(body_container)
        bcl.setContentsMargins(0, 12, 0, 0)
        bcl.setSpacing(0)

        self.search = QLineEdit()
        self.search.setPlaceholderText("Find in this book…")
        self.search.setMaximumWidth(280)
        self.search.textChanged.connect(self._apply_filter)
        sr = QHBoxLayout()
        sr.setContentsMargins(28, 0, 28, 0)
        sr.addWidget(self.search)
        sr.addStretch()
        bcl.addLayout(sr)

        self.body = QTextBrowser()
        self.body.setOpenExternalLinks(False)
        self.body.setStyleSheet(f"QTextBrowser {{ background: {PALETTE['bg_elev']}; border: none; padding: 0; }}")
        self._apply_font()
        sc = QScrollArea()
        sc.setWidget(self.body)
        sc.setWidgetResizable(True)
        sc.setFrameShape(QFrame.NoFrame)
        bcl.addWidget(sc, 1)
        rl.addWidget(body_container, 1)

        layout.addWidget(right, 1)

    def _apply_font(self) -> None:
        f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        f.setStyleHint(QFont.Serif)
        f.setPointSize(self._base_pt)
        self.body.setFont(f)

    def show_book(self, book: Book) -> None:
        self._book_id = book.id
        self.title_lbl.setText(book.title + (f"  ·  {book.author}" if book.author else ""))
        self._chunks = self.vectors.get_all_chunks(book.id)
        self.nav.clear()
        if not self._chunks:
            self.nav.addItem("(no chunks)")
            self.body.setHtml(
                f'<div style="color:{PALETTE["text_muted"]}; padding:40px">'
                "No chunks indexed.</div>"
            )
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
        col_w = 700
        parts = [
            f"<div style='margin: 24px auto 40px auto; max-width: {col_w}px;"
            f" padding: 0 28px; font-family: Georgia, Charter, serif;"
            f" font-size: {pt}px; line-height: 1.65; color: {PALETTE['text']};'>"
        ]
        if not self._filtered:
            parts.append(
                f'<p style="color:{PALETTE["text_muted"]}; text-align:center;'
                f' padding:60px 0; font-family:-apple-system,sans-serif;">No matches.</p>'
            )
        else:
            last_ch = None
            for c in self._filtered:
                ch = c.get("chapter") or ""
                if ch != last_ch:
                    margin = "0" if last_ch is None else "32px"
                    parts.append(
                        f'<h2 style="color:{PALETTE["accent"]}; font-size: 10px;'
                        f' font-weight: 700; text-transform: uppercase;'
                        f' letter-spacing: 2px; margin: {margin} 0 14px 0;'
                        f' padding-bottom: 8px;'
                        f' border-bottom: 1px solid {PALETTE["border"]};'
                        f' font-family: -apple-system, sans-serif;">'
                        f'{html_escape(ch or "—")}</h2>'
                    )
                    last_ch = ch
                text = html_escape(c["text"])
                if self.search.text().strip():
                    text = _highlight(text, self.search.text().strip())
                parts.append(
                    f'<p style="white-space: pre-wrap; margin: 0 0 14px 0;">{text}</p>'
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

    def _bump_font(self, delta: int) -> None:
        self._base_pt = max(11, min(24, self._base_pt + delta))
        self._apply_font()
        self._render()

    def _add_bookmark(self) -> None:
        if not self._book_id or not self._filtered:
            return
        first = self._filtered[0]
        text, ok = QInputDialog.getText(self, "Bookmark", "Note (optional):")
        if not ok:
            return
        try:
            self.library.add_bookmark(
                self._book_id,
                chunk_index=first["chunk_index"],
                note=text or None,
                chapter=first.get("chapter"),
            )
            self.bookmark_btn.setText("✦ Bookmarked")
            QTimer.singleShot(1500, lambda: self.bookmark_btn.setText("✦ Bookmark"))
        except Exception:  # noqa: BLE001
            pass

    def _nav_context_menu(self, pos: QPoint) -> None:
        item = self.nav.itemAt(pos)
        if not item:
            return
        menu = QMenu(self)
        copy_action = menu.addAction("Copy chapter title")
        action = menu.exec_(QCursor.pos())
        if action == copy_action:
            QApplication.clipboard().setText(item.text())


def _highlight(text: str, query: str) -> str:
    if not query:
        return text
    return re.sub(
        f"({re.escape(query)})",
        r'<span style="background:' + PALETTE["selection_strong"] + r'">\1</span>',
        text,
        flags=re.IGNORECASE,
    )


# ----------------------------------------------------------------- interview view


class ChatTab(QWidget):
    """Chat body. Reused by InterviewView and the popout window."""

    def __init__(self, library, vectors, ollama, preset, on_submit_ingest, on_submit_soul):
        super().__init__()
        self.library = library
        self.vectors = vectors
        self.ollama = ollama
        self.preset = preset
        self.on_submit_ingest = on_submit_ingest
        self.on_submit_soul = on_submit_soul
        self._history: list[dict] = []
        self._restrict_book_ids: list[str] | None = None
        self._thinking_dots: Optional[QLabel] = None
        self._thinking_frame = 0
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(400)
        self._thinking_timer.timeout.connect(self._tick_dots)
        # Session tracking
        self._session_id: Optional[str] = None
        self._no_save: bool = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Scrollable log
        self.log = QWidget()
        self.log_v = QVBoxLayout(self.log)
        self.log_v.setContentsMargins(0, 0, 0, 0)
        self.log_v.setSpacing(10)
        self.log_v.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.log)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda mn, mx: self.scroll.verticalScrollBar().setValue(mx)
        )
        layout.addWidget(self.scroll, 1)

        # Composer
        composer = QWidget()
        composer.setStyleSheet(
            f"background: {PALETTE['bg_elev']}; border-top: 1px solid {PALETTE['border']};"
        )
        cv = QVBoxLayout(composer)
        cv.setContentsMargins(20, 12, 20, 12)
        cv.setSpacing(6)
        self.input = QLineEdit()
        self.input.setMaxLength(4000)
        self.input.setPlaceholderText("Ask anything…")
        f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        f.setPointSize(13)
        self.input.setFont(f)
        self.input.returnPressed.connect(self._on_send)
        self.input.setContextMenuPolicy(Qt.CustomContextMenu)
        self.input.customContextMenuRequested.connect(self._input_context_menu)
        cr = QHBoxLayout()
        cr.addWidget(self.input, 1)
        self.send_btn = QPushButton("Send")
        self.send_btn.setProperty("variant", "primary")
        self.send_btn.clicked.connect(self._on_send)
        cr.addWidget(self.send_btn)
        cv.addLayout(cr)
        layout.addWidget(composer)

        self._add_assistant(
            "Hi. I'm Learnage — I read every book you point at me, and I remember.\n\n"
            "Ask me anything, or tell me to add a book. I'll show my work."
        )

    def set_session(self, session_id: str, book_ids: list[str]) -> None:
        """Begin tracking a named session. Creates the DB row if it doesn't exist."""
        self._session_id = session_id
        try:
            self.library.create_session(session_id, book_ids)
        except Exception:  # noqa: BLE001 — already exists, fine
            pass
        # Restore message history from DB
        self._history = []
        rows = self.library.list_messages(session_id)
        for row in rows:
            self._history.append({"role": row["role"], "content": row["content"]})
        self._restore_history()

    def _restore_history(self) -> None:
        """Re-populate the chat log from self._history (no re-saving to DB)."""
        # Clear existing bubbles
        while self.log_v.count() > 1:
            it = self.log_v.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._no_save = True  # skip _save_message during restore
        for msg in self._history:
            role = msg.get("role", "user")
            text = msg.get("content", "")
            if role == "user":
                self._add_bubble(text, role="user")
            else:
                self._add_bubble(text, role="assistant")
        self._no_save = False

    def _save_message(self, role: str, content: str) -> None:
        """Persist a message to the current session."""
        if not self._session_id:
            return
        try:
            self.library.append_message(self._session_id, role, content)
        except Exception:  # noqa: BLE001
            pass

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape and self.input.text().strip():
            self.input.clear()
            e.accept()
        elif e.key() == Qt.Key_Return and (e.modifiers() & Qt.MetaModifier):
            self._on_send()
            e.accept()
        else:
            super().keyPressEvent(e)

    def _input_context_menu(self, pos: QPoint) -> None:
        menu = self.input.createStandardContextMenu()
        menu.addSeparator()
        menu.addAction("Clear conversation", self._clear_history)
        menu.exec_(self.input.mapToGlobal(pos))

    def _clear_history(self) -> None:
        self._history = []
        self._save_message("assistant", "(cleared)")
        # Clear log: keep only the stretch
        while self.log_v.count() > 1:
            it = self.log_v.takeAt(0)
            w = it.widget()
            if w:
                w.deleteLater()
        self._add_assistant("(cleared)")

    def _add_assistant(self, text: str) -> None:
        self._add_bubble(text, role="assistant")

    def _add_user(self, text: str) -> None:
        self._add_bubble(text, role="user")
        if not getattr(self, "_no_save", False):
            self._save_message("user", text)

    def _add_bubble(self, text: str, *, role: str) -> tuple[QWidget, QLabel, Optional[QLabel]]:
        """Add a chat bubble. Returns (wrap, bubble, thinking_dots_label).
        thinking_dots_label is only non-None for assistant bubbles."""
        wrap = QWidget()
        wb = QHBoxLayout(wrap)
        wb.setContentsMargins(40, 0, 40, 0)
        wb.setSpacing(0)

        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.RichText)
        bubble.setMaximumWidth(640)

        copy_ref: list[str] = [text]
        dots: Optional[QLabel] = None

        if role == "user":
            bubble.setStyleSheet(
                f"background: {PALETTE['accent_dim']}; color: white;"
                f" border-radius: 14px; padding: 12px 16px; font-size: 14px;"
            )
            wb.addStretch(1)
            wb.addWidget(bubble)
            dots = None
        else:
            # AI bubble: row with bubble left, copy button right
            row = QHBoxLayout()
            row.setSpacing(6)
            row.setContentsMargins(0, 0, 0, 0)
            bubble.setStyleSheet(
                f"background: {PALETTE['panel']}; color: {PALETTE['text']};"
                f" border-radius: 14px; padding: 12px 16px; font-size: 14px;"
            )
            row.addWidget(bubble, 1)
            copy_btn = QPushButton("copy")
            copy_btn.setFixedWidth(46)
            copy_btn.setFixedHeight(22)
            copy_btn.setProperty("variant", "ghost")
            copy_btn.setStyleSheet(
                f"font-size: 10px; padding: 0 4px; color: {PALETTE['text_dim']};"
            )
            copy_btn.clicked.connect(lambda _, ref=copy_ref: QApplication.clipboard().setText(ref[0]))
            copy_btn.setToolTip("Copy response")
            row.addWidget(copy_btn)
            wb.addLayout(row)
            wb.addStretch(1)

            # Thinking dots label (hidden until streaming starts)
            dots = QLabel("thinking")
            dots.setStyleSheet(
                f"color: {PALETTE['text_muted']}; font-size: 12px; font-style: italic;"
                f" padding: 2px 16px;"
            )
            dots.setVisible(False)
            self._last_copy_ref = copy_ref

        idx = self.log_v.count() - 1
        self.log_v.insertWidget(idx, wrap)
        return wrap, bubble, dots

    def _tick_dots(self) -> None:
        self._thinking_frame = (self._thinking_frame + 1) % 4
        if self._thinking_dots:
            self._thinking_dots.setText("thinking" + "." * self._thinking_frame)

    def _copy_text(self, text: str) -> None:
        QApplication.clipboard().setText(text)

    def _status_toast(self, msg: str) -> None:
        """Briefly flash a status message in the composer area."""
        for i in range(self.log_v.count()):
            w = self.log_v.itemAt(i).widget()
            if isinstance(w, QLabel) and hasattr(w, "_is_toast"):
                w.setText(msg)
                w.setVisible(True)
                QTimer.singleShot(1500, lambda ww=w: ww.setVisible(False))
                return
        lbl = QLabel(msg)
        lbl._is_toast = True
        lbl.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 11px; font-style: italic;"
            f" padding: 2px 40px;"
        )
        lbl.setAlignment(Qt.AlignCenter)
        idx = max(0, self.log_v.count() - 1)
        self.log_v.insertWidget(idx, lbl)
        QTimer.singleShot(1500, lambda: lbl.setVisible(False))

    def _add_tool_card(self, call: ToolCall) -> None:
        wrap = QWidget()
        wb = QHBoxLayout(wrap)
        wb.setContentsMargins(40, 0, 40, 0)
        card = ToolCard(call)
        wb.addWidget(card, 1)
        idx = self.log_v.count() - 1
        self.log_v.insertWidget(idx, wrap)
        card.setContextMenuPolicy(Qt.CustomContextMenu)
        card.customContextMenuRequested.connect(
            lambda pos, c=call: self._tool_context_menu(c, pos)
        )

    def _tool_context_menu(self, call: ToolCall, pos: QPoint) -> None:
        menu = QMenu(self)
        copy_args = menu.addAction("Copy args")
        copy_res = menu.addAction("Copy result")
        chosen = menu.exec_(QCursor.pos())
        clip = QApplication.clipboard()
        if chosen == copy_args:
            clip.setText(json.dumps(call.arguments, default=str, indent=2))
        elif chosen == copy_res:
            clip.setText(json.dumps(call.result, default=str, indent=2))

    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._add_user(text)
        self._history.append({"role": "user", "content": text})
        _wrap, bubble, dots = self._add_bubble("", role="assistant")
        if dots is not None:
            dots.setVisible(False)
        self._thinking_dots = dots
        self._pending: list[str] = []
        self._run_agent(text, bubble)

    def _run_agent(self, text: str, bubble: QLabel) -> None:
        # Show and animate thinking indicator
        if self._thinking_dots:
            self._thinking_dots.setVisible(True)
            self._thinking_frame = 0
            self._thinking_timer.start()

        runner = AgentRunner(
            question=text,
            history=self._history[:-1],
            preset=self.preset,
            ollama=self.ollama,
            library=self.library,
            vectors=self.vectors,
            on_submit_ingest=self.on_submit_ingest,
            on_submit_soul=self.on_submit_soul,
            restrict_book_ids=self._restrict_book_ids,
        )

        def on_token(t: str) -> None:
            self._thinking_timer.stop()
            if self._thinking_dots:
                self._thinking_dots.setVisible(False)
            self._pending.append(t)
            full = "".join(self._pending)
            bubble.setText(html_escape(full))
            if hasattr(self, "_last_copy_ref"):
                self._last_copy_ref[0] = full

        def on_tool_start(call: ToolCall) -> None:
            self._thinking_timer.stop()
            if self._thinking_dots:
                self._thinking_dots.setVisible(False)
            self._add_tool_card(call)

        def on_tool_finish(call: ToolCall) -> None:
            for i in range(self.log_v.count() - 1, -1, -1):
                it = self.log_v.itemAt(i)
                w = it.widget() if it else None
                if isinstance(w, QWidget):
                    inner = w.findChild(ToolCard)
                    if inner and inner.call is call:
                        inner._render()
                        break

        def on_final(full: str) -> None:
            self._thinking_timer.stop()
            if self._thinking_dots:
                self._thinking_dots.setVisible(False)
            self._history.append({"role": "assistant", "content": full})
            if not getattr(self, "_no_save", False):
                self._save_message("assistant", full)

        def on_error(msg: str) -> None:
            self._thinking_timer.stop()
            if self._thinking_dots:
                self._thinking_dots.setVisible(False)
            bubble.setText(f'<span style="color:{PALETTE["error"]}">{html_escape(msg)}</span>')

        runner.signals.token.connect(on_token)
        runner.signals.tool_call_started.connect(on_tool_start)
        runner.signals.tool_call_finished.connect(on_tool_finish)
        runner.signals.final.connect(on_final)
        runner.signals.error.connect(on_error)
        QThreadPool.globalInstance().start(runner)


# ----------------------------------------------------------------- thinking indicator (class removed — animation lives in ChatTab._thinking_timer)


class ToolCard(QFrame):
    def __init__(self, call: ToolCall) -> None:
        super().__init__()
        self.call = call
        self.setStyleSheet(
            f"QFrame {{ background: {PALETTE['panel']}; border: 1px solid {PALETTE['border']};"
            f" border-radius: 10px; }}"
            f"QFrame:hover {{ border-color: {PALETTE['border_strong']}; }}"
        )
        v = QVBoxLayout(self)
        v.setContentsMargins(12, 8, 12, 10)
        v.setSpacing(4)
        self.head = QLabel()
        self.head.setTextFormat(Qt.RichText)
        v.addWidget(self.head)
        self.body = QLabel()
        self.body.setTextFormat(Qt.RichText)
        self.body.setWordWrap(True)
        self.body.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 11px;")
        v.addWidget(self.body)
        self._render()

    def _render(self) -> None:
        glyph = {
            "search_library": "🔍",
            "list_books": "📚",
            "read_soul": "✺",
            "ingest": "⬇",
            "generate_soul": "✺",
            "forget": "✗",
        }.get(self.call.name, "·")
        ok = self.call.error is None
        mark = "✓" if ok else "✗"
        color = PALETTE["success"] if ok else PALETTE["error"]
        dur = round((self.call.finished_at or time.time()) - self.call.started_at, 2)
        self.head.setText(
            f'<span style="color:{color}">{mark}</span> '
            f'<span style="color:{PALETTE["text"]}">{glyph} <b>{html_escape(self.call.name)}</b></span> '
            f'<span style="color:{PALETTE["text_dim"]}">· {dur}s</span>'
        )
        args_str = json.dumps(self.call.arguments, default=str)[:200]
        result_str = json.dumps(self.call.result, default=str)[:300]
        self.body.setText(
            f'<b style="color:{PALETTE["text_dim"]}">args</b> '
            f'<span style="font-family:monospace">{html_escape(args_str)}</span><br>'
            f'<b style="color:{PALETTE["text_dim"]}">result</b> '
            f'<span style="font-family:monospace">{html_escape(result_str)}</span>'
        )


# ----------------------------------------------------------------- interview view


class InterviewView(QWidget):
    popout_requested = Signal(str)

    def __init__(self, library, vectors, ollama, preset, on_submit_ingest, on_submit_soul):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        header = QWidget()
        header.setStyleSheet(
            f"background: {PALETTE['bg_elev']}; border-bottom: 1px solid {PALETTE['border']};"
        )
        h = QVBoxLayout(header)
        h.setContentsMargins(28, 14, 28, 14)
        h.setSpacing(4)
        title = QLabel("Interview")
        title.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 16px; font-weight: 600;"
        )
        h.addWidget(title)
        self.subtitle = QLabel("Pick a book to interview")
        self.subtitle.setTextFormat(Qt.PlainText)
        self.subtitle.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 12px;")
        h.addWidget(self.subtitle)

        self.session_lbl = QLabel("")
        self.session_lbl.setStyleSheet(f"color: {PALETTE['text_dim']}; font-size: 10px;")
        self.session_lbl.setVisible(False)
        h.addWidget(self.session_lbl)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        actions.addStretch()
        self.newchat_btn = QPushButton("✛ New chat")
        self.newchat_btn.setProperty("variant", "ghost")
        self.newchat_btn.clicked.connect(self._on_new_chat)
        actions.addWidget(self.newchat_btn)
        self.history_btn = QPushButton("⊞ History")
        self.history_btn.setProperty("variant", "ghost")
        self.history_btn.clicked.connect(self._on_history)
        actions.addWidget(self.history_btn)
        self.popout_btn = QPushButton("↗ Pop out")
        self.popout_btn.setProperty("variant", "ghost")
        self.popout_btn.clicked.connect(self._on_popout)
        actions.addWidget(self.popout_btn)
        h.addLayout(actions)
        layout.addWidget(header)

        # Body
        self.chat = ChatTab(
            library=library, vectors=vectors, ollama=ollama,
            preset=preset, on_submit_ingest=on_submit_ingest,
            on_submit_soul=on_submit_soul,
        )
        layout.addWidget(self.chat, 1)

    def show_book(self, book: Book) -> None:
        import uuid
        self._book_id = book.id
        self.subtitle.setTextFormat(Qt.PlainText)
        self.subtitle.setText(f"with {book.title}")
        self.chat._restrict_book_ids = [book.id]
        # Create a new session for this book
        session_id = str(uuid.uuid4())[:8]
        self.chat.set_session(session_id, [book.id])
        self.session_lbl.setText(f"session: {session_id}")
        self.session_lbl.setVisible(True)
        self.chat._add_assistant(
            f"I'm now reading <b>{html_escape(book.title)}</b> with you.\n\n"
            f"Ask me anything about it. I'll search the text, cite passages, and "
            f"ground every answer in the book."
        )

    def _on_new_chat(self) -> None:
        """Start a new session for the current book."""
        if not hasattr(self, "_book_id") or not self._book_id:
            return
        book_ids = self.chat._restrict_book_ids or []
        if not book_ids:
            return
        import uuid
        session_id = str(uuid.uuid4())[:8]
        self.chat.set_session(session_id, book_ids)
        self.session_lbl.setText(f"session: {session_id}")
        self.chat._add_assistant(
            "New session started. What's on your mind?"
        )

    def _on_history(self) -> None:
        if not hasattr(self, "_book_id") or not self._book_id:
            return
        sessions = self.chat.library.list_sessions(book_id=self._book_id)
        if not sessions:
            QMessageBox.information(self, "History", "No previous sessions for this book.")
            return
        # Show session picker
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Session history — {getattr(self, '_book_id', '')[:8]}")
        dlg.setMinimumWidth(500)
        lay = QVBoxLayout(dlg)
        lay.setSpacing(8)
        for s in sessions[:20]:
            sid = s["id"]
            ts = s.get("started_at", "?")[:19]
            ended = s.get("ended_at")
            dur = ""
            if ended:
                try:
                    from datetime import datetime
                    start = datetime.fromisoformat(s["started_at"])
                    end = datetime.fromisoformat(ended)
                    dur = f" · {int((end-start).total_seconds())}s"
                except Exception:  # noqa: BLE001
                    pass
            first_msg = ""
            msgs = self.chat.library.list_messages(sid)
            if msgs:
                first_msg = msgs[0].get("content", "")[:60].replace("\n", " ")
            btn = QPushButton(f"  {ts}{dur}  ·  {first_msg}")
            btn.setStyleSheet(
                f"text-align: left; padding: 8px 12px;"
                f" background: {PALETTE['panel']};"
                f" border: 1px solid {PALETTE['border']};"
            )
            btn.clicked.connect(lambda _, sid=sid: self._load_session(sid, dlg))
            lay.addWidget(btn)
        close_btn = QPushButton("Close")
        close_btn.clicked.connect(dlg.close)
        lay.addWidget(close_btn)
        dlg.setStyleSheet(_qss())
        dlg.exec()

    def _load_session(self, session_id: str, dlg: QDialog) -> None:
        dlg.close()
        if hasattr(self, "_book_id"):
            self.chat.set_session(session_id, [self._book_id])
            self.chat._add_assistant("(session restored)")

    def _on_popout(self) -> None:
        if hasattr(self, "_book_id") and self._book_id:
            self.popout_requested.emit(self._book_id)


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
            self.table.setItem(row, 4, QTableWidgetItem(err))


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
        self._popouts: dict[str, "PopoutInterview"] = {}

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

    # ---------------------------------------------------------------- popout

    def _open_popout(self, book_id: str) -> None:
        # Popouts are now per-book BookWindow instances.
        self._open_book(book_id)

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


# ----------------------------------------------------------------- mind dialog


class MindDialog(QDialog):
    """Create or edit a Mind."""

    def __init__(self, mind, library, parent=None):
        super().__init__(parent)
        self.mind = mind
        self.library = library

        from learnage.minds.base import SCOPE_LABELS, ALL_SCOPES
        self._SCOPE_LABELS = SCOPE_LABELS
        self._ALL_SCOPES = ALL_SCOPES

        title = "Edit Mind" if mind.id else "New Mind"
        self.setWindowTitle(title)
        self.setMinimumSize(640, 600)
        self.setStyleSheet(_qss())

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # Identity row: icon + name + color
        id_row = QHBoxLayout()
        id_row.setSpacing(10)
        id_row.addWidget(QLabel("Icon"))
        self.icon_edit = QLineEdit(mind.icon or "✦")
        self.icon_edit.setMaxLength(4)
        self.icon_edit.setFixedWidth(48)
        self.icon_edit.setFont(QFontDatabase.systemFont(QFontDatabase.GeneralFont))
        id_row.addWidget(self.icon_edit)
        id_row.addWidget(QLabel("Name"))
        self.name_edit = QLineEdit(mind.name)
        self.name_edit.setPlaceholderText("Witchcraft")
        id_row.addWidget(self.name_edit, 1)
        id_row.addWidget(QLabel("Color"))
        self.color_edit = QLineEdit(mind.color or "#9ca8b8")
        self.color_edit.setFixedWidth(90)
        id_row.addWidget(self.color_edit)
        layout.addLayout(id_row)

        # Description
        desc_lbl = QLabel("Description")
        desc_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        layout.addWidget(desc_lbl)
        self.desc_edit = QLineEdit(mind.description)
        self.desc_edit.setPlaceholderText("One-line subtitle for the sidebar")
        layout.addWidget(self.desc_edit)

        # Scope
        scope_lbl = QLabel("Scope")
        scope_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        layout.addWidget(scope_lbl)
        scope_row = QHBoxLayout()
        scope_row.setSpacing(10)
        self.scope_combo = QComboBox()
        for s in ALL_SCOPES:
            self.scope_combo.addItem(self._SCOPE_LABELS.get(s, s), s)
        idx = self.scope_combo.findData(mind.scope_kind)
        if idx >= 0:
            self.scope_combo.setCurrentIndex(idx)
        self.scope_combo.currentIndexChanged.connect(self._update_scope_help)
        scope_row.addWidget(self.scope_combo, 1)
        layout.addLayout(scope_row)
        self.scope_help = QLabel("")
        self.scope_help.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 11px;"
        )
        self.scope_help.setWordWrap(True)
        layout.addWidget(self.scope_help)

        self.values_edit = QLineEdit(", ".join(mind.scope_values))
        self.values_edit.setPlaceholderText(
            "Comma-separated: witchcraft, occult, ritual  (or book ids for 'manual')"
        )
        layout.addWidget(self.values_edit)

        # Scope preview
        self.scope_preview = QLabel("")
        self.scope_preview.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 11px; padding: 4px 0;"
        )
        layout.addWidget(self.scope_preview)

        # Persona
        prompt_lbl = QLabel("Persona (system prompt)")
        prompt_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        layout.addWidget(prompt_lbl)
        self.prompt_edit = QPlainTextEdit(mind.system_prompt)
        self.prompt_edit.setPlaceholderText(
            "You are a scholar of the esoteric…  (the role the LLM plays)"
        )
        f = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        f.setPointSize(12)
        self.prompt_edit.setFont(f)
        self.prompt_edit.setMinimumHeight(140)
        layout.addWidget(self.prompt_edit)

        # Tuning row
        tune_lbl = QLabel("Tuning")
        tune_lbl.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 10px;"
            f" font-weight: 700; text-transform: uppercase; letter-spacing: 1.5px;"
        )
        layout.addWidget(tune_lbl)
        tune_row = QHBoxLayout()
        tune_row.setSpacing(10)
        tune_row.addWidget(QLabel("top_k"))
        self.topk_spin = QSpinBox()
        self.topk_spin.setRange(2, 60)
        self.topk_spin.setValue(mind.top_k)
        tune_row.addWidget(self.topk_spin)
        tune_row.addWidget(QLabel("top_n"))
        self.topn_spin = QSpinBox()
        self.topn_spin.setRange(1, 20)
        self.topn_spin.setValue(mind.top_n)
        tune_row.addWidget(self.topn_spin)
        tune_row.addWidget(QLabel("temp"))
        self.temp_spin = QDoubleSpinBox()
        self.temp_spin.setRange(0.0, 1.5)
        self.temp_spin.setSingleStep(0.05)
        self.temp_spin.setValue(mind.temperature)
        tune_row.addWidget(self.temp_spin)
        self.soul_check = QCheckBox("include collective soul")
        self.soul_check.setChecked(mind.include_soul)
        tune_row.addWidget(self.soul_check)
        tune_row.addStretch()
        layout.addLayout(tune_row)

        # Buttons
        btns = QHBoxLayout()
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self.save_btn = QPushButton("Save")
        self.save_btn.setProperty("variant", "primary")
        self.save_btn.clicked.connect(self._save)
        btns.addWidget(self.save_btn)
        layout.addLayout(btns)

        self._update_scope_help()

    def _update_scope_help(self) -> None:
        from learnage.minds.base import SCOPE_CATEGORY, SCOPE_TAG, SCOPE_UNION, SCOPE_MANUAL, SCOPE_ALL
        kind = self.scope_combo.currentData()
        examples = {
            SCOPE_ALL: "Searches every book in the library.",
            SCOPE_CATEGORY: "Books whose category equals one of the values below.",
            SCOPE_TAG: "Books that have any of the values as a tag.",
            SCOPE_UNION: "Books matching the category OR any tag in the values below.",
            SCOPE_MANUAL: "Comma-separated book IDs. Useful for personal reading lists.",
        }
        self.scope_help.setText(examples.get(kind, ""))
        self._refresh_preview()

    def _refresh_preview(self) -> None:
        try:
            test_mind = self._build_mind()
            n = test_mind.matches_count(self.library.list_books())
            self.scope_preview.setText(f"In scope: {n} book{'s' if n != 1 else ''}")
        except Exception:  # noqa: BLE001
            self.scope_preview.setText("")

    def _build_mind(self):
        from learnage.minds.base import Mind
        vals = [v.strip() for v in self.values_edit.text().split(",") if v.strip()]
        return Mind(
            id=self.mind.id or "_preview",
            name=self.name_edit.text().strip() or "Mind",
            scope_kind=self.scope_combo.currentData(),
            scope_values=vals,
        )

    def _save(self) -> None:
        from learnage.minds.base import Mind
        name = self.name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Missing name", "Give the Mind a name.")
            return
        icon = self.icon_edit.text().strip() or "✦"
        color = self.color_edit.text().strip() or "#9ca8b8"
        desc = self.desc_edit.text().strip()
        sys_prompt = self.prompt_edit.toPlainText().strip()
        scope_kind = self.scope_combo.currentData()
        vals = [v.strip() for v in self.values_edit.text().split(",") if v.strip()]
        new_mind = Mind(
            id=self.mind.id,
            name=name,
            description=desc,
            icon=icon,
            color=color,
            scope_kind=scope_kind,
            scope_values=vals,
            system_prompt=sys_prompt,
            temperature=self.temp_spin.value(),
            top_k=self.topk_spin.value(),
            top_n=self.topn_spin.value(),
            include_soul=self.soul_check.isChecked(),
            soul_max_chars=self.mind.soul_max_chars,
            preset_name=self.mind.preset_name,
            is_builtin=self.mind.is_builtin,
            created_at=self.mind.created_at,
        )
        self.mind = new_mind
        self.accept()


# ----------------------------------------------------------------- mind chat tab


class MindChatTab(QWidget):
    """Chat body for a single Mind — header + log + composer."""

    citation_clicked = Signal(str, int)  # book_id, chunk_index
    parent_edit_requested = Signal(str)  # mind_id

    def __init__(self, mind, library, vectors, ollama, preset, *, home=None):
        super().__init__()
        self.mind = mind
        self.library = library
        self.vectors = vectors
        self.ollama = ollama
        self.preset = preset
        self.home = home
        self._history: list[dict] = []
        self._session_id: Optional[str] = None
        self._pending: list[str] = []
        self._thinking_dots: Optional[QLabel] = None
        self._thinking_timer = QTimer(self)
        self._thinking_timer.setInterval(400)
        self._thinking_timer.timeout.connect(self._tick_dots)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Header
        layout.addWidget(self._build_header(), 0)

        # Scrollable log
        self.log = QWidget()
        self.log_v = QVBoxLayout(self.log)
        self.log_v.setContentsMargins(0, 16, 0, 16)
        self.log_v.setSpacing(10)
        self.log_v.addStretch(1)
        self.scroll = QScrollArea()
        self.scroll.setWidget(self.log)
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QFrame.NoFrame)
        self.scroll.verticalScrollBar().rangeChanged.connect(
            lambda mn, mx: self.scroll.verticalScrollBar().setValue(mx)
        )
        layout.addWidget(self.scroll, 1)

        # Composer
        composer = QWidget()
        composer.setStyleSheet(
            f"background: {PALETTE['bg_elev']}; border-top: 1px solid {PALETTE['border']};"
        )
        cv = QVBoxLayout(composer)
        cv.setContentsMargins(20, 12, 20, 12)
        cv.setSpacing(6)
        self.input = QLineEdit()
        self.input.setMaxLength(4000)
        self.input.setPlaceholderText(f"Ask {mind.name}…")
        f = QFontDatabase.systemFont(QFontDatabase.GeneralFont)
        f.setPointSize(13)
        self.input.setFont(f)
        self.input.returnPressed.connect(self._on_send)
        cr = QHBoxLayout()
        cr.addWidget(self.input, 1)
        self.send_btn = QPushButton("Send")
        self.send_btn.setProperty("variant", "primary")
        self.send_btn.clicked.connect(self._on_send)
        cr.addWidget(self.send_btn)
        cv.addLayout(cr)
        layout.addWidget(composer)

    def _build_header(self) -> QWidget:
        h = QWidget()
        h.setStyleSheet(
            f"background: {PALETTE['bg_elev']}; border-bottom: 1px solid {PALETTE['border']};"
        )
        v = QVBoxLayout(h)
        v.setContentsMargins(28, 16, 28, 16)
        v.setSpacing(2)
        row = QHBoxLayout()
        row.setSpacing(10)
        icon_lbl = QLabel(self.mind.icon or "✦")
        icon_lbl.setStyleSheet(
            f"color: {self.mind.color}; font-size: 22px; font-weight: 600;"
        )
        row.addWidget(icon_lbl)
        name_lbl = QLabel(self.mind.name)
        name_lbl.setStyleSheet(
            f"color: {PALETTE['text']}; font-size: 18px; font-weight: 600;"
        )
        row.addWidget(name_lbl)
        row.addStretch()
        # Notes button (with badge if notes exist)
        self.notes_btn = QPushButton()
        self.notes_btn.setProperty("variant", "ghost")
        self.notes_btn.setFixedHeight(24)
        self.notes_btn.setToolTip("Persistent notes — read by the Mind every prompt")
        self.notes_btn.clicked.connect(self._open_notes_editor)
        self._refresh_notes_badge()
        row.addWidget(self.notes_btn)
        # Edit mind button
        edit_btn = QPushButton("edit")
        edit_btn.setProperty("variant", "ghost")
        edit_btn.setFixedWidth(60)
        edit_btn.setToolTip("Edit this mind")
        edit_btn.clicked.connect(lambda: self.parent_edit_requested.emit(self.mind.id))
        row.addWidget(edit_btn)
        v.addLayout(row)

        if self.mind.description:
            desc_lbl = QLabel(self.mind.description)
            desc_lbl.setStyleSheet(
                f"color: {PALETTE['text_muted']}; font-size: 12px;"
            )
            v.addWidget(desc_lbl)

        scope_lbl = QLabel(self.mind.scope_description())
        scope_lbl.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 11px; padding-top: 4px;"
        )
        v.addWidget(scope_lbl)
        return h

    # ----------------------------------------------------------- notes

    def _refresh_notes_badge(self) -> None:
        if not self.home:
            self.notes_btn.setText("notes")
            return
        from learnage.minds.notes import MindNotes
        notes = MindNotes(self.home)
        text = notes.load(self.mind.id).strip()
        if text:
            # Show a small badge: "● notes"
            self.notes_btn.setText(
                f"● notes · {len(text):,}"
            )
        else:
            self.notes_btn.setText("+ notes")

    def _open_notes_editor(self) -> None:
        if not self.home:
            return
        from learnage.minds.notes import MindNotes
        notes = MindNotes(self.home)
        current = notes.load(self.mind.id)

        dlg = QDialog(self)
        dlg.setWindowTitle(f"Notes · {self.mind.name}")
        dlg.setMinimumSize(640, 480)
        dlg.setStyleSheet(_qss())

        layout = QVBoxLayout(dlg)
        layout.setSpacing(10)

        # Header explaining what notes do
        head = QLabel(
            "<b>Persistent notes</b> — the Mind reads these on every prompt.<br>"
            "Use this for preferences, ongoing threads, names, anything the Mind "
            "should always know about you. Markdown is fine."
        )
        head.setWordWrap(True)
        head.setStyleSheet(
            f"color: {PALETTE['text_muted']}; font-size: 12px; padding: 6px 0;"
        )
        layout.addWidget(head)

        editor = QPlainTextEdit(current)
        mono = QFontDatabase.systemFont(QFontDatabase.FixedFont)
        mono.setPointSize(13)
        editor.setFont(mono)
        editor.setStyleSheet(
            f"QPlainTextEdit {{ background: {PALETTE['bg']}; color: {PALETTE['text']};"
            f" border: 1px solid {PALETTE['border']}; padding: 14px;"
            f" line-height: 1.5; }}"
        )
        layout.addWidget(editor, 1)

        # Char count + clear button
        meta = QHBoxLayout()
        char_lbl = QLabel("")
        char_lbl.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 11px;")
        meta.addWidget(char_lbl)
        meta.addStretch()

        def _update_count() -> None:
            n = len(editor.toPlainText())
            char_lbl.setText(f"{n:,} chars")

        editor.textChanged.connect(_update_count)
        _update_count()

        clear_btn = QPushButton("Clear")
        clear_btn.setProperty("variant", "ghost")
        clear_btn.clicked.connect(lambda: editor.setPlainText(""))
        meta.addWidget(clear_btn)
        layout.addLayout(meta)

        # Footer buttons
        btns = QHBoxLayout()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(dlg.reject)
        btns.addWidget(cancel)
        btns.addStretch()
        save = QPushButton("Save")
        save.setProperty("variant", "primary")
        save.clicked.connect(lambda: dlg.accept())
        btns.addWidget(save)
        layout.addLayout(btns)

        if dlg.exec() == QDialog.Accepted:
            notes.save(self.mind.id, editor.toPlainText().strip())
            self._refresh_notes_badge()
            self.statusBar().showMessage(  # type: ignore[attr-defined]
                f"saved notes for {self.mind.name}", 3000,
            )

    def set_session(self, session_id: str, book_ids: list[str]) -> None:
        self._session_id = session_id
        try:
            self.library.create_session(session_id, book_ids)
        except Exception:  # noqa: BLE001
            pass
        # Restore history
        rows = self.library.list_messages(session_id)
        for r in rows:
            self._add_bubble(r["content"], role=r["role"])
            self._history.append({"role": r["role"], "content": r["content"]})

    # ----------------------------------------------------------- send/stream

    def _on_send(self) -> None:
        text = self.input.text().strip()
        if not text:
            return
        self.input.clear()
        self._add_bubble(text, role="user")
        self._history.append({"role": "user", "content": text})
        if self._session_id:
            try:
                self.library.append_message(self._session_id, "user", text)
            except Exception:  # noqa: BLE001
                pass
        _w, bubble, dots = self._add_bubble("", role="assistant")
        if dots:
            dots.setVisible(False)
        self._thinking_dots = dots
        self._pending = []
        self._last_bubble = bubble
        self._stream(bubble, text)

    def _stream(self, bubble: QLabel, question: str) -> None:
        from learnage.minds.runner import stream_mind_chat, citations_for_mind

        history = self._history[:-1]

        # Pre-fetch citations so the bubble can be re-rendered with
        # clickable [N] markers once the stream finishes.
        try:
            citations = citations_for_mind(
                question,
                mind=self.mind,
                library=self.library,
                vectors=self.vectors,
                preset=self.preset,
                home=self.home,
            )
        except Exception:  # noqa: BLE001
            citations = []
        self._last_citations = citations

        class _Runner(QRunnable):
            def run(_self) -> None:
                try:
                    stream = stream_mind_chat(
                        question,
                        mind=self.mind,
                        library=self.library,
                        vectors=self.vectors,
                        ollama=self.ollama,
                        preset=self.preset,
                        history=history,
                        home=self.home,
                    )
                    for token in stream:
                        _self._token.emit(token)
                    _self._done.emit(True, "")
                except Exception as exc:  # noqa: BLE001
                    _self._done.emit(False, str(exc))

        class _Signals(QObject):
            from PySide6.QtCore import Signal as _S
            _token = _S(str)
            _done = _S(bool, str)

        signals = _Signals()
        runner = _Runner()
        runner._token = signals._token  # attach for closure
        runner._done = signals._done
        signals._token.connect(self._on_token)
        signals._done.connect(lambda ok, msg: self._on_done(ok, msg))
        QThreadPool.globalInstance().start(runner)

    def _on_token(self, token: str) -> None:
        self._thinking_timer.stop()
        if self._thinking_dots:
            self._thinking_dots.setVisible(False)
        self._pending.append(token)
        # While streaming, show escaped plain text. We re-render with
        # clickable citations once the stream completes (in _on_done).
        bubble = getattr(self, "_last_bubble", None)
        if bubble:
            bubble.setText(html_escape("".join(self._pending)))

    def _on_done(self, ok: bool, msg: str) -> None:
        self._thinking_timer.stop()
        bubble = getattr(self, "_last_bubble", None)
        if not ok:
            if bubble:
                bubble.setText(
                    f'<span style="color:{PALETTE["error"]}">{html_escape(msg)}</span>'
                )
            return
        full = "".join(self._pending)
        # Re-render with clickable citation markers + footer
        if bubble:
            citations = getattr(self, "_last_citations", [])
            from learnage.minds.citations import render_text_with_citations, build_citation_footer
            html_body = render_text_with_citations(full, citations)
            html_body += build_citation_footer(citations)
            bubble.setText(html_body)
            # Wire citation clicks
            bubble.linkActivated.connect(self._on_link_activated)
            bubble.setTextInteractionFlags(Qt.TextBrowserInteraction)
        self._history.append({"role": "assistant", "content": full})
        if self._session_id:
            try:
                self.library.append_message(self._session_id, "assistant", full)
            except Exception:  # noqa: BLE001
                pass

    def _on_link_activated(self, url: str) -> None:
        from learnage.minds.citations import parse_citation_url
        parsed = parse_citation_url(url)
        if parsed:
            book_id, chunk_index = parsed
            self.citation_clicked.emit(book_id, chunk_index)

    def _tick_dots(self) -> None:
        if not self._thinking_dots:
            return
        self._thinking_frame = (self._thinking_frame + 1) % 4
        self._thinking_dots.setText("·" * self._thinking_frame)

    def _add_bubble(self, text: str, *, role: str) -> tuple:
        wrap = QWidget()
        wb = QHBoxLayout(wrap)
        wb.setContentsMargins(40, 0, 40, 0)
        wb.setSpacing(0)
        bubble = QLabel(text)
        bubble.setWordWrap(True)
        bubble.setTextFormat(Qt.RichText)
        bubble.setMaximumWidth(640)
        dots: Optional[QLabel] = None

        if role == "user":
            bubble.setStyleSheet(
                f"background: {PALETTE['accent_dim']}; color: white;"
                f" border-radius: 14px; padding: 12px 16px; font-size: 14px;"
            )
            wb.addStretch(1)
            wb.addWidget(bubble)
        else:
            bubble.setStyleSheet(
                f"background: {PALETTE['panel']}; color: {PALETTE['text']};"
                f" border-radius: 14px; padding: 12px 16px; font-size: 14px;"
            )
            wb.addWidget(bubble)
            wb.addStretch(1)
            dots = QLabel("")
            dots.setStyleSheet(
                f"color: {PALETTE['text_muted']}; font-size: 11px; font-style: italic;"
                f" padding: 2px 16px;"
            )
            dots.setVisible(False)
            wb.addWidget(dots)

        # Insert before the trailing stretch
        self.log_v.insertWidget(self.log_v.count() - 1, wrap)
        self._last_bubble = bubble
        return wrap, bubble, dots

    def keyPressEvent(self, e) -> None:
        if e.key() == Qt.Key_Escape and self.input.text().strip():
            self.input.clear()
            e.accept()
        elif e.key() == Qt.Key_Return and (e.modifiers() & Qt.MetaModifier):
            self._on_send()
            e.accept()
        else:
            super().keyPressEvent(e)


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
