"""Method ``records_retrieval`` version 1: agent records, ID routing and bounded retrieval.

Spec: docs/agent-overload-records-retrieval-spec.md, "Harness integration". Production code
does every step; the method only adapts the harness's views to it:

- Each ``AgentView`` becomes a production ``RecordView``. Its purpose is the one
  ``create_agent`` wrote (``AgentView.extra``), else the backfilled purpose
  (``seed_purposes: "backfill"``), else "". Recent work is the last 3 work items, cut
  like production cuts them.
- Candidates come from production ``select_candidates``, with an embedder over
  ``ModelClient.embed`` and an in-memory index pre-filled in ``prepare()``.
- The scorer is production's pass-through ``InteractionAgentScorer`` (the only v1 scorer).
- The prompt is the records system prompt, the records tool schemas and production's
  ``render_agent_entry`` and ``prepare_records_messages``.
- The real ``_run_interaction_loop`` runs with stubs that return the same payloads as
  ``server/agents/interaction_agent/tools_records.py``.

Purposes and record vectors are cached under ``evals/agent_overload/cache/records_retrieval/1/``
(ignored by the dirty-tree check), so reruns don't pay for them again. Fake-model runs use
no cache.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import math
from pathlib import Path
from typing import Any, Optional

from server.agents.interaction_agent.records_prompt import (
    RECORDS_PROMPT_PATH,
    build_records_system_prompt,
    prepare_records_messages,
)
from server.agents.interaction_agent.runtime import InteractionAgentRuntime, _ToolCall
from server.agents.interaction_agent.tools import ToolResult
from server.agents.interaction_agent.tools_records import AGENT_NAME_MAX_CHARS, RECORDS_TOOL_SCHEMAS
from server.services.agents.purpose import (
    PURPOSE_PROMPT_SHA256,
    clean_purpose,
    purpose_cache_key,
    purpose_request,
)
from server.services.agents.records import (
    INSTRUCTIONS_MAX_CHARS,
    PURPOSE_MAX_CHARS,
    RECENT_WORK_MAX,
    RESULT_MAX_CHARS,
    WorkSnippet,
    truncate_text,
)
from server.services.agents.text import render_agent_entry, retrieval_text
from server.services.execution.log_store import _slugify
from server.services.routing import (
    CandidateSet,
    EmbeddingIndex,
    EntryView,
    InteractionAgentScorer,
    RecordView,
    RetrievalParams,
    ScoringInput,
    select_candidates,
)
from server.services.routing.embeddings import EMBED_BATCH_SIZE, content_key, text_sha256

from ..llm import ModelClient, SpendCapReached, message_content
from ..spend import PlannedCalls
from ..state import render_transcript
from ..util import EVAL_ROOT, REPO_ROOT, append_jsonl, call_seed, read_jsonl, sha256_file, sha256_hex
from .base import AgentView, Delegation, Entry, RoutingInput, RoutingOutput, new_agent_key
from .names_only import LOOP_LIMIT_MESSAGE, HarnessInteractionRuntime, ToolStubs, TurnRecorder

CACHE_DIR = EVAL_ROOT / "cache" / "records_retrieval" / "1"
PURPOSES_FILE = "purposes.jsonl"
EMBEDDINGS_FILE = "embeddings.jsonl"

SEED_PURPOSES = ("backfill", "none")
SCORERS = {"interaction_agent": InteractionAgentScorer}
DEFAULT_EMBEDDING = {"model": "openai/text-embedding-3-small", "dimensions": 512}
# OpenRouter's route for embeddings (spec decision 6); OpenAI direct ignores it.
EMBEDDING_PROVIDER = {"order": ["openai"], "allow_fallbacks": False}
RETRIEVAL_KEYS = tuple(f.name for f in dataclasses.fields(RetrievalParams))
METHOD_KEYS = ("seed_purposes", "embedding", "scorer")

# Dry-run estimates for prepare(): tokens per call (guesses; output includes reasoning).
BACKFILL_INPUT_TOKENS = 150
BACKFILL_OUTPUT_TOKENS = 400
RECORD_TEXT_EXTRA_TOKENS = 30  # a backfilled purpose, not known before the call


class MethodConfigError(ValueError):
    pass


@dataclasses.dataclass(frozen=True)
class MethodParams:
    retrieval: RetrievalParams
    seed_purposes: str
    embedding_model: str
    embedding_dimensions: int
    scorer: str

    @classmethod
    def parse(cls, params: Optional[dict]) -> "MethodParams":
        params = dict(params or {})
        unknown = sorted(set(params) - set(RETRIEVAL_KEYS) - set(METHOD_KEYS))
        if unknown:
            raise MethodConfigError(f"records_retrieval: unknown params {unknown}")
        retrieval = RetrievalParams(**{k: params[k] for k in RETRIEVAL_KEYS if k in params})
        seed = params.get("seed_purposes", "backfill")
        if seed not in SEED_PURPOSES:
            raise MethodConfigError(f"records_retrieval: seed_purposes must be one of {SEED_PURPOSES}, got {seed!r}")
        embedding = {**DEFAULT_EMBEDDING, **(params.get("embedding") or {})}
        scorer = (params.get("scorer") or {}).get("name", "interaction_agent")
        if scorer not in SCORERS:
            raise MethodConfigError(f"records_retrieval v1 has only the scorers {sorted(SCORERS)}, got {scorer!r}")
        return cls(retrieval, seed, str(embedding["model"]), int(embedding["dimensions"]), scorer)

    def to_dict(self) -> dict:
        return {
            **dataclasses.asdict(self.retrieval),
            "seed_purposes": self.seed_purposes,
            "embedding": {"model": self.embedding_model, "dimensions": self.embedding_dimensions},
            "scorer": {"name": self.scorer},
        }


def record_view(view: AgentView, backfilled: dict[str, str]) -> RecordView:
    """A production RecordView for a harness AgentView."""
    purpose = dict(view.extra).get("purpose") or backfilled.get(view.agent_id, "")
    work = [
        WorkSnippet(
            instructions=truncate_text(w.instructions, INSTRUCTIONS_MAX_CHARS),
            result=truncate_text(w.result, RESULT_MAX_CHARS) or "(no response)",
            at="",
        )
        for w in view.work_log[-RECENT_WORK_MAX:]
    ]
    return RecordView(
        agent_id=view.agent_id,
        name=view.name,
        purpose=purpose,
        recent_work=tuple(work),
        last_active=view.last_active,
        task_count=len(view.work_log),
    )


def _first_task(view: AgentView) -> str:
    return view.work_log[0].instructions if view.work_log else ""


class MethodCache:
    """purposes.jsonl and embeddings.jsonl under ``cache_dir`` (in memory only when it is None)."""

    def __init__(self, cache_dir: Optional[Path]):
        self.dir = cache_dir
        self.purposes: dict[tuple[str, str, str], str] = {}  # (agent_id, key, model) -> purpose
        self.vectors: dict[str, dict] = {}  # content_key -> index entry
        for row in self._rows(PURPOSES_FILE):
            self.purposes[(row["agent_id"], row["key"], row["model"])] = row["purpose"]
        for row in self._rows(EMBEDDINGS_FILE):
            self.vectors[row["key"]] = {k: row[k] for k in ("text_sha256", "model", "dimensions", "vector")}

    def _path(self, filename: str) -> Optional[Path]:
        return self.dir / filename if self.dir is not None else None

    def _rows(self, filename: str) -> list[dict]:
        path = self._path(filename)
        return read_jsonl(path) if path is not None and path.exists() else []

    def purpose(self, agent: AgentView, model: str) -> Optional[str]:
        return self.purposes.get((agent.agent_id, purpose_cache_key(agent.name, _first_task(agent)), model))

    def add_purpose(self, agent: AgentView, model: str, purpose: str) -> None:
        key = purpose_cache_key(agent.name, _first_task(agent))
        self.purposes[(agent.agent_id, key, model)] = purpose
        self._append(PURPOSES_FILE, {"agent_id": agent.agent_id, "key": key, "model": model, "purpose": purpose})

    def add_vector(self, text: str, model: str, dimensions: int, vector: list[float]) -> None:
        key = content_key(text, model, dimensions)
        entry = {"text_sha256": text_sha256(text), "model": model, "dimensions": dimensions, "vector": vector}
        self.vectors[key] = entry
        self._append(EMBEDDINGS_FILE, {"key": key, **entry})

    def _append(self, filename: str, row: dict) -> None:
        path = self._path(filename)
        if path is not None:
            append_jsonl(path, row)

    def describe(self) -> dict:
        def digest(filename: str) -> Optional[str]:
            path = self._path(filename)
            return sha256_file(path) if path is not None and path.exists() else None

        location = None
        if self.dir is not None:
            location = self.dir.relative_to(REPO_ROOT).as_posix() if self.dir.is_relative_to(REPO_ROOT) else str(self.dir)
        return {
            "dir": location,
            "purposes_sha256": digest(PURPOSES_FILE),
            "embeddings_sha256": digest(EMBEDDINGS_FILE),
        }


class _TurnEmbedder:
    """Production's Embedder over ModelClient.embed; keeps the calls for the turn's records."""

    def __init__(self, client: ModelClient, model: str, dimensions: int):
        self.client = client
        self.model = model
        self.dimensions = dimensions
        self.calls: list = []
        self.cap_reached = False

    async def embed(self, texts: list[str], purpose: str) -> list[list[float]]:
        try:
            vectors, record = await self.client.embed(
                purpose="embed_query",
                model=self.model,
                inputs=texts,
                dimensions=self.dimensions,
                provider=EMBEDDING_PROVIDER,
            )
        except SpendCapReached:
            # select_candidates turns embedder errors into the lexical fallback; the cap must stop the run.
            self.cap_reached = True
            raise
        self.calls.append(record)
        return vectors


# ---------------------------------------------------------------------------
# Tool stubs


class RecordsTurnRecorder(TurnRecorder):
    def __init__(self, views: list[RecordView]):
        super().__init__(roster=())
        self.views = views
        self.created_ids: dict[str, str] = {}  # synthetic id of an agent created this turn -> name
        self.resolved_by_name = 0
        self.rejected_creates: list[dict] = []
        self.purpose_fallbacks = 0
        self.failure_recorded = False  # a stub already recorded (or excused) a failed call


def created_agent_id(name: str) -> str:
    """Stand-in for production's random id: deterministic, so seeds and results don't depend on it."""
    return "ag_" + sha256_hex(f"created|{name}")[:8]


class RecordsToolStubs(ToolStubs):
    """Same signatures and ToolResult payloads as ``tools_records.py`` (and the shared tools)."""

    r: RecordsTurnRecorder

    def _agents(self) -> list[tuple[str, str, str]]:
        """(id shown to the model, name, agent_key) for listed agents, then agents created this turn."""
        listed = [(v.agent_id, v.name, v.agent_id) for v in self.r.views]
        created = [(agent_id, name, new_agent_key(name)) for agent_id, name in self.r.created_ids.items()]
        return listed + created

    def _resolve(self, agent_id: Any) -> Optional[tuple[str, str, str]]:
        """Like production: the id, then an exact name, then the slug (logged as resolved by name)."""
        agents = self._agents()
        for entry in agents:
            if entry[0] == agent_id:
                return entry
        candidate = str(agent_id or "").strip()
        if not candidate:
            return None
        match = next((e for e in agents if e[1] == candidate), None)
        if match is None:
            slug = _slugify(candidate)
            match = next((e for e in agents if _slugify(e[1]) == slug), None)
        if match is not None:
            self.r.resolved_by_name += 1
        return match

    def _delegate(self, agent_key: str, name: str, instructions: Any, extra: Optional[dict] = None) -> None:
        self.r.delegations.append(
            Delegation(
                agent_key=agent_key,
                agent_name=name,
                instructions=str(instructions),
                iteration=self.r.iteration,
                order=len(self.r.delegations),
                extra=dict(extra or {}),
            )
        )

    def send_message_to_agent(self, agent_id: str, instructions: str) -> ToolResult:
        match = self._resolve(agent_id)
        if match is None:
            self.r.invalid_calls.append(
                {"tool": "send_message_to_agent", "raw_arguments": self._raw(), "error": "unknown agent_id"}
            )
            self.r.failure_recorded = True
            return ToolResult(
                success=False,
                payload={
                    "error": f"Unknown agent_id '{agent_id}'. Use an id from <active_agents>, or create_agent for new work."
                },
            )
        shown_id, name, agent_key = match
        self._delegate(agent_key, name, instructions)
        return ToolResult(
            success=True,
            payload={"status": "submitted", "agent_id": shown_id, "agent_name": name, "new_agent_created": False},
        )

    def create_agent(self, name: str, purpose: str, instructions: str) -> ToolResult:
        name = (name or "").strip()[:AGENT_NAME_MAX_CHARS].strip()
        purpose = (purpose or "").strip()
        if not name:
            return ToolResult(success=False, payload={"error": "Agent name is required."})
        if not purpose:
            purpose = truncate_text(instructions, PURPOSE_MAX_CHARS)
            self.r.purpose_fallbacks += 1
        slug = _slugify(name)
        existing = next((e for e in self._agents() if _slugify(e[1]) == slug), None)
        if existing is not None:
            existing_id, existing_name, _ = existing
            self.r.rejected_creates.append({"name": name, "existing_agent_id": existing_id})
            self.r.failure_recorded = True  # a recoverable refusal, not an invalid call
            return ToolResult(
                success=False,
                payload={
                    "error": (
                        f"An agent named '{existing_name}' (id {existing_id}) already exists. "
                        "Use send_message_to_agent with that id, or choose a different name."
                    ),
                    "existing_agent_id": existing_id,
                },
            )
        agent_id = created_agent_id(name)
        self.r.created_ids[agent_id] = name
        self._delegate(new_agent_key(name), name, instructions, {"purpose": truncate_text(purpose, PURPOSE_MAX_CHARS)})
        return ToolResult(
            success=True,
            payload={"status": "submitted", "agent_id": agent_id, "agent_name": name, "new_agent_created": True},
        )

    def handle_tool_call(self, name: str, arguments: Any) -> ToolResult:
        """Mirror of ``tools_records.handle_records_tool_call`` dispatching to the stubs."""
        try:
            if isinstance(arguments, str):
                args = json.loads(arguments) if arguments.strip() else {}
            elif isinstance(arguments, dict):
                args = arguments
            else:
                return ToolResult(success=False, payload={"error": "Invalid arguments format"})

            if name == "send_message_to_agent":
                return self.send_message_to_agent(**args)
            if name == "create_agent":
                return self.create_agent(**args)
            if name == "send_message_to_user":
                return self.send_message_to_user(**args)
            if name == "send_draft":
                return self.send_draft(**args)
            if name == "wait":
                return self.wait(**args)

            return ToolResult(success=False, payload={"error": f"Unknown tool: {name}"})
        except json.JSONDecodeError:
            return ToolResult(success=False, payload={"error": "Invalid JSON"})
        except TypeError as exc:
            return ToolResult(success=False, payload={"error": f"Missing required arguments: {exc}"})
        except Exception:  # as in production
            return ToolResult(success=False, payload={"error": "Failed to execute"})


# TypeError messages name the function; they must read like the module-level production tools.
for _stub_name in ("send_message_to_agent", "create_agent"):
    getattr(RecordsToolStubs, _stub_name).__qualname__ = _stub_name


class RecordsHarnessRuntime(HarnessInteractionRuntime):
    """names_only's harness runtime with the records tools and stubs."""

    def __init__(self, *, recorder: RecordsTurnRecorder, **kwargs: Any) -> None:
        super().__init__(recorder=recorder, **kwargs)
        self.tool_schemas = RECORDS_TOOL_SCHEMAS
        self._stubs = RecordsToolStubs(recorder)

    def _execute_tool(self, tool_call: _ToolCall) -> ToolResult:
        if "__invalid_arguments__" in tool_call.arguments:
            return super()._execute_tool(tool_call)
        self._recorder.failure_recorded = False
        self._stubs.current_call = tool_call
        result = self._stubs.handle_tool_call(tool_call.name, tool_call.arguments)
        if not result.success and not self._recorder.failure_recorded:
            self._recorder.invalid_calls.append(
                {
                    "tool": tool_call.name,
                    "raw_arguments": self._recorder.raw_arguments.get(tool_call.identifier or tool_call.name),
                    "error": (result.payload or {}).get("error"),
                }
            )
        return result


