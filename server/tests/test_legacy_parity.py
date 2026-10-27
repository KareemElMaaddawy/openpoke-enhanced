"""Legacy mode must stay byte-identical to the code on main."""

import hashlib
import json
import unittest
from pathlib import Path
from unittest import mock

from server.agents.interaction_agent import routing as routing_module
from server.agents.interaction_agent.agent import (
    SYSTEM_PROMPT,
    build_system_prompt,
    prepare_message_with_history,
)
from server.agents.interaction_agent.routing import LegacyRouting
from server.agents.interaction_agent.runtime import InteractionAgentRuntime
from server.agents.interaction_agent.tools import TOOL_SCHEMAS, ToolResult, get_tool_schemas
from server.tests.runtime_helpers import TempServerState, assistant_reply, make_settings

# Recorded from main (187633a) before any records-mode code was added.
LEGACY_SYSTEM_PROMPT_SHA256 = "d8257b89da9fcb47eaf980b1f9a097c8e147c45196e569e13303c04ec9a1da37"
LEGACY_TOOL_SCHEMAS_SHA256 = "3d957311ef46de6c7f5f2fc8eb173c4c213e7d45330c5ddf90f39a720b20b5bc"

_PROMPT_PATH = Path(__file__).resolve().parent.parent / "agents" / "interaction_agent" / "system_prompt.md"


class LegacyHashesTest(unittest.TestCase):
    def test_system_prompt_file_unchanged(self) -> None:
        digest = hashlib.sha256(_PROMPT_PATH.read_bytes()).hexdigest()
        self.assertEqual(digest, LEGACY_SYSTEM_PROMPT_SHA256)

    def test_tool_schemas_unchanged(self) -> None:
        encoded = json.dumps(TOOL_SCHEMAS, sort_keys=True).encode("utf-8")
        self.assertEqual(hashlib.sha256(encoded).hexdigest(), LEGACY_TOOL_SCHEMAS_SHA256)


class LegacyRuntimeParityTest(unittest.IsolatedAsyncioTestCase):
    """With routing_mode="legacy" the runtime sends exactly what the module functions build."""

    def setUp(self) -> None:
        self.state = TempServerState(make_settings(routing_mode="legacy")).start()
        self.addCleanup(self.state.stop)
        for name in ["Email Keith", "AWS Invoice Lookup", 'Quote "Agent" <x>']:
            self.state.roster.add_agent(name)
        self.state.conversation.record_user_message("find the aws invoice")
        self.state.conversation.record_agent_message("[SUCCESS] AWS Invoice Lookup: Found it.")
        self.state.conversation.record_reply("Found it: $42.")

    def _runtime(self, replies):
        runtime = InteractionAgentRuntime()
        calls = []

        async def fake_llm_call(system_prompt, messages):
            calls.append((system_prompt, json.loads(json.dumps(messages))))
            return replies.pop(0)

        runtime._make_llm_call = fake_llm_call
        return runtime, calls

    def test_strategy_and_schemas(self) -> None:
        runtime = InteractionAgentRuntime()
        self.assertIsInstance(runtime.routing, LegacyRouting)
        self.assertIs(runtime.tool_schemas, TOOL_SCHEMAS)
        self.assertIs(runtime.tool_schemas, get_tool_schemas())
        self.assertEqual(runtime.routing.build_system_prompt(), build_system_prompt())
        self.assertEqual(runtime.routing.build_system_prompt(), SYSTEM_PROMPT)

    async def test_user_turn_sends_legacy_prompt_and_messages(self) -> None:
        transcript = self.state.conversation.load_transcript()
        self.state.settings.conversation_summary_threshold = 0  # transcript from the conversation log
        expected = prepare_message_with_history("was it paid?", transcript, message_type="user")

        runtime, calls = self._runtime([assistant_reply("Checking.")])
        result = await runtime.execute("was it paid?")

        self.assertTrue(result.success)
        system_prompt, messages = calls[0]
        self.assertEqual(system_prompt, build_system_prompt())
        self.assertEqual(messages, expected)
        self.assertIn('<agent name="Quote &quot;Agent&quot; &lt;x&gt;" />', messages[0]["content"])

    async def test_agent_turn_with_working_memory_transcript(self) -> None:
        transcript = self.state.working_memory.render_transcript()
        self.assertTrue(transcript.strip())
        expected = prepare_message_with_history("[SUCCESS] Email Keith: Sent.", transcript, message_type="agent")

        runtime, calls = self._runtime([assistant_reply("Done.")])
        result = await runtime.handle_agent_message("[SUCCESS] Email Keith: Sent.")

        self.assertTrue(result.success)
        self.assertEqual(calls[0], (build_system_prompt(), expected))

    async def test_tool_calls_go_to_legacy_handler(self) -> None:
        runtime = InteractionAgentRuntime()
        sentinel = ToolResult(success=True, payload={"status": "submitted"})
        with mock.patch.object(routing_module, "handle_tool_call", return_value=sentinel) as handler:
            from server.agents.interaction_agent.runtime import _ToolCall

            result = runtime._execute_tool(
                _ToolCall("call_1", "send_message_to_agent", {"agent_name": "X", "instructions": "Y"})
            )
        self.assertIs(result, sentinel)
        handler.assert_called_once_with("send_message_to_agent", {"agent_name": "X", "instructions": "Y"})

    def test_legacy_never_touches_records_files(self) -> None:
        InteractionAgentRuntime()
        self.assertFalse((self.state.base / "execution_agents" / "agents.json").exists())
        self.assertFalse((self.state.base / "execution_agents" / "embeddings.json").exists())


if __name__ == "__main__":
    unittest.main()
