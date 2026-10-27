"""Spend safeguards: dry run, refusal without --confirm-spend, the total cap and the per-run cap."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import io
import tempfile
import unittest
from pathlib import Path

from evals.agent_overload.harness import llm, spend


def args(tmp: Path, **kw) -> argparse.Namespace:
    base = dict(dry_run=False, confirm_spend=False, fake_model=False, max_cost=None, ledger=tmp / "ledger.jsonl")
    base.update(kw)
    return argparse.Namespace(**base)


PLANNED = [spend.PlannedCalls("routing", "openai/gpt-6-luna", 1000, 5000, 300)]
BUDGET = spend.Budget(total_cap_usd=50.0, estimate_margin=1.25)


class GateTest(unittest.TestCase):
    def run_gate(self, a):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            mode = spend.gate(a, "test step", PLANNED, budget=BUDGET, cap_usd=2.0)
        return mode, out.getvalue()

    def test_dry_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            mode, text = self.run_gate(args(Path(tmp), dry_run=True, confirm_spend=True))
        self.assertEqual(mode, "dry_run")
        self.assertIn("estimated cost:            $0.65", text)
        self.assertIn("spend ledger total so far: $0.00", text)

    def test_refuses_without_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(SystemExit) as cm:
                self.run_gate(args(Path(tmp)))
        self.assertEqual(cm.exception.code, spend.EXIT_NOT_CONFIRMED)

    def test_fake_needs_no_confirm(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_gate(args(Path(tmp), fake_model=True))[0], "fake")

    def test_total_cap(self):
        with tempfile.TemporaryDirectory() as tmp:
            ledger = Path(tmp) / "ledger.jsonl"
            spend.append_spend(ledger, "r1", "fixture:x", 49.5)
            self.assertAlmostEqual(spend.ledger_total(ledger), 49.5)
            with self.assertRaises(SystemExit) as cm:
                self.run_gate(args(Path(tmp), confirm_spend=True))
        self.assertEqual(cm.exception.code, spend.EXIT_OVER_BUDGET)

    def test_confirmed_within_budget(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(self.run_gate(args(Path(tmp), confirm_spend=True))[0], "real")


class ClientGuardTest(unittest.TestCase):
    def test_paid_client_requires_confirmation(self):
        with self.assertRaises(llm.SpendNotConfirmed):
            llm.OpenRouterClient(confirm_spend=False, api_key="x")

    def test_spend_cap_stops_calls(self):
        tracker = llm.SpendTracker(cap_usd=0.0001)
        client = llm.FakeClient(spend=tracker)

        async def go():
            await client.chat(purpose="summarizer", model="openai/gpt-6-luna", messages=[{"role": "user", "content": "x" * 4000}])
            await client.chat(purpose="summarizer", model="openai/gpt-6-luna", messages=[{"role": "user", "content": "y"}])

        with self.assertRaises(llm.SpendCapReached):
            asyncio.run(go())
        self.assertTrue(tracker.capped)
        self.assertEqual(len(client.records), 1)

    def test_estimate_cost(self):
        self.assertAlmostEqual(llm.estimate_cost("openai/gpt-6-luna", 1_000_000, 1_000_000), 0.60)
        self.assertAlmostEqual(llm.estimate_cost("anthropic/claude-sonnet-5.5", 1_000_000, 0), 2.0)

    def test_pin_check(self):
        listing = {"openai/gpt-6-luna": {"canonical_slug": "openai/gpt-6-luna-20261101"}}
        observed, problems = llm.check_pins(listing, {"openai/gpt-6-luna": "openai/gpt-6-luna-20260922", "x/y": "x/y-1"})
        self.assertEqual(observed["openai/gpt-6-luna"], "openai/gpt-6-luna-20261101")
        self.assertEqual(len(problems), 2)


if __name__ == "__main__":
    unittest.main()
