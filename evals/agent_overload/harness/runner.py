"""Suites: ``single``, ``sequence`` and ``token_probe`` (design: Run modes).

The runner owns the state, the cases and scoring; the method only sees a
``RoutingInput``. Every unit sets ``CALL_CONTEXT`` so model calls get their seed
and are attributed to the right case, N, mode, rep and turn.
"""

from __future__ import annotations

import asyncio
import copy
import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

from server.agents.interaction_agent.tools import TOOL_SCHEMAS

from .config import RunPlan
from .fixtures import FixtureSet
from .llm import CALL_CONTEXT, ApiError, ModelClient, SpendCapReached, message_content
from .methods.base import AgentView, RoutingOutput, WorkItem, is_new_key
from .methods.names_only import build_messages
from .rosters import roster_for_case
from .scoring import STATUS_API_ERROR, ScoringContext, TurnScore, score_turn
from .state import (
    DONE_TEXT,
    ORPHAN,
    RoutingState,
    WorkAssignment,
    apply_turn,
    initial_state,
    maybe_summarize,
    next_run_agent_id,
)
from .util import age_days, call_seed

DORMANT_DAYS = 14


@dataclass
class RunContext:
    run_id: str
    plan: RunPlan
    fixtures: FixtureSet
    method: Any  # RoutingMethod
    client: ModelClient
    interaction_model: str
    summarizer_model: str
    provider: Optional[dict]
    extra_params: dict
    turns: list[dict] = field(default_factory=list)
    sequences: list[dict] = field(default_factory=list)
    capped: bool = False
    summarizer_errors: int = 0


# ---------------------------------------------------------------------------
# Case selection


def select_single(cases: list[dict], limit: Optional[int]) -> list[dict]:
    """All cases, or ``limit`` cases picked round-robin across (label kind, query style) cells."""
    ordered = sorted(cases, key=lambda c: c["case_id"])
    if limit is None or limit >= len(ordered):
        return ordered
    cells: dict[tuple, list[dict]] = {}
    for case in ordered:
        cells.setdefault((case["label"]["kind"], case["meta"]["query_style"]), []).append(case)
    picked: list[dict] = []
    while len(picked) < limit:
        for key in sorted(cells):
            if cells[key] and len(picked) < limit:
                picked.append(cells[key].pop(0))
    return sorted(picked, key=lambda c: c["case_id"])


def select_sequences(cases: list[dict], limit: Optional[int]) -> list[dict]:
    ordered = sorted(cases, key=lambda c: c["case_id"])
    return ordered if limit is None else ordered[:limit]


def planned_units(ctx_plan: RunPlan, fixtures: FixtureSet) -> dict[str, int]:
    """Counts used by --dry-run and the pre-run estimate."""
    counts = {"single_turns": 0, "sequence_turns": 0, "sequence_runs": 0, "token_probes": 0}
    for split in ctx_plan.splits:
        singles = select_single(fixtures.single.get(split, []), ctx_plan.single_limit)
        seqs = select_sequences(fixtures.sequences.get(split, []), ctx_plan.sequence_limit)
        counts["single_turns"] += len(singles) * len(ctx_plan.single_sizes[split]) * ctx_plan.single_reps
        runs = len(seqs) * len(ctx_plan.sequence_sizes[split]) * len(ctx_plan.modes) * ctx_plan.sequence_reps
        counts["sequence_runs"] += runs
        counts["sequence_turns"] += sum(len(s["turns"]) for s in seqs) * len(ctx_plan.sequence_sizes[split]) * len(
            ctx_plan.modes
        ) * ctx_plan.sequence_reps
        if ctx_plan.token_probe:
            counts["token_probes"] += len(singles)
    return counts


# ---------------------------------------------------------------------------
# Turn records


def _call_summary(output: Optional[RoutingOutput]) -> dict:
    calls = output.llm_calls if output is not None else []
    routing = [c for c in calls if c.purpose == "routing"]
    return {
        "call_ids": [c.call_id for c in calls],
        "n_calls": len(calls),
        "routing_calls": len(routing),
        "prompt_tokens": sum(c.prompt_tokens or 0 for c in calls),
        "completion_tokens": sum(c.completion_tokens or 0 for c in calls),
        "reasoning_tokens": sum(c.reasoning_tokens or 0 for c in calls),
        "cost": sum(c.cost or 0.0 for c in calls),
        "latency_ms": sum(c.latency_ms or 0.0 for c in calls),
        "first_call_prompt_tokens": routing[0].prompt_tokens if routing else None,
    }


