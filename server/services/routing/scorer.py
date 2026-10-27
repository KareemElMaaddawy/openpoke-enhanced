"""Scorer slot between candidate selection and the prompt.

Version 1 ships only the pass-through scorer: the interaction agent decides among the
candidates. Later scorers return "reuse", "create" or "ask" with a confidence; those are
advisory until a scorer spec chooses how they are consumed (hint or enforce).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Protocol, Tuple

from .candidates import CandidateSet, EntryView, RecordView


@dataclass(frozen=True)
class ScoringInput:
    message_text: str
    message_type: str
    entries: Tuple[EntryView, ...]
    candidates: Tuple[RecordView, ...]       # in CandidateSet.shown order
    candidate_set: CandidateSet


@dataclass
class ScoringDecision:
    kind: str                                # "defer" | "reuse" | "create" | "ask"
    agent_id: Optional[str] = None           # for "reuse"
    confidence: Optional[float] = None
    candidates: Optional[List[str]] = None   # a scorer may reorder or trim the shown list (rerankers)
    llm_calls: list = field(default_factory=list)   # model calls the scorer made, for cost accounting
    diagnostics: dict = field(default_factory=dict)


class Scorer(Protocol):
    name: str
    version: str

    async def decide(self, inp: ScoringInput) -> ScoringDecision: ...


class InteractionAgentScorer:
    """Defer to the interaction agent: render the shown candidates and let it route."""

    name, version = "interaction_agent", "1"

    async def decide(self, inp: ScoringInput) -> ScoringDecision:
        return ScoringDecision(kind="defer")


__all__ = ["InteractionAgentScorer", "Scorer", "ScoringDecision", "ScoringInput"]
