"""Conversation and roster state for routing turns, rendered the way production renders it.

The harness keeps the interaction agent's conversation in memory instead of the
real conversation log, and renders it with the production ``WorkingMemoryLog``
(design: Transcript rendering). Sequence turns update the state either with the
method's own choices (carried forward) or with the gold choices (corrected each
turn), as described under "State update between sequence turns".
"""

from __future__ import annotations

import copy
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Iterable, Optional

from server.agents.execution_agent.batch_manager import ExecutionBatchManager
from server.agents.execution_agent.runtime import ExecutionResult
from server.config import get_settings
from server.services.conversation.summarization.prompt_builder import build_summarization_prompt
from server.services.conversation.summarization.state import LogEntry, SummaryState
from server.services.conversation.summarization.working_memory_log import WorkingMemoryLog

from .methods.base import AgentView, Entry, RoutingInput, WorkItem
from .util import add_seconds, days_before, seeded_uniform

ORPHAN = "orphan"
DONE_TEXT = "Done."
RESULT_PREFIXES = ("[SUCCESS] ", "[FAILED] ")

# Offsets for entries the harness appends after a turn's message (design: State update).
EFFECTS_OFFSET_S = 5
RESULT_OFFSET_S = 60
RESULT_REPLY_OFFSET_S = 65

__all__ = [
    "AgentView",
    "Entry",
    "WorkItem",
    "AgentRecord",
    "RoutingState",
    "WorkAssignment",
    "render_transcript",
    "format_batch_payload",
    "initial_state",
    "apply_turn",
    "maybe_summarize",
    "summarization_settings",
]


# ---------------------------------------------------------------------------
# Production rendering

_render_lock = threading.Lock()
_render_log: Optional[WorkingMemoryLog] = None
_render_dir: Optional[tempfile.TemporaryDirectory] = None
_batch_formatter = ExecutionBatchManager()


def _working_memory_log() -> WorkingMemoryLog:
    global _render_log, _render_dir
    with _render_lock:
        if _render_log is None:
            _render_dir = tempfile.TemporaryDirectory(prefix="agent-overload-render-")
            _render_log = WorkingMemoryLog(Path(_render_dir.name) / "working_memory.log")
        return _render_log


def render_transcript(summary_text: str, entries: Iterable[Entry], last_index: int = -1) -> str:
    """Render like ``InteractionAgentRuntime._load_conversation_transcript`` with summarization on."""
    unsummarized = [
        LogEntry(tag=e.tag, payload=e.payload, index=last_index + 1 + i, timestamp=e.timestamp or None)
        for i, e in enumerate(entries)
    ]
    state = SummaryState(
        summary_text=summary_text,
        last_index=last_index,
        updated_at=None,
        unsummarized_entries=unsummarized,
    )
    return _working_memory_log().render_transcript(state)


def format_batch_payload(results: Iterable[tuple[str, str]]) -> str:
    """``[SUCCESS] <agent_name>: <text>`` lines via the real ``_format_batch_payload``."""
    payload = [
        ExecutionResult(agent_name=name, success=True, response=text) for name, text in results
    ]
    return _batch_formatter._format_batch_payload(payload)


def summarization_settings() -> tuple[int, int]:
    settings = get_settings()
    return settings.conversation_summary_threshold, max(settings.conversation_summary_tail_size, 0)


# ---------------------------------------------------------------------------
# State


@dataclass
class AgentRecord:
    """Harness-side agent: what a method sees (``view()``) plus the hidden thread mapping."""

    agent_id: str
    name: str
    thread_id: str  # agent_thread: the agent's creation thread
    created_at: str
    last_active: str
    seeded: bool
    work_log: list[WorkItem] = field(default_factory=list)
    map_order: int = 0  # order in which the agent was mapped to its thread
    extra: dict = field(default_factory=dict)  # what the creating method stored (Delegation.extra)

    def view(self) -> AgentView:
        return AgentView(
            agent_id=self.agent_id,
            name=self.name,
            work_log=tuple(self.work_log),
            created_at=self.created_at,
            last_active=self.last_active,
            extra=tuple(sorted(self.extra.items())),
        )


