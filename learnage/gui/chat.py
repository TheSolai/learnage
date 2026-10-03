"""Chat body + interview view + tool cards.

Extracted from gui/app.py in v2.0. Holds three widgets that the launcher
and BookWindow share:

- ChatTab — the main chat body (user input + assistant bubbles + tool cards)
- InterviewView — header + ChatTab + history popout for a single book
- ToolCard — the in-stream collapsible card for a tool-call

Both ChatTab and InterviewView reference ``html_escape`` from
``learnage.gui.widgets``.
"""

from __future__ import annotations

import json
import uuid
from typing import Optional

from PySide6.QtCore import (
    QObject,
    QPoint,
    QRunnable,
    Qt,
    QThreadPool,
    QTimer,
    Signal,
    Slot,
)
from PySide6.QtGui import QCursor, QFont, QFontDatabase
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QVBoxLayout,
    QWidget,
)

from learnage.config import Preset as _Preset
from learnage.gui.agent import AgentRunner, ToolCall
from learnage.gui.theme import PALETTE
from learnage.gui.widgets import html_escape
from learnage.llm.ollama import OllamaClient
from learnage.store.library import Book, Library
from learnage.store.vectors import VectorStore


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
        # Cover + subtitle row
        sub_row = QHBoxLayout()
        sub_row.setSpacing(10)
        self.cover_lbl = QLabel()
        self.cover_lbl.setFixedSize(28, 42)
        self.cover_lbl.setVisible(False)
        sub_row.addWidget(self.cover_lbl)
        self.subtitle = QLabel("Pick a book to interview")
        self.subtitle.setTextFormat(Qt.PlainText)
        self.subtitle.setStyleSheet(f"color: {PALETTE['text_muted']}; font-size: 12px;")
        sub_row.addWidget(self.subtitle, 1)
        h.addLayout(sub_row)

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
        from learnage.gui import covers as _covers
        self._book_id = book.id
        self.subtitle.setTextFormat(Qt.PlainText)
        self.subtitle.setText(f"with {book.title}")
        # Show cover thumbnail next to the subtitle
        pix = _covers.extract_or_placeholder(
            {"title": book.title}, book.source_format, book.source_path,
        )
        self.cover_lbl.setPixmap(
            pix.scaled(28, 42, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )
        self.cover_lbl.setVisible(True)
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


