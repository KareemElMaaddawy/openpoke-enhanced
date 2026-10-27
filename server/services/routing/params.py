"""Retrieval parameters. Defaults are starting points to tune on dev, not decisions."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalParams:
    # Show every record when there are at most this many active ones. The server reads
    # OPENPOKE_FULL_ROSTER_MAX (Settings.full_roster_max) and falls back to this default.
    full_roster_max: int = 25
    k: int = 8                      # records shown when retrieving
    max_pinned: int = 3             # pinned agents counted inside K
    pin_lookback: int = 3           # recent agent_message entries scanned for result lines
    use_pins: bool = True
    use_semantic: bool = True
    use_lexical: bool = True
    w_sem: float = 1.0
    w_lex: float = 1.0
    w_rec: float = 0.0              # off by default because of the recency-lock risk
    rrf_k: int = 60
    query_with_previous_user_message: bool = True
    render_recent: int = 1          # snippets shown per prompt entry


__all__ = ["RetrievalParams"]
