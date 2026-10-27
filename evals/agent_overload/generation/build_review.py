"""Step 9: the label review (free, no model calls).

Three subcommands, run in order:

1. ``disagreements``: lists every item where the draft and the second labeler
   disagree, with what the interaction agent sees, in ``review/disagreements.md``.
   The implementing agent resolves each one in ``review/agent_decisions.jsonl``:
   ``{"item", "decision", "label", "note"}`` with decision ``keep_draft``,
   ``use_labeler``, ``relabel`` (give ``label`` in thread ids), ``rewritten`` (the case
   was edited by hand), ``drop`` (single-turn only; redraft it) or ``unsure``.
2. ``sheet``: applies those decisions, then writes the user's queue
   ``review/review_sheet.md`` with the unsure items plus 10 random agreed items as a
   sanity check, and a ``review/user_decisions.json`` template. Refuses if the queue
   would exceed 30 items.
3. ``apply``: applies ``review/user_decisions.json`` and reports the sanity result.

``python -m evals.agent_overload.generation.build_review disagreements``
"""

from __future__ import annotations

import argparse
import json
import random
from pathlib import Path
from typing import Optional

from ..harness.runner import apply_gold
from ..harness.state import RoutingState
from .common import SEED, SPLITS, base_parser, ensure_not_frozen, read_json, read_rows, write_json, write_rows
from .cross_label import label_state, labels_agree, load_fixture_maps

QUEUE_CAP = 30
SANITY_ITEMS = 10
HISTORY_LINES = 14


# ---------------------------------------------------------------------------
# Items


def iter_items(fixtures_dir: Path, fixtures: dict):
    """Yield (split, item_id, case, turn_or_None, state, message, draft_label, cross_label) for every labeled item."""
    for split in SPLITS:
        for case in read_rows(fixtures_dir / f"cases.single.{split}.jsonl"):
            cl = case["provenance"].get("cross_label")
            state = label_state(case, fixtures, split, case["history"], case["message"]["timestamp"])
            yield split, case["case_id"], case, None, state, case["message"], case["label"], cl
        for seq in read_rows(fixtures_dir / f"cases.sequence.{split}.jsonl"):
            state = label_state(seq, fixtures, split, seq["initial_history"], seq["turns"][0]["timestamp"])
            turns_cl = (seq["provenance"].get("cross_label") or {}).get("turns", {})
            for turn in seq["turns"]:
                yield split, f"{seq['case_id']}#t{turn['turn']}", seq, turn, state.clone(), turn["message"], turn["label"], turns_cl.get(str(turn["turn"]))
                apply_gold(state, turn, fixtures["agent_of_thread"][split])


def label_names(label: dict, state: RoutingState) -> str:
    kind = label.get("kind")
    if kind in ("REUSE", "REUSE_ANY"):
        names = []
        for t in label.get("threads", []):
            agent = state.canonical_agent(t)
            names.append(f"\"{state.by_id(agent).name}\" ({t})" if agent else f"(no agent for {t})")
        return f"{kind}({', '.join(names)})"
    if kind == "CREATE":
        return f"CREATE (new agent for thread {label['new_thread']})" if label.get("new_thread") else "CREATE (new agent)"
    return kind or "?"


