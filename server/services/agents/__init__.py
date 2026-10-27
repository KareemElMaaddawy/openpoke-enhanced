"""Agent records used by records-mode routing."""

from .records import (
    AgentRecord,
    AgentRecordStore,
    SlugCollision,
    WorkSnippet,
    get_agent_records,
    reconcile_from_roster,
    truncate_text,
)
from .text import render_agent_entry, retrieval_text

__all__ = [
    "AgentRecord",
    "AgentRecordStore",
    "SlugCollision",
    "WorkSnippet",
    "get_agent_records",
    "reconcile_from_roster",
    "render_agent_entry",
    "retrieval_text",
    "truncate_text",
]