# ---------------------------------------------------------------------------
# Method


class RecordsRetrievalMethod:
    name = "records_retrieval"
    version = "1"

    def __init__(
        self,
        client: ModelClient,
        model: str,
        provider: Optional[dict] = None,
        extra_params: Optional[dict] = None,
        params: Optional[dict] = None,
        summarizer_model: Optional[str] = None,
        cache_dir: Optional[Path] = CACHE_DIR,
        purpose: str = "routing",
    ):
        self.client = client
        self.model = model
        self.provider = provider
        self.extra_params = dict(extra_params or {})
        self.config = MethodParams.parse(params)
        self.params = self.config.retrieval
        self.summarizer_model = summarizer_model or model
        self.cache_dir = cache_dir
        self.purpose = purpose
        self.scorer = SCORERS[self.config.scorer]()
        self.cache = MethodCache(cache_dir)
        self.index = EmbeddingIndex(key_by_content=True)
        self.index.prefill(self.cache.vectors)
        self.purposes: dict[str, str] = {}  # agent_id -> backfilled purpose
        self.prepare_stats = {"purpose_calls": 0, "embed_calls": 0, "empty_purposes": 0}

    # -- RoutingMethod --------------------------------------------------------

    def describe(self) -> dict:
        return {
            "name": self.name,
            "version": self.version,
            "params": self.config.to_dict(),
            "system_prompt_sha256": sha256_file(RECORDS_PROMPT_PATH),
            "tool_schemas_sha256": sha256_hex(json.dumps(RECORDS_TOOL_SCHEMAS, sort_keys=True)),
            "purpose_prompt_sha256": PURPOSE_PROMPT_SHA256,
            "embedding": {"model": self.config.embedding_model, "dimensions": self.config.embedding_dimensions},
            "scorer": {"name": self.scorer.name, "version": self.scorer.version},
            "summarizer_model": self.summarizer_model,
            "method_source_sha256": sha256_file(Path(__file__)),
            "max_tool_iterations": InteractionAgentRuntime.MAX_TOOL_ITERATIONS,
            "cache": self.cache.describe(),
            "prepare": dict(self.prepare_stats),
        }

    async def prepare(self, agents: list[AgentView]) -> None:
        """Backfill purposes (if configured), then embed every record's retrieval text."""
        if self.config.seed_purposes == "backfill":
            await asyncio.gather(*(self._backfill(agent) for agent in agents))
        texts = list(dict.fromkeys(retrieval_text(record_view(a, self.purposes)) for a in agents))
        model, dims = self.config.embedding_model, self.config.embedding_dimensions
        missing = [t for t in texts if self.index.lookup("", t, model, dims) is None]
        for start in range(0, len(missing), EMBED_BATCH_SIZE):
            batch = missing[start:start + EMBED_BATCH_SIZE]
            vectors, _record = await self.client.embed(
                purpose="embed_records", model=model, inputs=batch, dimensions=dims, provider=EMBEDDING_PROVIDER
            )
            self.prepare_stats["embed_calls"] += 1
            for text, vector in zip(batch, vectors):
                self.cache.add_vector(text, model, dims, self.index.put("", text, model, dims, vector))

    async def _backfill(self, agent: AgentView) -> None:
        cached = self.cache.purpose(agent, self.summarizer_model)
        if cached is not None:
            self.purposes[agent.agent_id] = cached
            return
        system, messages = purpose_request(agent.name, _first_task(agent))
        response, _record = await self.client.chat(
            purpose="purpose_backfill",
            model=self.summarizer_model,
            messages=messages,
            system=system,
            provider=self.provider,
            seed=call_seed("purpose_backfill", agent.agent_id),
        )
        self.prepare_stats["purpose_calls"] += 1
        purpose = clean_purpose(message_content(response))
        if not purpose:
            self.prepare_stats["empty_purposes"] += 1
        self.purposes[agent.agent_id] = purpose
        self.cache.add_purpose(agent, self.summarizer_model, purpose)

    def views(self, inp: RoutingInput) -> list[RecordView]:
        return [record_view(a, self.purposes) for a in inp.roster]

    async def select(self, inp: RoutingInput, embedder: _TurnEmbedder) -> CandidateSet:
        """Production candidate selection for one turn (the retrieval probe calls this alone)."""
        entries = [EntryView(e.tag, e.payload) for e in inp.entries]
        candidate_set = await select_candidates(
            self.views(inp), inp.message_text, inp.message_type, entries, self.params, embedder, self.index
        )
        if embedder.cap_reached:
            raise SpendCapReached("spend cap reached during an embedding call")
        return candidate_set

    def turn_embedder(self) -> _TurnEmbedder:
        return _TurnEmbedder(self.client, self.config.embedding_model, self.config.embedding_dimensions)

    def probe_request(self, inp: RoutingInput) -> tuple[str, list[dict], list[dict]]:
        """The token probe's request: this method's prompt and tools with an empty roster."""
        transcript = render_transcript(inp.summary_text, inp.entries)
        messages = prepare_records_messages(inp.message_text, transcript, inp.message_type, None, 0, 0)
        return build_records_system_prompt(), messages, RECORDS_TOOL_SCHEMAS

    async def route(self, inp: RoutingInput) -> RoutingOutput:
        views = self.views(inp)
        embedder = self.turn_embedder()
        candidate_set = await self.select(inp, embedder)
        by_id = {v.agent_id: v for v in views}
        decision = await self.scorer.decide(
            ScoringInput(
                message_text=inp.message_text,
                message_type=inp.message_type,
                entries=tuple(EntryView(e.tag, e.payload) for e in inp.entries),
                candidates=tuple(by_id[i] for i in candidate_set.shown),
                candidate_set=candidate_set,
            )
        )
        shown = [i for i in (decision.candidates or candidate_set.shown) if i in by_id]
        rendered = "\n".join(render_agent_entry(by_id[i], self.params.render_recent) for i in shown)
        transcript = render_transcript(inp.summary_text, inp.entries)
        messages = prepare_records_messages(
            inp.message_text, transcript, inp.message_type, rendered or None, len(shown), len(views)
        )

        recorder = RecordsTurnRecorder(views)
        runtime = RecordsHarnessRuntime(
            client=self.client,
            model=self.model,
            provider=self.provider,
            extra_params=self.extra_params,
            recorder=recorder,
            purpose=self.purpose,
        )
        loop_limit_hit = False
        try:
            summary = await runtime._run_interaction_loop(build_records_system_prompt(), messages)
        except RuntimeError as exc:
            if str(exc) != LOOP_LIMIT_MESSAGE:
                raise
            loop_limit_hit = True
        else:
            final = runtime._finalize_response(summary)
            if final and not summary.user_messages:
                recorder.effects.append(Entry("poke_reply", "", final))

        diagnostics: dict[str, Any] = {
            "candidate_mode": candidate_set.mode,
            "excluded": list(candidate_set.excluded),
            "pinned": list(candidate_set.pinned),
            "embed_calls": candidate_set.embed_calls,
            "resolved_by_name": recorder.resolved_by_name,
            "rejected_creates": list(recorder.rejected_creates),
            "purpose_fallbacks": recorder.purpose_fallbacks,
        }
        if candidate_set.mode.startswith("retrieved"):
            # Only when retrieval ran: in "full" mode the order is just the roster order.
            diagnostics["candidates"] = list(candidate_set.ranked)
        if candidate_set.error:
            diagnostics["embed_error"] = candidate_set.error
        return RoutingOutput(
            delegations=recorder.delegations,
            history_effects=recorder.effects,
            invalid_calls=recorder.invalid_calls,
            llm_calls=list(embedder.calls) + list(runtime.calls),
            diagnostics=diagnostics,
            loop_limit_hit=loop_limit_hit,
        )


