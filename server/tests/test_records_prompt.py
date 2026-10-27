"""Records-mode system prompt and message builder."""

import unittest

from server.agents.interaction_agent.agent import (
    _render_conversation_history,
    _render_current_turn,
)
from server.agents.interaction_agent.records_prompt import (
    RECORDS_PROMPT_PATH,
    build_records_system_prompt,
    prepare_records_messages,
)
from server.services.agents.records import WorkSnippet
from server.services.agents.text import render_agent_entry
from server.services.routing.candidates import RecordView

LEGACY_PROMPT_PATH = RECORDS_PROMPT_PATH.with_name("system_prompt.md")
START, END = "<!-- routing:start -->\n", "\n<!-- routing:end -->"


class PromptDriftTest(unittest.TestCase):
    def test_text_outside_markers_equals_system_prompt(self) -> None:
        records = RECORDS_PROMPT_PATH.read_text(encoding="utf-8")
        legacy = LEGACY_PROMPT_PATH.read_text(encoding="utf-8")
        self.assertEqual(records.count(START), 1)
        self.assertEqual(records.count(END), 1)

        before, rest = records.split(START)
        _, after = rest.split(END)
        self.assertTrue(legacy.startswith(before), "text before the routing markers drifted")
        self.assertTrue(legacy.endswith(after), "text after the routing markers drifted")
        replaced = legacy[len(before): len(legacy) - len(after)]
        self.assertTrue(replaced.startswith("Send Message to Agent Tool Usage\n"))
        self.assertNotIn("Send Message to User Tool Usage", replaced)

    def test_markers_are_not_sent_to_the_model(self) -> None:
        prompt = build_records_system_prompt()
        self.assertNotIn("routing:start", prompt)
        self.assertNotIn("routing:end", prompt)
        self.assertIn("TOOLS\n\nSend Message to Agent and Create Agent Tool Usage\n\n", prompt)
        self.assertIn("**before** calling these tools.\n\nSend Message to User Tool Usage", prompt)


class PrepareRecordsMessagesTest(unittest.TestCase):
    def test_structure_matches_legacy_sections(self) -> None:
        transcript = '<user_message timestamp="2026-10-26 09:00:00">find my aws invoice</user_message>'
        entry = render_agent_entry(
            RecordView(
                agent_id="ag_1f3a9c2e",
                name="AWS Invoice Lookup",
                purpose="Finds AWS invoices.",
                recent_work=(WorkSnippet("Find it", "Found.", "2026-10-26 09:00:01"),),
                last_active="2026-10-26 09:00:01",
                task_count=1,
            )
        )
        messages = prepare_records_messages("was it paid?", transcript, "user", entry, shown=1, total=40)
        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["role"], "user")
        self.assertEqual(
            messages[0]["content"],
            "\n\n".join(
                [
                    _render_conversation_history(transcript),
                    f'<active_agents shown="1" total="40">\n{entry}\n</active_agents>',
                    _render_current_turn("was it paid?", "user"),
                ]
            ),
        )

    def test_agent_message_turn(self) -> None:
        content = prepare_records_messages("[SUCCESS] X: done", "", "agent", None, 0, 0)[0]["content"]
        self.assertTrue(content.startswith("<conversation_history>\nNone\n</conversation_history>"))
        self.assertTrue(content.endswith("<new_agent_message>\n[SUCCESS] X: done\n</new_agent_message>"))

    def test_empty_roster_renders_none(self) -> None:
        content = prepare_records_messages("hi", "", "user", None, 0, 0)[0]["content"]
        self.assertIn('<active_agents shown="0" total="0">\nNone\n</active_agents>', content)
        content = prepare_records_messages("hi", "", "user", "", 0, 0)[0]["content"]
        self.assertIn('<active_agents shown="0" total="0">\nNone\n</active_agents>', content)


if __name__ == "__main__":
    unittest.main()
