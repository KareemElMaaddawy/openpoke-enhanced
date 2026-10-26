"""Print a summary of what the generation steps have written so far (free, read-only).

``python -m evals.agent_overload.generation.inspect_fixtures [threads|agents|cases|sequences|labels|all]``

Counts, distributions and a few random samples per artifact, for checking a step's
output before running the next one.
"""

from __future__ import annotations

import argparse
import json
import random
from collections import Counter
from pathlib import Path
from typing import Optional

from .common import FIXTURES_DIR, SPLITS, read_json, read_rows

SAMPLES = 3


def _sample(rows: list, k: int = SAMPLES, seed: int = 1) -> list:
    return random.Random(seed).sample(rows, min(k, len(rows)))


def threads(d: Path) -> None:
    print("## threads")
    for split in SPLITS:
        rows = read_rows(d / f"threads.{split}.jsonl")
        if not rows:
            print(f"{split}: not written yet")
            continue
        roles = Counter(r["role"] for r in rows)
        paired = sum(1 for r in rows if r.get("near_distractor_of"))
        print(f"{split}: {len(rows)} threads {dict(roles)}, {paired // 2} near-distractor pairs, categories {dict(Counter(r['category'] for r in rows))}")
        for r in _sample([r for r in rows if r["role"] == "case"]):
            print(f"  [{r['thread_id']}] {r['topic']} | \"{r['opening_request']}\" -> {r['canned_result']}")
        pairs = [r for r in rows if r.get("near_distractor_of")]
        for r in _sample(pairs, 2):
            other = next(o for o in rows if o["thread_id"] == r["near_distractor_of"])
            print(f"  pair: {r['topic']}  <->  {other['topic']}")
    chit = read_rows(d / "chitchat.jsonl")
    if chit:
        kinds = Counter(c["kind"] for c in chit)
        print(f"chitchat: {dict(kinds)}; e.g. " + " | ".join(f"\"{c['user']}\" -> \"{c['reply']}\"" for c in _sample([c for c in chit if c['kind'] == 'exchange'], 2)))


def agents(d: Path) -> None:
    print("## agents")
    for split in SPLITS:
        rows = read_rows(d / f"agents.{split}.jsonl")
        if not rows:
            print(f"{split}: not written yet")
            continue
        naming = read_json(d / "review" / "naming" / f"{split}.json", {})
        attempts = Counter(v.get("attempts") for v in naming.values())
        statuses = Counter(v.get("status") for v in naming.values())
        cleaning = read_json(d / "review" / f"filler_cleaning.{split}.json", {})
        print(
            f"{split}: {len(rows)} agents {dict(Counter(r['role'] for r in rows))}; naming {dict(statuses)}, attempts {dict(sorted(attempts.items()))}; "
            f"filler removed {len(cleaning.get('removed', []))}; descriptiveness {dict(Counter(str(r.get('descriptiveness')) for r in rows if r['role'] == 'case'))}"
        )
        threads = {t["thread_id"]: t for t in read_rows(d / f"threads.{split}.jsonl")}
        for r in _sample(rows, 6):
            print(f"  \"{r['name']}\"  ({r['role']}, {r.get('descriptiveness')}) for: {threads[r['thread_id']]['opening_request']}")
        rosters = read_json(d / f"rosters.{split}.json")
        if rosters:
            ages = list(rosters["filler_age_days"].values())
            print(f"  roster: {len(rosters['filler_order'])} filler, ages 0-3d {sum(a <= 3 for a in ages)}, 4-14d {sum(3 < a <= 14 for a in ages)}, 15-60d {sum(a > 14 for a in ages)}")


def cases(d: Path) -> None:
    print("## single-turn cases")
    for split in SPLITS:
        rows = read_rows(d / f"cases.single.{split}.jsonl")
        if not rows:
            print(f"{split}: not written yet")
            continue
        cells = Counter(f"{c['label']['kind']}/{c['meta']['query_style']}" for c in rows)
        print(
            f"{split}: {len(rows)} cases; {dict(sorted(cells.items()))}\n"
            f"  history {dict(Counter(c['history']['type'] for c in rows))}, "
            f"summarized done {sum(1 for c in rows if c['history'].get('summary_text'))}, "
            f"subtypes {dict(Counter(c['message']['subtype'] for c in rows))}, old {sum(1 for c in rows if c['meta'].get('old_thread'))}"
        )
        failures = read_rows(d / "review" / "draft_failures.jsonl")
        if failures:
            print(f"  draft failures: {len(failures)}: " + "; ".join(f"{f['case_id']}: {f['error'][:80]}" for f in failures[:5]))
        for c in _sample(rows):
            tail = c["history"]["entries"][-4:]
            print(f"  [{c['case_id']}] {c['label']} {c['meta']['query_style']} / {c['message']['subtype']}")
            for e in tail:
                print(f"      {e['tag']}: {e['payload'][:110]}")
            print(f"    >> {c['message']['text'][:160]}")


def sequences(d: Path) -> None:
    print("## sequences")
    for split in SPLITS:
        rows = read_rows(d / f"cases.sequence.{split}.jsonl")
        if not rows:
            print(f"{split}: not written yet")
            continue
        print(f"{split}: {len(rows)} sequences, initial histories assembled {sum(1 for s in rows if s['initial_history']['entries'])}")
        s = _sample(rows, 1)[0]
        print(f"  [{s['case_id']}]")
        for t in s["turns"]:
            print(f"    t{t['turn']} {t['label']} {t['meta']['query_style']}: {t['message']['text'][:100]}  ->  {(t['gold']['result_text'] or '')[:60]}")


def labels(d: Path) -> None:
    print("## second labels")
    summary = read_json(d / "review" / "cross_label_summary.json")
    if not summary:
        print("not run yet")
        return
    print(json.dumps(summary))
    for split in SPLITS:
        rows = read_rows(d / f"cases.single.{split}.jsonl")
        disagree = [c for c in rows if (c["provenance"].get("cross_label") or {}).get("agreed") is False]
        by_kind = Counter(c["label"]["kind"] for c in disagree)
        print(f"{split}: single-turn disagreements by draft label {dict(by_kind)}")


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("what", nargs="?", default="all", choices=["threads", "agents", "cases", "sequences", "labels", "all"])
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES_DIR)
    args = parser.parse_args(argv)
    sections = {"threads": threads, "agents": agents, "cases": cases, "sequences": sequences, "labels": labels}
    for name, fn in sections.items():
        if args.what in (name, "all"):
            fn(args.fixtures_dir)
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
