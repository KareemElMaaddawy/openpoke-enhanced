"""Retrieval queries built from the incoming message and recent context."""

from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional, Sequence

from .pins import RESULT_LINE

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .candidates import EntryView
    from .params import RetrievalParams

EMAIL_ALERT_PREFIX = "Important email watcher notification:"
QUERY_MAX_CHARS = 2000


def message_query(message_text: str, message_type: str) -> str:
    """The message text, without `[STATUS] name: ` prefixes or the email-alert prefix."""
    text = (message_text or "").strip()
    if message_type == "agent":
        if text.startswith(EMAIL_ALERT_PREFIX):
            text = text[len(EMAIL_ALERT_PREFIX):].strip()
        else:
            text = "\n".join(RESULT_LINE.sub("", line, count=1) for line in text.splitlines())
    return text[:QUERY_MAX_CHARS]


def previous_user_message(entries: Sequence["EntryView"]) -> Optional[str]:
    for entry in reversed(entries):
        if entry.tag == "user_message" and entry.payload.strip():
            return entry.payload.strip()
    return None


def build_queries(
    message_text: str,
    message_type: str,
    entries: Sequence["EntryView"],
    params: "RetrievalParams",
) -> List[str]:
    """[q_msg] or [q_msg, q_ctx], each cut to 2,000 characters."""
    q_msg = message_query(message_text, message_type)
    queries = [q_msg]
    if params.query_with_previous_user_message:
        previous = previous_user_message(entries)
        if previous:
            queries.append(f"{previous}\n{q_msg}"[:QUERY_MAX_CHARS])
    return queries


__all__ = ["EMAIL_ALERT_PREFIX", "QUERY_MAX_CHARS", "build_queries", "message_query"]
