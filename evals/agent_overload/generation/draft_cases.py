"""Step 4: draft the single-turn cases (Sonnet 5.5). Paid.

``python -m evals.agent_overload.generation.draft_cases --dry-run``

``planning.case_plans`` fixes every quota-relevant choice per case (label, style,
message subtype, history type, position, old-thread cases, which threads appear and
in what order, the case's timestamp and agent ages). Sonnet writes only the text:
the tail of the conversation and the new message. Code checks the draft against
the plan (schema, threads used, ordering, forbidden names, 4 to 16 entries), renders
result lines with the exact frozen agent names, and assigns timestamps. A rejected
draft is redrafted, up to 3 attempts. ``--redraft s-test-0007,...`` replaces chosen
cases (for example after review), passing the reviewer's note to the drafter.
"""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from pathlib import Path
from typing import Any, Optional

from ..harness.spend import PlannedCalls
from ..harness.state import format_batch_payload
from ..harness.util import format_ts, parse_ts
from .common import (
    GEN_MODEL,
    SPLITS,
    GenerationError,
    StepContext,
    base_parser,
    content_of,
    extract_json,
    prompt_text,
    read_json,
    read_rows,
    render_prompt,
    run_paid_step,
    write_rows,
)
from .planning import CasePlan, case_plans, rng_for

MAX_ATTEMPTS = 3
EMAIL_ALERT_PREFIX = "Important email watcher notification:\n"
NOMINAL_CASES = 180

STYLE_RULES = {
    "explicit": "It names the target thread's topic in words close to the target agent's name.",
    "paraphrased": "It refers to the target thread with little word overlap with the target agent's name: paraphrase, or use a detail from the result instead of the topic words.",
    "implicit_follow_up": "It points at the most recent result without naming the topic (for example 'reply to that', 'move it to friday', 'forward it to my accountant'), so it can only be resolved through the history.",
}


def agent_names(fixtures_dir: Path, split: str) -> tuple[dict[str, str], dict[str, str]]:
    agents = read_rows(fixtures_dir / f"agents.{split}.jsonl")
    return {a["thread_id"]: a["agent_id"] for a in agents}, {a["thread_id"]: a["name"] for a in agents}


def _thread_text(t: dict, name: Optional[str], role: str) -> str:
    ups = "; ".join(f"\"{u['request']}\" -> {u['result']}" for u in t.get("follow_ups", []))
    agent = f'agent "{name}"' if name else "no agent yet"
    return (
        f"- {t['thread_id']} ({role}; {agent})\n"
        f"  topic: {t['topic']}\n"
        f"  first request: \"{t['opening_request']}\" -> {t['canned_result']}\n"
        + (f"  later requests: {ups}\n" if ups else "")
    )


