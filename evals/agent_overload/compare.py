"""Paired comparison of two runs: ``python -m evals.agent_overload.compare <baseline> <candidate>``.

Runs are paired by template (case, and turn for sequences) at each split, suite,
mode and N. Each metric difference (candidate − baseline) gets a paired cluster
bootstrap CI, and each group gets a McNemar test on templates' majority outcome
(correct only when more than half of the reps are correct). Free: no API calls.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import defaultdict
from pathlib import Path
from typing import Optional

from .harness.metrics import Bootstrap, StatsConfig
from .harness.report import fmt
from .harness.runner import read_jsonl_gz
from .harness.scoring import REUSE_KINDS, STATUS_API_ERROR
from .harness.util import EVAL_ROOT

RESULTS_ROOT = EVAL_ROOT / "results"
RATE_METRICS = [
    ("accuracy", lambda t: bool(t["turn_correct"]), lambda t: True),
    ("accuracy_lenient", lambda t: bool(t["turn_correct_lenient"]), lambda t: True),
    ("false_spawn_rate", lambda t: t["primary_outcome"] == "false_spawn", lambda t: t["label"]["kind"] in REUSE_KINDS),
    ("misroute_rate", lambda t: t["primary_outcome"] == "misroute", lambda t: t["label"]["kind"] in REUSE_KINDS),
    ("false_reuse_rate", lambda t: t["primary_outcome"] == "false_reuse", lambda t: t["label"]["kind"] == "CREATE"),
    ("missed_delegation_rate", lambda t: t["primary_outcome"] == "missed_delegation", lambda t: t["label"]["kind"] != "NO_DELEGATION"),
    ("extra_delegation_rate", lambda t: any(o["outcome"] == "extra_delegation" for o in t["outcomes"]), lambda t: True),
    ("invalid_call_rate", lambda t: any(o["outcome"] == "invalid_call" for o in t["outcomes"]), lambda t: True),
]
MEAN_METRICS = [
    ("input_tokens_per_turn_mean", "prompt_tokens", "int"),
    ("cost_per_turn_mean", "cost", "usd"),
    ("latency_ms_per_turn_mean", "latency_ms", "ms"),
]


class CompareError(RuntimeError):
    pass


def resolve_run(ref: str, results_root: Path) -> Path:
    path = Path(ref)
    if path.is_dir():
        return path
    candidate = results_root / ref
    if candidate.is_dir():
        return candidate
    raise CompareError(f"run {ref!r} not found (looked in {results_root})")


def load_run(run_dir: Path) -> tuple[dict, list[dict]]:
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    turns = read_jsonl_gz(run_dir / "turns.jsonl.gz")
    return config, turns


def check_comparable(a: dict, b: dict) -> list[str]:
    """Raise on hard mismatches; return warnings for soft ones."""
    for name, cfg in (("baseline", a), ("candidate", b)):
        end = cfg.get("end") or {}
        if cfg.get("fake_model"):
            raise CompareError(f"{name} run {cfg['run_id']} used the fake model")
        if end.get("capped"):
            raise CompareError(f"{name} run {cfg['run_id']} was capped")
        if end.get("failed"):
            raise CompareError(f"{name} run {cfg['run_id']} failed its api_error limit")
    if a["case_set_hash"] != b["case_set_hash"]:
        raise CompareError("case_set_hash differs: the runs used different fixtures")
    shared = sorted(set(a["plan"]["splits"]) & set(b["plan"]["splits"]))
    if not shared:
        raise CompareError(f"the runs share no split: {a['plan']['splits']} vs {b['plan']['splits']}")
    warnings = []
    if sorted(a["plan"]["splits"]) != sorted(b["plan"]["splits"]):
        warnings.append(f"comparing the shared split(s) only: {shared}")
    if a["models"].get("observed_canonical_slugs") != b["models"].get("observed_canonical_slugs"):
        warnings.append(f"model canonical slugs differ: {a['models']['observed_canonical_slugs']} vs {b['models']['observed_canonical_slugs']}")
    if a["models"].get("provider") != b["models"].get("provider"):
        warnings.append("provider settings differ")
    if a.get("harness_version") != b.get("harness_version"):
        warnings.append(f"harness version differs: {a.get('harness_version')} vs {b.get('harness_version')}")
    if a["runtime"].get("concurrency") != b["runtime"].get("concurrency"):
        warnings.append("concurrency differs: latency differences are not comparable")
    for key in ("single_sizes", "sequence_sizes", "single_reps", "sequence_reps"):
        if a["plan"].get(key) != b["plan"].get(key):
            warnings.append(f"plan {key} differs; only shared templates and sizes are compared")
    return warnings


def mcnemar(b: int, c: int) -> float:
    """Exact two-sided McNemar p-value from the discordant counts."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def _group_key(t: dict) -> tuple:
    return (t["split"], t["suite"], t.get("mode") or "-", int(t["N"]))


