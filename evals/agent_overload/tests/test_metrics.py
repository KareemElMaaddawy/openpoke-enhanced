"""Metric aggregation, bootstrap CIs, drop point, tokens and sequence statistics."""

from __future__ import annotations

import unittest

from evals.agent_overload.harness import metrics as m

STATS = m.StatsConfig(resamples=400, ci=0.95, seed=20261025)


def turn(case_id, n, rep, correct, outcome=None, kind="REUSE", split="test", suite="single", **extra):
    outcome = outcome or ("correct_reuse" if correct else "misroute")
    record = {
        "split": split,
        "suite": suite,
        "case_id": case_id,
        "turn": extra.pop("turn_index", None),
        "mode": extra.pop("mode", None),
        "N": n,
        "rep": rep,
        "label": {"kind": kind},
        "primary_outcome": outcome,
        "outcomes": [{"outcome": outcome, "tags": []}],
        "tags": extra.pop("tags", []),
        "turn_correct": correct,
        "turn_correct_lenient": correct or outcome == "duplicate_reuse",
        "status": extra.pop("status", "ok"),
        "dims": extra.pop("dims", {"query_style": "explicit"}),
        "prompt_tokens": extra.pop("prompt_tokens", 5000),
        "completion_tokens": 300,
        "cost": 0.001,
        "latency_ms": 2000,
        "n_calls": 2,
        "routing_calls": 2,
        "first_call_prompt_tokens": extra.pop("first_call_prompt_tokens", None),
        "agents_shown": n,
        "dormant_fraction": 0.4,
        "recency_eligible": extra.pop("recency_eligible", False),
    }
    record.update(extra)
    return record


def accuracy_grid(acc_by_n: dict[int, float], templates: int = 40, reps: int = 2) -> list[dict]:
    """Templates 0..k-1 correct at each N, where k = acc * templates (identical across reps)."""
    turns = []
    for n, acc in acc_by_n.items():
        correct_templates = round(acc * templates)
        for i in range(templates):
            for rep in range(reps):
                turns.append(turn(f"s-{i:03d}", n, rep, i < correct_templates))
    return turns


class BootstrapTest(unittest.TestCase):
    def test_ratio_value_and_ci_bracket(self):
        boot = m.Bootstrap([f"c{i}" for i in range(30)], STATS)
        num = {f"c{i}": 1.0 for i in range(20)}
        den = {f"c{i}": 1.0 for i in range(30)}
        res = boot.ratio(num, den)
        self.assertAlmostEqual(res["value"], 20 / 30)
        self.assertLess(res["ci"][0], res["value"])
        self.assertGreater(res["ci"][1], res["value"])

    def test_deterministic(self):
        a = m.Bootstrap(["x", "y", "z"], STATS)
        b = m.Bootstrap(["z", "y", "x"], STATS)
        self.assertEqual(a.weights, b.weights)

    def test_empty_denominator(self):
        boot = m.Bootstrap(["a"], STATS)
        self.assertEqual(boot.ratio({}, {})["value"], None)

    def test_quantile(self):
        boot = m.Bootstrap(["a", "b"], STATS)
        res = boot.quantile({"a": [1.0, 2.0, 3.0], "b": [10.0]}, 50)
        self.assertEqual(res["value"], 2.5)
        self.assertEqual(res["n"], 4)


