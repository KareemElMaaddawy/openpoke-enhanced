"""State, transcript parity, summarization rule, turn updates and agent times."""

from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from server.services.conversation.log import ConversationLog, _default_formatter
from server.services.conversation.summarization.state import LogEntry, SummaryState
from server.services.conversation.summarization.working_memory_log import WorkingMemoryLog

from evals.agent_overload.harness import state as st
from evals.agent_overload.harness.methods.base import Entry
from evals.agent_overload.harness.util import age_days


def tricky_entries() -> list[Entry]:
    return [
        Entry("user_message", "2026-10-20 09:14:00", "can you find my AWS invoice for October? <urgent> & thanks"),
        Entry("poke_reply", "2026-10-20 09:14:05", "on it"),
        Entry(
            "agent_message",
            "2026-10-20 09:15:10",
            '[SUCCESS] AWS Invoice Lookup: Found it: $412.37\n[SUCCESS] Re: "Keith" offsite: Done.',
        ),
        Entry("wait", "2026-10-20 09:15:12", "Message already sent"),
        Entry("poke_reply", "2026-10-20 09:15:15", "Found it: $412.37, due Nov 3.\nSecond line"),
    ]


def make_state(entries=None) -> st.RoutingState:
    agents = {
        "a-1": {"agent_id": "a-1", "thread_id": "t-1", "name": "AWS Invoice Lookup", "work_log": []},
        "a-2": {"agent_id": "a-2", "thread_id": "t-2", "name": 'Re: "Keith" offsite', "work_log": []},
        "a-f": {"agent_id": "a-f", "thread_id": "t-f", "name": "Gym Reminder", "work_log": []},
    }
    times = {
        "a-1": {"last_active": "2026-10-20 09:15:10", "created_at": "2026-10-10 08:00:00"},
        "a-2": {"last_active": "2026-10-20 09:15:10", "created_at": "2026-10-01 08:00:00"},
    }
    return st.initial_state(
        roster_ids=["a-f", "a-1", "a-2"],
        agents=agents,
        agent_times=times,
        filler_age_days={"a-f": 20.5},
        now="2026-10-21 10:00:00",
        history={"summary_text": "", "last_index": -1, "entries": [e.__dict__ for e in (entries or [])]},
    )


class TranscriptParityTest(unittest.TestCase):
    def test_matches_conversation_log_load_transcript(self):
        entries = tricky_entries()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "conversation.log"
            path.write_text(
                "".join(_default_formatter(e.tag, e.timestamp, e.payload) for e in entries), encoding="utf-8"
            )
            log = ConversationLog(path)
            self.assertEqual(st.render_transcript("", entries), log.load_transcript())

    def test_matches_working_memory_render_with_summary(self):
        entries = tricky_entries()
        summary = "Summary generated: 2026-10-20 09:00\n\nTimeline & Commitments:\n- No items. <x> & y"
        with tempfile.TemporaryDirectory() as tmp:
            wml = WorkingMemoryLog(Path(tmp) / "wm.log")
            wml.write_summary_state(
                SummaryState(
                    summary_text=summary,
                    last_index=99,
                    updated_at=None,
                    unsummarized_entries=[
                        LogEntry(tag=e.tag, payload=e.payload, index=100 + i, timestamp=e.timestamp)
                        for i, e in enumerate(entries)
                    ],
                )
            )
            self.assertEqual(st.render_transcript(summary, entries, last_index=99), wml.render_transcript())

    def test_empty_history_renders_empty(self):
        self.assertEqual(st.render_transcript("", []), "")

    def test_batch_payload_format(self):
        self.assertEqual(
            st.format_batch_payload([("A", " found "), ("B", "Done.")]), "[SUCCESS] A: found\n[SUCCESS] B: Done."
        )


