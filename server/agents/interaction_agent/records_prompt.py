"""Records-mode prompt: system prompt file and the per-turn message builder."""

import re
from pathlib import Path
from typing import Dict, List, Optional

from .agent import _render_conversation_history, _render_current_turn

RECORDS_PROMPT_PATH = Path(__file__).parent / "system_prompt_records.md"
ROUTING_MARKER = re.compile(r"^<!-- routing:(?:start|end) -->\n?", re.MULTILINE)

# The file keeps the routing markers so a test can check it against system_prompt.md;
# the model gets the prompt without them.
RECORDS_SYSTEM_PROMPT = ROUTING_MARKER.sub("", RECORDS_PROMPT_PATH.read_text(encoding="utf-8")).strip()


def build_records_system_prompt() -> str:
    """Return the static system prompt for the interaction agent in records mode."""
    return RECORDS_SYSTEM_PROMPT


def prepare_records_messages(
    latest_text: str,
    transcript: str,
    message_type: str,
    rendered_agents: Optional[str],
    shown: int,
    total: int,
) -> List[Dict[str, str]]:
    """Same structure as prepare_message_with_history, with record entries in <active_agents>."""
    agents = rendered_agents if rendered_agents else "None"
    sections = [
        _render_conversation_history(transcript),
        f'<active_agents shown="{shown}" total="{total}">\n{agents}\n</active_agents>',
        _render_current_turn(latest_text, message_type),
    ]
    return [{"role": "user", "content": "\n\n".join(sections)}]


__all__ = [
    "RECORDS_PROMPT_PATH",
    "RECORDS_SYSTEM_PROMPT",
    "build_records_system_prompt",
    "prepare_records_messages",
]
