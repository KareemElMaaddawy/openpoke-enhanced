"""Pins: agents named in execution results, for implicit follow-ups ("reply to that")."""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Dict, List, Optional, Sequence

from ..execution.log_store import _slugify

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .candidates import EntryView, RecordView
    from .params import RetrievalParams

# Lines written by ExecutionBatchManager._format_batch_payload: "[SUCCESS] Agent Name: response"
RESULT_LINE = re.compile(r"^\[(SUCCESS|FAILED)\] (.+?): ")


def result_line_names(text: str) -> List[str]:
    """Agent names from every `[STATUS] name: ` line in *text*, in order."""
    names: List[str] = []
    for line in (text or "").splitlines():
        match = RESULT_LINE.match(line)
        if match:
            names.append(match.group(2))
    return names


class _NameResolver:
    """Exact name, then exact alias, then slug."""

    def __init__(self, records: Sequence["RecordView"]):
        self._by_name: Dict[str, str] = {}
        self._by_alias: Dict[str, str] = {}
        self._by_slug: Dict[str, str] = {}
        for r in records:
            self._by_name.setdefault(r.name, r.agent_id)
            for alias in r.aliases:
                self._by_alias.setdefault(alias, r.agent_id)
                self._by_slug.setdefault(_slugify(alias), r.agent_id)
            self._by_slug.setdefault(_slugify(r.name), r.agent_id)

    def resolve(self, name: str) -> Optional[str]:
        return self._by_name.get(name) or self._by_alias.get(name) or self._by_slug.get(_slugify(name))


def find_pins(
    message_text: str,
    message_type: str,
    entries: Sequence["EntryView"],
    records: Sequence["RecordView"],
    params: "RetrievalParams",
) -> List[str]:
    """Agent ids to pin: names in this execution result, then in recent result lines, newest first."""
    if not params.use_pins or params.max_pinned <= 0:
        return []

    names: List[str] = []
    if message_type == "agent":
        names.extend(result_line_names(message_text))

    agent_messages = [e for e in entries if e.tag == "agent_message"]
    lookback = agent_messages[-params.pin_lookback:] if params.pin_lookback > 0 else []
    for entry in reversed(lookback):
        names.extend(result_line_names(entry.payload))

    resolver = _NameResolver(records)
    pins: List[str] = []
    for name in names:
        agent_id = resolver.resolve(name)
        if agent_id and agent_id not in pins:
            pins.append(agent_id)
            if len(pins) >= params.max_pinned:
                break
    return pins


__all__ = ["RESULT_LINE", "find_pins", "result_line_names"]