def render_item(number: int, item_id: str, case: dict, turn: Optional[dict], state: RoutingState, message: dict, draft: dict, cl: Optional[dict], fixtures: dict, split: str, extra: str = "") -> str:
    threads = fixtures["threads"][split]
    lines = [f"### {number}. `{item_id}`" + (f" ({extra})" if extra else ""), ""]
    meta = (turn or case)["meta"]
    lines.append(f"- Style: {meta.get('query_style')}; message: {message.get('subtype')}")
    if state.summary_text:
        summary = state.summary_text if len(state.summary_text) < 700 else state.summary_text[:700] + " ..."
        lines.append("- Summary (start): " + summary.replace("\n", " / "))
    lines.append("- Visible history (latest entries):")
    lines.append("")
    lines.append("```")
    for e in state.entries[-HISTORY_LINES:]:
        lines.append(f"{e.timestamp} {e.tag}: {e.payload}")
    lines.append("```")
    lines.append("")
    lines.append("- New message:")
    lines.append("")
    lines.append("```")
    lines.append(message["text"])
    lines.append("```")
    lines.append("")
    relevant = []
    for agent_id in case["required_agents"] + [a.agent_id for a in state.roster if not a.seeded]:
        agent = next((a for a in state.roster if a.agent_id == agent_id), None)
        if agent and agent_id not in [r[0] for r in relevant]:
            relevant.append((agent_id, agent.name, agent.thread_id))
    lines.append("- Relevant agents (the roster also has about 195 unrelated filler agents):")
    for agent_id, name, thread in relevant:
        topic = threads.get(thread, {}).get("topic", "")
        lines.append(f"  - \"{name}\" ({thread}: {topic})")
    if draft.get("kind") == "CREATE":
        lines.append(f"  - new thread {draft['new_thread']}: {threads[draft['new_thread']]['topic']}")
    lines.append(f"- **Draft label:** {label_names(draft, state)}")
    if cl:
        lines.append(f"- **Second labeler:** {label_names(cl['label'], state) if cl['label']['kind'] != 'INVALID' else 'INVALID'} — {cl.get('reason', '')}")
    rationale = case["provenance"].get("rationale") if turn is None else None
    if rationale:
        lines.append(f"- Drafter's rationale: {rationale}")
    lines.append("")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Subcommands


def cmd_disagreements(fixtures_dir: Path) -> int:
    fixtures = load_fixture_maps(fixtures_dir)
    rows, blocks = [], []
    missing = 0
    for split, item_id, case, turn, state, message, draft, cl in iter_items(fixtures_dir, fixtures):
        if cl is None:
            missing += 1
            continue
        if cl["agreed"]:
            continue
        rows.append({"item": item_id, "split": split, "draft": draft, "labeler": cl["label"], "reason": cl.get("reason")})
        blocks.append(render_item(len(rows), item_id, case, turn, state, message, draft, cl, fixtures, split))
    header = [
        "# Label disagreements",
        "",
        f"{len(rows)} items where the draft and the second labeler disagree. Resolve each in `review/agent_decisions.jsonl`.",
        "",
    ]
    (fixtures_dir / "review").mkdir(parents=True, exist_ok=True)
    (fixtures_dir / "review" / "disagreements.md").write_text("\n".join(header + blocks), encoding="utf-8")
    write_rows(fixtures_dir / "review" / "disagreements.jsonl", rows)
    print(f"{len(rows)} disagreements written to {fixtures_dir / 'review' / 'disagreements.md'}" + (f"; {missing} items not labeled yet" if missing else ""))
    return 0


def _find(fixtures_dir: Path, item_id: str) -> tuple[str, Path, list[dict], dict, Optional[dict]]:
    case_id, _, turn = item_id.partition("#t")
    for split in SPLITS:
        kind = "sequence" if turn else "single"
        path = fixtures_dir / f"cases.{kind}.{split}.jsonl"
        rows = read_rows(path)
        for case in rows:
            if case["case_id"] == case_id:
                t = next((x for x in case["turns"] if str(x["turn"]) == turn), None) if turn else None
                return split, path, rows, case, t
    raise KeyError(item_id)


def _set_review(case: dict, turn: Optional[dict], review: dict) -> None:
    if turn is None:
        case["provenance"]["review"] = review
    else:
        reviews = case["provenance"].get("review") or {}
        reviews[str(turn["turn"])] = review
        case["provenance"]["review"] = reviews


