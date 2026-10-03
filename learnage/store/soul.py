"""Soul access helpers — structured soul records with backward compatibility."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any


@dataclass
class SoulRecord:
    """Structured soul of a book.

    Backward-compatible: legacy fields (`summary`, `voice`, `themes`,
    `characters`, `plot`, `key_passages`, `craft_notes`) keep their
    existing JSON shapes. New fields add depth:
      - meta:          genre / period / form tags
      - key_concepts:  terms, doctrines, techniques the book introduces
      - key_figures:   people, places, deities, named entities
      - questions:     questions the book answers (great for interviewer prompts)
      - quotes:        short representative passages (raw list, no context)
      - tone_words:    single-word adjectives capturing the book's atmosphere
    """

    summary: str = ""
    voice: dict[str, Any] | None = None
    themes: list[dict[str, str]] | None = None
    characters: list[dict[str, str]] | None = None
    plot: dict[str, str] | None = None
    key_passages: list[dict[str, str]] | None = None
    craft_notes: list[str] | None = None

    # New structured fields
    meta: dict[str, str] = field(default_factory=dict)
    key_concepts: list[str] = field(default_factory=list)
    key_figures: list[str] = field(default_factory=list)
    questions: list[str] = field(default_factory=list)
    quotes: list[str] = field(default_factory=list)
    tone_words: list[str] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "summary": self.summary,
                "voice": self.voice or {},
                "themes": self.themes or [],
                "characters": self.characters or [],
                "plot": self.plot or {},
                "key_passages": self.key_passages or [],
                "craft_notes": self.craft_notes or [],
                "meta": self.meta or {},
                "key_concepts": self.key_concepts or [],
                "key_figures": self.key_figures or [],
                "questions": self.questions or [],
                "quotes": self.quotes or [],
                "tone_words": self.tone_words or [],
            },
            ensure_ascii=False,
            indent=2,
        )

    @staticmethod
    def from_json(s: str) -> "SoulRecord":
        data = json.loads(s)
        return SoulRecord(
            summary=data.get("summary", "") or "",
            voice=data.get("voice") or {},
            themes=data.get("themes") or [],
            characters=data.get("characters") or [],
            plot=data.get("plot") or {},
            key_passages=data.get("key_passages") or [],
            craft_notes=data.get("craft_notes") or [],
            meta=data.get("meta") or {},
            key_concepts=list(data.get("key_concepts") or []),
            key_figures=list(data.get("key_figures") or []),
            questions=list(data.get("questions") or []),
            quotes=list(data.get("quotes") or []),
            tone_words=list(data.get("tone_words") or []),
        )

    @property
    def is_empty(self) -> bool:
        return not any(
            [
                self.summary,
                self.voice,
                self.themes,
                self.characters,
                self.plot,
                self.key_passages,
                self.craft_notes,
                self.meta,
                self.key_concepts,
                self.key_figures,
                self.questions,
                self.quotes,
                self.tone_words,
            ]
        )

    def short_brief(self, *, max_chars: int = 1200) -> str:
        """Compact textual brief for the interview prompt."""
        parts: list[str] = []
        if self.summary:
            parts.append(f"Summary: {self.summary}")
        if self.voice:
            v = self.voice
            vbits = [str(v.get(k, "")) for k in ("register", "tone", "rhythm", "diction") if v.get(k)]
            if vbits:
                parts.append("Voice: " + "; ".join(vbits))
        if self.tone_words:
            parts.append("Tone: " + ", ".join(self.tone_words[:8]))
        if self.meta:
            bits = [f"{k}: {v}" for k, v in self.meta.items() if v]
            if bits:
                parts.append("Meta: " + "; ".join(bits))
        if self.themes:
            parts.append(
                "Themes: "
                + ", ".join(f"{t.get('name', '')} ({t.get('gloss', '')})" for t in self.themes)
            )
        if self.key_concepts:
            parts.append("Concepts: " + ", ".join(self.key_concepts[:10]))
        if self.key_figures:
            parts.append("Figures: " + ", ".join(self.key_figures[:10]))
        if self.characters:
            parts.append(
                "Characters: "
                + ", ".join(f"{c.get('name', '')} — {c.get('gloss', '')}" for c in self.characters)
            )
        if self.questions:
            parts.append(
                "Questions: "
                + "; ".join(self.questions[:5])
            )
        if self.plot:
            p = self.plot
            if p.get("central_tension"):
                parts.append(f"Central tension: {p['central_tension']}")
        if self.key_passages:
            parts.append(
                "Key passages:\n  - "
                + "\n  - ".join(
                    f"“{kp.get('quote', '')}” ({kp.get('context', '')})"
                    for kp in self.key_passages[:5]
                )
            )
        if self.quotes:
            parts.append(
                "Quotes:\n  - "
                + "\n  - ".join(f"“{q}”" for q in self.quotes[:5])
            )
        if self.craft_notes:
            parts.append("Notes:\n  - " + "\n  - ".join(self.craft_notes[:5]))
        out = "\n".join(parts)
        return out[:max_chars]


def merge_soul_brief(records: list[SoulRecord], *, max_chars: int = 3000) -> str:
    """Build a 'collective soul' brief from many books — used by Minds.

    Aggregates themes, concepts, figures, and tone across books. Avoids
    blowing past `max_chars`.
    """
    if not records:
        return ""
    parts: list[str] = [f"Collective soul across {len(records)} book(s):\n"]
    themes: dict[str, int] = {}
    concepts: dict[str, int] = {}
    figures: dict[str, int] = {}
    tone_counter: dict[str, int] = {}
    for r in records:
        if r.summary:
            parts.append(f"- {r.summary[:240]}")
        for t in r.themes or []:
            name = (t.get("name") or "").strip()
            if name:
                themes[name] = themes.get(name, 0) + 1
        for c in r.key_concepts or []:
            c = c.strip()
            if c:
                concepts[c] = concepts.get(c, 0) + 1
        for f in r.key_figures or []:
            f = f.strip()
            if f:
                figures[f] = figures.get(f, 0) + 1
        for w in r.tone_words or []:
            w = w.strip().lower()
            if w:
                tone_counter[w] = tone_counter.get(w, 0) + 1

    def _top(d: dict[str, int], n: int) -> list[str]:
        return [k for k, _ in sorted(d.items(), key=lambda kv: (-kv[1], kv[0].lower()))[:n]]

    if themes:
        parts.append("Recurring themes: " + ", ".join(_top(themes, 12)))
    if concepts:
        parts.append("Recurring concepts: " + ", ".join(_top(concepts, 12)))
    if figures:
        parts.append("Recurring figures: " + ", ".join(_top(figures, 12)))
    if tone_counter:
        parts.append("Dominant tones: " + ", ".join(_top(tone_counter, 8)))

    out = "\n".join(parts)
    return out[:max_chars]
