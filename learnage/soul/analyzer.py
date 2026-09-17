"""Soul analyzer — extract a rich, structured soul from a book's text."""

from __future__ import annotations

import json
import re
from typing import Iterable

from learnage.ingest.chunker import Chunk
from learnage.llm.ollama import OllamaClient
from learnage.store.soul import SoulRecord


_SOUL_SCHEMA_HINT = """{
  "summary": "One paragraph (3-5 sentences) capturing the book's essence.",
  "voice": {"register": "...", "tone": "...", "rhythm": "...", "diction": "..."},
  "meta": {"genre": "...", "period": "...", "form": "...", "language": "..."},
  "tone_words": ["...", "..."],
  "themes": [{"name": "...", "gloss": "..."}],
  "key_concepts": ["...", "..."],
  "key_figures": ["people/places/deities named"],
  "questions": ["questions the book answers, framed as if asked by a reader"],
  "quotes": ["short representative passage (max 240 chars)"],
  "characters": [{"name": "...", "role": "protagonist|antagonist|supporting|...", "gloss": "..."}],
  "plot": {"shape": "...", "central_tension": "...", "arc": "..."},
  "key_passages": [{"quote": "...", "context": "...", "why": "..."}],
  "craft_notes": ["..."]
}"""


def _build_prompt(book_title: str, author: str | None, condensed: str, category: str | None) -> list[dict]:
    sys = (
        "You are a literary analyst and close reader. Extract the SOUL of the book in front of you.\n"
        "Return STRICT JSON matching this shape:\n"
        f"{_SOUL_SCHEMA_HINT}\n"
        "Be specific. Pull real concepts, real figures, real phrases from the text. "
        "Do not include any prose outside the JSON. Do not use markdown fences."
    )
    user = (
        f"Book: {book_title}"
        + (f" by {author}" if author else "")
        + (f"  ·  Category: {category}" if category else "")
        + "\n\nBelow are excerpts from the book (first lines, chapter headings, "
        "and representative passages). Read carefully. Then output the JSON.\n\n"
        + condensed
    )
    return [
        {"role": "system", "content": sys},
        {"role": "user", "content": user},
    ]


def _condense(chunks: Iterable[Chunk], max_chars: int) -> str:
    """Build a condensed view of a book for the soul prompt."""
    chunks = list(chunks)
    parts: list[str] = []
    budget = max_chars
    # Always include first chunk and last chunk if any.
    if chunks:
        parts.append("[FIRST PASSAGE]\n" + chunks[0].text[:4000])
        budget -= len(parts[-1])

    # Sample evenly across the rest.
    if len(chunks) > 2 and budget > 1000:
        middle = chunks[1:-1]
        step = max(1, len(middle) // 6)
        sampled = middle[::step]
        for c in sampled:
            head = f"[ch: {c.chapter or '—'}]\n" if c.chapter else "[ch: —]\n"
            piece = head + c.text[:2000]
            if budget - len(piece) < 0:
                break
            parts.append(piece)
            budget -= len(piece)

    # Always include last chunk if any.
    if len(chunks) > 1 and budget > 1000:
        tail = "[LAST PASSAGE]\n" + chunks[-1].text[:4000]
        if budget - len(tail) >= 0:
            parts.append(tail)

    return "\n\n".join(parts)[:max_chars]


_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(text: str) -> dict | None:
    """Pull the first JSON object out of a (possibly noisy) response."""
    if not text:
        return None
    # Strip code fences if present
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:  # noqa: BLE001
            pass
    m = _JSON_RE.search(text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:  # noqa: BLE001
        return None


def _string_list(value: object, *, limit: int = 16, max_len: int = 120) -> list[str]:
    """Coerce a value into a clean list[str]."""
    if not value:
        return []
    out: list[str] = []
    if isinstance(value, list):
        for v in value:
            if isinstance(v, str):
                s = v.strip()
                if s:
                    out.append(s[:max_len])
            elif isinstance(v, dict):
                # Common shapes: {"name": ..., "gloss": ...}
                name = v.get("name") or v.get("term") or v.get("concept") or v.get("figure")
                if isinstance(name, str) and name.strip():
                    out.append(name.strip()[:max_len])
            if len(out) >= limit:
                break
    return out


def _string_dict(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        return {}
    return {str(k): str(v).strip()[:240] for k, v in value.items() if v}


def analyze_soul(
    *,
    title: str,
    author: str | None,
    chunks: list[Chunk],
    client: OllamaClient,
    model: str,
    category: str | None = None,
    max_input_chars: int = 80_000,
) -> SoulRecord:
    """Ask an LLM to extract a rich soul of a book from a condensed view."""
    condensed = _condense(chunks, max_input_chars)
    messages = _build_prompt(title, author, condensed, category)

    resp = client.chat(model=model, messages=messages, stream=False)
    raw = ""
    if isinstance(resp, dict):
        raw = (resp.get("message") or {}).get("content", "") or ""

    data = _extract_json(raw)
    if not data:
        # Retry once with a fix-it hint.
        fix_messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user", "content": "Return ONLY valid JSON. No commentary."},
        ]
        resp = client.chat(model=model, messages=fix_messages, stream=False)
        if isinstance(resp, dict):
            raw = (resp.get("message") or {}).get("content", "") or ""
        data = _extract_json(raw)

    if not data:
        return SoulRecord(
            summary="(soul analysis failed — model returned non-JSON)",
            craft_notes=["Soul analysis could not parse JSON from the model."],
        )

    return SoulRecord(
        summary=str(data.get("summary", "")).strip(),
        voice=data.get("voice") or {},
        themes=data.get("themes") or [],
        characters=data.get("characters") or [],
        plot=data.get("plot") or {},
        key_passages=data.get("key_passages") or [],
        craft_notes=data.get("craft_notes") or [],
        meta=_string_dict(data.get("meta")),
        key_concepts=_string_list(data.get("key_concepts"), limit=20),
        key_figures=_string_list(data.get("key_figures"), limit=20),
        questions=_string_list(data.get("questions"), limit=12, max_len=200),
        quotes=_string_list(data.get("quotes"), limit=8, max_len=240),
        tone_words=_string_list(data.get("tone_words"), limit=12, max_len=32),
    )