def _candidate_rank(output: Optional[RoutingOutput], state: RoutingState, expected: list[str]) -> tuple[bool, Optional[int]]:
    if output is None or "candidates" not in output.diagnostics:
        return False, None
    threads = state.agent_thread()
    for rank, agent_id in enumerate(output.diagnostics["candidates"], start=1):
        if threads.get(agent_id) in expected:
            return True, rank
    return True, None


def turn_record(
    *,
    ctx: RunContext,
    split: str,
    suite: str,
    case: dict,
    turn: Optional[dict],
    mode: Optional[str],
    n: int,
    rep: int,
    state: RoutingState,
    output: Optional[RoutingOutput],
    score: TurnScore,
    now: str,
    dims: dict,
    error: Optional[str] = None,
) -> dict:
    label = (turn or case)["label"]
    meta = (turn or case)["meta"]
    roster_ids = [a.agent_id for a in state.roster]
    required = set(case["required_agents"])
    excluded = list((output.diagnostics.get("excluded") or []) if output else [])
    has_candidates, rank = _candidate_rank(output, state, score.expected_threads)
    dormant = sum(1 for a in state.roster if age_days(a.last_active, now) > DORMANT_DAYS)
    record = {
        "run_id": ctx.run_id,
        "split": split,
        "suite": suite,
        "case_id": case["case_id"],
        "turn": turn["turn"] if turn else None,
        "mode": mode,
        "N": n,
        "rep": rep,
        "method": ctx.method.name,
        "method_version": ctx.method.version,
        "label": label,
        "meta": meta,
        "dims": dims,
        "roster_size": len(roster_ids),
        "required_positions": {aid: i for i, aid in enumerate(roster_ids) if aid in required},
        "delegations": [
            {"agent_key": d.agent_key, "agent_name": d.agent_name, "instructions": d.instructions, "iteration": d.iteration}
            for d in (output.delegations if output else [])
        ],
        "history_effects": [{"tag": e.tag, "payload": e.payload} for e in (output.history_effects if output else [])],
        "invalid_calls": list(output.invalid_calls) if output else [],
        "outcomes": score.outcomes,
        "primary_outcome": score.primary_outcome,
        "primary_key": score.primary_key,
        "primary_agent_thread": score.primary_agent_thread,
        "tags": score.tags,
        "turn_correct": score.turn_correct,
        "turn_correct_lenient": score.turn_correct_lenient,
        "status": score.status,
        "loop_limit_hit": bool(output.loop_limit_hit) if output else False,
        "prev_thread": None,
        "recency_eligible": score.recency_eligible,
        "expected_threads": score.expected_threads,
        "agents_shown": len(roster_ids) - len(excluded),
        "excluded": excluded,
        "dormant_fraction": dormant / len(roster_ids) if roster_ids else 0.0,
        "has_candidates": has_candidates,
        "candidate_rank": rank,
        "error": error,
    }
    record.update(_call_summary(output))
    return record


def _scoring_context(label: dict, state: RoutingState, prev_thread: Optional[str], with_context: bool) -> ScoringContext:
    return ScoringContext(
        label=label,
        roster=[(a.agent_id, a.name) for a in state.roster],
        agent_thread=state.agent_thread(),
        canonical=state.canonical_map(),
        prev_thread=prev_thread,
        agent_context=copy.deepcopy(state.agent_context) if with_context else None,
    )


def _message_tag(message: dict) -> str:
    return "agent_message" if message["type"] == "agent" else "user_message"


# ---------------------------------------------------------------------------
# Suites


