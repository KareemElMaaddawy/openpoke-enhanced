"""Small shared helpers: timestamps, hashing, seeds and name similarity."""

from __future__ import annotations

import hashlib
import json
import logging
import random
from datetime import datetime, timedelta
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any, Iterable

from server.services.execution.log_store import _slugify

# The production logger warns on every malformed tool call; the harness records those itself.
logging.getLogger("openpoke.server").setLevel(logging.ERROR)

TS_FORMAT = "%Y-%m-%d %H:%M:%S"

REPO_ROOT = Path(__file__).resolve().parents[3]
EVAL_ROOT = REPO_ROOT / "evals" / "agent_overload"

# Stopwords for token comparisons of agent-name slugs (design: Tags, near_duplicate).
STOPWORDS = frozenset({"to", "for", "the", "a", "an", "of", "and", "with", "my", "re"})

# Words that say what kind of task an agent does, not which entity it's about. Filler cleaning
# ignores them. Every word here appeared in at least 8 of the 548 v1 names (2026-10-26), plus "mail".
TASK_WORDS = frozenset(
    {
        "email", "mail", "search", "find", "reminder", "receipt", "invoice", "lookup", "order", "renewal",
        "appointment", "confirmation", "contact", "check", "calendar", "status", "invite", "quote",
        "refund", "message", "billing",
    }
)


# ---------------------------------------------------------------------------
# Timestamps


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, TS_FORMAT)


def format_ts(value: datetime) -> str:
    return value.strftime(TS_FORMAT)


def add_seconds(timestamp: str, seconds: float) -> str:
    return format_ts(parse_ts(timestamp) + timedelta(seconds=seconds))


def days_before(timestamp: str, days: float) -> str:
    """Timestamp ``days`` days before ``timestamp``, rounded to the second."""
    shifted = parse_ts(timestamp) - timedelta(days=days)
    return format_ts(shifted.replace(microsecond=0))


def age_days(timestamp: str, now: str) -> float:
    """Days from ``timestamp`` to ``now`` (positive when ``timestamp`` is earlier)."""
    return (parse_ts(now) - parse_ts(timestamp)).total_seconds() / 86400.0


# ---------------------------------------------------------------------------
# Hashing and seeds


def sha256_hex(data: bytes | str) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_hex(path.read_bytes())


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _field(value: Any) -> str:
    return "-" if value is None else str(value)


def call_seed(
    purpose: str,
    case_id: Any = None,
    n: Any = None,
    mode: Any = None,
    rep: Any = None,
    turn: Any = None,
    iteration: Any = None,
) -> int:
    """Seed for one call position (design: Model calls). ``None`` fields render as ``-``."""
    key = "|".join(_field(v) for v in (purpose, case_id, n, mode, rep, turn, iteration))
    return int(sha256_hex(key)[:8], 16)


def seeded_rng(key: str, digits: int = 16) -> random.Random:
    return random.Random(int(sha256_hex(key)[:digits], 16))


def seeded_uniform(key: str, low: float, high: float) -> float:
    return seeded_rng(key).uniform(low, high)


def tree_hash(paths: Iterable[Path], root: Path) -> str:
    """sha256 over sorted ``path\\0sha256(file)`` lines (design: Recorded with every run)."""
    lines = []
    for path in sorted(paths, key=lambda p: p.relative_to(root).as_posix()):
        lines.append(f"{path.relative_to(root).as_posix()}\0{sha256_file(path)}\n")
    return sha256_hex("".join(lines))


# ---------------------------------------------------------------------------
# JSON lines


def read_jsonl(path: Path) -> list[dict]:
    rows = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def write_jsonl(path: Path, rows: Iterable[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")


# ---------------------------------------------------------------------------
# Agent-name similarity


def slug(name: str) -> str:
    """Production log-file slug (``_slugify`` in ``log_store.py``)."""
    return _slugify(name)


def slug_tokens(name: str) -> set[str]:
    return {tok for tok in slug(name).split("-") if tok and tok not in STOPWORDS}


def slug_ratio(a: str, b: str) -> float:
    return SequenceMatcher(None, slug(a), slug(b)).ratio()


def token_jaccard(a: str, b: str) -> float:
    ta, tb = slug_tokens(a), slug_tokens(b)
    if not ta and not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_near_duplicate(new_name: str, existing_name: str) -> bool:
    """Tag rule for ``near_duplicate`` (ratio >= 0.75, Jaccard >= 0.5, or equal slugs)."""
    if slug(new_name) == slug(existing_name):
        return True
    return slug_ratio(new_name, existing_name) >= 0.75 or token_jaccard(new_name, existing_name) >= 0.5


def _is_task_word(token: str) -> bool:
    return token in TASK_WORDS or (token.endswith("s") and token[:-1] in TASK_WORDS)


def name_core(name: str) -> list[str]:
    """Slug tokens without stopwords and task words: the part of a name that names the entity."""
    return [tok for tok in slug(name).split("-") if tok and tok not in STOPWORDS and not _is_task_word(tok)]


def is_filler_conflict(filler_name: str, case_name: str) -> bool:
    """Filler cleaning rule v2: on the name cores, ratio >= 0.6 or at least 2 shared tokens.

    v1 compared whole slugs, so "Figma Invoice Email" and "Zapier Invoice Search" conflicted
    on task words alone. A name whose core is empty never conflicts.
    """
    a, b = name_core(filler_name), name_core(case_name)
    if not a or not b:
        return False
    if SequenceMatcher(None, "-".join(a), "-".join(b)).ratio() >= 0.6:
        return True
    return len(set(a) & set(b)) >= 2


# ---------------------------------------------------------------------------
# Statistics helpers shared by metrics and compare


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def percentile(values: list[float], q: float) -> float | None:
    """Linear-interpolated percentile, ``q`` in [0, 100]."""
    if not values:
        return None
    ordered = sorted(values)
    if len(ordered) == 1:
        return float(ordered[0])
    pos = (len(ordered) - 1) * q / 100.0
    lo = int(pos)
    hi = min(lo + 1, len(ordered) - 1)
    frac = pos - lo
    return ordered[lo] + (ordered[hi] - ordered[lo]) * frac
