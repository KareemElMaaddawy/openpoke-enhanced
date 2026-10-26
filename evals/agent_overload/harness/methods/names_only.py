"""Baseline method ``names_only`` version 1: reproduces production routing exactly.

- The roster function ``get_agent_roster`` used by ``prepare_message_with_history`` is
  replaced once with a fake that reads the turn's names from a ``ContextVar``, so
  concurrent turns never see each other's rosters.
- The prompt is built by the unchanged ``build_system_prompt`` and
  ``prepare_message_with_history``.
- The real ``_run_interaction_loop`` runs in a subclass of ``InteractionAgentRuntime``
  whose ``_make_llm_call`` goes through ``harness/llm.py`` and whose ``_execute_tool``
  dispatches to stubs with the real tools' signatures and payloads. The stubs never
  touch the roster, the conversation log, the execution logs or the event loop.
"""

from __future__ import annotations

import contextvars
import json
from typing import Any, Optional

from server.agents.interaction_agent import agent as interaction_agent_module
from server.agents.interaction_agent.agent import build_system_prompt, prepare_message_with_history
from server.agents.interaction_agent.runtime import InteractionAgentRuntime, _ToolCall
from server.agents.interaction_agent.tools import ToolResult, get_tool_schemas
from server.config import get_settings

from ..llm import CALL_CONTEXT, ApiError, ModelClient
from ..state import render_transcript
from ..util import EVAL_ROOT, REPO_ROOT, call_seed, sha256_file, sha256_hex
from .base import AgentView, Delegation, Entry, RoutingInput, RoutingOutput, new_agent_key

LOOP_LIMIT_MESSAGE = "Reached tool iteration limit without final response"

_ROSTER_NAMES: contextvars.ContextVar[tuple[str, ...]] = contextvars.ContextVar("names_only_roster", default=())


class _ContextRoster:
    """Stands in for ``AgentRoster``: ``load()`` is a no-op, names come from the ContextVar."""

    def load(self) -> None:
        return None

    def get_agents(self) -> list[str]:
        return list(_ROSTER_NAMES.get())


_CONTEXT_ROSTER = _ContextRoster()
_installed = False


def install_roster_patch() -> None:
    """Replace ``get_agent_roster`` in the interaction agent's prompt module (once)."""
    global _installed
    if not _installed:
        interaction_agent_module.get_agent_roster = lambda: _CONTEXT_ROSTER
        _installed = True


def build_messages(inp: RoutingInput) -> tuple[str, list[dict]]:
    """System prompt and messages exactly as production builds them for this input."""
    install_roster_patch()
    token = _ROSTER_NAMES.set(tuple(a.name for a in inp.roster))
    try:
        transcript = render_transcript(inp.summary_text, inp.entries)
        messages = prepare_message_with_history(inp.message_text, transcript, message_type=inp.message_type)
    finally:
        _ROSTER_NAMES.reset(token)
    return build_system_prompt(), messages


class TurnRecorder:
    """What the stubs observed during one turn."""

    def __init__(self, roster: tuple[AgentView, ...]):
        self.name_to_id = {a.name: a.agent_id for a in roster}
        self.created: list[str] = []
        self.delegations: list[Delegation] = []
        self.effects: list[Entry] = []
        self.invalid_calls: list[dict] = []
        self.iteration = -1
        self.raw_arguments: dict[str, Any] = {}