async def run_single_unit(ctx: RunContext, split: str, case: dict, n: int, rep: int) -> None:
    if ctx.capped:
        return
    fs = ctx.fixtures
    CALL_CONTEXT.set({"case_id": case["case_id"], "N": n, "mode": None, "rep": rep, "turn": None, "suite": "single", "split": split})
    roster_ids = roster_for_case(case, n, fs.rosters[split]["filler_order"], fs.agent_of_thread[split], fs.threads[split])
    now = case["message"]["timestamp"]
    state = initial_state(
        roster_ids=roster_ids,
        agents=fs.agents[split],
        agent_times=case["agent_times"],
        filler_age_days=fs.rosters[split]["filler_age_days"],
        now=now,
        history=case["history"],
    )
    sc = _scoring_context(case["label"], state, case["meta"].get("prev_thread"), with_context=False)
    output: Optional[RoutingOutput] = None
    error = None
    try:
        output = await ctx.method.route(state.routing_input(case["message"]["text"], case["message"]["type"]))
        score = score_turn(sc, output)
    except SpendCapReached:
        ctx.capped = True
        return
    except ApiError as exc:
        score = score_turn(sc, None, status=STATUS_API_ERROR)
        error = str(exc)
    dims = {
        "query_style": case["meta"].get("query_style"),
        "message_subtype": case["message"].get("subtype"),
        "label_kind": case["label"]["kind"],
        "target_position": case.get("target_position"),
        "target_age_bucket": case["meta"].get("target_age_bucket"),
        "name_descriptiveness": case["meta"].get("name_descriptiveness"),
        "history_type": case["history"].get("type"),
        "target_name_visible": case["meta"].get("target_name_visible"),
    }
    record = turn_record(
        ctx=ctx, split=split, suite="single", case=case, turn=None, mode=None, n=n, rep=rep,
        state=state, output=output, score=score, now=now, dims=dims, error=error,
    )
    record["prev_thread"] = case["meta"].get("prev_thread")
    ctx.turns.append(record)


def _carried_work(state: RoutingState, score: TurnScore, gold: dict) -> list[WorkAssignment]:
    ordered = sorted(score.distinct, key=lambda d: (d.agent_key != score.primary_key, d.order))
    work = []
    for d in ordered:
        text = (gold.get("result_text") or DONE_TEXT) if d.agent_key == score.primary_key else DONE_TEXT
        new_id = next_run_agent_id(state) if is_new_key(d.agent_key) else None
        work.append(WorkAssignment(d.agent_key, d.agent_name, d.instructions, text, new_id))
    return work


def _gold_work(ctx: RunContext, split: str, state: RoutingState, turn: dict) -> list[WorkAssignment]:
    label, gold = turn["label"], turn["gold"]
    instructions = turn["message"]["text"]
    kind = label["kind"]
    if kind in ("REUSE", "REUSE_ANY"):
        agent_id = state.canonical_agent(label["threads"][0])
        if agent_id is None:
            raise RuntimeError(f"{turn}: gold state has no agent for {label['threads'][0]}")
        name = state.by_id(agent_id).name
        return [WorkAssignment(agent_id, name, instructions, gold["result_text"])]
    if kind == "CREATE":
        gold_id = ctx.fixtures.agent_of_thread[split][label["new_thread"]]
        name = gold["create_name"]
        return [WorkAssignment(f"new:{name}", name, instructions, gold["result_text"], gold_id)]
    return []


def apply_gold_turn(ctx: RunContext, split: str, state: RoutingState, turn: dict) -> None:
    work = _gold_work(ctx, split, state, turn)
    apply_turn(
        state,
        message_tag=_message_tag(turn["message"]),
        message_text=turn["message"]["text"],
        timestamp=turn["timestamp"],
        effects=[("poke_reply", r) for r in turn["gold"].get("poke_replies") or []],
        work=work,
        primary_thread=turn["meta"].get("primary_thread"),
        result_reply=turn["gold"].get("result_reply") if work else None,
    )


def summarizer_call(ctx: RunContext, purpose: str = "summarizer"):
    async def call(system_prompt: str, messages: list[dict]) -> str:
        c = CALL_CONTEXT.get()
        seed = call_seed(purpose, c.get("case_id"), c.get("N"), c.get("mode"), c.get("rep"), c.get("turn"), None)
        response, _record = await ctx.client.chat(
            purpose=purpose,
            model=ctx.summarizer_model,
            messages=messages,
            system=system_prompt,
            provider=ctx.provider,
            seed=seed,
        )
        return message_content(response)

    return call


def sequence_end_stats(seq: dict, state: RoutingState, collided: set[str]) -> dict:
    threads_in_s: set[str] = set()
    for t in seq["turns"]:
        label = t["label"]
        if label["kind"] in ("REUSE", "REUSE_ANY"):
            threads_in_s.update(label["threads"])
        elif label["kind"] == "CREATE":
            threads_in_s.add(label["new_thread"])
    if any(a.thread_id == ORPHAN for a in state.roster):
        threads_in_s.add(ORPHAN)
    agents_in_s = [a for a in state.roster if a.thread_id in threads_in_s]
    counts: dict[str, int] = {}
    for a in agents_in_s:
        counts[a.thread_id] = counts.get(a.thread_id, 0) + 1
    extra = sum(max(0, c - 1) for t, c in counts.items() if t != ORPHAN) + counts.get(ORPHAN, 0)
    with_agents = len(counts)
    return {
        "threads_in_S": sorted(threads_in_s),
        "agents_in_S": len(agents_in_s),
        "extra_agents": extra,
        "duplicate_rate": extra / len(agents_in_s) if agents_in_s else 0.0,
        "inflation_ratio": len(agents_in_s) / with_agents if with_agents else None,
        "extra_agents_per_thread": extra / len(threads_in_s) if threads_in_s else 0.0,
        "created": state.created_count,
        "gold_created": sum(1 for t in seq["turns"] if t["label"]["kind"] == "CREATE"),
        "slug_collisions": len(collided),
    }


