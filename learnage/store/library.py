"""SQLite-backed library: books, chunks meta, sessions, messages."""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS books (
  id TEXT PRIMARY KEY,
  title TEXT NOT NULL,
  author TEXT,
  source_path TEXT NOT NULL,
  source_format TEXT NOT NULL,
  source_hash TEXT NOT NULL,
  byte_size INTEGER,
  char_count INTEGER,
  chunk_count INTEGER,
  ingested_at TEXT NOT NULL,
  soul_json TEXT,
  soul_generated_at TEXT,
  soul_status TEXT,
  category TEXT,
  tags_json TEXT
);

CREATE INDEX IF NOT EXISTS idx_books_title ON books(title);

CREATE TABLE IF NOT EXISTS chunks_meta (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  chapter TEXT,
  char_start INTEGER,
  char_end INTEGER,
  token_estimate INTEGER,
  FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_chunks_book ON chunks_meta(book_id, chunk_index);

CREATE TABLE IF NOT EXISTS sessions (
  id TEXT PRIMARY KEY,
  started_at TEXT NOT NULL,
  ended_at TEXT,
  book_ids TEXT NOT NULL,
  title TEXT
);

CREATE TABLE IF NOT EXISTS messages (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  session_id TEXT NOT NULL,
  role TEXT NOT NULL,
  content TEXT NOT NULL,
  citations_json TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (session_id) REFERENCES sessions(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, id);

CREATE TABLE IF NOT EXISTS bookmarks (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  book_id TEXT NOT NULL,
  chunk_index INTEGER NOT NULL,
  chapter TEXT,
  note TEXT,
  created_at TEXT NOT NULL,
  FOREIGN KEY (book_id) REFERENCES books(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_bookmarks_book ON bookmarks(book_id, chunk_index);
"""


@dataclass
class Book:
    id: str
    title: str
    author: str | None
    source_path: str
    source_format: str
    source_hash: str
    byte_size: int | None
    char_count: int | None
    chunk_count: int | None
    ingested_at: str
    soul_json: str | None
    soul_generated_at: str | None
    soul_status: str | None
    category: str | None = None
    tags: list[str] | None = None

    @property
    def display_tags(self) -> list[str]:
        return self.tags or []


class Library:
    """SQLite-backed library store."""

    def __init__(self, db_path: Path) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()
        self._migrate()

    def _migrate(self) -> None:
        """Apply incremental migrations for older DBs."""
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(books)").fetchall()}
        if "category" not in cols:
            self._conn.execute("ALTER TABLE books ADD COLUMN category TEXT")
        if "tags_json" not in cols:
            self._conn.execute("ALTER TABLE books ADD COLUMN tags_json TEXT")
        self._conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_books_category ON books(category)"
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # ---------------------------------------------------------------- books

    def upsert_book(self, book: Book) -> None:
        tags_json = json.dumps(book.tags or [], ensure_ascii=False)
        self._conn.execute(
            """
            INSERT INTO books (
                id, title, author, source_path, source_format, source_hash,
                byte_size, char_count, chunk_count, ingested_at,
                soul_json, soul_generated_at, soul_status,
                category, tags_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                title=excluded.title,
                author=excluded.author,
                source_path=excluded.source_path,
                source_format=excluded.source_format,
                source_hash=excluded.source_hash,
                byte_size=excluded.byte_size,
                char_count=excluded.char_count,
                chunk_count=excluded.chunk_count,
                ingested_at=excluded.ingested_at,
                category=COALESCE(excluded.category, books.category),
                tags_json=excluded.tags_json
            """,
            (
                book.id,
                book.title,
                book.author,
                book.source_path,
                book.source_format,
                book.source_hash,
                book.byte_size,
                book.char_count,
                book.chunk_count,
                book.ingested_at,
                book.soul_json,
                book.soul_generated_at,
                book.soul_status,
                book.category,
                tags_json,
            ),
        )
        self._conn.commit()

    def find_by_hash(self, source_hash: str) -> Book | None:
        row = self._conn.execute(
            "SELECT * FROM books WHERE source_hash = ?", (source_hash,)
        ).fetchone()
        return _book_from_row(row) if row else None

    def find_by_title(self, title: str) -> Book | None:
        # Fuzzy: exact match first, then case-insensitive contains.
        row = self._conn.execute(
            "SELECT * FROM books WHERE LOWER(title) = LOWER(?)", (title,)
        ).fetchone()
        if row:
            return _book_from_row(row)
        row = self._conn.execute(
            "SELECT * FROM books WHERE LOWER(title) LIKE LOWER(?) LIMIT 1",
            (f"%{title}%",),
        ).fetchone()
        return _book_from_row(row) if row else None

    def get_book(self, book_id: str) -> Book | None:
        row = self._conn.execute(
            "SELECT * FROM books WHERE id = ?", (book_id,)
        ).fetchone()
        return _book_from_row(row) if row else None

    def list_books(self) -> list[Book]:
        rows = self._conn.execute(
            "SELECT * FROM books ORDER BY ingested_at DESC"
        ).fetchall()
        return [_book_from_row(r) for r in rows]

    def list_books_by_category(self, category: str | None) -> list[Book]:
        if category is None:
            return [b for b in self.list_books() if not b.category]
        return [b for b in self.list_books() if (b.category or "").lower() == category.lower()]

    def list_books_with_tag(self, tag: str) -> list[Book]:
        t = tag.lower()
        out = []
        for b in self.list_books():
            if any(tg.lower() == t for tg in b.display_tags):
                out.append(b)
        return out

    def set_book_category(self, book_id: str, category: str | None) -> None:
        self._conn.execute(
            "UPDATE books SET category = ? WHERE id = ?",
            (category, book_id),
        )
        self._conn.commit()

    def bulk_set_category(self, book_ids: list[str], category: str | None) -> int:
        """Set category on many books at once. Returns count updated."""
        if not book_ids:
            return 0
        # Drop empty ids defensively
        ids = [bid for bid in book_ids if bid]
        if not ids:
            return 0
        qmarks = ",".join("?" for _ in ids)
        cur = self._conn.execute(
            f"UPDATE books SET category = ? WHERE id IN ({qmarks})",
            (category, *ids),
        )
        self._conn.commit()
        return cur.rowcount

    def bulk_set_tags(self, book_ids: list[str], tags: list[str], mode: str = "replace") -> int:
        """Set tags on many books. `mode` is 'replace' (default) or 'append'.

        Returns count updated. Existing tags are not preserved in 'replace'.
        """
        if not book_ids:
            return 0
        ids = [bid for bid in book_ids if bid]
        if not ids:
            return 0
        # Sanitize the input tag list once
        seen: set[str] = set()
        clean: list[str] = []
        for t in tags:
            tt = t.strip()
            if not tt:
                continue
            key = tt.lower()
            if key in seen:
                continue
            seen.add(key)
            clean.append(tt)
        if mode == "append":
            # Merge with existing tags per-book
            updated = 0
            for bid in ids:
                row = self._conn.execute(
                    "SELECT tags_json FROM books WHERE id = ?", (bid,)
                ).fetchone()
                existing: list[str] = []
                if row and row["tags_json"]:
                    try:
                        loaded = json.loads(row["tags_json"])
                        if isinstance(loaded, list):
                            existing = [str(t) for t in loaded]
                    except Exception:  # noqa: BLE001
                        pass
                merged: list[str] = []
                seen2: set[str] = set()
                for t in existing + clean:
                    if t.lower() in seen2:
                        continue
                    seen2.add(t.lower())
                    merged.append(t)
                self._conn.execute(
                    "UPDATE books SET tags_json = ? WHERE id = ?",
                    (json.dumps(merged, ensure_ascii=False), bid),
                )
                updated += 1
            self._conn.commit()
            return updated
        # replace mode — single UPDATE
        qmarks = ",".join("?" for _ in ids)
        cur = self._conn.execute(
            f"UPDATE books SET tags_json = ? WHERE id IN ({qmarks})",
            (json.dumps(clean, ensure_ascii=False), *ids),
        )
        self._conn.commit()
        return cur.rowcount

    def set_book_tags(self, book_id: str, tags: list[str]) -> None:
        # Sanitize: strip, dedupe (case-insensitive), drop empty
        seen: set[str] = set()
        clean: list[str] = []
        for t in tags:
            tt = t.strip()
            if not tt:
                continue
            key = tt.lower()
            if key in seen:
                continue
            seen.add(key)
            clean.append(tt)
        self._conn.execute(
            "UPDATE books SET tags_json = ? WHERE id = ?",
            (json.dumps(clean, ensure_ascii=False), book_id),
        )
        self._conn.commit()

    def list_categories(self) -> list[str]:
        rows = self._conn.execute(
            "SELECT category, COUNT(*) AS n FROM books "
            "WHERE category IS NOT NULL AND category != '' "
            "GROUP BY category ORDER BY n DESC"
        ).fetchall()
        return [r["category"] for r in rows]

    def list_tags(self) -> list[tuple[str, int]]:
        """Return [(tag, count)] sorted by count desc."""
        rows = self._conn.execute("SELECT tags_json FROM books WHERE tags_json IS NOT NULL").fetchall()
        counts: dict[str, int] = {}
        for r in rows:
            try:
                tags = json.loads(r["tags_json"])
            except Exception:  # noqa: BLE001
                continue
            if not isinstance(tags, list):
                continue
            for t in tags:
                if not isinstance(t, str):
                    continue
                key = t.strip()
                if not key:
                    continue
                counts[key] = counts.get(key, 0) + 1
        return sorted(counts.items(), key=lambda kv: (-kv[1], kv[0].lower()))

    def delete_book(self, book_id: str) -> None:
        self._conn.execute("DELETE FROM chunks_meta WHERE book_id = ?", (book_id,))
        self._conn.execute("DELETE FROM books WHERE id = ?", (book_id,))
        self._conn.commit()

    def set_soul(
        self,
        book_id: str,
        soul_json: str,
        status: str = "ok",
    ) -> None:
        self._conn.execute(
            """
            UPDATE books
               SET soul_json = ?, soul_status = ?, soul_generated_at = ?
             WHERE id = ?
            """,
            (soul_json, status, _now_iso(), book_id),
        )
        self._conn.commit()

    # -------------------------------------------------------------- chunks

    def replace_chunks(
        self,
        book_id: str,
        chunks: list[tuple[int, str | None, int, int, int]],
    ) -> None:
        """Replace all chunks for a book.

        chunks is a list of (chunk_index, chapter, char_start, char_end, token_estimate).
        """
        self._conn.execute("DELETE FROM chunks_meta WHERE book_id = ?", (book_id,))
        self._conn.executemany(
            """
            INSERT INTO chunks_meta
                (book_id, chunk_index, chapter, char_start, char_end, token_estimate)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            [(book_id, *c) for c in chunks],
        )
        self._conn.commit()

    def get_chapter_for_chunk(self, book_id: str, chunk_index: int) -> str | None:
        row = self._conn.execute(
            "SELECT chapter FROM chunks_meta WHERE book_id = ? AND chunk_index = ?",
            (book_id, chunk_index),
        ).fetchone()
        return row["chapter"] if row else None

    def get_chunk_meta_for_book(self, book_id: str) -> list[dict]:
        """Return ordered chunk metadata for a book."""
        rows = self._conn.execute(
            "SELECT chunk_index, chapter, char_start, char_end, token_estimate "
            "FROM chunks_meta WHERE book_id = ? ORDER BY chunk_index",
            (book_id,),
        ).fetchall()
        return [
            {
                "chunk_index": r["chunk_index"],
                "chapter": r["chapter"],
                "char_start": r["char_start"],
                "char_end": r["char_end"],
                "token_estimate": r["token_estimate"],
            }
            for r in rows
        ]

    # ------------------------------------------------------------- sessions

    def create_session(self, session_id: str, book_ids: list[str], title: str | None = None) -> None:
        self._conn.execute(
            "INSERT INTO sessions (id, started_at, book_ids, title) VALUES (?, ?, ?, ?)",
            (session_id, _now_iso(), ",".join(book_ids), title),
        )
        self._conn.commit()

    def end_session(self, session_id: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET ended_at = ? WHERE id = ?",
            (_now_iso(), session_id),
        )
        self._conn.commit()

    def append_message(
        self,
        session_id: str,
        role: str,
        content: str,
        citations: list[dict] | None = None,
    ) -> None:
        self._conn.execute(
            "INSERT INTO messages (session_id, role, content, citations_json, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                session_id,
                role,
                content,
                json.dumps(citations) if citations else None,
                _now_iso(),
            ),
        )
        self._conn.commit()

    def list_sessions(self, book_id: str | None = None) -> list[dict]:
        """List sessions, optionally filtered by book_id (in book_ids column)."""
        rows = self._conn.execute(
            "SELECT * FROM sessions ORDER BY started_at DESC LIMIT 50"
        ).fetchall()
        out = []
        for r in rows:
            d = dict(r)
            book_ids = (d.get("book_ids") or "").split(",")
            if book_id is None or book_id in book_ids:
                d["book_ids"] = book_ids
                out.append(d)
        return out

    # ------------------------------------------------------------ bookmarks

    def add_bookmark(
        self,
        book_id: str,
        *,
        chunk_index: int,
        note: str | None = None,
        chapter: str | None = None,
    ) -> int:
        cur = self._conn.execute(
            "INSERT INTO bookmarks (book_id, chunk_index, chapter, note, created_at) VALUES (?, ?, ?, ?, ?)",
            (book_id, chunk_index, chapter, note, _now_iso()),
        )
        self._conn.commit()
        return cur.lastrowid

    def list_bookmarks(self, book_id: str) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, chunk_index, chapter, note, created_at FROM bookmarks "
            "WHERE book_id = ? ORDER BY chunk_index",
            (book_id,),
        ).fetchall()
        return [
            {
                "id": r["id"],
                "chunk_index": r["chunk_index"],
                "chapter": r["chapter"],
                "note": r["note"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def delete_bookmark(self, bookmark_id: int) -> None:
        self._conn.execute("DELETE FROM bookmarks WHERE id = ?", (bookmark_id,))
        self._conn.commit()

    def list_messages(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            "SELECT * FROM messages WHERE session_id = ? ORDER BY id",
            (session_id,),
        ).fetchall()
        out = []
        for r in rows:
            out.append(
                {
                    "role": r["role"],
                    "content": r["content"],
                    "citations": json.loads(r["citations_json"]) if r["citations_json"] else None,
                    "created_at": r["created_at"],
                }
            )
        return out


def _book_from_row(row: sqlite3.Row) -> Book:
    raw_tags = row["tags_json"] if "tags_json" in row.keys() else None
    tags: list[str] = []
    if raw_tags:
        try:
            loaded = json.loads(raw_tags)
            if isinstance(loaded, list):
                tags = [str(t) for t in loaded]
        except Exception:  # noqa: BLE001
            tags = []
    return Book(
        id=row["id"],
        title=row["title"],
        author=row["author"],
        source_path=row["source_path"],
        source_format=row["source_format"],
        source_hash=row["source_hash"],
        byte_size=row["byte_size"],
        char_count=row["char_count"],
        chunk_count=row["chunk_count"],
        ingested_at=row["ingested_at"],
        soul_json=row["soul_json"],
        soul_generated_at=row["soul_generated_at"],
        soul_status=row["soul_status"],
        category=row["category"] if "category" in row.keys() else None,
        tags=tags,
    )


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")