class ToolStubs:
    """Same signatures and ``ToolResult`` payloads as ``server/agents/interaction_agent/tools.py``."""

    def __init__(self, recorder: TurnRecorder):
        self.r = recorder
        self.current_call: Optional[_ToolCall] = None

    def _raw(self) -> Any:
        call = self.current_call
        if call is None:
            return None
        return self.r.raw_arguments.get(call.identifier or "", call.arguments)

    def send_message_to_agent(self, agent_name: str, instructions: str) -> ToolResult:
        existing = set(self.r.name_to_id) | set(self.r.created)
        is_new = agent_name not in existing
        payload = {"status": "submitted", "agent_name": agent_name, "new_agent_created": is_new}
        if not isinstance(agent_name, str):
            # Production fails while slugifying a non-string name and reports "Failed to execute".
            raise TypeError("agent_name must be a string")
        if agent_name == "":
            # Production would create an agent named "" and answer as below; the harness scores it invalid.
            self.r.invalid_calls.append(
                {"tool": "send_message_to_agent", "raw_arguments": self._raw(), "error": "empty agent_name"}
            )
            return ToolResult(success=True, payload=payload)
        if is_new:
            self.r.created.append(agent_name)
        key = self.r.name_to_id.get(agent_name) or new_agent_key(agent_name)
        self.r.delegations.append(
            Delegation(
                agent_key=key,
                agent_name=agent_name,
                instructions=str(instructions),
                iteration=self.r.iteration,
                order=len(self.r.delegations),
            )
        )
        return ToolResult(success=True, payload=payload)

    def send_message_to_user(self, message: str) -> ToolResult:
        self.r.effects.append(Entry("poke_reply", "", str(message)))
        return ToolResult(success=True, payload={"status": "delivered"}, user_message=message, recorded_reply=True)

    def send_draft(self, to: str, subject: str, body: str) -> ToolResult:
        self.r.effects.append(Entry("poke_reply", "", f"To: {to}\nSubject: {subject}\n\n{body}"))
        return ToolResult(
            success=True,
            payload={"status": "draft_recorded", "to": to, "subject": subject},
            recorded_reply=True,
        )

    def wait(self, reason: str) -> ToolResult:
        self.r.effects.append(Entry("wait", "", str(reason)))
        return ToolResult(success=True, payload={"status": "waiting", "reason": reason}, recorded_reply=True)

    def handle_tool_call(self, name: str, arguments: Any) -> ToolResult:
        """Mirror of ``tools.handle_tool_call`` dispatching to the stubs."""
        try:
            if isinstance(arguments, str):
                args = json.loads(arguments) if arguments.strip() else {}
            elif isinstance(arguments, dict):
                args = arguments
            else:
                return ToolResult(success=False, payload={"error": "Invalid arguments format"})

            if name == "send_message_to_agent":
                return self.send_message_to_agent(**args)
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
            if str(exc) == "agent_name must be a string":
                return ToolResult(success=False, payload={"error": "Failed to execute"})
            return ToolResult(success=False, payload={"error": f"Missing required arguments: {exc}"})
        except Exception:  # pragma: no cover - defensive, as in production
            return ToolResult(success=False, payload={"error": "Failed to execute"})


# TypeError messages name the function by its __qualname__ ("ToolStubs.wait() missing ...").
# The model sees that text in the tool result, so it must read like the real module-level tools.
for _stub_name in ("send_message_to_agent", "send_message_to_user", "send_draft", "wait"):
    getattr(ToolStubs, _stub_name).__qualname__ = _stub_name


