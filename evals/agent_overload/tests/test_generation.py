"""Generation logic: plans meet the quotas, drafts are checked, histories assemble, paid commands are gated."""

from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from collections import Counter
from pathlib import Path

from evals.agent_overload import run
from evals.agent_overload.generation import (
    assemble_histories,
    common,
    cross_label,
    draft_cases,
    draft_sequences,
    gen_threads,
    name_agents,
    planning,
    rate_names,
    summarize_histories,
)
from evals.agent_overload.harness.spend import EXIT_NOT_CONFIRMED
from evals.agent_overload.harness.util import EVAL_ROOT, parse_ts

PAID_SCRIPTS = [gen_threads, name_agents, rate_names, draft_cases, draft_sequences, summarize_histories, cross_label]


def world(split: str):
    """A synthetic thread catalog with the design's counts, all named."""
    case_n = gen_threads.CASE_TOTALS[split]
    pairs = gen_threads.PAIR_TOTALS[split]
    threads = {}
    for i in range(case_n):
        tid = f"t-{split}-{i + 1:04d}"
        threads[tid] = {"thread_id": tid, "role": "case", "near_distractor_of": None, "topic": f"topic {i}",
                        "opening_request": f"request {i}", "canned_result": f"result {i}", "result_reply": "ok",
                        "follow_ups": [{"request": f"follow-up {j} on {i}", "result": "r", "reply": "ok"} for j in range(3)]}
    ids = sorted(threads)
    for p in range(pairs):
        a, b = ids[2 * p], ids[2 * p + 1]
        threads[a]["near_distractor_of"], threads[b]["near_distractor_of"] = b, a
    for i in range(210):
        tid = f"t-{split}-{201 + i:04d}"
        threads[tid] = {"thread_id": tid, "role": "filler", "near_distractor_of": None, "topic": f"filler {i}"}
    agent_of = {t: "a-" + t[2:] for t in threads}
    return threads, agent_of


class PlanningTest(unittest.TestCase):
    def test_single_quotas_and_cross_quotas(self):
        for split, total in (("test", 120), ("dev", 60)):
            threads, agent_of = world(split)
            plans = planning.case_plans(split, threads, agent_of)
            self.assertEqual(len(plans), total)
            cells = Counter((p.kind, p.style) for p in plans)
            for kind, style, test_n, dev_n in planning.QUOTA_CELLS:
                self.assertEqual(cells[(kind, style)], test_n if split == "test" else dev_n, (split, kind, style))
            self.assertEqual(sum(p.history_type == "summarized" for p in plans), round(total * 0.3))
            subtypes = Counter(p.subtype for p in plans)
            self.assertEqual(subtypes["execution_result"], 8 if split == "test" else 4)
            self.assertEqual(subtypes["email_alert"], 8 if split == "test" else 4)
            no_deleg = [p for p in plans if p.kind == "NO_DELEGATION"]
            self.assertEqual(sum(p.subtype == "user" for p in no_deleg), 3 if split == "test" else 1)
            old = Counter(p.style for p in plans if p.old)
            self.assertEqual(dict(old), planning.OLD_THREAD_CASES[split])
            self.assertTrue(all(p.subtype == "user" for p in plans if p.old))

    def test_positions_balanced_within_style_and_required_limit(self):
        threads, agent_of = world("test")
        plans = planning.case_plans("test", threads, agent_of)
        for (kind, style), group in _groups(plans).items():
            positions = Counter(p.target_position for p in group)
            if kind in ("REUSE", "REUSE_ANY") or (kind, style) == ("CREATE", "near_distractor"):
                self.assertNotIn(None, positions)
                self.assertLessEqual(max(positions.values()) - min(positions.values()), 1, (kind, style, positions))
            else:
                self.assertEqual(set(positions), {None})
        for p in plans:
            self.assertLessEqual(len(p.required_threads()), planning.MAX_REQUIRED_SINGLE, p.case_id)
            if p.old:
                self.assertIn(p.targets[0], p.forbidden_threads)
                self.assertNotIn(p.targets[0], p.history_threads)
                self.assertGreaterEqual(p.aged_threads[p.targets[0]], 15)
            if p.kind == "CREATE":
                self.assertNotIn(p.new_thread, p.required_threads())

    def test_plans_are_deterministic_and_avoid_sequence_threads(self):
        threads, agent_of = world("dev")
        a = [p.to_dict() for p in planning.case_plans("dev", threads, agent_of)]
        b = [p.to_dict() for p in planning.case_plans("dev", threads, agent_of)]
        self.assertEqual(a, b)
        reserved = planning.reserved_threads("dev", threads, agent_of)
        self.assertEqual(len(reserved), 2 * planning.SEQUENCE_COUNTS["dev"])
        for p in planning.case_plans("dev", threads, agent_of):
            self.assertFalse(set(p.required_threads()) & reserved)
            self.assertNotIn(p.new_thread, reserved)

    def test_sequence_plans(self):
        threads, agent_of = world("test")
        plans = planning.sequence_plans("test", threads, agent_of)
        self.assertEqual(len(plans), 8)
        for plan in plans:
            kinds = Counter(t["label"]["kind"] for t in plan.turns)
            self.assertEqual(len(plan.turns), 12)
            self.assertEqual(kinds["CREATE"], 2)
            self.assertGreaterEqual(kinds["REUSE"], 6)
            self.assertEqual(kinds["REUSE_ANY"], 1)
            self.assertGreaterEqual(kinds["NO_DELEGATION"], 2)
            self.assertTrue(any(t["subtype"] == "email_alert" for t in plan.turns))
            self.assertTrue(any(t["style"] == "near_distractor" for t in plan.turns))
            stamps = [t["timestamp"] for t in plan.turns]
            self.assertEqual(stamps, sorted(stamps))
            delegating = [t for t in plan.turns if t["label"]["kind"] != "NO_DELEGATION"]
            switches = sum(1 for prev, cur in zip(delegating, delegating[1:]) if prev["primary_thread"] != cur["primary_thread"])
            self.assertGreaterEqual(switches, len(delegating) / 2)
            # every reused created thread is reused after its CREATE turn
            created_at = {t["label"]["new_thread"]: t["turn"] for t in plan.turns if t["label"]["kind"] == "CREATE"}
            for t in plan.turns:
                for thread in t["label"].get("threads", []):
                    if thread in created_at:
                        self.assertGreater(t["turn"], created_at[thread])
            implicit = [t for t in plan.turns if t["style"] == "implicit_follow_up"]
            for t in implicit:
                previous = [d for d in delegating if d["turn"] < t["turn"]][-1]
                self.assertEqual(previous["primary_thread"], t["primary_thread"])  # resolvable from the last result


