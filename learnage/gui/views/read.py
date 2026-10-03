"""ReadView — the launcher's read-preview for a book.

Extracted from gui/app.py in v2.0. Shows the cover, title, author, and the
first chunk of a book, with a "read full" affordance. Different from
BookReadView (in book_window.py), which is the per-book tabbed reader.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from learnage.gui.theme import PALETTE
from learnage.gui.widgets import html_escape
from learnage.store.library import Book


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


# ----------------------------------------------------------------- chat / interview view
