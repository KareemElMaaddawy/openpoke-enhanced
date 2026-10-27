"""Records mode through the real InteractionAgentRuntime, with a fake model and embedder."""

import json
import re
import unittest

from server.agents.interaction_agent import routing as routing_module
from server.agents.interaction_agent.records_prompt import build_records_system_prompt
from server.agents.interaction_agent.routing import RecordsRouting
from server.agents.interaction_agent.runtime import InteractionAgentRuntime
from server.agents.interaction_agent.tools_records import RECORDS_TOOL_SCHEMAS
from server.tests.runtime_helpers import (
    TempServerState,
    assistant_reply,
    make_settings,
    tool_call,
)

NOW = "2026-10-26 10:00:00"


class RecordsRuntimeTestCase(unittest.IsolatedAsyncioTestCase):
    full_roster_max = 25

    def setUp(self) -> None:
        settings = make_settings(routing_mode="records", full_roster_max=self.full_roster_max)
        self.state = TempServerState(settings).start()
        self.addCleanup(self.state.stop)

    def add_record(self, name: str, purpose: str = "", work: str = "") -> str:
        record = self.state.records.create(name, purpose, NOW)
        self.state.roster.add_agent(name)
        if work:
            self.state.records.touch_dispatch(record.agent_id, work, NOW)
        return record.agent_id

    def runtime(self, replies):
        runtime = InteractionAgentRuntime()
        calls = []

        async def fake_llm_call(system_prompt, messages):
            calls.append((system_prompt, json.loads(json.dumps(messages))))
            return replies.pop(0)

        runtime._make_llm_call = fake_llm_call
        return runtime, calls

    @staticmethod
    def active_agents_block(messages) -> str:
        match = re.search(r"<active_agents[^>]*>.*?</active_agents>", messages[0]["content"], re.S)
        return match.group(0)


class FullModeTurnTest(RecordsRuntimeTestCase):
    async def test_full_roster_turn(self) -> None:
        ids = [
            self.add_record("AWS Invoice Lookup", "Finds AWS invoices.", "Find the October invoice"),
            self.add_record("Email Keith", "Emails with Keith about the Q3 report."),
            self.add_record("Flight Booking"),
        ]
        runtime, calls = self.runtime([assistant_reply("On it.")])
        self.assertIsInstance(runtime.routing, RecordsRouting)
        self.assertIs(runtime.tool_schemas, RECORDS_TOOL_SCHEMAS)

        with self.assertLogs("openpoke.server", "INFO") as logs:
            result = await runtime.execute("was the aws invoice paid?")

        self.assertTrue(result.success)
        system_prompt, messages = calls[0]
        self.assertEqual(system_prompt, build_records_system_prompt())
        block = self.active_agents_block(messages)
        self.assertTrue(block.startswith('<active_agents shown="3" total="3">'))
        self.assertEqual(re.findall(r'<agent id="([^"]+)"', block), ids)
        self.assertIn("<purpose>Finds AWS invoices.</purpose>", block)
        self.assertIn("<recent>Find the October invoice</recent>", block)
        self.assertTrue(messages[0]["content"].endswith("<new_user_message>\nwas the aws invoice paid?\n</new_user_message>"))
        self.assertEqual(self.state.embedder.calls, [])
        self.assertIn("Routing candidates: mode=full shown=3/3 full_roster_max=25", "\n".join(logs.output))

    async def test_empty_roster(self) -> None:
        runtime, calls = self.runtime([assistant_reply("Hi!")])
        await runtime.execute("hello")
        self.assertEqual(self.active_agents_block(calls[0][1]), '<active_agents shown="0" total="0">\nNone\n</active_agents>')


