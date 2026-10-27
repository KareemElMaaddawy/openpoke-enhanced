"""Aggregation of scored turns into ``metrics.json``, with cluster-bootstrap CIs.

Design: Metrics and Uncertainty. Every metric is computed per split, per suite
(per mode for sequences) and per roster size N; "all_N" pools the sizes. CIs are
95% cluster bootstraps over templates (sequences for the sequence suite): one set
of resample weights is drawn per (split, suite, mode) scope and reused for every
N, so differences between sizes (the accuracy drop point) are paired.
"""

from __future__ import annotations

import random
from collections import Counter, defaultdict
from dataclasses import dataclass
from typing import Any, Callable, Iterable, Optional

from .scoring import CORRECT_OUTCOMES, DELEGATING_KINDS, PRIMARY_OUTCOMES, REUSE_KINDS, STATUS_API_ERROR
from .util import median, percentile

METRICS_VERSION = "1"

SINGLE_DIMS = (
    "query_style",
    "message_subtype",
    "label_kind",
    "target_position",
    "target_age_bucket",
    "name_descriptiveness",
    "history_type",
    "target_name_visible",
)
SEQUENCE_DIMS = ("query_style", "message_subtype", "label_kind", "turn_index")
RECALL_KS = (1, 3, 5, 10, 20)
DROP_THRESHOLD = 0.05
DORMANT_DAYS = 14


@dataclass(frozen=True)
class StatsConfig:
    resamples: int = 2000
    ci: float = 0.95
    seed: int = 20261025

    @classmethod
    def from_config(cls, stats: dict) -> "StatsConfig":
        return cls(
            resamples=int(stats.get("bootstrap_resamples", 2000)),
            ci=float(stats.get("ci", 0.95)),
            seed=int(stats.get("seed", 20261025)),
        )


# ---------------------------------------------------------------------------
# Cluster bootstrap


class Bootstrap:
    """Resample weights over a fixed list of clusters (templates or sequences)."""

    def __init__(self, cluster_ids: Iterable[str], stats: StatsConfig):
        self.ids = sorted(set(cluster_ids))
        self.index = {cid: i for i, cid in enumerate(self.ids)}
        self.stats = stats
        rng = random.Random(stats.seed)
        size = len(self.ids)
        self.weights: list[list[int]] = []
        for _ in range(stats.resamples if size else 0):
            counts = [0] * size
            for i in rng.choices(range(size), k=size):
                counts[i] += 1
            self.weights.append(counts)

    def _bounds(self, samples: list[float]) -> Optional[list[float]]:
        if not samples:
            return None
        alpha = (1.0 - self.stats.ci) / 2.0
        return [percentile(samples, 100 * alpha), percentile(samples, 100 * (1 - alpha))]

    def _vector(self, per_cluster: dict[str, float]) -> list[float]:
        vec = [0.0] * len(self.ids)
        for cid, value in per_cluster.items():
            vec[self.index[cid]] = value
        return vec

    def ratio(self, num: dict[str, float], den: dict[str, float]) -> dict:
        """Σnum/Σden over clusters, with a percentile CI."""
        total_den = sum(den.values())
        if total_den <= 0:
            return {"value": None, "ci": None, "n": 0}
        value = sum(num.values()) / total_den
        nv, dv = self._vector(num), self._vector(den)
        active = [i for i, d in enumerate(dv) if d]
        samples = []
        for w in self.weights:
            d = sum(w[i] * dv[i] for i in active)
            if d > 0:
                samples.append(sum(w[i] * nv[i] for i in active) / d)
        return {"value": value, "ci": self._bounds(samples), "n": total_den}

    def ratio_diff(self, num_a, den_a, num_b, den_b) -> dict:
        """Paired difference of two ratios (a − b) over the same clusters."""
        if sum(den_a.values()) <= 0 or sum(den_b.values()) <= 0:
            return {"value": None, "ci": None}
        value = sum(num_a.values()) / sum(den_a.values()) - sum(num_b.values()) / sum(den_b.values())
        na, da, nb, db = (self._vector(x) for x in (num_a, den_a, num_b, den_b))
        samples = []
        for w in self.weights:
            sda = sum(wi * x for wi, x in zip(w, da))
            sdb = sum(wi * x for wi, x in zip(w, db))
            if sda > 0 and sdb > 0:
                sna = sum(wi * x for wi, x in zip(w, na))
                snb = sum(wi * x for wi, x in zip(w, nb))
                samples.append(sna / sda - snb / sdb)
        return {"value": value, "ci": self._bounds(samples)}

    def quantile(self, values: dict[str, list[float]], q: float) -> dict:
        """Percentile ``q`` of pooled unit values, with a CI from resampling clusters."""
        pooled = [v for vals in values.values() for v in vals]
        if not pooled:
            return {"value": None, "ci": None, "n": 0}
        point = median(pooled) if q == 50 else percentile(pooled, q)
        per_index = [values.get(cid, []) for cid in self.ids]
        active = [i for i, vals in enumerate(per_index) if vals]
        samples = []
        for w in self.weights:
            sample: list[float] = []
            for i in active:
                if w[i]:
                    sample.extend(per_index[i] * w[i])
            if sample:
                samples.append(median(sample) if q == 50 else percentile(sample, q))
        return {"value": point, "ci": self._bounds(samples), "n": len(pooled)}

    def mean(self, values: dict[str, list[float]]) -> dict:
        num = {cid: float(sum(vals)) for cid, vals in values.items() if vals}
        den = {cid: float(len(vals)) for cid, vals in values.items() if vals}
        return self.ratio(num, den)