def describe(plan: CasePlan, threads: dict[str, dict], names: dict[str, str], note: Optional[str] = None) -> dict[str, str]:
    """The plan, thread, tail and message sections of the drafting prompt."""
    topic = lambda t: threads[t]["topic"]  # noqa: E731
    lines = []
    if plan.kind == "REUSE":
        t = plan.targets[0]
        lines.append(f"- Correct label: REUSE of thread {t} ({topic(t)}), whose agent is named \"{names[t]}\".")
    elif plan.kind == "REUSE_ANY":
        a, b = plan.targets
        lines.append(f"- Correct label: REUSE_ANY of threads {a} (agent \"{names[a]}\") and {b} (agent \"{names[b]}\").")
    elif plan.kind == "CREATE":
        lines.append(f"- Correct label: CREATE: new work on thread {plan.new_thread} ({topic(plan.new_thread)}), which no visible agent covers.")
    else:
        lines.append("- Correct label: NO_DELEGATION.")
    lines.append(f"- Query style: {plan.style}.")
    message_type = {"user": "a user message", "execution_result": "an execution agent's result", "email_alert": "an important-email notification"}[plan.subtype]
    lines.append(f"- The new message is {message_type}.")
    if plan.distractor:
        lines.append(
            f"- The agent list also contains \"{names[plan.distractor]}\" for thread {plan.distractor} ({topic(plan.distractor)}), "
            "which looks similar but is different work."
        )
    if plan.old:
        lines.append("- The target agent was last used weeks ago, so the target thread doesn't appear in the recent conversation at all.")
    lines.append("- The agent list will also hold up to 200 unrelated agents.")
    if note:
        lines.append(f"- A reviewer flagged an earlier draft of this case: {note} Avoid that problem.")

    roles = {}
    for t in plan.targets:
        roles[t] = "target"
    if plan.distractor:
        roles[plan.distractor] = "near-distractor"
    if plan.new_thread:
        roles[plan.new_thread] = "new work for the message"
    for t in plan.history_threads:
        roles.setdefault(t, "context")
    thread_text = "\n".join(
        _thread_text(threads[t], names.get(t) if t != plan.new_thread else None, role) for t, role in roles.items()
    )

    tail = [
        "- Use delegated exchanges for exactly these threads, each at least once: "
        + ", ".join(plan.history_threads)
        + ". Use no other thread in a delegated exchange. Each exchange should be a new request on that thread, consistent with its details.",
    ]
    if plan.last_thread:
        tail.append(f"- The last delegated exchange must be on thread {plan.last_thread}.")
    if plan.not_last:
        tail.append(f"- Thread {plan.not_last} must not be the last delegated exchange; put another thread's exchange after it.")
    for t in plan.forbidden_threads:
        name = f" or the agent name \"{names[t]}\"" if names.get(t) else ""
        tail.append(f"- Don't mention thread {t} ({topic(t)}){name} anywhere in the tail.")
    if plan.subtype == "execution_result":
        tail.append(
            "- End the tail with one {\"kind\": \"pending\", \"thread\": \""
            + plan.message_thread
            + "\", \"user\": \"...\", \"ack\": \"...\"} exchange: the user's request on that thread whose result is the new message."
        )
        if plan.kind == "REUSE":
            tail.append("- That pending request must also ask for a follow-up once the result is in (for example 'and forward it to my accountant when you find it').")
        else:
            tail.append("- The new message must fully answer that pending request, so nothing more needs doing.")
    if plan.subtype == "email_alert" and plan.kind == "REUSE":
        tail.append(
            f"- In a delegated exchange on thread {plan.targets[0]}, the user asks that agent to act when a specific email arrives "
            "(for example 'when keith replies, draft a yes')."
        )
    tail.append("- You may add chat exchanges where natural. The tail has 4 to 16 entries in total (delegated = 4, pending/chat/alert = 2).")

    if plan.subtype == "execution_result":
        message = (
            f"Write only the result text from the agent of thread {plan.message_thread}; it will be shown as "
            f"\"[SUCCESS] {names[plan.message_thread]}: <your text>\"."
        )
        message += " The follow-up the user asked for is now due, so it goes back to the same agent." if plan.kind == "REUSE" else " It only needs summarizing for the user."
    elif plan.subtype == "email_alert":
        message = "Write only the notification body (it will be prefixed with \"Important email watcher notification:\")."
        if plan.kind == "REUSE":
            message += f" It is the email the user asked the agent of thread {plan.targets[0]} to act on."
        else:
            message += " It's about something new that only needs summarizing for the user; nothing should be done yet."
    elif plan.kind == "REUSE":
        message = "A user message asking for more work on the target thread. " + STYLE_RULES.get(plan.style, "")
        if plan.style == "near_distractor":
            message = (
                "A user message asking for more work on the target thread. It must clearly be about the target "
                "thread, not the near-distractor, without copying the target agent's name word for word."
            )
        if plan.old:
            message += " Name the topic clearly enough that the agent name is the only link to it."
    elif plan.kind == "REUSE_ANY":
        message = (
            "Write the two target threads' delegated exchanges so that both agents reported on the same object "
            "(for example both found the same email). The user message then acts on that object, so either agent holds enough context."
        )
    elif plan.kind == "CREATE":
        message = (
            f"A user message asking for the new work on thread {plan.new_thread}, written as a fresh request. It must not "
            "continue any agent's visible work, and a parallel agent must not be an equally valid choice."
        )
        if plan.distractor:
            message += f" The agent \"{names[plan.distractor]}\" looks related but its work is different."
    else:
        message = (
            "A user message answered directly from visible context or small talk (for example asking what amount a result "
            "said, or a reaction), needing no new work."
        )
    return {"plan": "\n".join(lines), "threads": thread_text, "tail_rules": "\n".join(tail), "message_rules": message}


