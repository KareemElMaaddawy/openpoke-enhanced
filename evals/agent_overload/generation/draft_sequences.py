"""Step 5: draft the multi-turn sequences (Sonnet 5.5). Paid.

``python -m evals.agent_overload.generation.draft_sequences --dry-run``

``planning.sequence_plans`` fixes each sequence's threads (three seeded threads, a
near-distractor pair, two threads created during the run) and its 12-turn plan
(labels, styles, message types, timestamps). Sonnet writes the messages and the
gold replies and results. The two created threads' agents are marked
``"seeded": false`` in ``agents.<split>.jsonl``; their frozen names are the gold
``create_name``. The initial history is assembled later by ``assemble_histories.py``.
"""

from __future__ import annotations

import asyncio
import json
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
    prompt_text,
    read_rows,
    render_prompt,
    run_paid_step,
    write_rows,
)
from .draft_cases import EMAIL_ALERT_PREFIX, STYLE_RULES, agent_names
from .planning import SequencePlan, sequence_plans

MAX_ATTEMPTS = 3
NOMINAL_SEQUENCES = 12


def _thread_line(t: dict, name: Optional[str]) -> str:
    agent = f'agent "{name}"' if name else "no agent yet"
    return f"- {t['thread_id']} ({agent}): {t['topic']}. First request: \"{t['opening_request']}\" -> {t['canned_result']}"


def describe(plan: SequencePlan, threads: dict, names: dict) -> dict[str, str]:
    topic = lambda t: threads[t]["topic"]  # noqa: E731
    history = "\n".join(_thread_line(threads[t], names[t]) for t in plan.history_threads)
    aged = "\n".join(_thread_line(threads[t], names[t]) for t in plan.aged)
    new = "\n".join(_thread_line(threads[t], None) + f" Its agent will be named \"{names[t]}\"." for t in plan.created.values())
    lines = []
    roles = {**plan.seeded, **plan.created}
    for turn in plan.turns:
        label = turn["label"]
        kind = label["kind"]
        message_type = {"user": "user message", "email_alert": "important-email notification"}[turn["subtype"]]
        if kind == "REUSE":
            t = label["threads"][0]
            what = f"REUSE of {t} ({topic(t)}, agent \"{names[t]}\")"
        elif kind == "REUSE_ANY":
            a, b = label["threads"]
            what = f"REUSE_ANY of {a} (agent \"{names[a]}\") and {b} (agent \"{names[b]}\")"
        elif kind == "CREATE":
            what = f"CREATE: new work on {label['new_thread']} ({topic(label['new_thread'])})"
        else:
            what = "NO_DELEGATION"
        guide = ""
        if kind == "REUSE" and turn["style"] in STYLE_RULES and turn["subtype"] == "user":
            guide = STYLE_RULES[turn["style"]]
        if kind == "REUSE" and turn["style"] == "near_distractor":
            p1 = plan.seeded["P1"]
            guide = (
                f"It's about {label['threads'][0]}, not the similar thread {p1} (agent \"{names[p1]}\"), which came up earlier; "
                "don't copy either agent name word for word."
            )
        if kind == "REUSE" and turn["subtype"] == "email_alert":
            guide = f"This is the email the user earlier asked the agent of {label['threads'][0]} to act on when it arrived."
        if kind == "REUSE" and turn["roles"] == ["C"] and turn["subtype"] == "user" and any(
            t["subtype"] == "email_alert" and t["label"].get("threads") == label.get("threads") for t in plan.turns
        ):
            guide += " In this request the user also asks the agent to act when a specific reply arrives (for example 'when they reply, confirm thursday')."
        if kind == "REUSE_ANY":
            a, b = label["threads"]
            guide = (
                f"The latest results from the agents of {a} and {b} earlier in this sequence must both mention the same "
                "object (an email, a confirmation, a document), and this message acts on that object."
            )
        if kind == "CREATE":
            guide = "A fresh request that no existing agent's work covers; a parallel agent must not be an equally valid choice."
        if kind == "NO_DELEGATION":
            if turn["subtype"] == "email_alert":
                about = f" related to {turn['primary_thread']} ({topic(turn['primary_thread'])})" if turn["primary_thread"] else ""
                guide = f"A notification{about} that only needs summarizing for the user; nothing should be done yet."
            else:
                guide = "Answered directly from visible context or small talk; no new work."
        lines.append(f"Turn {turn['turn']} at {turn['timestamp']}: {message_type}; label {what}; style {turn['style']}. {guide}".strip())
    return {"history_threads": history, "aged_threads": aged or "(none)", "new_threads": new, "turn_plan": "\n".join(lines)}


