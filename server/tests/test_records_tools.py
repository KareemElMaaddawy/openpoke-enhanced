"""Records-mode tools: ID routing, create_agent, and the dispatch completion callback."""

import asyncio
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server.agents.execution_agent.runtime import ExecutionResult
from server.agents.interaction_agent import tools, tools_records
from server.agents.interaction_agent.tools_records import (
    RECORDS_TOOL_SCHEMAS,
    ROUTING_COUNTS,
    create_agent,
    handle_records_tool_call,
    send_message_to_agent,
)
from server.services.agents.records import AgentRecordStore
from server.services.execution.log_store import ExecutionAgentLogStore
from server.services.execution.roster import AgentRoster

NOW = "2026-10-26 10:00:00"


class RecordsToolsTestCase(unittest.TestCase):
    """Temp stores patched in for the singletons; execution dispatch patched out."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        base = Path(self._tmp.name) / "execution_agents"
        base.mkdir()
        self.roster_path = base / "roster.json"
        self.store = AgentRecordStore(base / "agents.json")
        self.roster = AgentRoster(self.roster_path)
        self.logs = ExecutionAgentLogStore(base)
        self.dispatch = mock.Mock(return_value=True)

        patches = [
            mock.patch.object(tools_records, "get_agent_records", return_value=self.store),
            mock.patch.object(tools_records, "get_agent_roster", return_value=self.roster),
            mock.patch.object(tools_records, "get_execution_agent_logs", return_value=self.logs),
            mock.patch.object(tools_records, "_dispatch", self.dispatch),
            mock.patch.object(tools_records, "_now", return_value=NOW),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.addCleanup(self._tmp.cleanup)

    def requests_for(self, name: str) -> list:
        return [payload for tag, _, payload in self.logs.iter_entries(name) if tag == "agent_request"]


class SendMessageToAgentTest(RecordsToolsTestCase):
    def test_unknown_id_errors_and_creates_nothing(self) -> None:
        before = ROUTING_COUNTS["unknown_agent_id"]
        result = send_message_to_agent("ag_deadbeef", "do something")
        self.assertFalse(result.success)
        self.assertEqual(
            result.payload,
            {"error": "Unknown agent_id 'ag_deadbeef'. Use an id from <active_agents>, or create_agent for new work."},
        )
        self.assertEqual(self.store.all(), [])
        self.assertEqual(json.loads(self.roster_path.read_text()), [])
        self.assertEqual(list(self.logs.list_agents()), [])
        self.dispatch.assert_not_called()
        self.assertEqual(ROUTING_COUNTS["unknown_agent_id"], before + 1)

    def test_reuse_by_id(self) -> None:
        record = self.store.create("AWS Invoice Lookup", "Finds AWS invoices.", NOW)
        result = send_message_to_agent(record.agent_id, "Was October paid?")
        self.assertTrue(result.success)
        self.assertEqual(
            result.payload,
            {
                "status": "submitted",
                "agent_id": record.agent_id,
                "agent_name": "AWS Invoice Lookup",
                "new_agent_created": False,
            },
        )
        self.dispatch.assert_called_once_with(record.agent_id, "AWS Invoice Lookup", "Was October paid?")
        self.assertEqual(self.requests_for("AWS Invoice Lookup"), ["Was October paid?"])
        updated = self.store.get(record.agent_id)
        self.assertEqual(updated.task_count, 1)
        self.assertEqual(updated.recent_work[-1].instructions, "Was October paid?")

    def test_name_passed_as_id_resolves(self) -> None:
        record = self.store.create("Email Keith", "Emails with Keith.", NOW)
        before = ROUTING_COUNTS["resolved_by_name"]
        result = send_message_to_agent("email keith", "Reply to Keith")
        self.assertTrue(result.success)
        self.assertEqual(result.payload["agent_id"], record.agent_id)
        self.assertEqual(ROUTING_COUNTS["resolved_by_name"], before + 1)
        self.dispatch.assert_called_once_with(record.agent_id, "Email Keith", "Reply to Keith")


class CreateAgentTest(RecordsToolsTestCase):
    def test_create_adds_record_roster_and_log(self) -> None:
        result = create_agent("Vercel Job Offer", "Tracks the Vercel offer thread with the recruiter.", "Find the offer email")
        self.assertTrue(result.success)
        agent_id = result.payload["agent_id"]
        self.assertEqual(
            result.payload,
            {"status": "submitted", "agent_id": agent_id, "agent_name": "Vercel Job Offer", "new_agent_created": True},
        )
        record = self.store.get(agent_id)
        self.assertEqual(record.purpose, "Tracks the Vercel offer thread with the recruiter.")
        self.assertEqual(record.purpose_source, "create")
        self.assertEqual(record.task_count, 1)
        self.assertEqual(json.loads(self.roster_path.read_text()), ["Vercel Job Offer"])
        self.assertEqual(self.requests_for("Vercel Job Offer"), ["Find the offer email"])
        self.dispatch.assert_called_once_with(agent_id, "Vercel Job Offer", "Find the offer email")

    def test_collision_errors_with_existing_id(self) -> None:
        existing = self.store.create("Email Keith", "Emails with Keith.", NOW)
        before = ROUTING_COUNTS["rejected_create"]
        result = create_agent("email-keith", "Duplicate", "Reply to Keith")
        self.assertFalse(result.success)
        self.assertEqual(result.payload["existing_agent_id"], existing.agent_id)
        self.assertEqual(
            result.payload["error"],
            f"An agent named 'Email Keith' (id {existing.agent_id}) already exists. "
            "Use send_message_to_agent with that id, or choose a different name.",
        )
        self.assertEqual(len(self.store.all()), 1)
        self.assertEqual(json.loads(self.roster_path.read_text()), [])
        self.dispatch.assert_not_called()
        self.assertEqual(ROUTING_COUNTS["rejected_create"], before + 1)

    def test_collision_with_alias(self) -> None:
        existing = self.store.create("Email Keith", "", NOW)
        self.store.add_alias(existing.agent_id, "Keith Thread")
        result = create_agent("keith thread", "x", "y")
        self.assertEqual(result.payload["existing_agent_id"], existing.agent_id)

    def test_empty_purpose_falls_back_to_instructions(self) -> None:
        before = ROUTING_COUNTS["purpose_fallback"]
        instructions = "Find the latest invoice from AWS " + "and summarize it " * 20
        result = create_agent("AWS Invoices", "   ", instructions)
        self.assertTrue(result.success)
        record = self.store.get(result.payload["agent_id"])
        self.assertEqual(record.purpose_source, "instructions_fallback")
        self.assertTrue(record.purpose.startswith("Find the latest invoice from AWS"))
        self.assertLessEqual(len(record.purpose), 200)
        self.assertEqual(ROUTING_COUNTS["purpose_fallback"], before + 1)

    def test_empty_name_errors(self) -> None:
        result = create_agent("  ", "purpose", "instructions")
        self.assertFalse(result.success)
        self.assertEqual(self.store.all(), [])
        self.dispatch.assert_not_called()

    def test_long_name_is_cut_to_60(self) -> None:
        result = create_agent("N" * 80, "purpose", "instructions")
        self.assertEqual(result.payload["agent_name"], "N" * 60)


class HandleRecordsToolCallTest(RecordsToolsTestCase):
    def test_json_string_arguments(self) -> None:
        result = handle_records_tool_call(
            "create_agent", json.dumps({"name": "Flights", "purpose": "Books flights.", "instructions": "Find SFO-JFK"})
        )
        self.assertTrue(result.success)

    def test_missing_arguments(self) -> None:
        result = handle_records_tool_call("create_agent", {"name": "Flights"})
        self.assertFalse(result.success)
        self.assertIn("Missing required arguments", result.payload["error"])

    def test_legacy_agent_name_argument_is_rejected(self) -> None:
        result = handle_records_tool_call("send_message_to_agent", {"agent_name": "x", "instructions": "y"})
        self.assertFalse(result.success)
        self.dispatch.assert_not_called()

    def test_unknown_tool(self) -> None:
        result = handle_records_tool_call("reacttomessage", {})
        self.assertEqual(result.payload, {"error": "Unknown tool: reacttomessage"})

    def test_shared_tools_delegate_to_legacy_functions(self) -> None:
        self.assertIs(tools_records.wait, tools.wait)
        self.assertIs(tools_records.send_message_to_user, tools.send_message_to_user)
        self.assertIs(tools_records.send_draft, tools.send_draft)
        sentinel = tools.ToolResult(success=True, payload={"status": "waiting"})
        with mock.patch.object(tools_records, "wait", return_value=sentinel) as wait:
            self.assertIs(handle_records_tool_call("wait", {"reason": "dup"}), sentinel)
        wait.assert_called_once_with(reason="dup")


class SchemasTest(unittest.TestCase):
    def test_tool_list(self) -> None:
        names = [s["function"]["name"] for s in RECORDS_TOOL_SCHEMAS]
        self.assertEqual(names, ["send_message_to_agent", "create_agent", "send_message_to_user", "send_draft", "wait"])

    def test_shared_schemas_are_the_legacy_ones(self) -> None:
        legacy = {s["function"]["name"]: s for s in tools.TOOL_SCHEMAS}
        for schema in RECORDS_TOOL_SCHEMAS[2:]:
            self.assertIs(schema, legacy[schema["function"]["name"]])

    def test_routing_schemas(self) -> None:
        send, create = RECORDS_TOOL_SCHEMAS[0]["function"], RECORDS_TOOL_SCHEMAS[1]["function"]
        self.assertEqual(send["parameters"]["required"], ["agent_id", "instructions"])
        self.assertEqual(create["parameters"]["required"], ["name", "purpose", "instructions"])
        self.assertFalse(send["parameters"]["additionalProperties"])
        self.assertFalse(create["parameters"]["additionalProperties"])


class DispatchCompletionTest(unittest.IsolatedAsyncioTestCase):
    async def test_result_is_recorded_on_the_record(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = AgentRecordStore(Path(tmp) / "agents.json")
            record = store.create("Worker", "", NOW)
            store.touch_dispatch(record.agent_id, "task", NOW)

            manager = mock.Mock()
            manager.execute_agent = mock.AsyncMock(
                return_value=ExecutionResult(agent_name="Worker", success=True, response="All done.")
            )
            with mock.patch.object(tools_records, "_EXECUTION_BATCH_MANAGER", manager), mock.patch.object(
                tools_records, "get_agent_records", return_value=store
            ):
                self.assertTrue(tools_records._dispatch(record.agent_id, "Worker", "task"))
                pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
                await asyncio.gather(*pending)

            manager.execute_agent.assert_awaited_once_with("Worker", "task")
            self.assertEqual(store.get(record.agent_id).recent_work[-1].result, "All done.")

    def test_no_event_loop_returns_false(self) -> None:
        self.assertFalse(tools_records._dispatch("ag_x", "Worker", "task"))


if __name__ == "__main__":
    unittest.main()
