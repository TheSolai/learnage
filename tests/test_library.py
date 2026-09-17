"""Library (SQLite) tests."""

from pathlib import Path

from learnage.store.library import Book, Library


def _make_book(**kw) -> Book:
    base = dict(
        id="abc123def4567890",
        title="Test Book",
        author="Anne",
        source_path="/tmp/test.txt",
        source_format="txt",
        source_hash="deadbeef" * 8,
        byte_size=1234,
        char_count=5000,
        chunk_count=10,
        ingested_at="2026-09-12T10:00:00",
        soul_json=None,
        soul_generated_at=None,
        soul_status="pending",
    )
    base.update(kw)
    return Book(**base)


def test_upsert_and_get(tmp_path: Path):
    lib = Library(tmp_path / "lib.db")
    b = _make_book()
    lib.upsert_book(b)
    got = lib.get_book(b.id)
    assert got is not None
    assert got.title == "Test Book"
    lib.close()


def test_find_by_hash(tmp_path: Path):
    lib = Library(tmp_path / "lib.db")
    b = _make_book()
    lib.upsert_book(b)
    found = lib.find_by_hash(b.source_hash)
    assert found is not None
    assert found.id == b.id
    lib.close()


def test_find_by_title_fuzzy(tmp_path: Path):
    lib = Library(tmp_path / "lib.db")
    b = _make_book(title="The Cartographer's Letter")
    lib.upsert_book(b)
    assert lib.find_by_title("Cartographer") is not None
    assert lib.find_by_title("cartographer's letter") is not None
    lib.close()


def test_set_soul(tmp_path: Path):
    lib = Library(tmp_path / "lib.db")
    b = _make_book()
    lib.upsert_book(b)
    lib.set_soul(b.id, '{"summary": "x"}', status="ok")
    got = lib.get_book(b.id)
    assert got.soul_status == "ok"
    assert got.soul_json and "summary" in got.soul_json
    lib.close()


def test_replace_chunks(tmp_path: Path):
    lib = Library(tmp_path / "lib.db")
    b = _make_book()
    lib.upsert_book(b)
    lib.replace_chunks(b.id, [(0, "Chapter 1", 0, 100, 25), (1, "Chapter 1", 100, 200, 25)])
    assert lib.get_chapter_for_chunk(b.id, 0) == "Chapter 1"
    lib.close()


def test_messages_round_trip(tmp_path: Path):
    lib = Library(tmp_path / "lib.db")
    lib.create_session("sess1", ["b1", "b2"])
    lib.append_message("sess1", "user", "hello")
    lib.append_message("sess1", "assistant", "hi there", citations=[{"book_id": "b1"}])
    msgs = lib.list_messages("sess1")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "user"
    assert msgs[1]["citations"] == [{"book_id": "b1"}]
    lib.end_session("sess1")
    lib.close()