@dataclass
class RoutingState:
    """In-memory conversation and roster. ``entries`` are the unsummarized entries."""

    roster: list[AgentRecord]
    entries: list[Entry]
    summary_text: str = ""
    base_index: int = 0  # global index of entries[0]
    agent_context: dict[str, set[str]] = field(default_factory=dict)
    created_count: int = 0
    _map_counter: int = 0

    @property
    def last_index(self) -> int:
        return self.base_index - 1

    # -- lookups ----------------------------------------------------------

    def agent_thread(self) -> dict[str, str]:
        return {a.agent_id: a.thread_id for a in self.roster}

    def agent_names(self) -> dict[str, str]:
        return {a.agent_id: a.name for a in self.roster}

    def by_id(self, agent_id: str) -> AgentRecord:
        for agent in self.roster:
            if agent.agent_id == agent_id:
                return agent
        raise KeyError(agent_id)

    def resolve_name(self, name: str) -> Optional[str]:
        """Exact-string match, as ``send_message_to_agent`` does."""
        for agent in self.roster:
            if agent.name == name:
                return agent.agent_id
        return None

    def canonical_agent(self, thread_id: str) -> Optional[str]:
        """The first agent mapped to the thread, seeded or created."""
        mapped = [a for a in self.roster if a.thread_id == thread_id]
        if not mapped:
            return None
        return min(mapped, key=lambda a: a.map_order).agent_id

    def canonical_map(self) -> dict[str, str]:
        result: dict[str, str] = {}
        for agent in sorted(self.roster, key=lambda a: a.map_order):
            result.setdefault(agent.thread_id, agent.agent_id)
        return result

    def prev_thread(self) -> Optional[str]:
        """Thread of the agent in the most recent result line (first line of the latest batch)."""
        names = sorted({a.name for a in self.roster}, key=len, reverse=True)
        for entry in reversed(self.entries):
            if entry.tag != "agent_message" or not entry.payload.startswith(RESULT_PREFIXES):
                continue
            first_line = entry.payload.split("\n", 1)[0]
            for prefix in RESULT_PREFIXES:
                if first_line.startswith(prefix):
                    rest = first_line[len(prefix):]
                    break
            for name in names:  # longest first, since names may contain ": "
                if rest.startswith(f"{name}: ") or rest == f"{name}:":
                    agent_id = self.resolve_name(name)
                    return self.by_id(agent_id).thread_id if agent_id else None
            return None
        return None

    # -- rendering ---------------------------------------------------------

    def transcript(self) -> str:
        return render_transcript(self.summary_text, self.entries, self.last_index)

    def routing_input(self, message_text: str, message_type: str, now: str = "") -> RoutingInput:
        return RoutingInput(
            roster=tuple(a.view() for a in self.roster),
            summary_text=self.summary_text,
            entries=tuple(self.entries),
            message_text=message_text,
            message_type=message_type,
            now=now,
        )

    # -- mutation ----------------------------------------------------------

    def clone(self) -> "RoutingState":
        return copy.deepcopy(self)

    def add_entry(self, tag: str, timestamp: str, payload: str) -> None:
        self.entries.append(Entry(tag=tag, timestamp=timestamp, payload=payload))

    def next_map_order(self) -> int:
        self._map_counter += 1
        return self._map_counter

    def add_agent(self, record: AgentRecord) -> AgentRecord:
        record.map_order = self.next_map_order()
        self.roster.append(record)  # appended at the end, like roster.add_agent
        self.agent_context.setdefault(record.agent_id, set()).add(record.thread_id)
        return record


def _created_offset_days(key: str) -> float:
    return seeded_uniform(key, 0.0, 30.0)


def initial_state(
    *,
    roster_ids: list[str],
    agents: dict[str, dict],
    agent_times: dict[str, dict],
    filler_age_days: dict[str, float],
    now: str,
    history: dict,
) -> RoutingState:
    """Build the starting state for a case at one roster size.

    ``agents`` maps agent_id to its ``agents.<split>.jsonl`` row. ``agent_times``
    is the case's frozen ``agent_times`` for required agents; filler times come
    from ``filler_age_days`` relative to ``now``.
    """
    roster: list[AgentRecord] = []
    context: dict[str, set[str]] = {}
    for order, agent_id in enumerate(roster_ids, start=1):
        row = agents[agent_id]
        if agent_id in agent_times:
            last_active = agent_times[agent_id]["last_active"]
            created_at = agent_times[agent_id]["created_at"]
        elif agent_id in filler_age_days:
            last_active = days_before(now, filler_age_days[agent_id])
            created_at = days_before(last_active, _created_offset_days(f"{agent_id}|created"))
        else:
            raise KeyError(f"no agent times for {agent_id}")
        work_log = [WorkItem(w["instructions"], w["result"]) for w in row.get("work_log", [])]
        roster.append(
            AgentRecord(
                agent_id=agent_id,
                name=row["name"],
                thread_id=row["thread_id"],
                created_at=created_at,
                last_active=last_active,
                seeded=True,
                work_log=work_log,
                map_order=order,
            )
        )
        context[agent_id] = {row["thread_id"]}

    last_index = int(history.get("last_index", -1))
    entries = [Entry(e["tag"], e["timestamp"], e["payload"]) for e in history.get("entries", [])]
    state = RoutingState(
        roster=roster,
        entries=entries,
        summary_text=history.get("summary_text", "") or "",
        base_index=last_index + 1,
        agent_context=context,
    )
    state._map_counter = len(roster)
    return state


