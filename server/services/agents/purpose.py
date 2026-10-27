"""Purpose backfill: one model call that writes a purpose line from an agent's name and first task.

Shared by the eval harness (``records_retrieval`` with ``seed_purposes: "backfill"``) and,
later, an optional paid production backfill for imported agents. Only the prompt and its
parsing live here; callers make the call with their own client.
"""

from __future__ import annotations

import hashlib
from typing import Dict, List, Tuple

from .records import PURPOSE_MAX_CHARS, truncate_text

PURPOSE_SYSTEM_PROMPT = (
    "You write the purpose line for a background worker in a personal assistant. Given the worker's "
    "name and its first task, write one sentence of at most 25 words naming the person, company or "
    "thread and the kind of ongoing work. Output only the sentence."
)
PURPOSE_PROMPT_SHA256 = hashlib.sha256(PURPOSE_SYSTEM_PROMPT.encode("utf-8")).hexdigest()


def purpose_request(name: str, first_task: str) -> Tuple[str, List[Dict[str, str]]]:
    """(system prompt, messages) for one backfill call."""
    return PURPOSE_SYSTEM_PROMPT, [{"role": "user", "content": f"Name: {name}\nFirst task: {first_task}"}]


def purpose_cache_key(name: str, first_task: str) -> str:
    """sha256(prompt + name + instructions): a cached purpose is reused only for the same inputs."""
    return hashlib.sha256(f"{PURPOSE_SYSTEM_PROMPT}\0{name}\0{first_task}".encode("utf-8")).hexdigest()


def clean_purpose(text: str) -> str:
    """The model's sentence without surrounding quotes, cut to the record limit."""
    cleaned = (text or "").strip().strip('"').strip("'").strip()
    return truncate_text(cleaned, PURPOSE_MAX_CHARS)


__all__ = [
    "PURPOSE_PROMPT_SHA256",
    "PURPOSE_SYSTEM_PROMPT",
    "clean_purpose",
    "purpose_cache_key",
    "purpose_request",
]
