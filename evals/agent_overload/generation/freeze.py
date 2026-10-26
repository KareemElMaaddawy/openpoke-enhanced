"""Step 10: validate, compute derived fields, and freeze the case set (free).

``python -m evals.agent_overload.generation.freeze --check``   validate only
``python -m evals.agent_overload.generation.freeze --update-config``   freeze and fill the config's expected_hash

Computes, for every case: ``meta.prev_thread`` (thread of the most recent result line
in the visible history), ``meta.target_name_visible``, ``meta.name_descriptiveness``,
``agent_times`` (``last_active`` = the latest result line naming the agent, including
the summarized part read from ``review/raw_histories/``, else ``now`` minus
``agent_ages``; ``created_at`` = ``last_active`` minus a seeded 0 to 30 days, never later
than the agent's first result line) and ``meta.target_age_bucket``. Then checks the
schemas, the quotas and the rules (old-thread targets 15 to 60 days old and absent
from the visible history, required agents within limits, every disagreement
reviewed), and writes ``MANIFEST.json`` with the per-file hashes and the
``case_set_hash``. The harness refuses to load a set whose hashes don't match.
"""

from __future__ import annotations

import json
from collections import Counter
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Optional

from ..harness.fixtures import MANIFEST_NAME, case_set_hash, file_hashes
from ..harness.rosters import BUCKETS, MAX_REQUIRED
from ..harness.runner import apply_gold
from ..harness.state import RESULT_PREFIXES, initial_state
from ..harness.util import REPO_ROOT, age_days, days_before, parse_ts, seeded_uniform
from .common import SPLITS, base_parser, prompt_hashes, read_json, read_rows, write_json, write_rows
from .planning import _slots

VERSION = "v1"
TAGS = ("user_message", "agent_message", "poke_reply", "wait")


class FreezeError(Exception):
    pass


def age_bucket(days: float) -> str:
    if days <= 3:
        return "recent"
    if days <= 14:
        return "mid"
    return "old"


def result_line_times(entries: list[dict], names: dict[str, str]) -> dict[str, list[str]]:
    """agent_id -> timestamps of result lines naming it (``names`` maps agent_id to name)."""
    by_length = sorted(names.items(), key=lambda kv: len(kv[1]), reverse=True)
    out: dict[str, list[str]] = {}
    for e in entries:
        if e["tag"] != "agent_message" or not e["payload"].startswith(RESULT_PREFIXES):
            continue
        for line in e["payload"].split("\n"):
            for prefix in RESULT_PREFIXES:
                if line.startswith(prefix):
                    rest = line[len(prefix):]
                    for agent_id, name in by_length:
                        if rest.startswith(f"{name}: ") or rest == f"{name}:":
                            out.setdefault(agent_id, []).append(e["timestamp"])
                            break
    return out


def compute_agent_times(case_id: str, required: list[str], names: dict[str, str], raw_entries: list[dict], agent_ages: dict, now: str) -> dict:
    lines = result_line_times(raw_entries, {a: names[a] for a in required})
    times = {}
    for agent_id in required:
        offset = seeded_uniform(f"{case_id}|{agent_id}|created", 0.0, 30.0)
        if agent_id in lines:
            last = max(lines[agent_id])
            first = min(lines[agent_id])
            created = min(days_before(last, offset), first)
        elif agent_id in agent_ages:
            last = days_before(now, float(agent_ages[agent_id]))
            created = days_before(last, offset)
        else:
            raise FreezeError(f"{case_id}: {agent_id} is neither named in the history nor in agent_ages")
        times[agent_id] = {"last_active": last, "created_at": created}
    return times


def _check_entries(case_id: str, entries: list[dict], before: Optional[str]) -> None:
    previous = None
    for e in entries:
        if e.get("tag") not in TAGS or not isinstance(e.get("payload"), str) or not e.get("timestamp"):
            raise FreezeError(f"{case_id}: malformed history entry {e}")
        parse_ts(e["timestamp"])
        if previous and e["timestamp"] < previous:
            raise FreezeError(f"{case_id}: history timestamps go backwards at {e['timestamp']}")
        previous = e["timestamp"]
    if before and previous and previous > before:
        raise FreezeError(f"{case_id}: history continues after the message ({previous} > {before})")


def _check_reviewed(item: str, cl: Optional[dict], review: Optional[dict], problems: list[str]) -> None:
    if cl is None:
        problems.append(f"{item}: no second label")
    elif not cl.get("agreed") and not review:
        problems.append(f"{item}: disagreement without a review decision")