class RoutingMetricsTest(unittest.TestCase):
    def test_rates_use_their_denominators(self):
        turns = [
            turn("s1", 10, 0, True),
            turn("s2", 10, 0, False, "false_spawn", tags=["near_duplicate"]),
            turn("s3", 10, 0, False, "misroute", tags=["recency"], recency_eligible=True),
            turn("s4", 10, 0, False, "false_reuse", kind="CREATE"),
            turn("s5", 10, 0, True, "correct_create", kind="CREATE"),
            turn("s6", 10, 0, False, "missed_delegation", kind="CREATE"),
            turn("s7", 10, 0, True, "correct_no_delegation", kind="NO_DELEGATION"),
            turn("s8", 10, 0, None, status="api_error"),
        ]
        boot = m.Bootstrap([t["case_id"] for t in turns], STATS)
        res = m.routing_metrics(boot, turns)
        self.assertEqual(res["scored_turns"], 7)
        self.assertEqual(res["api_error_turns"], 1)
        self.assertAlmostEqual(res["accuracy"]["value"], 3 / 7)
        self.assertAlmostEqual(res["false_spawn_rate"]["value"], 1 / 3)
        self.assertAlmostEqual(res["misroute_rate"]["value"], 1 / 3)
        self.assertAlmostEqual(res["false_reuse_rate"]["value"], 1 / 3)
        self.assertAlmostEqual(res["missed_delegation_rate"]["value"], 1 / 6)
        self.assertAlmostEqual(res["near_duplicate_share"]["value"], 1.0)
        self.assertAlmostEqual(res["recency_lock_rate"]["value"], 1.0)
        self.assertEqual(res["confusion"]["CREATE"]["false_reuse"], 1)
        self.assertEqual(res["confusion"]["NO_DELEGATION"]["correct_no_delegation"], 1)
        self.assertNotIn("recall_at_k", res)

    def test_extra_and_invalid_rates_count_turns(self):
        t1 = turn("s1", 10, 0, False)
        t1["outcomes"] = [
            {"outcome": "invalid_call", "tags": []},
            {"outcome": "invalid_call", "tags": []},
            {"outcome": "correct_reuse", "tags": []},
            {"outcome": "extra_delegation", "tags": []},
        ]
        t2 = turn("s2", 10, 0, True)
        boot = m.Bootstrap(["s1", "s2"], STATS)
        res = m.routing_metrics(boot, [t1, t2])
        self.assertAlmostEqual(res["invalid_call_rate"]["value"], 0.5)
        self.assertAlmostEqual(res["extra_delegation_rate"]["value"], 0.5)

    def test_consistency(self):
        turns = [
            turn("s1", 10, 0, True),
            turn("s1", 10, 1, True),
            turn("s2", 10, 0, True),
            turn("s2", 10, 1, False),
        ]
        boot = m.Bootstrap(["s1", "s2"], STATS)
        self.assertAlmostEqual(m.consistency(boot, turns)["value"], 0.5)
        self.assertIsNone(m.consistency(boot, turns[::2])["value"])  # one rep each

    def test_recall_at_k_when_candidates_reported(self):
        turns = [
            turn("s1", 10, 0, True, has_candidates=True, candidate_rank=1),
            turn("s2", 10, 0, False, has_candidates=True, candidate_rank=4),
            turn("s3", 10, 0, False, has_candidates=True, candidate_rank=None),
        ]
        boot = m.Bootstrap(["s1", "s2", "s3"], STATS)
        res = m.routing_metrics(boot, turns)
        self.assertAlmostEqual(res["recall_at_k"]["1"]["value"], 1 / 3)
        self.assertAlmostEqual(res["recall_at_k"]["5"]["value"], 2 / 3)

    def test_breakdowns(self):
        turns = [
            turn("s1", 10, 0, True, dims={"query_style": "explicit"}),
            turn("s2", 10, 0, False, dims={"query_style": "paraphrased"}),
            turn("s3", 10, 0, True, dims={"query_style": "paraphrased"}),
            turn("s4", 10, 0, True, dims={}),
        ]
        boot = m.Bootstrap(["s1", "s2", "s3", "s4"], STATS)
        res = m.breakdowns(boot, turns, ("query_style",))["query_style"]
        self.assertEqual(res["paraphrased"]["n"], 2)
        self.assertAlmostEqual(res["paraphrased"]["accuracy"]["value"], 0.5)
        self.assertEqual(res["paraphrased"]["outcome_shares"], {"correct_reuse": 0.5, "misroute": 0.5})
        self.assertEqual(res["none"]["n"], 1)


