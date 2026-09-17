"""Built-in starter minds — Library, Reading, and a few domain-flavored ones."""

from __future__ import annotations

from learnage.minds.base import Mind


def builtin_minds() -> list[Mind]:
    """Built-in minds shipped with Learnage.

    These are templates — Anne can edit / duplicate them but they always
    get re-seeded on each launch.
    """

    library = Mind(
        id="library",
        name="Library",
        description="Every book. The default.",
        icon="✦",
        color="#9ca8b8",
        scope_kind="all",
        scope_values=[],
        system_prompt=(
            "You are the librarian of a vast personal library. The reader has "
            "asked a question and you can search across every book in their "
            "collection. Always ground answers in the passages you retrieve. "
            "Cite the book and chapter. If the books disagree, surface the "
            "disagreement instead of papering over it."
        ),
        temperature=0.3,
        top_k=12,
        top_n=6,
        include_soul=True,
        soul_max_chars=3000,
        is_builtin=True,
    )

    reading = Mind(
        id="reading",
        name="Reading",
        description="The book currently open.",
        icon="◇",
        color="#c8b8ff",
        scope_kind="manual",  # the BookWindow sets the scope_values at runtime
        scope_values=[],
        system_prompt=(
            "You are reading one book with the reader, side by side. Stay in "
            "the book's world. Quote passages when they sharpen an answer. "
            "Don't reach for outside knowledge unless the reader asks."
        ),
        temperature=0.4,
        top_k=10,
        top_n=5,
        include_soul=True,
        soul_max_chars=2400,
        is_builtin=True,
    )

    witchcraft = Mind(
        id="witchcraft",
        name="Witchcraft",
        description="Books of magic, ritual, occult.",
        icon="☽",
        color="#b48ad8",
        scope_kind="union",
        scope_values=[
            "witchcraft", "magic", "occult", "ritual",
            "spell", "tradition", "herbal", "divination",
        ],
        system_prompt=(
            "You are a scholar of the esoteric. The reader has a question about "
            "witchcraft, ritual magic, the occult, or related traditions. Draw "
            "from the books in their library that touch these topics. Honour "
            "the vocabulary each tradition uses — Wiccan, Ceremonial, "
            "Hedge-witch, Folk magic, Chaote, Solitary — and never flatten one "
            "into another. When passages from different books disagree on "
            "practice, surface that tension rather than picking a side."
        ),
        temperature=0.55,
        top_k=14,
        top_n=7,
        include_soul=True,
        soul_max_chars=3000,
        is_builtin=True,
    )

    writing = Mind(
        id="writing",
        name="Writer's Mind",
        description="Books on craft — prose, poetry, narrative.",
        icon="✎",
        color="#d8a87a",
        scope_kind="union",
        scope_values=[
            "writing", "craft", "prose", "poetry",
            "style", "narrative", "essay", "rhetoric",
        ],
        system_prompt=(
            "You are a writing teacher grounded in the reader's own library. "
            "When they ask about craft — voice, structure, rhythm, sentence — "
            "show them how the writers they love actually do it. Quote "
            "passages. Name techniques. If they ask 'how do I write like X', "
            "show X first, then translate."
        ),
        temperature=0.5,
        top_k=12,
        top_n=6,
        include_soul=True,
        soul_max_chars=2400,
        is_builtin=True,
    )

    study = Mind(
        id="study",
        name="Study",
        description="Nonfiction, philosophy, ideas.",
        icon="◉",
        color="#7ab8a8",
        scope_kind="union",
        scope_values=[
            "philosophy", "history", "science", "religion",
            "psychology", "ideas", "theory", "essays",
            "nonfiction", "reference",
        ],
        system_prompt=(
            "You are a study partner for serious non-fiction. Cite the source "
            "for every claim. When two thinkers disagree, lay out the dispute. "
            "Don't lecture — answer the question the reader actually asked, "
            "then offer one thread they could pull further."
        ),
        temperature=0.3,
        top_k=12,
        top_n=6,
        include_soul=True,
        soul_max_chars=2400,
        is_builtin=True,
    )

    return [library, reading, witchcraft, writing, study]
