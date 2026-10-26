"""Step 2: agent names from the real interaction prompt, then filler cleaning and rosters. Paid.

``python -m evals.agent_overload.generation.name_agents --dry-run``

For each thread, the ``names_only`` loop runs the production prompt with the pinned
interaction model and provider, an empty roster and empty history, and the thread's
``opening_request`` as the new user message. The first ``send_message_to_agent``
name is kept. A turn with no delegation, or a name that matches or slug-collides
with one already taken in the split, is resampled (new seed), up to 3 attempts in
total; then the thread is dropped. Earlier thread ids win collisions.

When every thread is named or dropped, filler agents whose names resemble a case
agent's (slug ratio >= 0.6 or >= 2 shared non-stopword tokens) are removed, filler
is trimmed to 200 per split, and ``rosters.<split>.json`` is written with the
filler order and ages (both seeded with 20261025).
"""

from __future__ import annotations

import asyncio
import random
from collections import Counter
from pathlib import Path
from typing import Optional

from ..harness.llm import CALL_CONTEXT
from ..harness.methods.base import RoutingInput
from ..harness.methods.names_only import NamesOnlyMethod
from ..harness.spend import PlannedCalls
from ..harness.util import is_filler_conflict, slug
from .common import (
    SEED,
    SPLITS,
    GenerationError,
    StepContext,
    base_parser,
    load_config,
    read_json,
    read_rows,
    run_paid_step,
    write_json,
    write_rows,
)

MAX_ATTEMPTS = 3  # model failures (no delegation, or a colliding name) before a thread is dropped
MAX_TRIES_PER_RUN = 10  # API errors included; past this a thread stays pending until the next run
CHUNK = 40  # threads per save, in thread-id order
FILLER_PER_SPLIT = 200
NOMINAL_THREADS = 585
MODEL_FAILURES = ("no delegation", "collision")


def state_path(fixtures_dir: Path, split: str) -> Path:
    return fixtures_dir / "review" / "naming" / f"{split}.json"


def model_failures(entry: dict) -> int:
    """Attempts that count toward the 3-attempt budget. API errors don't: they say nothing about the model."""
    return sum(1 for h in entry.get("history", []) if h.get("reason") in MODEL_FAILURES)


def requeue(state: dict) -> int:
    """Put back threads that were dropped although fewer than 3 attempts were model failures."""
    count = 0
    for entry in state.values():
        if entry.get("status") == "dropped" and model_failures(entry) < MAX_ATTEMPTS:
            entry["status"] = "pending"
            count += 1
    return count


def pending_threads(fixtures_dir: Path, split: str) -> list[dict]:
    threads = read_rows(fixtures_dir / f"threads.{split}.jsonl")
    state = read_json(state_path(fixtures_dir, split), {})
    requeue(state)
    return [t for t in threads if state.get(t["thread_id"], {}).get("status") not in ("named", "dropped")]


def record_result(entry: dict, number: int, result, taken: set, taken_slugs: set, provenance) -> None:
    """Apply one attempt's result to a thread's naming state."""
    entry["attempts"] = number
    if isinstance(result, BaseException):
        entry["history"].append({"attempt": number, "name": None, "reason": f"error: {result}"})
    else:
        first, record = result
        if first is None:
            entry["history"].append({"attempt": number, "name": None, "reason": "no delegation"})
        elif first.agent_name in taken or slug(first.agent_name) in taken_slugs:
            entry["history"].append({"attempt": number, "name": first.agent_name, "reason": "collision"})
        else:
            entry.update(
                {
                    "status": "named",
                    "name": first.agent_name,
                    "instructions": first.instructions,
                    "provenance": provenance(record, number),
                }
            )
            entry["history"].append({"attempt": number, "name": first.agent_name, "reason": "accepted"})
            taken.add(first.agent_name)
            taken_slugs.add(slug(first.agent_name))
    if entry["status"] == "pending" and model_failures(entry) >= MAX_ATTEMPTS:
        entry["status"] = "dropped"


