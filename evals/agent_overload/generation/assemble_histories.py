"""Step 6: assemble long histories in code (free, deterministic, no model calls).

``python -m evals.agent_overload.generation.assemble_histories``

- Summarized single-turn cases: 100 to 126 entries (even, and enough that the raw
  history has at least 110) go in front of the drafted tail. The raw history is saved
  to ``review/raw_histories/<case_id>.jsonl``; ``summarize_histories.py`` then applies
  the production summarization rule to it.
- Sequences: 96 entries before turn 1, written into ``initial_history``.

A history is a series of exchanges with production's shapes: delegated (user
request, acknowledgement, ``[SUCCESS] <agent>: <result>`` via
``_format_batch_payload``, reply) and chit-chat (user message, reply). Only the
case's own required threads that aren't aged appear in delegated exchanges, each
starting with its opening request; about 60% of exchanges are delegated. Timestamps
spread over the 3 days before the first tail entry (or turn 1), 08:00 to 22:00, at
least 2 minutes apart. The generator is seeded with ``sha256(f"{case_id}|history")``.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from ..harness.state import format_batch_payload
from ..harness.util import format_ts, parse_ts, sha256_hex
from .common import SPLITS, GenerationError, base_parser, ensure_not_frozen, read_rows, write_rows

SEQUENCE_ENTRIES = 96
SUMMARIZED_MIN, SUMMARIZED_MAX = 100, 126
RAW_MINIMUM = 110
DELEGATED_SHARE = 0.6


def history_rng(case_id: str) -> random.Random:
    return random.Random(int(sha256_hex(f"{case_id}|history")[:16], 16))


def thread_exchanges(thread: dict) -> list[tuple[str, str, str]]:
    """(request, result, reply) for the opening request and each follow-up, in order."""
    out = [(thread["opening_request"], thread["canned_result"], thread["result_reply"])]
    out += [(u["request"], u["result"], u["reply"]) for u in thread.get("follow_ups", [])]
    return out


def plan_exchanges(total_entries: int, available: dict[str, int], rng: random.Random) -> tuple[dict[str, int], int]:
    """How many delegated exchanges per thread, and how many chit-chat exchanges, to fill ``total_entries``."""
    target_delegated = round(3 * total_entries / 16)  # 4d + 2c = L with d / (d + c) = 0.6
    capacity = sum(available.values())
    delegated = min(target_delegated, capacity)
    while (total_entries - 4 * delegated) % 2:
        delegated -= 1
    per_thread = {t: 0 for t in available}
    threads = sorted(available)
    # Every thread gets its opening request first, then fill round-robin.
    for t in threads:
        if delegated - sum(per_thread.values()) > 0 and available[t] > 0:
            per_thread[t] = 1
    while sum(per_thread.values()) < delegated:
        room = [t for t in threads if per_thread[t] < available[t]]
        per_thread[rng.choice(room)] += 1
    chitchat = (total_entries - 4 * sum(per_thread.values())) // 2
    return per_thread, chitchat


def assemble(
    case_id: str,
    total_entries: int,
    threads: list[dict],
    names: dict[str, str],
    chitchat: list[dict],
    end: str,
) -> list[dict]:
    """Entries for one history ending before ``end`` (the first tail entry or turn 1)."""
    rng = history_rng(case_id)
    exchanges_by_thread = {t["thread_id"]: thread_exchanges(t) for t in threads}
    per_thread, n_chat = plan_exchanges(total_entries, {k: len(v) for k, v in exchanges_by_thread.items()}, rng)
    pool = [c for c in chitchat if c["kind"] == "exchange"]
    acks = [c["text"] for c in chitchat if c["kind"] == "ack"] or ["on it"]
    if n_chat > len(pool):
        raise GenerationError(f"{case_id}: needs {n_chat} chit-chat exchanges, pool has {len(pool)}")
    chats = rng.sample(pool, n_chat)

    # Interleave: thread exchanges keep their order; positions are shuffled.
    slots = [("chat", i) for i in range(n_chat)]
    for t, n in per_thread.items():
        slots += [("thread", t)] * n
    rng.shuffle(slots)
    next_index = {t: 0 for t in per_thread}

    starts = _start_times(len(slots), end, rng)
    entries: list[dict] = []
    for (kind, ref), start in zip(slots, starts):
        if kind == "chat":
            chat = chats[ref]
            entries.append({"tag": "user_message", "timestamp": format_ts(start), "payload": chat["user"]})
            entries.append({"tag": "poke_reply", "timestamp": format_ts(start + timedelta(seconds=5)), "payload": chat["reply"]})
        else:
            request, result, reply = exchanges_by_thread[ref][next_index[ref]]
            next_index[ref] += 1
            result_at = start + timedelta(seconds=rng.randint(60, 180))
            entries.append({"tag": "user_message", "timestamp": format_ts(start), "payload": request})
            entries.append({"tag": "poke_reply", "timestamp": format_ts(start + timedelta(seconds=5)), "payload": rng.choice(acks)})
            entries.append({"tag": "agent_message", "timestamp": format_ts(result_at), "payload": format_batch_payload([(names[ref], result)])})
            entries.append({"tag": "poke_reply", "timestamp": format_ts(result_at + timedelta(seconds=5)), "payload": reply})
    if len(entries) != total_entries:
        raise GenerationError(f"{case_id}: assembled {len(entries)} entries, expected {total_entries}")
    return entries


def _start_times(count: int, end: str, rng: random.Random) -> list[datetime]:
    """``count`` exchange start times in the 3 days before ``end``, 08:00 to 22:00, >= 5 minutes apart."""
    end_dt = parse_ts(end)
    window_start = (end_dt - timedelta(days=3)).replace(hour=8, minute=0, second=0)
    minutes = []
    day = window_start
    while day < end_dt:
        day_start = day.replace(hour=8, minute=0, second=0)
        day_end = min(day.replace(hour=22, minute=0, second=0), end_dt - timedelta(minutes=10))
        m = day_start
        while m < day_end:
            minutes.append(m)
            m += timedelta(minutes=5)
        day = (day + timedelta(days=1)).replace(hour=8, minute=0, second=0)
    if len(minutes) < count:
        raise GenerationError("not enough room for the history's exchanges")
    picked = sorted(rng.sample(minutes, count))
    return [p + timedelta(seconds=rng.randint(0, 59)) for p in picked]


def summarized_length(case_id: str, tail_entries: int) -> int:
    rng = history_rng(f"{case_id}|length")
    low = max(SUMMARIZED_MIN, RAW_MINIMUM - tail_entries)
    low += low % 2
    return rng.randrange(low, SUMMARIZED_MAX + 1, 2)


def main(argv: Optional[list[str]] = None) -> int:
    args = base_parser(__doc__, paid=False).parse_args(argv)
    fixtures_dir: Path = args.fixtures_dir
    chitchat = read_rows(fixtures_dir / "chitchat.jsonl")
    if not chitchat:
        print("error: chitchat.jsonl not found (run gen_threads.py first)")
        return 1
    if not args.dry_run:
        ensure_not_frozen(fixtures_dir)
    raw_dir = fixtures_dir / "review" / "raw_histories"
    for split in SPLITS:
        threads = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
        agents = read_rows(fixtures_dir / f"agents.{split}.jsonl")
        names_by_thread = {a["thread_id"]: a["name"] for a in agents}
        thread_of_agent = {a["agent_id"]: a["thread_id"] for a in agents}

        cases = read_rows(fixtures_dir / f"cases.single.{split}.jsonl")
        assembled = 0
        for case in cases:
            if case["history"]["type"] != "summarized" or case["history"].get("summary_text"):
                continue
            raw_path = raw_dir / f"{case['case_id']}.jsonl"
            tail = case["history"].get("tail_entries") or case["history"]["entries"]
            aged = set(case.get("agent_ages") or {})
            used = [thread_of_agent[a] for a in case["required_agents"] if a not in aged]
            length = summarized_length(case["case_id"], len(tail))
            prefix = assemble(case["case_id"], length, [threads[t] for t in used], names_by_thread, chitchat, tail[0]["timestamp"])
            if args.dry_run:
                assembled += 1
                continue
            write_rows(raw_path, prefix + tail)
            case["history"]["tail_entries"] = tail
            case["history"]["entries"] = prefix + tail
            assembled += 1
        if not args.dry_run:
            write_rows(fixtures_dir / f"cases.single.{split}.jsonl", cases)

        sequences = read_rows(fixtures_dir / f"cases.sequence.{split}.jsonl")
        for seq in sequences:
            if seq["initial_history"]["entries"]:
                continue
            aged = set(seq.get("agent_ages") or {})
            used = [thread_of_agent[a] for a in seq["required_agents"] if a not in aged]
            entries = assemble(seq["case_id"], SEQUENCE_ENTRIES, [threads[t] for t in used], names_by_thread, chitchat, seq["turns"][0]["timestamp"])
            seq["initial_history"] = {"summary_text": "", "last_index": -1, "entries": entries}
        if not args.dry_run:
            write_rows(fixtures_dir / f"cases.sequence.{split}.jsonl", sequences)
        print(f"{split}: {'would assemble' if args.dry_run else 'assembled'} {assembled} summarized single-turn histories and "
              f"{len(sequences)} sequence histories")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
