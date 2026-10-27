"""Records-mode tools: reuse by agent_id, and a separate create_agent that needs a purpose.

Only the routing tool changes. send_message_to_user, send_draft and wait are the legacy
functions and schemas.
"""

import asyncio
import json
from collections import Counter
from typing import Any

from ...logging_config import logger
from ...services.agents import SlugCollision, get_agent_records, truncate_text
from ...services.agents.records import PURPOSE_MAX_CHARS
from ...services.execution import get_agent_roster, get_execution_agent_logs
from ...utils.timezones import now_in_user_timezone
from .tools import (
    _EXECUTION_BATCH_MANAGER,
    TOOL_SCHEMAS,
    ToolResult,
    send_draft,
    send_message_to_user,
    wait,
)

AGENT_NAME_MAX_CHARS = 60

SEND_MESSAGE_TO_AGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "send_message_to_agent",
        "description": "Give a task to an existing execution agent from <active_agents>. The agent keeps its history, so prefer the agent that already holds the relevant context.",
        "parameters": {
            "type": "object",
            "properties": {
                "agent_id": {"type": "string", "description": "The id attribute of an agent in <active_agents>, e.g. 'ag_1f3a9c2e'."},
                "instructions": {"type": "string", "description": "Instructions for the agent to execute."},
            },
            "required": ["agent_id", "instructions"],
            "additionalProperties": False,
        },
    },
}

CREATE_AGENT_SCHEMA = {
    "type": "function",
    "function": {
        "name": "create_agent",
        "description": "Start a new execution agent for work no agent in <active_agents> covers, and give it its first task.",
        "parameters": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Short human-readable name for the ongoing work (e.g. 'Vercel Job Offer', 'Email to Sharanjeet'). At most 60 characters."},
                "purpose": {"type": "string", "description": "One sentence on the ongoing work this agent owns: the person, company or thread, and the kind of task. Used to find the agent again later. At most 200 characters."},
                "instructions": {"type": "string", "description": "Instructions for the agent's first task."},
            },
            "required": ["name", "purpose", "instructions"],
            "additionalProperties": False,
        },
    },
}

RECORDS_TOOL_SCHEMAS = [
    SEND_MESSAGE_TO_AGENT_SCHEMA,
    CREATE_AGENT_SCHEMA,
    *[s for s in TOOL_SCHEMAS if s["function"]["name"] != "send_message_to_agent"],
]

# Routing events worth watching in make logs: resolved_by_name, unknown_agent_id,
# rejected_create, purpose_fallback. Process-lifetime counts, reset on restart.
ROUTING_COUNTS: Counter = Counter()


def _count(event: str) -> int:
    ROUTING_COUNTS[event] += 1
    return ROUTING_COUNTS[event]


def _now() -> str:
    return now_in_user_timezone("%Y-%m-%d %H:%M:%S")


