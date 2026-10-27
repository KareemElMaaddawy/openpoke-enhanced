"""Step 8: blind second labels from Gemini 3.8 Flash. Paid.

``python -m evals.agent_overload.generation.cross_label --dry-run``

The labeler gets the labeling rules and the output format as its system prompt, and
exactly what the interaction agent would see at N=200 as the user message (the
production-rendered conversation history, active agents and new message), without
the draft's label. Sequences are labeled turn by turn from the gold state; when the
gold state crosses the summarization threshold it's summarized with one real
summarizer call (``label_summarizer``), as at run time. Agent names in the answer
are mapped back to threads; agreement means the same label kind and, for REUSE and
REUSE_ANY, the same set of threads.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

from ..harness.llm import CALL_CONTEXT, message_content
from ..harness.methods.names_only import build_messages
from ..harness.rosters import roster_for_case
from ..harness.runner import apply_gold
from ..harness.spend import PlannedCalls
from ..harness.state import RoutingState, initial_state, maybe_summarize
from ..harness.util import call_seed
from .common import (
    LABEL_MODEL,
    SPLITS,
    GenerationError,
    StepContext,
    base_parser,
    content_of,
    extract_json,
    load_config,
    prompt_text,
    read_json,
    read_rows,
    run_paid_step,
    write_rows,
)

LABEL_N = 200
KINDS = ("REUSE", "REUSE_ANY", "CREATE", "NO_DELEGATION")
NOMINAL = {"single": 180, "sequence_turns": 144, "sequences": 12}


def labeler_system_prompt() -> str:
    return prompt_text("labeling_rules.md").strip() + "\n\n" + prompt_text("cross_label.md").strip()


def label_state(case: dict, fixtures: dict, split: str, history: dict, now: str) -> RoutingState:
    """State at N=200; agent times don't matter for labeling, so required agents use ``now``."""
    roster_ids = roster_for_case(case, LABEL_N, fixtures["rosters"][split]["filler_order"], fixtures["agent_of_thread"][split], fixtures["threads"][split])
    times = {a: {"last_active": now, "created_at": now} for a in case["required_agents"]}
    return initial_state(
        roster_ids=roster_ids,
        agents=fixtures["agents"][split],
        agent_times=times,
        filler_age_days=fixtures["rosters"][split]["filler_age_days"],
        now=now,
        history=history,
    )


def parse_label(data: Any, state: RoutingState) -> dict:
    if not isinstance(data, dict) or data.get("label") not in KINDS:
        raise GenerationError("label missing or unknown")
    kind = data["label"]
    names = data.get("agents") or []
    if not isinstance(names, list):
        raise GenerationError("agents is not a list")
    threads = state.agent_thread()
    agent_ids = []
    for name in names:
        agent_id = state.resolve_name(name) if isinstance(name, str) else None
        if agent_id is None:
            raise GenerationError(f"unknown agent name {name!r}")
        agent_ids.append(agent_id)
    if kind == "REUSE" and len(agent_ids) != 1:
        raise GenerationError("REUSE needs exactly one agent")
    if kind == "REUSE_ANY" and len(agent_ids) < 2:
        raise GenerationError("REUSE_ANY needs two or more agents")
    label: dict = {"kind": kind}
    if kind in ("REUSE", "REUSE_ANY"):
        label["threads"] = sorted({threads[a] for a in agent_ids})
        if kind == "REUSE_ANY" and len(label["threads"]) == 1:
            label = {"kind": "REUSE", "threads": label["threads"]}
    return {"label": label, "agents": names, "reason": str(data.get("reason", ""))}


def labels_agree(draft: dict, other: dict) -> bool:
    if draft["kind"] != other["kind"]:
        return False
    if draft["kind"] in ("REUSE", "REUSE_ANY"):
        return sorted(draft["threads"]) == sorted(other["threads"])
    return True