# ---------------------------------------------------------------------------
# Turn updates


@dataclass
class WorkAssignment:
    """One distinct agent that received work on a turn, in result-line order."""

    agent_key: str  # existing agent_id, or "new:<name>"
    agent_name: str  # the name used in the result line
    instructions: str
    result_text: str
    new_agent_id: Optional[str] = None  # id for a created agent (a-run-<n> or the frozen gold id)
    extra: dict = field(default_factory=dict)  # stored on a created agent (carried mode)


def apply_turn(
    state: RoutingState,
    *,
    message_tag: str,
    message_text: str,
    timestamp: str,
    effects: list[tuple[str, str]],
    work: list[WorkAssignment],
    primary_thread: Optional[str],
    result_reply: Optional[str],
) -> None:
    """Append one turn to the state (steps 1 to 5 of the state update; summarization is separate).

    ``effects`` are (tag, payload) pairs appended at +5 s, +6 s, ... ``work`` is in
    result-line order (the primary first). New agents are appended to the roster and
    mapped to ``primary_thread``, or to ``orphan`` when it is ``None``.
    """
    state.add_entry(message_tag, timestamp, message_text)
    for offset, (tag, payload) in enumerate(effects):
        state.add_entry(tag, add_seconds(timestamp, EFFECTS_OFFSET_S + offset), payload)

    if not work:
        return

    thread_for_new = primary_thread if primary_thread is not None else ORPHAN
    lines: list[tuple[str, str]] = []
    for item in work:
        if item.new_agent_id is not None:
            record = state.add_agent(
                AgentRecord(
                    agent_id=item.new_agent_id,
                    name=item.agent_name,
                    thread_id=thread_for_new,
                    created_at=timestamp,
                    last_active=timestamp,
                    seeded=False,
                    extra=dict(item.extra),
                )
            )
        else:
            record = state.by_id(item.agent_key)
        record.work_log.append(WorkItem(item.instructions, item.result_text))
        record.last_active = timestamp
        if primary_thread is not None:
            state.agent_context.setdefault(record.agent_id, set()).add(primary_thread)
        lines.append((item.agent_name, item.result_text))

    state.add_entry("agent_message", add_seconds(timestamp, RESULT_OFFSET_S), format_batch_payload(lines))
    if result_reply is not None:
        state.add_entry("poke_reply", add_seconds(timestamp, RESULT_REPLY_OFFSET_S), result_reply)


def next_run_agent_id(state: RoutingState) -> str:
    state.created_count += 1
    return f"a-run-{state.created_count}"


# ---------------------------------------------------------------------------
# Summarization

SummarizeCall = Callable[[str, list[dict]], Awaitable[str]]


def needs_summary(state: RoutingState) -> bool:
    threshold, tail = summarization_settings()
    if threshold <= 0:
        return False
    return len(state.entries) >= threshold + tail


async def maybe_summarize(state: RoutingState, call: SummarizeCall) -> bool:
    """Apply ``summarize_conversation``'s rule once. Returns True when a summary was written.

    ``call(system_prompt, messages)`` returns the summarizer's stripped text. An
    empty text leaves the state unchanged, as production does when the summarizer
    returns no content.
    """
    if not needs_summary(state):
        return False
    threshold, _ = summarization_settings()
    batch = [
        LogEntry(tag=e.tag, payload=e.payload, index=state.base_index + i, timestamp=e.timestamp or None)
        for i, e in enumerate(state.entries[:threshold])
    ]
    prompt = build_summarization_prompt(state.summary_text, batch)
    text = (await call(prompt.system_prompt, prompt.messages) or "").strip()
    if not text:
        return False
    state.summary_text = text
    state.entries = state.entries[threshold:]
    state.base_index += threshold
    return True
