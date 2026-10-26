"""Deterministic plans for single-turn cases and sequences (no model calls).

Code decides everything a quota depends on (label, query style, message subtype,
history type, target position, old-thread cases, which threads appear where, the
case's timestamp and agent ages); the drafter only writes the text. That makes the
quotas exact and keeps the label independent of the drafter's choices, which the
second labeler then checks.
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from typing import Optional

from ..harness.rosters import BUCKETS
from ..harness.util import format_ts, sha256_hex

SEED = 20261025

# (label kind, query style, test count, dev count) — design: Quotas for single-turn templates.
QUOTA_CELLS = [
    ("REUSE", "explicit", 18, 9),
    ("REUSE", "paraphrased", 18, 9),
    ("REUSE", "implicit_follow_up", 18, 9),
    ("REUSE", "near_distractor", 18, 9),
    ("REUSE_ANY", "any", 10, 5),
    ("CREATE", "plain", 14, 7),
    ("CREATE", "near_distractor", 12, 6),
    ("NO_DELEGATION", "any", 12, 6),
]
# Agent-message allocation (decided 2026-10-25): {split: {(kind, style): {subtype: count}}}.
AGENT_MESSAGES = {
    "test": {
        ("NO_DELEGATION", "any"): {"execution_result": 5, "email_alert": 4},
        ("REUSE", "explicit"): {"execution_result": 3},
        ("REUSE", "paraphrased"): {"email_alert": 2},
        ("REUSE", "near_distractor"): {"email_alert": 2},
    },
    "dev": {
        ("NO_DELEGATION", "any"): {"execution_result": 3, "email_alert": 2},
        ("REUSE", "explicit"): {"execution_result": 1},
        ("REUSE", "paraphrased"): {"email_alert": 1},
        ("REUSE", "near_distractor"): {"email_alert": 1},
    },
}
OLD_THREAD_CASES = {"test": {"explicit": 6, "near_distractor": 5}, "dev": {"explicit": 3, "near_distractor": 3}}
SUMMARIZED_SHARE = 0.30
SEQUENCE_COUNTS = {"test": 8, "dev": 4}
MAX_REQUIRED_SINGLE = 6
MAX_REQUIRED_SEQUENCE = 8


def rng_for(key: str) -> random.Random:
    return random.Random(int(sha256_hex(f"{SEED}|{key}")[:16], 16))


def filler_like_age(rng: random.Random) -> float:
    """Same mixture as filler ages: 30% 0-3 days, 30% 4-14, 40% 15-60."""
    r = rng.random()
    if r < 0.3:
        return round(rng.uniform(0.0, 3.0), 2)
    if r < 0.6:
        return round(rng.uniform(4.0, 14.0), 2)
    return round(rng.uniform(15.0, 60.0), 2)


def random_now(rng: random.Random, first_day: str = "2026-10-06", last_day: str = "2026-10-24") -> str:
    start = datetime.strptime(first_day, "%Y-%m-%d")
    days = (datetime.strptime(last_day, "%Y-%m-%d") - start).days
    moment = start + timedelta(days=rng.randint(0, days), hours=rng.randint(9, 20), minutes=rng.randint(0, 59))
    return format_ts(moment)


def largest_remainder(counts: list[int], share: float, total: int) -> list[int]:
    raw = [c * share for c in counts]
    base = [int(x) for x in raw]
    order = sorted(range(len(counts)), key=lambda i: (-(raw[i] - base[i]), i))
    for i in order[: total - sum(base)]:
        base[i] += 1
    return base


# ---------------------------------------------------------------------------
# Pools


@dataclass
class Pools:
    split: str
    threads: dict[str, dict]
    agent_of_thread: dict[str, str]
    reserved: set[str] = field(default_factory=set)

    def seeded_case_threads(self) -> list[str]:
        return sorted(
            t
            for t, row in self.threads.items()
            if row["role"] == "case" and t in self.agent_of_thread and t not in self.reserved
        )

    def pair_threads(self) -> list[str]:
        out = []
        for t in self.seeded_case_threads():
            partner = self.threads[t].get("near_distractor_of")
            if partner and partner in self.agent_of_thread and partner not in self.reserved:
                out.append(t)
        return out

    def create_threads(self) -> list[str]:
        return sorted(t for t, row in self.threads.items() if row["role"] == "case" and t not in self.reserved)

    def partner(self, thread_id: str) -> Optional[str]:
        return self.threads[thread_id].get("near_distractor_of")


class Picker:
    """Least-used-first selection with a seeded tie-break, so threads spread evenly over cases."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.usage: Counter = Counter()

    def pick(self, pool: list[str], exclude: set[str]) -> str:
        candidates = [t for t in pool if t not in exclude]
        if not candidates:
            raise ValueError("thread pool exhausted")
        low = min(self.usage[t] for t in candidates)
        best = sorted(t for t in candidates if self.usage[t] == low)
        choice = self.rng.choice(best)
        self.usage[choice] += 1
        return choice


