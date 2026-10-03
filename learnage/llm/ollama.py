"""Ollama HTTP client — chat, embed, stream."""

from __future__ import annotations

import asyncio
import os
from typing import Iterator

import httpx


DEFAULT_URL = "http://localhost:11434"


class OllamaError(RuntimeError):
    """Raised on Ollama API errors."""


class OllamaClient:
    """Minimal Ollama HTTP client.

    Handles chat (with optional streaming), embeddings, and a model-existence
    check. Designed to be reused — keep one instance per process.
    """

    def __init__(self, base_url: str | None = None, timeout: float = 120.0) -> None:
        self.base_url = (base_url or os.environ.get("LEARNAGE_OLLAMA_URL") or DEFAULT_URL).rstrip("/")
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "OllamaClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ utils

    def _post(self, path: str, json: dict) -> dict:
        try:
            r = self._client.post(f"{self.base_url}{path}", json=json)
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama unreachable at {self.base_url}: {e}") from e
        if r.status_code != 200:
            raise OllamaError(f"Ollama {path} returned {r.status_code}: {r.text[:300]}")
        return r.json()

    def _stream_post(self, path: str, json: dict) -> Iterator[dict]:
        try:
            with self._client.stream("POST", f"{self.base_url}{path}", json=json) as r:
                if r.status_code != 200:
                    body = r.read().decode("utf-8", errors="replace")
                    raise OllamaError(f"Ollama {path} returned {r.status_code}: {body[:300]}")
                for line in r.iter_lines():
                    if not line:
                        continue
                    try:
                        import json as _json
                        yield _json.loads(line)
                    except Exception:  # noqa: BLE001
                        continue
        except httpx.HTTPError as e:
            raise OllamaError(f"Ollama unreachable at {self.base_url}: {e}") from e

    def ping(self) -> bool:
        try:
            r = self._client.get(f"{self.base_url}/api/tags", timeout=5.0)
            return r.status_code == 200
        except httpx.HTTPError:
            return False

    def list_models(self) -> list[str]:
        r = self._client.get(f"{self.base_url}/api/tags", timeout=10.0)
        if r.status_code != 200:
            raise OllamaError(f"Ollama /api/tags returned {r.status_code}")
        return [m["name"] for m in r.json().get("models", [])]

    def has_model(self, name: str) -> bool:
        # Ollama accepts tags like "qwen3:8b" or "qwen3:8b-q4_0"; match on prefix.
        for m in self.list_models():
            if m == name or m.split(":")[0] == name.split(":")[0]:
                return True
        return False

    # ------------------------------------------------------------------ chat

    def chat(
        self,
        model: str,
        messages: list[dict],
        *,
        stream: bool = False,
        options: dict | None = None,
        tools: list[dict] | None = None,
    ) -> Iterator[dict] | dict:
        """Call /api/chat. Returns a stream iterator if stream=True, else a final dict."""
        payload: dict = {"model": model, "messages": messages, "stream": stream}
        if options:
            payload["options"] = options
        if tools:
            payload["tools"] = tools
        if stream:
            return self._stream_post("/api/chat", payload)
        return self._post("/api/chat", payload)

    # ------------------------------------------------------------------ embed

    def embed(self, model: str, text: str) -> list[float]:
        """Embed a single string. Truncates to fit the model's context."""
        text = _truncate_for_embed(text)
        out = self._post("/api/embeddings", {"model": model, "prompt": text})
        return out.get("embedding", [])

    def embed_batch(self, model: str, texts: list[str], *, batch_size: int = 16) -> list[list[float]]:
        """Embed many strings sequentially. Order is preserved."""
        results: list[list[float]] = []
        for t in texts:
            results.append(self.embed(model, t))
        return results

    async def embed_batch_async(
        self,
        model: str,
        texts: list[str],
        *,
        concurrency: int = 16,
    ) -> list[list[float]]:
        """Embed many strings concurrently via async httpx. Order is preserved."""
        sem = asyncio.Semaphore(concurrency)

        async def _one(text: str) -> list[float]:
            text = _truncate_for_embed(text)
            async with sem:
                async with httpx.AsyncClient(timeout=self.timeout) as c:
                    try:
                        r = await c.post(
                            f"{self.base_url}/api/embeddings",
                            json={"model": model, "prompt": text},
                        )
                    except httpx.HTTPError as e:
                        raise OllamaError(f"Ollama unreachable: {e}") from e
                if r.status_code != 200:
                    raise OllamaError(f"Ollama embed returned {r.status_code}: {r.text[:300]}")
                return r.json().get("embedding", [])

        # Run all concurrently; gather preserves order.
        coros = [_one(t) for t in texts]
        return await asyncio.gather(*coros)


def _truncate_for_embed(text: str, *, max_chars: int = 1500) -> str:
    """Truncate text to fit an embed model's context window.

    nomic-embed-text has a 2048-token context but BERT-style tokenizers
    balloon single-char tokens, so we cap at ~1500 chars which is safely
    under the limit for inputs with lots of punctuation.
    """
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def get_client(url: str | None = None) -> OllamaClient:
    """Convenience factory."""
    return OllamaClient(url)

