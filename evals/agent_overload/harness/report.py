"""``report.md`` from ``metrics.json`` and the recorded config (design: Report layout)."""

from __future__ import annotations

from typing import Any, Optional

from .metrics import SEQUENCE_DIMS, SINGLE_DIMS

HEADLINE_COLUMNS = [
    ("accuracy", "Accuracy", "pct"),
    ("false_spawn_rate", "False spawn", "pct"),
    ("misroute_rate", "Misroute", "pct"),
    ("false_reuse_rate", "False reuse", "pct"),
    ("missed_delegation_rate", "Missed deleg.", "pct"),
    ("extra_delegation_rate", "Extra deleg.", "pct"),
    ("duplicate_rate", "Duplicate rate", "pct"),
    ("roster_tokens_per_turn_median", "Roster tok/turn", "int"),
    ("input_tokens_per_turn_median", "Input tok/turn", "int"),
    ("cost_per_turn_mean", "Cost/turn", "usd"),
    ("latency_ms_per_turn_median", "Latency p50", "ms"),
]


def _fmt_value(value: Optional[float], kind: str) -> str:
    if value is None:
        return "n/a"
    if kind == "pct":
        return f"{100 * value:.1f}%"
    if kind == "int":
        return f"{value:,.0f}"
    if kind == "usd":
        return f"${value:.5f}"
    if kind == "ms":
        return f"{value / 1000:.2f}s"
    if kind == "float":
        return f"{value:.2f}"
    return str(value)


def fmt(metric: Any, kind: str = "pct", ci: bool = True) -> str:
    """Format ``{"value", "ci"}`` as ``value [lo, hi]``."""
    if metric is None:
        return "n/a"
    if not isinstance(metric, dict):
        return _fmt_value(metric, kind)
    value = metric.get("value")
    text = _fmt_value(value, kind)
    bounds = metric.get("ci")
    if ci and value is not None and bounds and None not in bounds:
        if kind == "pct":
            text += f" [{100 * bounds[0]:.1f}, {100 * bounds[1]:.1f}]"
        else:
            text += f" [{_fmt_value(bounds[0], kind)}, {_fmt_value(bounds[1], kind)}]"
    return text


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    out = ["| " + " | ".join(header) + " |", "| " + " | ".join("---" for _ in header) + " |"]
    out += ["| " + " | ".join(row) + " |" for row in rows]
    return out


def _n_keys(block: dict) -> list[str]:
    return sorted((k for k in block if k.isdigit()), key=int)


def headline_table(metrics: dict, split: str) -> list[str]:
    single = metrics["single"].get(split)
    if not single:
        return [f"No single-turn results for the {split} split."]
    duplicates = (metrics["sequence"].get(split) or {}).get("duplicates", {})
    rows = []
    for n in _n_keys(single) + ["all_N"]:
        block = single[n]
        row = [n.replace("all_N", "all N")]
        for key, _label, kind in HEADLINE_COLUMNS:
            if key == "duplicate_rate":
                row.append(fmt(duplicates[n]["duplicate_rate"], kind) if n in duplicates else "n/a")
            else:
                row.append(fmt(block.get(key), kind))
        rows.append(row)
    return _table(["N"] + [label for _, label, _ in HEADLINE_COLUMNS], rows)


def confusion_table(block: dict) -> list[str]:
    matrix = block.get("confusion") or {}
    columns = sorted({c for row in matrix.values() for c, v in row.items() if v})
    if not columns:
        return ["(no scored turns)"]
    rows = [[kind] + [str(matrix[kind].get(c, 0)) for c in columns] for kind in sorted(matrix)]
    return _table(["label \\ outcome"] + columns, rows)


def breakdown_tables(block_by_n: dict, dims: tuple[str, ...]) -> list[str]:
    lines: list[str] = []
    ns = _n_keys(block_by_n)
    for dim in dims:
        values = sorted({v for n in ns for v in (block_by_n[n].get("breakdowns", {}).get(dim) or {})})
        if not values:
            continue
        lines.append(f"**{dim}** (accuracy [95% CI], n)")
        lines.append("")
        rows = []
        for n in ns:
            table = block_by_n[n]["breakdowns"].get(dim) or {}
            row = [n]
            for v in values:
                cell = table.get(v)
                row.append(f"{fmt(cell['accuracy'])} ({cell['n']})" if cell else "")
            rows.append(row)
        lines += _table(["N"] + values, rows)
        lines.append("")
    return lines


