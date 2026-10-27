"""Temp-path stand-ins for the runtime's singletons, so tests never touch server/data."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

from server.agents.interaction_agent import agent as agent_module
from server.agents.interaction_agent import routing as routing_module
from server.agents.interaction_agent import runtime as runtime_module
from server.agents.interaction_agent import tools_records
from server.config import Settings
from server.services.agents.records import AgentRecordStore
from server.services.conversation.log import ConversationLog
from server.services.conversation.summarization.working_memory_log import WorkingMemoryLog
from server.services.execution.log_store import ExecutionAgentLogStore
from server.services.execution.roster import AgentRoster
from server.services.routing.embeddings import EmbeddingIndex
from server.tests.fakes import FakeEmbedder

FAKE_KEY = "sk-test-not-a-real-key"


def make_settings(**overrides: Any) -> Settings:
    values: Dict[str, Any] = {"openrouter_api_key": FAKE_KEY, "routing_mode": "legacy"}
    values.update(overrides)
    return Settings(**values)


def assistant_reply(content: str = "", tool_calls: Optional[List[dict]] = None) -> dict:
    message: Dict[str, Any] = {"role": "assistant", "content": content}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return {"choices": [{"message": message}]}


def tool_call(call_id: str, name: str, arguments: dict) -> dict:
    import json

    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": json.dumps(arguments)}}


class TempServerState:
    """Temp conversation log, working memory, roster, execution logs, records and index,
    patched in wherever the interaction runtime and routing look them up."""

    def __init__(self, settings: Settings):
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name)
        (base / "conversation").mkdir()
        (base / "execution_agents").mkdir()
        self.base = base
        self.settings = settings

        self.working_memory = WorkingMemoryLog(base / "conversation" / "poke_working_memory.log")
        self.conversation = ConversationLog(base / "conversation" / "poke_conversation.log")
        self.conversation._working_memory_log = self.working_memory
        self.conversation._notify_summarization = lambda: None  # no background summarizer

        self.roster = AgentRoster(base / "execution_agents" / "roster.json")
        self.logs = ExecutionAgentLogStore(base / "execution_agents")
        self.records = AgentRecordStore(base / "execution_agents" / "agents.json")
        self.index = EmbeddingIndex(base / "execution_agents" / "embeddings.json")
        self.dispatch = mock.Mock(return_value=True)
        self.embedder = FakeEmbedder()
        self._patches: List[Any] = []

    def start(self) -> "TempServerState":
        targets = [
            (runtime_module, "get_settings", lambda: self.settings),
            (runtime_module, "get_conversation_log", lambda: self.conversation),
            (runtime_module, "get_working_memory_log", lambda: self.working_memory),
            (routing_module, "get_settings", lambda: self.settings),
            (routing_module, "get_agent_records", lambda: self.records),
            (routing_module, "get_embedding_index", lambda: self.index),
            (routing_module, "get_agent_roster", lambda: self.roster),
            (routing_module, "get_execution_agent_logs", lambda: self.logs),
            # Records mode gets the fake embedder: no OpenRouter calls from tests.
            (routing_module, "OpenRouterEmbedder", lambda *args, **kwargs: self.embedder),
            (agent_module, "get_agent_roster", lambda: self.roster),
            (tools_records, "get_agent_records", lambda: self.records),
            (tools_records, "get_agent_roster", lambda: self.roster),
            (tools_records, "get_execution_agent_logs", lambda: self.logs),
            (tools_records, "_dispatch", self.dispatch),
        ]
        for module, name, value in targets:
            patcher = mock.patch.object(module, name, value)
            patcher.start()
            self._patches.append(patcher)
        return self

    def stop(self) -> None:
        for patcher in reversed(self._patches):
            patcher.stop()
        self._patches.clear()
        self._tmp.cleanup()
