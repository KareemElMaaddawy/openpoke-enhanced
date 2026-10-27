"""BM25 over agent retrieval texts."""

from __future__ import annotations

import math
import re
from collections import Counter
from typing import Iterable, List, Sequence

# The eval scorer's stopwords plus common chat filler.
STOPWORDS = frozenset(
    {
        "to", "for", "the", "a", "an", "of", "and", "with", "my", "re",
        "is", "it", "that", "this", "on", "in", "at", "me", "can", "you", "please", "i",
    }
)

K1 = 1.2
B = 0.75

_TOKEN = re.compile(r"[a-z0-9]+")


def tokenize(text: str) -> List[str]:
    return [t for t in _TOKEN.findall((text or "").lower()) if t not in STOPWORDS]


def bm25_scores(query_tokens: Iterable[str], documents: Sequence[Sequence[str]]) -> List[float]:
    """Okapi BM25 score of each tokenized document for the query token set."""
    n_docs = len(documents)
    if n_docs == 0:
        return []
    terms = set(query_tokens)
    avg_len = sum(len(doc) for doc in documents) / n_docs or 1.0
    doc_freq = Counter(t for doc in documents for t in set(doc) if t in terms)

    scores: List[float] = []
    for doc in documents:
        tf = Counter(t for t in doc if t in terms)
        norm = K1 * (1 - B + B * len(doc) / avg_len)
        score = 0.0
        for term, freq in tf.items():
            df = doc_freq[term]
            idf = math.log((n_docs - df + 0.5) / (df + 0.5) + 1.0)
            score += idf * freq * (K1 + 1) / (freq + norm)
        scores.append(score)
    return scores


__all__ = ["B", "K1", "STOPWORDS", "bm25_scores", "tokenize"]
