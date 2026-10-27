"""Retrieval parameters.

The defaults are the values frozen for the version 1 test run
(evals/agent_overload/configs/v1_records_test.json, tuned on dev on 2026-10-27), so
``make dev ROUTING=records`` runs what was measured. A harness test checks they match.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetrievalParams:
    # Show every record when there are at most this many active ones. The server reads
    # OPENPOKE_FULL_ROSTER_MAX (Settings.full_roster_max) and falls back to this default.
    full_roster_max: int = 50       # largest baseline dev N below its accuracy drop point (100)
    k: int = 5                      # records shown when retrieving (dev recall@5 0.976 at N=200)
    max_pinned: int = 3             # pinned agents counted inside K
    pin_lookback: int = 3           # recent agent_message entries scanned for result lines
    use_pins: bool = True
    use_semantic: bool = True
    use_lexical: bool = True
    w_sem: float = 1.0
    w_lex: float = 1.0
    w_rec: float = 0.0              # off by default because of the recency-lock risk
    rrf_k: int = 60
    query_with_previous_user_message: bool = False  # off: it pulled toward the old topic on topic switches
    render_recent: int = 1          # snippets shown per prompt entry


__all__ = ["RetrievalParams"]