def finalize_single(case: dict, fs: dict, split: str, fixtures_dir: Path, problems: list[str]) -> None:
    case_id = case["case_id"]
    agents = fs["agents"][split]
    threads = fs["threads"][split]
    required = case["required_agents"]
    label = case["label"]
    if len(required) > MAX_REQUIRED["single"]:
        problems.append(f"{case_id}: {len(required)} required agents (max {MAX_REQUIRED['single']})")
    for a in required:
        if a not in agents:
            raise FreezeError(f"{case_id}: unknown required agent {a}")
    agent_of = fs["agent_of_thread"][split]
    if label["kind"] in ("REUSE", "REUSE_ANY"):
        if not label.get("threads") or (label["kind"] == "REUSE") != (len(label["threads"]) == 1):
            problems.append(f"{case_id}: malformed {label['kind']} label")
        for t in label.get("threads", []):
            if agent_of.get(t) not in required:
                problems.append(f"{case_id}: target thread {t} has no required agent")
    elif label["kind"] == "CREATE":
        if label.get("new_thread") not in threads:
            problems.append(f"{case_id}: CREATE new_thread missing")
        elif agent_of.get(label["new_thread"]) in required:
            problems.append(f"{case_id}: CREATE thread's own agent is in the roster")
    elif label["kind"] != "NO_DELEGATION":
        problems.append(f"{case_id}: unknown label {label['kind']}")
    if case.get("target_position") not in (None, *BUCKETS):
        problems.append(f"{case_id}: bad target_position")

    history = case["history"]
    message = case["message"]
    _check_entries(case_id, history["entries"], message["timestamp"])
    if history["type"] == "summarized":
        if not history.get("summary_text") or history.get("last_index", -1) < 0:
            problems.append(f"{case_id}: summarized history has no summary")
        raw = read_rows(fixtures_dir / "review" / "raw_histories" / f"{case_id}.jsonl")
        if not raw:
            problems.append(f"{case_id}: raw history missing")
        if len(history["entries"]) < 10:
            problems.append(f"{case_id}: fewer than 10 unsummarized entries")
    else:
        raw = history["entries"]
        if not 4 <= len(raw) <= 16:
            problems.append(f"{case_id}: short history has {len(raw)} entries")
    if message["subtype"] == "email_alert" and not message["text"].startswith("Important email watcher notification:\n"):
        problems.append(f"{case_id}: email alert without the watcher prefix")

    names = {a: agents[a]["name"] for a in required}
    now = message["timestamp"]
    times = compute_agent_times(case_id, required, names, raw, case.get("agent_ages") or {}, now)
    case["agent_times"] = times
    state = initial_state(
        roster_ids=required, agents=agents, agent_times=times, filler_age_days={}, now=now, history=history
    )
    transcript = state.transcript()
    meta = case["meta"]
    meta["prev_thread"] = state.prev_thread()
    targets = [agent_of[t] for t in label.get("threads", [])] if label["kind"] in ("REUSE", "REUSE_ANY") else []
    meta["target_name_visible"] = any(
        names[a] in transcript or escape(names[a], quote=False) in transcript for a in targets
    ) if targets else None
    meta["name_descriptiveness"] = agents[targets[0]].get("descriptiveness") if targets else None
    meta["target_age_bucket"] = age_bucket(age_days(times[targets[0]]["last_active"], now)) if targets else None
    if meta.get("old_thread"):
        age = age_days(times[targets[0]]["last_active"], now)
        if not 15 <= age <= 60:
            problems.append(f"{case_id}: old-thread target is {age:.1f} days old")
        if meta["target_name_visible"]:
            problems.append(f"{case_id}: old-thread target's name is visible in the history")
    _check_reviewed(case_id, case["provenance"].get("cross_label"), case["provenance"].get("review"), problems)


