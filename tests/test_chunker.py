"""Chunker tests."""

from learnage.ingest.chunker import chunk_text, split_sentences, chunk_book


def test_split_sentences_basic():
    text = "Hello world. This is a test! Another sentence?"
    sents = split_sentences(text)
    assert len(sents) == 3
    assert sents[0] == "Hello world."
    assert sents[1] == "This is a test!"
    assert sents[2] == "Another sentence?"


def test_split_sentences_handles_abbreviations():
    text = "Dr. Smith arrived at noon. Mr. Jones followed."
    sents = split_sentences(text)
    # We don't strictly require a count (abbrev handling is heuristic),
    # but we should NOT split "Dr." from "Smith".
    assert any("Dr. Smith arrived" in s for s in sents)
    assert any("Mr. Jones" in s for s in sents)


def test_chunk_text_empty():
    assert chunk_text("") == []
    assert chunk_text("   \n\n  ") == []


def test_chunk_text_creates_chunks():
    text = (
        "This is sentence one. " * 20
        + "This is sentence two. " * 20
        + "This is sentence three. " * 20
    )
    chunks = chunk_text(text, target_tokens=50, overlap_tokens=10)
    assert len(chunks) >= 2
    # Each chunk has chapter metadata = None when chunk_text is called directly.
    assert all(c.chapter is None for c in chunks)
    # Chunks cover the input without huge gaps.
    full = " ".join(c.text for c in chunks)
    assert "sentence one" in full
    assert "sentence three" in full


def test_chunk_text_overlap():
    text = ("Sentence. " * 100)
    chunks = chunk_text(text, target_tokens=30, overlap_tokens=10)
    if len(chunks) >= 2:
        # The tail of chunk N should appear in chunk N+1 (overlap).
        tail = chunks[0].text.split()[-3:]
        next_text = chunks[1].text
        assert any(w in next_text for w in tail), "expected overlap between consecutive chunks"


def test_chunk_book_preserves_chapter_metadata():
    chapters = [
        ("Chapter One", "Once upon a time. There was a bear. The bear was brave."),
        ("Chapter Two", "The bear met a fox. They became friends. They went home."),
    ]
    chunks = chunk_book(chapters, target_tokens=10, overlap_tokens=2)
    chapters_seen = {c.chapter for c in chunks}
    assert "Chapter One" in chapters_seen
    assert "Chapter Two" in chapters_seen
