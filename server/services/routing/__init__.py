"""Candidate selection for records-mode routing, and the scorer slot."""

from .candidates import CandidateSet, EntryView, RecordView, select_candidates
from .embeddings import Embedder, EmbeddingError, EmbeddingIndex, OpenRouterEmbedder
from .params import RetrievalParams
from .scorer import InteractionAgentScorer, Scorer, ScoringDecision, ScoringInput

__all__ = [
    "CandidateSet",
    "Embedder",
    "EmbeddingError",
    "EmbeddingIndex",
    "EntryView",
    "InteractionAgentScorer",
    "OpenRouterEmbedder",
    "RecordView",
    "RetrievalParams",
    "Scorer",
    "ScoringDecision",
    "ScoringInput",
    "select_candidates",
]
