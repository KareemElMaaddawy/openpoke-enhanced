"""Scorer: one test per outcome label and per tag, plus the edge cases the design lists."""

from __future__ import annotations

import unittest

from evals.agent_overload.harness import scoring
from evals.agent_overload.harness.methods.base import Delegation, Entry, RoutingOutput

ROSTER = [
    ("a-1", "AWS Invoice Lookup"),
    ("a-2", "Uber Rides Receipts"),
    ("a-3", "Uber Eats Refund"),
    ("a-dup", "AWS Invoice Lookup 2"),  # a later duplicate of thread t-1
]
AGENT_THREAD = {"a-1": "t-1", "a-2": "t-2", "a-3": "t-3", "a-dup": "t-1"}
CANONICAL = {"t-1": "a-1", "t-2": "a-2", "t-3": "a-3"}


def ctx(label, prev_thread=None, agent_context=None, roster=ROSTER, agent_thread=AGENT_THREAD, canonical=CANONICAL):
    return scoring.ScoringContext(
        label=label,
        roster=list(roster),
        agent_thread=dict(agent_thread),
        canonical=dict(canonical),
        prev_thread=prev_thread,
        agent_context=agent_context,
    )


def out(*keys, replies=(), invalid=(), excluded=None, loop_limit=False):
    delegations = []
    for order, key in enumerate(keys):
        name = key[4:] if key.startswith("new:") else dict(ROSTER)[key]
        delegations.append(Delegation(agent_key=key, agent_name=name, instructions="do it", iteration=0, order=order))
    effects = [Entry("poke_reply", "2026-10-21 10:00:05", r) for r in replies]
    diagnostics = {"excluded": list(excluded)} if excluded is not None else {}
    return RoutingOutput(
        delegations=delegations,
        history_effects=effects,
        invalid_calls=list(invalid),
        llm_calls=[],
        diagnostics=diagnostics,
        loop_limit_hit=loop_limit,
    )


REUSE_T1 = {"kind": "REUSE", "threads": ["t-1"]}
REUSE_ANY = {"kind": "REUSE_ANY", "threads": ["t-2", "t-3"]}
CREATE = {"kind": "CREATE", "new_thread": "t-9"}
NO_DELEGATION = {"kind": "NO_DELEGATION"}


class OutcomeTest(unittest.TestCase):
    def check(self, label, output, primary, correct, lenient=None, **ctx_kwargs):
        score = scoring.score_turn(ctx(label, **ctx_kwargs), output)
        self.assertEqual(score.primary_outcome, primary)
        self.assertEqual(score.turn_correct, correct)
        if lenient is not None:
            self.assertEqual(score.turn_correct_lenient, lenient)
        return score

    def test_correct_reuse(self):
        score = self.check(REUSE_T1, out("a-1"), "correct_reuse", True, True)
        self.assertEqual(score.primary_key, "a-1")
        self.assertEqual(score.primary_agent_thread, "t-1")

    def test_duplicate_reuse_is_lenient_only(self):
        self.check(REUSE_T1, out("a-dup"), "duplicate_reuse", False, True)

    def test_misroute(self):
        self.check(REUSE_T1, out("a-2"), "misroute", False, False)

    def test_false_spawn(self):
        self.check(REUSE_T1, out("new:Gym Reminder"), "false_spawn", False)

    def test_reuse_any_accepts_any_listed_thread(self):
        self.check(REUSE_ANY, out("a-3"), "correct_reuse", True)
        self.check(REUSE_ANY, out("a-1"), "misroute", False)

    def test_false_reuse(self):
        self.check(CREATE, out("a-1"), "false_reuse", False)

    def test_correct_create(self):
        self.check(CREATE, out("new:Denver Flights"), "correct_create", True)

    def test_correct_no_delegation(self):
        score = self.check(NO_DELEGATION, out(replies=["sure"]), "correct_no_delegation", True)
        self.assertEqual([o["outcome"] for o in score.outcomes], ["correct_no_delegation"])

    def test_extra_delegation_on_no_delegation_label(self):
        score = self.check(NO_DELEGATION, out("a-1", "new:X"), "extra_delegation", False)
        self.assertEqual([o["outcome"] for o in score.outcomes], ["extra_delegation", "extra_delegation"])

    def test_missed_delegation(self):
        self.check(REUSE_T1, out(replies=["done!"]), "missed_delegation", False)

    def test_extra_delegation_beside_correct_primary(self):
        score = self.check(REUSE_T1, out("a-1", "a-2"), "correct_reuse", False, False)
        self.assertEqual([o["outcome"] for o in score.outcomes], ["correct_reuse", "extra_delegation"])

    def test_primary_is_first_correct_not_first(self):
        score = self.check(REUSE_T1, out("a-2", "a-1"), "correct_reuse", False)
        self.assertEqual(score.primary_key, "a-1")
        self.assertEqual(
            [(o["agent_key"], o["outcome"]) for o in score.outcomes],
            [("a-2", "extra_delegation"), ("a-1", "correct_reuse")],
        )

    def test_primary_is_first_when_none_correct(self):
        score = self.check(REUSE_T1, out("a-2", "new:X"), "misroute", False)
        self.assertEqual(score.primary_key, "a-2")

    def test_duplicate_name_same_turn_is_collapsed(self):
        score = self.check(CREATE, out("new:Denver Flights", "new:Denver Flights"), "correct_create", True)
        self.assertEqual(len(score.distinct), 1)
        self.assertEqual(score.outcomes[0]["repeat_calls"], 1)

    def test_invalid_call_does_not_make_turn_wrong(self):
        invalid = [{"tool": "send_message_to_agent", "raw_arguments": "{", "error": "invalid json"}]
        score = self.check(REUSE_T1, out("a-1", invalid=invalid), "correct_reuse", True)
        self.assertEqual(score.outcomes[0]["outcome"], "invalid_call")

    def test_only_invalid_calls_is_missed_delegation(self):
        invalid = [
            {"tool": "send_message_to_agent", "raw_arguments": '{"agent_name": ""}', "error": "empty agent_name"},
            {"tool": "send_message_to_agent", "raw_arguments": '{"name": "x"}', "error": "Missing required arguments"},
        ]
        score = self.check(REUSE_T1, out(invalid=invalid), "missed_delegation", False)
        self.assertEqual([o["outcome"] for o in score.outcomes], ["invalid_call", "invalid_call", "missed_delegation"])

    def test_loop_limit_is_scored_and_flagged(self):
        score = self.check(REUSE_T1, out("a-1", loop_limit=True), "correct_reuse", True)
        self.assertEqual(score.status, scoring.STATUS_LOOP_LIMIT)

    def test_api_error_is_left_out(self):
        score = scoring.score_turn(ctx(REUSE_T1), None, status=scoring.STATUS_API_ERROR)
        self.assertEqual(score.status, scoring.STATUS_API_ERROR)
        self.assertIsNone(score.turn_correct)
        self.assertEqual(score.outcomes, [])


