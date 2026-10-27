"""Retrieval-only probe for ``records_retrieval`` (dev only): recall@k without any routing calls.

``python -m evals.agent_overload.retrieval_probe --config evals/agent_overload/configs/v1_records_retrieval.json``

For every dev single-turn case and roster size it builds the roster exactly as the runner
does and runs only production candidate selection (``select_candidates``). It reports
recall@k of the case's target agent, overall and by roster size, query style, message
subtype, whether the target's name is visible, and history type, plus the share of hits
at K that came only from pins. It costs only embeddings and the one-off purpose backfill
(both cached).

It reads labels, so it refuses ``--split test``. Spend rules are run.py's: ``--dry-run``
prints the plan and calls nothing, ``--confirm-spend`` is needed for real calls, and
``--fake-model`` uses the deterministic fake. ``--set key=value`` overrides a method
param for this probe only (for example ``--set use_pins=false``).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .harness.config import ConfigError, load_config
from .harness.fixtures import FixtureError, load_fixtures
from .harness.llm import (
    CALL_CONTEXT,
    DEFAULT_RPM,
    OPENAI_DEFAULT_RPM,
    FakeClient,
    OpenAIClient,
    OpenRouterClient,
    SpendCapReached,
    SpendTracker,
    check_openai_pins,
    check_pins,
    fetch_model_listing,
    load_pricing,
    openai_key,
)
from .harness.methods.records_retrieval import (
    CACHE_DIR,
    MethodConfigError,
    MethodParams,
    RecordsRetrievalMethod,
    prepare_plan,
)
from .harness.runner import fixture_agent_views, single_case_state
from .harness.scoring import REUSE_KINDS
from .harness.spend import Budget, PlannedCalls, add_paid_args, append_spend, gate
from .harness.util import EVAL_ROOT, REPO_ROOT, canonical_json, sha256_hex

RESULTS_ROOT = EVAL_ROOT / "results" / "probes"
FAKE_RESULTS_ROOT = EVAL_ROOT / "results" / "_fake" / "probes"
RECALL_KS = (1, 3, 5, 8, 10, 12, 20)  # 5, 8 and 12 are the candidate K values
DEFAULT_SIZES = (50, 100, 200)
GROUPS = ("N", "query_style", "message_subtype", "target_name_visible", "history_type")
QUERY_TOKENS = 120  # per probe unit, for the estimate: the message plus the previous user message


class _CachingEmbedder:
    """Wraps a turn embedder so identical texts are embedded once per probe run.

    The probe measures recall, not latency, so a query shared by several roster sizes (and
    the pins-off rerun) needs only one call.
    """

    def __init__(self, inner, cache: dict[str, list[float]]):
        self.inner = inner
        self.model = inner.model
        self.dimensions = inner.dimensions
        self.cache = cache
        self.cap_reached = False

    async def embed(self, texts: list[str], purpose: str) -> list[list[float]]:
        missing = [t for t in dict.fromkeys(texts) if t not in self.cache]
        if missing:
            try:
                vectors = await self.inner.embed(missing, purpose)
            finally:
                self.cap_reached = self.inner.cap_reached
            self.cache.update(zip(missing, vectors))
        return [self.cache[t] for t in texts]


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="python -m evals.agent_overload.retrieval_probe", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, required=True, help="a records_retrieval config")
    parser.add_argument("--split", default="dev", choices=["dev", "test"], help="dev only; test is refused")
    parser.add_argument("--sizes", type=int, nargs="+", default=list(DEFAULT_SIZES), help="roster sizes (default 50 100 200)")
    parser.add_argument("--set", dest="overrides", action="append", default=[], metavar="KEY=VALUE",
                        help="override a method param for this probe (JSON value, e.g. use_pins=false, k=5)")
    parser.add_argument("--limit", type=int, default=None, help="only the first N cases (by case_id)")
    parser.add_argument("--results-dir", type=Path, default=None)
    parser.add_argument("--manifest", type=Path, default=None)
    parser.add_argument("--accept-model-change", action="store_true")
    parser.add_argument("--rpm", type=float, default=None)
    add_paid_args(parser)
    return parser.parse_args(argv)


def apply_overrides(params: dict, overrides: list[str]) -> dict:
    result = json.loads(json.dumps(params))
    for item in overrides:
        key, sep, raw = item.partition("=")
        if not sep or not key:
            raise ConfigError(f"--set expects KEY=VALUE, got {item!r}")
        try:
            value = json.loads(raw)
        except ValueError:
            value = raw
        result[key.strip()] = value
    return result


def target_rank(ranked: list[str], agent_thread: dict[str, str], expected: list[str]) -> Optional[int]:
    """1-based position of the first candidate in one of the expected threads (as the runner scores it)."""
    for rank, agent_id in enumerate(ranked, start=1):
        if agent_thread.get(agent_id) in expected:
            return rank
    return None


async def probe_unit(method: RecordsRetrievalMethod, embedder: _CachingEmbedder, pins_off, fs, split, case, n) -> dict:
    CALL_CONTEXT.set({"case_id": case["case_id"], "N": n, "mode": None, "rep": None, "turn": None, "suite": "probe", "split": split})
    state = single_case_state(fs, split, case, n)
    inp = state.routing_input(case["message"]["text"], case["message"]["type"], now=case["message"]["timestamp"])
    expected = list(case["label"].get("threads") or [])
    threads = state.agent_thread()
    with_pins = await method.select(inp, embedder)
    without = await pins_off.select(inp, embedder) if method.params.use_pins else with_pins
    rank = target_rank(with_pins.ranked, threads, expected)
    rank_without = target_rank(without.ranked, threads, expected)
    k = method.params.k
    return {
        "case_id": case["case_id"],
        "N": n,
        "mode": with_pins.mode,
        "rank": rank,
        "rank_without_pins": rank_without,
        "pin_only_hit": rank is not None and rank <= k and (rank_without is None or rank_without > k),
        "embed_error": with_pins.error,
        "query_style": case["meta"].get("query_style"),
        "message_subtype": case["message"].get("subtype"),
        "target_name_visible": case["meta"].get("target_name_visible"),
        "history_type": case["history"].get("type"),
    }


def summarize(rows: list[dict], k: int) -> dict:
    def block(members: list[dict]) -> dict:
        n = len(members)
        hits_at_k = [r for r in members if r["rank"] is not None and r["rank"] <= k]
        return {
            "n": n,
            "recall_at": {str(x): (sum(1 for r in members if r["rank"] is not None and r["rank"] <= x) / n if n else None) for x in RECALL_KS},
            "pin_only_share_of_hits_at_k": (sum(1 for r in hits_at_k if r["pin_only_hit"]) / len(hits_at_k)) if hits_at_k else None,
        }

    result = {"overall": block(rows), "by": {}}
    for group in GROUPS:
        buckets: dict[str, list[dict]] = defaultdict(list)
        for r in rows:
            buckets[str(r[group])].append(r)
        ordered = sorted(buckets.items(), key=lambda kv: (0, int(kv[0]), "") if kv[0].isdigit() else (1, 0, kv[0]))
        result["by"][group] = {key: block(members) for key, members in ordered}
    return result


def render_markdown(meta: dict, summary: dict) -> str:
    def fmt(value: Optional[float]) -> str:
        return "n/a" if value is None else f"{100 * value:.1f}%"

    header = "| group | value | n | " + " | ".join(f"R@{x}" for x in RECALL_KS) + " | pin-only share at K |"
    sep = "| --- | --- | --- | " + " | ".join("---" for _ in RECALL_KS) + " | --- |"

    def row(group: str, value: str, b: dict) -> str:
        return f"| {group} | {value} | {b['n']} | " + " | ".join(fmt(b["recall_at"][str(x)]) for x in RECALL_KS) + f" | {fmt(b['pin_only_share_of_hits_at_k'])} |"

    lines = [
        f"# Retrieval probe {meta['probe_id']}",
        "",
        f"Config `{meta['config']}`, split {meta['split']}, sizes {meta['sizes']}, K = {meta['params']['k']}, "
        f"cost ${meta['cost_usd']:.4f}{' (FAKE MODEL)' if meta['fake_model'] else ''}.",
        "",
        f"Params: `{json.dumps(meta['params'], sort_keys=True)}`",
        "",
        f"Recall counts single-turn REUSE / REUSE_ANY cases ({summary['overall']['n']} case-size units). "
        f"Modes seen: {meta['modes']}. Embedding failures (lexical fallback): {meta['embed_failures']}.",
        "",
        header,
        sep,
        row("overall", "all", summary["overall"]),
    ]
    for group, buckets in summary["by"].items():
        for value, b in buckets.items():
            lines.append(row(group, value, b))
    return "\n".join(lines) + "\n"


def make_client(config: dict, args, spend: SpendTracker, fake: bool):
    concurrency = int(config["runtime"]["concurrency"])
    if fake:
        return FakeClient(spend=spend, concurrency=concurrency)
    kwargs = dict(
        confirm_spend=args.confirm_spend,
        spend=spend,
        concurrency=concurrency,
        timeout_s=float(config["runtime"]["timeout_s"]),
        max_retries=int(config["runtime"]["max_retries"]),
        rpm=args.rpm,
    )
    if config["models"].get("api", "openrouter") == "openai":
        return OpenAIClient(model_ids=config["models"]["openai_model_ids"], **kwargs)
    return OpenRouterClient(**kwargs)


async def check_models(config: dict) -> list[str]:
    if config["models"].get("api", "openrouter") == "openai":
        key = openai_key()
        if not key:
            return ["OPENAI_API_KEY is not set (add it to .env at the repository root, or export it)"]
        _observed, problems = await check_openai_pins(config["models"]["openai_model_ids"], key)
        return problems
    _observed, problems = check_pins(await fetch_model_listing(), config["models"]["expected_canonical_slugs"])
    return problems


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    if args.split != "dev":
        print("Refusing: the probe reads labels, so it runs on dev only (tuning on test isn't allowed).")
        return 1
    config = load_config(args.config)
    method_cfg = config["method"]
    if method_cfg["name"] != "records_retrieval":
        print(f"error: the probe needs a records_retrieval config, got {method_cfg['name']}")
        return 1
    if args.rpm is None:
        args.rpm = OPENAI_DEFAULT_RPM if config["models"].get("api") == "openai" else DEFAULT_RPM
    try:
        params = apply_overrides(method_cfg.get("params") or {}, args.overrides)
        method_params = MethodParams.parse(params)
    except (ConfigError, MethodConfigError) as exc:
        print(f"error: {exc}")
        return 1
    try:
        fixtures = load_fixtures(args.manifest or (REPO_ROOT / config["case_set"]["manifest"]),
                                 expected_hash=config["case_set"].get("expected_hash"))
    except FixtureError as exc:
        print(f"error: {exc}")
        return 1

    cases = sorted(fixtures.single.get(args.split, []), key=lambda c: c["case_id"])
    if args.limit is not None:
        cases = cases[: args.limit]
    reuse_cases = [c for c in cases if c["label"]["kind"] in REUSE_KINDS]
    agents = fixture_agent_views(fixtures, args.split)
    planned = prepare_plan(params, agents, config["models"]["summarizer"], CACHE_DIR)
    planned.append(
        PlannedCalls("embed_query", method_params.embedding_model, len(reuse_cases), QUERY_TOKENS, 0, "queries, once per case")
    )
    pricing = load_pricing()
    estimate = sum(p.cost(pricing) for p in planned)
    budget = Budget(float(config["budget"]["total_cap_usd"]), float(config["budget"]["estimate_margin"]))
    max_cost = args.max_cost if args.max_cost is not None else max(0.5, round(estimate * 2, 2))
    extra = [
        "",
        f"split {args.split}, sizes {args.sizes}, {len(reuse_cases)} REUSE cases of {len(cases)}, "
        f"{len(reuse_cases) * len(args.sizes)} probe units; no routing calls",
        f"  params: {json.dumps(params, sort_keys=True)}",
        f"  cache: {CACHE_DIR.relative_to(REPO_ROOT)} (purposes and record vectors are reused by later runs)",
    ]
    if method_params.retrieval.full_roster_max >= min(args.sizes):
        extra.append(
            f"  note: full_roster_max={method_params.retrieval.full_roster_max} shows every agent at some sizes; "
            "pass --set full_roster_max=0 to measure retrieval at every size"
        )
    mode = gate(args, "retrieval_probe.py", planned, budget=budget, cap_usd=max_cost, extra_lines=extra, estimate_override=estimate)
    if mode == "dry_run":
        return 0
    return asyncio.run(execute(args, config, params, fixtures, reuse_cases, mode, max_cost))


async def execute(args, config, params, fixtures, cases, mode, max_cost) -> int:
    fake = mode == "fake"
    if not fake:
        problems = await check_models(config)
        if problems and not args.accept_model_change:
            print("Refusing: model check failed:\n  " + "\n  ".join(problems) + "\nPass --accept-model-change to run anyway.")
            return 6
    started = datetime.now(timezone.utc)
    probe_id = f"{started.strftime('%Y%m%d-%H%M%S')}-probe-{sha256_hex(canonical_json({'params': params, 'sizes': args.sizes}))[:8]}"
    spend = SpendTracker(cap_usd=max_cost)
    client = make_client(config, args, spend, fake)
    common = dict(
        client=client,
        model=config["models"]["interaction"],
        provider=config["models"]["provider"],
        summarizer_model=config["models"]["summarizer"],
        cache_dir=None if fake else CACHE_DIR,
    )
    capped = False
    rows: list[dict] = []
    try:
        method = RecordsRetrievalMethod(params=params, **common)
        pins_off = RecordsRetrievalMethod(params={**params, "use_pins": False}, **common)
        await method.prepare(fixture_agent_views(fixtures, args.split))
        pins_off.purposes, pins_off.index = method.purposes, method.index
        embedder = _CachingEmbedder(method.turn_embedder(), {})
        results = await asyncio.gather(
            *(probe_unit(method, embedder, pins_off, fixtures, args.split, case, n) for case in cases for n in args.sizes),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, SpendCapReached):
                capped = True
            elif isinstance(result, BaseException):
                raise result
            else:
                rows.append(result)
    except SpendCapReached:
        capped = True
    finally:
        await client.aclose()
        if not fake:
            append_spend(args.ledger, probe_id, "probe", spend.total_usd)

    summary = summarize(rows, method.params.k)
    meta = {
        "probe_id": probe_id,
        "config": str(args.config),
        "split": args.split,
        "sizes": args.sizes,
        "params": method.config.to_dict(),
        "fake_model": fake,
        "capped": capped,
        "cost_usd": spend.total_usd,
        "modes": sorted({r["mode"] for r in rows}),
        "embed_failures": sum(1 for r in rows if r["embed_error"]),
        "method": method.describe(),
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    out_dir = (args.results_dir or (FAKE_RESULTS_ROOT if fake else RESULTS_ROOT)) / probe_id
    out_dir.mkdir(parents=True, exist_ok=False)
    (out_dir / "probe.json").write_text(json.dumps({"meta": meta, "summary": summary, "rows": rows}, indent=2, sort_keys=True), encoding="utf-8")
    report = render_markdown(meta, summary)
    (out_dir / "probe.md").write_text(report, encoding="utf-8")
    print()
    print(report)
    print(f"probe {probe_id} written to {out_dir}; cost ${spend.total_usd:.4f}")
    if capped:
        print("warning: CAPPED: the probe stopped at its cost cap; results are partial.")
        return 8
    return 0


if __name__ == "__main__":
    sys.exit(main())