class DropPointTest(unittest.TestCase):
    def test_detects_large_drop(self):
        turns = accuracy_grid({10: 0.9, 50: 0.875, 100: 0.7, 200: 0.5})
        boot = m.Bootstrap({t["case_id"] for t in turns}, STATS)
        res = m.drop_point(boot, m._by_n(turns))
        self.assertEqual(res["drop_n"], 100)
        self.assertAlmostEqual(res["differences"]["100"]["value"], -0.2)
        self.assertLess(res["differences"]["100"]["ci"][1], 0)

    def test_no_drop_when_within_threshold(self):
        turns = accuracy_grid({10: 0.9, 50: 0.875, 200: 0.875})
        boot = m.Bootstrap({t["case_id"] for t in turns}, STATS)
        self.assertIsNone(m.drop_point(boot, m._by_n(turns))["drop_n"])

    def test_missing_baseline(self):
        turns = accuracy_grid({50: 0.9})
        boot = m.Bootstrap({t["case_id"] for t in turns}, STATS)
        self.assertIsNone(m.drop_point(boot, m._by_n(turns))["drop_n"])


class TokenMetricsTest(unittest.TestCase):
    def test_roster_tokens_from_probe_and_linear_fit(self):
        turns = []
        for n in (10, 50, 200):
            for i in range(5):
                turns.append(turn(f"s{i}", n, 0, True, first_call_prompt_tokens=4000 + 12 * n + i))
        probes = [
            {"split": "test", "suite": "token_probe", "case_id": f"s{i}", "prompt_tokens": 3990 + i, "N": 0, "status": "ok"}
            for i in range(5)
        ]
        res = m.compute_metrics(turns + probes, [], [], STATS)
        block = res["single"]["test"]
        self.assertEqual(block["10"]["roster_tokens_per_call_median"]["value"], 130.0)
        self.assertEqual(block["200"]["roster_tokens_per_turn_median"]["value"], 2 * (10 + 12 * 200))
        self.assertAlmostEqual(block["roster_token_fit"]["slope"], 12.0)
        self.assertAlmostEqual(block["roster_token_fit"]["intercept"], 10.0)

    def test_cost_totals_by_purpose(self):
        calls = [
            {"purpose": "routing", "cost": 0.001, "prompt_tokens": 100, "completion_tokens": 10},
            {"purpose": "routing", "cost": 0.002, "prompt_tokens": 100, "completion_tokens": 10},
            {"purpose": "summarizer", "cost": 0.01, "prompt_tokens": 1000, "completion_tokens": 500},
        ]
        totals = m.cost_totals(calls)
        self.assertAlmostEqual(totals["total_cost_usd"], 0.013)
        self.assertEqual(totals["by_purpose"]["routing"]["calls"], 2)


class SequenceMetricsTest(unittest.TestCase):
    def test_compounding_and_duplicates(self):
        turns = []
        for seq in ("q1", "q2"):
            for t in (1, 2):
                turns.append(turn(seq, 10, 0, True, suite="sequence", mode="corrected", turn_index=t))
                turns.append(turn(seq, 10, 0, t == 1, suite="sequence", mode="carried", turn_index=t))
        sequences = [
            {"split": "test", "case_id": "q1", "N": 10, "mode": "carried", "rep": 0, "status": "ok",
             "duplicate_rate": 0.25, "inflation_ratio": 1.5, "extra_agents": 2, "extra_agents_per_thread": 0.5,
             "created": 3, "gold_created": 2, "slug_collisions": 1},
            {"split": "test", "case_id": "q2", "N": 10, "mode": "carried", "rep": 0, "status": "ok",
             "duplicate_rate": 0.0, "inflation_ratio": 1.0, "extra_agents": 0, "extra_agents_per_thread": 0.0,
             "created": 2, "gold_created": 2, "slug_collisions": 0},
        ]
        res = m.compute_metrics(turns, sequences, [], STATS)
        seq = res["sequence"]["test"]
        comp = seq["compounding"]["10"]
        self.assertEqual(comp["per_turn"]["1"]["difference"], 0.0)
        self.assertEqual(comp["per_turn"]["2"]["difference"], -1.0)
        self.assertAlmostEqual(comp["overall_difference"]["value"], -0.5)
        dup = seq["duplicates"]["10"]
        self.assertAlmostEqual(dup["duplicate_rate"]["value"], 0.125)
        self.assertAlmostEqual(dup["created_minus_gold"]["value"], 0.5)
        self.assertEqual(dup["slug_collisions_total"], 1)
        self.assertIn("turn_index", seq["carried"]["10"]["breakdowns"])
        self.assertAlmostEqual(seq["carried"]["all_N"]["accuracy"]["value"], 0.5)


if __name__ == "__main__":
    unittest.main()