def cmd_sheet(fixtures_dir: Path, extra_sanity: int) -> int:
    ensure_not_frozen(fixtures_dir)
    decisions = read_rows(fixtures_dir / "review" / "agent_decisions.jsonl")
    disagreements = {r["item"] for r in read_rows(fixtures_dir / "review" / "disagreements.jsonl")}
    decided = {d["item"] for d in decisions}
    undecided = sorted(disagreements - decided)
    if undecided:
        print(f"error: {len(undecided)} disagreements have no decision in agent_decisions.jsonl, e.g. {undecided[:5]}")
        return 1
    unsure = []
    dropped = []
    for d in decisions:
        split, path, rows, case, turn = _find(fixtures_dir, d["item"])
        target = turn if turn is not None else case
        decision = d["decision"]
        if decision == "unsure":
            unsure.append(d["item"])
            continue
        if decision == "drop":
            if turn is not None:
                print(f"error: {d['item']}: sequence turns can't be dropped; relabel, rewrite or mark unsure")
                return 1
            rows = [c for c in rows if c["case_id"] != case["case_id"]]
            write_rows(path, rows)
            dropped.append(d["item"])
            continue
        if decision == "use_labeler":
            target["label"] = (case["provenance"]["cross_label"] if turn is None else case["provenance"]["cross_label"]["turns"][str(turn["turn"])])["label"]
        elif decision == "relabel":
            target["label"] = d["label"]
        elif decision not in ("keep_draft", "rewritten"):
            print(f"error: {d['item']}: unknown decision {decision!r}")
            return 1
        _set_review(case, turn, {"by": "agent", "decision": decision, "note": d.get("note", "")})
        write_rows(path, rows)

    fixtures = load_fixture_maps(fixtures_dir)
    agreed = []
    by_id = {}
    for split, item_id, case, turn, state, message, draft, cl in iter_items(fixtures_dir, fixtures):
        by_id[item_id] = (split, case, turn, state, message, draft, cl)
        if cl and cl["agreed"]:
            agreed.append(item_id)
    previous = read_json(fixtures_dir / "review" / "user_decisions.json", {"items": []})
    already = {i["item"] for i in previous.get("items", []) if i.get("kind") == "sanity"}
    rng = random.Random(SEED + len(already))
    pool = sorted(i for i in agreed if i not in already)
    sanity = sorted(rng.sample(pool, min(len(pool), SANITY_ITEMS + extra_sanity)))
    queue = [(i, "unsure") for i in sorted(unsure)] + [(i, "sanity") for i in sanity]
    if len(queue) > QUEUE_CAP + extra_sanity:
        print(
            f"error: the queue would have {len(queue)} items (cap {QUEUE_CAP}). Drop the most ambiguous unsure items "
            "(decision \"drop\", then draft_cases.py --redraft) instead of spending more review time."
        )
        return 1

    blocks = []
    for number, (item_id, kind) in enumerate(queue, start=1):
        split, case, turn, state, message, draft, cl = by_id[item_id]
        extra = "unsure: the draft and the second labeler disagree" if kind == "unsure" else "sanity check: both labelers agreed"
        note = next((d.get("note") for d in decisions if d["item"] == item_id), None)
        block = render_item(number, item_id, case, turn, state, message, draft, cl, fixtures, split, extra)
        if note:
            block += f"- Agent's note: {note}\n"
        blocks.append(block)
    header = [
        "# Label review sheet",
        "",
        f"{len(unsure)} unsure items and {len(sanity)} sanity-check items. For each, read the history and the message, "
        "decide the label under the labeling rules (`generation/prompts/labeling_rules.md`), and record it in "
        "`review/user_decisions.json` (instructions in the runbook).",
        "",
        "Labels: REUSE(agent) = continue that agent's work; REUSE_ANY = any of several agents is fine; CREATE = new agent; "
        "NO_DELEGATION = answer directly.",
        "",
    ]
    (fixtures_dir / "review" / "review_sheet.md").write_text("\n".join(header + blocks), encoding="utf-8")
    template = {
        "instructions": (
            "Fill in decision for every item. unsure items: \"draft\", \"labeler\", \"label\" (then set label to "
            "{\"kind\": ..., \"agents\": [exact agent names]}) or \"drop\". sanity items: \"ok\" or \"wrong\" (and set "
            "label if wrong). note is optional."
        ),
        "items": previous.get("items", [])
        + [{"item": i, "kind": k, "decision": None, "label": None, "note": ""} for i, k in queue if i not in {x["item"] for x in previous.get("items", [])}],
    }
    write_json(fixtures_dir / "review" / "user_decisions.json", template)
    print(f"review sheet: {len(queue)} items ({len(unsure)} unsure, {len(sanity)} sanity); dropped {len(dropped)}: {dropped}")
    print(f"  {fixtures_dir / 'review' / 'review_sheet.md'}\n  {fixtures_dir / 'review' / 'user_decisions.json'}")
    return 0