class TagTest(unittest.TestCase):
    def tags(self, label, output, **ctx_kwargs):
        return scoring.score_turn(ctx(label, **ctx_kwargs), output).tags

    def test_near_duplicate(self):
        self.assertIn("near_duplicate", self.tags(REUSE_T1, out("new:AWS Invoice Lookup Oct")))
        self.assertIn("near_duplicate", self.tags(REUSE_T1, out("new:aws invoice")))  # token Jaccard
        self.assertNotIn("near_duplicate", self.tags(REUSE_T1, out("new:Gym Reminder")))

    def test_slug_collision_against_roster(self):
        self.assertIn("slug_collision", self.tags(REUSE_T1, out("new:aws-invoice-lookup")))
        self.assertNotIn("slug_collision", self.tags(REUSE_T1, out("new:AWS Invoice")))

    def test_slug_collision_within_turn(self):
        score = scoring.score_turn(ctx(CREATE), out("new:Denver Flights", "new:denver flights"))
        self.assertEqual([o["tags"] for o in score.outcomes], [["slug_collision"], ["slug_collision"]])

    def test_recency_on_misroute_and_false_reuse(self):
        self.assertIn("recency", self.tags(REUSE_T1, out("a-2"), prev_thread="t-2"))
        self.assertNotIn("recency", self.tags(REUSE_T1, out("a-2"), prev_thread="t-3"))
        self.assertIn("recency", self.tags(CREATE, out("a-3"), prev_thread="t-3"))

    def test_recency_eligibility(self):
        self.assertTrue(scoring.score_turn(ctx(REUSE_T1, prev_thread="t-2"), out("a-1")).recency_eligible)
        self.assertFalse(scoring.score_turn(ctx(REUSE_T1, prev_thread="t-1"), out("a-1")).recency_eligible)
        self.assertFalse(scoring.score_turn(ctx(REUSE_T1), out("a-1")).recency_eligible)
        self.assertFalse(scoring.score_turn(ctx(NO_DELEGATION, prev_thread="t-2"), out()).recency_eligible)

    def test_context_reuse_only_with_agent_context(self):
        context = {"a-2": {"t-2", "t-1"}}
        self.assertIn("context_reuse", self.tags(REUSE_T1, out("a-2"), agent_context=context))
        self.assertNotIn("context_reuse", self.tags(REUSE_T1, out("a-2")))
        self.assertNotIn("context_reuse", self.tags(REUSE_T1, out("a-2"), agent_context={"a-2": {"t-2"}}))

    def test_reply_is_question(self):
        self.assertIn("reply_is_question", self.tags(REUSE_T1, out(replies=["ok", "which invoice? "])))
        self.assertNotIn("reply_is_question", self.tags(REUSE_T1, out(replies=["which one?", "on it"])))

    def test_target_excluded(self):
        self.assertIn("target_excluded", self.tags(REUSE_T1, out("new:X", excluded=["a-1"])))
        self.assertIn("target_excluded", self.tags(REUSE_T1, out("a-2", excluded=["a-1"])))
        self.assertIn("target_excluded", self.tags(REUSE_T1, out(excluded=["a-1"])))
        self.assertNotIn("target_excluded", self.tags(REUSE_T1, out("new:X", excluded=["a-2"])))
        self.assertNotIn("target_excluded", self.tags(REUSE_ANY, out("new:X", excluded=["a-2"])))
        self.assertIn("target_excluded", self.tags(REUSE_ANY, out("new:X", excluded=["a-2", "a-3"])))

    def test_tags_never_change_outcomes(self):
        score = scoring.score_turn(ctx(REUSE_T1, prev_thread="t-2"), out("a-2", excluded=["a-1"]))
        self.assertEqual(score.primary_outcome, "misroute")
        self.assertEqual(score.tags, ["recency", "target_excluded"])


if __name__ == "__main__":
    unittest.main()
