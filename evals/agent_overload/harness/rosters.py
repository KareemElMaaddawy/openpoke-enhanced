"""Deterministic roster for (case, N), the same for every method and repetition.

Design: "Building the roster for (case, N)". Required agents are always present;
filler is a prefix of the split's fixed ``filler_order`` (so rosters are nested
across N); the position anchor is placed in its ``target_position`` bucket and
everything else is shuffled into the remaining slots with a generator seeded by
``sha256(f"{case_id}|{N}|roster")``.
"""

from __future__ import annotations

from typing import Optional

from .util import seeded_rng

BUCKETS = ("first_third", "middle_third", "last_third")
MAX_REQUIRED = {"single": 6, "sequence": 8}


def bucket_range(bucket: str, n: int) -> tuple[int, int]:
    if bucket == "first_third":
        return 0, n // 3
    if bucket == "middle_third":
        return n // 3, 2 * n // 3
    if bucket == "last_third":
        return 2 * n // 3, n
    raise ValueError(f"unknown position bucket: {bucket}")


def bucket_of(index: int, n: int) -> str:
    for bucket in BUCKETS:
        lo, hi = bucket_range(bucket, n)
        if lo <= index < hi:
            return bucket
    raise ValueError(f"index {index} outside roster of size {n}")


def position_anchor(case: dict, agent_of_thread: dict[str, str], threads: dict[str, dict]) -> Optional[str]:
    """The agent placed in ``target_position``, or ``None`` when the case has no anchor.

    REUSE and REUSE_ANY: the first target thread's agent. CREATE: the agent of the
    new thread's near-distractor, when it is a required agent. NO_DELEGATION and
    sequences: no anchor.
    """
    label = case.get("label")
    if not label:
        return None
    kind = label["kind"]
    required = set(case["required_agents"])
    if kind in ("REUSE", "REUSE_ANY"):
        return agent_of_thread[label["threads"][0]]
    if kind == "CREATE":
        distractor = threads.get(label["new_thread"], {}).get("near_distractor_of")
        if distractor and agent_of_thread.get(distractor) in required:
            return agent_of_thread[distractor]
    return None


def build_roster(
    case_id: str,
    required: list[str],
    n: int,
    filler_order: list[str],
    anchor: Optional[str] = None,
    target_position: Optional[str] = None,
) -> list[str]:
    """Agent ids in roster order for one case at roster size ``n``."""
    if len(set(required)) != len(required):
        raise ValueError(f"{case_id}: duplicate required agents")
    if len(required) > n:
        raise ValueError(f"{case_id}: {len(required)} required agents do not fit N={n}")
    filler_count = n - len(required)
    filler = [a for a in filler_order if a not in set(required)][:filler_count]
    if len(filler) < filler_count:
        raise ValueError(f"{case_id}: not enough filler agents for N={n}")
    if (anchor is None) != (target_position is None):
        raise ValueError(f"{case_id}: anchor and target_position must be set together")

    rng = seeded_rng(f"{case_id}|{n}|roster")
    if anchor is None:
        pool = list(required) + filler
        rng.shuffle(pool)
        return pool

    if anchor not in required:
        raise ValueError(f"{case_id}: anchor {anchor} is not a required agent")
    lo, hi = bucket_range(target_position, n)
    anchor_index = rng.randrange(lo, hi)
    others = [a for a in required if a != anchor] + filler
    rng.shuffle(others)
    roster = others[:anchor_index] + [anchor] + others[anchor_index:]
    return roster


def roster_for_case(
    case: dict,
    n: int,
    filler_order: list[str],
    agent_of_thread: dict[str, str],
    threads: dict[str, dict],
) -> list[str]:
    """Roster for a single-turn or sequence case, using its anchor and ``target_position``."""
    anchor = position_anchor(case, agent_of_thread, threads)
    target_position = case.get("target_position") if anchor is not None else None
    if anchor is not None and target_position is None:
        raise ValueError(f"{case['case_id']}: case has an anchor but no target_position")
    return build_roster(case["case_id"], list(case["required_agents"]), n, filler_order, anchor, target_position)