def _dispatch(agent_id: str, agent_name: str, instructions: str) -> bool:
    """Run the execution agent in the background, as legacy does; record its result on completion."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.error("No running event loop available for async execution")
        return False

    async def _execute_async() -> None:
        try:
            result = await _EXECUTION_BATCH_MANAGER.execute_agent(agent_name, instructions)
            get_agent_records().record_result(agent_id, result.response)
            status = "SUCCESS" if result.success else "FAILED"
            logger.info(f"Agent '{agent_name}' ({agent_id}) completed: {status}")
        except Exception as exc:  # pragma: no cover - defensive
            logger.error(f"Agent '{agent_name}' ({agent_id}) failed: {str(exc)}")

    loop.create_task(_execute_async())
    return True


def send_message_to_agent(agent_id: str, instructions: str) -> ToolResult:
    """Send instructions to an existing agent, resolved by id (or, as a fallback, by name)."""
    store = get_agent_records()
    record = store.get(agent_id)
    if record is None:
        record = store.find_by_name_or_slug(agent_id)
        if record is not None:
            n = _count("resolved_by_name")
            logger.info(
                f"Resolved agent_id {agent_id!r} by name to {record.agent_id} "
                f"(resolved_by=\"name\", count={n})"
            )
    if record is None:
        n = _count("unknown_agent_id")
        logger.warning(f"Unknown agent_id {agent_id!r}; nothing dispatched (count={n})")
        return ToolResult(
            success=False,
            payload={
                "error": f"Unknown agent_id '{agent_id}'. Use an id from <active_agents>, or create_agent for new work."
            },
        )

    store.touch_dispatch(record.agent_id, instructions, _now())
    get_execution_agent_logs().record_request(record.name, instructions)
    logger.info(f"Reused agent: {record.name} ({record.agent_id})")

    if not _dispatch(record.agent_id, record.name, instructions):
        return ToolResult(success=False, payload={"error": "No event loop available"})

    return ToolResult(
        success=True,
        payload={
            "status": "submitted",
            "agent_id": record.agent_id,
            "agent_name": record.name,
            "new_agent_created": False,
        },
    )


def create_agent(name: str, purpose: str, instructions: str) -> ToolResult:
    """Create a new agent with a purpose and give it its first task."""
    name = (name or "").strip()[:AGENT_NAME_MAX_CHARS].strip()
    purpose = (purpose or "").strip()
    if not name:
        return ToolResult(success=False, payload={"error": "Agent name is required."})

    purpose_source = "create"
    if not purpose:
        purpose = truncate_text(instructions, PURPOSE_MAX_CHARS)
        purpose_source = "instructions_fallback"
        n = _count("purpose_fallback")
        logger.warning(f"create_agent '{name}' had no purpose; using the instructions (count={n})")

    store = get_agent_records()
    now = _now()
    try:
        record = store.create(name, purpose, now, purpose_source=purpose_source)
    except SlugCollision as exc:
        existing = exc.existing
        n = _count("rejected_create")
        logger.info(f"create_agent '{name}' rejected: collides with {existing.agent_id} (count={n})")
        return ToolResult(
            success=False,
            payload={
                "error": (
                    f"An agent named '{existing.name}' (id {existing.agent_id}) already exists. "
                    "Use send_message_to_agent with that id, or choose a different name."
                ),
                "existing_agent_id": existing.agent_id,
            },
        )

    get_agent_roster().add_agent(name)
    get_execution_agent_logs().record_request(name, instructions)
    store.touch_dispatch(record.agent_id, instructions, now)
    logger.info(f"Created agent: {name} ({record.agent_id})")

    if not _dispatch(record.agent_id, name, instructions):
        return ToolResult(success=False, payload={"error": "No event loop available"})

    return ToolResult(
        success=True,
        payload={
            "status": "submitted",
            "agent_id": record.agent_id,
            "agent_name": name,
            "new_agent_created": True,
        },
    )


def get_records_tool_schemas():
    """Return the records-mode tool schemas."""
    return RECORDS_TOOL_SCHEMAS


# Same shape as tools.handle_tool_call, with the records routing tools
def handle_records_tool_call(name: str, arguments: Any) -> ToolResult:
    """Handle tool calls from the interaction agent in records mode."""
    try:
        if isinstance(arguments, str):
            args = json.loads(arguments) if arguments.strip() else {}
        elif isinstance(arguments, dict):
            args = arguments
        else:
            return ToolResult(success=False, payload={"error": "Invalid arguments format"})

        if name == "send_message_to_agent":
            return send_message_to_agent(**args)
        if name == "create_agent":
            return create_agent(**args)
        if name == "send_message_to_user":
            return send_message_to_user(**args)
        if name == "send_draft":
            return send_draft(**args)
        if name == "wait":
            return wait(**args)

        logger.warning("unexpected tool", extra={"tool": name})
        return ToolResult(success=False, payload={"error": f"Unknown tool: {name}"})
    except json.JSONDecodeError:
        return ToolResult(success=False, payload={"error": "Invalid JSON"})
    except TypeError as exc:
        return ToolResult(success=False, payload={"error": f"Missing required arguments: {exc}"})
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("tool call failed", extra={"tool": name, "error": str(exc)})
        return ToolResult(success=False, payload={"error": "Failed to execute"})


__all__ = [
    "CREATE_AGENT_SCHEMA",
    "RECORDS_TOOL_SCHEMAS",
    "ROUTING_COUNTS",
    "SEND_MESSAGE_TO_AGENT_SCHEMA",
    "create_agent",
    "get_records_tool_schemas",
    "handle_records_tool_call",
    "send_message_to_agent",
]
