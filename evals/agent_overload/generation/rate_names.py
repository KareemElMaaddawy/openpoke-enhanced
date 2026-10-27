"""Step 3: rate each agent name as specific, partial or generic (Sonnet 5.5). Paid.

``python -m evals.agent_overload.generation.rate_names --dry-run``

Batches of 40 agents per call. Ratings go into ``descriptiveness`` in
``agents.<split>.jsonl``; whatever mix comes out is the natural mix and is reported,
not forced. Only unrated agents are sent, so a rerun continues where it stopped.
"""

from __future__ import annotations

import asyncio
import json
from collections import Counter
from pathlib import Path
from typing import Any, Optional

from ..harness.spend import PlannedCalls
from .common import (
    GEN_MODEL,
    SPLITS,
    GenerationError,
    StepContext,
    base_parser,
    content_of,
    extract_json,
    read_rows,
    render_prompt,
    run_paid_step,
    write_json,
    write_rows,
)

BATCH = 40
RATINGS = ("specific", "partial", "generic")
NOMINAL_AGENTS = 565


def unrated(fixtures_dir: Path, split: str) -> list[dict]:
    return [a for a in read_rows(fixtures_dir / f"agents.{split}.jsonl") if a.get("descriptiveness") not in RATINGS]


def validate(data: Any, ids: list[str]) -> dict[str, str]:
    rows = data.get("ratings") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise GenerationError("no ratings list")
    out = {r.get("agent_id"): r.get("rating") for r in rows if isinstance(r, dict)}
    missing = [i for i in ids if out.get(i) not in RATINGS]
    if missing:
        raise GenerationError(f"{len(missing)} items missing or invalid")
    return {i: out[i] for i in ids}


async def rate_batch(ctx: StepContext, batch: list[dict], threads: dict[str, dict]) -> tuple[dict[str, str], dict]:
    items = "\n".join(
        json.dumps(
            {
                "agent_id": a["agent_id"],
                "name": a["name"],
                "topic": threads[a["thread_id"]]["topic"],
                "request": threads[a["thread_id"]]["opening_request"],
            },
            ensure_ascii=False,
        )
        for a in batch
    )
    prompt = render_prompt("rate_names.md", items=items)
    ids = [a["agent_id"] for a in batch]
    last = None
    for attempt in range(1, 4):
        response, record = await ctx.client.chat(
            purpose="rate_names",
            model=GEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            extra={"max_tokens": 4000},
            fake_hint={"ids": ids, "names": [a["name"] for a in batch], "attempt": attempt},
        )
        try:
            return validate(extract_json(content_of(response)), ids), ctx.provenance(GEN_MODEL, record, attempt)
        except GenerationError as exc:
            last = exc
    raise GenerationError(f"rating batch failed after 3 attempts ({last})")


def fake_rate_responder(payload: dict, hint: Any) -> dict:
    from ..harness.llm import fake_message

    from ..harness.util import sha256_hex

    ratings = [{"agent_id": i, "rating": RATINGS[int(sha256_hex(n)[:2], 16) % 3]} for i, n in zip(hint["ids"], hint["names"])]
    return fake_message(json.dumps({"ratings": ratings}))


def main(argv: Optional[list[str]] = None) -> int:
    args = base_parser(__doc__).parse_args(argv)
    fixtures_dir: Path = args.fixtures_dir
    have = all((fixtures_dir / f"agents.{s}.jsonl").exists() for s in SPLITS)
    todo = sum(len(unrated(fixtures_dir, s)) for s in SPLITS) if have else NOMINAL_AGENTS
    batches = -(-todo // BATCH) if todo else 0
    planned = [PlannedCalls("rate_names", GEN_MODEL, batches * 1.1, 2800, 1300, f"{BATCH} names per call")]
    extra = [
        "",
        f"agents to rate: {todo}" + ("" if have else " (nominal: agents files not found yet)"),
        f"writes: descriptiveness in {fixtures_dir}/agents.{{dev,test}}.jsonl, review/name_ratings.json",
    ]

    async def body(ctx: StepContext) -> None:
        if not have:
            raise GenerationError("agents files not found: run name_agents.py first")
        mix: dict[str, Counter] = {}
        for split in SPLITS:
            agents = read_rows(fixtures_dir / f"agents.{split}.jsonl")
            threads = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
            todo_agents = [a for a in agents if a.get("descriptiveness") not in RATINGS]
            batches = [todo_agents[i : i + BATCH] for i in range(0, len(todo_agents), BATCH)]
            results = await asyncio.gather(*(rate_batch(ctx, b, threads) for b in batches), return_exceptions=True)
            ratings: dict[str, str] = {}
            cap = None
            for r in results:
                if isinstance(r, BaseException):
                    if r.__class__.__name__ == "SpendCapReached":
                        cap = r
                    else:
                        print(f"warning: {r}")
                    continue
                ratings.update(r[0])
            for a in agents:
                if a["agent_id"] in ratings:
                    a["descriptiveness"] = ratings[a["agent_id"]]
            write_rows(fixtures_dir / f"agents.{split}.jsonl", agents)
            mix[split] = Counter(a.get("descriptiveness") or "unrated" for a in agents if a["role"] == "case")
            if cap:
                raise cap
        write_json(fixtures_dir / "review" / "name_ratings.json", {s: dict(c) for s, c in mix.items()})
        print("case-agent descriptiveness mix: " + json.dumps({s: dict(c) for s, c in mix.items()}))

    return run_paid_step(
        args, step="rate_names", title="rate_names.py (Sonnet 5.5)", planned=planned, body=body,
        models=[GEN_MODEL], fake_responders={"rate_names": fake_rate_responder}, extra_lines=extra,
    )


if __name__ == "__main__":
    raise SystemExit(main())
