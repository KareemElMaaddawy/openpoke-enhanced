"""Run a config: ``python -m evals.agent_overload.run --config <path> --profile <name>``.

Paid. Without ``--confirm-spend`` it prints the plan and exits; ``--dry-run`` does the
same with exit code 0; ``--fake-model`` runs end to end against the deterministic fake.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .harness.config import (
    PLACEHOLDER_HASH,
    ConfigError,
    build_recorded_config,
    config_hash,
    git_state,
    load_config,
    resolve_plan,
)
from .harness.fixtures import FixtureError, load_fixtures
from .harness.llm import (
    DEFAULT_RPM,
    FakeClient,
    OpenRouterClient,
    SpendTracker,
    check_pins,
    estimate_cost,
    fetch_model_listing,
    load_pricing,
)
from .harness.methods.names_only import NamesOnlyMethod
from .harness.metrics import StatsConfig, compute_metrics
from .harness.report import render_report
from .harness.runner import RunContext, cost_profile, planned_units, run_all, sort_key, write_jsonl_gz
from .harness.scoring import STATUS_API_ERROR
from .harness.spend import Budget, add_paid_args, append_spend, gate
from .harness.util import EVAL_ROOT, REPO_ROOT, append_jsonl, read_jsonl

RESULTS_ROOT = EVAL_ROOT / "results"
FAKE_RESULTS_ROOT = RESULTS_ROOT / "_fake"
TEST_LEDGER = RESULTS_ROOT / "test_ledger.jsonl"
DESIGN_COUNTS = {
    "single": {"test": 120, "dev": 60},
    "sequence": {"test": 8, "dev": 4},
    "turns_per_sequence": 12,
}

EXIT_TEST_LEDGER = 4
EXIT_DIRTY = 5
EXIT_MODEL_CHANGED = 6
EXIT_API_ERRORS = 7
EXIT_CAPPED = 8


def make_method(config: dict, client):
    method = config["method"]
    if method["name"] == "names_only" and str(method["version"]) == NamesOnlyMethod.version:
        return NamesOnlyMethod(
            client,
            model=config["models"]["interaction"],
            provider=config["models"]["provider"],
            extra_params=config["models"].get("extra_params") or {},
        )
    raise ConfigError(f"unknown method {method['name']} v{method['version']}")


def nominal_units(plan) -> dict:
    counts = {"single_turns": 0, "sequence_turns": 0, "sequence_runs": 0, "token_probes": 0}
    for split in plan.splits:
        singles = DESIGN_COUNTS["single"][split] if plan.single_limit is None else min(plan.single_limit, DESIGN_COUNTS["single"][split])
        seqs = DESIGN_COUNTS["sequence"][split] if plan.sequence_limit is None else min(plan.sequence_limit, DESIGN_COUNTS["sequence"][split])
        counts["single_turns"] += singles * len(plan.single_sizes[split]) * plan.single_reps
        runs = seqs * len(plan.sequence_sizes[split]) * len(plan.modes) * plan.sequence_reps
        counts["sequence_runs"] += runs
        counts["sequence_turns"] += runs * DESIGN_COUNTS["turns_per_sequence"]
        counts["token_probes"] += singles if plan.token_probe else 0
    return counts


def latest_cost_profile(config: dict, results_root: Path = RESULTS_ROOT) -> tuple[dict, str]:
    """Per-unit costs from the latest real smoke run of the same method and model, else the design."""
    method = config["method"]
    model = config["models"]["interaction"]
    candidates = []
    for cfg_path in sorted(results_root.glob("*/config.json")):
        try:
            recorded = json.loads(cfg_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if (
            recorded.get("plan", {}).get("profile") == "smoke"
            and not recorded.get("fake_model")
            and not recorded.get("end", {}).get("capped")
            and recorded.get("method", {}).get("name") == method["name"]
            and str(recorded.get("method", {}).get("version")) == str(method["version"])
            and recorded.get("models", {}).get("interaction") == model
        ):
            metrics_path = cfg_path.parent / "metrics.json"
            if metrics_path.exists():
                candidates.append((recorded["run_id"], metrics_path))
    design = load_pricing()["design_estimates"]
    if candidates:
        run_id, path = sorted(candidates)[-1]
        profile = json.loads(path.read_text(encoding="utf-8")).get("cost_profile") or {}
        merged = {k: (profile.get(k) if profile.get(k) is not None else design[k]) for k in design if k != "note"}
        return merged, f"smoke run {run_id}"
    return {k: v for k, v in design.items() if k != "note"}, "design estimates (no smoke run yet)"


def estimate_run_cost(units: dict, profile: dict) -> float:
    return (
        units["single_turns"] * profile["single_turn_usd"]
        + units["sequence_turns"] * profile["sequence_turn_usd"]
        + units["sequence_runs"] * profile["summarizer_per_sequence_run_usd"]
        + units["token_probes"] * profile["token_probe_usd"]
    )


def check_test_ledger(config: dict, cfg_hash: str, ledger: Path = TEST_LEDGER) -> Optional[str]:
    if not ledger.exists():
        return None
    method = config["method"]
    for row in read_jsonl(ledger):
        if (
            row.get("method") == method["name"]
            and str(row.get("method_version")) == str(method["version"])
            and row.get("config_hash") != cfg_hash
        ):
            return (
                f"{method['name']} v{method['version']} already has a test run ({row['run_id']}) with a different "
                "config hash. Bump the method version to run test again."
            )
    return None


def price_check(calls: list[dict], model: str) -> Optional[dict]:
    pricing = load_pricing()
    actual = expected = 0.0
    n = 0
    for c in calls:
        if c.get("model") != model or c.get("cost") is None or c.get("cost_estimated") or c.get("prompt_tokens") is None:
            continue
        actual += c["cost"]
        expected += estimate_cost(model, c["prompt_tokens"], c.get("completion_tokens") or 0, pricing)
        n += 1
    if not n or expected <= 0:
        return None
    return {"ratio": actual / expected, "calls": n}


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals.agent_overload.run", description=__doc__)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--profile", required=True, choices=["smoke", "dev-quick", "dev", "test", "full"])
    parser.add_argument("--allow-dirty", action="store_true", help="run on a dirty tree (flagged in the report)")
    parser.add_argument("--accept-model-change", action="store_true", help="run even if the model alias moved")
    parser.add_argument("--results-dir", type=Path, default=None, help="where run directories go")
    parser.add_argument("--manifest", type=Path, default=None, help="override the config's fixture manifest")
    parser.add_argument(
        "--rpm", type=float, default=DEFAULT_RPM,
        help=f"max requests per minute per model (default {DEFAULT_RPM:g}, under OpenRouter's new-account limit; 0 = no pacing)",
    )
    add_paid_args(parser)
    return parser.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    config = load_config(args.config)
    plan = resolve_plan(config, args.profile)
    max_cost = args.max_cost if args.max_cost is not None else float(config["budget"]["max_cost_usd"])
    cfg_hash = config_hash(config, args.profile)
    budget = Budget(float(config["budget"]["total_cap_usd"]), float(config["budget"]["estimate_margin"]))
    manifest_path = args.manifest or (REPO_ROOT / config["case_set"]["manifest"])
    expected_hash = config["case_set"].get("expected_hash")

    fixtures = None
    fixture_note = ""
    try:
        if expected_hash in (None, PLACEHOLDER_HASH):
            if not (args.fake_model or args.dry_run):
                raise FixtureError("config case_set.expected_hash is not filled in (run freeze.py --update-config)")
            fixtures = load_fixtures(manifest_path, expected_hash=None)
        else:
            fixtures = load_fixtures(manifest_path, expected_hash=expected_hash)
    except FixtureError as exc:
        if not args.dry_run:
            print(f"error: {exc}")
            return 1
        fixture_note = f"fixtures not loadable ({exc.__class__.__name__}): using the design's case counts"

    units = planned_units(plan, fixtures) if fixtures else nominal_units(plan)
    profile, profile_source = latest_cost_profile(config)
    estimate = estimate_run_cost(units, profile)
    git = git_state()
    extra = [
        "",
        f"profile {args.profile}: splits {plan.splits}, reps single {plan.single_reps} / sequence {plan.sequence_reps}",
        f"  single sizes {plan.single_sizes}, sequence sizes {plan.sequence_sizes}, modes {plan.modes}",
        f"  single turns {units['single_turns']}, sequence turns {units['sequence_turns']} "
        f"({units['sequence_runs']} sequence-runs), token probes {units['token_probes']}",
        f"  estimated model calls ≈ {round((units['single_turns'] + units['sequence_turns']) * profile['routing_calls_per_turn'] + units['sequence_runs'] + units['token_probes'])}",
        f"  models: interaction {config['models']['interaction']}, summarizer {config['models']['summarizer']}, provider {config['models']['provider']}",
        f"  per-unit costs from {profile_source}: "
        + ", ".join(f"{k}={v}" for k, v in profile.items()),
        f"  config hash {cfg_hash[:16]}, git {git.get('sha')}{' DIRTY: ' + ', '.join(git['dirty_paths'][:5]) if git.get('dirty') else ''}",
    ]
    calls = (units["single_turns"] + units["sequence_turns"]) * profile["routing_calls_per_turn"] + units["sequence_runs"] + units["token_probes"]
    if args.rpm:
        extra.append(
            f"  pacing: at most {args.rpm:g} requests/minute per model, so this run takes at least {calls / args.rpm / 60:.1f} hours"
        )
    if fixture_note:
        extra.append("  " + fixture_note)
    if estimate * budget.estimate_margin > max_cost:
        extra.append(
            f"  WARNING: estimate x margin (${estimate * budget.estimate_margin:.2f}) is above the per-run cap "
            f"(${max_cost:.2f}); the run would probably be capped and unusable. Pass --max-cost "
            f"{round(estimate * budget.estimate_margin * 1.2 + 0.5)} after checking the smoke run's costs."
        )
    mode = gate(
        args, f"run.py --profile {args.profile} ({config['method']['name']} v{config['method']['version']})", [],
        budget=budget, cap_usd=max_cost, extra_lines=extra, estimate_override=estimate,
    )
    if mode == "dry_run":
        return 0

    if mode == "real":
        if git.get("dirty") and not args.allow_dirty:
            print("Refusing to run on a dirty tree (commit first, or pass --allow-dirty): " + ", ".join(git["dirty_paths"][:10]))
            return EXIT_DIRTY
        if "test" in plan.splits:
            problem = check_test_ledger(config, cfg_hash)
            if problem:
                print("Refusing: " + problem)
                return EXIT_TEST_LEDGER

    return asyncio.run(execute(args, config, plan, fixtures, mode, cfg_hash, max_cost))


async def execute(args, config, plan, fixtures, mode, cfg_hash, max_cost) -> int:
    fake = mode == "fake"
    started = datetime.now(timezone.utc)
    run_id = f"{started.strftime('%Y%m%d-%H%M%S')}-{config['method']['name']}-{cfg_hash[:8]}"
    results_root = args.results_dir or (FAKE_RESULTS_ROOT if fake else RESULTS_ROOT)
    run_dir = results_root / run_id
    run_dir.mkdir(parents=True, exist_ok=False)
    spend = SpendTracker(cap_usd=max_cost)
    runtime_cfg = config["runtime"]
    expected_slugs = config["models"]["expected_canonical_slugs"]
    observed: dict = {}

    if fake:
        client = FakeClient(spend=spend, raw_dir=run_dir / "raw", concurrency=int(runtime_cfg["concurrency"]))
        observed = {m: f"{s}-fake" for m, s in expected_slugs.items()}
    else:
        listing = await fetch_model_listing()
        observed, problems = check_pins(listing, expected_slugs)
        if problems and not args.accept_model_change:
            print("Refusing: model pin check failed:\n  " + "\n  ".join(problems) + "\nPass --accept-model-change to run anyway.")
            run_dir.rmdir()
            return EXIT_MODEL_CHANGED
        client = OpenRouterClient(
            confirm_spend=args.confirm_spend,
            spend=spend,
            raw_dir=run_dir / "raw",
            concurrency=int(runtime_cfg["concurrency"]),
            timeout_s=float(runtime_cfg["timeout_s"]),
            max_retries=int(runtime_cfg["max_retries"]),
            rpm=args.rpm,
        )

    method = make_method(config, client)
    recorded = build_recorded_config(
        config=config, plan=plan, run_id=run_id, cfg_hash=cfg_hash, method_description=method.describe(),
        fixtures_manifest=fixtures.manifest, fake=fake, max_cost_usd=max_cost, observed_slugs=observed,
        accept_model_change=args.accept_model_change, started_at=started.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    recorded["runtime_pacing"] = {"rpm_per_model": args.rpm, "note": "operational; not part of the config hash"}
    (run_dir / "config.json").write_text(json.dumps(recorded, indent=2, sort_keys=True), encoding="utf-8")
    if not fake and "test" in plan.splits:
        append_jsonl(
            TEST_LEDGER,
            {
                "run_id": run_id,
                "method": config["method"]["name"],
                "method_version": str(config["method"]["version"]),
                "config_hash": cfg_hash,
                "case_set_hash": fixtures.case_set_hash,
                "date": started.strftime("%Y-%m-%d"),
            },
        )

    ctx = RunContext(
        run_id=run_id, plan=plan, fixtures=fixtures, method=method, client=client,
        interaction_model=config["models"]["interaction"], summarizer_model=config["models"]["summarizer"],
        provider=config["models"]["provider"], extra_params=config["models"].get("extra_params") or {},
    )
    try:
        await run_all(ctx)
    finally:
        await client.aclose()
        if not fake:
            append_spend(args.ledger, run_id, f"run:{plan.profile}", spend.total_usd)

    turns = sorted(ctx.turns, key=sort_key)
    sequences = sorted(ctx.sequences, key=sort_key)
    calls = [r.to_dict() for r in client.records]
    routing_turns = [t for t in turns if t["suite"] in ("single", "sequence")]
    api_errors = sum(1 for t in routing_turns if t["status"] == STATUS_API_ERROR)
    api_rate = api_errors / len(routing_turns) if routing_turns else 0.0
    failed = api_rate > float(runtime_cfg["max_api_error_rate"]) or bool(ctx.unit_errors)
    capped = ctx.capped or spend.capped
    providers = Counter(c.get("provider") or "unknown" for c in calls)

    warnings = []
    if fake:
        warnings.append("FAKE MODEL: results are synthetic and refused by compare.py.")
    if recorded["git"].get("dirty"):
        warnings.append("Dirty tree: " + ", ".join(recorded["git"]["dirty_paths"][:10]))
    if capped:
        warnings.append(f"CAPPED at ${max_cost:.2f}: the run is incomplete and can't be used for comparisons.")
    if failed:
        warnings.append(f"FAILED: api_error rate {100 * api_rate:.2f}% exceeds {100 * float(runtime_cfg['max_api_error_rate']):.0f}%.")
    if args.accept_model_change:
        warnings.append("Model change accepted (--accept-model-change).")
    if ctx.unit_errors:
        warnings.append(f"{len(ctx.unit_errors)} units crashed with a harness error; see unit_errors in config.json.")
    if ctx.summarizer_errors:
        warnings.append(f"{ctx.summarizer_errors} summarizer calls failed (state left unsummarized, as production does).")
    if not fake and any(p not in ("OpenAI", "openai") for p in providers):
        warnings.append(f"Providers other than OpenAI seen: {dict(providers)}")

    metrics = compute_metrics(turns, sequences, calls, StatsConfig.from_config(config["stats"]))
    metrics["cost_profile"] = cost_profile(turns, sequences, calls)
    ended = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    summary = {
        "ended_at": ended,
        "turns": len(routing_turns),
        "api_error_turns": api_errors,
        "api_error_rate": api_rate,
        "loop_limit_turns": sum(1 for t in routing_turns if t.get("status") == "loop_limit"),
        "summarizer_errors": ctx.summarizer_errors,
        "capped": capped,
        "failed": failed,
        "total_cost_usd": spend.total_usd,
        "calls": len(calls),
        "providers": dict(providers),
        "price_check": price_check(calls, config["models"]["interaction"]),
        "warnings": warnings,
        "unit_errors": ctx.unit_errors,
    }
    recorded["end"] = summary
    (run_dir / "config.json").write_text(json.dumps(recorded, indent=2, sort_keys=True), encoding="utf-8")
    write_jsonl_gz(run_dir / "turns.jsonl.gz", turns)
    write_jsonl_gz(run_dir / "sequences.jsonl.gz", sequences)
    write_jsonl_gz(run_dir / "calls.jsonl.gz", calls)
    (run_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True), encoding="utf-8")
    (run_dir / "report.md").write_text(render_report(recorded, metrics, summary), encoding="utf-8")

    print()
    print(f"run {run_id} written to {run_dir}")
    print(f"turns {len(routing_turns)}, calls {len(calls)}, cost ${spend.total_usd:.4f}, api_error {api_errors}")
    for w in warnings:
        print("warning: " + w)
    if capped:
        return EXIT_CAPPED
    if failed or ctx.unit_errors:
        return EXIT_API_ERRORS
    return 0


if __name__ == "__main__":
    sys.exit(main())