def validate_draft(data: Any, plan: CasePlan, names: dict[str, str]) -> dict:
    if not isinstance(data, dict):
        raise GenerationError("draft is not an object")
    if "error" in data:
        raise GenerationError(f"drafter declined: {data['error']}")
    tail, message = data.get("tail"), data.get("message")
    if not isinstance(tail, list) or not tail or not isinstance(message, str) or not message.strip():
        raise GenerationError("missing tail or message")
    delegated = []
    entries = 0
    for i, item in enumerate(tail):
        kind = item.get("kind") if isinstance(item, dict) else None
        required = {
            "delegated": ("thread", "user", "ack", "result", "reply"),
            "pending": ("thread", "user", "ack"),
            "chat": ("user", "reply"),
            "alert": ("text", "reply"),
        }.get(kind)
        if required is None:
            raise GenerationError(f"tail item {i}: unknown kind {kind!r}")
        if not all(isinstance(item.get(f), str) and item[f].strip() for f in required):
            raise GenerationError(f"tail item {i}: missing fields")
        entries += 4 if kind == "delegated" else 2
        if kind == "delegated":
            if item["thread"] not in plan.history_threads:
                raise GenerationError(f"tail item {i}: thread {item['thread']} not allowed")
            delegated.append(item["thread"])
        if kind == "pending":
            if plan.subtype != "execution_result" or i != len(tail) - 1 or item["thread"] != plan.message_thread:
                raise GenerationError("pending exchange only allowed last, for the result's thread")
    if plan.subtype == "execution_result" and tail[-1].get("kind") != "pending":
        raise GenerationError("execution_result case must end with a pending exchange")
    if not 4 <= entries <= 16:
        raise GenerationError(f"tail has {entries} entries, expected 4 to 16")
    missing = [t for t in plan.history_threads if t not in delegated]
    if missing:
        raise GenerationError(f"threads missing from the tail: {missing}")
    if plan.last_thread and delegated[-1] != plan.last_thread:
        raise GenerationError(f"last delegated exchange must be {plan.last_thread}")
    if plan.not_last and delegated[-1] == plan.not_last:
        raise GenerationError(f"{plan.not_last} must not be the last delegated exchange")
    tail_text = json.dumps(tail, ensure_ascii=False).lower()
    for t in plan.forbidden_threads:
        if names.get(t) and names[t].lower() in tail_text:
            raise GenerationError(f"forbidden agent name {names[t]!r} appears in the tail")
    return {"tail": tail, "message": message.strip(), "rationale": str(data.get("rationale", "")).strip()}


def render_entries(plan: CasePlan, tail: list[dict], names: dict[str, str], acks_fallback: str = "on it") -> list[dict]:
    """Tail items to production-shaped entries with timestamps counted back from the case's time."""
    rng = rng_for(f"{plan.case_id}|tail-times")
    durations = []
    for item in tail:
        kind = item["kind"]
        if kind == "delegated":
            result_after = rng.randint(60, 240)
            durations.append([0, 5, result_after, result_after + 5])
        elif kind == "pending":
            durations.append([0, 5])
        else:
            durations.append([0, 5])
    now = parse_ts(plan.now)
    if tail[-1]["kind"] == "pending":
        end = now - timedelta(seconds=rng.randint(60, 240))
    else:
        end = now - timedelta(minutes=rng.randint(2, 30))
    starts = []
    cursor = end
    for offsets in reversed(durations):
        start = cursor - timedelta(seconds=offsets[-1])
        starts.append(start)
        cursor = start - timedelta(minutes=rng.randint(10, 180))
    starts.reverse()
    entries = []
    for item, start, offsets in zip(tail, starts, durations):
        ts = [format_ts(start + timedelta(seconds=s)) for s in offsets]
        kind = item["kind"]
        if kind == "delegated":
            entries += [
                {"tag": "user_message", "timestamp": ts[0], "payload": item["user"].strip()},
                {"tag": "poke_reply", "timestamp": ts[1], "payload": item["ack"].strip() or acks_fallback},
                {"tag": "agent_message", "timestamp": ts[2], "payload": format_batch_payload([(names[item["thread"]], item["result"].strip())])},
                {"tag": "poke_reply", "timestamp": ts[3], "payload": item["reply"].strip()},
            ]
        elif kind == "pending":
            entries += [
                {"tag": "user_message", "timestamp": ts[0], "payload": item["user"].strip()},
                {"tag": "poke_reply", "timestamp": ts[1], "payload": item["ack"].strip() or acks_fallback},
            ]
        elif kind == "chat":
            entries += [
                {"tag": "user_message", "timestamp": ts[0], "payload": item["user"].strip()},
                {"tag": "poke_reply", "timestamp": ts[1], "payload": item["reply"].strip()},
            ]
        else:
            entries += [
                {"tag": "agent_message", "timestamp": ts[0], "payload": EMAIL_ALERT_PREFIX + item["text"].strip()},
                {"tag": "poke_reply", "timestamp": ts[1], "payload": item["reply"].strip()},
            ]
    return entries


