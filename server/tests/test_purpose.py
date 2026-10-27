"""Purpose backfill prompt shared by the eval harness and production."""

import unittest

from server.services.agents.purpose import (
    PURPOSE_SYSTEM_PROMPT,
    clean_purpose,
    purpose_cache_key,
    purpose_request,
)


class PurposeTest(unittest.TestCase):
    def test_request(self) -> None:
        system, messages = purpose_request("AWS Invoice Lookup", "Find the October invoice")
        self.assertEqual(system, PURPOSE_SYSTEM_PROMPT)
        self.assertEqual(messages, [{"role": "user", "content": "Name: AWS Invoice Lookup\nFirst task: Find the October invoice"}])

    def test_cache_key_depends_on_name_and_task(self) -> None:
        key = purpose_cache_key("A", "task")
        self.assertEqual(key, purpose_cache_key("A", "task"))
        self.assertNotEqual(key, purpose_cache_key("B", "task"))
        self.assertNotEqual(key, purpose_cache_key("A", "other task"))

    def test_clean(self) -> None:
        self.assertEqual(clean_purpose('  "Finds AWS invoices."  '), "Finds AWS invoices.")
        self.assertLessEqual(len(clean_purpose("word " * 100)), 200)
        self.assertEqual(clean_purpose(""), "")


if __name__ == "__main__":
    unittest.main()
