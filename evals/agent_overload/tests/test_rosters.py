"""Roster construction: deterministic, nested filler, anchor bucket, required agents present."""

from __future__ import annotations

import unittest

from evals.agent_overload.harness import rosters

SIZES = [10, 25, 50, 100, 125, 200]
FILLER = [f"a-f-{i:03d}" for i in range(200)]
THREADS = {
    "t-1": {"near_distractor_of": "t-2"},
    "t-2": {"near_distractor_of": "t-1"},
    "t-3": {},
    "t-4": {},
}
AGENT_OF_THREAD = {"t-1": "a-1", "t-2": "a-2", "t-3": "a-3"}


def case(kind="REUSE", position="middle_third", required=("a-1", "a-2", "a-3"), **label):
    lab = {"kind": kind, **label}
    if kind in ("REUSE", "REUSE_ANY") and "threads" not in lab:
        lab["threads"] = ["t-1"]
    return {"case_id": "s-test-0001", "required_agents": list(required), "target_position": position, "label": lab}


class RosterTest(unittest.TestCase):
    def test_deterministic(self):
        c = case()
        first = rosters.roster_for_case(c, 50, FILLER, AGENT_OF_THREAD, THREADS)
        second = rosters.roster_for_case(c, 50, FILLER, AGENT_OF_THREAD, THREADS)
        self.assertEqual(first, second)
        other = dict(c, case_id="s-test-0002")
        self.assertNotEqual(first, rosters.roster_for_case(other, 50, FILLER, AGENT_OF_THREAD, THREADS))

    def test_size_required_and_nested_filler(self):
        c = case()
        previous_filler: set[str] = set()
        for n in SIZES:
            roster = rosters.roster_for_case(c, n, FILLER, AGENT_OF_THREAD, THREADS)
            self.assertEqual(len(roster), n)
            self.assertEqual(len(set(roster)), n)
            self.assertTrue(set(c["required_agents"]) <= set(roster))
            filler = set(roster) - set(c["required_agents"])
            self.assertEqual(filler, set(FILLER[: n - 3]))
            self.assertTrue(previous_filler <= filler)
            previous_filler = filler

    def test_anchor_lands_in_its_bucket_at_every_n(self):
        for bucket in rosters.BUCKETS:
            for case_number in range(20):
                c = dict(case(position=bucket), case_id=f"s-test-{case_number:04d}")
                for n in SIZES:
                    roster = rosters.roster_for_case(c, n, FILLER, AGENT_OF_THREAD, THREADS)
                    self.assertEqual(rosters.bucket_of(roster.index("a-1"), n), bucket, (bucket, n))

    def test_anchor_rules(self):
        self.assertEqual(rosters.position_anchor(case(), AGENT_OF_THREAD, THREADS), "a-1")
        any_case = case(kind="REUSE_ANY", threads=["t-3", "t-1"])
        self.assertEqual(rosters.position_anchor(any_case, AGENT_OF_THREAD, THREADS), "a-3")
        create_distractor = case(kind="CREATE", new_thread="t-1", required=("a-2", "a-3"))
        self.assertEqual(rosters.position_anchor(create_distractor, AGENT_OF_THREAD, THREADS), "a-2")
        create_plain = case(kind="CREATE", new_thread="t-4", position=None)
        self.assertIsNone(rosters.position_anchor(create_plain, AGENT_OF_THREAD, THREADS))
        no_delegation = case(kind="NO_DELEGATION", position=None)
        self.assertIsNone(rosters.position_anchor(no_delegation, AGENT_OF_THREAD, THREADS))
        sequence = {"case_id": "q-test-001", "required_agents": ["a-1"]}
        self.assertIsNone(rosters.position_anchor(sequence, AGENT_OF_THREAD, THREADS))

    def test_unanchored_case_is_shuffled_deterministically(self):
        c = case(kind="NO_DELEGATION", position=None)
        roster = rosters.roster_for_case(c, 10, FILLER, AGENT_OF_THREAD, THREADS)
        self.assertEqual(len(roster), 10)
        self.assertEqual(roster, rosters.roster_for_case(c, 10, FILLER, AGENT_OF_THREAD, THREADS))

    def test_errors(self):
        with self.assertRaises(ValueError):
            rosters.build_roster("c", ["a"] * 2, 10, FILLER)
        with self.assertRaises(ValueError):
            rosters.build_roster("c", [f"r{i}" for i in range(11)], 10, FILLER)
        with self.assertRaises(ValueError):
            rosters.build_roster("c", ["a-1"], 10, FILLER, anchor="a-9", target_position="first_third")
        with self.assertRaises(ValueError):
            rosters.build_roster("c", ["a-1"], 300, FILLER)
        with self.assertRaises(ValueError):
            rosters.roster_for_case(case(position=None), 10, FILLER, AGENT_OF_THREAD, THREADS)

    def test_buckets_partition_roster(self):
        for n in SIZES:
            covered = []
            for bucket in rosters.BUCKETS:
                lo, hi = rosters.bucket_range(bucket, n)
                covered.extend(range(lo, hi))
            self.assertEqual(covered, list(range(n)))


if __name__ == "__main__":
    unittest.main()