def _template(t: dict) -> tuple:
    return (t["case_id"], t.get("turn"))


def compare_group(turns_a: list[dict], turns_b: list[dict], stats: StatsConfig) -> dict:
    by_a: dict[tuple, list[dict]] = defaultdict(list)
    by_b: dict[tuple, list[dict]] = defaultdict(list)
    for t in turns_a:
        by_a[_template(t)].append(t)
    for t in turns_b:
        by_b[_template(t)].append(t)
    shared = sorted(set(by_a) & set(by_b), key=str)
    pa = [t for k in shared for t in by_a[k]]
    pb = [t for k in shared for t in by_b[k]]
    boot = Bootstrap((k[0] for k in shared), stats)
    result: dict = {"templates": len(shared), "turns_baseline": len(pa), "turns_candidate": len(pb), "metrics": {}}

    def counts(turns, num, den):
        n: dict[str, float] = defaultdict(float)
        d: dict[str, float] = defaultdict(float)
        for t in turns:
            if den(t):
                d[t["case_id"]] += 1
                if num(t):
                    n[t["case_id"]] += 1
        return dict(n), dict(d)

    for name, num, den in RATE_METRICS:
        na, da = counts(pa, num, den)
        nb, db = counts(pb, num, den)
        base = sum(na.values()) / sum(da.values()) if sum(da.values()) else None
        cand = sum(nb.values()) / sum(db.values()) if sum(db.values()) else None
        result["metrics"][name] = {"baseline": base, "candidate": cand, "difference": boot.ratio_diff(nb, db, na, da), "kind": "pct"}
    for name, field, kind in MEAN_METRICS:
        def sums(turns):
            n: dict[str, float] = defaultdict(float)
            d: dict[str, float] = defaultdict(float)
            for t in turns:
                if t.get(field) is not None:
                    n[t["case_id"]] += float(t[field])
                    d[t["case_id"]] += 1
            return dict(n), dict(d)

        na, da = sums(pa)
        nb, db = sums(pb)
        base = sum(na.values()) / sum(da.values()) if sum(da.values()) else None
        cand = sum(nb.values()) / sum(db.values()) if sum(db.values()) else None
        result["metrics"][name] = {"baseline": base, "candidate": cand, "difference": boot.ratio_diff(nb, db, na, da), "kind": kind}

    def majority(turns: list[dict]) -> bool:
        return sum(bool(t["turn_correct"]) for t in turns) > len(turns) / 2

    b = c = 0
    for k in shared:
        ma, mb = majority(by_a[k]), majority(by_b[k])
        if ma and not mb:
            b += 1
        elif mb and not ma:
            c += 1
    result["mcnemar"] = {"baseline_only_correct": b, "candidate_only_correct": c, "p_value": mcnemar(b, c)}
    return result


