"""Sidebar — the left-hand nav pane.

Extracted from app.py in v2.0. Holds:
- the section list (Library / Souls / Chat all / Ingesting / Recent / Add books)
- the per-Mind list with drag-to-reorder
- the brand strip and status footer

Signals:
- section_changed(str)  — user picked a top-level section
- mind_opened(str)      — clicked a Mind (or sent a Mind action via context menu)
- mind_reordered(list)  — user dragged to a new order
- mind_sort_changed(str)— user picked a sort mode from the popup
- new_mind_requested()  — user clicked the + button
"""

from __future__ import annotations

from PySide6.QtCore import QPoint, QSize, Qt, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QPushButton,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from learnage.gui import covers  # noqa: F401 — re-exported for callers
from learnage.gui.theme import PALETTE


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
        for m in minds:
            if m.id == "reading":
                continue
            glyph = m.icon or "✦"
            label = m.name
            item = QListWidgetItem(f"  {glyph}    {label}")
            item.setData(Qt.UserRole, m.id)
            item.setSizeHint(200, 30)
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