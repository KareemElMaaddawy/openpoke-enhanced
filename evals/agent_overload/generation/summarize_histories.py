"""Step 7: apply the production summarization rule to the long single-turn histories. Paid.

``python -m evals.agent_overload.generation.summarize_histories --dry-run``

For each summarized case, the first 100 raw entries go through the real
``build_summarization_prompt`` and the pinned summarizer model and provider, once.
The case stores the summary, ``last_index`` 99, and the remaining entries (at least
10, always including the drafted tail). The raw history stays in
``review/raw_histories/`` for audit.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Optional

from server.services.conversation.summarization.prompt_builder import build_summarization_prompt
from server.services.conversation.summarization.state import LogEntry

from ..harness.llm import message_content
from ..harness.spend import PlannedCalls
from ..harness.state import summarization_settings
from ..harness.util import call_seed
from .common import (
    SPLITS,
    GenerationError,
    StepContext,
    base_parser,
    load_config,
    read_rows,
    run_paid_step,
    write_rows,
)

NOMINAL_CASES = 54


def pending(fixtures_dir: Path, split: str) -> list[dict]:
    return [
        c
        for c in read_rows(fixtures_dir / f"cases.single.{split}.jsonl")
        if c["history"]["type"] == "summarized" and not c["history"].get("summary_text")
    ]


async def summarize_case(ctx: StepContext, case: dict, model: str, raw_dir: Path) -> Optional[dict]:
    threshold, tail_size = summarization_settings()
    raw = read_rows(raw_dir / f"{case['case_id']}.jsonl")
    if len(raw) < threshold + tail_size:
        raise GenerationError(f"{case['case_id']}: raw history has {len(raw)} entries, below {threshold + tail_size}")
    batch = [LogEntry(tag=e["tag"], payload=e["payload"], index=i, timestamp=e["timestamp"]) for i, e in enumerate(raw[:threshold])]
    prompt = build_summarization_prompt("", batch)
    response, record = await ctx.client.chat(
        purpose="fixture_summarizer",
        model=model,
        messages=prompt.messages,
        system=prompt.system_prompt,
        provider=ctx.provider_for(model),
        seed=call_seed("fixture_summarizer", case["case_id"]),
    )
    text = message_content(response)
    if not text:
        raise GenerationError(f"{case['case_id']}: summarizer returned no text")
    tail = case["history"].get("tail_entries") or []
    remaining = raw[threshold:]
    if tail and remaining[-len(tail):] != tail:
        raise GenerationError(f"{case['case_id']}: the drafted tail would be summarized away")
    case["history"] = {
        "type": "summarized",
        "summary_text": text,
        "last_index": threshold - 1,
        "entries": remaining,
        "raw_entry_count": len(raw),
    }
    case["provenance"]["summarized_by"] = ctx.provenance(model, record)
    return case


def main(argv: Optional[list[str]] = None) -> int:
    args = base_parser(__doc__).parse_args(argv)
    fixtures_dir: Path = args.fixtures_dir
    model = load_config(args.config)["models"]["summarizer"]
    have = all((fixtures_dir / f"cases.single.{s}.jsonl").exists() for s in SPLITS)
    count = sum(len(pending(fixtures_dir, s)) for s in SPLITS) if have else NOMINAL_CASES
    planned = [PlannedCalls("fixture_summarizer", model, count * 1.05, 6500, 1200, "100 entries per call, reasoning included")]
    extra = [
        "",
        f"histories to summarize: {count}" + ("" if have else " (nominal: cases files not found yet)"),
        f"writes: summary_text, last_index and remaining entries in {fixtures_dir}/cases.single.{{dev,test}}.jsonl",
    ]

    async def body(ctx: StepContext) -> None:
        raw_dir = fixtures_dir / "review" / "raw_histories"
        for split in SPLITS:
            path = fixtures_dir / f"cases.single.{split}.jsonl"
            cases = read_rows(path)
            todo = [c for c in cases if c["history"]["type"] == "summarized" and not c["history"].get("summary_text")]
            if any(not (raw_dir / f"{c['case_id']}.jsonl").exists() for c in todo):
                raise GenerationError("raw histories missing: run assemble_histories.py first")
            results = await asyncio.gather(*(summarize_case(ctx, c, model, raw_dir) for c in todo), return_exceptions=True)
            cap = None
            for r in results:
                if isinstance(r, BaseException):
                    if r.__class__.__name__ == "SpendCapReached":
                        cap = r
                    else:
                        print(f"warning: {r}")
            write_rows(path, cases)  # summarize_case updated the dicts in place
            print(f"{split}: {sum(1 for r in results if isinstance(r, dict))} histories summarized")
            if cap:
                raise cap

    return run_paid_step(
        args, step="summarize_histories", title=f"summarize_histories.py ({model}, production summarizer prompt)",
        planned=planned, body=body, models=[model], extra_lines=extra,
    )


if __name__ == "__main__":
    raise SystemExit(main())
