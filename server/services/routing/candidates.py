"""Candidate selection: which agent records the interaction agent sees on a turn.

Pure async functions over plain data. Nothing here reads files or settings; callers pass
records, entries, parameters, an embedder and an index, so the server and the eval harness
run the same code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..agents.records import WorkSnippet
from ..agents.text import retrieval_text
from .embeddings import EMBED_BATCH_SIZE, Embedder, EmbeddingError, EmbeddingIndex, dot, normalize
from .lexical import bm25_scores, tokenize
from .params import RetrievalParams
from .pins import find_pins
from .query import build_queries

RANKED_MAX = 20


@dataclass(frozen=True)
class RecordView:
    """What selection needs; built from AgentRecord or from the harness AgentView."""

    agent_id: str
    name: str
    purpose: str
    recent_work: Tuple[WorkSnippet, ...]
    last_active: str           # "" if unknown
    task_count: int = 0
    aliases: Tuple[str, ...] = ()

    @classmethod
    def from_record(cls, record: Any) -> "RecordView":
        return cls(
            agent_id=record.agent_id,
            name=record.name,
            purpose=record.purpose,
            recent_work=tuple(record.recent_work),
            last_active=record.last_active,
            task_count=record.task_count,
            aliases=tuple(record.aliases),
        )


@dataclass(frozen=True)
class EntryView:
    tag: str                   # user_message | agent_message | poke_reply | wait
    payload: str


@dataclass
class CandidateSet:
    mode: str                  # "full" | "retrieved" | "retrieved_lexical_fallback" | "empty"
    shown: List[str]           # agent_ids rendered into the prompt, in render order
    ranked: List[str]          # pins + fused order, first 20, for recall@k
    excluded: List[str]        # active agent_ids not shown
    pinned: List[str]
    scores: Dict[str, dict]    # agent_id -> {"sem": float|None, "lex": float|None, "rrf": float}
    queries: List[str]
    embed_calls: int
    error: Optional[str] = None   # why the semantic channel was dropped, if it was


@dataclass
class _EmbedCounter:
    calls: int = 0


async def _semantic_scores(
    records: Sequence[RecordView],
    texts: Dict[str, str],
    queries: List[str],
    embedder: Optional[Embedder],
    index: EmbeddingIndex,
    counter: _EmbedCounter,
) -> Dict[str, float]:
    """max cosine over the queries for every record. Stale record vectors are embedded in the
    same call(s) as the queries, at most EMBED_BATCH_SIZE inputs per call."""
    if embedder is None:
        raise EmbeddingError("no embedder configured")

    model, dimensions = embedder.model, embedder.dimensions
    stale = [r for r in records if index.is_stale(r.agent_id, texts[r.agent_id], model, dimensions)]
    inputs: List[Tuple[Optional[str], str]] = [(None, q) for q in queries]
    inputs += [(r.agent_id, texts[r.agent_id]) for r in stale]

    query_vectors: List[List[float]] = []
    for start in range(0, len(inputs), EMBED_BATCH_SIZE):
        batch = inputs[start:start + EMBED_BATCH_SIZE]
        counter.calls += 1
        vectors = await embedder.embed([text for _, text in batch], purpose="retrieval")
        if len(vectors) != len(batch):
            raise EmbeddingError(f"expected {len(batch)} vectors, got {len(vectors)}")
        for (agent_id, text), vector in zip(batch, vectors):
            if agent_id is None:
                query_vectors.append(normalize(vector))
            else:
                index.put(agent_id, text, model, dimensions, vector)

    scores: Dict[str, float] = {}
    for r in records:
        vector = index.get(r.agent_id) or []
        scores[r.agent_id] = max(dot(q, vector) for q in query_vectors)
    return scores


def _rank(ids: Sequence[str], key: Dict[str, Any]) -> Dict[str, int]:
    """1-based ranks of the ids present in *key*, highest value first; ties keep roster order."""
    ordered = sorted((i for i in ids if i in key), key=lambda i: key[i], reverse=True)
    return {agent_id: position for position, agent_id in enumerate(ordered, start=1)}


async def select_candidates(
    records: Sequence[RecordView],
    message_text: str,
    message_type: str,
    entries: Sequence[EntryView],
    params: RetrievalParams,
    embedder: Optional[Embedder] = None,
    index: Optional[EmbeddingIndex] = None,
) -> CandidateSet:
    """Choose the records to show. *records* are the active records in roster order."""
    ids = [r.agent_id for r in records]

    # 1. Short-circuits
    if not records:
        return CandidateSet("empty", [], [], [], [], {}, [], 0)
    if len(records) <= params.full_roster_max:
        return CandidateSet("full", list(ids), list(ids), [], [], {}, [], 0)

    # 2. Pins, 3. queries
    pins = find_pins(message_text, message_type, entries, records, params)
    queries = build_queries(message_text, message_type, entries, params)
    texts = {r.agent_id: retrieval_text(r) for r in records}

    # 4. Semantic channel (9. failure drops it for this turn)
    mode = "retrieved"
    error: Optional[str] = None
    counter = _EmbedCounter()
    sem: Dict[str, float] = {}
    if params.use_semantic:
        try:
            sem = await _semantic_scores(
                records, texts, queries, embedder, index if index is not None else EmbeddingIndex(), counter
            )
        except Exception as exc:
            mode, error, sem = "retrieved_lexical_fallback", f"{type(exc).__name__}: {exc}", {}

    # 5. Lexical channel
    lex: Dict[str, float] = {}
    if params.use_lexical:
        query_tokens = set().union(*(tokenize(q) for q in queries))
        raw = bm25_scores(query_tokens, [tokenize(texts[i]) for i in ids])
        lex = dict(zip(ids, raw))

    # 6. Recency channel
    last_active = {r.agent_id: r.last_active for r in records}
    recency = {i: last_active[i] for i in ids if last_active[i]} if params.w_rec > 0 else {}

    # 7. Reciprocal rank fusion
    channels = [
        (params.w_sem, _rank(ids, sem)),
        (params.w_lex, _rank(ids, {i: s for i, s in lex.items() if s > 0})),
        (params.w_rec, _rank(ids, recency)),
    ]
    rrf = {
        i: sum(w / (params.rrf_k + ranks[i]) for w, ranks in channels if w and i in ranks) for i in ids
    }
    fused = sorted(ids)
    fused.sort(key=lambda i: last_active[i], reverse=True)
    fused.sort(key=lambda i: rrf[i], reverse=True)

    # 8. Output
    ranked = (pins + [i for i in fused if i not in pins])[:RANKED_MAX]
    shown = ranked[: params.k]
    shown_set = set(shown)
    scores = {
        i: {"sem": sem.get(i) if sem else None, "lex": lex.get(i) if params.use_lexical else None, "rrf": rrf[i]}
        for i in ids
    }
    return CandidateSet(
        mode=mode,
        shown=shown,
        ranked=ranked,
        excluded=[i for i in ids if i not in shown_set],
        pinned=pins,
        scores=scores,
        queries=queries,
        embed_calls=counter.calls,
        error=error,
    )


__all__ = ["CandidateSet", "EntryView", "RANKED_MAX", "RecordView", "select_candidates"]