async def run_sequence_unit(ctx: RunContext, split: str, seq: dict, n: int, mode: str, rep: int) -> None:
    if ctx.capped:
        return
    fs = ctx.fixtures
    base_ctx = {"case_id": seq["case_id"], "N": n, "mode": mode, "rep": rep, "suite": "sequence", "split": split}
    CALL_CONTEXT.set({**base_ctx, "turn": None})
    roster_ids = roster_for_case(seq, n, fs.rosters[split]["filler_order"], fs.agent_of_thread[split], fs.threads[split])
    state = initial_state(
        roster_ids=roster_ids,
        agents=fs.agents[split],
        agent_times=seq["agent_times"],
        filler_age_days=fs.rosters[split]["filler_age_days"],
        now=seq["turns"][0]["timestamp"],
        history=seq["initial_history"],
    )
    aborted = False
    status = "ok"
    collided: set[str] = set()
    for turn in seq["turns"]:
        CALL_CONTEXT.set({**base_ctx, "turn": turn["turn"]})
        prev = state.prev_thread()
        sc = _scoring_context(turn["label"], state, prev, with_context=True)
        dims = {
            "query_style": turn["meta"].get("query_style"),
            "message_subtype": turn["message"].get("subtype"),
            "label_kind": turn["label"]["kind"],
            "turn_index": turn["turn"],
        }
        output: Optional[RoutingOutput] = None
        error = None
        if aborted:
            score = score_turn(sc, None, status=STATUS_API_ERROR)
            error = "sequence-run aborted after an earlier api_error"
        else:
            try:
                output = await ctx.method.route(state.routing_input(turn["message"]["text"], turn["message"]["type"]))
                score = score_turn(sc, output)
            except SpendCapReached:
                ctx.capped = True
                status = "capped"
                break
            except ApiError as exc:
                score = score_turn(sc, None, status=STATUS_API_ERROR)
                error = str(exc)
        record = turn_record(
            ctx=ctx, split=split, suite="sequence", case=seq, turn=turn, mode=mode, n=n, rep=rep,
            state=state, output=output, score=score, now=turn["timestamp"], dims=dims, error=error,
        )
        record["prev_thread"] = prev
        ctx.turns.append(record)

        if score.status == STATUS_API_ERROR:
            if mode == "carried":
                aborted = True
                status = "api_error"
                continue
            apply_gold_turn(ctx, split, state, turn)
        elif mode == "carried":
            for o in score.outcomes:
                if "slug_collision" in o.get("tags", []):
                    collided.add(o["agent_key"])
            apply_turn(
                state,
                message_tag=_message_tag(turn["message"]),
                message_text=turn["message"]["text"],
                timestamp=turn["timestamp"],
                effects=[(e.tag, e.payload) for e in output.history_effects],
                work=_carried_work(state, score, turn["gold"]),
                primary_thread=turn["meta"].get("primary_thread"),
                result_reply=turn["gold"].get("result_reply") if score.distinct else None,
            )
        else:
            apply_gold_turn(ctx, split, state, turn)

        try:
            await maybe_summarize(state, summarizer_call(ctx))
        except SpendCapReached:
            ctx.capped = True
            status = "capped"
            break
        except ApiError:
            # Production keeps going unsummarized when the summarizer fails; the next turn retries.
            ctx.summarizer_errors += 1

    seq_record = {
        "run_id": ctx.run_id,
        "split": split,
        "case_id": seq["case_id"],
        "N": n,
        "mode": mode,
        "rep": rep,
        "status": status,
        "roster_additions": [
            {"agent_id": a.agent_id, "name": a.name, "thread_id": a.thread_id}
            for a in state.roster
            if not a.seeded
        ],
        "agent_thread": state.agent_thread(),
    }
    if mode == "carried" and status == "ok":
        seq_record.update(sequence_end_stats(seq, state, collided))
    ctx.sequences.append(seq_record)


