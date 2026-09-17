"""SoulRecord tests."""

from learnage.store.soul import SoulRecord


def test_roundtrip():
    s = SoulRecord(
        summary="A book about maps.",
        voice={"register": "literary", "tone": "wistful"},
        themes=[{"name": "memory", "gloss": "how we hold onto places"}],
        characters=[{"name": "Mira", "role": "protagonist", "gloss": "the cartographer"}],
        plot={"shape": "linear", "central_tension": "a letter never sent"},
        key_passages=[{"quote": "Everything that has a name can be lost.", "context": "advice"}],
        craft_notes=["uses place as character"],
    )
    j = s.to_json()
    s2 = SoulRecord.from_json(j)
    assert s2.summary == s.summary
    assert s2.voice == s.voice
    assert s2.themes == s.themes
    assert s2.characters == s.characters


def test_short_brief_includes_summary():
    s = SoulRecord(summary="A short book about waiting.")
    brief = s.short_brief()
    assert "waiting" in brief