# ---------------------------------------------------------------------------
# Helpers over turn records


def _scored(turns: list[dict]) -> list[dict]:
    return [t for t in turns if t.get("status") != STATUS_API_ERROR]


def _kind(turn: dict) -> str:
    return turn["label"]["kind"]


def _has_outcome(turn: dict, outcome: str) -> bool:
    return any(o["outcome"] == outcome for o in turn.get("outcomes", []))


def _count_by_cluster(turns: list[dict], pred: Callable[[dict], bool], cluster: Callable[[dict], str]) -> dict:
    counts: dict[str, float] = defaultdict(float)
    for t in turns:
        if pred(t):
            counts[cluster(t)] += 1
    return dict(counts)


def _values_by_cluster(turns: list[dict], fn: Callable[[dict], Any], cluster) -> dict[str, list[float]]:
    out: dict[str, list[float]] = defaultdict(list)
    for t in turns:
        value = fn(t)
        if value is not None:
            out[cluster(t)].append(float(value))
    return dict(out)


def _cluster(turn: dict) -> str:
    return turn["case_id"]


def _rate(boot: Bootstrap, turns: list[dict], num_pred, den_pred) -> dict:
    den_turns = [t for t in turns if den_pred(t)]
    num = _count_by_cluster(den_turns, num_pred, _cluster)
    den = _count_by_cluster(den_turns, lambda t: True, _cluster)
    return boot.ratio(num, den)


def routing_metrics(boot: Bootstrap, turns: list[dict]) -> dict:
    """Routing accuracy and the outcome rates for one group of turn-runs."""
    scored = _scored(turns)
    delegating = lambda t: _kind(t) in DELEGATING_KINDS  # noqa: E731
    reuse = lambda t: _kind(t) in REUSE_KINDS  # noqa: E731
    everything = lambda t: True  # noqa: E731
    metrics = {
        "turns": len(turns),
        "scored_turns": len(scored),
        "api_error_turns": len(turns) - len(scored),
        "loop_limit_turns": sum(1 for t in scored if t.get("status") == "loop_limit"),
        "accuracy": _rate(boot, scored, lambda t: t["turn_correct"], everything),
        "accuracy_lenient": _rate(boot, scored, lambda t: t["turn_correct_lenient"], everything),
        "false_spawn_rate": _rate(boot, scored, lambda t: t["primary_outcome"] == "false_spawn", reuse),
        "misroute_rate": _rate(boot, scored, lambda t: t["primary_outcome"] == "misroute", reuse),
        "duplicate_reuse_rate": _rate(boot, scored, lambda t: t["primary_outcome"] == "duplicate_reuse", reuse),
        "false_reuse_rate": _rate(
            boot, scored, lambda t: t["primary_outcome"] == "false_reuse", lambda t: _kind(t) == "CREATE"
        ),
        "missed_delegation_rate": _rate(
            boot, scored, lambda t: t["primary_outcome"] == "missed_delegation", delegating
        ),
        "extra_delegation_rate": _rate(boot, scored, lambda t: _has_outcome(t, "extra_delegation"), everything),
        "invalid_call_rate": _rate(boot, scored, lambda t: _has_outcome(t, "invalid_call"), everything),
        "near_duplicate_share": _rate(
            boot,
            scored,
            lambda t: "near_duplicate" in t.get("tags", []),
            lambda t: t["primary_outcome"] == "false_spawn",
        ),
        "recency_lock_rate": _rate(
            boot, scored, lambda t: "recency" in t.get("tags", []), lambda t: bool(t.get("recency_eligible"))
        ),
        "excluded_target_error_rate": _rate(
            boot, scored, lambda t: "target_excluded" in t.get("tags", []), delegating
        ),
        "excluded_target_error_rate_old": _rate(
            boot,
            scored,
            lambda t: "target_excluded" in t.get("tags", []),
            lambda t: delegating(t) and (t.get("dims") or {}).get("target_age_bucket") == "old",
        ),
        "consistency": consistency(boot, scored),
        "agents_shown_median": boot.quantile(_values_by_cluster(scored, lambda t: t.get("agents_shown"), _cluster), 50),
        "dormant_fraction": boot.mean(_values_by_cluster(scored, lambda t: t.get("dormant_fraction"), _cluster)),
        "confusion": confusion(scored),
    }
    if any(t.get("candidate_rank") is not None or t.get("has_candidates") for t in scored):
        with_candidates = [t for t in scored if t.get("has_candidates") and _kind(t) in REUSE_KINDS]
        metrics["recall_at_k"] = {
            str(k): _rate(
                boot,
                with_candidates,
                lambda t, k=k: t.get("candidate_rank") is not None and t["candidate_rank"] <= k,
                lambda t: True,
            )
            for k in RECALL_KS
        }
    return metrics


