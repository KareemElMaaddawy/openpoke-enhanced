"""Fake-model end to end: generate fixtures, review, freeze, run, report; plus manifest, ages and side effects.

The whole pipeline runs once (setUpClass) in a temp directory with ``--fake-model``.
No API is called and nothing is written to the real spend ledger.
"""

from __future__ import annotations

import contextlib
import gzip
import io
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from evals.agent_overload import compare, run
from evals.agent_overload.generation import (
    assemble_histories,
    build_review,
    cross_label,
    draft_cases,
    draft_sequences,
    freeze,
    gen_threads,
    name_agents,
    rate_names,
    summarize_histories,
)
from evals.agent_overload.harness.fixtures import FixtureError, load_fixtures
from evals.agent_overload.harness.state import RESULT_PREFIXES
from evals.agent_overload.harness.util import REPO_ROOT, EVAL_ROOT, age_days, read_jsonl, sha256_file

CONFIG = EVAL_ROOT / "configs" / "baseline_names_only.json"


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = fn(*args)
    return code, out.getvalue()


def data_snapshot() -> dict[str, str]:
    root = REPO_ROOT / "server" / "data"
    return {p.relative_to(root).as_posix(): sha256_file(p) for p in sorted(root.rglob("*")) if p.is_file()}


class EndToEndTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.fixtures = root / "v1"
        cls.config = root / "config.json"
        cls.ledger = root / "ledger.jsonl"
        cls.results = root / "results"
        shutil.copy(CONFIG, cls.config)
        common = ["--fixtures-dir", str(cls.fixtures), "--config", str(cls.config)]
        paid = common + ["--fake-model", "--ledger", str(cls.ledger)]
        cls.data_before = data_snapshot()
        for module in (gen_threads, name_agents, rate_names, draft_cases, draft_sequences):
            code, out = quiet(module.main, paid)
            assert code == 0, (module.__name__, out[-2000:])
        code, out = quiet(assemble_histories.main, common)
        assert code == 0, out
        for module in (summarize_histories, cross_label):
            code, out = quiet(module.main, paid)
            assert code == 0, (module.__name__, out[-2000:])
        code, out = quiet(build_review.main, ["disagreements"] + common)
        assert code == 0, out
        review = cls.fixtures / "review"
        rows = read_jsonl(review / "disagreements.jsonl")
        decisions = [{"item": r["item"], "decision": "unsure" if i < 2 else "keep_draft", "note": "test"} for i, r in enumerate(rows)]
        (review / "agent_decisions.jsonl").write_text("".join(json.dumps(d) + "\n" for d in decisions))
        code, out = quiet(build_review.main, ["sheet"] + common)
        assert code == 0, out
        user = json.loads((review / "user_decisions.json").read_text())
        for item in user["items"]:
            item["decision"] = "draft" if item["kind"] == "unsure" else "ok"
        (review / "user_decisions.json").write_text(json.dumps(user))
        code, out = quiet(build_review.main, ["apply"] + common)
        assert code == 0, out
        code, out = quiet(freeze.main, common + ["--update-config"])
        assert code == 0, out[-3000:]
        code, out = quiet(
            run.main,
            ["--config", str(cls.config), "--profile", "smoke", "--fake-model", "--results-dir", str(cls.results), "--ledger", str(cls.ledger)],
        )
        assert code == 0, out[-3000:]
        cls.run_dir = next(cls.results.iterdir())
        cls.data_after = data_snapshot()

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # -- results ----------------------------------------------------------

    def test_results_metrics_and_report_written(self):
        for name in ("config.json", "turns.jsonl.gz", "sequences.jsonl.gz", "calls.jsonl.gz", "metrics.json", "report.md"):
            self.assertTrue((self.run_dir / name).exists(), name)
        metrics = json.loads((self.run_dir / "metrics.json").read_text())
        self.assertIn("dev", metrics["single"])
        self.assertIn("accuracy", metrics["single"]["dev"]["10"])
        self.assertIn("carried", metrics["sequence"]["dev"])
        self.assertIn("duplicates", metrics["sequence"]["dev"])
        report = (self.run_dir / "report.md").read_text()
        for section in ("## 1. Run identity", "## 2. Headline", "## 3. Accuracy drop point", "## 6. Sequences", "## 10. Costs"):
            self.assertIn(section, report)
        self.assertIn("FAKE MODEL", report)
        config = json.loads((self.run_dir / "config.json").read_text())
        self.assertTrue(config["fake_model"])
        self.assertEqual(config["end"]["turns"], 68)  # 10 single x 2 N + 1 sequence x 12 turns x 2 N x 2 modes

    def test_turn_records_cover_every_unit(self):
        with gzip.open(self.run_dir / "turns.jsonl.gz", "rt") as fh:
            turns = [json.loads(line) for line in fh]
        suites = {t["suite"] for t in turns}
        self.assertEqual(suites, {"single", "sequence", "token_probe"})
        single = [t for t in turns if t["suite"] == "single"]
        self.assertTrue(all(t["primary_outcome"] for t in single))
        self.assertTrue(all(t["roster_size"] == t["N"] for t in single))

    def test_no_ledger_writes_and_no_server_data_changes(self):
        self.assertFalse(self.ledger.exists())
        self.assertEqual(self.data_before, self.data_after)

    def test_spend_cap_stops_cleanly(self):
        results = Path(self.tmp.name) / "capped"
        code, out = quiet(
            run.main,
            ["--config", str(self.config), "--profile", "smoke", "--fake-model", "--max-cost", "0.002",
             "--results-dir", str(results), "--ledger", str(self.ledger)],
        )
        self.assertEqual(code, run.EXIT_CAPPED, out[-1500:])
        run_dir = next(results.iterdir())
        report = (run_dir / "report.md").read_text()
        self.assertIn("CAPPED", report)
        config = json.loads((run_dir / "config.json").read_text())
        self.assertTrue(config["end"]["capped"])
        self.assertLess(config["end"]["turns"], 68)

    def test_compare_refuses_fake_runs(self):
        code, out = quiet(compare.main, [str(self.run_dir), str(self.run_dir)])
        self.assertEqual(code, 2)
        self.assertIn("fake model", out)

    # -- manifest ---------------------------------------------------------

    def test_manifest_loads_and_one_byte_change_fails(self):
        manifest = self.fixtures / "MANIFEST.json"
        fs = load_fixtures(manifest, expected_hash=json.loads(self.config.read_text())["case_set"]["expected_hash"])
        self.assertEqual(len(fs.single["test"]), 120)
        target = self.fixtures / "chitchat.jsonl"
        original = target.read_bytes()
        try:
            target.write_bytes(original[:-2] + (b"X" if original[-2:-1] != b"X" else b"Y") + original[-1:])
            with self.assertRaises(FixtureError):
                load_fixtures(manifest)
        finally:
            target.write_bytes(original)
        load_fixtures(manifest)

    def test_frozen_dir_refuses_generation(self):
        with self.assertRaises(Exception):
            assemble_histories.ensure_not_frozen(self.fixtures)

    # -- quotas and ages --------------------------------------------------

    def test_quotas(self):
        manifest = json.loads((self.fixtures / "MANIFEST.json").read_text())
        test = manifest["quota_counts"]["test"]
        self.assertEqual(test["cells"]["REUSE|explicit"], 18)
        self.assertEqual(test["cells"]["NO_DELEGATION|any"], 12)
        self.assertEqual(test["history_type"], {"short": 84, "summarized": 36})
        self.assertEqual(test["message_subtype"], {"user": 104, "execution_result": 8, "email_alert": 8})
        self.assertEqual(test["old_thread"], 11)
        self.assertEqual(manifest["quota_counts"]["dev"]["old_thread"], 6)

    def test_ages(self):
        fs = load_fixtures(self.fixtures / "MANIFEST.json")
        for split in ("dev", "test"):
            agents = fs.agents[split]
            for case in fs.single[split]:
                raw = case["history"]["entries"]
                if case["history"]["type"] == "summarized":
                    raw = read_jsonl(self.fixtures / "review" / "raw_histories" / f"{case['case_id']}.jsonl")
                for agent_id, times in case["agent_times"].items():
                    self.assertLessEqual(times["created_at"], times["last_active"])
                    name = agents[agent_id]["name"]
                    stamps = [
                        e["timestamp"] for e in raw
                        if e["tag"] == "agent_message" and any(
                            line.startswith(tuple(p + name + ": " for p in RESULT_PREFIXES)) for line in e["payload"].split("\n")
                        )
                    ]
                    if stamps:
                        self.assertEqual(times["last_active"], max(stamps), (case["case_id"], agent_id))
                        self.assertLessEqual(times["created_at"], min(stamps))
                    else:
                        self.assertIn(agent_id, case["agent_ages"])
                if case["meta"].get("old_thread"):
                    target = fs.agent_of_thread[split][case["label"]["threads"][0]]
                    age = age_days(case["agent_times"][target]["last_active"], case["message"]["timestamp"])
                    self.assertTrue(15 <= age <= 60, (case["case_id"], age))
                    self.assertFalse(case["meta"]["target_name_visible"])
                    self.assertEqual(case["meta"]["target_age_bucket"], "old")

    def test_sequences_update_last_active_on_delegation(self):
        from evals.agent_overload.harness.runner import apply_gold
        from evals.agent_overload.harness.state import initial_state

        fs = load_fixtures(self.fixtures / "MANIFEST.json")
        seq = fs.sequences["dev"][0]
        state = initial_state(
            roster_ids=list(seq["required_agents"]), agents=fs.agents["dev"], agent_times=seq["agent_times"],
            filler_age_days={}, now=seq["turns"][0]["timestamp"], history=seq["initial_history"],
        )
        for turn in seq["turns"]:
            apply_gold(state, turn, fs.agent_of_thread["dev"])
            label = turn["label"]
            if label["kind"] in ("REUSE", "REUSE_ANY"):
                agent = state.by_id(state.canonical_agent(label["threads"][0]))
            elif label["kind"] == "CREATE":
                agent = state.by_id(fs.agent_of_thread["dev"][label["new_thread"]])
                self.assertEqual(agent.created_at, turn["timestamp"])
            else:
                continue
            self.assertEqual(agent.last_active, turn["timestamp"])

if __name__ == "__main__":
    unittest.main()