async def ask_labeler(ctx: StepContext, state: RoutingState, message: dict, hint: dict) -> dict:
    _system, messages = build_messages(state.routing_input(message["text"], message["type"]))
    last = None
    for attempt in range(1, 3):
        response, record = await ctx.client.chat(
            purpose="cross_label",
            model=LABEL_MODEL,
            messages=messages,
            system=labeler_system_prompt(),
            fake_hint={**hint, "attempt": attempt, "names": state.agent_names(), "threads": state.agent_thread()},
        )
        try:
            parsed = parse_label(extract_json(content_of(response)), state)
        except GenerationError as exc:
            last = exc
            continue
        parsed["provenance"] = ctx.provenance(LABEL_MODEL, record, attempt)
        return parsed
    return {"label": {"kind": "INVALID"}, "agents": [], "reason": f"no valid answer: {last}", "provenance": None}


async def label_single(ctx: StepContext, case: dict, fixtures: dict, split: str) -> dict:
    state = label_state(case, fixtures, split, case["history"], case["message"]["timestamp"])
    result = await ask_labeler(ctx, state, case["message"], {"draft": case["label"]})
    result["agreed"] = labels_agree(case["label"], result["label"])
    result["model"] = LABEL_MODEL
    case["provenance"]["cross_label"] = result
    return case


async def label_sequence(ctx: StepContext, seq: dict, fixtures: dict, split: str, summarizer: str) -> dict:
    CALL_CONTEXT.set({"case_id": seq["case_id"], "N": LABEL_N, "mode": "gold", "rep": None, "turn": None})
    state = label_state(seq, fixtures, split, seq["initial_history"], seq["turns"][0]["timestamp"])
    turns: dict[str, dict] = {}

    async def summarize(system_prompt: str, messages: list[dict]) -> str:
        c = CALL_CONTEXT.get()
        response, _ = await ctx.client.chat(
            purpose="label_summarizer",
            model=summarizer,
            messages=messages,
            system=system_prompt,
            provider=ctx.provider_for(summarizer),
            seed=call_seed("label_summarizer", c.get("case_id"), LABEL_N, "gold", None, c.get("turn")),
        )
        return message_content(response)

    for turn in seq["turns"]:
        CALL_CONTEXT.set({"case_id": seq["case_id"], "N": LABEL_N, "mode": "gold", "rep": None, "turn": turn["turn"]})
        result = await ask_labeler(ctx, state, turn["message"], {"draft": turn["label"]})
        result["agreed"] = labels_agree(turn["label"], result["label"])
        turns[str(turn["turn"])] = result
        apply_gold(state, turn, fixtures["agent_of_thread"][split])
        await maybe_summarize(state, summarize)
    seq["provenance"]["cross_label"] = {"model": LABEL_MODEL, "turns": turns}
    return seq


def load_fixture_maps(fixtures_dir: Path) -> dict:
    out: dict = {"threads": {}, "agents": {}, "agent_of_thread": {}, "rosters": {}}
    for split in SPLITS:
        out["threads"][split] = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
        agents = read_rows(fixtures_dir / f"agents.{split}.jsonl")
        out["agents"][split] = {a["agent_id"]: a for a in agents}
        out["agent_of_thread"][split] = {a["thread_id"]: a["agent_id"] for a in agents}
        out["rosters"][split] = read_json(fixtures_dir / f"rosters.{split}.json")
    return out


def fake_label_responder(payload: dict, hint: Any) -> dict:
    """Agrees with the draft about 90% of the time, so the review flow gets exercised."""
    from ..harness.llm import fake_message
    from ..harness.util import sha256_hex

    draft = hint["draft"]
    by_thread: dict[str, str] = {}
    for agent_id, thread in hint["threads"].items():
        by_thread.setdefault(thread, hint["names"][agent_id])
    disagree = int(sha256_hex(json.dumps(payload["messages"][-1]["content"]))[:4], 16) % 10 == 0
    if disagree:
        answer = {"label": "CREATE" if draft["kind"] != "CREATE" else "NO_DELEGATION", "agents": [], "reason": "fake disagreement"}
    elif draft["kind"] in ("REUSE", "REUSE_ANY"):
        answer = {"label": draft["kind"], "agents": [by_thread[t] for t in draft["threads"] if t in by_thread], "reason": "fake"}
    else:
        answer = {"label": draft["kind"], "agents": [], "reason": "fake"}
    return fake_message(json.dumps(answer))