def finalize_sequence(seq: dict, fs: dict, split: str, problems: list[str]) -> None:
    case_id = seq["case_id"]
    agents = fs["agents"][split]
    required = seq["required_agents"]
    if len(required) > MAX_REQUIRED["sequence"]:
        problems.append(f"{case_id}: {len(required)} required agents (max {MAX_REQUIRED['sequence']})")
    first = seq["turns"][0]["timestamp"]
    entries = seq["initial_history"]["entries"]
    _check_entries(case_id, entries, first)
    names = {a: agents[a]["name"] for a in required}
    times = compute_agent_times(case_id, required, names, entries, seq.get("agent_ages") or {}, first)
    seq["agent_times"] = times
    state = initial_state(roster_ids=required, agents=agents, agent_times=times, filler_age_days={}, now=first, history=seq["initial_history"])
    previous = None
    reviews = seq["provenance"].get("review") or {}
    turns_cl = (seq["provenance"].get("cross_label") or {}).get("turns", {})
    for turn in seq["turns"]:
        if previous and turn["timestamp"] <= previous:
            problems.append(f"{case_id}: turn {turn['turn']} timestamp not after the previous turn")
        previous = turn["timestamp"]
        label = turn["label"]
        if label["kind"] in ("REUSE", "REUSE_ANY"):
            for t in label["threads"]:
                if state.canonical_agent(t) is None:
                    problems.append(f"{case_id}: turn {turn['turn']} reuses {t}, which has no agent in the gold state")
        if label["kind"] == "CREATE":
            agent_id = fs["agent_of_thread"][split].get(label["new_thread"])
            if agent_id is None or agents[agent_id]["name"] != turn["gold"]["create_name"]:
                problems.append(f"{case_id}: turn {turn['turn']} create_name doesn't match the frozen agent name")
            elif agents[agent_id].get("seeded", True):
                problems.append(f"{case_id}: created thread's agent {agent_id} is marked seeded")
        _check_reviewed(f"{case_id}#t{turn['turn']}", turns_cl.get(str(turn["turn"])), reviews.get(str(turn["turn"])), problems)
        try:
            apply_gold(state, turn, fs["agent_of_thread"][split])
        except RuntimeError as exc:
            problems.append(f"{case_id}: {exc}")
            return


def quota_report(fs: dict) -> tuple[dict, list[str]]:
    report, problems = {}, []
    for split in SPLITS:
        cases = fs["single"][split]
        cells = Counter((c["label"]["kind"], c["meta"]["query_style"]) for c in cases)
        expected = Counter((s["kind"], s["style"]) for s in _slots(split))
        for key, n in expected.items():
            if cells.get(key, 0) != n:
                problems.append(f"{split}: quota {key} has {cells.get(key, 0)} cases, expected {n}")
        report[split] = {
            "cells": {f"{k}|{s}": n for (k, s), n in sorted(cells.items())},
            "history_type": dict(Counter(c["history"]["type"] for c in cases)),
            "message_subtype": dict(Counter(c["message"]["subtype"] for c in cases)),
            "target_position": dict(Counter(str(c.get("target_position")) for c in cases)),
            "target_age_bucket": dict(Counter(str(c["meta"].get("target_age_bucket")) for c in cases)),
            "name_descriptiveness": dict(Counter(str(c["meta"].get("name_descriptiveness")) for c in cases)),
            "old_thread": sum(1 for c in cases if c["meta"].get("old_thread")),
            "target_name_visible": dict(Counter(str(c["meta"].get("target_name_visible")) for c in cases)),
            "sequences": len(fs["sequences"][split]),
            "sequence_turns": dict(Counter(t["label"]["kind"] for s in fs["sequences"][split] for t in s["turns"])),
        }
    return report, problems


def generator_models(fs: dict) -> dict[str, list[str]]:
    seen: dict[str, set] = {}

    def add(prov: Optional[dict]) -> None:
        if prov and prov.get("model"):
            seen.setdefault(prov["model"], set()).add(str(prov.get("canonical_slug")))

    for split in SPLITS:
        for a in fs["agents"][split].values():
            add(a.get("name_source"))
        for c in fs["single"][split]:
            p = c["provenance"]
            add(p.get("drafted_by"))
            add(p.get("summarized_by"))
            add((p.get("cross_label") or {}).get("provenance"))
        for s in fs["sequences"][split]:
            add(s["provenance"].get("drafted_by"))
            for t in ((s["provenance"].get("cross_label") or {}).get("turns") or {}).values():
                add(t.get("provenance"))
    return {m: sorted(v) for m, v in sorted(seen.items())}


