"""Text views of agent records: retrieval text for the index and BM25, and prompt entries.

Both functions accept an AgentRecord or a routing RecordView (duck-typed), so the server
and the eval harness render records the same way.
"""

from __future__ import annotations

from html import escape
from typing import Any, List

RETRIEVAL_TEXT_MAX_CHARS = 1500


def _work_line(snippet: Any) -> str:
    return snippet.instructions + (f" → {snippet.result}" if snippet.result else "")


def retrieval_text(r: Any) -> str:
    """Name, purpose, then up to 3 snippets, newest first; ≤ 1,500 chars."""
    lines = [r.name]
    if r.purpose:
        lines.append(r.purpose)
    for w in reversed(r.recent_work):
        lines.append(_work_line(w))
    return "\n".join(lines)[:RETRIEVAL_TEXT_MAX_CHARS]


def render_agent_entry(r: Any, render_recent: int = 1) -> str:
    """Render one <agent> entry for the <active_agents> block."""
    attrs = [f'id="{escape(r.agent_id, quote=True)}"', f'name="{escape(r.name, quote=True)}"']
    if r.last_active:
        attrs.append(f'last_active="{escape(r.last_active[:10], quote=True)}"')
    attrs.append(f'tasks="{int(r.task_count)}"')

    lines: List[str] = [f"<agent {' '.join(attrs)}>"]
    if r.purpose:
        lines.append(f"<purpose>{escape(r.purpose, quote=True)}</purpose>")
    if render_recent > 0:
        for w in list(reversed(r.recent_work))[:render_recent]:
            lines.append(f"<recent>{escape(_work_line(w), quote=True)}</recent>")
    lines.append("</agent>")
    return "\n".join(lines)


__all__ = ["retrieval_text", "render_agent_entry", "RETRIEVAL_TEXT_MAX_CHARS"]
