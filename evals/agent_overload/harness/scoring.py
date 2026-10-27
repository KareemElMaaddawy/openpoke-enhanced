"""Outcome labels and tags for one turn, the same for every method (design: Scoring, version 1)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from .methods.base import Delegation, RoutingOutput, is_new_key
from .util import is_near_duplicate, slug

SCORER_VERSION = "1"

DELEGATING_KINDS = ("REUSE", "REUSE_ANY", "CREATE")
REUSE_KINDS = ("REUSE", "REUSE_ANY")
CORRECT_OUTCOMES = ("correct_reuse", "correct_create", "correct_no_delegation")
PRIMARY_OUTCOMES = (
    "correct_reuse",
    "correct_create",
    "correct_no_delegation",
    "duplicate_reuse",
    "misroute",
    "false_spawn",
    "false_reuse",
    "missed_delegation",
    "extra_delegation",
)
TAGS = (
    "near_duplicate",
    "slug_collision",
    "recency",
    "context_reuse",
    "reply_is_question",
    "target_excluded",
)

STATUS_OK = "ok"
STATUS_LOOP_LIMIT = "loop_limit"
STATUS_API_ERROR = "api_error"


@dataclass
class ScoringContext:
    """What the scorer needs besides the method's output.

    ``roster`` is the snapshot at the start of the turn as (agent_id, name) pairs.
    ``agent_context`` is given only for sequences (it enables ``context_reuse``).
    """

    label: dict
    roster: list[tuple[str, str]]
    agent_thread: dict[str, str]
    canonical: dict[str, str]  # thread -> canonical agent id
    prev_thread: Optional[str]
    agent_context: Optional[dict[str, set[str]]] = None


@dataclass
class DistinctDelegation:
    agent_key: str
    agent_name: str
    instructions: str
    iteration: int
    order: int
    repeat_calls: int
    extra: dict = field(default_factory=dict)


@dataclass
class TurnScore:
    outcomes: list[dict]
    primary_outcome: Optional[str]
    primary_key: Optional[str]
    primary_agent_thread: Optional[str]
    tags: list[str]
    turn_correct: Optional[bool]
    turn_correct_lenient: Optional[bool]
    status: str
    distinct: list[DistinctDelegation] = field(default_factory=list)
    recency_eligible: bool = False
    expected_threads: list[str] = field(default_factory=list)


def expected_threads(label: dict) -> list[str]:
    kind = label["kind"]
    if kind in REUSE_KINDS:
        return list(label["threads"])
    if kind == "CREATE":
        return [label["new_thread"]]
    return []


def collapse(delegations: list[Delegation]) -> list[DistinctDelegation]:
    """Collapse delegations with the same ``agent_key``, keeping the first and counting repeats."""
    distinct: dict[str, DistinctDelegation] = {}
    for d in sorted(delegations, key=lambda d: d.order):
        if d.agent_key in distinct:
            distinct[d.agent_key].repeat_calls += 1
            continue
        distinct[d.agent_key] = DistinctDelegation(
            agent_key=d.agent_key,
            agent_name=d.agent_name,
            instructions=d.instructions,
            iteration=d.iteration,
            order=d.order,
            repeat_calls=0,
            extra=dict(d.extra),
        )
    return list(distinct.values())


def classify(d: DistinctDelegation, ctx: ScoringContext) -> str:
    kind = ctx.label["kind"]
    created = is_new_key(d.agent_key)
    if kind in REUSE_KINDS:
        if created:
            return "false_spawn"
        thread = ctx.agent_thread.get(d.agent_key)
        if thread in ctx.label["threads"]:
            return "correct_reuse" if ctx.canonical.get(thread) == d.agent_key else "duplicate_reuse"
        return "misroute"
    if kind == "CREATE":
        return "correct_create" if created else "false_reuse"
    raise ValueError(f"classify called for label {kind}")


def _last_reply(output: RoutingOutput) -> Optional[str]:
    replies = [e.payload for e in output.history_effects if e.tag == "poke_reply"]
    return replies[-1] if replies else None


def _slug_collides(d: DistinctDelegation, ctx: ScoringContext, distinct: list[DistinctDelegation]) -> bool:
    new_slug = slug(d.agent_name)
    others = [name for _, name in ctx.roster]
    others += [o.agent_name for o in distinct if is_new_key(o.agent_key) and o.agent_key != d.agent_key]
    return any(slug(name) == new_slug and name != d.agent_name for name in others)


def score_turn(ctx: ScoringContext, output: Optional[RoutingOutput], status: str = STATUS_OK) -> TurnScore:
    label = ctx.label
    kind = label["kind"]
    expected = expected_threads(label)
    recency_eligible = (
        kind in DELEGATING_KINDS and ctx.prev_thread is not None and ctx.prev_thread not in expected
    )

    if status == STATUS_API_ERROR or output is None:
        return TurnScore(
            outcomes=[],
            primary_outcome=None,
            primary_key=None,
            primary_agent_thread=None,
            tags=[],
            turn_correct=None,
            turn_correct_lenient=None,
            status=STATUS_API_ERROR,
            recency_eligible=recency_eligible,
            expected_threads=expected,
        )

    outcomes: list[dict] = [
        {"outcome": "invalid_call", "tool": call.get("tool"), "error": call.get("error"), "tags": []}
        for call in output.invalid_calls
    ]
    distinct = collapse(output.delegations)
    primary_outcome: Optional[str] = None
    primary: Optional[DistinctDelegation] = None
    has_extra = False

    if kind == "NO_DELEGATION":
        if not distinct:
            primary_outcome = "correct_no_delegation"
            outcomes.append({"outcome": primary_outcome, "tags": []})
        else:
            primary_outcome = "extra_delegation"
            has_extra = True
    elif not distinct:
        primary_outcome = "missed_delegation"
        tags = []
        reply = _last_reply(output)
        if reply is not None and reply.rstrip().endswith("?"):
            tags.append("reply_is_question")
        if _target_excluded(ctx, output, expected):
            tags.append("target_excluded")
        outcomes.append({"outcome": primary_outcome, "tags": tags})
    else:
        classes = [classify(d, ctx) for d in distinct]
        index = next((i for i, c in enumerate(classes) if c in CORRECT_OUTCOMES), 0)
        primary = distinct[index]
        primary_outcome = classes[index]
        has_extra = len(distinct) > 1

    primary_agent_thread = None
    if primary is not None and not is_new_key(primary.agent_key):
        primary_agent_thread = ctx.agent_thread.get(primary.agent_key)

    for d in distinct:
        is_primary = primary is not None and d.agent_key == primary.agent_key
        outcome = primary_outcome if is_primary else "extra_delegation"
        tags: list[str] = []
        if is_new_key(d.agent_key) and _slug_collides(d, ctx, distinct):
            tags.append("slug_collision")
        if is_primary:
            tags += _primary_tags(outcome, d, ctx, output, expected)
        outcomes.append(
            {
                "outcome": outcome,
                "agent_key": d.agent_key,
                "agent_name": d.agent_name,
                "repeat_calls": d.repeat_calls,
                "primary": is_primary,
                "tags": tags,
            }
        )

    turn_tags = sorted({t for o in outcomes for t in o["tags"]})
    correct = primary_outcome in CORRECT_OUTCOMES and not has_extra
    lenient = (primary_outcome in CORRECT_OUTCOMES or primary_outcome == "duplicate_reuse") and not has_extra
    final_status = STATUS_LOOP_LIMIT if output.loop_limit_hit else STATUS_OK
    return TurnScore(
        outcomes=outcomes,
        primary_outcome=primary_outcome,
        primary_key=primary.agent_key if primary is not None else None,
        primary_agent_thread=primary_agent_thread,
        tags=turn_tags,
        turn_correct=correct,
        turn_correct_lenient=lenient,
        status=final_status,
        distinct=distinct,
        recency_eligible=recency_eligible,
        expected_threads=expected,
    )


def _target_excluded(ctx: ScoringContext, output: RoutingOutput, expected: list[str]) -> bool:
    excluded = set(output.diagnostics.get("excluded") or [])
    if not expected or not excluded:
        return False
    for thread in expected:
        agent = ctx.canonical.get(thread)
        if agent is None or agent not in excluded:
            return False
    return True


def _primary_tags(
    outcome: str,
    d: DistinctDelegation,
    ctx: ScoringContext,
    output: RoutingOutput,
    expected: list[str],
) -> list[str]:
    tags: list[str] = []
    chosen_thread = None if is_new_key(d.agent_key) else ctx.agent_thread.get(d.agent_key)

    if outcome == "false_spawn":
        expected_names = [name for agent_id, name in ctx.roster if ctx.agent_thread.get(agent_id) in expected]
        if any(is_near_duplicate(d.agent_name, name) for name in expected_names):
            tags.append("near_duplicate")

    if outcome in ("misroute", "false_reuse"):
        if chosen_thread is not None and chosen_thread == ctx.prev_thread and chosen_thread not in expected:
            tags.append("recency")

    if outcome == "misroute" and ctx.agent_context is not None:
        if ctx.agent_context.get(d.agent_key, set()) & set(expected):
            tags.append("context_reuse")

    if outcome in ("false_spawn", "misroute") and _target_excluded(ctx, output, expected):
        tags.append("target_excluded")

    return tags