class SummarizationRuleTest(unittest.TestCase):
    def _entries(self, count: int) -> list[Entry]:
        return [Entry("user_message", f"2026-10-20 09:{i // 60:02d}:{i % 60:02d}", f"m{i}") for i in range(count)]

    def test_below_threshold_does_nothing(self):
        state = make_state(self._entries(109))
        calls = []

        async def fake(system, messages):
            calls.append(messages)
            return "summary"

        self.assertFalse(asyncio.run(st.maybe_summarize(state, fake)))
        self.assertEqual(calls, [])
        self.assertEqual(len(state.entries), 109)

    def test_summarizes_first_100_at_110(self):
        state = make_state(self._entries(110))
        seen = {}

        async def fake(system, messages):
            seen["system"] = system
            seen["content"] = messages[0]["content"]
            return "  the summary  "

        self.assertTrue(asyncio.run(st.maybe_summarize(state, fake)))
        self.assertIn("[0] user message: m0", seen["content"])
        self.assertIn("[99] user message: m99", seen["content"])
        self.assertNotIn("m100", seen["content"])
        # The production builder keeps the f-string's indentation (dedent sees the interpolated lines).
        self.assertRegex(seen["content"], r"Existing memory summary:\n\s*None\n")
        self.assertEqual(state.summary_text, "the summary")
        self.assertEqual(state.last_index, 99)
        self.assertEqual([e.payload for e in state.entries], [f"m{i}" for i in range(100, 110)])
        self.assertTrue(state.transcript().startswith("<conversation_summary>the summary</conversation_summary>"))

    def test_second_summary_continues_indices_and_includes_previous(self):
        state = make_state(self._entries(110))

        async def first(system, messages):
            return "S1"

        asyncio.run(st.maybe_summarize(state, first))
        for i in range(100):
            state.add_entry("poke_reply", "2026-10-21 10:00:00", f"r{i}")
        seen = {}

        async def second(system, messages):
            seen["content"] = messages[0]["content"]
            return "S2"

        self.assertTrue(asyncio.run(st.maybe_summarize(state, second)))
        self.assertRegex(seen["content"], r"Existing memory summary:\n\s*S1\n")
        self.assertIn("[100] user message: m100", seen["content"])
        self.assertEqual(state.last_index, 199)
        self.assertEqual(len(state.entries), 10)

    def test_empty_summary_leaves_state_unchanged(self):
        state = make_state(self._entries(110))

        async def empty(system, messages):
            return "   "

        self.assertFalse(asyncio.run(st.maybe_summarize(state, empty)))
        self.assertEqual(len(state.entries), 110)
        self.assertEqual(state.last_index, -1)


class TurnUpdateTest(unittest.TestCase):
    def test_carried_update_with_new_and_existing_agents(self):
        state = make_state()
        new_id = st.next_run_agent_id(state)
        st.apply_turn(
            state,
            message_tag="user_message",
            message_text="find the uber eats refund",
            timestamp="2026-10-21 10:00:00",
            effects=[("poke_reply", "checking"), ("wait", "dup")],
            work=[
                st.WorkAssignment("new:Uber Eats Refund", "Uber Eats Refund", "find refund", "Refund posted.", new_id),
                st.WorkAssignment("a-1", "AWS Invoice Lookup", "also check", st.DONE_TEXT),
            ],
            primary_thread="t-9",
            result_reply="Yep, posted.",
        )
        self.assertEqual(new_id, "a-run-1")
        self.assertEqual(state.roster[-1].agent_id, "a-run-1")
        self.assertEqual(state.roster[-1].thread_id, "t-9")
        self.assertEqual(state.roster[-1].created_at, "2026-10-21 10:00:00")
        self.assertEqual(state.by_id("a-1").last_active, "2026-10-21 10:00:00")
        self.assertEqual(state.by_id("a-1").work_log[-1].result, "Done.")
        self.assertIn("t-9", state.agent_context["a-1"])
        tags = [(e.tag, e.timestamp) for e in state.entries]
        self.assertEqual(
            tags,
            [
                ("user_message", "2026-10-21 10:00:00"),
                ("poke_reply", "2026-10-21 10:00:05"),
                ("wait", "2026-10-21 10:00:06"),
                ("agent_message", "2026-10-21 10:01:00"),
                ("poke_reply", "2026-10-21 10:01:05"),
            ],
        )
        self.assertEqual(
            state.entries[3].payload, "[SUCCESS] Uber Eats Refund: Refund posted.\n[SUCCESS] AWS Invoice Lookup: Done."
        )
        self.assertEqual(state.prev_thread(), "t-9")

    def test_new_agent_without_primary_thread_is_orphan(self):
        state = make_state()
        st.apply_turn(
            state,
            message_tag="user_message",
            message_text="hi",
            timestamp="2026-10-21 10:00:00",
            effects=[],
            work=[st.WorkAssignment("new:X", "X", "do", "Done.", st.next_run_agent_id(state))],
            primary_thread=None,
            result_reply=None,
        )
        self.assertEqual(state.roster[-1].thread_id, st.ORPHAN)
        self.assertEqual(state.entries[-1].tag, "agent_message")

    def test_no_work_appends_only_message_and_effects(self):
        state = make_state()
        st.apply_turn(
            state,
            message_tag="agent_message",
            message_text="Important email watcher notification:\nhi",
            timestamp="2026-10-21 10:00:00",
            effects=[("poke_reply", "fyi")],
            work=[],
            primary_thread="t-1",
            result_reply="ignored",
        )
        self.assertEqual([e.tag for e in state.entries], ["agent_message", "poke_reply"])

    def test_clone_is_independent(self):
        state = make_state()
        copy = state.clone()
        copy.add_entry("user_message", "2026-10-21 10:00:00", "x")
        copy.roster[0].name = "changed"
        self.assertEqual(state.entries, [])
        self.assertEqual(state.roster[0].name, "Gym Reminder")