def render_report(recorded: dict, metrics: dict, summary: dict) -> str:
    lines: list[str] = []
    method = recorded["method"]
    models = recorded["models"]
    git = recorded["git"]
    split_names = sorted(set(metrics["single"]) | set(metrics["sequence"]))
    headline_split = "test" if "test" in metrics["single"] else (split_names[0] if split_names else None)

    if models.get("accept_model_change"):
        lines.append(
            f"**MODEL CHANGE ACCEPTED: expected {models['expected_canonical_slugs']}, "
            f"observed {models['observed_canonical_slugs']}.**"
        )
        lines.append("")
    lines.append(f"# Agent overload run {recorded['run_id']}")
    lines.append("")

    # 1. Run identity
    lines.append("## 1. Run identity")
    lines.append("")
    providers = ", ".join(f"{p} ({n})" for p, n in sorted(summary.get("providers", {}).items())) or "n/a"
    identity = [
        ["Run id", recorded["run_id"]],
        ["Profile", recorded["plan"]["profile"]],
        ["Method", f"{method['name']} v{method['version']}"],
        ["Case set", f"{recorded['case_set_version']} ({(recorded['case_set_hash'] or '')[:16]})"],
        ["Interaction model", f"{models['interaction']} (observed slug: {models['observed_canonical_slugs'].get(models['interaction'])})"],
        ["Summarizer model", models["summarizer"]],
        ["Provider settings", str(models["provider"])],
        ["Providers seen", providers],
        ["Models returned", ", ".join(f"{m} ({n})" for m, n in sorted(summary.get("returned_models", {}).items())) or "n/a"],
        ["Git", f"{git.get('sha')}{' (dirty)' if git.get('dirty') else ''}"],
        ["Harness / scorer", f"{recorded['harness_version']} / {recorded['scorer_version']}"],
        ["Started / ended", f"{recorded['started_at']} / {summary.get('ended_at')}"],
    ]
    lines += _table(["", ""], identity)
    lines.append("")
    warnings = list(summary.get("warnings", []))
    if warnings:
        lines.append("**Warnings:**")
        lines.append("")
        lines += [f"- {w}" for w in warnings]
    else:
        lines.append("No warnings.")
    lines.append("")
    lines.append(
        f"Turns run: {summary.get('turns', 0)}, api_error: {summary.get('api_error_turns', 0)} "
        f"({100 * summary.get('api_error_rate', 0):.2f}%), loop limit: {summary.get('loop_limit_turns', 0)}, "
        f"summarizer errors: {summary.get('summarizer_errors', 0)}."
    )
    lines.append("")

    # 2. Headline
    lines.append(f"## 2. Headline ({headline_split} split, single-turn suite)")
    lines.append("")
    if headline_split:
        lines.append(
            "Rates are shares of turn-runs with 95% cluster-bootstrap CIs over templates. Duplicate rate comes "
            "from carried-forward sequences (n/a where sequences don't run). Tokens, cost and latency count the "
            "routing method's calls only."
        )
        lines.append("")
        lines += headline_table(metrics, headline_split)
    lines.append("")

    # 3. Drop point
    lines.append("## 3. Accuracy drop point")
    lines.append("")
    for split in sorted(metrics["single"]):
        dp = metrics["single"][split].get("drop_point") or {}
        drop = dp.get("drop_n")
        verdict = f"N = {drop}" if drop is not None else "none detected"
        lines.append(
            f"- **{split}:** {verdict} (first N whose accuracy is more than 5 points below N={dp.get('baseline_n')} "
            "with a paired 95% CI excluding 0)."
        )
        diffs = dp.get("differences") or {}
        if diffs:
            lines.append(
                "  Differences from N=10: "
                + ", ".join(f"N={n}: {fmt(d)}" for n, d in sorted(diffs.items(), key=lambda kv: int(kv[0])))
            )
    lines.append("")

    # 4. Confusion matrices
    lines.append("## 4. Confusion matrices")
    lines.append("")
    if headline_split and headline_split in metrics["single"]:
        block = metrics["single"][headline_split]
        ns = _n_keys(block)
        for n in [ns[0], ns[-1]] if len(ns) > 1 else ns:
            lines.append(f"**N = {n}** ({headline_split}, rows = label kind, columns = primary outcome)")
            lines.append("")
            lines += confusion_table(block[n])
            lines.append("")

    # 5. Breakdowns
    lines.append("## 5. Breakdowns")
    lines.append("")
    if headline_split and headline_split in metrics["single"]:
        lines += breakdown_tables(metrics["single"][headline_split], SINGLE_DIMS)

    # 6. Sequences
    lines.append("## 6. Sequences")
    lines.append("")
    if not metrics["sequence"]:
        lines.append("No sequence results.")
        lines.append("")
    for split, seq in sorted(metrics["sequence"].items()):
        lines.append(f"### {split}")
        lines.append("")
        modes = [m for m in ("carried", "corrected") if m in seq]
        ns = sorted({n for m in modes for n in _n_keys(seq[m])}, key=int)
        rows = []
        for n in ns:
            row = [n]
            for m in modes:
                row.append(fmt(seq[m].get(n, {}).get("accuracy")))
            comp = (seq.get("compounding") or {}).get(n)
            row.append(fmt(comp["overall_difference"]) if comp else "n/a")
            row.append(fmt(seq.get("corrected", {}).get(n, {}).get("recency_lock_rate")))
            rows.append(row)
        lines += _table(
            ["N"] + [f"accuracy ({m})" for m in modes] + ["carried − corrected", "recency lock (corrected)"], rows
        )
        lines.append("")
        if seq.get("compounding"):
            turn_ids = sorted({t for c in seq["compounding"].values() for t in c["per_turn"]}, key=int)
            rows = []
            for n, comp in sorted(seq["compounding"].items(), key=lambda kv: int(kv[0])):
                rows.append([n] + [_fmt_value(comp["per_turn"].get(t, {}).get("difference"), "pct") for t in turn_ids])
            lines.append("Compounding: accuracy carried forward minus corrected each turn, by turn index.")
            lines.append("")
            lines += _table(["N"] + [f"t{t}" for t in turn_ids], rows)
            lines.append("")
        if seq.get("duplicates"):
            rows = []
            for n, d in sorted(seq["duplicates"].items(), key=lambda kv: int(kv[0])):
                rows.append(
                    [
                        n,
                        str(d["sequence_runs"]),
                        fmt(d["duplicate_rate"]),
                        fmt(d["inflation_ratio"], "float"),
                        fmt(d["extra_agents_per_thread"], "float"),
                        fmt(d["created_minus_gold"], "float"),
                        str(d["slug_collisions_total"]),
                    ]
                )
            lines.append("Duplicates (carried forward, end of sequence).")
            lines.append("")
            lines += _table(
                ["N", "runs", "duplicate rate", "inflation ratio", "extra agents / thread", "created − gold", "slug collisions"],
                rows,
            )
            lines.append("")
        if "carried" in seq:
            lines += breakdown_tables(seq["carried"], SEQUENCE_DIMS)

    # 7. Tokens
    lines.append("## 7. Tokens")
    lines.append("")
    for split, block in sorted(metrics["single"].items()):
        fit = block.get("roster_token_fit") or {}
        slope = fit.get("slope")
        lines.append(
            f"**{split}:** roster tokens per call ≈ {_fmt_value(slope, 'float')} × N + "
            f"{_fmt_value(fit.get('intercept'), 'float')} (least squares over {fit.get('points', 0)} turn-runs)."
        )
        lines.append("")
        rows = []
        for n in _n_keys(block):
            b = block[n]
            rows.append(
                [
                    n,
                    fmt(b.get("roster_tokens_per_call_median"), "int"),
                    fmt(b.get("roster_tokens_per_turn_median"), "int"),
                    fmt(b.get("input_tokens_per_turn_median"), "int"),
                    fmt(b.get("input_tokens_per_turn_p95"), "int", ci=False),
                    fmt(b.get("routing_calls_per_turn_mean"), "float"),
                ]
            )
        lines += _table(["N", "roster tok/call", "roster tok/turn", "input tok/turn p50", "input tok/turn p95", "routing calls/turn"], rows)
        lines.append("")

    # 8. Consistency, invalid calls, loop limits
    lines.append("## 8. Consistency, invalid calls, loop limits")
    lines.append("")
    rows = []
    for split, block in sorted(metrics["single"].items()):
        for n in _n_keys(block):
            b = block[n]
            rows.append(
                [split, n, fmt(b.get("consistency")), fmt(b.get("invalid_call_rate")), str(b.get("loop_limit_turns", 0)), str(b.get("api_error_turns", 0))]
            )
    lines += _table(["split", "N", "consistency", "invalid call rate", "loop limit turns", "api_error turns"], rows)
    lines.append("")

    # 9. Dev split
    lines.append("## 9. Dev split")
    lines.append("")
    if "dev" in metrics["single"] and headline_split != "dev":
        lines += headline_table(metrics, "dev")
    elif headline_split == "dev":
        lines.append("The headline above is the dev split (no test split in this run).")
    else:
        lines.append("No dev results.")
    lines.append("")

    # 10. Costs
    lines.append("## 10. Costs")
    lines.append("")
    costs = metrics.get("costs") or {}
    lines.append(f"Total: ${costs.get('total_cost_usd', 0):.4f} over {costs.get('total_calls', 0)} calls.")
    lines.append("")
    rows = [
        [p, str(r["calls"]), f"${r['cost_usd']:.4f}", f"{r['prompt_tokens']:,}", f"{r['completion_tokens']:,}", f"{r['reasoning_tokens']:,}"]
        for p, r in (costs.get("by_purpose") or {}).items()
    ]
    lines += _table(["purpose", "calls", "cost", "prompt tokens", "completion tokens", "reasoning tokens"], rows)
    lines.append("")
    price = summary.get("price_check")
    if price:
        lines.append(
            f"Price check: actual cost / cost at the pricing table's standard rates = {price['ratio']:.3f} "
            f"over {price['calls']} calls. Near 1.0 means the standard endpoint; well below or above suggests "
            "the flex or fast endpoint."
        )
        lines.append("")
    profile = metrics.get("cost_profile") or {}
    if profile:
        lines.append(
            "Measured per-unit costs (used by later pre-run estimates): "
            + ", ".join(f"{k} = {_fmt_value(v, 'float') if 'calls' in k else ('n/a' if v is None else f'${v:.5f}')}" for k, v in profile.items())
        )
        lines.append("")
    return "\n".join(lines)