def consistency(boot: Bootstrap, scored: list[dict]) -> dict:
    """Share of templates whose reps all produced the same primary outcome (None with < 2 reps)."""
    by_template: dict[tuple, list[str]] = defaultdict(list)
    for t in scored:
        by_template[(t["case_id"], t.get("turn"))].append(t["primary_outcome"])
    num: dict[str, float] = defaultdict(float)
    den: dict[str, float] = defaultdict(float)
    for (case_id, _turn), outcomes in by_template.items():
        if len(outcomes) < 2:
            continue
        den[case_id] += 1
        if len(set(outcomes)) == 1:
            num[case_id] += 1
    if not den:
        return {"value": None, "ci": None, "n": 0}
    return boot.ratio(dict(num), dict(den))


def confusion(scored: list[dict]) -> dict:
    matrix: dict[str, dict[str, int]] = {}
    for t in scored:
        row = matrix.setdefault(_kind(t), {o: 0 for o in PRIMARY_OUTCOMES})
        row[t["primary_outcome"]] = row.get(t["primary_outcome"], 0) + 1
    return matrix


def cost_metrics(boot: Bootstrap, turns: list[dict], probes: Optional[dict[tuple, float]] = None) -> dict:
    """Tokens, cost, latency and calls per turn (the method's calls only)."""
    scored = _scored(turns)
    out = {
        "input_tokens_per_turn_median": boot.quantile(_values_by_cluster(scored, lambda t: t.get("prompt_tokens"), _cluster), 50),
        "input_tokens_per_turn_p95": boot.quantile(_values_by_cluster(scored, lambda t: t.get("prompt_tokens"), _cluster), 95),
        "output_tokens_per_turn_mean": boot.mean(_values_by_cluster(scored, lambda t: t.get("completion_tokens"), _cluster)),
        "cost_per_turn_mean": boot.mean(_values_by_cluster(scored, lambda t: t.get("cost"), _cluster)),
        "latency_ms_per_turn_median": boot.quantile(_values_by_cluster(scored, lambda t: t.get("latency_ms"), _cluster), 50),
        "latency_ms_per_turn_p95": boot.quantile(_values_by_cluster(scored, lambda t: t.get("latency_ms"), _cluster), 95),
        "calls_per_turn_mean": boot.mean(_values_by_cluster(scored, lambda t: t.get("n_calls"), _cluster)),
        "routing_calls_per_turn_mean": boot.mean(_values_by_cluster(scored, lambda t: t.get("routing_calls"), _cluster)),
    }
    if probes is not None:
        per_call = _values_by_cluster(scored, lambda t: roster_tokens_per_call(t, probes), _cluster)
        per_turn = _values_by_cluster(
            scored,
            lambda t: None
            if roster_tokens_per_call(t, probes) is None
            else roster_tokens_per_call(t, probes) * (t.get("routing_calls") or 0),
            _cluster,
        )
        out["roster_tokens_per_call_median"] = boot.quantile(per_call, 50)
        out["roster_tokens_per_turn_median"] = boot.quantile(per_turn, 50)
    return out


def roster_tokens_per_call(turn: dict, probes: dict[tuple, float]) -> Optional[float]:
    base = probes.get((turn["split"], turn["case_id"]))
    first = turn.get("first_call_prompt_tokens")
    if base is None or first is None:
        return None
    return float(first) - float(base)