def render_message(plan: CasePlan, text: str, names: dict[str, str]) -> dict:
    if plan.subtype == "execution_result":
        rendered = format_batch_payload([(names[plan.message_thread], text)])
    elif plan.subtype == "email_alert":
        rendered = EMAIL_ALERT_PREFIX + text
    else:
        rendered = text
    return {"type": "user" if plan.subtype == "user" else "agent", "subtype": plan.subtype, "text": rendered, "timestamp": plan.now}


def build_case(plan: CasePlan, draft: dict, ids: dict[str, str], names: dict[str, str], provenance: dict) -> dict:
    return {
        "case_id": plan.case_id,
        "split": plan.split,
        "required_agents": [ids[t] for t in plan.required_threads()],
        "target_position": plan.target_position,
        "history": {"type": plan.history_type, "summary_text": "", "last_index": -1, "entries": render_entries(plan, draft["tail"], names)},
        "message": render_message(plan, draft["message"], names),
        "label": plan.label(),
        "meta": {
            "query_style": plan.style,
            "prev_thread": None,
            "name_descriptiveness": None,
            "target_name_visible": None,
            "target_age_bucket": None,
            "old_thread": plan.old,
        },
        "agent_ages": {ids[t]: days for t, days in plan.aged_threads.items()},
        "agent_times": None,
        "provenance": {
            "drafted_by": provenance,
            "plan": plan.to_dict(),
            "rationale": draft["rationale"],
            "cross_label": None,
            "review": None,
        },
    }


async def draft_one(ctx: StepContext, plan: CasePlan, threads: dict, ids: dict, names: dict, note: Optional[str], attempt_offset: int) -> dict:
    sections = describe(plan, threads, names, note)
    prompt = render_prompt("draft_case.md", rules=prompt_text("labeling_rules.md"), **sections)
    last = None
    for attempt in range(1 + attempt_offset, MAX_ATTEMPTS + 1 + attempt_offset):
        response, record = await ctx.client.chat(
            purpose="draft_case",
            model=GEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            extra={"max_tokens": 6000},
            fake_hint={"plan": plan.to_dict(), "names": names, "threads": {t: threads[t] for t in plan.required_threads() + ([plan.new_thread] if plan.new_thread else [])}, "attempt": attempt},
        )
        try:
            draft = validate_draft(extract_json(content_of(response)), plan, names)
        except GenerationError as exc:
            last = exc
            continue
        return build_case(plan, draft, ids, names, ctx.provenance(GEN_MODEL, record, attempt))
    raise GenerationError(f"{plan.case_id}: no valid draft after {MAX_ATTEMPTS} attempts ({last})")


# ---------------------------------------------------------------------------
# Fake drafter


