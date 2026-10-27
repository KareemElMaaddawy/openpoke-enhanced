"""Agent record store and import from the legacy roster."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from server.services.agents import records as records_module
from server.services.agents.records import (
    AgentRecordStore,
    SlugCollision,
    reconcile_from_roster,
    truncate_text,
)
from server.services.execution.log_store import ExecutionAgentLogStore
from server.services.execution.roster import AgentRoster

NOW = "2026-10-26 10:00:00"


class TempDirTestCase(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()


class TruncateTextTest(unittest.TestCase):
    def test_short_text_is_unchanged_but_whitespace_collapsed(self) -> None:
        self.assertEqual(truncate_text("  find   the\ninvoice ", 200), "find the invoice")

    def test_long_text_cut_at_word_boundary(self) -> None:
        text = "alpha beta gamma delta epsilon"
        out = truncate_text(text, 14)
        self.assertEqual(out, "alpha beta…")
        self.assertLessEqual(len(out), 14)

    def test_single_long_word_is_hard_cut(self) -> None:
        out = truncate_text("x" * 50, 10)
        self.assertEqual(out, "x" * 9 + "…")


class AgentRecordStoreTest(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.path = self.dir / "agents.json"
        self.store = AgentRecordStore(self.path)

    def test_missing_file_reads_empty_and_writes_nothing(self) -> None:
        self.assertEqual(self.store.all(), [])
        self.assertIsNone(self.store.get("ag_missing"))
        self.assertFalse(self.path.exists())

    def test_create_persists_record(self) -> None:
        record = self.store.create("AWS Invoice Lookup", "Finds AWS invoices.", NOW)
        self.assertRegex(record.agent_id, r"^ag_[0-9a-f]{8}$")
        self.assertEqual(record.slug, "aws-invoice-lookup")
        self.assertEqual(record.created_at, NOW)
        self.assertEqual(record.last_active, NOW)
        self.assertEqual(record.task_count, 0)
        self.assertEqual(record.status, "active")
        self.assertEqual(record.purpose_source, "create")

        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["version"], 1)
        self.assertEqual([r["agent_id"] for r in data["records"]], [record.agent_id])

        reloaded = AgentRecordStore(self.path)
        self.assertEqual(reloaded.get(record.agent_id), record)

    def test_create_truncates_purpose(self) -> None:
        record = self.store.create("Long", "word " * 100, NOW)
        self.assertLessEqual(len(record.purpose), 200)
        self.assertTrue(record.purpose.endswith("…"))

    def test_slug_collision_raises_with_existing(self) -> None:
        first = self.store.create("Email Keith", "Emails with Keith.", NOW)
        with self.assertRaises(SlugCollision) as ctx:
            self.store.create("email-keith", "Duplicate.", NOW)
        self.assertEqual(ctx.exception.existing.agent_id, first.agent_id)
        self.assertEqual(len(self.store.all()), 1)

    def test_alias_lookup_and_collision(self) -> None:
        record = self.store.create("Email Keith", "", NOW)
        self.store.add_alias(record.agent_id, "Keith Mail")
        self.assertEqual(self.store.find_by_name_or_slug("Keith Mail").agent_id, record.agent_id)
        with self.assertRaises(SlugCollision):
            self.store.create("keith mail", "", NOW)

    def test_find_prefers_exact_name_then_alias_then_slug(self) -> None:
        a = self.store.create("Email Keith", "", NOW)
        b = self.store.create("Keith Notes", "", NOW)
        self.store.add_alias(b.agent_id, "Email  Keith!")  # same slug as a, but an exact alias of b
        self.assertEqual(self.store.find_by_name_or_slug("Email Keith").agent_id, a.agent_id)
        self.assertEqual(self.store.find_by_name_or_slug("Email  Keith!").agent_id, b.agent_id)
        self.assertEqual(self.store.find_by_name_or_slug("EMAIL keith").agent_id, a.agent_id)
        self.assertIsNone(self.store.find_by_name_or_slug("Somebody Else"))
        self.assertIsNone(self.store.find_by_name_or_slug(""))

    def test_touch_dispatch_keeps_last_three_snippets(self) -> None:
        record = self.store.create("Worker", "", NOW)
        for i in range(4):
            self.store.touch_dispatch(record.agent_id, f"task {i}", f"2026-10-2{i} 09:00:00")
        updated = self.store.get(record.agent_id)
        self.assertEqual(updated.task_count, 4)
        self.assertEqual(updated.last_active, "2026-10-23 09:00:00")
        self.assertEqual([w.instructions for w in updated.recent_work], ["task 1", "task 2", "task 3"])
        self.assertEqual(updated.recent_work[-1].at, "2026-10-23 09:00:00")
        self.assertTrue(all(w.result == "" for w in updated.recent_work))

    def test_touch_dispatch_truncates_instructions(self) -> None:
        record = self.store.create("Worker", "", NOW)
        self.store.touch_dispatch(record.agent_id, "word " * 100, NOW)
        snippet = self.store.get(record.agent_id).recent_work[0]
        self.assertLessEqual(len(snippet.instructions), 200)
        self.assertTrue(snippet.instructions.endswith("…"))

    def test_record_result_fills_newest_open_snippet(self) -> None:
        record = self.store.create("Worker", "", NOW)
        self.store.touch_dispatch(record.agent_id, "first", NOW)
        self.store.record_result(record.agent_id, "first done")
        self.store.touch_dispatch(record.agent_id, "second", NOW)
        self.store.touch_dispatch(record.agent_id, "third", NOW)
        self.store.record_result(record.agent_id, "x" * 300)
        work = self.store.get(record.agent_id).recent_work
        self.assertEqual(work[0].result, "first done")
        self.assertEqual(work[1].result, "")
        self.assertLessEqual(len(work[2].result), 150)
        self.store.record_result(record.agent_id, "second done")
        self.assertEqual(self.store.get(record.agent_id).recent_work[1].result, "second done")

    def test_returned_records_are_copies(self) -> None:
        record = self.store.create("Worker", "", NOW)
        record.name = "Mutated"
        self.store.all()[0].recent_work.append(None)
        stored = self.store.get(record.agent_id)
        self.assertEqual(stored.name, "Worker")
        self.assertEqual(stored.recent_work, [])

    def test_write_is_atomic(self) -> None:
        record = self.store.create("Worker", "", NOW)
        before = self.path.read_text(encoding="utf-8")
        with mock.patch.object(records_module.os, "replace", side_effect=OSError("disk full")):
            with self.assertRaises(OSError):
                self.store.touch_dispatch(record.agent_id, "task", NOW)
        self.assertEqual(self.path.read_text(encoding="utf-8"), before)
        self.assertEqual(json.loads(before)["records"][0]["task_count"], 0)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["agents.json", "agents.json.tmp"])
        self.store.touch_dispatch(record.agent_id, "task", NOW)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()), ["agents.json"])

    def test_unknown_keys_from_a_newer_version_are_ignored(self) -> None:
        record = self.store.create("Worker", "", NOW)
        data = json.loads(self.path.read_text(encoding="utf-8"))
        data["records"][0]["last_run"] = NOW
        self.path.write_text(json.dumps(data), encoding="utf-8")
        self.assertEqual(AgentRecordStore(self.path).get(record.agent_id), record)

    def test_clear(self) -> None:
        self.store.create("Worker", "", NOW)
        self.store.clear()
        self.assertFalse(self.path.exists())
        self.assertEqual(self.store.all(), [])
        self.assertEqual(AgentRecordStore(self.path).all(), [])


def _write_log(log_dir: Path, slug: str, entries: list[tuple[str, str, str]]) -> None:
    lines = [f'<{tag} timestamp="{ts}">{payload}</{tag}>' for tag, ts, payload in entries]
    (log_dir / f"{slug}.log").write_text("\n".join(lines) + "\n", encoding="utf-8")


class ReconcileFromRosterTest(TempDirTestCase):
    def setUp(self) -> None:
        super().setUp()
        self.log_dir = self.dir / "execution_agents"
        self.log_dir.mkdir()
        roster_path = self.log_dir / "roster.json"
        roster_path.write_text(
            json.dumps(["Email Keith", "AWS Invoice Lookup", "email-keith", "No Log Agent"]),
            encoding="utf-8",
        )
        self.roster = AgentRoster(roster_path)
        self.logs = ExecutionAgentLogStore(self.log_dir)
        self.store = AgentRecordStore(self.log_dir / "agents.json")

        _write_log(
            self.log_dir,
            "email-keith",
            [
                ("agent_request", "2026-10-01 09:00:00", "Find the latest email from Keith"),
                ("agent_action", "2026-10-01 09:00:05", "Calling gmail_fetch_emails"),
                ("agent_response", "2026-10-01 09:00:10", "Keith asked about the Q3 report."),
                ("agent_response", "2026-10-02 08:00:00", "Trigger run output"),
                ("agent_request", "2026-10-03 09:00:00", "Draft a reply to Keith"),
                ("agent_request", "2026-10-03 09:00:01", "Also check Keith's calendar invite"),
                ("agent_response", "2026-10-03 09:00:20", "Draft ready."),
                ("agent_response", "2026-10-03 09:00:30", "Invite accepted."),
                ("agent_request", "2026-10-04 10:00:00", "Send the reply"),
            ],
        )
        _write_log(
            self.log_dir,
            "aws-invoice-lookup",
            [
                ("agent_request", "2026-09-15 12:00:00", "Find the October AWS invoice"),
                ("agent_response", "2026-09-15 12:00:30", "Invoice found: $42."),
            ],
        )

    def test_import_builds_records_and_aliases(self) -> None:
        counts = reconcile_from_roster(self.store, self.roster, self.logs, now=NOW)
        self.assertEqual(counts, {"created": 3, "aliased": 1, "total": 3})

        records = self.store.all()
        self.assertEqual([r.name for r in records], ["Email Keith", "AWS Invoice Lookup", "No Log Agent"])

        keith = records[0]
        self.assertEqual(keith.aliases, ["email-keith"])
        self.assertEqual(keith.purpose, "")
        self.assertEqual(keith.purpose_source, "import")
        self.assertEqual(keith.created_at, "2026-10-01 09:00:00")
        self.assertEqual(keith.last_active, "2026-10-04 10:00:00")
        self.assertEqual(keith.task_count, 4)
        self.assertEqual(
            [(w.instructions, w.result, w.at) for w in keith.recent_work],
            [
                ("Draft a reply to Keith", "Draft ready.", "2026-10-03 09:00:00"),
                ("Also check Keith's calendar invite", "Invite accepted.", "2026-10-03 09:00:01"),
                ("Send the reply", "", "2026-10-04 10:00:00"),
            ],
        )

        aws = records[1]
        self.assertEqual(aws.task_count, 1)
        self.assertEqual(aws.recent_work[0].result, "Invoice found: $42.")

        no_log = records[2]
        self.assertEqual((no_log.created_at, no_log.last_active), (NOW, NOW))
        self.assertEqual((no_log.task_count, no_log.recent_work), (0, []))

    def test_import_is_idempotent(self) -> None:
        reconcile_from_roster(self.store, self.roster, self.logs, now=NOW)
        ids = [r.agent_id for r in self.store.all()]
        counts = reconcile_from_roster(self.store, self.roster, self.logs, now=NOW)
        self.assertEqual(counts, {"created": 0, "aliased": 0, "total": 3})
        self.assertEqual([r.agent_id for r in self.store.all()], ids)

    def test_import_picks_up_names_added_later(self) -> None:
        reconcile_from_roster(self.store, self.roster, self.logs, now=NOW)
        self.roster.add_agent("Later Legacy Agent")
        counts = reconcile_from_roster(self.store, self.roster, self.logs, now=NOW)
        self.assertEqual(counts["created"], 1)
        self.assertIsNotNone(self.store.find_by_name_or_slug("Later Legacy Agent"))


if __name__ == "__main__":
    unittest.main()