def _groups(plans):
    out = {}
    for p in plans:
        out.setdefault((p.kind, p.style), []).append(p)
    return out


class DraftValidationTest(unittest.TestCase):
    def setUp(self):
        threads, agent_of = world("test")
        self.plans = planning.case_plans("test", threads, agent_of)
        self.names = {t: f"Agent {t}" for t in threads}

    def plan(self, **want):
        return next(p for p in self.plans if all(getattr(p, k) == v for k, v in want.items()))

    def delegated(self, thread):
        return {"kind": "delegated", "thread": thread, "user": "u", "ack": "a", "result": "r", "reply": "y"}

    def test_valid_and_rejected_drafts(self):
        plan = self.plan(kind="REUSE", style="implicit_follow_up", subtype="user")
        tail = [self.delegated(t) for t in plan.history_threads]
        ok = draft_cases.validate_draft({"tail": tail, "message": "reply to that", "rationale": "x"}, plan, self.names)
        self.assertEqual(ok["message"], "reply to that")
        bad_order = list(reversed(tail)) if len(tail) > 1 else None
        if bad_order:
            with self.assertRaises(common.GenerationError):
                draft_cases.validate_draft({"tail": bad_order, "message": "m"}, plan, self.names)
        with self.assertRaises(common.GenerationError):
            draft_cases.validate_draft({"tail": tail + [self.delegated("t-test-0999")], "message": "m"}, plan, self.names)
        with self.assertRaises(common.GenerationError):
            draft_cases.validate_draft({"error": "can't"}, plan, self.names)
        with self.assertRaises(common.GenerationError):
            draft_cases.validate_draft({"tail": tail[:-1] or [], "message": "m"}, plan, self.names)

    def test_old_case_rejects_target_name_in_tail(self):
        plan = self.plan(kind="REUSE", style="explicit", old=True)
        tail = [self.delegated(t) for t in plan.history_threads]
        tail[0]["result"] = "also " + self.names[plan.targets[0]]
        with self.assertRaises(common.GenerationError):
            draft_cases.validate_draft({"tail": tail, "message": "m"}, plan, self.names)

    def test_execution_result_needs_pending_last(self):
        plan = self.plan(kind="REUSE", subtype="execution_result")
        tail = [self.delegated(t) for t in plan.history_threads]
        with self.assertRaises(common.GenerationError):
            draft_cases.validate_draft({"tail": tail, "message": "found"}, plan, self.names)
        tail.append({"kind": "pending", "thread": plan.message_thread, "user": "find it and forward it", "ack": "on it"})
        draft = draft_cases.validate_draft({"tail": tail, "message": "found"}, plan, self.names)
        entries = draft_cases.render_entries(plan, draft["tail"], self.names)
        self.assertEqual(entries[-1]["tag"], "poke_reply")
        self.assertLess(entries[-1]["timestamp"], plan.now)
        stamps = [e["timestamp"] for e in entries]
        self.assertEqual(stamps, sorted(stamps))
        message = draft_cases.render_message(plan, "found", self.names)
        self.assertEqual(message["text"], f"[SUCCESS] {self.names[plan.message_thread]}: found")
        self.assertEqual(message["type"], "agent")

    def test_extract_json(self):
        self.assertEqual(common.extract_json('sure!\n```json\n{"a": [1, 2]}\n```'), {"a": [1, 2]})
        self.assertEqual(common.extract_json('{"a": 1} trailing'), {"a": 1})
        with self.assertRaises(common.GenerationError):
            common.extract_json("no json here")