def fake_draft_responder(payload: dict, hint: Any) -> dict:
    from ..harness.llm import fake_message

    plan, names, threads = hint["plan"], hint["names"], hint["threads"]
    history = list(plan["history_threads"])
    if plan["last_thread"]:
        history = [t for t in history if t != plan["last_thread"]] + [plan["last_thread"]]
    tail = [
        {"kind": "delegated", "thread": t, "user": threads[t]["opening_request"], "ack": "on it",
         "result": threads[t]["canned_result"], "reply": threads[t]["result_reply"]}
        for t in history
    ]
    if plan["subtype"] == "execution_result":
        tail.append({"kind": "pending", "thread": plan["message_thread"], "user": "and forward it when found", "ack": "on it"})
    if sum(4 if i["kind"] == "delegated" else 2 for i in tail) < 4:
        tail.append({"kind": "chat", "user": "thanks", "reply": "anytime"})
    kind, style = plan["kind"], plan["style"]
    if plan["subtype"] == "execution_result":
        message = "Found it and it is ready."
    elif plan["subtype"] == "email_alert":
        message = "A new email arrived about the plans."
    elif kind in ("REUSE", "REUSE_ANY"):
        target = plan["targets"][0]
        message = "reply to that" if style == "implicit_follow_up" else f"any update on {names[target].lower()}?"
    elif kind == "CREATE":
        message = threads[plan["new_thread"]]["opening_request"]
    else:
        message = "lol thanks"
    return fake_message(json.dumps({"tail": tail, "message": message, "rationale": "fake"}))


# ---------------------------------------------------------------------------
# CLI


def main(argv: Optional[list[str]] = None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--redraft", default="", help="comma-separated case ids to draft again (replacing them)")
    args = parser.parse_args(argv)
    fixtures_dir: Path = args.fixtures_dir
    redraft = {c.strip() for c in args.redraft.split(",") if c.strip()}

    have = all((fixtures_dir / f"agents.{s}.jsonl").exists() for s in SPLITS)
    todo: dict[str, list[CasePlan]] = {}
    if have:
        for split in SPLITS:
            threads = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
            ids, _names = agent_names(fixtures_dir, split)
            done = {c["case_id"] for c in read_rows(fixtures_dir / f"cases.single.{split}.jsonl")}
            todo[split] = [p for p in case_plans(split, threads, ids) if p.case_id not in done or p.case_id in redraft]
    count = sum(len(v) for v in todo.values()) if have else NOMINAL_CASES
    planned = [PlannedCalls("draft_case", GEN_MODEL, count * 1.25, 2600, 1700, "one case per call, 25% redrafts; output x1.75 per step 1")]
    extra = [
        "",
        f"cases to draft: {count}" + ("" if have else " (nominal: agents files not found yet)") + (f", redrafting {sorted(redraft)}" if redraft else ""),
        f"writes: {fixtures_dir}/cases.single.{{dev,test}}.jsonl, review/draft_failures.jsonl",
    ]

    async def body(ctx: StepContext) -> None:
        if not have:
            raise GenerationError("agents files not found: run name_agents.py and rate_names.py first")
        decisions = {d.get("item"): d for d in read_rows(fixtures_dir / "review" / "agent_decisions.jsonl")}
        failures = []
        for split in SPLITS:
            threads = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
            ids, names = agent_names(fixtures_dir, split)
            path = fixtures_dir / f"cases.single.{split}.jsonl"
            existing = {c["case_id"]: c for c in read_rows(path)}
            tasks = []
            for plan in todo[split]:
                prior = existing.get(plan.case_id)
                note = (decisions.get(plan.case_id) or {}).get("note") if plan.case_id in redraft else None
                offset = (prior or {}).get("provenance", {}).get("drafted_by", {}).get("attempts", 0) if prior else 0
                tasks.append(draft_one(ctx, plan, threads, ids, names, note, offset))
            results = await asyncio.gather(*tasks, return_exceptions=True)
            cap = None
            for plan, result in zip(todo[split], results):
                if isinstance(result, BaseException):
                    if result.__class__.__name__ == "SpendCapReached":
                        cap = result
                    else:
                        failures.append({"case_id": plan.case_id, "error": str(result)})
                    continue
                existing[plan.case_id] = result
            write_rows(path, [existing[k] for k in sorted(existing)])
            print(f"{split}: {len(existing)} cases drafted")
            if cap:
                raise cap
        failure_path = fixtures_dir / "review" / "draft_failures.jsonl"
        write_rows(failure_path, failures)
        if failures:
            print(f"{len(failures)} cases failed; see {failure_path}. Rerun the same command to retry them.")

    return run_paid_step(
        args, step="draft_cases", title="draft_cases.py (Sonnet 5.5)", planned=planned, body=body,
        models=[GEN_MODEL], fake_responders={"draft_case": fake_draft_responder}, extra_lines=extra,
    )


if __name__ == "__main__":
    raise SystemExit(main())