class RetrievedModeTurnTest(RecordsRuntimeTestCase):
    full_roster_max = 3

    def setUp(self) -> None:
        super().setUp()
        for i in range(10):
            self.add_record(f"Filler Agent {i}", f"Handles unrelated chore number {i}.")
        self.keith = self.add_record("Email Keith", "Emails with Keith about the Q3 report.")
        self.aws = self.add_record("AWS Invoice Lookup", "Finds AWS invoices.")

    async def test_retrieves_k_and_saves_index(self) -> None:
        runtime, calls = self.runtime([assistant_reply("On it.")])
        with self.assertLogs("openpoke.server", "INFO") as logs:
            await runtime.execute("draft a reply to Keith about the Q3 report")

        block = self.active_agents_block(calls[0][1])
        shown = re.findall(r'<agent id="([^"]+)"', block)
        self.assertTrue(block.startswith('<active_agents shown="8" total="12">'))
        self.assertEqual(len(shown), 8)
        self.assertEqual(shown[0], self.keith)
        self.assertEqual(len(self.state.embedder.calls), 1)
        self.assertEqual(len(self.state.embedder.calls[0]), 1 + 12)   # q_msg + every record (all stale)
        self.assertTrue((self.state.base / "execution_agents" / "embeddings.json").exists())
        self.assertIn("Routing candidates: mode=retrieved shown=8/12 full_roster_max=3 k=8", "\n".join(logs.output))

        runtime, _ = self.runtime([assistant_reply("Ok.")])
        await runtime.execute("thanks")
        self.assertEqual(self.state.embedder.calls[1][:1], ["thanks"])
        self.assertEqual(len(self.state.embedder.calls[1]), 2)   # q_msg + q_ctx; record vectors cached

    async def test_execution_result_pins_agent(self) -> None:
        runtime, calls = self.runtime([assistant_reply("Done.")])
        await runtime.handle_agent_message("[SUCCESS] AWS Invoice Lookup: Invoice is unpaid.")
        shown = re.findall(r'<agent id="([^"]+)"', self.active_agents_block(calls[0][1]))
        self.assertEqual(shown[0], self.aws)
        self.assertEqual(runtime.routing.last_candidate_set.pinned, [self.aws])

    async def test_previous_user_message_is_used_from_conversation_entries(self) -> None:
        self.state.conversation.record_user_message("find the aws invoice")
        self.state.conversation.record_reply("Found it.")
        runtime, _ = self.runtime([assistant_reply("Sure.")])
        await runtime.execute("reply to that")
        self.assertEqual(runtime.routing.last_candidate_set.queries, ["reply to that", "find the aws invoice\nreply to that"])

    async def test_embedding_failure_falls_back_to_lexical(self) -> None:
        self.state.embedder.fail = True
        before = routing_module.EMBEDDING_FAILURES
        runtime, calls = self.runtime([assistant_reply("On it.")])
        with self.assertLogs("openpoke.server", "INFO") as logs:
            result = await runtime.execute("draft a reply to Keith")
        self.assertTrue(result.success)
        self.assertEqual(runtime.routing.last_candidate_set.mode, "retrieved_lexical_fallback")
        self.assertEqual(routing_module.EMBEDDING_FAILURES, before + 1)
        shown = re.findall(r'<agent id="([^"]+)"', self.active_agents_block(calls[0][1]))
        self.assertEqual((len(shown), shown[0]), (8, self.keith))
        output = "\n".join(logs.output)
        self.assertIn("Embedding failed, using lexical retrieval for this turn", output)
        self.assertIn("mode=retrieved_lexical_fallback", output)


class ToolLoopTest(RecordsRuntimeTestCase):
    async def test_create_then_reuse_by_id(self) -> None:
        existing = self.add_record("Email Keith", "Emails with Keith.")
        replies = [
            assistant_reply(tool_calls=[
                tool_call("c1", "create_agent", {"name": "Flight Booking", "purpose": "Books the user's flights to NYC.", "instructions": "Find SFO-JFK flights"}),
                tool_call("c2", "send_message_to_agent", {"agent_id": existing, "instructions": "Reply to Keith"}),
                tool_call("c3", "send_message_to_agent", {"agent_id": "ag_00000000", "instructions": "Lost"}),
            ]),
            assistant_reply("Working on both."),
        ]
        runtime, calls = self.runtime(replies)
        result = await runtime.execute("book flights and reply to keith")

        self.assertTrue(result.success)
        self.assertEqual(result.response, "Working on both.")
        created = self.state.records.find_by_name_or_slug("Flight Booking")
        self.assertEqual(created.purpose, "Books the user's flights to NYC.")
        self.assertEqual(json.loads((self.state.base / "execution_agents" / "roster.json").read_text()), ["Email Keith", "Flight Booking"])
        self.assertEqual(
            [c.args for c in self.state.dispatch.call_args_list],
            [(created.agent_id, "Flight Booking", "Find SFO-JFK flights"), (existing, "Email Keith", "Reply to Keith")],
        )
        tool_messages = [m for m in calls[1][1] if m["role"] == "tool"]
        results = [json.loads(m["content"]) for m in tool_messages]
        self.assertEqual([r["status"] for r in results], ["success", "success", "error"])
        self.assertIn("Unknown agent_id 'ag_00000000'", results[2]["error"]["error"])
        self.assertEqual(len(self.state.records.all()), 2)


if __name__ == "__main__":
    unittest.main()