async def run_probe_unit(ctx: RunContext, split: str, case: dict) -> None:
    if ctx.capped:
        return
    CALL_CONTEXT.set({"case_id": case["case_id"], "N": 0, "mode": None, "rep": None, "turn": None, "suite": "token_probe", "split": split})
    state = initial_state(
        roster_ids=[],
        agents={},
        agent_times={},
        filler_age_days={},
        now=case["message"]["timestamp"],
        history=case["history"],
    )
    system_prompt, messages = build_messages(state.routing_input(case["message"]["text"], case["message"]["type"]))
    record = {
        "run_id": ctx.run_id, "split": split, "suite": "token_probe", "case_id": case["case_id"], "turn": None,
        "mode": None, "N": 0, "rep": None, "status": "ok", "prompt_tokens": None, "cost": 0.0, "call_ids": [], "error": None,
    }
    try:
        _response, call = await ctx.client.chat(
            purpose="token_probe",
            model=ctx.interaction_model,
            messages=messages,
            system=system_prompt,
            tools=TOOL_SCHEMAS,
            provider=ctx.provider,
            seed=call_seed("token_probe", case["case_id"], 0),
            extra={**ctx.extra_params, "max_tokens": 1},
        )
        record.update({"prompt_tokens": call.prompt_tokens, "cost": call.cost or 0.0, "call_ids": [call.call_id]})
    except SpendCapReached:
        ctx.capped = True
        return
    except ApiError as exc:
        record.update({"status": STATUS_API_ERROR, "error": str(exc)})
    ctx.turns.append(record)


async def run_all(ctx: RunContext) -> None:
    plan, fs = ctx.plan, ctx.fixtures
    tasks = []
    for split in plan.splits:
        singles = select_single(fs.single.get(split, []), plan.single_limit)
        seqs = select_sequences(fs.sequences.get(split, []), plan.sequence_limit)
        # names_only builds nothing here; later methods may index or cache agent records.
        await ctx.method.prepare(
            [
                AgentView(a["agent_id"], a["name"], tuple(WorkItem(**w) for w in a.get("work_log", [])), "", "")
                for a in fs.agents[split].values()
            ]
        )
        for seq in seqs:
            for n in plan.sequence_sizes[split]:
                for mode in plan.modes:
                    for rep in range(plan.sequence_reps):
                        tasks.append(run_sequence_unit(ctx, split, seq, n, mode, rep))
        for case in singles:
            for n in plan.single_sizes[split]:
                for rep in range(plan.single_reps):
                    tasks.append(run_single_unit(ctx, split, case, n, rep))
            if plan.token_probe:
                tasks.append(run_probe_unit(ctx, split, case))
    await asyncio.gather(*tasks)


# ---------------------------------------------------------------------------
# Results


def write_jsonl_gz(path: Path, rows: list[dict]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True, default=str) + "\n")


def read_jsonl_gz(path: Path) -> list[dict]:
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return [json.loads(line) for line in handle if line.strip()]


def sort_key(row: dict) -> tuple:
    return (
        row.get("split") or "",
        row.get("suite") or "",
        row.get("case_id") or "",
        row.get("N") or 0,
        row.get("mode") or "",
        row.get("rep") if row.get("rep") is not None else -1,
        row.get("turn") or 0,
    )


def cost_profile(turns: list[dict], sequences: list[dict], calls: list[dict]) -> dict:
    """Measured per-unit costs, used by later runs' pre-run estimates."""

    def mean(values: list[float]) -> Optional[float]:
        return sum(values) / len(values) if values else None

    ok = [t for t in turns if t.get("status") != STATUS_API_ERROR]
    single = [t["cost"] for t in ok if t["suite"] == "single"]
    seq = [t["cost"] for t in ok if t["suite"] == "sequence"]
    probes = [t["cost"] for t in ok if t["suite"] == "token_probe"]
    summarizer = sum(c.get("cost") or 0.0 for c in calls if c.get("purpose") == "summarizer")
    runs = len(sequences)
    routing_calls = [t["routing_calls"] for t in ok if t["suite"] in ("single", "sequence")]
    return {
        "single_turn_usd": mean(single),
        "sequence_turn_usd": mean(seq),
        "summarizer_per_sequence_run_usd": summarizer / runs if runs else None,
        "token_probe_usd": mean(probes),
        "routing_calls_per_turn": mean(routing_calls),
    }