# ---------------------------------------------------------------------------
# Sequences


@dataclass
class SequencePlan:
    case_id: str
    split: str
    seeded: dict[str, str]  # role (A, B, C, P1, P2) -> thread
    created: dict[str, str]  # N1, N2 -> thread
    history_threads: list[str]  # seeded threads that appear in the initial history
    aged: dict[str, float]  # thread -> age in days for seeded threads absent from the history
    start: str
    turns: list[dict]

    def to_dict(self) -> dict:
        return asdict(self)


# Turn templates: (label kind, roles, style, subtype). Two orders, alternated across sequences.
_TEMPLATES = [
    [
        ("REUSE", ["A"], "explicit", "user"),
        ("CREATE", ["N1"], "plain", "user"),
        ("REUSE", ["N1"], "implicit_follow_up", "user"),
        ("NO_DELEGATION", ["B"], "any", "email_alert"),
        ("REUSE", ["B"], "paraphrased", "user"),
        ("REUSE", ["P2"], "near_distractor", "user"),
        ("CREATE", ["N2"], "plain", "user"),
        ("REUSE", ["A"], "paraphrased", "user"),
        ("REUSE_ANY", ["B", "A"], "any", "user"),
        ("NO_DELEGATION", [], "any", "user"),
        ("REUSE", ["N2"], "explicit", "user"),
        ("EXTRA", ["C"], "explicit", "user"),
    ],
    [
        ("REUSE", ["B"], "paraphrased", "user"),
        ("REUSE", ["P2"], "near_distractor", "user"),
        ("CREATE", ["N1"], "plain", "user"),
        ("REUSE", ["C"], "explicit", "user"),  # the user asks C's agent to act when a reply arrives
        ("REUSE", ["N1"], "explicit", "user"),
        ("NO_DELEGATION", [], "any", "user"),
        ("CREATE", ["N2"], "plain", "user"),
        ("REUSE", ["N2"], "implicit_follow_up", "user"),
        ("REUSE", ["C"], "explicit", "email_alert"),  # that reply arrives
        ("REUSE_ANY", ["C", "N1"], "any", "user"),
        ("NO_DELEGATION", ["A"], "any", "email_alert"),
        ("EXTRA", ["A"], "explicit", "user"),
    ],
]