def validate(data: Any, plan: SequencePlan, names: dict) -> list[dict]:
    turns = data.get("turns") if isinstance(data, dict) else None
    if not isinstance(turns, list) or len(turns) != len(plan.turns):
        raise GenerationError(f"expected {len(plan.turns)} turns")
    by_number = {t.get("turn"): t for t in turns if isinstance(t, dict)}
    out = []
    for spec in plan.turns:
        t = by_number.get(spec["turn"])
        if t is None:
            raise GenerationError(f"turn {spec['turn']} missing")
        for field in ("message", "poke_reply"):
            if not isinstance(t.get(field), str) or not t[field].strip():
                raise GenerationError(f"turn {spec['turn']}: missing {field}")
        delegating = spec["label"]["kind"] != "NO_DELEGATION"
        if delegating and not all(isinstance(t.get(f), str) and t[f].strip() for f in ("result_text", "result_reply")):
            raise GenerationError(f"turn {spec['turn']}: delegating turn needs result_text and result_reply")
        message = t["message"].lower()
        if spec["style"] == "near_distractor" and names[plan.seeded["P1"]].lower() in message:
            raise GenerationError(f"turn {spec['turn']}: near-distractor message copies the distractor's name")
        if spec["style"] == "implicit_follow_up" and names[spec["label"]["threads"][0]].lower() in message:
            raise GenerationError(f"turn {spec['turn']}: implicit follow-up names the agent")
        out.append(t)
    return out


def build_sequence(plan: SequencePlan, turns: list[dict], ids: dict, names: dict, provenance: dict) -> dict:
    required = [ids[plan.seeded[r]] for r in ("A", "B", "C", "P1", "P2")]
    case_turns = []
    for spec, t in zip(plan.turns, turns):
        kind = spec["label"]["kind"]
        delegating = kind != "NO_DELEGATION"
        text = t["message"].strip()
        if spec["subtype"] == "email_alert":
            text = EMAIL_ALERT_PREFIX + text
        case_turns.append(
            {
                "turn": spec["turn"],
                "timestamp": spec["timestamp"],
                "message": {"type": "agent" if spec["subtype"] == "email_alert" else "user", "subtype": spec["subtype"], "text": text},
                "label": spec["label"],
                "meta": {"query_style": spec["style"], "primary_thread": spec["primary_thread"]},
                "gold": {
                    "create_name": names[spec["label"]["new_thread"]] if kind == "CREATE" else None,
                    "poke_replies": [t["poke_reply"].strip()],
                    "result_text": t["result_text"].strip() if delegating else None,
                    "result_reply": t["result_reply"].strip() if delegating else None,
                },
            }
        )
    return {
        "case_id": plan.case_id,
        "split": plan.split,
        "required_agents": required,
        "initial_history": {"summary_text": "", "last_index": -1, "entries": []},
        "agent_ages": {ids[t]: days for t, days in plan.aged.items()},
        "agent_times": None,
        "turns": case_turns,
        "provenance": {"drafted_by": provenance, "plan": plan.to_dict(), "cross_label": None, "review": None},
    }


async def draft_one(ctx: StepContext, plan: SequencePlan, threads: dict, ids: dict, names: dict) -> dict:
    prompt = render_prompt("draft_sequence.md", rules=prompt_text("labeling_rules.md"), **describe(plan, threads, names))
    last = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response, record = await ctx.client.chat(
            purpose="draft_sequence",
            model=GEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            extra={"max_tokens": 12000},
            fake_hint={"plan": plan.to_dict(), "names": names, "attempt": attempt},
        )
        try:
            turns = validate(extract_json(content_of(response)), plan, names)
        except GenerationError as exc:
            last = exc
            continue
        return build_sequence(plan, turns, ids, names, ctx.provenance(GEN_MODEL, record, attempt))
    raise GenerationError(f"{plan.case_id}: no valid draft after {MAX_ATTEMPTS} attempts ({last})")