# ---------------------------------------------------------------------------
# Dry-run estimate


def prepare_plan(
    params: Optional[dict],
    agents: list[AgentView],
    summarizer_model: str,
    cache_dir: Optional[Path] = CACHE_DIR,
) -> list[PlannedCalls]:
    """What ``prepare()`` would call for these agents, given the caches (for --dry-run)."""
    config = MethodParams.parse(params)
    cache = MethodCache(cache_dir)
    model, dims = config.embedding_model, config.embedding_dimensions
    purposes: dict[str, str] = {}
    to_backfill = 0
    embed_tokens: list[float] = []
    for agent in agents:
        if config.seed_purposes == "backfill":
            cached = cache.purpose(agent, summarizer_model)
            if cached is None:
                # Its purpose, and so its retrieval text, isn't known until the call.
                to_backfill += 1
                embed_tokens.append(len(retrieval_text(record_view(agent, {}))) / 4 + RECORD_TEXT_EXTRA_TOKENS)
                continue
            purposes[agent.agent_id] = cached
        text = retrieval_text(record_view(agent, purposes))
        if content_key(text, model, dims) not in cache.vectors:
            embed_tokens.append(len(text) / 4)
    planned: list[PlannedCalls] = []
    if to_backfill:
        planned.append(
            PlannedCalls("purpose_backfill", summarizer_model, to_backfill, BACKFILL_INPUT_TOKENS, BACKFILL_OUTPUT_TOKENS, "one-off, cached")
        )
    if embed_tokens:
        calls = math.ceil(len(embed_tokens) / EMBED_BATCH_SIZE)
        planned.append(PlannedCalls("embed_records", model, calls, sum(embed_tokens) / calls, 0, "one-off, cached"))
    return planned


__all__ = [
    "CACHE_DIR",
    "MethodCache",
    "MethodConfigError",
    "MethodParams",
    "RecordsHarnessRuntime",
    "RecordsRetrievalMethod",
    "RecordsToolStubs",
    "RecordsTurnRecorder",
    "created_agent_id",
    "prepare_plan",
    "record_view",
]
