"""Small modal dialogs collected in one place.

Extracted from gui/app.py in v2.0. Currently:

- WeedDialog — bulk-select-and-delete books matching low-quality thresholds.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from learnage.gui.theme import PALETTE
from learnage.store.blocklist import Blocklist
from learnage.store.library import Book, Library
from learnage.store.vectors import VectorStore


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


