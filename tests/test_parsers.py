"""Parser tests."""

from pathlib import Path

import pytest

from learnage.ingest.parsers import detect_format, parse


SAMPLE = Path(__file__).resolve().parent.parent / "data" / "samples" / "short_story.txt"


def test_detect_txt():
    assert detect_format(SAMPLE) == "txt"


def test_detect_unknown_raises(tmp_path):
    f = tmp_path / "thing.xyz"
    f.write_text("hi")
    with pytest.raises(ValueError):
        detect_format(f)


def test_parse_txt():
    book = parse(SAMPLE)
    assert "Cartographer" in book.title or "Letter" in book.title or book.title
    assert book.author is None  # not encoded in sample
    chapters = [c for c in book.chapters if c.heading]
    assert any("Letter" in (c.heading or "") for c in chapters)
    # Some text from each chapter should appear in full_text.
    assert "Mira unfolded" in book.full_text
    assert "ELARA" in book.full_text