def compare_runs(dir_a: Path, dir_b: Path) -> dict:
    cfg_a, turns_a = load_run(dir_a)
    cfg_b, turns_b = load_run(dir_b)
    warnings = check_comparable(cfg_a, cfg_b)
    stats = StatsConfig.from_config(cfg_a["stats"])
    scored_a = [t for t in turns_a if t["suite"] in ("single", "sequence") and t["status"] != STATUS_API_ERROR]
    scored_b = [t for t in turns_b if t["suite"] in ("single", "sequence") and t["status"] != STATUS_API_ERROR]
    groups_a: dict[tuple, list[dict]] = defaultdict(list)
    groups_b: dict[tuple, list[dict]] = defaultdict(list)
    for t in scored_a:
        groups_a[_group_key(t)].append(t)
    for t in scored_b:
        groups_b[_group_key(t)].append(t)
    groups = {}
    for key in sorted(set(groups_a) & set(groups_b)):
        groups["|".join(map(str, key))] = compare_group(groups_a[key], groups_b[key], stats)
    pooled = {}
    for split, suite, mode in sorted({k[:3] for k in set(groups_a) & set(groups_b)}):
        a = [t for k, v in groups_a.items() if k[:3] == (split, suite, mode) for t in v]
        b = [t for k, v in groups_b.items() if k[:3] == (split, suite, mode) for t in v]
        # Pool sizes by treating (case, turn, N) as the template; the case stays the cluster.
        a2 = [dict(t, turn=(t.get("turn"), t["N"])) for t in a]
        b2 = [dict(t, turn=(t.get("turn"), t["N"])) for t in b]
        pooled[f"{split}|{suite}|{mode}|all_N"] = compare_group(a2, b2, stats)
    return {
        "baseline": {"run_id": cfg_a["run_id"], "method": cfg_a["method"]},
        "candidate": {"run_id": cfg_b["run_id"], "method": cfg_b["method"]},
        "case_set_hash": cfg_a["case_set_hash"],
        "warnings": warnings,
        "groups": groups,
        "pooled": pooled,
    }


def render_markdown(result: dict) -> str:
    a, b = result["baseline"], result["candidate"]
    lines = [
        f"# Comparison: {b['method']['name']} v{b['method']['version']} vs {a['method']['name']} v{a['method']['version']}",
        "",
        f"Baseline run `{a['run_id']}`, candidate run `{b['run_id']}`, case set `{result['case_set_hash'][:16]}`.",
        "Differences are candidate − baseline with paired 95% bootstrap CIs over templates. McNemar uses each "
        "template's majority outcome (a tie counts as not correct).",
        "",
    ]
    if result["warnings"]:
        lines += ["**Warnings:**", ""] + [f"- {w}" for w in result["warnings"]] + [""]
    for title, block in (("Pooled over N", result["pooled"]), ("Per roster size", result["groups"])):
        lines += [f"## {title}", ""]
        header = "| group | templates | accuracy Δ | false spawn Δ | misroute Δ | false reuse Δ | input tok Δ | cost Δ | McNemar p (b/c) |"
        lines += [header, "| " + " | ".join("---" for _ in header.strip("|").split("|")) + " |"]
        for key, g in block.items():
            m = g["metrics"]
            mc = g["mcnemar"]
            lines.append(
                f"| {key} | {g['templates']} | {fmt(m['accuracy']['difference'])} | {fmt(m['false_spawn_rate']['difference'])} | "
                f"{fmt(m['misroute_rate']['difference'])} | {fmt(m['false_reuse_rate']['difference'])} | "
                f"{fmt(m['input_tokens_per_turn_mean']['difference'], 'int')} | {fmt(m['cost_per_turn_mean']['difference'], 'usd')} | "
                f"{mc['p_value']:.3g} ({mc['baseline_only_correct']}/{mc['candidate_only_correct']}) |"
            )
        lines.append("")
    return "\n".join(lines)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m evals.agent_overload.compare", description=__doc__)
    parser.add_argument("baseline", help="baseline run id or directory")
    parser.add_argument("candidate", help="candidate run id or directory")
    parser.add_argument("--results-dir", type=Path, default=RESULTS_ROOT)
    parser.add_argument("--out", type=Path, default=None, help="output directory (default results/comparisons/<a>__vs__<b>)")
    args = parser.parse_args(argv)
    try:
        dir_a = resolve_run(args.baseline, args.results_dir)
        dir_b = resolve_run(args.candidate, args.results_dir)
        result = compare_runs(dir_a, dir_b)
    except CompareError as exc:
        print(f"refusing to compare: {exc}")
        return 2
    out = args.out or (args.results_dir / "comparisons" / f"{dir_a.name}__vs__{dir_b.name}")
    out.mkdir(parents=True, exist_ok=True)
    (out / "compare.json").write_text(json.dumps(result, indent=2, sort_keys=True, default=str), encoding="utf-8")
    markdown = render_markdown(result)
    (out / "compare.md").write_text(markdown, encoding="utf-8")
    print(markdown)
    print(f"\nwritten to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
