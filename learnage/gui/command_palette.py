"""⌘K command palette — fuzzy launcher for every action the app exposes.

Usage:
    :::ui
    palette = CommandPalette(parent=main_window)
    palette.show()
    palette.raise_()
    palette.activateWindow()

The palette reads from ``learnage.gui.command_registry``. Each result row
is a ``Command`` and ``run_command(key, target_kw=...)`` is invoked when
the user activates it.
"""

from __future__ import annotations

import re
from typing import Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontDatabase, QKeyEvent
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
    QWidget,
)

from learnage.gui import command_registry as _reg
from learnage.gui.command_registry import Command
from learnage.gui.theme import PALETTE


def _score(query: str, label: str, desc: str) -> int:
    """Fuzzy score — higher is better, 0 means no match.

    Subsequence match with substring bonus and category-weight.
    """
    q = query.lower().strip()
    hay = (label + " " + desc).lower()
    if not q:
        return 1
    if q in label.lower():
        # Exact substring in label is a strong match.
        return 100 + (50 - min(50, len(label)))
    if q in hay:
        return 50
    # Subsequence
    j = 0
    matched = 0
    last = -1
    for i, ch in enumerate(label.lower()):
        if j < len(q) and ch == q[j]:
            matched += 1
            if last == i - 1:
                matched += 2  # contiguous bonus
            last = i
            j += 1
    return matched * 5 if j == len(q) else 0


class CommandPalette(QDialog):
    """Modal-less dialog — closes on selection or Esc."""

    activated = Signal(str)  # command key

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        target_kind: str = "library",
        target_id: Optional[str] = None,
    ) -> None:
        super().__init__(parent)
        self._target_kind = target_kind
        self._target_id = target_id
        self.setWindowTitle("Commands")
        self.setModal(True)
        self.setWindowFlags(self.windowFlags() | Qt.FramelessWindowHint)
        self.resize(560, 420)
        self.setStyleSheet(
            f"QDialog {{ background: {PALETTE['bg_elev']};"
            f" border: 1px solid {PALETTE['border_strong']};"
            f" border-radius: 12px; }}"
        )

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        # Input
        input_box = QFrame()
        input_box.setStyleSheet(
            f"background: transparent; border-bottom: 1px solid {PALETTE['border']};"
        )
        ib = QHBoxLayout(input_box)
        ib.setContentsMargins(16, 12, 16, 12)
        ib.setSpacing(8)
        prompt = QLabel("⌘K")
        prompt.setStyleSheet(
            f"color: {PALETTE['accent']}; font-size: 13px; font-weight: 700;"
        )
        ib.addWidget(prompt)
        self.input = QLineEdit()
        self.input.setPlaceholderText("jump to anything…")
        self.input.setStyleSheet(
            f"QLineEdit {{ background: transparent; border: none;"
            f" color: {PALETTE['text']}; font-size: 14px; padding: 4px 0; }}"
        )
        self.input.textChanged.connect(self._refilter)
        self.input.returnPressed.connect(self._activate_current)
        ib.addWidget(self.input, 1)
        outer.addWidget(input_box)

        # Results
        self.list = QListWidget()
        self.list.setFrameShape(QFrame.NoFrame)
        self.list.setStyleSheet(
            "QListWidget { background: transparent; border: none; padding: 6px 0; }"
            "QListWidget::item { padding: 10px 16px; border: none; border-radius: 0; }"
            f"QListWidget::item:selected {{ background: {PALETTE['selection']}; }}"
            f"QListWidget::item:hover {{ background: {PALETTE['panel']}; }}"
        )
        outer.addWidget(self.list, 1)

        # Footer hint
        hint = QLabel("↵ run   ·   ↑↓ navigate   ·   esc cancel")
        hint.setStyleSheet(
            f"color: {PALETTE['text_dim']}; font-size: 10px; padding: 8px 16px;"
            f" border-top: 1px solid {PALETTE['border']};"
        )
        outer.addWidget(hint)

        # Pre-populate
        self._all = _reg.commands_for_target(self._target_kind, self._target_id)
        self._refilter()
        self.list.itemActivated.connect(self._on_item_activated)

    def keyPressEvent(self, e: QKeyEvent) -> None:
        if e.key() in (Qt.Key_Down, Qt.Key_Up):
            row = self.list.currentRow()
            n = self.list.count()
            if n == 0:
                return
            if e.key() == Qt.Key_Down:
                row = (row + 1) % n if row >= 0 else 0
            else:
                row = (row - 1) % n if row >= 0 else n - 1
            self.list.setCurrentRow(row)
            e.accept()
            return
        if e.key() == Qt.Key_Escape:
            self.reject()
            e.accept()
            return
        super().keyPressEvent(e)

    def showEvent(self, e) -> None:
        super().showEvent(e)
        self.input.setFocus()
        self.input.clear()
        self._refilter()

    def _refilter(self) -> None:
        q = self.input.text()
        scored: list[tuple[int, Command]] = []
        for c in self._all:
            s = _score(q, c.label, c.description)
            if s > 0:
                scored.append((s, c))
        scored.sort(key=lambda kv: (-kv[0], kv[1].category, kv[1].label))
        self.list.clear()
        for score, c in scored[:50]:
            item = QListWidgetItem()
            item.setData(Qt.UserRole, c.key)
            text = f"  {c.glyph}    {c.label}"
            item.setText(text)
            sub = f"  {c.category} — {c.description}"
            tip = f"{c.label}\n{c.category}\n{c.description}\n\ncommand: {c.key}"
            item.setToolTip(tip)
            item.setData(Qt.UserRole + 1, sub)
            self.list.addItem(item)
            # Custom two-line rendering
            self._render_row(item, c, sub)
        if self.list.count() > 0:
            self.list.setCurrentRow(0)

    def _render_row(self, item: QListWidgetItem, cmd: Command, sub: str) -> None:
        """Build a tiny two-line QLabel per row using rich-text."""
        item.setText(
            f"{cmd.glyph}    {cmd.label}    "
            f"<span style='color:{PALETTE['text_dim']}; font-size: 10px;'>"
            f"{cmd.category} — {cmd.description}</span>"
        )

    def _activate_current(self) -> None:
        item = self.list.currentItem()
        if item:
            self._on_item_activated(item)

    def _on_item_activated(self, item: QListWidgetItem) -> None:
        key = item.data(Qt.UserRole)
        if not key:
            return
        # Run with the bound target so commands like "forget this book" get
        # the right book_id.
        kwargs = {}
        if self._target_kind == "book" and self._target_id:
            kwargs["book_id"] = self._target_id
        if self._target_kind == "mind" and self._target_id:
            kwargs["mind_id"] = self._target_id
        ok = _reg.run_command(key, **kwargs)
        self.activated.emit(key)
        if ok:
            self.accept()
        else:
            # Stub — flash the input to acknowledge
            self.input.setStyleSheet(
                f"QLineEdit {{ background: {PALETTE['selection']};"
                f" color: {PALETTE['text']}; font-size: 14px; padding: 4px 0; }}"
            )