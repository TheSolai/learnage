"""Preset / config tests."""

import pytest

from learnage.config import load_preset


def test_load_balanced():
    p = load_preset("balanced")
    assert p.name == "balanced"
    assert p.llm
    assert p.embed
    assert p.chunk_target_tokens > 0


def test_load_fast_and_literary():
    fast = load_preset("fast")
    literary = load_preset("literary")
    assert fast.chunk_target_tokens < literary.chunk_target_tokens


def test_load_unknown_raises():
    with pytest.raises(FileNotFoundError):
        load_preset("does-not-exist")


def test_with_overrides():
    p = load_preset("balanced")
    p2 = p.with_overrides(llm="custom:1b", retrieval_k=42)
    assert p2.llm == "custom:1b"
    assert p2.retrieval_k == 42
    # Other fields preserved.
    assert p2.embed == p.embed
