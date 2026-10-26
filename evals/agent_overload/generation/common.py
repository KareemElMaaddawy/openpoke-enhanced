"""Shared plumbing for the fixture generation scripts.

Each paid script builds a plan (calls, models, token guesses), passes it through the
spend gate (``--dry-run`` / ``--confirm-spend`` / ``--fake-model``), runs its body with
a real or fake client under a per-step cap (twice the estimate unless ``--max-cost``),
and appends its actual spend to the ledger in a ``finally`` block. Scripts are
resumable: they load what earlier attempts produced and only do missing work, and
they save partial results when they're capped or interrupted.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from string import Template
from typing import Any, Awaitable, Callable, Optional

from ..harness.llm import (
    FakeClient,
    ModelClient,
    OpenRouterClient,
    SpendCapReached,
    SpendTracker,
    check_pins,
    fetch_model_listing,
    load_pricing,
)
from ..harness.spend import DEFAULT_CONFIG, Budget, PlannedCalls, add_paid_args, append_spend, gate
from ..harness.util import EVAL_ROOT, read_jsonl, sha256_file, write_jsonl

FIXTURES_DIR = EVAL_ROOT / "fixtures" / "v1"
PROMPTS_DIR = EVAL_ROOT / "generation" / "prompts"
RAW_DIR = EVAL_ROOT / "generation" / "raw"

GEN_MODEL = "anthropic/claude-sonnet-5.5"
LABEL_MODEL = "google/gemini-3.8-flash"
EXPECTED_SLUGS = {
    "openai/gpt-6-luna": "openai/gpt-6-luna-20260922",
    "google/gemini-3.8-flash": "google/gemini-3.8-flash-20260902",
    "anthropic/claude-sonnet-5.5": None,  # no pinned slug in the design; the observed one is recorded
}
SPLITS = ("dev", "test")
SEED = 20261025

# (key, description) in a fixed order; about equal shares (design: World model).
CATEGORIES = [
    ("finance", "finance and receipts"),
    ("travel", "travel"),
    ("work", "work email threads with named people"),
    ("scheduling", "scheduling and reminders (trigger work)"),
    ("shopping", "shopping and deliveries"),
    ("jobs", "job search"),
    ("subscriptions", "subscriptions and newsletters"),
    ("family", "family and personal"),
    ("events", "events and tickets"),
    ("home", "home and utilities"),
    ("health", "health and appointments"),
    ("security", "accounts and security notices"),
]


class GenerationError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# CLI and config


def base_parser(description: str, paid: bool = True) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument("--fixtures-dir", type=Path, default=FIXTURES_DIR, help="fixture version directory")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="run config (models, provider, budget)")
    if paid:
        parser.add_argument("--concurrency", type=int, default=8)
        parser.add_argument("--accept-model-change", action="store_true", help="continue if a pinned model moved")
        add_paid_args(parser)
    else:
        parser.add_argument("--dry-run", action="store_true", help="describe what would change and exit")
    return parser


def load_config(path: Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_not_frozen(fixtures_dir: Path) -> None:
    if (fixtures_dir / "MANIFEST.json").exists():
        raise GenerationError(
            f"{fixtures_dir} is frozen (MANIFEST.json exists). Fixtures are never edited after freezing; "
            "create a new version directory instead."
        )


# ---------------------------------------------------------------------------
# Prompts


def prompt_text(name: str) -> str:
    return (PROMPTS_DIR / name).read_text(encoding="utf-8")


def render_prompt(name: str, **values: Any) -> str:
    return Template(prompt_text(name)).substitute(**{k: str(v) for k, v in values.items()})


def prompt_hashes() -> dict[str, str]:
    return {p.name: sha256_file(p) for p in sorted(PROMPTS_DIR.glob("*.md"))}


# ---------------------------------------------------------------------------
# JSON from model text

_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> Any:
    """Parse the first JSON object in ``text`` (fenced or bare)."""
    candidates = [m.group(1) for m in _FENCE_RE.finditer(text or "")]
    candidates.append(text or "")
    for candidate in candidates:
        candidate = candidate.strip()
        start = min((i for i in (candidate.find("{"), candidate.find("[")) if i >= 0), default=-1)
        if start < 0:
            continue
        for end in range(len(candidate), start, -1):
            if candidate[end - 1] not in "}]":
                continue
            try:
                return json.loads(candidate[start:end])
            except json.JSONDecodeError:
                continue
    raise GenerationError("no JSON object found in model output")


def content_of(response: dict) -> str:
    choice = (response.get("choices") or [{}])[0]
    return ((choice.get("message") or {}).get("content") or "").strip()


# ---------------------------------------------------------------------------
# Files


def read_rows(path: Path) -> list[dict]:
    return read_jsonl(path) if path.exists() else []


def write_rows(path: Path, rows: list[dict]) -> None:
    write_jsonl(path, rows)


def read_json(path: Path, default: Any = None) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else default


def write_json(path: Path, obj: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=False, sort_keys=True) + "\n", encoding="utf-8")


# ---------------------------------------------------------------------------
# Running a paid step


class StepContext:
    """What a step body gets: the client, observed model slugs and the step's options."""

    def __init__(self, client: ModelClient, observed_slugs: dict, args: argparse.Namespace, config: dict):
        self.client = client
        self.observed_slugs = observed_slugs
        self.args = args
        self.config = config
        self.fake = client.fake

    def provenance(self, model: str, record: Any = None, attempts: int = 1) -> dict:
        return {
            "model": model,
            "canonical_slug": self.observed_slugs.get(model) or (record.returned_model if record else None),
            "returned_model": record.returned_model if record else None,
            "attempts": attempts,
            "request_sha256": record.request_sha256 if record else None,
            "fake": self.fake,
        }

    def provider_for(self, model: str) -> Optional[dict]:
        """The run config's provider pin applies to the interaction/summarizer model only."""
        if model in (self.config["models"]["interaction"], self.config["models"]["summarizer"]):
            return self.config["models"]["provider"]
        return None


