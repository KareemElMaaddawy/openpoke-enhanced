"""Retrieval text and prompt entry rendering for agent records."""

import unittest

from server.services.agents.records import AgentRecord, WorkSnippet
from server.services.agents.text import render_agent_entry, retrieval_text


def _record(**overrides) -> AgentRecord:
    fields = dict(
        agent_id="ag_1f3a9c2e",
        name="AWS Invoice Lookup",
        slug="aws-invoice-lookup",
        purpose="Finds the user's AWS invoices and answers billing questions about them.",
        recent_work=[
            WorkSnippet("Find the September invoice", "Found: $40.", "2026-10-01 09:00:00"),
            WorkSnippet("Check whether the October invoice was paid", "No payment recorded yet.", "2026-10-20 14:03:00"),
        ],
        created_at="2026-10-01 09:00:00",
        last_active="2026-10-20 14:03:00",
        task_count=3,
    )
    fields.update(overrides)
    return AgentRecord(**fields)


class RetrievalTextTest(unittest.TestCase):
    def test_name_purpose_then_snippets_newest_first(self) -> None:
        self.assertEqual(
            retrieval_text(_record()),
            "AWS Invoice Lookup\n"
            "Finds the user's AWS invoices and answers billing questions about them.\n"
            "Check whether the October invoice was paid → No payment recorded yet.\n"
            "Find the September invoice → Found: $40.",
        )

    def test_empty_purpose_and_open_snippet(self) -> None:
        record = _record(purpose="", recent_work=[WorkSnippet("Pending task", "", "2026-10-01 09:00:00")])
        self.assertEqual(retrieval_text(record), "AWS Invoice Lookup\nPending task")

    def test_capped_at_1500_chars(self) -> None:
        record = _record(purpose="p" * 2000)
        self.assertEqual(len(retrieval_text(record)), 1500)


class RenderAgentEntryTest(unittest.TestCase):
    def test_spec_example(self) -> None:
        self.assertEqual(
            render_agent_entry(_record()),
            '<agent id="ag_1f3a9c2e" name="AWS Invoice Lookup" last_active="2026-10-20" tasks="3">\n'
            "<purpose>Finds the user&#x27;s AWS invoices and answers billing questions about them.</purpose>\n"
            "<recent>Check whether the October invoice was paid → No payment recorded yet.</recent>\n"
            "</agent>",
        )

    def test_escaping(self) -> None:
        record = _record(
            name='Bob "B" <Ops> & Co',
            purpose="Tracks <b>bold</b> & 'quoted' work",
            recent_work=[WorkSnippet('Say "hi" <now>', "ok & done", "2026-10-01 09:00:00")],
        )
        rendered = render_agent_entry(record)
        self.assertIn('name="Bob &quot;B&quot; &lt;Ops&gt; &amp; Co"', rendered)
        self.assertIn("<purpose>Tracks &lt;b&gt;bold&lt;/b&gt; &amp; &#x27;quoted&#x27; work</purpose>", rendered)
        self.assertIn("<recent>Say &quot;hi&quot; &lt;now&gt; → ok &amp; done</recent>", rendered)

    def test_omits_empty_purpose_and_work(self) -> None:
        rendered = render_agent_entry(_record(purpose="", recent_work=[], task_count=0))
        self.assertEqual(
            rendered,
            '<agent id="ag_1f3a9c2e" name="AWS Invoice Lookup" last_active="2026-10-20" tasks="0">\n</agent>',
        )

    def test_omits_unknown_last_active(self) -> None:
        rendered = render_agent_entry(_record(last_active=""))
        self.assertTrue(rendered.startswith('<agent id="ag_1f3a9c2e" name="AWS Invoice Lookup" tasks="3">'))

    def test_render_recent_count(self) -> None:
        self.assertEqual(render_agent_entry(_record(), render_recent=2).count("<recent>"), 2)
        self.assertEqual(render_agent_entry(_record(), render_recent=0).count("<recent>"), 0)


if __name__ == "__main__":
    unittest.main()
