"""SoulView — the launcher's souls section body.

Extracted from gui/app.py in v2.0. Renders a single book's soul (summary,
characters, key passages, voice) plus a button to regenerate the soul via
the ingest pool.
"""

from __future__ import annotations

import json

from PySide6.QtCore import Qt
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

from learnage.gui import covers
from learnage.gui.theme import PALETTE
from learnage.gui.widgets import html_escape
from learnage.store.soul import SoulRecord
from learnage.store.library import Book


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

        # Header row: cover thumb on the left, title + author on the right
        header_row = QHBoxLayout()
        header_row.setSpacing(20)
        header_row.setContentsMargins(0, 0, 0, 0)

        cover_lbl = QLabel()
        pix = covers.extract_or_placeholder(
            {"title": book.title}, book.source_format, book.source_path,
        )
        cover_lbl.setPixmap(
            pix.scaled(96, 144, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        cover_lbl.setFixedSize(96, 144)
        header_row.addWidget(cover_lbl, 0)

        text_col = QVBoxLayout()
        text_col.setSpacing(2)

        title = QLabel()
        title.setTextFormat(Qt.PlainText)  # prevent HTML injection in titles
        title.setText(book.title)
        f = QFontDatabase.systemFont(QFontDatabase.TitleFont)
        f.setPointSize(22)
        f.setWeight(QFont.DemiBold)
        title.setFont(f)
        title.setWordWrap(True)
        title.setStyleSheet(f"color: {PALETTE['text']};")
        text_col.addWidget(title)

        if book.author:
            sub = QLabel(book.author)
            sub.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 13px;")
            text_col.addWidget(sub)

        meta = QHBoxLayout()
        meta.setSpacing(20)
        meta.setContentsMargins(0, 8, 0, 4)
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
        text_col.addLayout(meta)
        header_row.addLayout(text_col, 1)
        self.v.addLayout(header_row)

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