def linear_fit(points: list[tuple[float, float]]) -> dict:
    """Least-squares fit y = slope·x + intercept."""
    if len(points) < 2 or len({x for x, _ in points}) < 2:
        return {"slope": None, "intercept": None, "points": len(points)}
    n = len(points)
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    sxy = sum((x - mx) * (y - my) for x, y in points)
    slope = sxy / sxx
    return {"slope": slope, "intercept": my - slope * mx, "points": n}


def breakdowns(boot: Bootstrap, turns: list[dict], dims: tuple[str, ...]) -> dict:
    """Accuracy (with CI) and primary-outcome shares for each value of each dimension."""
    scored = _scored(turns)
    out: dict[str, dict] = {}
    for dim in dims:
        groups: dict[str, list[dict]] = defaultdict(list)
        for t in scored:
            value = (t.get("dims") or {}).get(dim)
            groups["none" if value is None else str(value)].append(t)
        table = {}
        for value, members in sorted(groups.items()):
            counts = Counter(t["primary_outcome"] for t in members)
            table[value] = {
                "n": len(members),
                "accuracy": _rate(boot, members, lambda t: t["turn_correct"], lambda t: True),
                "outcome_shares": {o: counts[o] / len(members) for o in sorted(counts)},
            }
        out[dim] = table
    return out


# ---------------------------------------------------------------------------
# Sequence-specific


def compounding(boot: Bootstrap, carried: list[dict], corrected: list[dict]) -> dict:
    """Accuracy per turn index, carried forward minus corrected each turn, plus a paired overall difference."""
    carried, corrected = _scored(carried), _scored(corrected)
    per_turn = {}
    for turn_index in sorted({t["turn"] for t in carried + corrected}):
        a = [t for t in carried if t["turn"] == turn_index]
        b = [t for t in corrected if t["turn"] == turn_index]
        acc_a = sum(bool(t["turn_correct"]) for t in a) / len(a) if a else None
        acc_b = sum(bool(t["turn_correct"]) for t in b) / len(b) if b else None
        per_turn[str(turn_index)] = {
            "carried": acc_a,
            "corrected": acc_b,
            "difference": None if acc_a is None or acc_b is None else acc_a - acc_b,
        }
    num_a = _count_by_cluster(carried, lambda t: t["turn_correct"], _cluster)
    den_a = _count_by_cluster(carried, lambda t: True, _cluster)
    num_b = _count_by_cluster(corrected, lambda t: t["turn_correct"], _cluster)
    den_b = _count_by_cluster(corrected, lambda t: True, _cluster)
    return {"per_turn": per_turn, "overall_difference": boot.ratio_diff(num_a, den_a, num_b, den_b)}


def duplicate_metrics(boot: Bootstrap, sequences: list[dict]) -> dict:
    runs = [s for s in sequences if s.get("status") == "ok"]

    def values(key: str) -> dict[str, list[float]]:
        return _values_by_cluster(runs, lambda s: s.get(key), _cluster)

    return {
        "sequence_runs": len(runs),
        "duplicate_rate": boot.mean(values("duplicate_rate")),
        "inflation_ratio": boot.mean(values("inflation_ratio")),
        "extra_agents_per_thread": boot.mean(values("extra_agents_per_thread")),
        "extra_agents": boot.mean(values("extra_agents")),
        "created_minus_gold": boot.mean(
            _values_by_cluster(runs, lambda s: s["created"] - s["gold_created"], _cluster)
        ),
        "slug_collisions_total": sum(s.get("slug_collisions", 0) for s in runs),
        "slug_collisions": boot.mean(values("slug_collisions")),
    }


def drop_point(boot: Bootstrap, turns_by_n: dict[int, list[dict]], baseline_n: int = 10) -> dict:
    """Smallest N whose accuracy is > 5 points below N=10 with a paired 95% CI excluding 0."""
    if baseline_n not in turns_by_n:
        return {"baseline_n": baseline_n, "drop_n": None, "differences": {}, "note": "baseline N not run"}
    base = _scored(turns_by_n[baseline_n])
    num_b = _count_by_cluster(base, lambda t: t["turn_correct"], _cluster)
    den_b = _count_by_cluster(base, lambda t: True, _cluster)
    differences = {}
    drop_n = None
    for n in sorted(turns_by_n):
        if n == baseline_n:
            continue
        scored = _scored(turns_by_n[n])
        num_a = _count_by_cluster(scored, lambda t: t["turn_correct"], _cluster)
        den_a = _count_by_cluster(scored, lambda t: True, _cluster)
        diff = boot.ratio_diff(num_a, den_a, num_b, den_b)
        differences[str(n)] = diff
        if (
            drop_n is None
            and diff["value"] is not None
            and diff["value"] < -DROP_THRESHOLD
            and diff["ci"] is not None
            and diff["ci"][1] < 0
        ):
            drop_n = n
    return {"baseline_n": baseline_n, "drop_n": drop_n, "differences": differences}


