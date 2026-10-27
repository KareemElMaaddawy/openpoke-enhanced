"""Routing strategies: what the interaction agent is shown and which routing tools it gets.

`legacy` is today's system (names-only roster, create-or-reuse by name) and returns exactly
what the module functions return. `records` shows agent records chosen by candidate
selection and routes by agent_id. The mode is read from settings when a runtime is created.
"""

from __future__ import annotations

import dataclasses
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence

from ...config import Settings, get_settings
from ...logging_config import logger
from ...services.agents import get_agent_records, reconcile_from_roster, render_agent_entry
from ...services.execution import get_agent_roster, get_execution_agent_logs
from ...services.routing import (
    CandidateSet,
    EmbeddingIndex,
    EntryView,
    InteractionAgentScorer,
    OpenRouterEmbedder,
    RecordView,
    RetrievalParams,
    Scorer,
    ScoringInput,
    select_candidates,
)
from .agent import build_system_prompt, prepare_message_with_history
from .records_prompt import build_records_system_prompt, prepare_records_messages
from .tools import ToolResult, get_tool_schemas, handle_tool_call
from .tools_records import get_records_tool_schemas, handle_records_tool_call


class RoutingStrategy(Protocol):
    name: str

    def build_system_prompt(self) -> str: ...

    def tool_schemas(self) -> List[dict]: ...

    async def prepare_messages(
        self,
        latest_text: str,
        transcript: str,
        message_type: str,
        entries: Sequence[EntryView],
    ) -> List[Dict[str, str]]: ...

    def handle_tool_call(self, name: str, arguments: Any) -> ToolResult: ...


class LegacyRouting:
    """Returns exactly what today's code returns."""

    name = "legacy"

    def build_system_prompt(self) -> str:
        return build_system_prompt()

    def tool_schemas(self) -> List[dict]:
        return get_tool_schemas()

    async def prepare_messages(
        self,
        latest_text: str,
        transcript: str,
        message_type: str,
        entries: Sequence[EntryView],
    ) -> List[Dict[str, str]]:
        return prepare_message_with_history(latest_text, transcript, message_type)

    def handle_tool_call(self, name: str, arguments: Any) -> ToolResult:
        return handle_tool_call(name, arguments)


# Production singletons for records mode

_DATA_DIR = Path(__file__).resolve().parent.parent.parent / "data"
_EMBEDDINGS_PATH = _DATA_DIR / "execution_agents" / "embeddings.json"

_embedding_index: Optional[EmbeddingIndex] = None
_singleton_lock = threading.Lock()

# Turns whose semantic channel failed and fell back to lexical retrieval (process lifetime).
EMBEDDING_FAILURES = 0


def get_embedding_index() -> EmbeddingIndex:
    """The production vector cache at server/data/execution_agents/embeddings.json."""
    global _embedding_index
    if _embedding_index is None:
        with _singleton_lock:
            if _embedding_index is None:
                _embedding_index = EmbeddingIndex(_EMBEDDINGS_PATH)
    return _embedding_index


def retrieval_params(settings: Settings) -> RetrievalParams:
    """RetrievalParams defaults, with full_roster_max from settings (OPENPOKE_FULL_ROSTER_MAX)."""
    return dataclasses.replace(RetrievalParams(), full_roster_max=settings.full_roster_max)


