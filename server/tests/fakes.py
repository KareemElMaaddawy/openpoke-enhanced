"""Test doubles shared by the server tests. No network."""

from __future__ import annotations

import hashlib
import math
import re
from typing import Dict, List, Optional


class FakeEmbedder:
    """Deterministic feature-hashed bag-of-words vectors.

    Tokens are hashed into `dimensions` buckets and the vector is normalized, so lexically
    similar texts get similar vectors. `vectors` overrides specific texts; `fail` makes every
    call raise. Every call's inputs are kept in `calls`.
    """

    model = "fake/bag-of-words"

    def __init__(
        self,
        dimensions: int = 64,
        vectors: Optional[Dict[str, List[float]]] = None,
        fail: bool = False,
    ):
        self.dimensions = dimensions
        self.vectors = dict(vectors or {})
        self.fail = fail
        self.calls: List[List[str]] = []

    def vector_for(self, text: str) -> List[float]:
        if text in self.vectors:
            return list(self.vectors[text])
        vector = [0.0] * self.dimensions
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            bucket = int(hashlib.md5(token.encode("utf-8")).hexdigest(), 16) % self.dimensions
            vector[bucket] += 1.0
        norm = math.sqrt(sum(x * x for x in vector)) or 1.0
        return [x / norm for x in vector]

    async def embed(self, texts: List[str], purpose: str) -> List[List[float]]:
        self.calls.append(list(texts))
        if self.fail:
            raise RuntimeError("embedding service unavailable")
        return [self.vector_for(text) for text in texts]

    @property
    def embedded_texts(self) -> List[str]:
        return [text for call in self.calls for text in call]