# ---------------------------------------------------------------------------
# Top level


def _by_n(turns: list[dict]) -> dict[int, list[dict]]:
    out: dict[int, list[dict]] = defaultdict(list)
    for t in turns:
        out[int(t["N"])].append(t)
    return dict(sorted(out.items()))


def _group_block(boot: Bootstrap, turns: list[dict], dims: tuple[str, ...], probes) -> dict:
    block = {}
    for n, members in _by_n(turns).items():
        block[str(n)] = {
            **routing_metrics(boot, members),
            **cost_metrics(boot, members, probes),
            "breakdowns": breakdowns(boot, members, dims),
        }
    block["all_N"] = {**routing_metrics(boot, turns), **cost_metrics(boot, turns, probes)}
    return block


def compute_metrics(
    turns: list[dict],
    sequences: list[dict],
    calls: list[dict],
    stats: StatsConfig,
) -> dict:
    """All metrics for one run. ``turns`` includes token-probe lines (suite ``token_probe``)."""
    probes = {
        (t["split"], t["case_id"]): t["prompt_tokens"]
        for t in turns
        if t["suite"] == "token_probe" and t.get("status") != STATUS_API_ERROR and t.get("prompt_tokens") is not None
    }
    result: dict[str, Any] = {"metrics_version": METRICS_VERSION, "single": {}, "sequence": {}}

    for split in sorted({t["split"] for t in turns}):
        single = [t for t in turns if t["split"] == split and t["suite"] == "single"]
        if single:
            boot = Bootstrap((t["case_id"] for t in single), stats)
            block = _group_block(boot, single, SINGLE_DIMS, probes)
            block["drop_point"] = drop_point(boot, _by_n(single))
            points = [
                (float(t["N"]), roster_tokens_per_call(t, probes))
                for t in _scored(single)
                if roster_tokens_per_call(t, probes) is not None
            ]
            block["roster_token_fit"] = linear_fit(points)
            result["single"][split] = block

        seq_turns = [t for t in turns if t["split"] == split and t["suite"] == "sequence"]
        if seq_turns:
            boot = Bootstrap((t["case_id"] for t in seq_turns), stats)
            seq_block: dict[str, Any] = {}
            for mode in sorted({t["mode"] for t in seq_turns}):
                members = [t for t in seq_turns if t["mode"] == mode]
                seq_block[mode] = _group_block(boot, members, SEQUENCE_DIMS, None)
            modes = {t["mode"] for t in seq_turns}
            if {"carried", "corrected"} <= modes:
                seq_block["compounding"] = {}
                for n, members in _by_n(seq_turns).items():
                    seq_block["compounding"][str(n)] = compounding(
                        boot,
                        [t for t in members if t["mode"] == "carried"],
                        [t for t in members if t["mode"] == "corrected"],
                    )
            seq_runs = [s for s in sequences if s["split"] == split and s["mode"] == "carried"]
            if seq_runs:
                seq_block["duplicates"] = {
                    str(n): duplicate_metrics(boot, [s for s in seq_runs if int(s["N"]) == n])
                    for n in sorted({int(s["N"]) for s in seq_runs})
                }
            result["sequence"][split] = seq_block

    result["costs"] = cost_totals(calls)
    return result


def cost_totals(calls: list[dict]) -> dict:
    by_purpose: dict[str, dict[str, float]] = {}
    for call in calls:
        row = by_purpose.setdefault(
            call.get("purpose", "unknown"),
            {"calls": 0, "cost_usd": 0.0, "prompt_tokens": 0, "completion_tokens": 0, "reasoning_tokens": 0},
        )
        row["calls"] += 1
        row["cost_usd"] += float(call.get("cost") or 0.0)
        row["prompt_tokens"] += int(call.get("prompt_tokens") or 0)
        row["completion_tokens"] += int(call.get("completion_tokens") or 0)
        row["reasoning_tokens"] += int(call.get("reasoning_tokens") or 0)
    return {
        "total_cost_usd": sum(r["cost_usd"] for r in by_purpose.values()),
        "total_calls": sum(r["calls"] for r in by_purpose.values()),
        "by_purpose": dict(sorted(by_purpose.items())),
    }


def is_correct_outcome(outcome: Optional[str]) -> bool:
    return outcome in CORRECT_OUTCOMES