async def name_split(ctx: StepContext, method: NamesOnlyMethod, fixtures_dir: Path, split: str) -> None:
    threads = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
    path = state_path(fixtures_dir, split)
    state: dict = read_json(path, {})
    requeued = requeue(state)
    if requeued:
        print(f"{split}: re-queued {requeued} threads dropped only because of API errors")
    taken = {v["name"] for v in state.values() if v.get("status") == "named"}
    taken_slugs = {slug(n) for n in taken}
    model = ctx.config["models"]["interaction"]

    async def attempt(thread: dict, number: int):
        CALL_CONTEXT.set({"case_id": thread["thread_id"], "N": 0, "mode": None, "rep": number, "turn": None})
        inp = RoutingInput(roster=(), summary_text="", entries=(), message_text=thread["opening_request"], message_type="user")
        out = await method.route(inp)
        first = out.delegations[0] if out.delegations else None
        record = out.llm_calls[0] if out.llm_calls else None
        return first, record

    tries: Counter = Counter()  # this run only, so a later rerun gets a fresh allowance

    def open_threads() -> list[str]:
        return sorted(
            t for t in threads if state.get(t, {}).get("status", "pending") == "pending" and tries[t] < MAX_TRIES_PER_RUN
        )

    while True:
        pending = open_threads()
        if not pending:
            break
        round_errors = 0
        for start in range(0, len(pending), CHUNK):
            chunk = pending[start : start + CHUNK]
            numbers = {t: state.get(t, {}).get("attempts", 0) + 1 for t in chunk}
            tries.update(chunk)
            results = await asyncio.gather(*(attempt(threads[t], numbers[t]) for t in chunk), return_exceptions=True)
            cap_error = None
            for thread_id, result in zip(chunk, results):  # id order, so earlier ids win collisions
                if isinstance(result, BaseException) and result.__class__.__name__ == "SpendCapReached":
                    cap_error = result
                    continue
                entry = state.setdefault(thread_id, {"status": "pending", "attempts": 0, "history": []})
                round_errors += isinstance(result, BaseException)
                record_result(entry, numbers[thread_id], result, taken, taken_slugs, lambda r, n: ctx.provenance(model, r, n))
            write_json(path, state)
            statuses = Counter(state.get(t, {}).get("status", "pending") for t in threads)
            print(f"{split}: {statuses['named']} named, {statuses['dropped']} dropped, {statuses['pending']} pending")
            if cap_error is not None:
                raise cap_error
        if round_errors == len(pending):
            print(f"{split}: every attempt in this round failed with an API error; stopping. Rerun later to continue.")
            break
    stuck = [t for t in threads if state.get(t, {}).get("status", "pending") == "pending"]
    if stuck:
        print(f"{split}: {len(stuck)} threads still pending after repeated API errors; rerun this step to continue.")


