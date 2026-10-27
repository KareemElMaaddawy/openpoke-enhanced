"""Spend ledger, cost plans and the gate every paid command goes through.

Design: Budget and spend guard, and Safeguards on paid commands. A paid command
prints its plan (calls, models, estimated cost, ledger total), then:

- ``--dry-run``: exits 0 without calling any API.
- no ``--confirm-spend``: exits 2 without calling any API.
- ``--confirm-spend``: refuses (exit 3) if ledger total + estimate × margin would pass
  the total cap; otherwise runs with a per-run cap.
- ``--fake-model``: runs against the deterministic fake, writes nothing to the ledger.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .llm import estimate_cost, load_pricing
from .util import EVAL_ROOT, append_jsonl, read_jsonl

DEFAULT_LEDGER = EVAL_ROOT / "results" / "spend_ledger.jsonl"
DEFAULT_CONFIG = EVAL_ROOT / "configs" / "baseline_names_only.json"

EXIT_NOT_CONFIRMED = 2
EXIT_OVER_BUDGET = 3


@dataclass
class PlannedCalls:
    purpose: str
    model: str
    calls: float
    input_tokens: float  # per call
    output_tokens: float  # per call
    note: str = ""

    def cost(self, pricing: dict) -> float:
        return estimate_cost(self.model, self.calls * self.input_tokens, self.calls * self.output_tokens, pricing)


@dataclass
class Budget:
    total_cap_usd: float
    estimate_margin: float

    @classmethod
    def from_config(cls, path: Path = DEFAULT_CONFIG) -> "Budget":
        budget = json.loads(path.read_text(encoding="utf-8"))["budget"]
        return cls(float(budget["total_cap_usd"]), float(budget["estimate_margin"]))


def ledger_rows(path: Path = DEFAULT_LEDGER) -> list[dict]:
    return read_jsonl(path) if path.exists() else []


def ledger_total(path: Path = DEFAULT_LEDGER) -> float:
    return sum(float(row.get("cost_usd") or 0.0) for row in ledger_rows(path))


def append_spend(path: Path, run_id: str, kind: str, cost_usd: float) -> None:
    append_jsonl(
        path,
        {
            "run_id": run_id,
            "kind": kind,
            "cost_usd": round(float(cost_usd), 6),
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    )


def add_paid_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_argument_group("spend safeguards")
    group.add_argument("--dry-run", action="store_true", help="print the plan and estimated cost; call no API")
    group.add_argument("--confirm-spend", action="store_true", help="actually call the paid API")
    group.add_argument("--fake-model", action="store_true", help="use the deterministic fake model (no API, no ledger)")
    group.add_argument("--max-cost", type=float, default=None, help="stop cleanly once this run has spent this much (USD)")
    group.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER, help=argparse.SUPPRESS)


def format_plan(
    title: str,
    planned: list[PlannedCalls],
    *,
    ledger_usd: float,
    budget: Budget,
    cap_usd: Optional[float],
    extra_lines: Optional[list[str]] = None,
    estimate_override: Optional[float] = None,
) -> tuple[str, float]:
    pricing = load_pricing()
    lines = [f"== {title} ==", ""]
    if planned:
        lines.append(f"{'purpose':<22} {'model':<28} {'calls':>7} {'in/call':>8} {'out/call':>8} {'est. $':>8}")
    total = 0.0
    for p in planned:
        cost = p.cost(pricing)
        total += cost
        lines.append(
            f"{p.purpose:<22} {p.model:<28} {p.calls:>7.0f} {p.input_tokens:>8.0f} {p.output_tokens:>8.0f} {cost:>8.3f}"
            + (f"  ({p.note})" if p.note else "")
        )
    if estimate_override is not None:
        total = estimate_override
    if planned:
        lines.append("")
    lines.append(f"estimated cost:            ${total:.2f}")
    lines.append(f"with margin x{budget.estimate_margin:g}:          ${total * budget.estimate_margin:.2f}")
    lines.append(f"spend ledger total so far: ${ledger_usd:.2f} of the ${budget.total_cap_usd:.2f} cap")
    lines.append(f"after this step (est.):    ${ledger_usd + total * budget.estimate_margin:.2f}")
    if cap_usd is not None:
        lines.append(f"per-run cap:               ${cap_usd:.2f} (the step stops cleanly when reached)")
    for line in extra_lines or []:
        lines.append(line)
    return "\n".join(lines), total


def gate(
    args: argparse.Namespace,
    title: str,
    planned: list[PlannedCalls],
    *,
    budget: Budget,
    cap_usd: Optional[float],
    extra_lines: Optional[list[str]] = None,
    estimate_override: Optional[float] = None,
) -> str:
    """Print the plan and decide: returns "dry_run", "fake" or "real", or exits."""
    ledger_usd = ledger_total(args.ledger)
    text, estimate = format_plan(
        title,
        planned,
        ledger_usd=ledger_usd,
        budget=budget,
        cap_usd=cap_usd,
        extra_lines=extra_lines,
        estimate_override=estimate_override,
    )
    print(text)
    print()
    if args.dry_run:
        print("dry run: no API was called.")
        return "dry_run"
    if args.fake_model:
        print("fake model: no API will be called and nothing is written to the spend ledger.")
        return "fake"
    if not args.confirm_spend:
        print("Refusing to call any API: pass --confirm-spend to run this step for real.")
        sys.exit(EXIT_NOT_CONFIRMED)
    if ledger_usd + estimate * budget.estimate_margin > budget.total_cap_usd:
        print(
            f"Refusing to start: ledger ${ledger_usd:.2f} + estimate ${estimate:.2f} x {budget.estimate_margin:g} "
            f"would exceed the ${budget.total_cap_usd:.2f} total cap."
        )
        sys.exit(EXIT_OVER_BUDGET)
    return "real"
