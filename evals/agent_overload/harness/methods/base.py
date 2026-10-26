"""The routing-method interface: the only part that changes between experiments."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..llm import CallRecord


@dataclass(frozen=True)
class WorkItem:
    instructions: str
    result: str


@dataclass(frozen=True)
class AgentView:
    agent_id: str  # stable harness id; methods that route by id use it
    name: str
    work_log: tuple[WorkItem, ...]  # what this agent has done; names_only ignores it
    created_at: str  # "YYYY-MM-DD HH:MM:SS"; names_only ignores it
    last_active: str  # last delegation to this agent; names_only ignores it
    # deliberately no thread_id


@dataclass(frozen=True)
class Entry:
    tag: str  # user_message | agent_message | poke_reply | wait
    timestamp: str  # "YYYY-MM-DD HH:MM:SS"
    payload: str


@dataclass(frozen=True)
class RoutingInput:
    roster: tuple[AgentView, ...]  # in roster order
    summary_text: str  # "" when there is no summary
    entries: tuple[Entry, ...]  # unsummarized entries, oldest first
    message_text: str
    message_type: str  # "user" | "agent"


@dataclass
class Delegation:
    agent_key: str  # existing agent_id, or "new:<exact name>"
    agent_name: str  # the name the method used
    instructions: str
    iteration: int  # loop iteration it came from (0-based)
    order: int  # order across the whole turn


@dataclass
class RoutingOutput:
    delegations: list[Delegation]
    history_effects: list[Entry]  # poke_reply / wait entries the turn produced, in order
    invalid_calls: list[dict]  # {"tool", "raw_arguments", "error"}
    llm_calls: list["CallRecord"]  # every model call the method made
    diagnostics: dict = field(default_factory=dict)  # {"candidates": [...]}, {"excluded": [...]}
    loop_limit_hit: bool = False


NEW_PREFIX = "new:"


def new_agent_key(name: str) -> str:
    return f"{NEW_PREFIX}{name}"


def is_new_key(agent_key: str) -> bool:
    return agent_key.startswith(NEW_PREFIX)


class RoutingMethod(Protocol):
    name: str
    version: str

    def describe(self) -> dict: ...  # params, prompt hashes; stored in config

    async def prepare(self, agents: list[AgentView]) -> None: ...  # build records/indices; may cache

    async def route(self, inp: RoutingInput) -> RoutingOutput: ...
