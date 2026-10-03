"""Mind editor + Mind chat tab.

Extracted from gui/app.py in v2.0. Two classes:

- MindDialog — modal editor for creating/editing a Mind (name, icon, colour,
  scope kind + values, persona, retrieval tuning).
- MindChatTab — per-Mind chat body: header (icon + name + scope + edit/notes
  buttons), streaming log, composer. Persists sessions to ``library.sessions``.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from typing import Optional

from PySide6.QtCore import (
    QObject,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
)
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextBrowser,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from learnage.config import Preset as _Preset
from learnage.gui.theme import PALETTE
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Library
from learnage.store.soul import SoulRecord
from learnage.store.vectors import VectorStore


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


