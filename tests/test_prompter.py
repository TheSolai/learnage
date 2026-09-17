"""Prompter tests."""

from learnage.interviewer.prompter import compose
from learnage.interviewer.retriever import Passage
from learnage.store.library import Book
from learnage.store.soul import SoulRecord


def _book():
    return Book(
        id="b1",
        title="Test",
        author="Author",
        source_path="/x",
        source_format="txt",
        source_hash="h",
        byte_size=1,
        char_count=10,
        chunk_count=1,
        ingested_at="now",
        soul_json=None,
        soul_generated_at=None,
        soul_status="ok",
    )


def test_compose_includes_soul_and_passages():
    b = _book()
    s = SoulRecord(summary="About maps.")
    passages = [Passage(book_id="b1", chunk_index=0, chapter="Ch 1", text="Some quote.", score=0.9)]
    msgs = compose(
        question="what is it about?",
        books=[b],
        souls={"b1": s},
        passages=passages,
        history=[],
    )
    assert msgs[0]["role"] == "system"
    user_msg = msgs[1]["content"]
    assert "LIBRARY" in user_msg
    assert "PASSAGES" in user_msg
    assert "About maps." in user_msg
    assert "Some quote." in user_msg
    assert "what is it about?" in user_msg


def test_compose_handles_no_passages():
    b = _book()
    msgs = compose(question="hi", books=[b], souls={"b1": None}, passages=[], history=[])
    assert "no passages" in msgs[1]["content"].lower()


def test_compose_includes_history():
    b = _book()
    history = [{"role": "user", "content": "earlier question"}, {"role": "assistant", "content": "earlier answer"}]
    msgs = compose(question="follow up", books=[b], souls={"b1": None}, passages=[], history=history)
    assert "earlier question" in msgs[1]["content"]
    assert "earlier answer" in msgs[1]["content"]