def sequence_plans(split: str, threads: dict[str, dict], agent_of_thread: dict[str, str]) -> list[SequencePlan]:
    """Plans for the split's sequences. Depends only on threads and which threads have agents."""
    pools = Pools(split, threads, agent_of_thread)
    rng = rng_for(f"{split}|sequences")
    picker = Picker(rng)
    plans = []
    used: set[str] = set()
    for i in range(SEQUENCE_COUNTS[split]):
        case_id = f"q-{split}-{i + 1:03d}"
        p1 = picker.pick(pools.pair_threads(), used)
        p2 = pools.partner(p1)
        taken = used | {p1, p2}
        a = picker.pick(pools.seeded_case_threads(), taken | _partners(pools, taken))
        b = picker.pick(pools.seeded_case_threads(), taken | {a} | _partners(pools, taken | {a}))
        c = picker.pick(pools.seeded_case_threads(), taken | {a, b} | _partners(pools, taken | {a, b}))
        n1 = picker.pick(pools.seeded_case_threads(), taken | {a, b, c} | _partners(pools, taken | {a, b, c}))
        n2 = picker.pick(pools.seeded_case_threads(), taken | {a, b, c, n1} | _partners(pools, taken | {a, b, c, n1}))
        # Created threads belong to this sequence only; seeded ones may recur in other cases.
        used |= {n1, n2}
        pools.reserved |= {n1, n2}
        seeded = {"A": a, "B": b, "C": c, "P1": p1, "P2": p2}
        created = {"N1": n1, "N2": n2}
        roles = {**seeded, **created}
        start = random_now(rng, "2026-10-06", "2026-10-18")
        template = _TEMPLATES[i % 2]
        extra_kind = ("REUSE", "NO_DELEGATION")[(i // 2) % 2]
        turns = []
        moment = datetime.strptime(start, "%Y-%m-%d %H:%M:%S")
        for index, (kind, role_list, style, subtype) in enumerate(template, start=1):
            if kind == "EXTRA":
                kind = extra_kind
                style = style if kind == "REUSE" else "any"
            if index > 1:
                moment = _next_turn_time(moment, rng)
            turn_threads = [roles[r] for r in role_list]
            if kind == "CREATE":
                label = {"kind": "CREATE", "new_thread": turn_threads[0]}
                primary = turn_threads[0]
            elif kind == "REUSE":
                label = {"kind": "REUSE", "threads": turn_threads[:1]}
                primary = turn_threads[0]
            elif kind == "REUSE_ANY":
                label = {"kind": "REUSE_ANY", "threads": turn_threads}
                primary = turn_threads[0]
            else:
                label = {"kind": "NO_DELEGATION"}
                primary = turn_threads[0] if turn_threads else None
            turns.append(
                {
                    "turn": index,
                    "timestamp": format_ts(moment),
                    "label": label,
                    "style": style,
                    "subtype": subtype,
                    "primary_thread": primary,
                    "roles": role_list,
                }
            )
        plans.append(
            SequencePlan(
                case_id=case_id,
                split=split,
                seeded=seeded,
                created=created,
                history_threads=[a, b, c, p1],
                aged={p2: round(rng.uniform(4.0, 14.0), 2)},
                start=start,
                turns=turns,
            )
        )
    return plans


def _partners(pools: Pools, chosen: set[str]) -> set[str]:
    return {p for t in chosen if (p := pools.partner(t))}


def _next_turn_time(moment: datetime, rng: random.Random) -> datetime:
    """20 minutes to 6 hours later, kept between 08:00 and 22:00."""
    nxt = moment + timedelta(minutes=rng.randint(20, 360))
    if nxt.hour >= 22 or nxt.hour < 8:
        nxt = (nxt + timedelta(days=1)).replace(hour=8, minute=rng.randint(0, 59))
    return nxt


def reserved_threads(split: str, threads: dict[str, dict], agent_of_thread: dict[str, str]) -> set[str]:
    """Threads that sequences create; they start without an agent and aren't used elsewhere."""
    return {t for plan in sequence_plans(split, threads, agent_of_thread) for t in plan.created.values()}


# ---------------------------------------------------------------------------
# Single-turn cases


@dataclass
class CasePlan:
    case_id: str
    split: str
    kind: str
    style: str
    subtype: str
    history_type: str
    target_position: Optional[str]
    old: bool
    targets: list[str]
    distractor: Optional[str]
    new_thread: Optional[str]
    history_threads: list[str]  # must each appear as a delegated exchange in the tail
    last_thread: Optional[str]  # must be the last delegated exchange
    not_last: Optional[str]  # must not be the last delegated exchange
    forbidden_threads: list[str]  # must not appear in the tail or message
    message_thread: Optional[str]  # execution_result: the agent that sends the result
    background_threads: list[str]  # summarized cases: appear only in the assembled history
    aged_threads: dict[str, float]  # thread -> age in days, for required threads absent from the history
    now: str

    def required_threads(self) -> list[str]:
        seen: list[str] = []
        for t in self.targets + ([self.distractor] if self.distractor else []) + self.history_threads + self.background_threads:
            if t not in seen:
                seen.append(t)
        return seen

    def label(self) -> dict:
        if self.kind in ("REUSE", "REUSE_ANY"):
            return {"kind": self.kind, "threads": list(self.targets)}
        if self.kind == "CREATE":
            return {"kind": "CREATE", "new_thread": self.new_thread}
        return {"kind": "NO_DELEGATION"}

    def to_dict(self) -> dict:
        return asdict(self)


def _slots(split: str) -> list[dict]:
    """One slot per case with label, style, subtype, history type, position and old flag fixed."""
    index = 0 if split == "test" else 1
    counts = [cell[2 + index] for cell in QUOTA_CELLS]
    total = sum(counts)
    summarized = largest_remainder(counts, SUMMARIZED_SHARE, round(total * SUMMARIZED_SHARE))
    rng = rng_for(f"{split}|slots")
    slots: list[dict] = []
    for (kind, style, *_), count, n_summarized in zip(QUOTA_CELLS, counts, summarized):
        subtypes = []
        for subtype, n in AGENT_MESSAGES[split].get((kind, style), {}).items():
            subtypes += [subtype] * n
        subtypes += ["user"] * (count - len(subtypes))
        old_count = OLD_THREAD_CASES[split].get(style, 0) if kind == "REUSE" else 0
        # Old-thread cases are user messages only (an agent message would put the target in view).
        old_flags = []
        users_seen = 0
        for subtype in subtypes:
            old = subtype == "user" and users_seen < old_count
            users_seen += subtype == "user"
            old_flags.append(old)
        history = ["summarized"] * n_summarized + ["short"] * (count - n_summarized)
        rng.shuffle(history)
        anchored = kind in ("REUSE", "REUSE_ANY") or (kind == "CREATE" and style == "near_distractor")
        offset = rng.randrange(3)
        for i in range(count):
            slots.append(
                {
                    "kind": kind,
                    "style": style,
                    "subtype": subtypes[i],
                    "old": old_flags[i],
                    "history_type": history[i],
                    "target_position": BUCKETS[(i + offset) % 3] if anchored else None,
                }
            )
    return slots


def case_plans(split: str, threads: dict[str, dict], agent_of_thread: dict[str, str]) -> list[CasePlan]:
    pools = Pools(split, threads, agent_of_thread, reserved_threads(split, threads, agent_of_thread))
    rng = rng_for(f"{split}|cases")
    picker = Picker(rng)
    seeded = pools.seeded_case_threads()
    pairs = pools.pair_threads()
    non_pair = [t for t in seeded if t not in set(pairs)] or seeded
    plans = []
    for number, slot in enumerate(_slots(split), start=1):
        case_id = f"s-{split}-{number:04d}"
        crng = rng_for(f"{case_id}|plan")
        plan = _compose(case_id, split, slot, pools, picker, seeded, pairs, non_pair, crng)
        plans.append(plan)
    return plans


def _compose(case_id, split, slot, pools: Pools, picker: Picker, seeded, pairs, non_pair, rng) -> CasePlan:
    kind, style, subtype, old = slot["kind"], slot["style"], slot["subtype"], slot["old"]
    targets: list[str] = []
    distractor = None
    new_thread = None
    history: list[str] = []
    last = not_last = None
    forbidden: list[str] = []
    message_thread = None
    aged: dict[str, float] = {}

    def context(exclude: set[str], k: int) -> list[str]:
        out = []
        for _ in range(k):
            t = picker.pick(non_pair, exclude | set(out) | _partners(pools, exclude | set(out)))
            out.append(t)
        return out

    if kind == "REUSE" and style == "near_distractor":
        t = picker.pick(pairs, set())
        d = pools.partner(t)
        targets, distractor = [t], d
        if old:
            aged[t] = round(rng.uniform(15.0, 60.0), 2)
            forbidden = [t]
            history = [d] + context({t, d}, rng.randint(0, 1))
        else:
            # An agent message must follow up visible work on the target, so it keeps the target in view.
            variant = rng.randrange(3) if subtype == "user" else rng.randrange(2)
            if variant == 0:  # target in view, distractor only in the roster
                history = [t] + context({t, d}, rng.randint(0, 1))
                aged[d] = filler_like_age(rng)
            elif variant == 1:  # both in view, distractor more recent (a recency trap)
                history = [t, d]
                last = d
            else:  # distractor in view, target only in the roster under its name
                history = [d] + context({t, d}, rng.randint(0, 1))
                aged[t] = round(rng.uniform(0.5, 14.0), 2)
                forbidden = [t]
        if subtype == "email_alert" and t in history:
            last = None
    elif kind == "REUSE":
        t = picker.pick(non_pair, set())
        targets = [t]
        if old:
            aged[t] = round(rng.uniform(15.0, 60.0), 2)
            forbidden = [t]
            history = context({t}, rng.randint(1, 2))
        elif style == "implicit_follow_up":
            history = context({t}, rng.randint(0, 2)) + [t]
            last = t
        else:
            others = context({t}, rng.randint(1, 2))
            history = [t] + others
            if subtype == "user" and rng.random() < 0.5:
                not_last = t  # a topic switch, so prev_thread differs from the target
        if subtype == "execution_result":
            message_thread = t
    elif kind == "REUSE_ANY":
        t1 = picker.pick(non_pair, set())
        t2 = picker.pick(non_pair, {t1} | _partners(pools, {t1}))
        targets = [t1, t2]
        history = [t1, t2] + context({t1, t2}, rng.randint(0, 1))
    elif kind == "CREATE":
        if style == "near_distractor":
            d = picker.pick(pairs, set())
            n = pools.partner(d)
            distractor, new_thread = d, n
            if rng.random() < 0.5:
                history = [d] + context({d, n}, rng.randint(0, 1))
            else:
                aged[d] = filler_like_age(rng)
                history = context({d, n}, rng.randint(1, 2))
        else:
            n = picker.pick(pools.create_threads(), set())
            new_thread = n
            history = context({n} | _partners(pools, {n}), rng.randint(1, 2))
        forbidden = [new_thread]
    else:  # NO_DELEGATION
        history = context(set(), rng.randint(1, 3))
        if subtype == "execution_result":
            message_thread = history[-1]

    background: list[str] = []
    if slot["history_type"] == "summarized":
        current = set(targets + history + ([distractor] if distractor else []))
        room = MAX_REQUIRED_SINGLE - len(current)
        want = max(0, min(room, 5 - len(set(history))))
        exclude = current | set(forbidden) | ({new_thread} if new_thread else set())
        for _ in range(want):
            exclude_now = exclude | set(background) | _partners(pools, exclude | set(background))
            background.append(picker.pick(non_pair, exclude_now))

    return CasePlan(
        case_id=case_id,
        split=split,
        kind=kind,
        style=style,
        subtype=subtype,
        history_type=slot["history_type"],
        target_position=slot["target_position"],
        old=old,
        targets=targets,
        distractor=distractor,
        new_thread=new_thread,
        history_threads=history,
        last_thread=last,
        not_last=not_last,
        forbidden_threads=forbidden,
        message_thread=message_thread,
        background_threads=background,
        aged_threads=aged,
        now=random_now(rng),
    )