class PrevThreadAndCanonicalTest(unittest.TestCase):
    def test_prev_thread_uses_first_line_and_names_with_colons(self):
        state = make_state(tricky_entries())
        self.assertEqual(state.prev_thread(), "t-1")
        state.add_entry("agent_message", "2026-10-20 10:00:00", '[SUCCESS] Re: "Keith" offsite: sent')
        self.assertEqual(state.prev_thread(), "t-2")

    def test_prev_thread_skips_email_alerts(self):
        state = make_state(tricky_entries())
        state.add_entry("agent_message", "2026-10-20 10:00:00", "Important email watcher notification:\nx")
        self.assertEqual(state.prev_thread(), "t-1")

    def test_prev_thread_none_without_result_lines(self):
        self.assertIsNone(make_state().prev_thread())

    def test_canonical_is_first_mapped_agent(self):
        state = make_state()
        state.add_agent(
            st.AgentRecord("a-run-1", "AWS Invoice", "t-1", "2026-10-21 10:00:00", "2026-10-21 10:00:00", False)
        )
        self.assertEqual(state.canonical_agent("t-1"), "a-1")
        state.add_agent(st.AgentRecord("a-run-2", "Y", "t-new", "2026-10-21 10:00:00", "2026-10-21 10:00:00", False))
        state.add_agent(st.AgentRecord("a-run-3", "Z", "t-new", "2026-10-21 10:00:00", "2026-10-21 10:00:00", False))
        self.assertEqual(state.canonical_agent("t-new"), "a-run-2")
        self.assertEqual(state.canonical_map()["t-new"], "a-run-2")
        self.assertIsNone(state.canonical_agent("t-missing"))


class AgentTimesTest(unittest.TestCase):
    def test_required_times_from_case_and_filler_from_ages(self):
        state = make_state()
        filler = state.by_id("a-f")
        self.assertAlmostEqual(age_days(filler.last_active, "2026-10-21 10:00:00"), 20.5, places=3)
        self.assertLessEqual(filler.created_at, filler.last_active)
        self.assertLessEqual(age_days(filler.created_at, filler.last_active), 30.0)
        self.assertEqual(state.by_id("a-1").last_active, "2026-10-20 09:15:10")
        again = make_state()
        self.assertEqual(again.by_id("a-f").created_at, filler.created_at)  # seeded, deterministic

    def test_missing_times_is_an_error(self):
        with self.assertRaises(KeyError):
            st.initial_state(
                roster_ids=["a-x"],
                agents={"a-x": {"agent_id": "a-x", "thread_id": "t", "name": "X"}},
                agent_times={},
                filler_age_days={},
                now="2026-10-21 10:00:00",
                history={},
            )

    def test_routing_input_hides_threads(self):
        inp = make_state(tricky_entries()).routing_input("hello", "user")
        self.assertEqual([a.agent_id for a in inp.roster], ["a-f", "a-1", "a-2"])
        self.assertFalse(hasattr(inp.roster[0], "thread_id"))
        self.assertEqual(len(inp.entries), 5)


if __name__ == "__main__":
    unittest.main()