class AssembleTest(unittest.TestCase):
    def test_assembled_history_shape(self):
        threads, _ = world("test")
        chosen = [threads[t] for t in sorted(threads)[:4]]
        names = {t["thread_id"]: f"Agent {t['thread_id']}" for t in chosen}
        chitchat = [{"kind": "exchange", "user": f"hi {i}", "reply": "hey"} for i in range(60)] + [{"kind": "ack", "text": "on it"}]
        entries = assemble_histories.assemble("q-test-001", 96, chosen, names, chitchat, "2026-10-20 10:00:00")
        self.assertEqual(len(entries), 96)
        stamps = [e["timestamp"] for e in entries]
        self.assertEqual(stamps, sorted(stamps))
        self.assertLess(stamps[-1], "2026-10-20 10:00:00")
        self.assertGreaterEqual(parse_ts(stamps[0]), parse_ts("2026-10-17 08:00:00"))
        for e in entries:
            self.assertTrue(8 <= parse_ts(e["timestamp"]).hour < 22)
        results = [e for e in entries if e["tag"] == "agent_message"]
        self.assertEqual(len(results), 16)
        for t in chosen:  # each thread starts with its opening request
            first = next(e for e in entries if e["tag"] == "user_message" and e["payload"] in [t["opening_request"]] + [u["request"] for u in t["follow_ups"]])
            self.assertEqual(first["payload"], t["opening_request"])
        again = assemble_histories.assemble("q-test-001", 96, chosen, names, chitchat, "2026-10-20 10:00:00")
        self.assertEqual(entries, again)

    def test_summarized_length_keeps_raw_at_least_110(self):
        for tail in (4, 8, 16):
            n = assemble_histories.summarized_length("s-test-0001", tail)
            self.assertGreaterEqual(n + tail, 110)
            self.assertTrue(100 <= n <= 126 and n % 2 == 0)


class PaidGateTest(unittest.TestCase):
    def run_main(self, module, argv):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            try:
                code = module.main(argv)
            except SystemExit as exc:
                code = exc.code
        return code, out.getvalue()

    def test_every_paid_script_dry_runs_and_refuses_without_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            empty = Path(tmp) / "v1"
            ledger = Path(tmp) / "ledger.jsonl"
            for module in PAID_SCRIPTS:
                code, out = self.run_main(module, ["--fixtures-dir", str(empty), "--dry-run", "--ledger", str(ledger)])
                self.assertEqual(code, 0, (module.__name__, out))
                self.assertIn("dry run: no API was called.", out)
                self.assertIn("estimated cost:", out)
                code, out = self.run_main(module, ["--fixtures-dir", str(empty), "--ledger", str(ledger)])
                self.assertEqual(code, EXIT_NOT_CONFIRMED, module.__name__)
                self.assertIn("Refusing to call any API", out)
            self.assertFalse(ledger.exists())

    def test_run_py_dry_run_and_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            config = str(EVAL_ROOT / "configs" / "baseline_names_only.json")
            code, out = self.run_main(run, ["--config", config, "--profile", "full", "--dry-run", "--manifest", str(Path(tmp) / "none.json"), "--ledger", str(ledger)])
            self.assertEqual(code, 0, out)
            self.assertIn("single turns 2160, sequence turns 2304 (192 sequence-runs), token probes 180", out)
            code, out = self.run_main(run, ["--config", config, "--profile", "smoke", "--manifest", str(Path(tmp) / "none.json"), "--ledger", str(ledger)])
            self.assertEqual(code, 1)  # fixtures not frozen: refuses before any spend question

    def test_test_ledger_blocks_second_config(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "test_ledger.jsonl"
            ledger.write_text('{"run_id": "r1", "method": "names_only", "method_version": "1", "config_hash": "aaa"}\n')
            config = {"method": {"name": "names_only", "version": "1"}}
            self.assertIsNone(run.check_test_ledger(config, "aaa", ledger))
            self.assertIn("different config hash", run.check_test_ledger(config, "bbb", ledger))
            self.assertIsNone(run.check_test_ledger({"method": {"name": "names_only", "version": "2"}}, "bbb", ledger))


if __name__ == "__main__":
    unittest.main()