def main(argv: Optional[list[str]] = None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--only", default="", help="comma-separated case ids to (re)label")
    args = parser.parse_args(argv)
    fixtures_dir: Path = args.fixtures_dir
    only = {c.strip() for c in args.only.split(",") if c.strip()}
    summarizer = load_config(args.config)["models"]["summarizer"]

    def wanted(case: dict) -> bool:
        return case["case_id"] in only if only else case["provenance"].get("cross_label") is None

    have = all((fixtures_dir / f"cases.single.{s}.jsonl").exists() for s in SPLITS)
    if have:
        singles = sum(1 for s in SPLITS for c in read_rows(fixtures_dir / f"cases.single.{s}.jsonl") if wanted(c))
        seqs = [c for s in SPLITS for c in read_rows(fixtures_dir / f"cases.sequence.{s}.jsonl") if wanted(c)]
        seq_turns = sum(len(c["turns"]) for c in seqs)
        n_seqs = len(seqs)
    else:
        singles, seq_turns, n_seqs = NOMINAL["single"], NOMINAL["sequence_turns"], NOMINAL["sequences"]
    planned = [
        PlannedCalls("cross_label (single)", LABEL_MODEL, singles * 1.05, 5600, 700, "N=200 prompt, reasoning included"),
        PlannedCalls("cross_label (sequence)", LABEL_MODEL, seq_turns * 1.05, 6500, 700, "one per turn, from the gold state"),
        PlannedCalls("label_summarizer", summarizer, n_seqs, 6500, 1200, "once per sequence"),
    ]
    extra = [
        "",
        f"single cases {singles}, sequence turns {seq_turns} ({n_seqs} sequences)" + ("" if have else " (nominal)"),
        f"writes: provenance.cross_label in {fixtures_dir}/cases.*.jsonl and review/cross_label_summary.json",
    ]

    async def body(ctx: StepContext) -> None:
        if not have:
            raise GenerationError("cases not found: run the drafting steps first")
        fixtures = load_fixture_maps(fixtures_dir)
        summary = {}
        for split in SPLITS:
            single_path = fixtures_dir / f"cases.single.{split}.jsonl"
            seq_path = fixtures_dir / f"cases.sequence.{split}.jsonl"
            singles_all = read_rows(single_path)
            seqs_all = read_rows(seq_path)
            if any(c["history"]["type"] == "summarized" and not c["history"].get("summary_text") for c in singles_all if wanted(c)):
                raise GenerationError("some summarized histories aren't summarized yet: run summarize_histories.py first")
            if any(not s["initial_history"]["entries"] for s in seqs_all if wanted(s)):
                raise GenerationError("sequence histories missing: run assemble_histories.py first")
            tasks = [label_single(ctx, c, fixtures, split) for c in singles_all if wanted(c)]
            tasks += [label_sequence(ctx, s, fixtures, split, summarizer) for s in seqs_all if wanted(s)]
            results = await asyncio.gather(*tasks, return_exceptions=True)
            cap = None
            for r in results:
                if isinstance(r, BaseException):
                    if r.__class__.__name__ == "SpendCapReached":
                        cap = r
                    else:
                        print(f"warning: {r!r}")
            write_rows(single_path, singles_all)
            write_rows(seq_path, seqs_all)
            labeled = [c["provenance"]["cross_label"] for c in singles_all if c["provenance"].get("cross_label")]
            turn_labels = [t for s in seqs_all if s["provenance"].get("cross_label") for t in s["provenance"]["cross_label"]["turns"].values()]
            summary[split] = {
                "single_labeled": len(labeled),
                "single_agreed": sum(1 for x in labeled if x["agreed"]),
                "sequence_turns_labeled": len(turn_labels),
                "sequence_turns_agreed": sum(1 for x in turn_labels if x["agreed"]),
                "invalid": sum(1 for x in labeled + turn_labels if x["label"]["kind"] == "INVALID"),
            }
            if cap:
                raise cap
        from .common import write_json

        write_json(fixtures_dir / "review" / "cross_label_summary.json", summary)
        print("agreement: " + json.dumps(summary))

    return run_paid_step(
        args, step="cross_label", title="cross_label.py (Gemini 3.8 Flash, blind second labels)", planned=planned,
        body=body, models=[LABEL_MODEL, summarizer], fake_responders={"cross_label": fake_label_responder}, extra_lines=extra,
    )


if __name__ == "__main__":
    raise SystemExit(main())
