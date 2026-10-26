"""Step 1: thread specs for both splits, plus the chit-chat pool (Sonnet 5.5). Paid.

``python -m evals.agent_overload.generation.gen_threads --dry-run``

Per split and category: one batch of case threads (with follow-ups and the
category's near-distractor pairs) and one batch of filler threads. Categories run
in parallel; within a category the four batches run in order, each told the
topics already written, so splits share nothing. Each batch's parsed output is
saved under ``review/gen_threads/`` and reused on a rerun; the thread files are
assembled once every batch exists. ``--top-up-filler N --split S`` adds N filler
threads to one split if filler cleaning leaves fewer than 200.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any, Optional

from ..harness.spend import PlannedCalls
from ..harness.util import sha256_hex
from .common import (
    CATEGORIES,
    GEN_MODEL,
    SPLITS,
    GenerationError,
    StepContext,
    base_parser,
    content_of,
    extract_json,
    read_json,
    read_rows,
    render_prompt,
    run_paid_step,
    write_json,
    write_rows,
)

CASE_TOTALS = {"test": 110, "dev": 55}
PAIR_TOTALS = {"test": 30, "dev": 15}
FILLER_TOTAL = 210
CHITCHAT_EXCHANGES = 60
CHITCHAT_ACKS = 15
MAX_ATTEMPTS = 3
FILLER_ID_START = 201


def spread(total: int, parts: int) -> list[int]:
    base, extra = divmod(total, parts)
    return [base + (1 if i < extra else 0) for i in range(parts)]


def allocation(split: str) -> list[dict]:
    cases = spread(CASE_TOTALS[split], len(CATEGORIES))
    pairs = spread(PAIR_TOTALS[split], len(CATEGORIES))
    filler = spread(FILLER_TOTAL, len(CATEGORIES))
    return [
        {"category": key, "description": desc, "cases": c, "pairs": p, "filler": f}
        for (key, desc), c, p, f in zip(CATEGORIES, cases, pairs, filler)
    ]


def batch_path(fixtures_dir: Path, split: str, category: str, kind: str) -> Path:
    return fixtures_dir / "review" / "gen_threads" / f"{split}.{category}.{kind}.json"


# ---------------------------------------------------------------------------
# Validation


def _text(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != ""


def validate_case_batch(data: Any, count: int, pairs: int) -> list[dict]:
    threads = data.get("threads") if isinstance(data, dict) else None
    if not isinstance(threads, list) or len(threads) != count:
        raise GenerationError(f"expected {count} threads, got {len(threads) if isinstance(threads, list) else 'none'}")
    keys = [t.get("key") for t in threads]
    if len(set(keys)) != count:
        raise GenerationError("duplicate thread keys")
    paired = 0
    for t in threads:
        for field in ("topic", "opening_request", "canned_result", "result_reply"):
            if not _text(t.get(field)):
                raise GenerationError(f"{t.get('key')}: missing {field}")
        ups = t.get("follow_ups")
        if not isinstance(ups, list) or len(ups) != 3 or not all(
            isinstance(u, dict) and all(_text(u.get(f)) for f in ("request", "result", "reply")) for u in ups
        ):
            raise GenerationError(f"{t.get('key')}: follow_ups must be 3 complete items")
        partner = t.get("pair_key")
        if partner is not None:
            other = next((o for o in threads if o.get("key") == partner), None)
            if other is None or other.get("pair_key") != t.get("key") or partner == t.get("key"):
                raise GenerationError(f"{t.get('key')}: pair_key {partner} is not symmetric")
            paired += 1
    if paired != 2 * pairs:
        raise GenerationError(f"expected {pairs} pairs, got {paired / 2:g}")
    return threads


def validate_filler_batch(data: Any, count: int) -> list[dict]:
    threads = data.get("threads") if isinstance(data, dict) else None
    if not isinstance(threads, list) or len(threads) != count:
        raise GenerationError(f"expected {count} filler threads, got {len(threads) if isinstance(threads, list) else 'none'}")
    for t in threads:
        for field in ("topic", "opening_request", "canned_result", "result_reply"):
            if not _text(t.get(field)):
                raise GenerationError(f"{t.get('key')}: missing {field}")
    return threads


def validate_chitchat(data: Any) -> dict:
    exchanges = data.get("exchanges") if isinstance(data, dict) else None
    acks = data.get("acks") if isinstance(data, dict) else None
    if not isinstance(exchanges, list) or len(exchanges) < CHITCHAT_EXCHANGES * 0.9:
        raise GenerationError("too few chit-chat exchanges")
    if not isinstance(acks, list) or len(acks) < CHITCHAT_ACKS * 0.8:
        raise GenerationError("too few acknowledgements")
    if not all(isinstance(e, dict) and _text(e.get("user")) and _text(e.get("reply")) for e in exchanges):
        raise GenerationError("malformed chit-chat exchange")
    if not all(_text(a) for a in acks):
        raise GenerationError("malformed acknowledgement")
    return {"exchanges": exchanges, "acks": acks}


# ---------------------------------------------------------------------------
# Model calls


async def ask_json(ctx: StepContext, purpose: str, prompt: str, validate, hint: dict, max_tokens: int = 12000) -> tuple[Any, dict]:
    last_error = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        response, record = await ctx.client.chat(
            purpose=purpose,
            model=GEN_MODEL,
            messages=[{"role": "user", "content": prompt}],
            extra={"max_tokens": max_tokens},
            fake_hint={**hint, "attempt": attempt},
        )
        try:
            data = validate(extract_json(content_of(response)))
        except GenerationError as exc:
            last_error = exc
            print(f"  {purpose} {hint.get('split', '')} {hint.get('category', '')}: attempt {attempt} rejected ({exc})")
            continue
        return data, ctx.provenance(GEN_MODEL, record, attempt)
    raise GenerationError(f"{purpose} {hint}: no valid output after {MAX_ATTEMPTS} attempts ({last_error})")


def _topics_text(topics: list[str]) -> str:
    return "\n".join(f"- {t}" for t in topics) if topics else "(none yet)"


async def run_category(ctx: StepContext, fixtures_dir: Path, category: dict, split_allocs: dict[str, dict], topics: list[str]) -> None:
    for split in ("test", "dev"):
        alloc = split_allocs[split]
        for kind in ("case", "filler"):
            path = batch_path(fixtures_dir, split, category["category"], kind)
            saved = read_json(path)
            if saved is None:
                if kind == "case":
                    prompt = render_prompt(
                        "gen_threads_case.md",
                        count=alloc["cases"],
                        pairs=alloc["pairs"],
                        category_description=category["description"],
                        existing_topics=_topics_text(topics),
                    )
                    hint = {"split": split, "category": category["category"], "kind": "case", "count": alloc["cases"], "pairs": alloc["pairs"]}
                    threads, prov = await ask_json(
                        ctx, "gen_threads", prompt, lambda d: validate_case_batch(d, alloc["cases"], alloc["pairs"]), hint
                    )
                else:
                    prompt = render_prompt(
                        "gen_threads_filler.md",
                        count=alloc["filler"],
                        category_description=category["description"],
                        existing_topics=_topics_text(topics),
                    )
                    hint = {"split": split, "category": category["category"], "kind": "filler", "count": alloc["filler"]}
                    threads, prov = await ask_json(ctx, "gen_threads", prompt, lambda d: validate_filler_batch(d, alloc["filler"]), hint)
                saved = {"threads": threads, "provenance": prov}
                write_json(path, saved)
            topics.extend(t["topic"] for t in saved["threads"])


def assemble(fixtures_dir: Path) -> Optional[dict[str, int]]:
    """Write threads.<split>.jsonl from the batch files once all of them exist."""
    counts = {}
    for split in SPLITS:
        rows, fillers = [], []
        for alloc in allocation(split):
            case_batch = read_json(batch_path(fixtures_dir, split, alloc["category"], "case"))
            filler_batch = read_json(batch_path(fixtures_dir, split, alloc["category"], "filler"))
            if case_batch is None or filler_batch is None:
                return None
            key_to_id = {}
            for t in case_batch["threads"]:
                key_to_id[t["key"]] = f"t-{split}-{len(rows) + 1:04d}"
                rows.append((t, alloc["category"], "case"))
            for t in filler_batch["threads"]:
                fillers.append((t, alloc["category"], "filler"))
            for t in case_batch["threads"]:
                t["_id"] = key_to_id[t["key"]]
                t["_pair_id"] = key_to_id.get(t.get("pair_key")) if t.get("pair_key") else None
        if len(rows) >= FILLER_ID_START:
            raise GenerationError("case thread ids would collide with filler ids")
        out = []
        for t, category, role in rows:
            out.append(_thread_row(t["_id"], split, role, category, t, t["_pair_id"]))
        for i, (t, category, role) in enumerate(fillers):
            out.append(_thread_row(f"t-{split}-{FILLER_ID_START + i:04d}", split, role, category, t, None))
        for extra in read_rows(fixtures_dir / "review" / "gen_threads" / f"{split}.topup.jsonl"):
            out.append(extra)
        write_rows(fixtures_dir / f"threads.{split}.jsonl", out)
        counts[split] = len(out)
    return counts


def _thread_row(thread_id: str, split: str, role: str, category: str, t: dict, pair_id: Optional[str]) -> dict:
    return {
        "thread_id": thread_id,
        "split": split,
        "role": role,
        "category": category,
        "topic": t["topic"].strip(),
        "opening_request": t["opening_request"].strip(),
        "canned_result": t["canned_result"].strip(),
        "result_reply": t["result_reply"].strip(),
        "follow_ups": [
            {"request": u["request"].strip(), "result": u["result"].strip(), "reply": u["reply"].strip()}
            for u in t.get("follow_ups", [])
        ]
        if role == "case"
        else [],
        "near_distractor_of": pair_id,
    }


async def run_chitchat(ctx: StepContext, fixtures_dir: Path) -> None:
    path = fixtures_dir / "review" / "gen_threads" / "chitchat.json"
    saved = read_json(path)
    if saved is None:
        prompt = render_prompt("gen_chitchat.md", exchanges=CHITCHAT_EXCHANGES, acks=CHITCHAT_ACKS)
        data, prov = await ask_json(ctx, "gen_chitchat", prompt, validate_chitchat, {"kind": "chitchat"})
        saved = {**data, "provenance": prov}
        write_json(path, saved)
    rows = [{"kind": "exchange", "user": e["user"].strip(), "reply": e["reply"].strip()} for e in saved["exchanges"]]
    rows += [{"kind": "ack", "text": a.strip()} for a in saved["acks"]]
    write_rows(fixtures_dir / "chitchat.jsonl", rows)


async def run_topup(ctx: StepContext, fixtures_dir: Path, split: str, count: int) -> None:
    threads = read_rows(fixtures_dir / f"threads.{split}.jsonl")
    if not threads:
        raise GenerationError("run the full step first")
    topics = [t["topic"] for t in threads]
    prompt = render_prompt(
        "gen_threads_filler.md", count=count, category_description="any everyday category", existing_topics=_topics_text(topics)
    )
    batch, _prov = await ask_json(ctx, "gen_threads", prompt, lambda d: validate_filler_batch(d, count), {"split": split, "category": "topup", "kind": "filler", "count": count})
    next_number = max(int(t["thread_id"].rsplit("-", 1)[1]) for t in threads) + 1
    topup_path = fixtures_dir / "review" / "gen_threads" / f"{split}.topup.jsonl"
    existing = read_rows(topup_path)
    new_rows = [
        _thread_row(f"t-{split}-{next_number + i:04d}", split, "filler", "mixed", t, None) for i, t in enumerate(batch)
    ]
    write_rows(topup_path, existing + new_rows)
    write_rows(fixtures_dir / f"threads.{split}.jsonl", threads + new_rows)


# ---------------------------------------------------------------------------
# Fake responder


def fake_word(key: str) -> str:
    """A random-looking 7-letter word, so fake names are about as dissimilar as real ones."""
    digest = sha256_hex(key)
    return "".join(chr(ord("a") + int(digest[i : i + 2], 16) % 26) for i in range(0, 14, 2)).capitalize()


def fake_threads_responder(payload: dict, hint: Any) -> dict:
    from ..harness.llm import fake_message

    hint = hint or {}
    if hint.get("kind") == "chitchat":
        data = {
            "exchanges": [{"user": f"haha ok number {i}", "reply": f"glad to help, round {i}"} for i in range(CHITCHAT_EXCHANGES)],
            "acks": [f"on it {i}" for i in range(CHITCHAT_ACKS)],
        }
        return fake_message(json.dumps(data))
    split, category, kind, count = hint["split"], hint["category"], hint["kind"], hint["count"]
    threads = []
    for i in range(count):
        base = f"{split}|{category}|{kind}|{i}"
        w1, w2, w3 = fake_word(base + "a"), fake_word(base + "b"), fake_word(base + "c")
        t = {
            "key": f"{'c' if kind == 'case' else 'f'}{i + 1}",
            "topic": f"{w1} {w2} {category} item",
            "opening_request": f"can you check the {w1} {w2} {w3} email",
            "canned_result": f"Found the {w1} {w2} email from {w3.lower()}@example.com dated Oct {1 + i % 28}.",
            "result_reply": f"Found the {w1} email.",
        }
        if kind == "case":
            t["follow_ups"] = [{"request": f"follow up {j} on {w1}", "result": f"{w1} follow-up {j} done.", "reply": f"Done ({j})."} for j in range(3)]
            t["pair_key"] = None
        threads.append(t)
    if kind == "case":
        for p in range(hint.get("pairs", 0)):
            a, b = threads[2 * p], threads[2 * p + 1]
            a["pair_key"], b["pair_key"] = b["key"], a["key"]
            shared = a["opening_request"].split()[4]  # share one word, like Uber rides vs Uber Eats
            b["opening_request"] = b["opening_request"].replace(b["opening_request"].split()[4], shared)
    return fake_message(json.dumps({"threads": threads}))


# ---------------------------------------------------------------------------
# CLI


def main(argv: Optional[list[str]] = None) -> int:
    parser = base_parser(__doc__)
    parser.add_argument("--top-up-filler", type=int, default=None, help="add N filler threads to --split")
    parser.add_argument("--split", choices=SPLITS, default=None)
    args = parser.parse_args(argv)
    fixtures_dir: Path = args.fixtures_dir

    if args.top_up_filler:
        if not args.split:
            parser.error("--top-up-filler needs --split")
        planned = [PlannedCalls("gen_threads (top-up)", GEN_MODEL, 1.2, 6000, args.top_up_filler * 180)]

        async def topup_body(ctx: StepContext) -> None:
            await run_topup(ctx, fixtures_dir, args.split, args.top_up_filler)

        return run_paid_step(
            args, step="gen_threads_topup", title="gen_threads.py --top-up-filler", planned=planned,
            body=topup_body, models=[GEN_MODEL], fake_responders={"gen_threads": fake_threads_responder},
        )

    allocs = {split: {a["category"]: a for a in allocation(split)} for split in SPLITS}
    missing = [
        (split, cat, kind)
        for split in SPLITS
        for cat, _ in CATEGORIES
        for kind in ("case", "filler")
        if read_json(batch_path(fixtures_dir, split, cat, kind)) is None
    ]
    n_case = sum(1 for m in missing if m[2] == "case")
    n_filler = len(missing) - n_case
    chitchat_missing = read_json(fixtures_dir / "review" / "gen_threads" / "chitchat.json") is None
    planned = [
        PlannedCalls("gen_threads (case)", GEN_MODEL, n_case * 1.25, 1050, 4800, "about 9 or 4 case threads per batch; tokens measured 2026-10-26"),
        PlannedCalls("gen_threads (filler)", GEN_MODEL, n_filler * 1.1, 950, 3250, "about 18 filler threads per batch; measured"),
        PlannedCalls("gen_chitchat", GEN_MODEL, 1.2 if chitchat_missing else 0, 300, 4500),
    ]
    extra = [
        "",
        f"batches still to generate: {len(missing)} of {len(SPLITS) * len(CATEGORIES) * 2}, chit-chat: {'yes' if chitchat_missing else 'done'}",
        f"targets per split: test {CASE_TOTALS['test']} case ({PAIR_TOTALS['test']} pairs) + {FILLER_TOTAL} filler; "
        f"dev {CASE_TOTALS['dev']} case ({PAIR_TOTALS['dev']} pairs) + {FILLER_TOTAL} filler",
        f"writes: {fixtures_dir}/threads.{{dev,test}}.jsonl, chitchat.jsonl, review/gen_threads/*.json",
    ]

    async def body(ctx: StepContext) -> None:
        topics_by_category: dict[str, list[str]] = {cat: [] for cat, _ in CATEGORIES}
        tasks = [
            run_category(ctx, fixtures_dir, {"category": cat, "description": desc}, {s: allocs[s][cat] for s in SPLITS}, topics_by_category[cat])
            for cat, desc in CATEGORIES
        ]
        tasks.append(run_chitchat(ctx, fixtures_dir))
        results = await asyncio.gather(*tasks, return_exceptions=True)
        errors = [r for r in results if isinstance(r, BaseException)]
        counts = assemble(fixtures_dir)
        if counts:
            print(f"threads written: {counts}")
        for err in errors:
            if not isinstance(err, GenerationError):
                raise err
            print(f"error: {err}")
        if errors:
            print("Some batches failed; rerun the same command to retry only those.")

    return run_paid_step(
        args, step="gen_threads", title="gen_threads.py (Sonnet 5.5: thread specs + chit-chat)", planned=planned,
        body=body, models=[GEN_MODEL],
        fake_responders={"gen_threads": fake_threads_responder, "gen_chitchat": fake_threads_responder},
        extra_lines=extra,
    )


if __name__ == "__main__":
    raise SystemExit(main())