class HarnessInteractionRuntime(InteractionAgentRuntime):
    """The production loop with the model call and the tools swapped out."""

    def __init__(
        self,
        *,
        client: ModelClient,
        model: str,
        provider: Optional[dict],
        extra_params: Optional[dict],
        recorder: TurnRecorder,
        purpose: str = "routing",
    ) -> None:
        # Not calling super().__init__: it requires an API key and opens the real logs,
        # neither of which the harness uses. The loop only needs these attributes.
        self.settings = get_settings()
        self.api_key = None
        self.model = model
        self.tool_schemas = get_tool_schemas()
        self._client = client
        self._provider = provider
        self._extra = dict(extra_params or {})
        self._recorder = recorder
        self._stubs = ToolStubs(recorder)
        self._purpose = purpose
        self.calls: list = []

    async def _make_llm_call(self, system_prompt: str, messages: list[dict[str, Any]]) -> dict[str, Any]:
        self._recorder.iteration += 1
        ctx = CALL_CONTEXT.get()
        seed = call_seed(
            self._purpose,
            ctx.get("case_id"),
            ctx.get("N"),
            ctx.get("mode"),
            ctx.get("rep"),
            ctx.get("turn"),
            self._recorder.iteration,
        )
        response, record = await self._client.chat(
            purpose=self._purpose,
            model=self.model,
            messages=messages,
            system=system_prompt,
            tools=self.tool_schemas,
            provider=self._provider,
            seed=seed,
            extra=self._extra,
        )
        self.calls.append(record)
        choice = (response.get("choices") or [{}])[0]
        message = choice.get("message")
        if not isinstance(message, dict):
            raise ApiError("response did not include an assistant message")
        for raw in message.get("tool_calls") or []:
            function = raw.get("function") or {}
            self._recorder.raw_arguments[raw.get("id") or function.get("name") or ""] = function.get("arguments")
            if not isinstance(function.get("name"), str) or not function.get("name"):
                # Production skips nameless calls with a warning; the harness counts them as invalid.
                self._recorder.invalid_calls.append(
                    {"tool": None, "raw_arguments": function.get("arguments"), "error": "tool call without name"}
                )
        return response

    def _execute_tool(self, tool_call: _ToolCall) -> ToolResult:
        if "__invalid_arguments__" in tool_call.arguments:
            error = tool_call.arguments["__invalid_arguments__"]
            self._recorder.invalid_calls.append(
                {
                    "tool": tool_call.name,
                    "raw_arguments": self._recorder.raw_arguments.get(tool_call.identifier or tool_call.name),
                    "error": error,
                }
            )
            return ToolResult(success=False, payload={"error": error})
        self._stubs.current_call = tool_call
        result = self._stubs.handle_tool_call(tool_call.name, tool_call.arguments)
        if not result.success:
            self._recorder.invalid_calls.append(
                {
                    "tool": tool_call.name,
                    "raw_arguments": self._recorder.raw_arguments.get(tool_call.identifier or tool_call.name),
                    "error": (result.payload or {}).get("error"),
                }
            )
        return result


class NamesOnlyMethod:
    name = "names_only"
    version = "1"

    def __init__(
        self,
        client: ModelClient,
        model: str,
        provider: Optional[dict] = None,
        extra_params: Optional[dict] = None,
        purpose: str = "routing",
    ):
        self.client = client
        self.model = model
        self.provider = provider
        self.extra_params = dict(extra_params or {})
        self.purpose = purpose
        install_roster_patch()

    def describe(self) -> dict:
        from server.agents.interaction_agent.tools import TOOL_SCHEMAS

        return {
            "name": self.name,
            "version": self.version,
            "params": {},
            "system_prompt_sha256": sha256_file(REPO_ROOT / "server/agents/interaction_agent/system_prompt.md"),
            "tool_schemas_sha256": sha256_hex(json.dumps(TOOL_SCHEMAS, sort_keys=True)),
            "method_source_sha256": sha256_file(EVAL_ROOT / "harness" / "methods" / "names_only.py"),
            "max_tool_iterations": InteractionAgentRuntime.MAX_TOOL_ITERATIONS,
            "cache": None,
        }

    async def prepare(self, agents: list[AgentView]) -> None:
        return None

    async def route(self, inp: RoutingInput) -> RoutingOutput:
        system_prompt, messages = build_messages(inp)
        recorder = TurnRecorder(inp.roster)
        runtime = HarnessInteractionRuntime(
            client=self.client,
            model=self.model,
            provider=self.provider,
            extra_params=self.extra_params,
            recorder=recorder,
            purpose=self.purpose,
        )
        loop_limit_hit = False
        try:
            summary = await runtime._run_interaction_loop(system_prompt, messages)
        except RuntimeError as exc:
            if str(exc) != LOOP_LIMIT_MESSAGE:
                raise
            loop_limit_hit = True
        else:
            final = runtime._finalize_response(summary)
            if final and not summary.user_messages:
                # Same as _finalize_response + record_reply when no send_message_to_user was made.
                recorder.effects.append(Entry("poke_reply", "", final))
        return RoutingOutput(
            delegations=recorder.delegations,
            history_effects=recorder.effects,
            invalid_calls=recorder.invalid_calls,
            llm_calls=list(runtime.calls),
            diagnostics={},
            loop_limit_hit=loop_limit_hit,
        )