def _label_from_names(label: dict, state: RoutingState) -> dict:
    kind = label["kind"]
    if kind in ("REUSE", "REUSE_ANY"):
        threads = []
        for name in label.get("agents") or []:
            agent = state.resolve_name(name)
            if agent is None:
                raise ValueError(f"unknown agent name {name!r}")
            threads.append(state.by_id(agent).thread_id)
        return {"kind": kind, "threads": sorted(set(threads))}
    if kind == "CREATE":
        if "new_thread" not in label:
            raise ValueError("a CREATE label needs new_thread (thread id)")
        return {"kind": "CREATE", "new_thread": label["new_thread"]}
    return {"kind": kind}


def cmd_apply(fixtures_dir: Path) -> int:
    ensure_not_frozen(fixtures_dir)
    data = read_json(fixtures_dir / "review" / "user_decisions.json")
    if not data:
        print("error: review/user_decisions.json not found (run build_review.py sheet)")
        return 1
    fixtures = load_fixture_maps(fixtures_dir)
    states = {item_id: (state, case, turn) for _s, item_id, case, turn, state, *_ in iter_items(fixtures_dir, fixtures)}
    open_items = [i["item"] for i in data["items"] if not i.get("decision")]
    if open_items:
        print(f"error: {len(open_items)} items have no decision yet: {open_items[:5]}")
        return 1
    for item in data["items"]:
        if item.get("applied"):
            continue
        split, path, rows, case, turn = _find(fixtures_dir, item["item"])
        target = turn if turn is not None else case
        decision = item["decision"]
        state = states[item["item"]][0]
        cl = case["provenance"]["cross_label"] if turn is None else case["provenance"]["cross_label"]["turns"][str(turn["turn"])]
        if decision == "drop":
            if turn is not None:
                print(f"error: {item['item']}: sequence turns can't be dropped")
                return 1
            write_rows(path, [c for c in rows if c["case_id"] != case["case_id"]])
            item["applied"] = True
            continue
        if decision == "labeler":
            target["label"] = cl["label"]
        elif decision == "label" or (decision == "wrong" and item.get("label")):
            target["label"] = _label_from_names(item["label"], state)
        _set_review(case, turn, {"by": "user", "decision": decision, "note": item.get("note", "")})
        write_rows(path, rows)
        item["applied"] = True
    write_json(fixtures_dir / "review" / "user_decisions.json", data)
    sanity = [i for i in data["items"] if i["kind"] == "sanity"]
    wrong_total = sum(1 for i in sanity if i["decision"] == "wrong")
    print(f"applied {len(data['items'])} decisions; sanity items wrong: {wrong_total} of {len(sanity)}")
    if wrong_total > 1:
        print("More than 1 sanity item was wrong: review 20 more agreed items together before freezing:\n"
              "  python -m evals.agent_overload.generation.build_review sheet --extra-sanity 20")
    return 0


def main(argv: Optional[list[str]] = None) -> int:
    parser = base_parser(__doc__, paid=False)
    parser.add_argument("command", choices=["disagreements", "sheet", "apply"])
    parser.add_argument("--extra-sanity", type=int, default=0, help="add this many more agreed items to the sheet")
    args = parser.parse_args(argv)
    if args.command == "disagreements":
        return cmd_disagreements(args.fixtures_dir)
    if args.command == "sheet":
        return cmd_sheet(args.fixtures_dir, args.extra_sanity)
    return cmd_apply(args.fixtures_dir)


if __name__ == "__main__":
    raise SystemExit(main())