def load(fixtures_dir: Path) -> dict:
    fs: dict = {"threads": {}, "agents": {}, "agent_of_thread": {}, "rosters": {}, "single": {}, "sequences": {}}
    for split in SPLITS:
        fs["threads"][split] = {t["thread_id"]: t for t in read_rows(fixtures_dir / f"threads.{split}.jsonl")}
        agents = read_rows(fixtures_dir / f"agents.{split}.jsonl")
        fs["agents"][split] = {a["agent_id"]: a for a in agents}
        fs["agent_of_thread"][split] = {a["thread_id"]: a["agent_id"] for a in agents}
        fs["rosters"][split] = read_json(fixtures_dir / f"rosters.{split}.json")
        fs["single"][split] = read_rows(fixtures_dir / f"cases.single.{split}.jsonl")
        fs["sequences"][split] = read_rows(fixtures_dir / f"cases.sequence.{split}.jsonl")
    return fs


def check_world(fs: dict, problems: list[str]) -> None:
    for split in SPLITS:
        threads, agents = fs["threads"][split], fs["agents"][split]
        if not threads or not agents or not fs["rosters"][split]:
            problems.append(f"{split}: threads, agents or rosters missing")
            continue
        for t in threads.values():
            partner = t.get("near_distractor_of")
            if partner and (partner not in threads or threads[partner].get("near_distractor_of") != t["thread_id"]):
                problems.append(f"{t['thread_id']}: near_distractor_of is not symmetric")
        filler = fs["rosters"][split]["filler_order"]
        if len(filler) != 200 or len(set(filler)) != 200:
            problems.append(f"{split}: filler_order must hold 200 distinct agents")
        for a in filler:
            if a not in agents or agents[a].get("role") != "filler":
                problems.append(f"{split}: filler {a} is not a filler agent")
        if set(fs["rosters"][split]["filler_age_days"]) != set(filler):
            problems.append(f"{split}: filler ages don't cover filler_order")
        other = SPLITS[1 - SPLITS.index(split)]
        if set(threads) & set(fs["threads"].get(other, {})):
            problems.append("dev and test share thread ids")


def main(argv: Optional[list[str]] = None) -> int:
    parser = base_parser(__doc__, paid=False)
    parser.add_argument("--check", action="store_true", help="validate and report, write nothing")
    parser.add_argument("--update-config", action="store_true", help="write the case_set_hash into the config")
    parser.add_argument("--allow-quota-gaps", action="store_true", help="freeze even if a quota cell is short (recorded)")
    args = parser.parse_args(argv)
    fixtures_dir: Path = args.fixtures_dir
    if (fixtures_dir / MANIFEST_NAME).exists():
        print(f"{fixtures_dir} is already frozen.")
        return 1
    fs = load(fixtures_dir)
    problems: list[str] = []
    check_world(fs, problems)
    try:
        for split in SPLITS:
            for case in fs["single"][split]:
                finalize_single(case, fs, split, fixtures_dir, problems)
            for seq in fs["sequences"][split]:
                finalize_sequence(seq, fs, split, problems)
    except FreezeError as exc:
        problems.append(str(exc))
    report, quota_problems = quota_report(fs)
    if not args.allow_quota_gaps:
        problems += quota_problems
    print(json.dumps(report, indent=2))
    if problems:
        print(f"\n{len(problems)} problems:")
        for p in problems[:60]:
            print("  - " + p)
        return 1
    if args.check or args.dry_run:
        print("\ncheck passed; nothing written.")
        return 0
    for split in SPLITS:
        write_rows(fixtures_dir / f"cases.single.{split}.jsonl", fs["single"][split])
        write_rows(fixtures_dir / f"cases.sequence.{split}.jsonl", fs["sequences"][split])
    hashes = file_hashes(fixtures_dir)
    digest = case_set_hash(hashes)
    manifest = {
        "case_set_version": VERSION,
        "frozen_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "files": hashes,
        "prompt_sha256": prompt_hashes(),
        "generator_models": generator_models(fs),
        "quota_counts": report,
        "quota_gaps_allowed": bool(args.allow_quota_gaps and quota_problems),
        "quota_problems": quota_problems,
        "case_set_hash": digest,
    }
    write_json(fixtures_dir / MANIFEST_NAME, manifest)
    print(f"\nfrozen: case_set_hash {digest}")
    if args.update_config:
        config = json.loads(Path(args.config).read_text(encoding="utf-8"))
        config["case_set"]["expected_hash"] = digest
        try:
            manifest_ref = (fixtures_dir / MANIFEST_NAME).resolve().relative_to(REPO_ROOT).as_posix()
        except ValueError:
            manifest_ref = str((fixtures_dir / MANIFEST_NAME).resolve())
        config["case_set"]["manifest"] = manifest_ref
        Path(args.config).write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        print(f"updated {args.config}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
