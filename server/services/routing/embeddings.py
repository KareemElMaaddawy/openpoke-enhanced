"""Embedding index and the OpenRouter embedder."""

from __future__ import annotations

import asyncio
import hashlib
import json
import math
import os
import threading
from pathlib import Path
from typing import Dict, List, Optional, Protocol

import httpx

from ...logging_config import logger
from ...openrouter_client.client import OpenRouterBaseURL, _headers

EMBED_BATCH_SIZE = 64
_INDEX_VERSION = 1


class Embedder(Protocol):
    model: str
    dimensions: int

    async def embed(self, texts: List[str], purpose: str) -> List[List[float]]: ...


class EmbeddingError(RuntimeError):
    """Raised when embeddings could not be produced."""


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def normalize(vector: List[float]) -> List[float]:
    """L2-normalize so cosine similarity is a dot product. Rounded to 6 places for storage."""
    norm = math.sqrt(sum(x * x for x in vector))
    if norm == 0:
        return [0.0 for _ in vector]
    return [round(x / norm, 6) for x in vector]


def dot(a: List[float], b: List[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


class EmbeddingIndex:
    """agent_id -> {"text_sha256", "model", "dimensions", "vector"}.

    With a path, it loads lazily from and saves atomically to that JSON file (production).
    Without one it is in-memory only (eval harness, tests).
    """

    def __init__(self, path: Optional[Path] = None):
        self._path = path
        self._lock = threading.Lock()
        self._entries: Dict[str, dict] = {}
        self._loaded = path is None
        self.dirty = False

    @property
    def path(self) -> Optional[Path]:
        return self._path

    def _ensure_loaded_locked(self) -> None:
        if self._loaded:
            return
        self._loaded = True
        if self._path is None or not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = dict(data.get("vectors", {}))
        except Exception as exc:
            logger.warning(f"Failed to load {self._path.name}: {exc}")
            self._entries = {}

    def is_stale(self, agent_id: str, text: str, model: str, dimensions: int) -> bool:
        with self._lock:
            self._ensure_loaded_locked()
            entry = self._entries.get(agent_id)
        return (
            entry is None
            or entry.get("text_sha256") != text_sha256(text)
            or entry.get("model") != model
            or entry.get("dimensions") != dimensions
        )

    def get(self, agent_id: str) -> Optional[List[float]]:
        with self._lock:
            self._ensure_loaded_locked()
            entry = self._entries.get(agent_id)
        return entry["vector"] if entry else None

    def put(self, agent_id: str, text: str, model: str, dimensions: int, vector: List[float]) -> None:
        with self._lock:
            self._ensure_loaded_locked()
            self._entries[agent_id] = {
                "text_sha256": text_sha256(text),
                "model": model,
                "dimensions": dimensions,
                "vector": normalize(vector),
            }
            self.dirty = True

    def save(self) -> None:
        """Write to disk atomically (no-op without a path)."""
        if self._path is None:
            self.dirty = False
            return
        with self._lock:
            payload = {"version": _INDEX_VERSION, "vectors": self._entries}
            tmp_path = self._path.with_name(self._path.name + ".tmp")
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path.write_text(json.dumps(payload), encoding="utf-8")
            os.replace(tmp_path, self._path)
            self.dirty = False

    def clear(self) -> None:
        with self._lock:
            self._entries = {}
            self._loaded = True
            self.dirty = False
            if self._path is not None:
                try:
                    if self._path.exists():
                        self._path.unlink()
                except Exception as exc:
                    logger.warning(f"Failed to clear {self._path.name}: {exc}")


class OpenRouterEmbedder:
    """POST /api/v1/embeddings through OpenRouter, pinned to the OpenAI provider."""

    TIMEOUT_SECONDS = 10.0
    MAX_RETRIES = 2
    RETRY_DELAY_SECONDS = 0.5

    def __init__(
        self,
        model: str,
        dimensions: int,
        *,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.model = model
        self.dimensions = dimensions
        self._api_key = api_key
        self._url = f"{(base_url or OpenRouterBaseURL).rstrip('/')}/embeddings"
        self._transport = transport

    def _request_body(self, texts: List[str]) -> dict:
        return {
            "model": self.model,
            "input": texts,
            "dimensions": self.dimensions,
            "encoding_format": "float",
            "provider": {"order": ["openai"], "allow_fallbacks": False},
        }

    async def embed(self, texts: List[str], purpose: str) -> List[List[float]]:
        if not texts:
            return []
        headers = _headers(api_key=self._api_key)
        body = self._request_body(texts)
        last_error: Optional[Exception] = None

        async with httpx.AsyncClient(transport=self._transport, timeout=self.TIMEOUT_SECONDS) as client:
            for attempt in range(self.MAX_RETRIES + 1):
                if attempt:
                    await asyncio.sleep(self.RETRY_DELAY_SECONDS * attempt)
                try:
                    response = await client.post(self._url, headers=headers, json=body)
                except httpx.HTTPError as exc:
                    last_error = exc
                    continue
                if response.status_code == 429 or response.status_code >= 500:
                    last_error = EmbeddingError(f"HTTP {response.status_code}: {response.text[:200]}")
                    continue
                if response.status_code >= 400:
                    raise EmbeddingError(f"HTTP {response.status_code}: {response.text[:200]}")
                return self._parse(response.json(), len(texts))

        raise EmbeddingError(f"Embedding request failed after {self.MAX_RETRIES + 1} attempts: {last_error}")

    def _parse(self, payload: dict, expected: int) -> List[List[float]]:
        data = payload.get("data") if isinstance(payload, dict) else None
        if not isinstance(data, list) or len(data) != expected:
            raise EmbeddingError(f"Expected {expected} embeddings, got {payload!r:.200}")
        ordered = sorted(data, key=lambda item: item.get("index", 0))
        vectors = [item.get("embedding") for item in ordered]
        if any(not isinstance(v, list) or len(v) != self.dimensions for v in vectors):
            raise EmbeddingError(f"Embeddings missing or not {self.dimensions}-dimensional")
        return vectors


__all__ = [
    "EMBED_BATCH_SIZE",
    "Embedder",
    "EmbeddingError",
    "EmbeddingIndex",
    "OpenRouterEmbedder",
    "dot",
    "normalize",
    "text_sha256",
]