class RecordsRouting:
    """Reads records, selects candidates, scores, renders, and logs the CandidateSet."""

    name = "records"

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        store=None,
        index: Optional[EmbeddingIndex] = None,
        embedder=None,
        scorer: Optional[Scorer] = None,
    ) -> None:
        settings = settings or get_settings()
        self.params = retrieval_params(settings)
        self.store = store or get_agent_records()
        self.index = index if index is not None else get_embedding_index()
        self.embedder = embedder or OpenRouterEmbedder(
            settings.embedding_model,
            settings.embedding_dimensions,
            api_key=settings.openrouter_api_key,
        )
        self.scorer: Scorer = scorer or InteractionAgentScorer()
        self.last_candidate_set: Optional[CandidateSet] = None

    def build_system_prompt(self) -> str:
        return build_records_system_prompt()

    def tool_schemas(self) -> List[dict]:
        return get_records_tool_schemas()

    async def prepare_messages(
        self,
        latest_text: str,
        transcript: str,
        message_type: str,
        entries: Sequence[EntryView],
    ) -> List[Dict[str, str]]:
        views = [RecordView.from_record(r) for r in self.store.all()]
        candidate_set = await select_candidates(
            views, latest_text, message_type, entries, self.params, self.embedder, self.index
        )
        if self.index.dirty:
            try:
                self.index.save()
            except Exception as exc:  # pragma: no cover - defensive
                logger.warning(f"Failed to save embedding index: {exc}")

        by_id = {v.agent_id: v for v in views}
        decision = await self.scorer.decide(
            ScoringInput(
                message_text=latest_text,
                message_type=message_type,
                entries=tuple(entries),
                candidates=tuple(by_id[i] for i in candidate_set.shown),
                candidate_set=candidate_set,
            )
        )
        shown = [i for i in (decision.candidates or candidate_set.shown) if i in by_id]
        self.last_candidate_set = candidate_set
        self._log_candidates(candidate_set, shown, by_id, len(views))

        rendered = "\n".join(render_agent_entry(by_id[i], self.params.render_recent) for i in shown)
        return prepare_records_messages(
            latest_text, transcript, message_type, rendered or None, len(shown), len(views)
        )

    def handle_tool_call(self, name: str, arguments: Any) -> ToolResult:
        return handle_records_tool_call(name, arguments)

    def _log_candidates(
        self,
        candidate_set: CandidateSet,
        shown: List[str],
        by_id: Dict[str, RecordView],
        total: int,
    ) -> None:
        global EMBEDDING_FAILURES
        if candidate_set.error:
            EMBEDDING_FAILURES += 1
            logger.warning(
                f"Embedding failed, using lexical retrieval for this turn "
                f"(failures={EMBEDDING_FAILURES}): {candidate_set.error}"
            )
        names = ", ".join(f"{i} ({by_id[i].name})" for i in shown) or "none"
        logger.info(
            f"Routing candidates: mode={candidate_set.mode} shown={len(shown)}/{total} "
            f"full_roster_max={self.params.full_roster_max} k={self.params.k} "
            f"pinned={candidate_set.pinned} embed_calls={candidate_set.embed_calls} agents=[{names}]"
        )
        logger.debug(
            "Routing candidate scores",
            extra={"queries": candidate_set.queries, "scores": {i: candidate_set.scores.get(i) for i in candidate_set.ranked}},
        )


def get_routing_strategy() -> RoutingStrategy:
    """The strategy for the configured routing mode (read now, not at import)."""
    settings = get_settings()
    if settings.routing_mode == "records":
        return RecordsRouting(settings)
    return LegacyRouting()


def describe_routing(settings: Settings) -> str:
    """The startup log line naming the routing mode in effect."""
    if settings.routing_mode != "records":
        return "Routing mode: legacy"
    params = retrieval_params(settings)
    return (
        f"Routing mode: records (embeddings {settings.embedding_model}@{settings.embedding_dimensions}, "
        f"K={params.k}, full_roster_max={params.full_roster_max})"
    )


def initialize_routing() -> None:
    """App startup: log the mode, and in records mode import legacy roster names as records."""
    settings = get_settings()
    logger.info(describe_routing(settings))
    if settings.routing_mode == "records":
        reconcile_from_roster(get_agent_records(), get_agent_roster(), get_execution_agent_logs())


__all__ = [
    "LegacyRouting",
    "RecordsRouting",
    "RoutingStrategy",
    "describe_routing",
    "get_embedding_index",
    "get_routing_strategy",
    "initialize_routing",
    "retrieval_params",
]