def run_paid_step(
    args: argparse.Namespace,
    *,
    step: str,
    title: str,
    planned: list[PlannedCalls],
    body: Callable[[StepContext], Awaitable[None]],
    models: list[str],
    fake_responders: Optional[dict] = None,
    extra_lines: Optional[list[str]] = None,
) -> int:
    config = load_config(args.config)
    budget = Budget.from_config(args.config)
    pricing = load_pricing()
    estimate = sum(p.cost(pricing) for p in planned)
    cap = args.max_cost if args.max_cost is not None else round(max(0.05, 2 * estimate), 2)
    mode = gate(args, title, planned, budget=budget, cap_usd=cap, extra_lines=extra_lines)
    if mode == "dry_run":
        return 0
    ensure_not_frozen(args.fixtures_dir)
    return asyncio.run(_execute(args, step, body, models, fake_responders, config, cap, mode))


async def _execute(args, step, body, models, fake_responders, config, cap, mode) -> int:
    spend = SpendTracker(cap_usd=cap)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    observed: dict = {}
    if mode == "fake":
        client: ModelClient = FakeClient(responders=fake_responders or {}, spend=spend, concurrency=args.concurrency)
        observed = {m: f"{m}-fake" for m in models}
    else:
        listing = await fetch_model_listing()
        observed, problems = check_pins(listing, {m: EXPECTED_SLUGS.get(m) for m in models})
        if problems and not args.accept_model_change:
            print("Refusing: model pin check failed:\n  " + "\n  ".join(problems))
            return 6
        client = OpenRouterClient(
            confirm_spend=args.confirm_spend,
            spend=spend,
            raw_dir=RAW_DIR / step / stamp,
            concurrency=args.concurrency,
        )
    ctx = StepContext(client, observed, args, config)
    status = 0
    try:
        await body(ctx)
    except SpendCapReached as exc:
        print(f"\nCAPPED: {exc}. Partial results were saved; rerun the same command to continue.")
        status = 8
    finally:
        await client.aclose()
        if mode == "real":
            append_spend(args.ledger, f"fixture-{step}-{stamp}", f"fixture:{step}", spend.total_usd)
    print(f"\n{step}: {spend.calls} calls, actual cost ${spend.total_usd:.4f}" + (" (fake)" if mode == "fake" else ""))
    return status


async def gather_limited(coros: list[Awaitable[Any]]) -> list[Any]:
    """Run coroutines concurrently (the client's semaphore limits in-flight calls)."""
    return await asyncio.gather(*coros, return_exceptions=True)


def raise_first_cap(results: list[Any]) -> None:
    for r in results:
        if isinstance(r, SpendCapReached):
            raise r


def fail(message: str) -> None:
    print(f"error: {message}")
    sys.exit(1)