def fake_sequence_responder(payload: dict, hint: Any) -> dict:
    from ..harness.llm import fake_message

    plan, names = hint["plan"], hint["names"]
    turns = []
    for spec in plan["turns"]:
        kind = spec["label"]["kind"]
        if kind == "REUSE" and spec["style"] == "implicit_follow_up":
            message = "ok do that one"
        elif kind in ("REUSE", "REUSE_ANY"):
            message = f"more on {names[spec['label']['threads'][0]].lower()}" if spec["style"] != "near_distractor" else "check the other one please"
        elif kind == "CREATE":
            message = f"new thing: {names[spec['label']['new_thread']].lower()}"
        else:
            message = "haha thanks"
        delegating = kind != "NO_DELEGATION"
        turns.append(
            {
                "turn": spec["turn"],
                "message": message,
                "poke_reply": "on it" if delegating else "anytime",
                "result_text": f"Done for turn {spec['turn']}." if delegating else None,
                "result_reply": f"All set ({spec['turn']})." if delegating else None,
            }
        )
    return fake_message(json.dumps({"turns": turns}))


def main(argv: Optional[list[str]] = None) -> int:
    args = base_parser(__doc__).parse_args(argv)
    fixtures_dir: Path = args.fixtures_dir
    have = all((fixtures_dir / f"agents.{s}.jsonl").exists() for s in SPLITS)
    todo: dict[str, list[SequencePlan]] = {}
    if have:
        for split in SPLITS:
            threads = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
            ids, _ = agent_names(fixtures_dir, split)
            done = {c["case_id"] for c in read_rows(fixtures_dir / f"cases.sequence.{split}.jsonl")}
            todo[split] = [p for p in sequence_plans(split, threads, ids) if p.case_id not in done]
    count = sum(len(v) for v in todo.values()) if have else NOMINAL_SEQUENCES
    planned = [PlannedCalls("draft_sequence", GEN_MODEL, count * 1.3, 3500, 4600, "one 12-turn sequence per call; output x1.75 per step 1")]
    extra = [
        "",
        f"sequences to draft: {count}" + ("" if have else " (nominal: agents files not found yet)"),
        f"writes: {fixtures_dir}/cases.sequence.{{dev,test}}.jsonl; marks created threads' agents seeded=false",
    ]

    async def body(ctx: StepContext) -> None:
        if not have:
            raise GenerationError("agents files not found: run name_agents.py first")
        for split in SPLITS:
            threads = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
            ids, names = agent_names(fixtures_dir, split)
            path = fixtures_dir / f"cases.sequence.{split}.jsonl"
            existing = {c["case_id"]: c for c in read_rows(path)}
            results = await asyncio.gather(*(draft_one(ctx, p, threads, ids, names) for p in todo[split]), return_exceptions=True)
            cap = None
            for plan, result in zip(todo[split], results):
                if isinstance(result, BaseException):
                    if result.__class__.__name__ == "SpendCapReached":
                        cap = result
                    else:
                        print(f"warning: {result}")
                    continue
                existing[plan.case_id] = result
            write_rows(path, [existing[k] for k in sorted(existing)])
            created = {t for c in existing.values() for t in c["provenance"]["plan"]["created"].values()}
            agents = read_rows(fixtures_dir / f"agents.{split}.jsonl")
            for a in agents:
                if a["thread_id"] in created:
                    a["seeded"] = False
            write_rows(fixtures_dir / f"agents.{split}.jsonl", agents)
            print(f"{split}: {len(existing)} sequences drafted")
            if cap:
                raise cap

    return run_paid_step(
        args, step="draft_sequences", title="draft_sequences.py (Sonnet 5.5)", planned=planned, body=body,
        models=[GEN_MODEL], fake_responders={"draft_sequence": fake_sequence_responder}, extra_lines=extra,
    )


if __name__ == "__main__":
    raise SystemExit(main())