def write_agents_and_rosters(fixtures_dir: Path) -> list[str]:
    """Agents files, filler cleaning and rosters. Returns problems (empty when complete)."""
    problems = []
    for split in SPLITS:
        threads = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
        state = read_json(state_path(fixtures_dir, split), {})
        requeue(state)
        if any(state.get(t, {}).get("status") not in ("named", "dropped") for t in threads):
            problems.append(f"{split}: some threads are not named yet (rerun this step)")
            continue
        previous = {a["agent_id"]: a for a in read_rows(fixtures_dir / f"agents.{split}.jsonl")}
        agents = []
        for thread_id in sorted(threads):
            entry = state[thread_id]
            if entry["status"] != "named":
                continue
            agent_id = "a-" + thread_id[2:]
            prior = previous.get(agent_id, {})
            agents.append(
                {
                    "agent_id": agent_id,
                    "thread_id": thread_id,
                    "role": threads[thread_id]["role"],
                    "name": entry["name"],
                    "descriptiveness": prior.get("descriptiveness"),
                    "seeded": prior.get("seeded", True),
                    "work_log": [{"instructions": entry["instructions"], "result": threads[thread_id]["canned_result"]}],
                    "name_source": entry["provenance"],
                }
            )
        case_names = [a["name"] for a in agents if a["role"] == "case"]
        kept, removed = [], []
        for agent in (a for a in agents if a["role"] == "filler"):
            conflicts = [c for c in case_names if is_filler_conflict(agent["name"], c)]
            if conflicts:
                removed.append({"agent_id": agent["agent_id"], "name": agent["name"], "reason": "similar to case agent", "conflicts": conflicts})
            else:
                kept.append(agent)
        for agent in kept[FILLER_PER_SPLIT:]:
            removed.append({"agent_id": agent["agent_id"], "name": agent["name"], "reason": "trimmed to 200"})
        kept = kept[:FILLER_PER_SPLIT]
        dropped_threads = [t for t in sorted(threads) if state[t]["status"] == "dropped"]
        write_json(
            fixtures_dir / "review" / f"filler_cleaning.{split}.json",
            {"removed": removed, "kept": len(kept), "dropped_threads": dropped_threads},
        )
        final = [a for a in agents if a["role"] == "case"] + kept
        write_rows(fixtures_dir / f"agents.{split}.jsonl", sorted(final, key=lambda a: a["agent_id"]))
        if len(kept) < FILLER_PER_SPLIT:
            problems.append(
                f"{split}: only {len(kept)} filler agents after cleaning; run gen_threads.py --top-up-filler "
                f"{FILLER_PER_SPLIT - len(kept) + 5} --split {split}, then this step again"
            )
            continue
        ids = sorted(a["agent_id"] for a in kept)
        order = list(ids)
        random.Random(SEED).shuffle(order)
        age_rng = random.Random(SEED)
        buckets = [(0.0, 3.0)] * 60 + [(4.0, 14.0)] * 60 + [(15.0, 60.0)] * 80
        age_rng.shuffle(buckets)
        ages = {aid: round(age_rng.uniform(lo, hi), 2) for aid, (lo, hi) in zip(ids, buckets)}
        write_json(fixtures_dir / f"rosters.{split}.json", {"filler_order": order, "filler_age_days": ages})
        print(f"{split}: {len([a for a in final if a['role'] == 'case'])} case agents, {len(kept)} filler, "
              f"{len(removed)} filler removed, {len(dropped_threads)} threads dropped")
    return problems


def main(argv: Optional[list[str]] = None) -> int:
    args = parse(argv)
    fixtures_dir: Path = args.fixtures_dir
    config = load_config(args.config)
    model = config["models"]["interaction"]
    have_threads = all((fixtures_dir / f"threads.{s}.jsonl").exists() for s in SPLITS)
    pending = sum(len(pending_threads(fixtures_dir, s)) for s in SPLITS) if have_threads else NOMINAL_THREADS
    planned = [PlannedCalls("naming", model, pending * 3.2 * 1.1, 2000, 70, "measured: about 3.2 calls per loop, 2,000 prompt tokens")]
    extra = [
        "",
        f"threads to name: {pending}" + ("" if have_threads else " (nominal: threads files not found yet)"),
        f"provider: {config['models']['provider']}",
        f"writes: {fixtures_dir}/agents.{{dev,test}}.jsonl, rosters.{{dev,test}}.json, review/naming/, review/filler_cleaning.*.json",
    ]

    async def body(ctx: StepContext) -> None:
        if not have_threads:
            raise GenerationError("threads files not found: run gen_threads.py first")
        method = NamesOnlyMethod(
            ctx.client, model=model, provider=ctx.provider_for(model),
            extra_params=config["models"].get("extra_params") or {}, purpose="naming",
        )
        for split in SPLITS:
            await name_split(ctx, method, fixtures_dir, split)
        problems = write_agents_and_rosters(fixtures_dir)
        for p in problems:
            print("warning: " + p)

    return run_paid_step(
        args, step="name_agents", title=f"name_agents.py ({model} through the production prompt)",
        planned=planned, body=body, models=[model], extra_lines=extra,
    )


def parse(argv):
    return base_parser(__doc__).parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
